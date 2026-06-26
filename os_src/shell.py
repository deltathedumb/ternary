"""
Ternary OS interactive shell.  load-addr=10000, frame-addr=15000, --lib.

RAM layout:
  5000..5063  command buffer (64 chars, null-terminated)
  5500        current working dir sector (0 = root)
  5501..5506  current dir name (6 chars, unused for root)
  5507        next free user sector (bump allocator, set at startup)
  6000..6080  current dir sector buffer (81 cells)
  6090..6095  name scratch for copy_name
  7000..      file I/O / subdir scan buffer

Directory entry format (8 cells each):
  cells[0..5]  name (6 ASCII chars, null-padded)
  cells[6]     start sector
  cells[7]     size in sectors (files > 0; directories = -1)

Constraints: no BoolOp, no semicolons, max 4 function args.
"""

# ── Intrinsics ────────────────────────────────────────────────────────────────

def mem_load(addr: int) -> int:
    return 0

def mem_store(addr: int, value: int) -> int:
    return 0

def print_char(ch: int) -> int:
    return 0

def read_char() -> int:
    return 0

def diskread(buf: int, sector: int) -> int:
    return 0

def diskwrite(buf: int, sector: int) -> int:
    return 0


# ── Integer output ────────────────────────────────────────────────────────────

def _print_digits(n: int) -> int:
    if n == 0:
        return 0
    _print_digits(n // 10)
    print_char(n % 10 + 48)
    return 0

def print_int(n: int) -> int:
    if n == 0:
        print_char(48)
        return 0
    if n < 0:
        print_char(45)
        n = 0 - n
    _print_digits(n)
    return 0


# ── Line input ────────────────────────────────────────────────────────────────

def read_line() -> int:
    i = 0
    done = 0
    while done == 0:
        ch = read_char()
        if ch == 13:
            done = 1
        else:
            if ch == 10:
                done = 1
            else:
                is_bs = 0
                if ch == 8:
                    is_bs = 1
                if ch == 127:
                    is_bs = 1
                if is_bs == 1:
                    if i > 0:
                        i = i - 1
                        print_char(8)
                        print_char(32)
                        print_char(8)
                else:
                    if i < 63:
                        mem_store(5000 + i, ch)
                        print_char(ch)
                        i = i + 1
    print_char(10)
    mem_store(5000 + i, 0)
    return i


# ── Argument parsing ──────────────────────────────────────────────────────────

def skip_word(i: int) -> int:
    ch = mem_load(5000 + i)
    while ch > 32:
        i = i + 1
        ch = mem_load(5000 + i)
    return i

def skip_spaces(i: int) -> int:
    ch = mem_load(5000 + i)
    while ch == 32:
        i = i + 1
        ch = mem_load(5000 + i)
    return i

def parse_num(i: int) -> int:
    n = 0
    ch = mem_load(5000 + i)
    while ch >= 48:
        if ch > 57:
            return n
        n = n * 10 + ch - 48
        i = i + 1
        ch = mem_load(5000 + i)
    return n

def arg_start() -> int:
    i = skip_word(0)
    return skip_spaces(i)

def arg_int() -> int:
    i = arg_start()
    return parse_num(i)

def next_arg(i: int) -> int:
    j = skip_word(i)
    return skip_spaces(j)


# ── Command name matching ─────────────────────────────────────────────────────

def buf_eq2(a: int, b: int) -> int:
    if mem_load(5000) != a:
        return 0
    if mem_load(5001) != b:
        return 0
    if mem_load(5002) > 32:
        return 0
    return 1

def buf_eq3(a: int, b: int, c: int) -> int:
    if mem_load(5000) != a:
        return 0
    if mem_load(5001) != b:
        return 0
    if mem_load(5002) != c:
        return 0
    if mem_load(5003) > 32:
        return 0
    return 1

def buf_eq4(a: int, b: int, c: int, d: int) -> int:
    if mem_load(5000) != a:
        return 0
    if mem_load(5001) != b:
        return 0
    if mem_load(5002) != c:
        return 0
    if mem_load(5003) != d:
        return 0
    if mem_load(5004) > 32:
        return 0
    return 1

def buf_eq5(a: int, b: int, c: int, d: int) -> int:
    if mem_load(5000) != a:
        return 0
    if mem_load(5001) != b:
        return 0
    if mem_load(5002) != c:
        return 0
    if mem_load(5003) != d:
        return 0
    return 1


# ── Sector allocator ─────────────────────────────────────────────────────────

def alloc_sector() -> int:
    """Bump-allocate one disk sector. Initialised by init_free_ptr at boot."""
    sec = mem_load(5507)
    mem_store(5507, sec + 1)
    return sec


# ── Filesystem helpers ────────────────────────────────────────────────────────

def copy_name(src: int) -> int:
    """Copy up to 6-char word from cmd buf[src..] to RAM[6090..6095].
    Returns index of first char after the name."""
    i = src
    j = 0
    ch = mem_load(5000 + i)
    while ch > 32:
        if j < 6:
            mem_store(6090 + j, ch)
            j = j + 1
        i = i + 1
        ch = mem_load(5000 + i)
    while j < 6:
        mem_store(6090 + j, 0)
        j = j + 1
    return i

def names_match(a: int, b: int) -> int:
    i = 0
    while i < 6:
        if mem_load(a + i) != mem_load(b + i):
            return 0
        i = i + 1
    return 1

def find_in_dir() -> int:
    """Scan loaded dir at RAM[6000] for name at RAM[6090]. Return entry base or 0."""
    e = 0
    while e < 10:
        base = 6000 + e * 8
        if mem_load(base) > 0:
            if names_match(base, 6090) == 1:
                return base
        e = e + 1
    return 0

def find_free_entry() -> int:
    e = 0
    while e < 10:
        base = 6000 + e * 8
        if mem_load(base) == 0:
            return base
        e = e + 1
    return 0

def write_dir_entry(entry_base: int, start_sec: int, size: int) -> int:
    i = 0
    while i < 6:
        mem_store(entry_base + i, mem_load(6090 + i))
        i = i + 1
    mem_store(entry_base + 6, start_sec)
    mem_store(entry_base + 7, size)
    return 0

def print_not_found() -> int:
    print_char(63)
    print_char(32)
    print_char(110)
    print_char(111)
    print_char(116)
    print_char(32)
    print_char(102)
    print_char(111)
    print_char(117)
    print_char(110)
    print_char(100)
    print_char(10)
    return 0

def print_not_dir() -> int:
    print_char(33)
    print_char(100)
    print_char(105)
    print_char(114)
    print_char(10)
    return 0

def print_is_dir() -> int:
    print_char(33)
    print_char(105)
    print_char(115)
    print_char(100)
    print_char(105)
    print_char(114)
    print_char(10)
    return 0

def print_ok() -> int:
    print_char(79)
    print_char(75)
    print_char(10)
    return 0


# ── Startup: scan all directories to find next free sector ────────────────────

def init_free_ptr() -> int:
    """Scan root dir and all subdirs, set RAM[5507] = first free sector."""
    highest = 121
    diskread(6000, 0)
    e = 0
    while e < 10:
        base = 6000 + e * 8
        if mem_load(base) > 0:
            s = mem_load(base + 6)
            sz = mem_load(base + 7)
            if sz < 0:
                if s + 1 > highest:
                    highest = s + 1
                diskread(7000, s)
                f = 0
                while f < 10:
                    fb = 7000 + f * 8
                    if mem_load(fb) > 0:
                        fs = mem_load(fb + 6)
                        fn = mem_load(fb + 7)
                        if fn > 0:
                            fend = fs + fn
                            if fend > highest:
                                highest = fend
                    f = f + 1
            else:
                if sz > 0:
                    fend = s + sz
                    if fend > highest:
                        highest = fend
        e = e + 1
    mem_store(5507, highest)
    return 0


# ── fib ──────────────────────────────────────────────────────────────────────

def fib(n: int) -> int:
    if n < 2:
        return n
    a = 0
    b = 1
    i = 2
    while i <= n:
        c = a + b
        a = b
        b = c
        i = i + 1
    return b

def cmd_fib() -> int:
    n = arg_int()
    result = fib(n)
    print_char(102)
    print_char(105)
    print_char(98)
    print_char(40)
    print_int(n)
    print_char(41)
    print_char(32)
    print_char(61)
    print_char(32)
    print_int(result)
    print_char(10)
    return 0


# ── echo ─────────────────────────────────────────────────────────────────────

def cmd_echo() -> int:
    i = arg_start()
    ch = mem_load(5000 + i)
    while ch > 0:
        print_char(ch)
        i = i + 1
        ch = mem_load(5000 + i)
    print_char(10)
    return 0


# ── clear ────────────────────────────────────────────────────────────────────

def cmd_clear() -> int:
    i = 0
    while i < 26:
        print_char(10)
        i = i + 1
    return 0


# ── mem / poke ───────────────────────────────────────────────────────────────

def cmd_mem() -> int:
    addr = arg_int()
    val = mem_load(addr)
    print_char(91)
    print_int(addr)
    print_char(93)
    print_char(32)
    print_char(61)
    print_char(32)
    print_int(val)
    print_char(10)
    return 0

def cmd_poke() -> int:
    i = arg_start()
    addr = parse_num(i)
    j = next_arg(i)
    val = parse_num(j)
    mem_store(addr, val)
    print_char(91)
    print_int(addr)
    print_char(93)
    print_char(60)
    print_char(61)
    print_int(val)
    print_char(10)
    return 0


# ── pwd ──────────────────────────────────────────────────────────────────────

def cmd_pwd() -> int:
    print_char(47)
    cwd = mem_load(5500)
    if cwd != 0:
        i = 0
        ch = mem_load(5501 + i)
        while ch > 0:
            print_char(ch)
            i = i + 1
            ch = mem_load(5501 + i)
    print_char(10)
    return 0


# ── ls ───────────────────────────────────────────────────────────────────────

def cmd_ls() -> int:
    cwd = mem_load(5500)
    diskread(6000, cwd)
    e = 0
    found = 0
    while e < 10:
        base = 6000 + e * 8
        n0 = mem_load(base)
        if n0 > 0:
            found = 1
            sz = mem_load(base + 7)
            if sz < 0:
                print_char(100)
                print_char(32)
            else:
                print_char(32)
                print_char(32)
            i = 0
            while i < 6:
                c = mem_load(base + i)
                if c > 0:
                    print_char(c)
                else:
                    print_char(32)
                i = i + 1
            if sz > 0:
                print_char(32)
                print_int(sz)
                print_char(115)
            print_char(10)
        e = e + 1
    if found == 0:
        print_char(40)
        print_char(101)
        print_char(109)
        print_char(112)
        print_char(116)
        print_char(121)
        print_char(41)
        print_char(10)
    return 0


# ── cd ───────────────────────────────────────────────────────────────────────

def cmd_cd() -> int:
    i = arg_start()
    c0 = mem_load(5000 + i)
    c1 = mem_load(5000 + i + 1)
    is_back = 0
    if c0 == 46:
        if c1 == 46:
            is_back = 1
    if c0 == 47:
        is_back = 1
    if c0 <= 32:
        is_back = 1
    if is_back == 1:
        mem_store(5500, 0)
        mem_store(5501, 0)
        mem_store(5502, 0)
        mem_store(5503, 0)
        mem_store(5504, 0)
        mem_store(5505, 0)
        mem_store(5506, 0)
        return 0
    copy_name(i)
    cwd = mem_load(5500)
    diskread(6000, cwd)
    entry = find_in_dir()
    if entry == 0:
        print_not_found()
        return 0
    sz = mem_load(entry + 7)
    if sz >= 0:
        print_not_dir()
        return 0
    sec = mem_load(entry + 6)
    mem_store(5500, sec)
    j = 0
    while j < 6:
        mem_store(5501 + j, mem_load(6090 + j))
        j = j + 1
    return 0


# ── mkdir ────────────────────────────────────────────────────────────────────

def cmd_mkdir() -> int:
    i = arg_start()
    copy_name(i)
    cwd = mem_load(5500)
    diskread(6000, cwd)
    entry = find_in_dir()
    if entry > 0:
        print_char(33)
        print_char(101)
        print_char(120)
        print_char(10)
        return 0
    free_e = find_free_entry()
    if free_e == 0:
        print_char(33)
        print_char(102)
        print_char(117)
        print_char(108)
        print_char(108)
        print_char(10)
        return 0
    sec = alloc_sector()
    j = 0
    while j < 81:
        mem_store(7000 + j, 0)
        j = j + 1
    diskwrite(7000, sec)
    dir_sz = 0 - 1
    write_dir_entry(free_e, sec, dir_sz)
    diskwrite(6000, cwd)
    print_ok()
    return 0


# ── cat ──────────────────────────────────────────────────────────────────────

def cmd_cat() -> int:
    i = arg_start()
    copy_name(i)
    cwd = mem_load(5500)
    diskread(6000, cwd)
    entry = find_in_dir()
    if entry == 0:
        print_not_found()
        return 0
    sz = mem_load(entry + 7)
    if sz < 0:
        print_is_dir()
        return 0
    start_sec = mem_load(entry + 6)
    num_secs = mem_load(entry + 7)
    buf = 7000
    sec = start_sec
    s = 0
    while s < num_secs:
        diskread(buf, sec)
        buf = buf + 81
        sec = sec + 1
        s = s + 1
    i = 0
    ch = mem_load(7000 + i)
    while ch > 0:
        print_char(ch)
        i = i + 1
        ch = mem_load(7000 + i)
    print_char(10)
    return 0


# ── write ────────────────────────────────────────────────────────────────────

def cmd_write() -> int:
    i0 = arg_start()
    i1 = copy_name(i0)
    i2 = skip_spaces(i1)
    j = 0
    k = i2
    ch = mem_load(5000 + k)
    while ch > 0:
        if j < 80:
            mem_store(7000 + j, ch)
            j = j + 1
        k = k + 1
        ch = mem_load(5000 + k)
    mem_store(7000 + j, 0)
    j = j + 1
    while j < 81:
        mem_store(7000 + j, 0)
        j = j + 1
    cwd = mem_load(5500)
    diskread(6000, cwd)
    entry = find_in_dir()
    if entry > 0:
        sz = mem_load(entry + 7)
        if sz < 0:
            print_is_dir()
            return 0
        sec = mem_load(entry + 6)
        diskwrite(7000, sec)
        write_dir_entry(entry, sec, 1)
        diskwrite(6000, cwd)
    else:
        free_e = find_free_entry()
        if free_e == 0:
            print_char(33)
            print_char(102)
            print_char(117)
            print_char(108)
            print_char(108)
            print_char(10)
            return 0
        sec = alloc_sector()
        diskwrite(7000, sec)
        write_dir_entry(free_e, sec, 1)
        diskwrite(6000, cwd)
    print_ok()
    return 0


# ── rm ───────────────────────────────────────────────────────────────────────

def cmd_rm() -> int:
    i = arg_start()
    copy_name(i)
    cwd = mem_load(5500)
    diskread(6000, cwd)
    entry = find_in_dir()
    if entry == 0:
        print_not_found()
        return 0
    i = 0
    while i < 8:
        mem_store(entry + i, 0)
        i = i + 1
    diskwrite(6000, cwd)
    print_ok()
    return 0


# ── sys ──────────────────────────────────────────────────────────────────────

def cmd_sys() -> int:
    print_char(84)
    print_char(69)
    print_char(82)
    print_char(78)
    print_char(65)
    print_char(82)
    print_char(89)
    print_char(32)
    print_char(79)
    print_char(83)
    print_char(10)
    print_char(82)
    print_char(65)
    print_char(77)
    print_char(32)
    print_char(32)
    print_char(52)
    print_char(51)
    print_char(48)
    print_char(52)
    print_char(54)
    print_char(55)
    print_char(50)
    print_char(49)
    print_char(10)
    print_char(68)
    print_char(105)
    print_char(115)
    print_char(107)
    print_char(32)
    print_char(49)
    print_char(57)
    print_char(54)
    print_char(56)
    print_char(51)
    print_char(10)
    return 0


# ── help ─────────────────────────────────────────────────────────────────────

def cmd_help() -> int:
    print_char(67)
    print_char(111)
    print_char(109)
    print_char(109)
    print_char(97)
    print_char(110)
    print_char(100)
    print_char(115)
    print_char(58)
    print_char(10)
    print_char(32)
    print_char(32)
    print_char(108)
    print_char(115)
    print_char(10)
    print_char(32)
    print_char(32)
    print_char(99)
    print_char(100)
    print_char(32)
    print_char(78)
    print_char(10)
    print_char(32)
    print_char(32)
    print_char(109)
    print_char(107)
    print_char(100)
    print_char(105)
    print_char(114)
    print_char(32)
    print_char(78)
    print_char(10)
    print_char(32)
    print_char(32)
    print_char(112)
    print_char(119)
    print_char(100)
    print_char(10)
    print_char(32)
    print_char(32)
    print_char(99)
    print_char(97)
    print_char(116)
    print_char(32)
    print_char(78)
    print_char(10)
    print_char(32)
    print_char(32)
    print_char(119)
    print_char(114)
    print_char(105)
    print_char(116)
    print_char(101)
    print_char(32)
    print_char(78)
    print_char(32)
    print_char(84)
    print_char(10)
    print_char(32)
    print_char(32)
    print_char(114)
    print_char(109)
    print_char(32)
    print_char(78)
    print_char(10)
    print_char(32)
    print_char(32)
    print_char(102)
    print_char(105)
    print_char(98)
    print_char(32)
    print_char(78)
    print_char(10)
    print_char(32)
    print_char(32)
    print_char(101)
    print_char(99)
    print_char(104)
    print_char(111)
    print_char(32)
    print_char(84)
    print_char(10)
    print_char(32)
    print_char(32)
    print_char(109)
    print_char(101)
    print_char(109)
    print_char(32)
    print_char(78)
    print_char(10)
    print_char(32)
    print_char(32)
    print_char(112)
    print_char(111)
    print_char(107)
    print_char(101)
    print_char(32)
    print_char(78)
    print_char(32)
    print_char(86)
    print_char(10)
    print_char(32)
    print_char(32)
    print_char(99)
    print_char(108)
    print_char(101)
    print_char(97)
    print_char(114)
    print_char(10)
    print_char(32)
    print_char(32)
    print_char(115)
    print_char(121)
    print_char(115)
    print_char(10)
    print_char(32)
    print_char(104)
    print_char(101)
    print_char(108)
    print_char(112)
    print_char(10)
    return 0


# ── unknown command ───────────────────────────────────────────────────────────

def cmd_unknown() -> int:
    print_char(63)
    print_char(32)
    print_char(40)
    print_char(104)
    print_char(101)
    print_char(108)
    print_char(112)
    print_char(41)
    print_char(10)
    return 0


# ── dispatch ─────────────────────────────────────────────────────────────────

def dispatch() -> int:
    is_ls = buf_eq2(108, 115)
    if is_ls == 1:
        cmd_ls()
        return 1
    is_cd = buf_eq2(99, 100)
    if is_cd == 1:
        cmd_cd()
        return 1
    is_pwd = buf_eq3(112, 119, 100)
    if is_pwd == 1:
        cmd_pwd()
        return 1
    is_cat = buf_eq3(99, 97, 116)
    if is_cat == 1:
        cmd_cat()
        return 1
    is_rm = buf_eq2(114, 109)
    if is_rm == 1:
        cmd_rm()
        return 1
    is_fib = buf_eq3(102, 105, 98)
    if is_fib == 1:
        cmd_fib()
        return 1
    is_sys = buf_eq3(115, 121, 115)
    if is_sys == 1:
        cmd_sys()
        return 1
    is_mem = buf_eq3(109, 101, 109)
    if is_mem == 1:
        cmd_mem()
        return 1
    is_echo = buf_eq4(101, 99, 104, 111)
    if is_echo == 1:
        cmd_echo()
        return 1
    is_help = buf_eq4(104, 101, 108, 112)
    if is_help == 1:
        cmd_help()
        return 1
    is_poke = buf_eq4(112, 111, 107, 101)
    if is_poke == 1:
        cmd_poke()
        return 1
    is_clr = buf_eq5(99, 108, 101, 97)
    if is_clr == 1:
        if mem_load(5004) == 114:
            if mem_load(5005) <= 32:
                cmd_clear()
                return 1
    is_wrt = buf_eq5(119, 114, 105, 116)
    if is_wrt == 1:
        if mem_load(5004) == 101:
            if mem_load(5005) <= 32:
                cmd_write()
                return 1
    is_mkd = buf_eq5(109, 107, 100, 105)
    if is_mkd == 1:
        if mem_load(5004) == 114:
            if mem_load(5005) <= 32:
                cmd_mkdir()
                return 1
    return 0


# ── main REPL ─────────────────────────────────────────────────────────────────

def main() -> int:
    print_char(10)
    print_char(84)
    print_char(69)
    print_char(82)
    print_char(78)
    print_char(65)
    print_char(82)
    print_char(89)
    print_char(32)
    print_char(83)
    print_char(72)
    print_char(69)
    print_char(76)
    print_char(76)
    print_char(10)
    print_char(84)
    print_char(121)
    print_char(112)
    print_char(101)
    print_char(32)
    print_char(39)
    print_char(104)
    print_char(101)
    print_char(108)
    print_char(112)
    print_char(39)
    print_char(32)
    print_char(102)
    print_char(111)
    print_char(114)
    print_char(32)
    print_char(99)
    print_char(111)
    print_char(109)
    print_char(109)
    print_char(97)
    print_char(110)
    print_char(100)
    print_char(115)
    print_char(10)
    print_char(10)
    mem_store(5500, 0)
    mem_store(5501, 0)
    mem_store(5502, 0)
    mem_store(5503, 0)
    mem_store(5504, 0)
    mem_store(5505, 0)
    mem_store(5506, 0)
    init_free_ptr()

    while 1 == 1:
        print_char(62)
        print_char(32)
        length = read_line()
        if length > 0:
            found = dispatch()
            if found == 0:
                cmd_unknown()

    return 0

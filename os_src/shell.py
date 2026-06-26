"""
Ternary OS interactive shell.  load-addr=1200, frame-addr=4200, --lib.

Command buffer: RAM[5000..5063]  (64 chars, null-terminated)

No module-level constant names in function bodies.
No semicolons (asmpython lexer rejects them).
No BoolOp (or/and) — split into nested ifs.
"""

def mem_load(addr: int) -> int:
    return 0

def mem_store(addr: int, value: int) -> int:
    return 0

def print_char(ch: int) -> int:
    return 0

def read_char() -> int:
    return 0


def print_int_digits(n: int) -> int:
    if n == 0:
        return 0
    print_int_digits(n // 10)
    print_char(n % 10 + 48)
    return 0

def print_int(n: int) -> int:
    if n == 0:
        print_char(48)
        return 0
    if n < 0:
        print_char(45)
        n = 0 - n
    print_int_digits(n)
    return 0


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

def parse_arg() -> int:
    n = 0
    i = 4
    ch = mem_load(5000 + i)
    while ch >= 48:
        if ch > 57:
            return n
        n = n * 10 + ch - 48
        i = i + 1
        ch = mem_load(5000 + i)
    return n

def cmd_fib() -> int:
    n = parse_arg()
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
    print_char(102)
    print_char(105)
    print_char(98)
    print_char(32)
    print_char(78)
    print_char(32)
    print_char(32)
    print_char(32)
    print_char(99)
    print_char(111)
    print_char(109)
    print_char(112)
    print_char(117)
    print_char(116)
    print_char(101)
    print_char(32)
    print_char(102)
    print_char(105)
    print_char(98)
    print_char(111)
    print_char(110)
    print_char(97)
    print_char(99)
    print_char(99)
    print_char(105)
    print_char(40)
    print_char(78)
    print_char(41)
    print_char(10)
    print_char(32)
    print_char(32)
    print_char(104)
    print_char(101)
    print_char(108)
    print_char(112)
    print_char(32)
    print_char(32)
    print_char(32)
    print_char(32)
    print_char(115)
    print_char(104)
    print_char(111)
    print_char(119)
    print_char(32)
    print_char(116)
    print_char(104)
    print_char(105)
    print_char(115)
    print_char(32)
    print_char(104)
    print_char(101)
    print_char(108)
    print_char(112)
    print_char(10)
    return 0


def cmd_unknown() -> int:
    print_char(63)
    print_char(10)
    return 0


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

    while 1 == 1:
        print_char(62)
        print_char(32)
        length = read_line()

        if length > 0:
            cmd = mem_load(5000)
            if cmd == 102:
                cmd_fib()
            else:
                if cmd == 104:
                    cmd_help()
                else:
                    cmd_unknown()

    return 0

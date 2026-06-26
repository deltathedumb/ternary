"""
Ternary OS shell.  load-addr=1200, frame-addr=4200, --lib.
Module-level names are uninitialized allocas in asmpython — use literals.
"""

def mem_load(addr: int) -> int:
    return 0

def mem_store(addr: int, value: int) -> int:
    return 0

def diskread(buf: int, sector: int) -> int:
    return 0

def call_addr(addr: int) -> int:
    return 0

def printf(fmt: str, val: int) -> int:
    return 0


def load_sectors(buf: int, start_sector: int, num_sectors: int) -> int:
    i = 0
    cur_sector = start_sector
    while i < num_sectors:
        cur_buf = buf + i * 81
        diskread(cur_buf, cur_sector)
        cur_sector = cur_sector + 1
        i = i + 1
    return 0


def name_matches(dir_base: int, name_addr: int) -> int:
    i = 0
    while i < 6:
        dc = mem_load(dir_base + i)
        nc = mem_load(name_addr + i)
        if dc == nc:
            i = i + 1
        else:
            return 0
    return 1


def find_file(name_addr: int) -> int:
    entry = 0
    while entry < 10:
        base = 2600 + entry * 8
        matched = name_matches(base, name_addr)
        if matched == 1:
            return base
        entry = entry + 1
    return 0


def main() -> int:
    diskread(2600, 0)

    mem_store(2682, 104)
    mem_store(2683, 101)
    mem_store(2684, 108)
    mem_store(2685, 108)
    mem_store(2686, 111)
    mem_store(2687, 0)

    entry_base = find_file(2682)

    if entry_base == 0:
        while 1 == 1:
            entry_base = 0

    start_sec = mem_load(entry_base + 6)
    num_secs  = mem_load(entry_base + 7)
    load_sectors(2000, start_sec, num_secs)

    call_addr(2000)

    return 0

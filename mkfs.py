"""
mkfs.py — Format the ternary virtual disk and write OS binaries.

Usage:
    python mkfs.py <disk_path> <kernel.tern> <shell.tern> <hello.tern>

The disk file is a flat array of 4-byte LE signed ints (one per cell).
Layout written:
    sector 0          directory (10 entries × 8 cells)
    sectors 1-10      kernel binary
    sectors 11-15     shell binary
    sectors 16-20     hello binary
"""

import struct
import sys
from pathlib import Path


def _int_to_bt(value: int, n: int = 16) -> list[int]:
    """Convert a Python int to balanced ternary (list of n trits, LSB first)."""
    trits = []
    v = value
    for _ in range(n):
        r = v % 3
        v //= 3
        if r == 2:
            trits.append(-1)
            v += 1
        else:
            trits.append(r)
    return trits

# ── Constants (must match os_constants.py) ────────────────────────────────────
SECTOR_SIZE       = 81
NUM_SECTORS       = 243
DISK_CELLS        = SECTOR_SIZE * NUM_SECTORS   # 19683

DIR_SECTOR        = 0
DIR_ENTRIES       = 10
DIR_ENTRY_SIZE    = 8
DIR_NAME_LEN      = 6

KERNEL_DISK_SECTOR  = 1
KERNEL_DISK_SECTORS = 10

SHELL_DISK_SECTOR   = 11
SHELL_DISK_SECTORS  = 130


def name_ints(s: str) -> list[int]:
    s = (s + "\x00" * 6)[:6]
    return [ord(c) for c in s]


def load_tern(path: Path) -> list[int]:
    raw = path.read_bytes()
    n = len(raw) // 4
    return list(struct.unpack_from(f"<{n}i", raw))


def pad_to_sectors(words: list[int], n_sectors: int) -> list[int]:
    target = n_sectors * SECTOR_SIZE
    if len(words) > target:
        raise ValueError(
            f"Binary too large: {len(words)} words > {target} cells "
            f"({n_sectors} sectors)"
        )
    return words + [0] * (target - len(words))


def build_disk(kernel_words, shell_words) -> list[int]:
    disk = [0] * DISK_CELLS

    # ── Directory (sector 0) ──────────────────────────────────────────────────
    entries = [
        ("kernel", KERNEL_DISK_SECTOR, KERNEL_DISK_SECTORS),
        ("shell\x00",  SHELL_DISK_SECTOR,   SHELL_DISK_SECTORS),
    ]
    dir_base = DIR_SECTOR * SECTOR_SIZE
    for idx, (name, start, size) in enumerate(entries):
        base = dir_base + idx * DIR_ENTRY_SIZE
        for i, c in enumerate(name_ints(name)):
            disk[base + i] = c
        disk[base + 6] = start
        disk[base + 7] = size

    # ── Kernel (sectors 1-10) ─────────────────────────────────────────────────
    kwords = pad_to_sectors(kernel_words, KERNEL_DISK_SECTORS)
    off = KERNEL_DISK_SECTOR * SECTOR_SIZE
    for i, w in enumerate(kwords):
        disk[off + i] = w

    # ── Shell (sectors 11-40) ─────────────────────────────────────────────────
    swords = pad_to_sectors(shell_words, SHELL_DISK_SECTORS)
    off = SHELL_DISK_SECTOR * SECTOR_SIZE
    for i, w in enumerate(swords):
        disk[off + i] = w

    return disk


def write_disk(path: Path, words: list[int]) -> None:
    """Write disk image in the Disk class's native trit-byte format.

    Each cell is stored as 16 bytes where byte[i] = trit[i] + 1
    (trit -1 → 0x00, trit 0 → 0x01, trit +1 → 0x02).
    This matches Disk._decode_byte() and Disk._encode_trit() in cpu.py.
    """
    buf = bytearray()
    for val in words:
        trits = _int_to_bt(val, 16)
        for t in trits:
            buf.append(t + 1)          # -1→0, 0→1, +1→2
    path.write_bytes(bytes(buf))
    print(f"Wrote {len(words)} cells ({len(buf)} bytes) -> {path}")


def main():
    if len(sys.argv) != 5:
        print("Usage: python mkfs.py <disk_path> <kernel.tern> <shell.tern> <hello.tern>")
        sys.exit(1)

    disk_path   = Path(sys.argv[1])
    kernel_path = Path(sys.argv[2])
    shell_path  = Path(sys.argv[3])
    hello_path  = Path(sys.argv[4])

    kernel_words = load_tern(kernel_path)
    shell_words  = load_tern(shell_path)
    hello_words  = load_tern(hello_path)

    print(f"kernel: {len(kernel_words)} words")
    print(f"shell:  {len(shell_words)} words")
    print(f"hello:  {len(hello_words)} words")

    disk = build_disk(kernel_words, shell_words, hello_words)
    write_disk(disk_path, disk)


if __name__ == "__main__":
    main()

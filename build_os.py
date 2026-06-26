"""
build_os.py — Compile all OS sources and build the virtual disk image.

Usage:
    python build_os.py [--out-dir <dir>]  (default: ./os_build)

Steps:
    1. Compile os_src/kernel.py → kernel.tern  (--load-addr 300  --frame-addr 4000)
    2. Compile os_src/shell.py  → shell.tern   (--load-addr 1200 --frame-addr 4200 --lib)
    3. Compile os_src/hello.py  → hello.tern   (--load-addr 2000 --frame-addr 4400 --lib)
    4. Build the bootsector binary             (hand-assembled into bootsector.tern)
    5. Call mkfs.py to write ternary.disk

The bootsector (RAM 0-242) is hand-assembled here because it is tiny and
needs hard-coded addresses.  It does two things:
    a. DISKREAD sector 1 (kernel start) → RAM 300, repeated 10 times
    b. JMP 300  (transfer to kernel)
"""

import argparse
import pathlib
import struct
import sys

# Add ternary directory to sys.path so we can import encoder from asmpython.
_HERE = pathlib.Path(__file__).parent.resolve()
_ASMPYTHON = _HERE.parent / "asmpython"
if str(_ASMPYTHON) not in sys.path:
    sys.path.insert(0, str(_ASMPYTHON))
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from asmpython._compiler.program import load_program
from asmpython._compiler import sema, ir_lower
from asmpython._backends.ternary import run_backend_codegen
from asmpython._backends.ternary import encoder as E
from os_constants import (
    KERNEL_RAM, KERNEL_DISK_SECTOR, KERNEL_DISK_SECTORS,
    SHELL_RAM, SHELL_DISK_SECTOR, SHELL_DISK_SECTORS,
    HELLO_DISK_SECTOR, HELLO_DISK_SECTORS,
    PROG_RAM, SECTOR_SIZE,
    KERNEL_FRAME, SHELL_FRAME, PROG_FRAME,
)


# ── Compilation helper ─────────────────────────────────────────────────────────

def compile_source(src_path: pathlib.Path, load_addr: int,
                   frame_addr: int, lib: bool) -> bytes:
    source = src_path.read_text(encoding="utf-8")
    mod = load_program(source, src_path)
    sema.analyze(mod)
    ir  = ir_lower.lower_module(mod)
    result = run_backend_codegen(ir, {
        "load_addr":  load_addr,
        "frame_addr": frame_addr,
        "lib":        lib,
    })
    data = result["output.tern"]
    n_words = len(data) // 4
    print(f"  {src_path.name:20s}  {n_words:4d} words "
          f"(load_addr={load_addr}, frame_addr={frame_addr}"
          + (", --lib" if lib else "") + ")")
    return data


# ── Bootsector ────────────────────────────────────────────────────────────────

def build_bootsector() -> bytes:
    """
    Hand-assemble the bootsector.  It must fit within 243 cells (3 sectors).

    Algorithm:
        r0 = KERNEL_RAM               # destination buffer base
        r1 = KERNEL_DISK_SECTOR       # first sector to read
        r2 = KERNEL_DISK_SECTOR + KERNEL_DISK_SECTORS   # stop sector
    loop:
        DISKREAD r0, r1               # read one sector into RAM[r0]
        r0 += SECTOR_SIZE             # advance buffer pointer
        r1 += 1                       # next sector
        CMP r2, r1                    # FLAGS = r1 - r2
        JL loop                       # if r1 < r2: keep going
        JMP KERNEL_RAM                # jump into kernel
    """
    words: list[int] = []

    # Setup registers
    words += E.movi(0, KERNEL_RAM)                             # r0 = 300
    words += E.movi(1, KERNEL_DISK_SECTOR)                     # r1 = 1
    words += E.movi(2, KERNEL_DISK_SECTOR + KERNEL_DISK_SECTORS)  # r2 = 11

    # Loop start address (absolute, no load_addr offset — bootsector loads at 0)
    loop_addr = len(words)

    words += E.diskread(0, 1)                                  # DISKREAD r0, r1
    words += E.movi(3, SECTOR_SIZE)                            # r3 = 81
    words += E.add(3, 0)                                       # r0 += r3
    words += E.inc(1)                                          # r1 += 1
    words += E.cmp_rr(2, 1)                                    # FLAGS = r1 - r2
    words += E.jl(loop_addr)                                   # if r1 < r2: loop
    words += E.jmp(KERNEL_RAM)                                 # jump to kernel

    n = len(words)
    assert n <= 243, f"Bootsector overflow: {n} words > 243"
    print(f"  {'bootsector':20s}  {n:4d} words (max 243)")
    # Pad to full bootsector region
    words += [0] * (243 - n)
    return struct.pack(f"<{len(words)}i", *words)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Build ternary OS disk image")
    ap.add_argument("--out-dir", default="os_build",
                    help="Output directory for .tern files and disk image")
    args = ap.parse_args()

    out_dir = _HERE / args.out_dir
    out_dir.mkdir(exist_ok=True)

    src_dir = _HERE / "os_src"

    print("Compiling OS sources…")
    kernel_bytes = compile_source(src_dir / "kernel.py",
                                  load_addr=KERNEL_RAM, frame_addr=KERNEL_FRAME, lib=False)
    shell_bytes  = compile_source(src_dir / "shell.py",
                                  load_addr=SHELL_RAM,  frame_addr=SHELL_FRAME, lib=True)
    hello_bytes  = compile_source(src_dir / "hello.py",
                                  load_addr=PROG_RAM,   frame_addr=PROG_FRAME,  lib=True)
    boot_bytes   = build_bootsector()

    # Write individual .tern files
    (out_dir / "kernel.tern").write_bytes(kernel_bytes)
    (out_dir / "shell.tern").write_bytes(shell_bytes)
    (out_dir / "hello.tern").write_bytes(hello_bytes)
    (out_dir / "bootsector.tern").write_bytes(boot_bytes)

    # Build disk image via mkfs logic (imported inline to avoid subprocess)
    import mkfs
    kernel_words = list(struct.unpack_from(f"<{len(kernel_bytes)//4}i", kernel_bytes))
    shell_words  = list(struct.unpack_from(f"<{len(shell_bytes)//4}i",  shell_bytes))
    hello_words  = list(struct.unpack_from(f"<{len(hello_bytes)//4}i",  hello_bytes))

    disk_words = mkfs.build_disk(kernel_words, shell_words, hello_words)
    disk_path = out_dir / "ternary.disk"
    mkfs.write_disk(disk_path, disk_words)

    print(f"\nDisk image:  {disk_path}")
    print(f"Bootsector:  {out_dir / 'bootsector.tern'}")
    print("Build complete.")


if __name__ == "__main__":
    main()

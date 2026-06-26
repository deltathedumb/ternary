"""
os_runner.py — Boot and run the ternary OS end-to-end.

Usage:
    python os_runner.py [--build-dir <dir>]  (default: ./os_build)

Expects the following files to exist in build_dir (created by build_os.py):
    bootsector.tern   — raw 4-byte-int binary for the bootsector
    ternary.disk      — trit-byte disk image (written by mkfs.py)

The runner:
  1. Creates a TernarySystem with the OS disk.
  2. Loads bootsector.tern into RAM[0..242] directly.
  3. Starts one CPU core (PC=0).
  4. Waits for HALT or timeout.
  5. Prints all io_out values.
"""

import argparse
import pathlib
import struct
import sys
import time

_HERE = pathlib.Path(__file__).parent.resolve()
_ASMPYTHON = _HERE.parent / "asmpython"
if str(_ASMPYTHON) not in sys.path:
    sys.path.insert(0, str(_ASMPYTHON))
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from cpu import TernarySystem, ternary_1


def load_tern_words(path: pathlib.Path) -> list[int]:
    raw = path.read_bytes()
    n = len(raw) // 4
    return list(struct.unpack_from(f"<{n}i", raw))


def run_os(build_dir: pathlib.Path, timeout: float = 30.0) -> None:
    boot_path = build_dir / "bootsector.tern"
    disk_path = build_dir / "ternary.disk"

    if not boot_path.exists():
        print(f"ERROR: {boot_path} not found — run build_os.py first")
        sys.exit(1)
    if not disk_path.exists():
        print(f"ERROR: {disk_path} not found — run build_os.py first")
        sys.exit(1)

    print(f"Disk:        {disk_path}")
    print(f"Bootsector:  {boot_path}")

    # Create system with the pre-built disk image.
    # The Disk class will open the file directly; pass its path as str.
    system = TernarySystem(
        ternary_1,
        num_cores=1,
        num_graphical_cores=0,
        disk_path=str(disk_path),
        disk_size=19683,
    )

    # _boot() already ran (using the default empty bootsector.raw).
    # Overwrite RAM[0..N-1] with our compiled bootsector.
    boot_words = load_tern_words(boot_path)
    for i, w in enumerate(boot_words):
        system.mem.set(i, w)

    print(f"Bootsector:  {len(boot_words)} words loaded into RAM[0]")
    print("Starting CPU core 0…")

    t0 = time.monotonic()
    system.start_all()
    system.cores[0].join(timeout=timeout)
    elapsed = time.monotonic() - t0
    system.stop_all()
    system.join_all()

    out = system.drain_io_out()

    print(f"Elapsed:     {elapsed:.3f}s")
    print(f"Core halted: {system.cores[0].HALTED}")
    print()

    if out:
        print("=== Program output ===")
        for port, value in out:
            print(f"  port {port}: {value}")
    else:
        print("(no output produced)")


def main():
    ap = argparse.ArgumentParser(description="Boot and run the ternary OS")
    ap.add_argument("--build-dir", default="os_build",
                    help="Directory containing bootsector.tern and ternary.disk")
    ap.add_argument("--timeout", type=float, default=30.0,
                    help="Max seconds to wait for HALT (default 30)")
    args = ap.parse_args()

    build_dir = _HERE / args.build_dir
    run_os(build_dir, timeout=args.timeout)


if __name__ == "__main__":
    main()

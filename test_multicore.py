#!/usr/bin/env python3
"""Multi-threaded test for the SharedState spinlock (ACQ/REL).

Two real Core threads race to increment a shared memory counter. The
unsafe variant skips the lock to demonstrate lost updates; the safe
variant wraps the read-modify-write in ACQ/REL and must always produce
an exact total.
"""
import sys
from cpu import TernarySystem, ternary_1, Immediate, encode_instruction

failures = []
COUNTER_ADDR = 1000
LOCK_ID = 0


def check(label, actual, expected):
    status = "[OK]" if actual == expected else "[FAIL]"
    if actual != expected:
        failures.append(label)
    print(f"{status} {label}: got {actual!r}, expected {expected!r}")


def build_program(use_lock: bool, n: int):
    """r1 counts down from n; each iteration does counter++ under (or without) a lock."""
    words = []
    addr = 0

    def emit(opcode, operands):
        nonlocal addr
        for w in encode_instruction(opcode, operands):
            words.append(w)
            addr += 1

    emit("00++0+", [1, Immediate(n)])  # MOVI r1, #n

    loop_addr = addr
    if use_lock:
        emit("00--+-", [Immediate(LOCK_ID)])  # ACQ #LOCK_ID
    emit("00000+", [Immediate(COUNTER_ADDR), 0])  # LOAD #COUNTER_ADDR, r0
    emit("000+--", [0])  # INC r0
    emit("0000-0", [Immediate(COUNTER_ADDR), 0])  # STORE #COUNTER_ADDR, r0
    if use_lock:
        emit("00--++", [Immediate(LOCK_ID)])  # REL #LOCK_ID
    emit("000+-+", [1])  # DEC r1
    emit("000--0", [Immediate(loop_addr)])  # JNZ loop_addr
    emit("000000", [])  # HALT

    return words


def run_race(use_lock: bool, n_per_core: int, num_cores: int = 2):
    system = TernarySystem(ternary_1, num_cores=num_cores)
    program = build_program(use_lock, n_per_core)
    for i, w in enumerate(program):
        system.mem.set(i, w)

    system.start_all()
    system.join_all()

    return int(system.mem.get(COUNTER_ADDR))


if __name__ == "__main__":
    N_PER_CORE = 1000  # 2 cores * 1000 = 2000 total, well under the 8-trit limit of 3280
    NUM_CORES = 2
    expected_total = N_PER_CORE * NUM_CORES

    safe_total = run_race(use_lock=True, n_per_core=N_PER_CORE, num_cores=NUM_CORES)
    check("ACQ/REL-protected counter is exact under contention", safe_total, expected_total)

    sys.setswitchinterval(0.0001)
    unsafe_total = run_race(use_lock=False, n_per_core=N_PER_CORE, num_cores=NUM_CORES)
    if unsafe_total != expected_total:
        print(
            f"[INFO] Unlocked counter lost updates as expected: "
            f"got {unsafe_total}, would be {expected_total} if races never happened"
        )
    else:
        print(
            f"[INFO] Unlocked run got lucky and saw no lost updates this time "
            f"(got {unsafe_total}); the GIL can mask the race -- this is not a failure"
        )

    print()
    if failures:
        print(f"[FAIL] {len(failures)} check(s) failed: {failures}")
        raise SystemExit(1)
    print("[OK] Spinlock correctness verified under real thread contention")

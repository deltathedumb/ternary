#!/usr/bin/env python3
"""Example program running on the ternary processor"""
from cpu import TernarySystem, ternary_1, encode_instruction

def run_example():
    """Run a simple program that adds two numbers and halts"""
    system = TernarySystem(ternary_1, num_cores=1)
    core = system.cores[0]

    core.r(0).from_int(7)
    core.r(1).from_int(5)

    print("Ternary Processor Example")
    print("=" * 40)
    print(f"\nInitial state:")
    print(f"  r0 = {int(core.r(0))}")
    print(f"  r1 = {int(core.r(1))}")

    # Program: ADD r0, r1  (r1 += r0); HALT
    program = [
        ("0000--", [0, 1]),  # ADD r0, r1
        ("000000", []),       # HALT
    ]

    addr = 0
    for opcode, operands in program:
        for word in encode_instruction(opcode, operands):
            system.mem.set(addr, word)
            addr += 1

    print(f"\nRunning program...")
    core.run()

    print(f"\nExecution complete")
    print(f"\nFinal state:")
    print(f"  r0 = {int(core.r(0))}")
    print(f"  r1 = {int(core.r(1))}")
    print(f"  PC = {int(core.PC)}")
    print(f"  FLAGS = {core.FLAGS}")
    print(f"  HALTED = {core.HALTED}")

if __name__ == "__main__":
    run_example()

#!/usr/bin/env python3
from cpu import TernarySystem, ternary_1, Trite, Immediate, encode_instruction

def fresh_core():
    """A single-core system, returned as (system, core) for tests."""
    system = TernarySystem(ternary_1, num_cores=1)
    return system, system.cores[0]

def write_program(system, instructions, start_addr=0):
    """instructions: list of (opcode, operands) tuples. Writes them sequentially
    and returns the address right after the last word written."""
    addr = start_addr
    for opcode, operands in instructions:
        for word in encode_instruction(opcode, operands):
            system.mem.set(addr, word)
            addr += 1
    return addr

def test_basic():
    """Test that a tiny program (MOV immediate, HALT) runs end-to-end."""
    system, core = fresh_core()

    write_program(system, [
        ("00000-", [2, Immediate(5)]),  # MOV r2, #5
        ("000000", []),                  # HALT
    ])

    core.run()

    print(f"Processor initialized with {len(core.registers)} registers")
    print(f"Memory size: {len(system.mem.mem)} locations")
    print(f"r2 = {int(core.r(2))} (expected 5)")
    print(f"HALTED = {core.HALTED}")
    status = "[OK]" if int(core.r(2)) == 5 and core.HALTED else "[FAIL]"
    print(f"{status} Basic fetch/decode/execute loop works")

def test_arithmetic():
    """Test arithmetic operations, including immediate operands."""
    system, core = fresh_core()

    core.r(0).from_int(10)
    core.r(1).from_int(5)

    print(f"\nArithmetic test:")
    print(f"  r0 = {int(core.r(0))}, r1 = {int(core.r(1))}")

    from cpu import op_add
    try:
        op_add(core, 0, 1)  # ADD r0, r1 -> r1 += r0
        print(f"  After ADD r0, r1: r1 = {int(core.r(1))}")
        print(f"  FLAGS = {core.FLAGS:04b}")
        assert int(core.r(1)) == 15
        print("[OK] Register-register arithmetic works")
    except Exception as e:
        print(f"[FAIL] Error: {e}")

    try:
        op_add(core, Immediate(100), 1)  # ADD #100, r1 -> r1 += 100
        print(f"  After ADD #100, r1: r1 = {int(core.r(1))}")
        assert int(core.r(1)) == 115
        print("[OK] Immediate-operand arithmetic works")
    except Exception as e:
        print(f"[FAIL] Error: {e}")

def test_full_program():
    """Run ADD #3, r0 then HALT through the real fetch/decode/execute loop."""
    system, core = fresh_core()
    core.r(0).from_int(7)

    write_program(system, [
        ("0000--", [Immediate(3), 0]),  # ADD #3, r0 -> r0 += 3
        ("000000", []),                  # HALT
    ])

    core.run()

    print(f"\nFull program test:")
    print(f"  r0 = {int(core.r(0))} (expected 10)")
    status = "[OK]" if int(core.r(0)) == 10 else "[FAIL]"
    print(f"{status} Multi-instruction program with immediate operand works")

def test_trite_conversion():
    """Test Trite integer conversion"""
    t = Trite()

    test_vals = [0, 1, -1, 13, -13, 100, -100]
    print(f"\nTrite conversion test:")
    for val in test_vals:
        t.reset()
        try:
            t.from_int(val)
            result = int(t)
            status = "[OK]" if result == val else "[FAIL]"
            print(f"  {status} {val:4d} -> {str(t)} -> {result:4d}")
        except Exception as e:
            print(f"  [FAIL] {val:4d} failed: {e}")

if __name__ == "__main__":
    test_basic()
    test_arithmetic()
    test_full_program()
    test_trite_conversion()
    print("\n[OK] All tests completed")

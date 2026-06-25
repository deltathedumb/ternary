#!/usr/bin/env python3
"""Coverage test for the extended instruction set (mul..leave)."""
from cpu import TernarySystem, ternary_1, Immediate, encode_instruction, Trite, GPU
import cpu as cpu_module

failures = []


def check(label, actual, expected):
    status = "[OK]" if actual == expected else "[FAIL]"
    if actual != expected:
        failures.append(label)
    print(f"{status} {label}: got {actual!r}, expected {expected!r}")


def write(core, prog, addr=0):
    """prog: list of (opcode, operands) tuples. Returns addr after last word."""
    for op, ops in prog:
        for w in encode_instruction(op, ops):
            core.system.mem.set(addr, w)
            addr += 1
    return addr


def fresh():
    """A single-core system; returns the Core (with .system attached)."""
    system = TernarySystem(ternary_1, num_cores=1)
    return system.cores[0]


def call(name, core, *args):
    return getattr(cpu_module, name)(core, *args)


# ---- arithmetic --------------------------------------------------------
c = fresh(); c.r(0).from_int(6); c.r(1).from_int(7)
call("op_mul", c, 0, 1)
check("MUL r1 *= r0", int(c.r(1)), 42)

c = fresh(); c.r(0).from_int(3); c.r(1).from_int(20)
call("op_div", c, 0, 1)
check("DIV r1 //= r0", int(c.r(1)), 6)

c = fresh(); c.r(0).from_int(3); c.r(1).from_int(20)
call("op_mod", c, 0, 1)
check("MOD r1 %= r0", int(c.r(1)), 2)

c = fresh(); c.r(0).from_int(5)
call("op_neg", c, 0)
check("NEG r0", int(c.r(0)), -5)

c = fresh(); c.r(0).from_int(5)
call("op_inc", c, 0)
check("INC r0", int(c.r(0)), 6)

c = fresh(); c.r(0).from_int(5)
call("op_dec", c, 0)
check("DEC r0", int(c.r(0)), 4)

c = fresh(); c.r(0).from_int(-5)
call("op_abs", c, 0)
check("ABS r0", int(c.r(0)), 5)

c = fresh(); c.r(0).from_int(2); c.r(1).from_int(3)
call("op_shl", c, 0, 1)
check("SHL r1 <<= r0", int(c.r(1)), 12)

c = fresh(); c.r(0).from_int(2); c.r(1).from_int(12)
call("op_shr", c, 0, 1)
check("SHR r1 >>= r0", int(c.r(1)), 3)

# ---- trit-wise ----------------------------------------------------------
a = Trite().from_int(5)
b = Trite().from_int(-3)
expected_min = Trite()
for i in range(len(expected_min.trits)):
    expected_min.trits[i].set(min(a.trits[i].get(), b.trits[i].get()))
c = fresh(); c.r(0).from_int(5); c.r(1).from_int(-3)
call("op_tmin", c, 0, 1)
check("TMIN trit-wise result", int(c.r(1)), int(expected_min))

expected_max = Trite()
for i in range(len(expected_max.trits)):
    expected_max.trits[i].set(max(a.trits[i].get(), b.trits[i].get()))
c = fresh(); c.r(0).from_int(5); c.r(1).from_int(-3)
call("op_tmax", c, 0, 1)
check("TMAX trit-wise result", int(c.r(1)), int(expected_max))

c = fresh(); c.r(0).from_int(13)
call("op_negtrit", c, 0)
check("NEGTRIT r0", int(c.r(0)), -13)

# ---- non-destructive compare --------------------------------------------
c = fresh(); c.r(0).from_int(5); c.r(1).from_int(2)
call("op_cmp", c, 0, 1)  # r1 - r0 = -3 -> NEGATIVE
check("CMP sets NEGATIVE, no write", (int(c.r(1)), bool(c.FLAGS & 2)), (2, True))

c = fresh(); c.r(0).from_int(0b110); c.r(1).from_int(0b011)
call("op_test", c, 0, 1)
check("TEST sets ZERO appropriately", bool(c.FLAGS & 1), (0b110 & 0b011) == 0)

# ---- conditional jumps through the real fetch/decode/execute loop ------
def jump_taken(opname, flags_value):
    c = fresh()
    c.FLAGS = flags_value
    jcc_words = encode_instruction(opname, [Immediate(0)])
    inc_words = encode_instruction("000+--", [0])
    halt_words = encode_instruction("000000", [])
    target = len(jcc_words) + len(inc_words)  # address of HALT, i.e. skip the INC
    jcc_words = encode_instruction(opname, [Immediate(target)])
    addr = 0
    for w in jcc_words + inc_words + halt_words:
        c.system.mem.set(addr, w); addr += 1
    c.run()
    return int(c.r(0))  # 0 if jump taken (INC skipped), 1 if not taken


check("JL taken on NEGATIVE", jump_taken("00+0-+", 2), 0)
check("JL not taken when not NEGATIVE", jump_taken("00+0-+", 0), 1)
check("JG taken when neither NEGATIVE nor ZERO", jump_taken("00+0+0", 0), 0)
check("JG not taken on ZERO", jump_taken("00+0+0", 1), 1)
check("JLE taken on ZERO", jump_taken("00+0+-", 1), 0)
check("JLE taken on NEGATIVE", jump_taken("00+0+-", 2), 0)
check("JGE taken when not NEGATIVE", jump_taken("00+0++", 0), 0)
check("JGE not taken on NEGATIVE", jump_taken("00+0++", 2), 1)
check("JC taken on CARRY", jump_taken("00+-00", 4), 0)
check("JNC taken when no CARRY", jump_taken("00+-0-", 0), 0)
check("JO taken on OVERFLOW", jump_taken("00+-0+", 8), 0)
check("JNO taken when no OVERFLOW", jump_taken("00+--0", 0), 0)

# ---- relative jump/call --------------------------------------------------
c = fresh()
inc_words = encode_instruction("000+--", [0])
halt_words = encode_instruction("000000", [])
jmpr_words = encode_instruction("00+---", [Immediate(len(inc_words))])  # skip the next INC
addr = 0
for w in jmpr_words + inc_words + halt_words:
    c.system.mem.set(addr, w); addr += 1
c.run()
check("JMPR skips next instruction", int(c.r(0)), 0)

c = fresh()
# CALLR(2 words) ; HALT(1 word) ; INC r0(2 words) ; RET(1 word)
callr_words = encode_instruction("00+--+", [Immediate(0)])  # placeholder offset, fixed below
halt_words = encode_instruction("000000", [])
inc_words = encode_instruction("000+--", [0])
ret_words = encode_instruction("000-+-", [])
next_pc = len(callr_words)  # addr right after CALLR
func_addr = next_pc + len(halt_words)
offset = func_addr - next_pc
callr_words = encode_instruction("00+--+", [Immediate(offset)])
addr = 0
for w in callr_words + halt_words + inc_words + ret_words:
    c.system.mem.set(addr, w); addr += 1
c.run()
check("CALLR/RET round-trip", int(c.r(0)), 1)

# ---- addressing: lea / loado / storeo -----------------------------------
c = fresh(); c.r(0).from_int(100)  # base
call("op_lea", c, 0, Immediate(5), 1)
check("LEA dst = base+offset", int(c.r(1)), 105)

c = fresh(); c.r(0).from_int(50)
c.system.mem.set(53, Trite().from_int(77))
call("op_loado", c, 0, Immediate(3), 1)
check("LOADO dst = mem[base+offset]", int(c.r(1)), 77)

c = fresh(); c.r(0).from_int(50); c.r(1).from_int(99)
call("op_storeo", c, 0, Immediate(3), 1)
check("STOREO mem[base+offset] = src", int(c.system.mem.get(53)), 99)

# ---- stack / immediate convenience --------------------------------------
c = fresh(); c.SP.from_int(0)
call("op_pushi", c, Immediate(42))
check("PUSHI pushes immediate", int(c.system.mem.get(int(c.SP))), 42)

c = fresh(); c.SP.from_int(10)
call("op_adjsp", c, Immediate(-3))
check("ADJSP adjusts SP", int(c.SP), 7)

c = fresh()
call("op_movi", c, 2, Immediate(9))
check("MOVI loads immediate", int(c.r(2)), 9)

c = fresh(); c.r(0).from_int(1); c.r(1).from_int(2)
call("op_xchg", c, 0, 1)
check("XCHG swaps registers", (int(c.r(0)), int(c.r(1))), (2, 1))

# ---- I/O ------------------------------------------------------------------
c = fresh()
call("op_out", c, Immediate(1), Immediate(55))
check("OUT records port/value", c.system.io_out, [(1, 55)])

c = fresh(); c.system.io_in = [123]
call("op_in", c, Immediate(1), 3)
check("IN reads from queue", int(c.r(3)), 123)

c = fresh()
call("op_in", c, Immediate(1), 3)
check("IN with empty queue defaults to 0", int(c.r(3)), 0)

# ---- enter / leave --------------------------------------------------------
c = fresh(); c.SP.from_int(0); c.FP.from_int(0)
call("op_enter", c, Immediate(4))
sp_after_enter = int(c.SP)
check("ENTER reserves frame_size below saved FP", sp_after_enter, -2 - 4)
call("op_leave", c)
check("LEAVE restores SP", int(c.SP), 0)

# ---- disk I/O --------------------------------------------------------------
c = fresh()
call("op_dstore", c, Immediate(7), Immediate(321))
check("DSTORE writes to disk", int(c.system.disk.get(7)), 321)

c = fresh()
c.system.disk.set(9, Trite().from_int(654))
call("op_dload", c, Immediate(9), 4)
check("DLOAD reads from disk", int(c.r(4)), 654)

# ---- vram I/O ---------------------------------------------------------------
c = fresh(); c.r(0).from_int(15)
call("op_vstore", c, Immediate(40), 0)
check("VSTORE writes to vram", int(c.system.vmem.get(40)), 15)

c = fresh()
c.system.vmem.set(41, Trite(trits=5).from_int(-9))
call("op_vload", c, Immediate(41), 5)
check("VLOAD reads from vram", int(c.r(5)), -9)

# ---- multicore primitives ---------------------------------------------------
c = fresh()
call("op_coreid", c, 6)
check("COREID loads this core's id", int(c.r(6)), c.core_id)

# ---- GPU dispatch (GPROC / GSYNC) ------------------------------------------
def fresh_gpu():
    """Like fresh(), but also starts the GPU core threads -- GPROC only
    queues a job, a GPUCore thread has to actually be running to drain it."""
    system = TernarySystem(ternary_1, num_cores=1, num_graphical_cores=2)
    for gpu_core in system.gpu_cores:
        gpu_core.start()
    return system.cores[0]


c = fresh_gpu()
call(
    "op_gproc", c,
    Immediate(GPU.OPCODE_FILL), Immediate(1000), Immediate(100),
    Immediate(4), Immediate(3), Immediate(50), Immediate(GPU.ROP_COPY),
)
call("op_gsync", c)
filled = [int(c.system.vmem.get(1000 + row * 100 + col)) for row in range(3) for col in range(4)]
check("GPROC FILL writes a rect", filled, [50] * 12)

call(
    "op_gproc", c,
    Immediate(GPU.OPCODE_BLIT), Immediate(1000), Immediate(2000), Immediate(100),
    Immediate(4), Immediate(3), Immediate(GPU.ROP_COPY),
)
call("op_gsync", c)
blitted = [int(c.system.vmem.get(2000 + row * 100 + col)) for row in range(3) for col in range(4)]
check("GPROC BLIT copies a rect", blitted, filled)

call(
    "op_gproc", c,
    Immediate(GPU.OPCODE_LINE), Immediate(5000), Immediate(5000 + 5 * 100 + 5),
    Immediate(100), Immediate(99), Immediate(GPU.ROP_COPY), Immediate(0),
)
call("op_gsync", c)
diag = [int(c.system.vmem.get(5000 + i * 100 + i)) for i in range(6)]
check("GPROC LINE draws a diagonal", diag, [99] * 6)

call(
    "op_gproc", c,
    Immediate(GPU.OPCODE_FILL), Immediate(3000), Immediate(100),
    Immediate(1), Immediate(1), Immediate(10), Immediate(GPU.ROP_COPY),
)
call("op_gsync", c)
call(
    "op_gproc", c,
    Immediate(GPU.OPCODE_FILL), Immediate(3000), Immediate(100),
    Immediate(1), Immediate(1), Immediate(5), Immediate(GPU.ROP_ADD),
)
call("op_gsync", c)
check("GPROC FILL with ROP_ADD accumulates", int(c.system.vmem.get(3000)), 15)

c.system.stop_all()
c.system.join_all()

print()
if failures:
    print(f"[FAIL] {len(failures)} check(s) failed: {failures}")
else:
    print("[OK] All extended-instruction checks passed")

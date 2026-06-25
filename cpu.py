import os
import queue
import threading


class Trit:
    HI = 1
    LO = -1
    MID = 0

    def __init__(self):
        self.value = Trit.MID

    def set(self, value):
        if value in (Trit.HI, Trit.LO, Trit.MID):
            self.value = value
        else:
            raise ValueError("Invalid Trit value")

    def get(self):
        return self.value


class SignalCarry(Exception):
    pass


class Immediate:
    __slots__ = ("value",)

    def __init__(self, value: int):
        self.value = value

    def __repr__(self):
        return f"Immediate({self.value})"


# =========================
# Trite (8-trit word)
# =========================
class Trite:
    def __init__(self, values=None, trits=None):
        self.trits = [Trit() for _ in range(trits or 8)]
        self.limit = 3 ** len(self.trits) // 2
        if values:
            for i in range(min(len(values), len(self.trits))):
                self.trits[i].set(values[i])

    def reset(self):
        for t in self.trits:
            t.set(Trit.MID)
        return self

    def set(self, index, value):
        self.trits[index].set(value)
        return self

    def get(self, index):
        return self.trits[index].get()

    def clone_from(self, other):
        n = min(len(self.trits), len(other.trits))
        for i in range(n):
            self.trits[i].set(other.get(i))
        for i in range(n, len(self.trits)):
            self.trits[i].set(Trit.MID)
        return self

    def from_int(self, value: int):
        if value > self.limit or value < -self.limit:
            raise SignalCarry()
        v = value
        for i in range(len(self.trits)):
            r = v % 3
            v //= 3
            if r == 0:
                self.trits[i].set(Trit.MID)
            elif r == 1:
                self.trits[i].set(Trit.HI)
            else:
                self.trits[i].set(Trit.LO)
                v += 1
        return self

    def from_str(self, value: str):
        if len(value) != len(self.trits):
            raise ValueError("String length does not match the number of trits")
        for char in value:
            if char not in ("+", "0", "-"):
                raise ValueError("Invalid character in string")
        for i, char in enumerate(value):
            if char == "+":
                self.trits[i].set(Trit.HI)
            elif char == "0":
                self.trits[i].set(Trit.MID)
            elif char == "-":
                self.trits[i].set(Trit.LO)
        return self

    def __str__(self):
        out = ""
        for t in self.trits:
            val = t.get()
            if val == Trit.HI:
                out += "+"
            elif val == Trit.MID:
                out += "0"
            elif val == Trit.LO:
                out += "-"
        return out

    def __repr__(self):
        return f"Trite({str(self)})"

    def __int__(self):
        out = 0
        for i, t in enumerate(self.trits):
            out += t.get() * (3**i)
        return out

    def __len__(self):
        return len(self.trits)

    def __getitem__(self, key):
        if isinstance(key, slice):
            indices = range(*key.indices(len(self.trits)))
            sub = Trite(trits=len(indices))
            for new_i, old_i in enumerate(indices):
                sub.trits[new_i].set(self.trits[old_i].get())
            return sub
        return self.trits[key].get()


class Flags:
    ZERO = 1 << 0
    NEGATIVE = 1 << 1
    CARRY = 1 << 2
    OVERFLOW = 1 << 3


# =========================
# THREAD-SAFE MEMORY & BUSES
# =========================
class Memory:
    def __init__(self, size):
        self.mem = [Trite() for _ in range(size)]
        self.lock = threading.Lock()

    def get(self, addr):
        with self.lock:
            # In Multithreading, returning a reference is DANGEROUS!
            # We must return a clone so cores don't accidentally mutate shared memory.
            original = self.mem[int(addr)]
            clone = Trite(trits=len(original.trits))
            return clone.clone_from(original)

    def set(self, addr, val):
        with self.lock:
            self.mem[int(addr)].clone_from(val)


class VideoMemory:
    def __init__(self, size):
        self.vmem = [Trite(trits=5) for _ in range(size)]
        self.lock = threading.Lock()

    def get(self, addr):
        with self.lock:
            original = self.vmem[int(addr)]
            clone = Trite(trits=5)
            return clone.clone_from(original)

    def set(self, addr, val):
        with self.lock:
            self.vmem[int(addr)].clone_from(val)


# =========================
# GPU (2D BLITTER)
# =========================
class GPU:
    """A small blitter modeled on classic 2D accelerator hardware (Amiga
    Blitter / VGA BitBLT engines): linear address + pitch addressing (no
    x/y coordinate registers) and raster-op (ROP) compositing instead of
    a plain overwrite. Dispatched from the CPU via the single GPROC
    instruction, so a whole fill/blit/line completes as one native
    Python loop instead of one ternary instruction (and one vmem.lock
    acquisition) per pixel.
    """

    OPCODE_FILL = 0
    OPCODE_BLIT = 1
    OPCODE_LINE = 2

    ROP_COPY = 0
    ROP_XOR = 1
    ROP_AND = 2
    ROP_OR = 3
    ROP_ADD = 4
    ROP_SUB = 5

    def __init__(self, vmem: "VideoMemory"):
        self.vmem = vmem

    def _combine(self, rop, src, dst):
        if rop == self.ROP_XOR:
            return src ^ dst
        if rop == self.ROP_AND:
            return src & dst
        if rop == self.ROP_OR:
            return src | dst
        if rop == self.ROP_ADD:
            return src + dst
        if rop == self.ROP_SUB:
            return dst - src
        return src  # ROP_COPY (and any unrecognised code)

    def _write(self, cell, value):
        # Mirrors op_add/op_sub's own overflow handling: wrap rather than
        # raise, since a ROP_ADD/ROP_SUB can legitimately overflow a
        # pixel's 5-trit range.
        try:
            cell.from_int(value)
        except SignalCarry:
            cell.from_int(value % (cell.limit * 2))

    def fill(self, dst_addr, pitch, width, height, color, rop):
        buf = self.vmem.vmem
        size = len(buf)
        with self.vmem.lock:
            for row in range(height):
                base = dst_addr + row * pitch
                if base < 0 or base + width > size:
                    continue
                for col in range(width):
                    cell = buf[base + col]
                    self._write(cell, self._combine(rop, color, int(cell)))

    def blit(self, src_addr, dst_addr, pitch, width, height, rop):
        buf = self.vmem.vmem
        size = len(buf)
        with self.vmem.lock:
            for row in range(height):
                srow = src_addr + row * pitch
                drow = dst_addr + row * pitch
                if srow < 0 or srow + width > size or drow < 0 or drow + width > size:
                    continue
                # Snapshot the source row first in case src and dst overlap.
                src_vals = [int(buf[srow + col]) for col in range(width)]
                for col in range(width):
                    cell = buf[drow + col]
                    self._write(cell, self._combine(rop, src_vals[col], int(cell)))

    def line(self, addr0, addr1, pitch, color, rop):
        x0, y0 = addr0 % pitch, addr0 // pitch
        x1, y1 = addr1 % pitch, addr1 // pitch
        buf = self.vmem.vmem
        size = len(buf)
        dx = abs(x1 - x0)
        dy = abs(y1 - y0)
        sx = 1 if x1 >= x0 else -1
        sy = 1 if y1 >= y0 else -1
        err = dx - dy
        x, y = x0, y0
        with self.vmem.lock:
            while True:
                addr = y * pitch + x
                if 0 <= addr < size:
                    cell = buf[addr]
                    self._write(cell, self._combine(rop, color, int(cell)))
                if x == x1 and y == y1:
                    break
                e2 = 2 * err
                if e2 > -dy:
                    err -= dy
                    x += sx
                if e2 < dx:
                    err += dx
                    y += sy


class SharedState:
    """A thread-safe 16-trit register that acts as the atomic synchronization primitive."""

    def __init__(self, trits=16):
        self.data = Trite(trits=trits)
        self.lock = threading.Lock()

    def atomic_test_and_set(self, index, test_val=Trit.MID, set_val=Trit.HI) -> bool:
        """Standard 'Test-and-Set' Mutex primitive. Returns True if lock acquired."""
        with self.lock:
            if self.data.get(index) == test_val:
                self.data.set(index, set_val)
                return True
            return False

    def release(self, index, reset_val=Trit.MID):
        with self.lock:
            self.data.set(index, reset_val)

    def get_full_state(self):
        with self.lock:
            clone = Trite(trits=len(self.data.trits))
            return clone.clone_from(self.data)


# =========================
# THREAD-SAFE DISK
# =========================
class Disk:
    _PLAIN_ENCODE = {-1: ord("-"), 0: ord("0"), 1: ord("+")}
    _PLAIN_DECODE = {ord("-"): -1, ord("0"): 0, ord("+"): 1}

    def __init__(self, path: str, size: int, trits: int = 8, plain: bool = False):
        self.path = path
        self.size = size
        self.trits = trits
        self.plain = plain
        self.lock = threading.Lock()

        total_bytes = size * trits
        fill_byte = b"0" if plain else b"\x00"

        if not os.path.exists(path):
            with open(path, "wb") as f:
                f.write(fill_byte * total_bytes)
        elif os.path.getsize(path) < total_bytes:
            with open(path, "r+b") as f:
                f.seek(0, os.SEEK_END)
                f.write(fill_byte * (total_bytes - f.tell()))
        self.file = open(path, "r+b")

    def _decode_byte(self, b: int) -> int:
        if self.plain:
            return self._PLAIN_DECODE.get(b, Trit.MID)
        return b - 1

    def _encode_trit(self, value: int) -> int:
        if self.plain:
            return self._PLAIN_ENCODE[value]
        return value + 1

    def get(self, addr) -> Trite:
        addr = int(addr)
        with self.lock:
            self.file.seek(addr * self.trits)
            chunk = self.file.read(self.trits)
            word = Trite(trits=self.trits)
            for i, b in enumerate(chunk):
                word.trits[i].set(self._decode_byte(b))
            return word

    def set(self, addr, val):
        addr = int(addr)
        chunk = bytes(self._encode_trit(val.get(i)) for i in range(self.trits))
        with self.lock:
            self.file.seek(addr * self.trits)
            self.file.write(chunk)
            self.file.flush()

    def close(self):
        self.file.close()


# =========================
# ISA & INSTRUCTIONS
# =========================
class InstructionSet:
    def __init__(self, **kwargs):
        self.instructions = kwargs

    def add(self, opcode: str | Trite, operandslength, func):
        if isinstance(opcode, str):
            self.instructions[opcode] = (operandslength, func)
        else:
            self.instructions[str(opcode)] = (operandslength, func)

    def get(self, opcode: str | Trite):
        entry = self.instructions.get(
            str(opcode) if isinstance(opcode, Trite) else opcode
        )
        return entry[1] if entry is not None else None

    def get_opcount(self, opcode: str | Trite):
        entry = self.instructions.get(
            str(opcode) if isinstance(opcode, Trite) else opcode
        )
        return entry[0] if entry is not None else None

    def instruction(self, opcode: str | Trite):
        def wrapper(func):
            self.add(opcode, func.__code__.co_argcount - 1, func)
            return func

        return wrapper


def encode_instruction(opcode: str, operands: list) -> list[Trite]:
    """Encodes one instruction as a stream of 8-trit words.

    Layout (the "first hunk" is 2 words = 16 trits):
        word 0: 6-trit opcode + 2-trit operand count (offset +4)
        word 1: ref-type map, one trit per operand slot --
                LO = register, MID = immediate, HI = reserved
        word 2i+2, 2i+3: operand i's value as a 16-trit number, split into
                          its low 8 trits and high 8 trits
    """
    count_field = str(Trite(trits=2).from_int(len(operands) - 4))
    header = Trite().from_str(opcode + count_field)

    reftype = Trite()
    for i, op in enumerate(operands):
        reftype.trits[i].set(Trit.MID if isinstance(op, Immediate) else Trit.LO)

    words = [header, reftype]
    for op in operands:
        value = op.value if isinstance(op, Immediate) else op
        full = Trite(trits=16).from_int(value)
        words.append(full[:8])
        words.append(full[8:16])
    return words


# =========================
# CORE (The Thread)
# =========================
class Core(threading.Thread):
    def __init__(self, core_id, system, isa):
        super().__init__(name=f"Core-{core_id}", daemon=True)
        self.core_id = core_id
        self.system = system
        self.isa = isa

        # Local State
        # 16 trits so registers/PC/SP/FP can hold any address in the largest
        # address space (vmem: 531441 cells) -- the instruction format
        # already encodes every operand as a full 16-trit value, so this
        # just matches what the ISA already supports.
        self.registers = [Trite(trits=16) for _ in range(16)]
        self.PC = Trite(trits=16)
        self.SP = Trite(trits=16)
        self.FP = Trite(trits=16)
        self.FLAGS = 0
        self.HALTED = False
        self._jumped = False
        self._next_pc = 0

    def r(self, i):
        return self.registers[i]

    def value(self, operand) -> int:
        if isinstance(operand, Immediate):
            return operand.value
        return int(self.r(operand))

    def as_trite(self, operand) -> Trite:
        if isinstance(operand, Immediate):
            return Trite(trits=16).from_int(operand.value)
        return self.r(operand)

    def set_pc(self, value: int):
        self.PC.from_int(value)
        self._jumped = True

    def _push_word(self, value: int):
        """Pushes one full 16-trit value onto the stack as two consecutive
        8-trit memory words (low half, then high half) -- the same split
        `encode_instruction` already uses for instruction operands -- so
        any address or register value, not just ones under 3280, survives
        a push/pop round trip intact."""
        full = Trite(trits=16).from_int(value)
        self.SP.from_int(int(self.SP) - 2)
        self.system.mem.set(self.SP, full[:8])
        self.system.mem.set(int(self.SP) + 1, full[8:16])

    def _pop_word(self) -> int:
        lo = self.system.mem.get(self.SP)
        hi = self.system.mem.get(int(self.SP) + 1)
        value = int(lo) + int(hi) * (3**8)
        self.SP.from_int(int(self.SP) + 2)
        return value

    def _set_flags(self, result, carry=False, overflow=False):
        self.FLAGS = 0
        if result == 0:
            self.FLAGS |= Flags.ZERO
        if result < 0:
            self.FLAGS |= Flags.NEGATIVE
        if carry:
            self.FLAGS |= Flags.CARRY
        if overflow:
            self.FLAGS |= Flags.OVERFLOW

    def step(self):
        if self.HALTED:
            return

        header = self.system.mem.get(self.PC)
        opcode_str = str(header[:6])

        if opcode_str not in self.isa.instructions:
            raise Exception(
                f"Core {self.core_id}: Unknown opcode: {opcode_str} at PC {int(self.PC)}"
            )

        op_count = self.isa.get_opcount(opcode_str)
        declared_count = int(header[6:8]) + 4

        if op_count != declared_count:
            raise Exception(f"Operand count mismatch for {opcode_str}")

        base = int(self.PC)
        reftype = self.system.mem.get(base + 1)
        operands = []

        for i in range(op_count):
            word_addr = base + 2 + i * 2
            lo = self.system.mem.get(word_addr)
            hi = self.system.mem.get(word_addr + 1)
            value = int(lo) + int(hi) * (3**8)
            tag = reftype.trits[i].get()
            if tag == Trit.MID:
                operands.append(Immediate(value))
            else:
                operands.append(value % 16)

        func = self.isa.get(opcode_str)
        if func is not None:
            self._next_pc = base + 2 + op_count * 2
            self._jumped = False
            func(self, *operands)
            if not self._jumped:
                self.PC.from_int(self._next_pc)
        else:
            self.PC.from_int(base + 2 + op_count * 2)

    def run(self):
        """The main execution loop for this core."""
        while not self.HALTED:
            self.step()


# =========================
# GPU CORE (The GPU's own thread)
# =========================
class GPUCore(threading.Thread):
    """A GPU execution unit: unlike a CPU `Core`, it doesn't fetch its own
    instruction stream -- it idles until the CPU dispatches a job via
    GPROC, runs that one blitter operation, then goes back to idling.
    Several of these let multiple queued jobs run concurrently, the same
    way real GPUs spread work across many execution units rather than
    one core doing everything serially.
    """

    def __init__(self, gpu_id, system):
        super().__init__(name=f"GPU-{gpu_id}", daemon=True)
        self.gpu_id = gpu_id
        self.system = system

    def run(self):
        while True:
            job = self.system.gpu_queue.get()
            if job is None:  # shutdown sentinel from TernarySystem.stop_all
                self.system.gpu_queue.task_done()
                break
            opcode, args = job
            try:
                gpu = self.system.gpu
                if opcode == GPU.OPCODE_FILL:
                    gpu.fill(*args)
                elif opcode == GPU.OPCODE_BLIT:
                    gpu.blit(*args)
                elif opcode == GPU.OPCODE_LINE:
                    gpu.line(*args[:5])
            finally:
                self.system.gpu_queue.task_done()


# =========================
# SYSTEM (The Motherboard)
# =========================
class TernarySystem:
    DEFAULT_DISK_PATH = "virtualstorage.raw"
    DEFAULT_DISK_SIZE = 19683
    DEFAULT_BOOTSECTOR_PATH = "bootsector.raw"
    DEFAULT_BOOTSECTOR_SIZE = 243

    def __init__(
        self,
        isa,
        num_cores=2,
        num_graphical_cores=2,
        disk_path=DEFAULT_DISK_PATH,
        disk_size=DEFAULT_DISK_SIZE,
        plain=False,
    ):
        self.mem = Memory(6561)
        self.vmem = VideoMemory(640 * 480 + 6561)
        self.state = SharedState(16)

        self.vbuffer_alloc = 640 * 480
        self.vbuffer_offset = 0

        self.io_lock = threading.Lock()
        self.io_in = []
        self.io_out = []

        self.disk = Disk(disk_path, disk_size, plain=plain)
        self.bootsector = Disk(
            self.DEFAULT_BOOTSECTOR_PATH, self.DEFAULT_BOOTSECTOR_SIZE, plain=plain
        )

        self.cores = [Core(i, self, isa) for i in range(num_cores)]

        # GPU: a small blitter (`self.gpu`) plus `num_graphical_cores` idle
        # GPUCore threads that only do work when a CPU core dispatches a
        # job via GPROC (`self.gpu_queue`). GSYNC blocks a CPU core on
        # `gpu_queue.join()` until every dispatched job has completed.
        self.gpu = GPU(self.vmem)
        self.gpu_queue = queue.Queue()
        self.gpu_cores = [GPUCore(i, self) for i in range(num_graphical_cores)]

        self._boot()

    def _boot(self):
        for i in range(self.bootsector.size):
            self.mem.set(i, self.bootsector.get(i))

    def start_all(self):
        for core in self.cores:
            core.start()
        for gpu_core in self.gpu_cores:
            gpu_core.start()

    def stop_all(self):
        for core in self.cores:
            core.HALTED = True  # type: ignore
        for _ in self.gpu_cores:
            self.gpu_queue.put(None)  # shutdown sentinel, one per GPU core

    def join_all(self):
        for core in self.cores:
            core.join()
        for gpu_core in self.gpu_cores:
            gpu_core.join()


ternary_1 = InstructionSet()


# ---- Core Logic & Memory Instructions ---------------------------
@ternary_1.instruction("000000")
def op_halt(self: Core):
    self.HALTED = True  # type: ignore


@ternary_1.instruction("00000-")
def op_mov(self: Core, dst, src):
    self.r(dst).from_int(self.value(src))


@ternary_1.instruction("00000+")
def op_load(self: Core, addr, dst):
    val = self.system.mem.get(self.value(addr))
    self.r(dst).clone_from(val)


@ternary_1.instruction("0000-0")
def op_store(self: Core, addr, src):
    self.system.mem.set(self.value(addr), self.as_trite(src))


@ternary_1.instruction("0000--")
def op_add(self: Core, a, b):
    x, y = self.value(b), self.value(a)
    dest = self.r(b)
    raw = x + y
    carry = abs(raw) > dest.limit
    try:
        dest.from_int(raw)
        overflow = False
    except SignalCarry:
        overflow = True
        dest.from_int(raw % (dest.limit * 2))
    self._set_flags(raw, carry, overflow)


@ternary_1.instruction("0000-+")
def op_sub(self: Core, a, b):
    x, y = self.value(b), self.value(a)
    dest = self.r(b)
    raw = x - y
    try:
        dest.from_int(raw)
        overflow = False
    except SignalCarry:
        overflow = True
        dest.from_int(raw % (dest.limit * 2))
    self._set_flags(raw, False, overflow)


@ternary_1.instruction("0000+0")
def op_and(self: Core, a, b):
    res = self.value(b) & self.value(a)
    self.r(b).from_int(res)
    self._set_flags(res)


@ternary_1.instruction("0000+-")
def op_or(self: Core, a, b):
    res = self.value(b) | self.value(a)
    self.r(b).from_int(res)
    self._set_flags(res)


@ternary_1.instruction("0000++")
def op_xor(self: Core, a, b):
    res = self.value(b) ^ self.value(a)
    self.r(b).from_int(res)
    self._set_flags(res)


@ternary_1.instruction("000-00")
def op_not(self: Core, a):
    res = ~self.value(a)
    self.r(a).from_int(res)
    self._set_flags(res)


@ternary_1.instruction("000-0-")
def op_jmp(self: Core, addr):
    self.set_pc(self.value(addr))


@ternary_1.instruction("000-0+")
def op_jz(self: Core, addr):
    if self.FLAGS & Flags.ZERO:
        self.set_pc(self.value(addr))


@ternary_1.instruction("000--0")
def op_jnz(self: Core, addr):
    if not (self.FLAGS & Flags.ZERO):
        self.set_pc(self.value(addr))


@ternary_1.instruction("000---")
def op_push(self: Core, r):
    self._push_word(self.value(r))


@ternary_1.instruction("000--+")
def op_pop(self: Core, r):
    self.r(r).from_int(self._pop_word())


@ternary_1.instruction("000-+0")
def op_call(self: Core, addr):
    self._push_word(self._next_pc)
    self.set_pc(self.value(addr))


@ternary_1.instruction("000-+-")
def op_ret(self: Core):
    self.set_pc(self._pop_word())


@ternary_1.instruction("000-++")
def op_nop(self: Core):
    pass


@ternary_1.instruction("000+00")
def op_mul(self: Core, a, b):
    res = self.value(b) * self.value(a)
    self.r(b).from_int(res)
    self._set_flags(res)


@ternary_1.instruction("000+0-")
def op_div(self: Core, a, b):
    res = self.value(b) // self.value(a)
    self.r(b).from_int(res)
    self._set_flags(res)


@ternary_1.instruction("000+0+")
def op_mod(self: Core, a, b):
    res = self.value(b) % self.value(a)
    self.r(b).from_int(res)
    self._set_flags(res)


@ternary_1.instruction("000+-0")
def op_neg(self: Core, a):
    res = -self.value(a)
    self.r(a).from_int(res)
    self._set_flags(res)


@ternary_1.instruction("000+--")
def op_inc(self: Core, a):
    res = self.value(a) + 1
    self.r(a).from_int(res)
    self._set_flags(res)


@ternary_1.instruction("000+-+")
def op_dec(self: Core, a):
    res = self.value(a) - 1
    self.r(a).from_int(res)
    self._set_flags(res)


@ternary_1.instruction("000++0")
def op_abs(self: Core, a):
    res = abs(self.value(a))
    self.r(a).from_int(res)
    self._set_flags(res)


@ternary_1.instruction("000++-")
def op_shl(self: Core, a, b):
    res = self.value(b) << self.value(a)
    self.r(b).from_int(res)
    self._set_flags(res)


@ternary_1.instruction("000+++")
def op_shr(self: Core, a, b):
    res = self.value(b) >> self.value(a)
    self.r(b).from_int(res)
    self._set_flags(res)


@ternary_1.instruction("00+000")
def op_tmin(self: Core, a, b):
    at, bt = self.as_trite(a), self.r(b)
    for i in range(len(bt.trits)):
        bt.trits[i].set(min(bt.trits[i].get(), at.trits[i].get()))
    self._set_flags(int(bt))


@ternary_1.instruction("00+00-")
def op_tmax(self: Core, a, b):
    at, bt = self.as_trite(a), self.r(b)
    for i in range(len(bt.trits)):
        bt.trits[i].set(max(bt.trits[i].get(), at.trits[i].get()))
    self._set_flags(int(bt))


@ternary_1.instruction("00+00+")
def op_negtrit(self: Core, a):
    at = self.r(a)
    for t in at.trits:
        t.set(-t.get())
    self._set_flags(int(at))


@ternary_1.instruction("00+0-0")
def op_cmp(self: Core, a, b):
    self._set_flags(self.value(b) - self.value(a))


@ternary_1.instruction("00+0--")
def op_test(self: Core, a, b):
    self._set_flags(self.value(b) & self.value(a))


@ternary_1.instruction("00+0-+")
def op_jl(self: Core, addr):
    if self.FLAGS & Flags.NEGATIVE:
        self.set_pc(self.value(addr))


@ternary_1.instruction("00+0+0")
def op_jg(self: Core, addr):
    if not (self.FLAGS & (Flags.NEGATIVE | Flags.ZERO)):
        self.set_pc(self.value(addr))


@ternary_1.instruction("00+0+-")
def op_jle(self: Core, addr):
    if self.FLAGS & (Flags.NEGATIVE | Flags.ZERO):
        self.set_pc(self.value(addr))


@ternary_1.instruction("00+0++")
def op_jge(self: Core, addr):
    if not (self.FLAGS & Flags.NEGATIVE):
        self.set_pc(self.value(addr))


@ternary_1.instruction("00+-00")
def op_jc(self: Core, addr):
    if self.FLAGS & Flags.CARRY:
        self.set_pc(self.value(addr))


@ternary_1.instruction("00+-0-")
def op_jnc(self: Core, addr):
    if not (self.FLAGS & Flags.CARRY):
        self.set_pc(self.value(addr))


@ternary_1.instruction("00+-0+")
def op_jo(self: Core, addr):
    if self.FLAGS & Flags.OVERFLOW:
        self.set_pc(self.value(addr))


@ternary_1.instruction("00+--0")
def op_jno(self: Core, addr):
    if not (self.FLAGS & Flags.OVERFLOW):
        self.set_pc(self.value(addr))


@ternary_1.instruction("00+---")
def op_jmpr(self: Core, offset):
    self.set_pc(self._next_pc + self.value(offset))


@ternary_1.instruction("00+--+")
def op_callr(self: Core, offset):
    self._push_word(self._next_pc)
    self.set_pc(self._next_pc + self.value(offset))


@ternary_1.instruction("00+-+0")
def op_lea(self: Core, base, offset, dst):
    self.r(dst).from_int(self.value(base) + self.value(offset))


@ternary_1.instruction("00+-+-")
def op_loado(self: Core, base, offset, dst):
    addr = self.value(base) + self.value(offset)
    self.r(dst).clone_from(self.system.mem.get(addr))


@ternary_1.instruction("00+-++")
def op_storeo(self: Core, base, offset, src):
    addr = self.value(base) + self.value(offset)
    self.system.mem.set(addr, self.as_trite(src))


@ternary_1.instruction("00++00")
def op_pushi(self: Core, imm):
    self._push_word(self.value(imm))


@ternary_1.instruction("00++0-")
def op_adjsp(self: Core, delta):
    self.SP.from_int(int(self.SP) + self.value(delta))


@ternary_1.instruction("00++0+")
def op_movi(self: Core, dst, imm):
    self.r(dst).from_int(self.value(imm))


@ternary_1.instruction("00++-0")
def op_xchg(self: Core, a, b):
    tmp = int(self.r(a))
    self.r(a).clone_from(self.r(b))
    self.r(b).from_int(tmp)


@ternary_1.instruction("00++--")
def op_out(self: Core, port, src):
    with self.system.io_lock:
        self.system.io_out.append((self.value(port), self.value(src)))


@ternary_1.instruction("00++-+")
def op_in(self: Core, port, dst):
    with self.system.io_lock:
        value = self.system.io_in.pop(0) if self.system.io_in else 0
    self.r(dst).from_int(value)


@ternary_1.instruction("00+++0")
def op_enter(self: Core, frame_size):
    self._push_word(int(self.FP))
    self.FP.from_int(int(self.SP))
    self.SP.from_int(int(self.SP) - self.value(frame_size))


@ternary_1.instruction("00+++-")
def op_leave(self: Core):
    self.SP.from_int(int(self.FP))
    self.FP.from_int(self._pop_word())


# ---- disk I/O -----------------------------------------------------------
@ternary_1.instruction("00-000")
def op_dload(self: Core, addr, dst):
    self.r(dst).clone_from(self.system.disk.get(self.value(addr)))


@ternary_1.instruction("00-00-")
def op_dstore(self: Core, addr, src):
    self.system.disk.set(self.value(addr), self.as_trite(src))


@ternary_1.instruction("00-00+")
def op_dloado(self: Core, base, offset, dst):
    addr = self.value(base) + self.value(offset)
    self.r(dst).clone_from(self.system.disk.get(addr))


@ternary_1.instruction("00-0-0")
def op_dstoreo(self: Core, base, offset, src):
    addr = self.value(base) + self.value(offset)
    self.system.disk.set(addr, self.as_trite(src))


# ---- vram I/O -----------------------------------------------------------
@ternary_1.instruction("00--00")
def op_vload(self: Core, addr, dst):
    self.r(dst).clone_from(self.system.vmem.get(self.value(addr)))


@ternary_1.instruction("00--0-")
def op_vstore(self: Core, addr, src):
    self.system.vmem.set(self.value(addr), self.as_trite(src))


@ternary_1.instruction("00--0+")
def op_vloado(self: Core, base, offset, dst):
    addr = self.value(base) + self.value(offset)
    self.r(dst).clone_from(self.system.vmem.get(addr))


@ternary_1.instruction("00---0")
def op_vstoreo(self: Core, base, offset, src):
    addr = self.value(base) + self.value(offset)
    self.system.vmem.set(addr, self.as_trite(src))


@ternary_1.instruction("00----")
def op_vclear(self: Core):
    zero = Trite(trits=5)
    with self.system.vmem.lock:
        for i in range(len(self.system.vmem.vmem)):
            self.system.vmem.vmem[i].clone_from(zero)


@ternary_1.instruction("00---+")
def op_vbuffer_fill(self: Core):
    zero = Trite(trits=5)
    with self.system.vmem.lock:
        for i in range(
            self.system.vbuffer_offset,
            self.system.vbuffer_offset + self.system.vbuffer_alloc,
        ):
            self.system.vmem.vmem[i].clone_from(zero)


# ---- GPU dispatch --------------------------------------------------------
@ternary_1.instruction("0+0000")
def op_gproc(self: Core, opcode, a, b, c, d, e, f):
    """Dispatches one job to the GPU's own instruction set (FILL=0,
    BLIT=1, LINE=2) instead of running it as ternary instructions, one
    per pixel, on this core. Always takes the same 7 operands (opcode +
    6 data slots), like a fixed-size hardware command packet; ops
    needing fewer than 6 data args (e.g. LINE) just leave the trailing
    ones unused. Asynchronous: the job is queued for the GPU cores and
    this core continues immediately. Use GSYNC to wait for completion.

        FILL: a=dst_addr, b=pitch, c=width,  d=height, e=color, f=rop
        BLIT: a=src_addr, b=dst_addr, c=pitch, d=width, e=height, f=rop
        LINE: a=addr0, b=addr1, c=pitch, d=color, e=rop
    """
    op = self.value(opcode)
    args = (
        self.value(a),
        self.value(b),
        self.value(c),
        self.value(d),
        self.value(e),
        self.value(f),
    )
    self.system.gpu_queue.put((op, args))


@ternary_1.instruction("0+000-")
def op_gsync(self: Core):
    """Blocks this core until every GPU job dispatched so far (by any
    core) has finished -- the fence a CPU must wait on before reading
    vmem results from an asynchronous GPROC."""
    self.system.gpu_queue.join()


# ---- System State & Multicore Concurrency ------------------------------
@ternary_1.instruction("00--+0")
def op_getstate(self: Core, dst):
    """Pulls the entire 16-trit shared state register into a local register."""
    self.r(dst).clone_from(self.system.state.get_full_state())


@ternary_1.instruction("00--+-")
def op_acq(self: Core, lock_id):
    """
    ATOMIC ACQUIRE: Attempts to lock the trit at `lock_id` index in the shared state.
    If it is already locked by another core, it rewinds the PC to spin-wait (busy loop)
    until the lock becomes available.
    """
    idx = self.value(lock_id)
    if not self.system.state.atomic_test_and_set(idx):
        # The lock is taken. Rewind the Program Counter to the current instruction.
        # This creates a "Spinlock" where the core will keep retrying this instruction.
        self.set_pc(int(self.PC))


@ternary_1.instruction("00--++")
def op_rel(self: Core, lock_id):
    """ATOMIC RELEASE: Unlocks the trit at `lock_id` index in the shared state."""
    idx = self.value(lock_id)
    self.system.state.release(idx)


@ternary_1.instruction("00-+-0")
def op_coreid(self: Core, dst):
    """Loads the executing Core's hardware ID into the destination register."""
    self.r(dst).from_int(self.core_id)


# Initialize a Dual-Core System
system = TernarySystem(ternary_1, num_cores=2)

if __name__ == "__main__":
    # Start all threads
    system.start_all()
    # Wait for completion (if they ever halt)
    system.join_all()

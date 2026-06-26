import os
from types import SimpleNamespace
from multiprocessing import Process, Event, Lock, JoinableQueue, Queue, RawArray, Value



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
# MEMORY (raw int array, shared across processes via RawArray)
# =========================
class Memory:
    def __init__(self, size, trit_width=16):
        self._trit_width = trit_width
        self._raw = RawArray("i", size)
        self._lock = Lock()

    @property
    def mem(self):
        # backward compat: len(system.mem.mem) still works
        return self._raw

    def get(self, addr) -> "Trite":
        with self._lock:
            val = self._raw[int(addr)]
        return Trite(trits=self._trit_width).from_int(val)

    def set(self, addr, val):
        with self._lock:
            self._raw[int(addr)] = int(val)

    @property
    def lock(self):
        return self._lock


# =========================
# VIDEO MEMORY (raw ints: 5-trit pixel values in [-121, 121])
# =========================
class VideoMemory:
    def __init__(self, size):
        self._raw = RawArray("i", size)
        self._lock = Lock()

    def get(self, addr) -> int:
        return self._raw[int(addr)]

    def set(self, addr, val):
        self._raw[int(addr)] = int(val)

    @property
    def lock(self):
        return self._lock

    @property
    def vmem(self):
        # backward compat for display code that reads system.vmem.vmem
        return self._raw


# =========================
# GPU (fill, blit, line -- operates directly on raw int vmem)
# =========================
class GPU:
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

    @staticmethod
    def _clamp(val, limit=121):
        if val > limit or val < -limit:
            return val % (limit * 2 + 1)
        return val

    def _combine(self, rop, src, dst):
        if rop == self.ROP_XOR:
            return src ^ dst
        if rop == self.ROP_AND:
            return src & dst
        if rop == self.ROP_OR:
            return src | dst
        if rop == self.ROP_ADD:
            return self._clamp(src + dst)
        if rop == self.ROP_SUB:
            return self._clamp(dst - src)
        return src  # ROP_COPY

    def fill(self, dst_addr, pitch, width, height, color, rop):
        raw = self.vmem._raw
        size = len(raw)
        with self.vmem._lock:
            for row in range(height):
                base = dst_addr + row * pitch
                if base < 0 or base + width > size:
                    continue
                for col in range(width):
                    idx = base + col
                    raw[idx] = self._combine(rop, color, raw[idx])

    def blit(self, src_addr, dst_addr, pitch, width, height, rop):
        raw = self.vmem._raw
        size = len(raw)
        with self.vmem._lock:
            for row in range(height):
                srow = src_addr + row * pitch
                drow = dst_addr + row * pitch
                if srow < 0 or srow + width > size or drow < 0 or drow + width > size:
                    continue
                # Snapshot source row before writing to handle src/dst overlap.
                src_vals = list(raw[srow : srow + width])
                for col in range(width):
                    raw[drow + col] = self._combine(rop, src_vals[col], raw[drow + col])

    def line(self, addr0, addr1, pitch, color, rop):
        x0, y0 = addr0 % pitch, addr0 // pitch
        x1, y1 = addr1 % pitch, addr1 // pitch
        raw = self.vmem._raw
        size = len(raw)
        dx = abs(x1 - x0)
        dy = abs(y1 - y0)
        sx = 1 if x1 >= x0 else -1
        sy = 1 if y1 >= y0 else -1
        err = dx - dy
        x, y = x0, y0
        with self.vmem._lock:
            while True:
                addr = y * pitch + x
                if 0 <= addr < size:
                    raw[addr] = self._combine(rop, color, raw[addr])
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
    def __init__(self, trits=16):
        self._raw = RawArray("i", trits)
        self._lock = Lock()

    def atomic_test_and_set(self, index, test_val=Trit.MID, set_val=Trit.HI) -> bool:
        with self._lock:
            if self._raw[index] == test_val:
                self._raw[index] = set_val
                return True
            return False

    def release(self, index, reset_val=Trit.MID):
        with self._lock:
            self._raw[index] = reset_val

    def get_full_state(self):
        with self._lock:
            clone = Trite(trits=len(self._raw))
            for i in range(len(self._raw)):
                clone.trits[i].set(self._raw[i])
            return clone


# =========================
# DISK (mp.Lock + pickle support for cross-process use)
# =========================
class Disk:
    _PLAIN_ENCODE = {-1: ord("-"), 0: ord("0"), 1: ord("+")}
    _PLAIN_DECODE = {ord("-"): -1, ord("0"): 0, ord("+"): 1}

    def __init__(self, path: str, size: int, trits: int = 16, plain: bool = False):
        self.path = path
        self.size = size
        self.trits = trits
        self.plain = plain
        self.lock = Lock()

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

    def __getstate__(self):
        # File handles can't be pickled; reopen in each child process.
        state = self.__dict__.copy()
        del state["file"]
        return state

    def __setstate__(self, state):
        self.__dict__.update(state)
        self.file = open(self.path, "r+b")

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

    def add(self, opcode: "str | Trite", operandslength, func):
        if isinstance(opcode, str):
            self.instructions[opcode] = (operandslength, func)
        else:
            self.instructions[str(opcode)] = (operandslength, func)

    def get(self, opcode: "str | Trite"):
        entry = self.instructions.get(
            str(opcode) if isinstance(opcode, Trite) else opcode
        )
        return entry[1] if entry is not None else None

    def get_opcount(self, opcode: "str | Trite"):
        entry = self.instructions.get(
            str(opcode) if isinstance(opcode, Trite) else opcode
        )
        return entry[0] if entry is not None else None

    def instruction(self, opcode: "str | Trite"):
        def wrapper(func):
            self.add(opcode, func.__code__.co_argcount - 1, func)
            return func

        return wrapper


def encode_instruction(opcode: str, operands: list) -> "list[Trite]":
    """One 16-trit header word (6-trit opcode + 2-trit count field + an
    8-trit reftype map, one trit per operand slot -- MID=immediate,
    LO=register, matching up to the ISA's 8-operand cap) followed by one
    full 16-trit word per operand. Memory words are 16 trits wide, so
    every operand value (already <= a 16-trit range) fits in exactly one
    word; no more splitting a value across a low/high word pair."""
    count_field = str(Trite(trits=2).from_int(len(operands) - 4))
    reftype_field = "".join(
        "0" if isinstance(op, Immediate) else "-" for op in operands
    ).ljust(8, "0")
    header = Trite(trits=16).from_str(opcode + count_field + reftype_field)

    words = [header]
    for op in operands:
        value = op.value if isinstance(op, Immediate) else op
        words.append(Trite(trits=16).from_int(value))
    return words



# =========================
# GPU CORE (multiprocessing worker -- drains gpu_queue)
# =========================


def _gpu_worker(vmem_raw, vmem_lock, gpu_queue, gpu_opcount):
    """Top-level GPU worker: reconstruct vmem from shared primitives, drain queue.

    Must be a top-level function (not a method) so Windows spawn can pickle it
    by name without serialising the TernarySystem object graph.
    """
    vmem = VideoMemory.__new__(VideoMemory)
    vmem._raw = vmem_raw
    vmem._lock = vmem_lock
    gpu = GPU(vmem)
    while True:
        job = gpu_queue.get()
        if job is None:
            gpu_queue.task_done()
            break
        opcode, args = job
        try:
            if opcode == GPU.OPCODE_FILL:
                gpu.fill(*args)
            elif opcode == GPU.OPCODE_BLIT:
                gpu.blit(*args)
            elif opcode == GPU.OPCODE_LINE:
                gpu.line(*args[:5])
        finally:
            gpu_opcount.value += 1
            gpu_queue.task_done()


class GPUCore(Process):
    def __init__(self, gpu_id, system):
        # Pass only the shared primitives needed by _gpu_worker, not system
        # itself.  Storing system would embed all other Core/GPUCore Process
        # objects in the pickle tree, which Python 3.12 on Windows rejects.
        super().__init__(
            target=_gpu_worker,
            args=(
                system.vmem._raw,
                system.vmem._lock,
                system.gpu_queue,
                system._gpu_opcount,
            ),
            name=f"GPU-{gpu_id}",
            daemon=True,
        )
        self.gpu_id = gpu_id


# =========================
# CPU CORE (multiprocessing -- one process per core)
# =========================
class Core(Process):
    def __init__(self, core_id, system, isa):
        super().__init__(name=f"Core-{core_id}", daemon=True)
        self.core_id = core_id
        self.system = system
        self.isa = isa

        # Local state -- not shared; each process owns its own registers.
        self.registers = [Trite(trits=16) for _ in range(16)]
        self.PC = Trite(trits=16)
        self.SP = Trite(trits=16)
        self.FP = Trite(trits=16)
        self.PSR = Trite(trits=16)  # power state register
        self.FLAGS = 0
        # mp.Event is backed by OS semaphore: shared between parent and child
        # so stop_all() (parent) and op_halt (child) both reach the same flag.
        self._halt = Event()
        self._jumped = False
        self._next_pc = 0

        # Stash the individual shared primitives needed to reconstruct system
        # in the child process.  __getstate__ will drop self.system (which
        # contains other unstarted Process objects) and keep only these, which
        # are all picklable mp primitives.
        self._s_mem_raw = system.mem._raw
        self._s_mem_lock = system.mem._lock
        self._s_vmem_raw = system.vmem._raw
        self._s_vmem_lock = system.vmem._lock
        self._s_state_raw = system.state._raw
        self._s_state_lock = system.state._lock
        self._s_disk_path = system.disk.path
        self._s_disk_size = system.disk.size
        self._s_disk_trits = system.disk.trits
        self._s_disk_plain = system.disk.plain
        self._s_boot_path = system.bootsector.path
        self._s_boot_size = system.bootsector.size
        self._s_boot_trits = system.bootsector.trits
        self._s_boot_plain = system.bootsector.plain
        self._s_gpu_queue = system.gpu_queue
        self._s_gpu_opc = system._gpu_opcount
        self._s_io_lock  = system.io_lock
        self._s_io_out_q = system._io_out_q
        self._s_io_in_q  = system._io_in_q

        self._s_step = system._step_counts[core_id]
        self._s_vbuf_alloc = system.vbuffer_alloc
        self._s_vbuf_off = system.vbuffer_offset
        self._s_num_cores = system.num_cores
        self._s_num_gcores = system.num_graphical_cores

    def __getstate__(self):
        # Windows spawn pickles the entire Process object.  Drop attributes
        # that contain other Process objects (system.cores / system.gpu_cores),
        # which Python 3.12 cannot pickle via ForkingPickler.
        state = self.__dict__.copy()
        del state["system"]  # rebuilt in __setstate__ from _s_* primitives
        del state["isa"]  # module-level global; not safely picklable by value
        del state["registers"]  # child starts with clean register file
        del state["PC"]
        del state["SP"]
        del state["FP"]
        return state

    def __setstate__(self, state):
        self.__dict__.update(state)
        # Rebuild lightweight wrappers from the shared primitives.
        mem = Memory.__new__(Memory)
        mem._trit_width = 16
        mem._raw = self._s_mem_raw
        mem._lock = self._s_mem_lock

        vmem = VideoMemory.__new__(VideoMemory)
        vmem._raw = self._s_vmem_raw
        vmem._lock = self._s_vmem_lock

        state_obj = SharedState.__new__(SharedState)
        state_obj._raw = self._s_state_raw
        state_obj._lock = self._s_state_lock

        disk = Disk(
            self._s_disk_path,
            self._s_disk_size,
            trits=self._s_disk_trits,
            plain=self._s_disk_plain,
        )
        boot = Disk(
            self._s_boot_path,
            self._s_boot_size,
            trits=self._s_boot_trits,
            plain=self._s_boot_plain,
        )

        step_counts = [None] * 16
        step_counts[self.core_id] = self._s_step
        sys = SimpleNamespace(
            mem=mem,
            vmem=vmem,
            state=state_obj,
            disk=disk,
            bootsector=boot,
            gpu_queue=self._s_gpu_queue,
            gpu=GPU(vmem),
            io_lock=self._s_io_lock,
            io_in=[],
            io_out=[],
            _io_out_q=self._s_io_out_q,
            _io_in_q=self._s_io_in_q,
            _step_counts=step_counts,
            _gpu_opcount=self._s_gpu_opc,
            vbuffer_alloc=self._s_vbuf_alloc,
            vbuffer_offset=self._s_vbuf_off,
            num_cores=self._s_num_cores,
            num_graphical_cores=self._s_num_gcores,
        )

        self.system = sys
        self.isa = (
            ternary_1  # module-level global; available after cpu.py import in child
        )
        self.registers = [Trite(trits=16) for _ in range(16)]
        self.PC = Trite(trits=16)
        self.SP = Trite(trits=16)
        self.FP = Trite(trits=16)

    @property
    def HALTED(self):
        return self._halt.is_set()

    @HALTED.setter
    def HALTED(self, value):
        if value:
            self._halt.set()
        else:
            self._halt.clear()

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
        # Memory words are now 16 trits -- the same width as a register --
        # so a stack slot is exactly one word, no more low/high split.
        self.SP.from_int(int(self.SP) - 1)
        self.system.mem.set(self.SP, Trite(trits=16).from_int(value))

    def _pop_word(self) -> int:
        value = int(self.system.mem.get(self.SP))
        self.SP.from_int(int(self.SP) + 1)
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
        if self._halt.is_set():
            return

        psr = int(self.PSR)
        if psr == 3:  # trit[1]=+1 → restart
            self.system.stop_all()
            self.system.start_all()
            return
        elif psr == 1:  # trit[0]=+1 → shutdown
            self.system.stop_all()
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
        reftype = header[8:16]  # same word as the opcode/count -- no separate fetch
        operands = []

        for i in range(op_count):  # type: ignore
            word = self.system.mem.get(base + 1 + i)
            value = int(word)
            tag = reftype.trits[i].get()
            if tag == Trit.MID:
                operands.append(Immediate(value))
            else:
                operands.append(value % 16)

        func = self.isa.get(opcode_str)
        if func is not None:
            self._next_pc = base + 1 + op_count  # type: ignore
            self._jumped = False
            func(self, *operands)
            if not self._jumped:
                self.PC.from_int(self._next_pc)
        else:
            self.PC.from_int(base + 1 + op_count)  # type: ignore

        self.system._step_counts[self.core_id].value += 1

    def run(self):
        while not self._halt.is_set():
            self.step()


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
        ram_size=6561,
    ):
        self.num_cores = num_cores
        self.num_graphical_cores = num_graphical_cores

        self.mem = Memory(ram_size)
        self.vmem = VideoMemory(640 * 480 + 6561)
        self.state = SharedState(16)

        self.vbuffer_alloc = 640 * 480
        self.vbuffer_offset = 0

        self.io_lock = Lock()
        self.io_in = []
        self.io_out = []
        self._io_out_q = Queue()   # cross-process; drained by drain_io_out()
        self._io_in_q  = Queue()   # cross-process; filled by push_input()

        self.disk = Disk(disk_path, disk_size, plain=plain)
        self.bootsector = Disk(
            self.DEFAULT_BOOTSECTOR_PATH, self.DEFAULT_BOOTSECTOR_SIZE, plain=plain
        )

        # Shared counters readable from any process (lock=False is safe here:
        # each core writes only its own slot; display reads are approximate).
        self._step_counts = [Value("l", 0, lock=False) for _ in range(num_cores)]
        self._gpu_opcount = Value("l", 0, lock=False)

        # gpu_queue must exist before Core objects are built so Core.__init__
        # can stash it as a picklable primitive for the child process.
        self.gpu = GPU(self.vmem)
        self.gpu_queue = JoinableQueue()

        self.cores = [Core(i, self, isa) for i in range(num_cores)]
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
            core.HALTED = True
        for _ in self.gpu_cores:
            self.gpu_queue.put(None)  # one sentinel per GPU core

    def drain_io_out(self) -> list:
        """Collect all (port, value) tuples written by OUT instructions across
        all cores since the last call.  Non-blocking; drains the shared queue."""
        results = []
        while not self._io_out_q.empty():
            try:
                results.append(self._io_out_q.get_nowait())
            except Exception:
                break
        self.io_out.extend(results)
        return results

    def push_input(self, char_int: int) -> None:
        """Send a character code to the CPU (consumed by IN instructions)."""
        self._io_in_q.put(char_int)

    def join_all(self):
        # Ensure any running GPU cores get a shutdown sentinel so they can
        # exit cleanly.  Extra sentinels are harmless if stop_all() was
        # already called (dead workers don't read from the queue).
        for gc in self.gpu_cores:
            if gc.pid is not None and gc.is_alive():
                self.gpu_queue.put(None)
        for core in self.cores:
            if core.pid is not None:
                core.join()
        for gpu_core in self.gpu_cores:
            if gpu_core.pid is not None:
                gpu_core.join()


ternary_1 = InstructionSet()


# ---- Core Logic & Memory Instructions ---------------------------
@ternary_1.instruction("000000")
def op_halt(self: Core):
    self.HALTED = True


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
    entry = (self.value(port), self.value(src))
    self.system._io_out_q.put(entry)
    with self.system.io_lock:
        self.system.io_out.append(entry)


@ternary_1.instruction("00++-+")
def op_in(self: Core, port, dst):
    # Block until a character arrives; poll with timeout so halt is honoured.
    value = 0
    while not self._halt.is_set():
        try:
            value = self.system._io_in_q.get(timeout=0.05)
            break
        except Exception:
            pass
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


# ---- Disk I/O -----------------------------------------------------------
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


# ---- VRAM I/O (vmem stores raw ints; get/set use int values directly) ----
@ternary_1.instruction("00--00")
def op_vload(self: Core, addr, dst):
    self.r(dst).from_int(self.system.vmem.get(self.value(addr)))


@ternary_1.instruction("00--0-")
def op_vstore(self: Core, addr, src):
    self.system.vmem.set(self.value(addr), self.value(src))


@ternary_1.instruction("00--0+")
def op_vloado(self: Core, base, offset, dst):
    addr = self.value(base) + self.value(offset)
    self.r(dst).from_int(self.system.vmem.get(addr))


@ternary_1.instruction("00---0")
def op_vstoreo(self: Core, base, offset, src):
    addr = self.value(base) + self.value(offset)
    self.system.vmem.set(addr, self.value(src))


@ternary_1.instruction("00----")
def op_vclear(self: Core):
    raw = self.system.vmem._raw
    with self.system.vmem.lock:
        for i in range(len(raw)):
            raw[i] = 0


@ternary_1.instruction("00---+")
def op_vbuffer_fill(self: Core):
    raw = self.system.vmem._raw
    with self.system.vmem.lock:
        for i in range(
            self.system.vbuffer_offset,
            self.system.vbuffer_offset + self.system.vbuffer_alloc,
        ):
            raw[i] = 0


# ---- GPU Dispatch --------------------------------------------------------
@ternary_1.instruction("0+0000")
def op_gproc(self: Core, opcode, a, b, c, d, e, f):
    """Enqueue one GPU job (FILL / BLIT / LINE).  Asynchronous; use GSYNC to fence.

    FILL: a=dst_addr, b=pitch, c=width, d=height, e=color, f=rop
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
    """Block until every queued GPU job has completed."""
    self.system.gpu_queue.join()


# ---- Disk I/O ----------------------------------------------------------
# Sector size: 81 cells (3^4).  The virtual disk holds DEFAULT_DISK_SIZE=19683
# cells → 243 sectors.  DISKREAD/DISKWRITE each transfer exactly one sector.
SECTOR_SIZE = 81


@ternary_1.instruction("0+000+")
def op_diskread(self: Core, dst_ram, disk_sector):
    """Read one sector (SECTOR_SIZE cells) from disk into RAM.

    dst_ram    — RAM address of the first cell to write (register or immediate)
    disk_sector — sector index on disk (register or immediate)
    """
    ram_base    = self.value(dst_ram)
    sector_num  = self.value(disk_sector)
    disk_base   = sector_num * SECTOR_SIZE
    disk        = self.system.disk
    for i in range(SECTOR_SIZE):
        word = disk.get(disk_base + i)          # acquires disk.lock briefly
        self.system.mem.set(ram_base + i, word) # acquires mem._lock briefly


@ternary_1.instruction("0+00-0")
def op_diskwrite(self: Core, src_ram, disk_sector):
    """Write one sector (SECTOR_SIZE cells) from RAM to disk.

    src_ram    — RAM address of the first cell to read (register or immediate)
    disk_sector — sector index on disk (register or immediate)
    """
    ram_base    = self.value(src_ram)
    sector_num  = self.value(disk_sector)
    disk_base   = sector_num * SECTOR_SIZE
    disk        = self.system.disk
    for i in range(SECTOR_SIZE):
        word = self.system.mem.get(ram_base + i)
        disk.set(disk_base + i, word)


@ternary_1.instruction("0+00-+")
def op_disksize(self: Core, dst):
    """Load the total number of disk sectors into dst."""
    n_sectors = self.system.disk.size // SECTOR_SIZE
    self.r(dst).from_int(n_sectors)


# ---- Shared State & Multicore Concurrency ------------------------------
@ternary_1.instruction("00--+0")
def op_getstate(self: Core, dst):
    self.r(dst).clone_from(self.system.state.get_full_state())


@ternary_1.instruction("00--+-")
def op_acq(self: Core, lock_id):
    idx = self.value(lock_id)
    if not self.system.state.atomic_test_and_set(idx):
        self.set_pc(int(self.PC))  # spin: rewind to this instruction


@ternary_1.instruction("00--++")
def op_rel(self: Core, lock_id):
    idx = self.value(lock_id)
    self.system.state.release(idx)


@ternary_1.instruction("00-+++")
def op_coreid(self: Core, dst):
    self.r(dst).from_int(self.core_id)


@ternary_1.instruction("00-+-+")
def op_numcores(self: Core, dst):
    """Loads the number of hardware cores into the destination register."""
    self.r(dst).from_int(self.system.num_cores)


@ternary_1.instruction("00-+-0")
def op_numgcores(self: Core, dst):
    """Loads the number of graphical (GPU) cores into the destination register."""
    self.r(dst).from_int(self.system.num_graphical_cores)


if __name__ == "__main__":
    system = TernarySystem(ternary_1, num_cores=2)
    system.start_all()
    system.join_all()

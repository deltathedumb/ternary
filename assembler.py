#!/usr/bin/env python3
"""
Ternary Assembler with Directive Support
Converts text assembly into a Sparse Memory Map of Ternary words.
"""

from cpu import Trite, Immediate, ternary_1, encode_instruction


class AssemblerError(Exception):
    pass


def _build_mnemonic_table() -> dict[str, tuple[str, int]]:
    table = {}
    for opcode_str, (op_count, func) in ternary_1.instructions.items():
        name = func.__name__
        if name.startswith("op_"):
            table[name[3:].upper()] = (opcode_str, op_count)
    return table


MNEMONICS = _build_mnemonic_table()


def _strip_comment(line: str) -> str:
    for marker in (";", "//"):
        idx = line.find(marker)
        if idx != -1:
            line = line[:idx]
    return line.strip()


def _tokenize_line(line: str):
    line = _strip_comment(line)
    if not line:
        return None, None, []

    label = None
    head = line.split(None, 1)[0]
    if head.endswith(":"):
        label = head[:-1]
        line = line[len(head) :].strip()
        if not line:
            return label, None, []

    parts = line.split(None, 1)
    mnemonic = parts[0].upper()
    operand_str = parts[1] if len(parts) > 1 else ""
    operands = [tok.strip() for tok in operand_str.split(",") if tok.strip()]
    return label, mnemonic, operands


def _is_register(token: str) -> bool:
    return len(token) > 1 and token[0].lower() == "r" and token[1:].isdigit()


def _parse_operand(token: str, symbols: dict[str, int]):
    if _is_register(token):
        return int(token[1:])

    # If it's an immediate value (starts with #)
    if token.startswith("#"):
        value = token[1:]
        if value in symbols:
            return Immediate(symbols[value])
        return Immediate(int(value, 0))

    # If it's a known symbol/label (used as an address or constant)
    if token in symbols:
        return Immediate(symbols[token])

    # Otherwise, try to parse it as a raw integer
    try:
        return Immediate(int(token, 0))
    except ValueError:
        raise AssemblerError(f"Unknown operand or undefined label: {token!r}")


def assemble(source: str) -> dict[int, Trite]:
    """
    Assembles code into a dictionary mapping Memory Addresses to Trite words.
    Allows for gaps in memory (Sparse Memory Map).
    """
    symbols: dict[str, int] = {}  # Holds both Labels and .equ Constants
    parsed_lines = []
    addr = 0

    # ==========================================
    # PASS 1: Map all labels and constants
    # ==========================================
    for lineno, raw in enumerate(source.splitlines(), start=1):
        clean_line = _strip_comment(raw).strip()
        if not clean_line:
            continue

        # Handle .equ Directive (Constants)
        if clean_line.lower().startswith(".equ"):
            parts = clean_line.split()
            if len(parts) != 3:
                raise AssemblerError(f"line {lineno}: .equ requires a name and a value")
            name = parts[1]
            val = int(parts[2], 0)  # Parses dec, hex (0x), bin (0b)
            symbols[name] = val
            continue

        # Handle .org Directive (Address Jump)
        if clean_line.lower().startswith(".org"):
            parts = clean_line.split()
            if len(parts) != 2:
                raise AssemblerError(f"line {lineno}: .org requires an address")
            addr = int(parts[1], 0)
            parsed_lines.append((lineno, ".ORG", None, [parts[1]]))
            continue

        # Ignore semantic section markers
        if clean_line.lower() in (".text", ".data"):
            continue

        # Standard Instructions and Labels
        label, mnemonic, operand_tokens = _tokenize_line(raw)

        if label is not None:
            if label in symbols:
                raise AssemblerError(
                    f"line {lineno}: duplicate label or constant {label!r}"
                )
            symbols[label] = addr

        if mnemonic is None:
            continue

        if mnemonic == "DAT":
            op_count = len(operand_tokens)
            parsed_lines.append((lineno, mnemonic, None, operand_tokens))
            addr += op_count
        else:
            if mnemonic not in MNEMONICS:
                raise AssemblerError(f"line {lineno}: unknown mnemonic {mnemonic!r}")
            opcode_str, op_count = MNEMONICS[mnemonic]
            parsed_lines.append((lineno, mnemonic, opcode_str, operand_tokens))
            addr += 1 + op_count  # 1 header word + 1 word/operand (16-trit words)

    # ==========================================
    # PASS 2: Encode machine code at exact addresses
    # ==========================================
    memory_map: dict[int, Trite] = {}
    current_addr = 0

    for lineno, mnemonic, opcode_str, operand_tokens in parsed_lines:
        try:
            if mnemonic == ".ORG":
                current_addr = int(operand_tokens[0], 0)
                continue

            if mnemonic == "DAT":
                for tok in operand_tokens:
                    # Support raw ternary strings (e.g., +0-0+0-0). Trit 0 is
                    # the least-significant digit (Trite's string convention
                    # is little-endian), so padding to the target width must
                    # go on the right to preserve the literal's value.
                    if all(c in "+0-" for c in tok) and len(tok) <= 16:
                        memory_map[current_addr] = Trite(trits=16).from_str(tok.ljust(16, "0"))
                    else:
                        val = _parse_operand(tok, symbols)
                        int_val = val.value if isinstance(val, Immediate) else val
                        memory_map[current_addr] = Trite(trits=16).from_int(int_val)
                    current_addr += 1
            else:
                op_count = len(operand_tokens)
                next_pc = current_addr + 1 + op_count  # 1 header word + 1 word/operand
                operands = []

                for tok in operand_tokens:
                    # Auto-calculate relative offsets for jumps
                    if mnemonic in ("JMPR", "CALLR") and tok in symbols:
                        relative_offset = symbols[tok] - next_pc
                        operands.append(Immediate(relative_offset))
                    else:
                        operands.append(_parse_operand(tok, symbols))

                encoded_words = encode_instruction(opcode_str, operands)
                for word in encoded_words:
                    memory_map[current_addr] = word
                    current_addr += 1

        except AssemblerError as e:
            raise AssemblerError(f"line {lineno}: {e}") from e

    return memory_map


def assemble_to_plain_text(source: str) -> str:
    """Outputs the compiled program with memory addresses for debugging."""
    memory_map = assemble(source)
    output = []
    # Sort addresses so the output is chronological
    for addr in sorted(memory_map.keys()):
        output.append(f"ADDR {addr:04}: {memory_map[addr]}")
    return "\n".join(output)


def load_into(target, source: str):
    """Loads the compiled memory map directly into the hardware target."""
    memory_map = assemble(source)
    for addr, word in memory_map.items():
        target.set(addr, word)
    return len(memory_map)


# Mirrors Disk._encode_trit / Disk's blank-fill byte in cpu.py, so a raw
# image written here is byte-for-byte what TernarySystem's own Disk would
# produce reading the same program off of it.
_PLAIN_ENCODE = {-1: ord("-"), 0: ord("0"), 1: ord("+")}


def assemble_to_raw_disk(source: str, size: int, plain: bool = False) -> bytes:
    """Assembles `source` and renders it as a raw virtual disk image: `size`
    trites (16-trit words), each word 16 bytes, in the exact on-disk encoding
    `Disk.get`/`Disk.set` (cpu.py) read and write. Addresses the program
    doesn't touch are filled with the same byte a freshly created `Disk`
    starts with, so the image is indistinguishable from one `TernarySystem`
    built itself and then loaded the program into.
    """
    memory_map = assemble(source)
    if memory_map:
        max_addr = max(memory_map.keys())
        if max_addr >= size:
            raise AssemblerError(
                f"program uses address {max_addr}, which is past the "
                f"requested disk size of {size} trites"
            )

    WORD_TRITS = 16
    fill_byte = ord("0") if plain else 0x00
    image = bytearray([fill_byte] * (size * WORD_TRITS))
    for addr, word in memory_map.items():
        offset = addr * WORD_TRITS
        for i in range(WORD_TRITS):
            value = word.get(i)
            image[offset + i] = _PLAIN_ENCODE[value] if plain else value + 1
    return bytes(image)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Ternary Assembler")
    parser.add_argument("program", help="path to the .asm source file")
    parser.add_argument(
        "--emit-raw",
        metavar="SIZE",
        type=int,
        help="write a raw virtual disk image of SIZE trites instead of "
        "printing the assembled program",
    )
    parser.add_argument(
        "-o",
        "--output",
        metavar="PATH",
        help="output path for --emit-raw (default: virtualstorage.raw)",
    )
    parser.add_argument(
        "--plain",
        action="store_true",
        help="use plain ASCII (+/0/-) trit encoding for --emit-raw, "
        "matching Disk(plain=True) in cpu.py",
    )
    args = parser.parse_args()

    with open(args.program) as f:
        text = f.read()

    try:
        if args.emit_raw is not None:
            image = assemble_to_raw_disk(text, args.emit_raw, plain=args.plain)
            out_path = args.output or "virtualstorage.raw"
            with open(out_path, "wb") as f:
                f.write(image)
            print(f"wrote {len(image)} bytes ({args.emit_raw} trites) to {out_path}")
        else:
            print(assemble_to_plain_text(text))
    except AssemblerError as e:
        print(f"assembler error: {e}")
        raise SystemExit(1)

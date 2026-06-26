"""
os_gui.py — GUI OS runner for the ternary computer.

Usage:
    python os_gui.py [--build-dir <dir>]  (default: ./os_build)

A pygame window split into two panels:
  Left:  terminal — OS boot log and program output (OUT port 0)
  Right: live stats — CPU state, IPS, elapsed time, memory
"""

import argparse
import pathlib
import struct
import sys
import time

import pygame

_HERE = pathlib.Path(__file__).parent.resolve()
_ASMPYTHON = _HERE.parent / "asmpython"
if str(_ASMPYTHON) not in sys.path:
    sys.path.insert(0, str(_ASMPYTHON))
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from cpu import TernarySystem, ternary_1

# ── Layout ─────────────────────────────────────────────────────────────────────
TERM_W   = 520
STATS_W  = 260
WIN_W    = TERM_W + STATS_W
WIN_H    = 480
FPS      = 30
PADDING  = 10

# ── Palette ───────────────────────────────────────────────────────────────────
BG_TERM  = (10,  12,  18)
BG_STATS = (18,  20,  28)
CYAN     = (70,  210, 255)
YELLOW   = (255, 235, 60)
GREEN    = (70,  240, 120)
ORANGE   = (255, 170, 50)
RED      = (255, 70,  70)
WHITE    = (230, 230, 235)
GRAY     = (130, 135, 148)
DIVIDER  = (45,  48,  62)
PROMPT   = (80,  200, 120)


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_tern_words(path: pathlib.Path) -> list[int]:
    raw = path.read_bytes()
    return list(struct.unpack_from(f"<{len(raw)//4}i", raw))


def _wrap_line(text: str, font, max_w: int) -> list[str]:
    """Split a string into lines that fit within max_w pixels."""
    if not text:
        return [""]
    words = text.split(" ")
    lines, cur = [], ""
    for w in words:
        candidate = (cur + " " + w).lstrip()
        if font.size(candidate)[0] <= max_w:
            cur = candidate
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines or [""]


# ── Terminal ──────────────────────────────────────────────────────────────────

class Terminal:
    """Scrollable text terminal rendered onto a Surface."""

    def __init__(self, surface: pygame.Surface, font: pygame.font.Font):
        self.surf = surface
        self.font = font
        self.lh = font.get_height() + 2
        self.max_w = surface.get_width() - PADDING * 2
        self.lines: list[tuple[str, tuple]] = []  # (text, color)
        self.scroll = 0          # lines scrolled from bottom

    def write(self, text: str, color=WHITE):
        for line in _wrap_line(text, self.font, self.max_w):
            self.lines.append((line, color))

    def blank(self):
        self.lines.append(("", WHITE))

    def append_char(self, ch: str) -> None:
        """Stream a single character into the terminal (from CPU port 1 output)."""
        if not ch:
            return
        if ch == "\n":
            # Flush the current pending line and start fresh
            if not self.lines or self.lines[-1][1] != GREEN:
                self.lines.append(("", GREEN))
            self.lines.append(("", GREEN))
            self.scroll = 0   # auto-scroll to bottom on new output
            return
        if ch == "\b":
            # Backspace: remove last char from the last line
            if self.lines and self.lines[-1][1] == GREEN:
                t, c = self.lines[-1]
                if t:
                    self.lines[-1] = (t[:-1], c)
            return
        # Append char to the last line (or start one)
        if not self.lines or self.lines[-1][1] != GREEN:
            self.lines.append(("", GREEN))
        t, c = self.lines[-1]
        self.lines[-1] = (t + ch, c)

    def render(self):
        self.surf.fill(BG_TERM)
        visible = self.surf.get_height() // self.lh
        start = max(0, len(self.lines) - visible - self.scroll)
        end   = min(len(self.lines), start + visible)
        for row, (text, color) in enumerate(self.lines[start:end]):
            self.surf.blit(self.font.render(text, True, color),
                           (PADDING, PADDING + row * self.lh))

    def scroll_up(self, n=3):
        max_scroll = max(0, len(self.lines) - (self.surf.get_height() // self.lh))
        self.scroll = min(self.scroll + n, max_scroll)

    def scroll_down(self, n=3):
        self.scroll = max(0, self.scroll - n)

    def scroll_home(self):
        max_scroll = max(0, len(self.lines) - (self.surf.get_height() // self.lh))
        self.scroll = max_scroll

    def scroll_end(self):
        self.scroll = 0


# ── Stats panel ───────────────────────────────────────────────────────────────

def render_stats(surf: pygame.Surface, fonts, system: TernarySystem,
                 state: dict, fps: float, elapsed: float):
    surf.fill(BG_STATS)
    font_hd, font_sm = fonts
    lh_hd = font_hd.get_height() + 3
    lh_sm = font_sm.get_height() + 2
    x, y = 8, 8
    w = surf.get_width() - 8

    def line(txt, color, big=False):
        nonlocal y
        f = font_hd if big else font_sm
        surf.blit(f.render(txt, True, color), (x, y))
        y += lh_hd if big else lh_sm

    def gap(n=4):
        nonlocal y
        y += n

    def divider():
        nonlocal y
        pygame.draw.line(surf, DIVIDER, (4, y + 2), (w - 4, y + 2), 1)
        y += 7

    line("TERNARY OS", CYAN, big=True)
    divider()

    # CPU cores
    now = time.monotonic()
    dt  = now - state["prev_time"]
    state["prev_time"] = now
    line("CPU", YELLOW)
    gap(2)
    for i, core in enumerate(system.cores):
        cur  = system._step_counts[i].value
        prev = state["prev_steps"][i]
        ips  = (cur - prev) / dt if dt > 0 else 0.0
        state["prev_steps"][i] = cur
        if not core.is_alive():
            tag, col = "STOPPED", RED
        elif core.HALTED:
            tag, col = f"HALTED  {ips:>7,.0f} IPS", ORANGE
        else:
            tag, col = f"RUNNING {ips:>7,.0f} IPS", GREEN
        line(f"  Core {i}  {tag}", col)
    divider()

    # Timing
    line("TIMING", YELLOW)
    gap(2)
    line(f"  Elapsed    {elapsed:>8.3f} s", WHITE)
    line(f"  FPS        {fps:>8.1f}", GRAY)
    divider()

    # Memory
    line("MEMORY", YELLOW)
    gap(2)
    line(f"  RAM        {len(system.mem._raw):>6,} words", WHITE)
    if hasattr(system, 'disk') and system.disk is not None:
        line(f"  Disk       {system.disk.size:>6,} cells", GRAY)
    divider()

    # ISA
    line("ISA", YELLOW)
    gap(2)
    line(f"  Instructions {len(ternary_1.instructions):>3}", WHITE)
    divider()

    gap(2)
    line("  [ESC]    quit", GRAY)
    line("  [scroll] terminal", GRAY)
    line("  [Home/End] jump", GRAY)


# ── Main ──────────────────────────────────────────────────────────────────────

def run_gui(build_dir: pathlib.Path):
    boot_path = build_dir / "bootsector.tern"
    disk_path = build_dir / "ternary.disk"

    for p in (boot_path, disk_path):
        if not p.exists():
            print(f"ERROR: {p} not found — run build_os.py first")
            sys.exit(1)

    pygame.init()
    pygame.display.set_caption("Ternary OS")
    screen = pygame.display.set_mode((WIN_W, WIN_H))
    clock  = pygame.time.Clock()

    try:
        font_hd = pygame.font.SysFont("Courier New", 13, bold=True)
        font_sm = pygame.font.SysFont("Courier New", 12)
        font_tr = pygame.font.SysFont("Courier New", 12)
    except Exception:
        font_hd = pygame.font.Font(None, 18)
        font_sm = pygame.font.Font(None, 16)
        font_tr = pygame.font.Font(None, 16)
    fonts = (font_hd, font_sm)

    term_surf  = pygame.Surface((TERM_W, WIN_H))
    stats_surf = pygame.Surface((STATS_W, WIN_H))
    term = Terminal(term_surf, font_tr)

    # Boot the OS
    term.write("TERNARY OS RUNNER", CYAN)
    term.write("-" * 36, DIVIDER)
    term.blank()
    term.write(f"disk:       {disk_path.name}", GRAY)
    term.write(f"bootsector: {boot_path.name}", GRAY)
    term.blank()
    term.write("Booting...", YELLOW)

    system = TernarySystem(
        ternary_1,
        num_cores=1,
        num_graphical_cores=0,
        disk_path=str(disk_path),
        disk_size=19683,
    )
    boot_words = load_tern_words(boot_path)
    for i, w in enumerate(boot_words):
        system.mem.set(i, w)

    term.write(f"Bootsector: {len(boot_words)} words -> RAM[0]", GRAY)
    term.blank()

    system.start_all()
    t_start = time.monotonic()
    halted  = False
    t_halt  = None

    perf_state = {
        "prev_time":  time.monotonic(),
        "prev_steps": [0] * len(system.cores),
    }

    fps = 0.0
    t_last_fps = time.monotonic()

    # Input line buffer (for rendering the current input line)
    input_buf: list[str] = []

    running = True
    while running:
        # ── Events ────────────────────────────────────────────────────────────
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_RETURN:
                    system.push_input(13)
                    input_buf.clear()
                elif event.key == pygame.K_BACKSPACE:
                    system.push_input(8)
                    if input_buf:
                        input_buf.pop()
                elif event.unicode and event.unicode.isprintable():
                    ch = ord(event.unicode)
                    system.push_input(ch)
                    input_buf.append(event.unicode)
            elif event.type == pygame.MOUSEWHEEL:
                mx, _ = pygame.mouse.get_pos()
                if mx < TERM_W:
                    if event.y > 0:
                        term.scroll_up(event.y * 3)
                    else:
                        term.scroll_down(-event.y * 3)

        # ── Poll CPU output ────────────────────────────────────────────────────
        new_out = system.drain_io_out()
        for port, value in new_out:
            if port == 1:
                # Character output from shell (print_char)
                term.append_char(chr(value) if 32 <= value < 127 else
                                 "\n"       if value == 10          else
                                 "\b"       if value == 8           else "")
            elif port == 0:
                term.write(str(value), GREEN)

        # ── Detect halt ───────────────────────────────────────────────────────
        if not halted:
            core = system.cores[0]
            if not core.is_alive() or core.HALTED:
                halted = True
                t_halt = time.monotonic()
                elapsed = t_halt - t_start
                term.blank()
                term.write(f"CPU halted  ({elapsed:.3f}s)", ORANGE)
                term.write("Press ESC to quit.", GRAY)
                # Drain any remaining output
                for port, value in system.drain_io_out():
                    if port == 0:
                        term.write(str(value), GREEN)

        # ── FPS ───────────────────────────────────────────────────────────────
        now = time.monotonic()
        dt_fps = now - t_last_fps
        if dt_fps > 0:
            fps = 1.0 / dt_fps
        t_last_fps = now
        elapsed = (t_halt or now) - t_start

        # ── Render ────────────────────────────────────────────────────────────
        term.render()
        render_stats(stats_surf, fonts, system, perf_state, fps, elapsed)

        screen.blit(term_surf,  (0,      0))
        screen.blit(stats_surf, (TERM_W, 0))
        pygame.draw.line(screen, DIVIDER, (TERM_W, 0), (TERM_W, WIN_H), 2)

        pygame.display.flip()
        clock.tick(FPS)

    # ── Shutdown ──────────────────────────────────────────────────────────────
    system.stop_all()
    system.join_all()
    pygame.quit()


def main():
    ap = argparse.ArgumentParser(description="GUI OS runner for the ternary computer")
    ap.add_argument("--build-dir", default="os_build",
                    help="Directory containing bootsector.tern and ternary.disk")
    args = ap.parse_args()
    run_gui(_HERE / args.build_dir)


if __name__ == "__main__":
    main()

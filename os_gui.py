"""
os_gui.py — GUI OS runner for the ternary computer.

The ternary CPU renders text directly into the shared video memory (vmem)
via TextTerminal (text_terminal.py).  This window just blits the raw
framebuffer — the display is driven by the simulated system.

Layout:
  Left  486×384   vmem framebuffer scaled 2× from 243×192
  Right 264×384   live stats panel

Usage:
    python os_gui.py [--build-dir <dir>]   (default: ./os_build)
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
from text_terminal import TextTerminal

# ── Video layout (must match TextTerminal constants in cpu.py) ─────────────────
VRAM_W  = 243
VRAM_H  = 192
SCALE   = 2
VIDEO_W = VRAM_W * SCALE   # 486
VIDEO_H = VRAM_H * SCALE   # 384
STATS_W = 264
WIN_W   = VIDEO_W + STATS_W
WIN_H   = VIDEO_H
FPS     = 30

# ── Palette ───────────────────────────────────────────────────────────────────
BG      = (18,  20,  28)
CYAN    = (70,  210, 255)
YELLOW  = (255, 235, 60)
GREEN   = (70,  240, 120)
ORANGE  = (255, 170, 50)
RED     = (255, 70,  70)
WHITE   = (230, 230, 235)
GRAY    = (130, 135, 148)
DIVIDER = (45,  48,  62)


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_tern_words(path: pathlib.Path) -> list[int]:
    raw = path.read_bytes()
    return list(struct.unpack_from(f"<{len(raw)//4}i", raw))


# ── Stats panel ───────────────────────────────────────────────────────────────

def render_stats(surf: pygame.Surface, fonts, system: TernarySystem,
                 state: dict, fps: float, elapsed: float) -> None:
    surf.fill(BG)
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

    line("TIMING", YELLOW)
    gap(2)
    line(f"  Elapsed  {elapsed:>8.3f} s", WHITE)
    line(f"  FPS      {fps:>8.1f}", GRAY)
    divider()

    line("DISPLAY", YELLOW)
    gap(2)
    line(f"  {VRAM_W}x{VRAM_H} @ {SCALE}x scale", GRAY)
    line(f"  30 cols x 24 rows", GRAY)
    divider()

    gap(2)
    line("  [ESC]    quit", GRAY)
    line("  [type]   shell input", GRAY)


# ── Main ──────────────────────────────────────────────────────────────────────

def run_gui(build_dir: pathlib.Path) -> None:
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

    # Build font BEFORE creating TernarySystem so child process gets it.
    font_data = _build_font()

    try:
        font_hd = pygame.font.SysFont("Courier New", 13, bold=True)
        font_sm = pygame.font.SysFont("Courier New", 12)
    except Exception:
        font_hd = pygame.font.Font(None, 18)
        font_sm = pygame.font.Font(None, 16)
    fonts = (font_hd, font_sm)

    # The video surface receives the raw vmem blit (grayscale, scaled 2x).
    video_surf = pygame.Surface((VRAM_W, VRAM_H))
    stats_surf = pygame.Surface((STATS_W, WIN_H))

    # Create and boot the system.
    system = TernarySystem(
        ternary_1,
        num_cores=1,
        num_graphical_cores=0,
        disk_path=str(disk_path),
        disk_size=19683,
    )
    terminal = TextTerminal(system.vmem, font_data)
    boot_words = load_tern_words(boot_path)
    for i, w in enumerate(boot_words):
        system.mem.set(i, w)

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
                elif event.key == pygame.K_BACKSPACE:
                    system.push_input(8)
                elif event.unicode and event.unicode.isprintable():
                    system.push_input(ord(event.unicode))

        # ── Drain output -> terminal ──────────────────────────────────────────
        for port, value in system.drain_io_out():
            if port == 1:
                terminal.write_char(value)

        # ── Detect halt ───────────────────────────────────────────────────────
        if not halted:
            core = system.cores[0]
            if not core.is_alive() or core.HALTED:
                halted  = True
                t_halt  = time.monotonic()

        # ── FPS ───────────────────────────────────────────────────────────────
        now = time.monotonic()
        dt_fps = now - t_last_fps
        if dt_fps > 0:
            fps = 1.0 / dt_fps
        t_last_fps = now
        elapsed = (t_halt or now) - t_start

        # ── Video: blit raw vmem → screen ─────────────────────────────────────
        raw = system.vmem._raw
        pxa = pygame.PixelArray(video_surf)
        with system.vmem.lock:
            idx = 0
            for yy in range(VRAM_H):
                for xx in range(VRAM_W):
                    t_val = raw[idx]
                    idx  += 1
                    # Map [-121, 121] → [0, 255], render as green channel
                    c = int((t_val + 121) * 1.0537)
                    c = max(0, min(255, c))
                    pxa[xx, yy] = (0 << 16) | (c << 8) | 0
        pxa.close()
        scaled = pygame.transform.scale(video_surf, (VIDEO_W, VIDEO_H))
        screen.blit(scaled, (0, 0))

        # ── Stats ─────────────────────────────────────────────────────────────
        render_stats(stats_surf, fonts, system, perf_state, fps, elapsed)
        screen.blit(stats_surf, (VIDEO_W, 0))
        pygame.draw.line(screen, DIVIDER, (VIDEO_W, 0), (VIDEO_W, WIN_H), 2)

        pygame.display.flip()
        clock.tick(FPS)

    system.stop_all()
    system.join_all()
    pygame.quit()


def main() -> None:
    ap = argparse.ArgumentParser(description="GUI OS runner — vmem display")
    ap.add_argument("--build-dir", default="os_build")
    args = ap.parse_args()
    run_gui(_HERE / args.build_dir)


if __name__ == "__main__":
    main()

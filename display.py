"""
Ternary Processor Simulator -- Display
Two-panel pygame window:
  Left:  live video output from the GPU framebuffer (243x192, scaled 2x)
  Right: real-time stats (IPS per core, GPU ops/s, FPS, memory sizes, status)

The bundled gradient demo program fills the screen with a cycling grayscale
gradient using GPROC FILL + GSYNC, driven by two CPU cores and two GPU cores.
"""

import sys
import time

import pygame  # type: ignore

from cpu import TernarySystem, ternary_1, encode_instruction, Immediate, Trite, GPU

# --- Layout ---------------------------------------------------------------
VRAM_W = 243
VRAM_H = 192
SCALE = 2
VIDEO_W = VRAM_W * SCALE  # 486
VIDEO_H = VRAM_H * SCALE  # 384
STATS_W = 264
WIN_W = VIDEO_W + STATS_W  # 750
WIN_H = VIDEO_H  # 384
FPS = 30

# --- Palette (stats panel) ------------------------------------------------
BG = (18, 20, 28)
CYAN = (70, 210, 255)
YELLOW = (255, 235, 60)
GREEN = (70, 240, 120)
ORANGE = (255, 170, 50)
RED = (255, 70, 70)
WHITE = (230, 230, 235)
GRAY = (130, 135, 148)
DIVIDER = (45, 48, 62)


# ---- Demo program --------------------------------------------------------
# Gradient animation using the "uniform buffer" pattern from modern GPUs:
#
#   HOST (Python display loop) owns the animation clock.  Every display
#   frame it writes the current color into a reserved memory address
#   (SYNC_ADDR), exactly like a GPU driver uploading a uniform to a
#   constant buffer before a draw call.
#
#   CORES just load from SYNC_ADDR each iteration and render their band.
#   No core tracks its own color counter; there is one authoritative
#   value broadcast to all of them, so they are permanently in phase.
#
# This is the same reason GPU shader invocations never drift relative to
# each other for uniforms: the host is the sole writer, the cores are
# read-only consumers of that value.
#
# Each core still claims its own disjoint horizontal band (via COREID)
# so no two cores ever write the same pixel -- that fix is kept from the
# previous tiling solution.
#
# Addresses are computed from each instruction's real encoded length
# (1 header word + 1 word/operand) so this doesn't silently break if
# the encoding changes.

# Memory address the display loop writes the current color to.
# Placed well above the program code (program is at most ~20 words).
SYNC_ADDR = 500


def _build_demo(num_cores):
    band_height = VRAM_H // num_cores

    # (label_or_None, opcode, operand-builder(labels) -> operands)
    spec = [
        # ── One-time setup: compute this core's band start address ──────
        (None, "00-+++", lambda L: [5]),                            # COREID r5
        (None, "00++0+", lambda L: [6, Immediate(band_height)]),    # MOVI r6, #band_height
        (None, "000+00", lambda L: [6, 5]),                         # MUL r6, r5  → r5 = core_id * band_height
        (None, "00++0+", lambda L: [7, Immediate(VRAM_W)]),         # MOVI r7, #VRAM_W
        (None, "000+00", lambda L: [7, 5]),                         # MUL r7, r5  → r5 = band start pixel addr

        # ── Render loop: read shared color, fill band, repeat ──────────
        # Load the current color from SYNC_ADDR (the host-written uniform).
        # This is the constant-buffer read: one memory cell, written only
        # by the display loop, read by every core each iteration.
        (
            "loop_start",
            "00000+",
            lambda L: [Immediate(SYNC_ADDR), 0],                    # LOAD #SYNC_ADDR, r0
        ),
        (
            None,
            "0+0000",
            lambda L: [
                Immediate(GPU.OPCODE_FILL),
                5,                          # dst_addr register (this core's band)
                Immediate(VRAM_W),          # pitch
                Immediate(VRAM_W),          # width
                Immediate(band_height),     # height (just this core's band)
                0,                          # color register
                Immediate(GPU.ROP_COPY),
            ],
        ),
        (None, "0+000-", lambda L: []),                             # GSYNC
        (None, "000-0-", lambda L: [Immediate(L["loop_start"])]),   # JMP loop_start
    ]

    # Pass 1: resolve label addresses (only operand count matters for sizing).
    placeholder = {"loop_start": 0}
    labels = {}
    addr = 0
    for name, opcode, build in spec:
        if name is not None:
            labels[name] = addr
        addr += 1 + len(build(placeholder))

    # Pass 2: build real operand lists with resolved labels.
    return [(opcode, build(labels)) for _, opcode, build in spec]


# ---- Stats rendering -----------------------------------------------------
def _render_stats(surface, fonts, system, fps, state):
    """Draw the stats panel onto `surface`.  `state` is a dict that persists
    between frames (prev counts, prev time) -- mutated in-place."""
    surface.fill(BG)
    font_hd, font_sm = fonts
    lh_hd = font_hd.get_height() + 3
    lh_sm = font_sm.get_height() + 2
    x, y = 10, 8

    def line(txt, color, big=False):
        nonlocal y
        f = font_hd if big else font_sm
        surface.blit(f.render(txt, True, color), (x, y))
        y += lh_hd if big else lh_sm

    def gap(n=4):
        nonlocal y
        y += n

    def divider():
        nonlocal y
        pygame.draw.line(surface, DIVIDER, (4, y + 2), (STATS_W - 4, y + 2), 1)
        y += 7

    # ── Header ──────────────────────────────────────────────────────────
    line("TERNARY SIMULATOR", CYAN, big=True)
    divider()

    # ── Performance ─────────────────────────────────────────────────────
    now = time.monotonic()
    dt = now - state["prev_time"]
    state["prev_time"] = now

    line("PERFORMANCE", YELLOW)
    gap(2)

    for i, core in enumerate(system.cores):
        cur = system._step_counts[i].value
        prev = state["prev_steps"][i]
        ips = (cur - prev) / dt if dt > 0 else 0.0
        state["prev_steps"][i] = cur

        if not core.is_alive():
            tag, col = "STOPPED", RED
        elif core.HALTED:
            tag, col = f"HALTED  {ips:>7,.0f} IPS", ORANGE
        else:
            tag, col = f"RUNNING {ips:>7,.0f} IPS", GREEN
        line(f"  CPU {i}  {tag}", col)

    gap(3)

    cur_gpu = system._gpu_opcount.value
    gpu_ops = (cur_gpu - state["prev_gpu"]) / dt if dt > 0 else 0.0
    state["prev_gpu"] = cur_gpu

    for i, gc in enumerate(system.gpu_cores):
        col = GREEN if gc.is_alive() else RED
        st = "RUNNING" if gc.is_alive() else "STOPPED"
        line(f"  GPU {i}  {st}", col)

    gap(2)
    line(f"  GPU ops   {gpu_ops:>7.1f} /s", WHITE)
    divider()

    # ── Display ─────────────────────────────────────────────────────────
    line("DISPLAY", YELLOW)
    gap(2)
    line(f"  FPS       {fps:>7.1f}", WHITE)
    line(f"  Resolution   {VRAM_W}x{VRAM_H}", GRAY)
    line(f"  Scale        {SCALE}x", GRAY)
    divider()

    # ── Memory ──────────────────────────────────────────────────────────
    line("MEMORY", YELLOW)
    gap(2)
    line(f"  RAM    {len(system.mem._raw):>8,} words", WHITE)
    line(f"  VRAM   {len(system.vmem._raw):>8,} pixels", WHITE)
    line(f"  VBUF     {VRAM_W}x{VRAM_H} ({VRAM_W * VRAM_H:,}px)", GRAY)
    divider()

    # ── ISA ─────────────────────────────────────────────────────────────
    line("ISA", YELLOW)
    gap(2)
    line(f"  Instructions {len(ternary_1.instructions):>4}", WHITE)
    line(f"  CPU cores    {len(system.cores):>4}", WHITE)
    line(f"  GPU cores    {len(system.gpu_cores):>4}", WHITE)
    divider()

    # ── Controls ────────────────────────────────────────────────────────
    gap(2)
    line("  [ESC] / close  quit", GRAY)


# ---- Main ----------------------------------------------------------------
def run_window():
    system = TernarySystem(ternary_1, num_cores=4, num_graphical_cores=32)
    system.vbuffer_alloc = VRAM_W * VRAM_H

    # Load demo program into shared memory before spawning cores.
    addr = 0
    for opcode, operands in _build_demo(system.num_cores):
        for word in encode_instruction(opcode, operands):
            system.mem.set(addr, word)
            addr += 1

    pygame.init()
    pygame.display.set_caption("Ternary Processor Simulator")
    screen = pygame.display.set_mode((WIN_W, WIN_H))
    video_surf = pygame.Surface((VRAM_W, VRAM_H))
    stats_surf = pygame.Surface((STATS_W, WIN_H))
    clock = pygame.time.Clock()

    # Prefer monospace; fall back to pygame default.
    try:
        font_hd = pygame.font.SysFont("Courier New", 13, bold=True)
        font_sm = pygame.font.SysFont("Courier New", 12)
    except Exception:
        font_hd = pygame.font.Font(None, 18)
        font_sm = pygame.font.Font(None, 16)
    fonts = (font_hd, font_sm)

    # Persistent state for rate calculations.
    perf_state = {
        "prev_time": time.monotonic(),
        "prev_steps": [0] * len(system.cores),
        "prev_gpu": 0,
    }

    # Initialise SYNC_ADDR to the start of the color range so cores have a
    # valid value the instant they first load it (before the display loop
    # writes its first update).
    _COLOR_MIN = -121
    _COLOR_MAX = 121
    _host_color = _COLOR_MIN
    system.mem.set(SYNC_ADDR, Trite().from_int(_host_color))

    print(
        f"Starting {len(system.cores)}-CPU / {len(system.gpu_cores)}-GPU ternary system…"
    )
    system.start_all()

    fps = 0.0
    t_last_fps = time.monotonic()

    try:
        running = True
        while running:
            # ── Host uniform update ───────────────────────────────────────
            # Advance the shared color by 1 each display frame and write it
            # to SYNC_ADDR.  This is the "upload uniform to constant buffer"
            # step: one write from the host, read by every core next iter.
            _host_color += 1
            if _host_color > _COLOR_MAX:
                _host_color = _COLOR_MIN
            system.mem.set(SYNC_ADDR, Trite().from_int(_host_color))

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    running = False

            # ── Video panel ──────────────────────────────────────────────
            raw = system.vmem._raw
            pxa = pygame.PixelArray(video_surf)
            with system.vmem.lock:
                idx = system.vbuffer_offset
                for yy in range(VRAM_H):
                    for xx in range(VRAM_W):
                        t_val = raw[idx]
                        idx += 1
                        # Map [-121, 121] → [0, 255] (grayscale)
                        c = int((t_val + 121) * 1.0537)
                        if c > 255:
                            c = 255
                        elif c < 0:
                            c = 0
                        pxa[xx, yy] = (c << 16) | (c << 8) | c
            pxa.close()

            scaled = pygame.transform.scale(video_surf, (VIDEO_W, VIDEO_H))
            screen.blit(scaled, (0, 0))

            # ── Stats panel ──────────────────────────────────────────────
            now = time.monotonic()
            dt_fps = now - t_last_fps
            if dt_fps > 0:
                fps = 1.0 / dt_fps
            t_last_fps = now

            _render_stats(stats_surf, fonts, system, fps, perf_state)
            screen.blit(stats_surf, (VIDEO_W, 0))

            # Panel border
            pygame.draw.line(screen, (55, 58, 72), (VIDEO_W, 0), (VIDEO_W, WIN_H), 2)

            pygame.display.flip()
            clock.tick(FPS)

    except KeyboardInterrupt:
        pass
    finally:
        print("Shutting down…")
        system.stop_all()
        system.join_all()
        pygame.quit()
        sys.exit()


if __name__ == "__main__":
    run_window()

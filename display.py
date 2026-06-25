import pygame  # type: ignore
import sys

# Import the 'system' instance from your cpu.py
from cpu import system

# --- Configuration ---
VRAM_WIDTH = 243   # exactly the framebuffer's 243 color levels -- see graphics_test.asm
VRAM_HEIGHT = 192
FPS = 15


def run_window():
    pygame.init()

    # Set up the display for native resolution
    screen = pygame.display.set_mode((VRAM_WIDTH, VRAM_HEIGHT))
    pygame.display.set_caption("Ternary Multi-Core Simulator (243x192 Native)")
    clock = pygame.time.Clock()

    # Tell the system how much memory the buffer actually takes
    system.vbuffer_alloc = VRAM_WIDTH * VRAM_HEIGHT

    print(f"Starting {len(system.cores)}-Core Ternary System...")
    # 1. START THE CPU THREADS
    system.start_all()

    running = True
    try:
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False

            # Lock the screen for direct pixel access
            pixels = pygame.PixelArray(screen)

            # Pre-fetch the raw array reference to avoid dot lookups in the loop
            vmem_array = system.vmem.vmem

            with system.vmem.lock:
                idx = system.vbuffer_offset

                # Optimized nested loop using a running index
                for y in range(VRAM_HEIGHT):
                    for x in range(VRAM_WIDTH):
                        # Read the integer value directly
                        t_val = int(vmem_array[idx])
                        idx += 1

                        # Math: Fast scale from [-121, 121] to [0, 255]
                        c_val = int((t_val + 121) * 1.0537)

                        # Fast clamp
                        if c_val > 255:
                            c_val = 255
                        elif c_val < 0:
                            c_val = 0

                        # Bitwise color packing (much faster than creating tuples)
                        # Shifts the values into 0xRRGGBB format
                        pixels[x, y] = (c_val << 16) | (c_val << 8) | c_val

            pixels.close()  # Unlock the surface so pygame can draw it

            # Push to Monitor
            pygame.display.flip()

            # Rest the rendering thread (15 FPS)
            clock.tick(FPS)

    except KeyboardInterrupt:
        print("Interrupt caught. Shutting down...")
    finally:
        # CLEANUP AND SHUTDOWN
        print("Halting CPU cores...")
        system.stop_all()
        system.join_all()
        pygame.quit()
        sys.exit()


if __name__ == "__main__":
    run_window()

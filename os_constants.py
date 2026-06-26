"""
Shared layout constants for the ternary OS.

  ┌──────────────────────────────────────────────────────────┐
  │ DISK  (19683 cells = 243 sectors × 81 cells/sector)      │
  │  sector  0        directory  (10 entries × 8 cells)      │
  │  sectors 1-10     kernel binary  (10 sectors)            │
  │  sectors 11-15    shell binary   ( 5 sectors)            │
  │  sectors 16-20    hello binary   ( 5 sectors)            │
  └──────────────────────────────────────────────────────────┘

  ┌──────────────────────────────────────────────────────────┐
  │ RAM  (6561 cells)                                        │
  │  0   - 242   bootsector (243 cells, loaded by _boot())  │
  │  300 - 1109  kernel loaded here  (810 cells, 10 sectors) │
  │  1200- 1604  shell loaded here   (405 cells,  5 sectors) │
  │  2000- 2404  user program area   (405 cells,  5 sectors) │
  │  2500- 2580  kernel scratch (directory reads, etc.)      │
  │  4000- 4199  kernel static frame (alloca slots)          │
  │  4200- 4399  shell  static frame                         │
  │  4400- 4599  user   static frame                         │
  │  6000- 6560  hardware stack region                       │
  └──────────────────────────────────────────────────────────┘

  Directory entry format (8 cells each):
    cells[0..5]  filename as ASCII ints, null-padded to 6 chars
    cells[6]     start_sector on disk
    cells[7]     size_in_sectors
"""

# ── Disk layout ───────────────────────────────────────────────────────────────
SECTOR_SIZE      = 81      # cells per sector (3^4)
NUM_SECTORS      = 243     # total sectors (19683 / 81)

DIR_SECTOR       = 0       # directory lives at sector 0
DIR_ENTRIES      = 10      # max files in directory
DIR_ENTRY_SIZE   = 8       # cells per directory entry

KERNEL_DISK_SECTOR  = 1    # kernel starts here
KERNEL_DISK_SECTORS = 10   # 10 sectors (810 cells)

SHELL_DISK_SECTOR   = 11   # shell starts here
SHELL_DISK_SECTORS  = 10   # 10 sectors (810 cells)

HELLO_DISK_SECTOR   = 21   # hello program starts here
HELLO_DISK_SECTORS  = 5    # 5 sectors (405 cells)

# ── RAM layout ────────────────────────────────────────────────────────────────
BOOTSECTOR_RAM   = 0       # bootsector loaded by _boot() into RAM[0]

KERNEL_RAM       = 300     # kernel loaded at this RAM address
SHELL_RAM        = 1200    # shell (user prog slot 1) loaded here
PROG_RAM         = 2000    # general user program area

KERNEL_SCRATCH   = 2500    # kernel scratch space (dir reads, temp)

# ── Static frame bases (alloca slots for compiled programs) ──────────────────
KERNEL_FRAME     = 4000    # kernel alloca frames
SHELL_FRAME      = 4200    # shell alloca frames
PROG_FRAME       = 4400    # user program alloca frames

# ── Directory entry field offsets ────────────────────────────────────────────
DIR_NAME_OFF     = 0       # first of 6 name cells
DIR_NAME_LEN     = 6
DIR_SECTOR_OFF   = 6       # start_sector field
DIR_SIZE_OFF     = 7       # size_in_sectors field

# ── Known filenames (as tuples of ASCII ints, 6 chars, 0-padded) ─────────────
# Used by kernel and shell to look up files.
def name_ints(s: str) -> tuple:
    """Return a 6-tuple of ASCII ints for a name string (padded / truncated)."""
    s = (s + "\x00" * 6)[:6]
    return tuple(ord(c) for c in s)

NAME_KERNEL = name_ints("kernel")   # (107,101,114,110,101,108)
NAME_SHELL  = name_ints("shell\x00")  # (115,104,101,108,108,0)
NAME_HELLO  = name_ints("hello\x00")  # (104,101,108,108,111,0)

; ===================================================================
; GRAPHICS TEST: continuously animated, always-seamless gradient sweep.
;
; The framebuffer has exactly 243 distinct color levels (a 5-trit
; value), so the screen is exactly 243 pixels wide: every row sweeps
; from one extreme to the other in exactly 243 steps, landing exactly
; on the far extreme at the last pixel -- no leftover pixels, no
; wraparound, no seam, ever, on any frame, regardless of timing.
;
; Animation comes from flipping the sweep direction every frame
; (black->white, then white->black, ...) instead of rolling the start
; point -- a rolling start would eventually push the wrap point into
; the middle of the row, which is what caused the seam before.
; ===================================================================
.equ VRAM_START 0
.equ SCREEN_WIDTH 243
.equ SCREEN_HEIGHT 192
.equ WHITE 121
.equ BLACK -121

.text
ENTRY:
    ; Both cores boot from address 0 and would otherwise run this program
    ; independently, racing to draw into the same shared vmem buffer (seen
    ; as two interleaved/split gradients). Only core 0 draws; every other
    ; core halts immediately.
    COREID r7
    CMP #0, r7
    JZ  BOOT
    HALT

BOOT:
    MOVI r3, #0              ; r3 = frame counter; its parity picks sweep direction

FRAME_LOOP:
    MOVI r0, #VRAM_START     ; r0 = pixel address, reset each frame
    MOVI r5, #SCREEN_HEIGHT  ; r5 = rows remaining this frame

    MOV  r8, r3              ; r8 = a scratch copy -- r3 itself stays untouched
    MOD  #2, r8               ;   so it keeps counting frames forever
    CMP  #0, r8
    JZ   EVEN_DIR
    MOVI r9, #WHITE          ; odd frame: sweep white -> black
    MOVI r10, #-1
    JMP  DIR_SET
EVEN_DIR:
    MOVI r9, #BLACK          ; even frame: sweep black -> white
    MOVI r10, #1
DIR_SET:

ROW_LOOP:
    MOV  r1, r9              ; r1 = color resets to this frame's sweep start every row
    MOVI r2, #SCREEN_WIDTH   ; r2 = pixels remaining this row

DRAW_LOOP:
    VSTORE r0, r1            ; draw this pixel
    INC  r0                  ; advance to the next pixel address
    ADD  r10, r1             ; step color toward the other extreme (+1 or -1)
    DEC  r2                  ; one fewer pixel left to draw this row
    JNZ  DRAW_LOOP             ; keep going until the row is done

    DEC r5                   ; one fewer row left to draw this frame
    JNZ ROW_LOOP                ; keep going until the frame is done

    INC r3                   ; next frame -- flips the sweep direction
    JMP FRAME_LOOP               ; redraw forever

; ===================================================================
; MAGIC NUMBERS (Constants)
; The .equ directive teaches the compiler nicknames for numbers.
; From now on, anytime it sees VRAM_START, it puts in 0x1000.
; ===================================================================
.equ VRAM_START 300   ; Let's pretend VRAM starts at address 300
.equ WHITE_PIXEL 121     ; The highest ternary value for a Trit(5)
.equ BLACK_PIXEL -121    ; The lowest ternary value

; ===================================================================
; THE CODE SECTION
; .text is just a sticky note telling us "CPU instructions start here"
; By default, the mailman starts putting this at Address 0.
; ===================================================================
.text
BOOT:
    ; 1. Load our cheat-sheet nicknames into registers
    MOVI r0, #VRAM_START     ; r0 now points to the first VRAM mailbox
    MOVI r1, #WHITE_PIXEL    ; r1 now holds the number for the color White
    MOVI r2, #0              ; r2 will be our counter to count to 10

DRAW_LOOP:
    ; 2. Put the color (r1) into the VRAM mailbox (r0)
    VSTORE r0, r1            ; Draw the pixel!
    
    ; 3. Move to the next mailbox
    INC r0                   ; r0 = r0 + 1 (Move pointer 1 pixel to the right)
    INC r2                   ; r2 = r2 + 1 (Increase our counter)
    
    ; 4. Check if we've drawn 10 pixels yet
    CMP #10, r2
    JL DRAW_LOOP             ; If counter is Less Than 10, Jump back up and loop
    
    ; 5. We are done drawing!
    HALT

; ===================================================================
; THE DATA SECTION
; .data is a sticky note telling us "Raw numbers start here"
; We use .org to tell the mailman exactly where to put this stuff!
; ===================================================================
.data

; Put my sprite at exactly address 200. Do not put it at address 12!
.org 200

MY_SPRITE:
    ; DAT means "Data". Do not translate this into a machine instruction!
    ; Just stuff these exact numbers into the mailboxes.
    DAT +0-0+0-0  ; A raw ternary word (maybe this looks like a smiley face)
    DAT 50        ; A regular decimal number
    DAT #WHITE_PIXEL ; We can even use our nicknames here!

; Put this other secret number at address 500
.org 500
SECRET_PASSWORD:
    DAT 999
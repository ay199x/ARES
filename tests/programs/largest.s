        .data
list:   .word   12, 7, 25, 3, 18        @ five numbers
intro:  .asciz  "The largest number is "

        .global _start
        .text
_start: LDR     R0, =intro
        SVC     #4              @ print the text
        LDR     R1, =list       @ R1: next number's address
        MOV     R2, #5          @ R2: numbers left
        MOV     R0, #0          @ R0: the largest so far
loop:   LDR     R3, [R1]        @ R3: the next number
        CMP     R3, R0
        MOVGT   R0, R3          @ keep it if it is larger
        ADD     R1, R1, #4
        SUBS    R2, R2, #1      @ count down; sets the flags
        BNE     loop            @ repeat until none is left
        SVC     #1              @ print the largest
        SVC     #10             @ end the program

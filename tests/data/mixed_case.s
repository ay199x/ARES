@ SPDX-License-Identifier: GPL-2.0-or-later
@ Copyright (c) 2026 The ARES Project
@
@ Every kind of token in lowercase and mixed case, for the capitalizer tests.
@ It assembles as written; it is never run.

        .Global _start
        .TEXT
        .Syntax divided

/* A comment over several lines:
   add r0, r1, #1 and ldr r0, =0x10
   must stay as written */

limit = 10
        .Equ    step, 4
        .set    Mixed_Name, 0x1f
count   .req    r6
acc     .dn     d7
vec     .qn     q3

        .Macro  push_pair first, second
        push    {\first, \second}
skip\@:
        b       skip\@
        .endM

        .Macro  Yield reg               @ named like an instruction
        .ifc    \reg, lr
        MOV     R0, #1
        .else
        MOV     R0, #2
        .endif
        .endm

        .macro  deflab name             @ makes a label
\name:  NOP
        .endm

_start:
        ldr     sp, =0x3ffffff8         @ add r0, r1 in a comment stays
        Mov     r0, #limit              // mov pc, lr stays too
        mov     count, #3
        ADD     r1, R2, #step
        aDd     a1, a2, a3
        sub     v1, v2, v3 ; rsb v4, v5, #0 ; Eor v6, v7, v8
        orr     fp, ip, sb
        and     sl, r12, r11
        bic     r0, r0, #0xFF
        mvn     r1, #0
        adds    r0, r0, #1
        addeqs  r0, r0, #1
        subnes  r1, r1, #2
        movcs   r2, r3
        movhs   r2, r3
        movcc   r2, r3
        movlo   r2, r3
        movmi   r2, r3
        movpl   r2, r3
        movvs   r2, r3
        movvc   r2, r3
        movhi   r2, r3
        movls   r2, r3
        movge   r2, r3
        movlt   r2, r3
        movgt   r2, r3
        movle   r2, r3
        moval   r2, r3
        cmp     r0, #'a'
        cmp     r1, #'\n'
        cmn     r2, #-1
        tst     r3, #0x80000000
        teq     r4, r5
        mov     r0, r1, lsl #2
        mov     r0, r1, LSR #3
        mov     r0, r1, asr r2
        mov     r0, r1, ror #4
        mov     r0, r1, rrx
        mov     r0, r1, asl #1
        lsl     r0, r1, #2
        lsls    r0, r1, #2
        mul     r0, r1, r2
        mla     r0, r1, r2, r3
        umull   r0, r1, r2, r3
        smull   r4, r5, r6, r7
        muls    r0, r1, r2
        smlabb  r0, r1, r2, r3
        qadd    r0, r1, r2
        uadd8   r0, r1, r2
        clz     r0, r1
        rbit    r0, r1
        rev     r0, r1
        uxtb    r0, r1
        sxth    r0, r1, ror #8
        bfi     r0, r1, #4, #8
        ubfx    r0, r1, #4, #8
        movw    r0, #:lower16:msg
        movt    r0, #:upper16:msg
        ldr     r1, =msg
        ldr     r2, =msg + 4
        ldr     r3, =0xff201000
        ldr     r0, [r1]
        ldr     r0, [r1, #4]!
        ldr     r0, [r1], #4
        ldr     r0, [r1, r2, lsl #2]
        ldrb    r0, [r1, -r2]
        ldreqb  r0, [r1]
        ldrneh  r0, [r1, #2]
        ldreqsb r0, [r1]
        ldreqsh r0, [r1]
        ldrd    r0, r1, [r2]
        strd    r2, r3, [sp, #-8]!
        str     r0, [r1], #4
        strb    r0, [r1]
        strh    r0, [r1]
        ldrex   r0, [r1]
        strex   r2, r0, [r1]
        ldreqht r0, [r1], #2
        ldrnesbt r0, [r1], #1
        streqht r0, [r1], #2
        ldseqb  r0, [r1]
        ldsh    r0, [r1]
        add     r0, r1, /* a comment between operands
                         */ r2
        stmfd   sp!, {r4-r6, lr}
        ldmfd   sp!, {r4-r6, lr}
        ldmia   r0!, {r1, r2}
        stmeqia r0, {r1, r2}
        stmdb   sp!, {r0}
        ldmed   sp!, {r0}
        push    {r4, LR}
        pop     {r4, pc}
        push_pair r4, r5
        mrs     r0, cpsr
        mrs     r1, Spsr
        mrs     r2, apsr
        msr     cpsr_fc, r0
        msr     cpsr_c, #0xd3
        msr     apsr_nzcvq, r1
        mrc     p15, 0, r0, c1, c0, 0
        mcr     P15, 0, r0, C7, c10, 5
        cpsid   if
        dmb     ish
        pld     [r0, #64]
        nop
        bl      func
        blx     r3
        bx      lr
        beq     func
        blne    func
        b       Func_Mixed

        .Syntax unified
        addseq  r0, r0, #1
        ldrbeq  r1, [r2]
        ldrsheq r1, [r2]
        ldmiaeq r0, {r1}
        ite     eq
        moveq   r0, #1
        movne   r0, #0
        .syntax divided

func:
        vadd.f32 s0, s1, s2
        Vmul.F64 d0, d1, d2
        vsub.f32 s3, s30, s29
        vcvt.f32.s32 s3, s4
        vcvt.s32.f64 s5, d6
        vldr    s0, [r0, #4]
        vstr    d1, [r0]
        vmov    r2, r3, d5
        vmov    s6, r4
        vmov.f32 s7, #1.5
        vmov.f64 d8, #-0.5
        vcmp.f32 s0, #0
        vmrs    apsr_nzcv, fpscr
        vmrs    r0, fpexc
        vmrs    r1, fpsid
        vmrs    r2, mvfr0
        vmrs    r3, MVFR1
        vmsr    fpscr, r0
        vpush   {d8-d9}
        vpop    {d8-d9}
        vaddeq.f32 s0, s0, s1
        vadd.f64 acc, acc, acc
        vmov    vec, q2
        vld1.32 {d0-d3}, [r0:128]!
        vst1.8  {d4[1]}, [r1]
        vmov.i32 q0, #0
        vdup.32 q1, d2[1]
        vadd.i16 q4, q5, q6
        vmull.u8 q7, d16, d31
        vmla.f32 q8, q9, q10
        vzip.8  d20, d21
        vld2.16 {d22, d23}, [r2]
        vst4.8  {d24, d25, d26, d27}, [r3]
        vmov.32 r0, d28[1]
        vext.8  q11, q12, q13, #3
        vshr.u32 q14, q15, #1
        fadds   s0, s1, s2
        fmrx    r0, fpsid
        vadd.f  s0, s1, s2
        vadd.d  d0, d1, d2
        vdupqeq.32 q0, r0
        vmrs    r0, fpinst
        vmrs    r1, FPINST2
        mcr     p15, 0, r0, cr7, CR10, 5
typed   .dn     d5.f32
        vadd    typed, typed, typed
        .unreq  typed
        .unreq  acc
        .unreq  vec

1:      subs    count, count, #1
        bne     1b
        bgt     2f
2:      adr     r0, d31
        ldr     r1, d31
        b       .
        yield   lr                      @ calls the macro
        deflab  s7
        bl      s7
        ldr     r0, s7
        adr     r1, s7
año:    subs    r0, r0, #1
        bne     año
10$:    subs    r1, r1, #1
        bne     10$

Func_Mixed:
# sub r0, r0, #1 is a line comment here
        mov     r0, #';' ; mov r1, #'@'
        svc     #10
d31:    .word   7
        .unreq  count
        .Ltorg

        .Data
        .Balign 4
msg:    .ASCIZ  "r0 add lsl sp; @ // /* not a comment */"
chars:  .byte   'x', ';', '@', 0
words:  .Word   0x1F, 0b101, 017, Mixed_Name, limit, step
halves: .hword  1, 2
        .ascii  "PUSH {R0}\n"
        .Align  2
table:  .space  8

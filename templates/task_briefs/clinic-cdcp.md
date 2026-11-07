# Task brief: dental clinic — CDCP coverage questions

Copy this into `--task-brief` (or adapt it) when the assistant should call a
dental clinic to ask about coverage. Replace the bracketed values.

## Greeting (pass as `--greeting`)

> Hi, I'm an AI assistant calling for [FIRST NAME]. [He/She/They] is a new
> patient — do you accept the Canadian Dental Care Plan, and bill directly
> to Sun Life?

## Task brief (pass as `--task-brief`)

> You are calling [CLINIC NAME] at [PHONE NUMBER] for [FIRST NAME]. [He/She/They]
> is a new patient and wants a New Patient Exam + Cleaning (Adult).
>
> Ask exactly two questions, one at a time, waiting for each answer:
> 1. Do you accept the Canadian Dental Care Plan (CDCP), and bill directly
>    to Sun Life?
> 2. Is a new patient exam + cleaning (adult) fully covered by CDCP, and if
>    not fully covered, how much would [FIRST NAME] have to pay out of pocket?
>
> Do not book an appointment — [FIRST NAME] books online themselves. If the
> clinic offers a time, write it down and report it. If the person asks for
> a membership number, say [FIRST NAME] will provide it directly.
>
> Background (only if asked): [e.g. when the last cleaning was; any
> relevant history, such as a past root canal; whether there is pain,
> sensitivity, or other problems; whether there is any other dental
> insurance besides CDCP; whether the CDCP membership card and number are
> available. Keep it to one or two short facts, and only share what is asked.]

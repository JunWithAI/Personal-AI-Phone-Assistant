# Task brief: restaurant booking

Copy this into `--task-brief` (or adapt it) when the assistant should call a
restaurant to book a table. Replace the bracketed values.

## Greeting (pass as `--greeting`)

> Hi, I'm an AI assistant calling for [FIRST NAME]. [He/She/They] would like
> to book a table for [PARTY SIZE] at [RESTAURANT NAME] for [DAY, DATE] at
> [TIME] — do you have a window seat available?

## Task brief (pass as `--task-brief`)

> You are calling [RESTAURANT NAME] to book a table for [FIRST NAME]. Ask if
> a window seat for [PARTY SIZE] is available on [DAY, DATE] at [TIME].
>
> - If a window seat is available, book it under the name [FIRST NAME] and
>   confirm the details back (date, time, party size, window seat, name).
> - If no window seat is available but another table for [PARTY SIZE] is
>   available at that time, book the available table, note it is not a
>   window seat, and confirm.
> - If no table is available at [TIME], ask what other times are available
>   that evening and take the closest time to [TIME] if they offer one.
> - If the restaurant is fully booked that evening, thank them and end
>   the call.

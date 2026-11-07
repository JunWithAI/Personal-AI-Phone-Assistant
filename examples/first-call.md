# Worked example: your first test call

This is the shortest path from a fresh `setup.py` to a verified working
call. Call your own mobile so you can hear the assistant and judge it
yourself.

## 1. Set up (once)

```bash
python3 scripts/setup.py --name Alex --phone +15551234567
```

You should see five steps complete and a summary with your assistant id,
your Telnyx number, and the command for a test call. If `setup.py` stops
at step 2 ("No active Telnyx phone number found"), buy a number in the
Telnyx Portal first (Numbers → Buy Numbers, Local, about $1/month), then
re-run it.

## 2. Dial yourself

Replace `+15551234567` with your own mobile number. The assistant will
call you, introduce itself as an AI assistant calling for Alex, and ask
you to confirm you can hear it.

```bash
python3 scripts/call.py --to +15551234567 \
  --greeting "Hi, I'm an AI assistant calling for Alex. Could you confirm this is a test call?" \
  --task-brief "This is a test call. Ask the person who answers to confirm they can hear you clearly, then thank them and end the call."
```

What to listen for:

- **The greeting should start about 1 second after you answer.** If you
  hear several seconds of silence, something is wrong — see
  `references/TROUBLESHOOTING.md` ("The greeting is slow").
- **The assistant should ask one thing, then wait.** Answer it, and it
  should respond naturally.
- **It should hang up promptly** after the final goodbye — about a second,
  not ten.

`call.py` prints a JSON summary. Note the `conversation_id` and the
`call_session_id`.

## 3. Review the call

```bash
python3 scripts/review.py --conversation <CONVERSATION_ID> --download test-call.mp3
```

Check:

- **Greeting latency** — aim for ~1s. Much more than that means the
  greeting is not reaching the caller promptly.
- **Transcript** — does the assistant follow the task brief? Did it share
  anything it should not have?
- **Hangup tool fired: yes** — the call ended cleanly. If it says no, the
  call ran until the timeout; see the troubleshooting guide.

## 4. Try a real scenario

Once the test call sounds right, try a task brief from
`templates/task_briefs/` — for example the restaurant booking, calling
your own phone and role-playing the front desk. That is how the system
was tuned: the assistant should navigate "no window seat" → "no 7pm" →
"6pm or 8pm available" and pick the closest time, confirm the details,
and hang up cleanly.

## 5. Keep it updated

```bash
bash scripts/update.sh
```

That pulls the latest template and re-applies it to your assistant.

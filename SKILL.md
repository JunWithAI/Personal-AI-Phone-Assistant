---
name: ai-phone-assistant
description: Make AI phone calls on the user's behalf through Telnyx — ask a business a question, book a table, or confirm a detail, with a general-purpose voice assistant that takes its task per call. Use when the user asks to call someone, have the AI call a shop/clinic/restaurant, or check how a past AI call went.
version: 1.0.0
---

# AI Phone Assistant

Make real phone calls through Telnyx. A single general-purpose voice
assistant does the talking; every call passes its own opening line and
task brief, so one assistant serves every scenario — no per-business
assistant to build.

## When to use this skill

- The user asks you to call someone, or to have the AI call a business
  (clinic, restaurant, shop, customer service) to ask something, book
  something, or confirm something.
- The user asks for a test call to their own phone.
- The user asks how a past AI call went, or for its transcript/recording.

Do NOT use it for Muse's built-in calling feature (a different, invite-only
feature for US businesses). This skill is a separate system the user runs
themselves through Telnyx.

## First-time setup (one command)

The user needs three things before setup. All three stay manual by design:

1. A **Telnyx account** with identity verification done, a payment method
   added, and a **phone number bought** (Local, about $1/month). Telnyx
   requires the account holder to do this; no script can do it for them.
2. A **Telnyx API key** (Portal > Auth > API Keys, v2 key). The user stores
   it one of these ways — never paste it into chat:
   - `TELNYX_API_KEY` environment variable, or
   - a `.env` file with `TELNYX_API_KEY=...`, or
   - `~/.config/muse-ai-phone/config.json` with `{"telnyx_api_key": "..."}`, or
   - in Muse, the `custom.telnyx` secure connection.
3. Their **first name** (and, optionally, their own phone number, which the
   assistant shares only when the other party explicitly asks for it).

Then run:

```bash
python3 scripts/setup.py --name <FIRST_NAME> [--phone <YOUR_PHONE>]
```

`setup.py` is idempotent. It verifies the key, finds the Telnyx number,
attaches it to a Call Control application (creating one if needed), creates
the general assistant from `templates/assistant.json` (or updates the
existing one), and saves state to `~/.config/muse-ai-phone/state.json`.
Run it again any time to sync the latest template — that is the update
mechanism (see "Staying up to date").

The default assistant needs **no OpenAI key**. Its brain
(`openai/gpt-5.6-sol`) runs through Telnyx's own inference, and its voice
is Telnyx Ultra with Deepgram transcription. An OpenAI key is only needed
for the experimental GPT-Live voice path (see `references/ARCHITECTURE.md`).

## Making a call

Confirm with the user before every call: the destination number, and what
the assistant should ask or book. Never dial without that confirmation.

1. Write the **greeting** — the exact opening line, one or two sentences,
   ending in the first question. It must identify the caller as an AI
   assistant (Telnyx requires this disclosure up front).
2. Write the **task brief** — what to ask, book, or confirm, and what
   counts as done. Be specific. See `templates/task_briefs/` for examples
   (dental CDCP questions, restaurant booking, generic questions).
3. Dial:

```bash
python3 scripts/call.py --to <DESTINATION_E164> \
  --greeting "<OPENING LINE>" \
  --task-brief "<WHAT TO DO ON THIS CALL>"
# Chinese call: add --language zh (greeting and task brief in Chinese).
```

`call.py` passes the greeting and task brief as per-call overrides, waits
for the answer, checks that the assistant actually spoke, and redials once
if the session was dead (no messages). It prints a JSON summary with the
`call_session_id` and `conversation_id`. With `--language zh`, it also
overrides the instructions and transcription for that call only, from
`templates/assistant_zh.json` — one stored assistant serves both
languages.

## Reviewing a call

```bash
python3 scripts/review.py --conversation <CONVERSATION_ID> [--download out.mp3]
# or: --session <CALL_SESSION_ID>  /  --call <CALL_CONTROL_ID>
```

This prints the transcript in order, the timing (answer time, greeting
latency, duration), whether the hangup tool fired, and the recording id.
`--download` saves the dual-channel recording.

## How the assistant behaves (shared rules)

These live in `templates/assistant.json` and apply to every call:

- Calls the user only by first name; never uses the full name, and never
  invents or shares a member number, date of birth, address, or other
  personal details.
- Shares the user's phone number only when the other party explicitly asks
  for a callback or confirmation number. Never volunteers it.
- Asks one question at a time and waits for the answer.
- If asked whether it is a robot or AI, answers honestly: yes.
- If the other party refuses to speak to an AI, apologises, asks for the
  best time for the user to call back, and ends the call.
- If the other party goes quiet, it follows up once, then wraps up — it
  does not wait in silence indefinitely.
- When the conversation is finished it says a brief goodbye and
  immediately calls the hangup tool. It never waits for the other party
  to hang up first.
- Current tuning: greeting starts immediately (`greeting_delay_ms: 0`),
  speaks slightly slower than normal (`voice_speed: 0.9`), follows up
  after 10 seconds of silence (`user_idle_reply_secs: 10`), and the call
  ends after 40 seconds of continuous silence or 300 seconds total.

Note: the 10-second follow-up is a prompt to the model, not a forced
utterance — in practice it does not always fire, and the assistant may
simply wait quietly. The 40-second timeout is the reliable backstop.

## Staying up to date

- **Code and templates:** `git pull` in this directory (the repo root is
  the skill). Then re-run `python3 scripts/setup.py --sync` to apply the
  latest assistant template to your existing assistant. `setup.py` backs
  up the current assistant config before overwriting it.
- **Or one step:** `bash scripts/update.sh` does both (pull + sync).
- The assistant's instructions, voice, and telephony settings live on
  Telnyx, not in this repo — a `git pull` alone does not change them.
  Re-running `setup.py` is what syncs them.

## Other agents (MCP)

The same phone tools are available to any MCP-capable personal agent
(Claude, Grok Bot, OpenAI Dots, Claude Duet, Cursor, …) through
`mcp_server/server.py` — a dependency-free MCP server (pure Python
standard library). See `mcp_server/README.md` for per-agent config.
It shares the same state file and the same Telnyx assistant as this
skill, so the two can be used interchangeably.

## Costs (Telnyx, approximate)

- Phone number: about $1/month.
- A 5-minute AI call inside North America: about $0.30–$0.40 (line +
  platform + AI inference). Calls to mobiles cost slightly more than to
  landlines. Calls outside the US/CA whitelist cost more and need the
  destination allow-listed in the Telnyx Portal first.
- Check your balance in the Telnyx Portal; auto-recharge is off by default.

## Limits

- Outbound calls only. The number is a caller ID; return calls are not
  answered unless you set up forwarding separately.
- English by default, Chinese supported per call. Pass `--language zh`
  to `call.py` (or `language: "zh"` to the MCP `make_phone_call` tool)
  and the assistant speaks and listens in Chinese for that call —
  instructions and transcription are overridden per call from
  `templates/assistant_zh.json`. Other languages need a translated
  template added the same way.
- Outbound destinations default to US + CA. Other countries need
  allow-listing in the Telnyx outbound voice profile.
- The assistant is only as good as its task brief. Complex negotiations
  and anything needing a real-time decision should stay with a human.
- Recording and AI-disclosure rules vary by jurisdiction. The greeting
  identifies the caller as AI; check local consent law before recording.
- See `references/ARCHITECTURE.md` for the full architecture and
  `references/TROUBLESHOOTING.md` for common failures.

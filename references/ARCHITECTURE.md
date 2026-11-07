# Architecture

## The idea in one paragraph

One general-purpose voice assistant does all the talking. It holds only the
shared rules (identity, privacy, turn-taking, hangup). Every call passes
two things that make it specific — the exact opening line and a short task
brief — as per-call overrides. So there is one assistant to maintain, and
every scenario is just a different brief. Muse is the operator: it writes
the brief, dials, watches the call, and reports back.

## Component map

```
You (phone / Muse app)
  │  "Call the clinic and ask about CDCP"
  ▼
Muse ── this skill ──────────────────────────────────────────────┐
  │  scripts/setup.py   one-command install / sync              │
  │  scripts/call.py    dial + per-call greeting + task brief   │
  │  scripts/review.py  transcript + timing + recording         │
  │  scripts/telnyx_client.py  Telnyx API (key from env/config) │
  ▼                                                              │
Telnyx API (api.telnyx.com)                                      │
  │  POST /v2/calls { connection_id, to, from,                   │
  │                   assistant: { id, greeting,                │
  │                                dynamic_variables } }         │
  ▼                                                              │
Telnyx AI Assistant — "Muse General Phone Assistant"            │
  │  Brain:  openai/gpt-5.6-sol  (via Telnyx inference)         │
  │  Ears:   Deepgram Flux (speech-to-text, English)             │
  │  Voice:  Telnyx Ultra (text-to-speech, speed 0.9)           │
  │  Rules:  shared instructions + {{task_brief}}                │
  │  Tools:  hangup (ends the call promptly)                     │
  ▼                                                              │
PSTN ──► the person / business being called ──────────────────────┘
  │
  └─► transcript + recording flow back to Telnyx, then to review.py
```

## The call flow

1. **You tell Muse** who to call and what to ask. Muse confirms the
   destination and the task with you first.
2. **Muse dials** (`call.py` → `POST /v2/calls`). The request carries the
   assistant id plus two per-call overrides: the `greeting` (exact opening
   line) and `dynamic_variables.task_brief` (what to do on this call).
   Telnyx warms up the assistant while the phone rings.
3. **The called party answers.** The assistant speaks its greeting. The
   greeting is a static string, so the audio is ready immediately — it does
   not wait for the language model to generate a first token.
4. **Conversation.** The assistant asks one question at a time and waits.
   Speech is transcribed by Deepgram, the brain (GPT-5.6-Sol) decides the
   reply, Telnyx Ultra speaks it. The assistant shares the caller's phone
   number only when explicitly asked, and never volunteers personal details.
5. **End.** When the task is done (or the other party says goodbye, or
   refuses to speak to an AI), the assistant says a brief goodbye and
   immediately calls the `hangup` tool. The call ends within about a second
   — it does not linger and burn minutes.
6. **Review.** `review.py` pulls the transcript, the timing (including
   greeting latency), and the dual-channel recording.

## Why one general assistant (not one per scenario)

Telnyx lets a single stored assistant supply defaults while each call
overrides the greeting, instructions, tools, voice, and transcription
("Reuse one assistant with per-call settings ... a separate stored
assistant per voice or business is not required"). It also supports
dynamic variables — `{{task_brief}}` placeholders in the instructions
that are filled with call-specific values at runtime. So the shared rules
live in one place and only the brief changes per call. Maintaining N
assistants for N scenarios meant every tuning change (for example, the
silence wait) had to be applied N times. One assistant means one place
to change.

## Layered architecture vs GPT-Live (why the default is layered)

Two architectures were tested on the same tasks:

| | Layered (default) | GPT-Live (experimental) |
|---|---|---|
| Brain / voice | GPT-5.6-Sol (text) + Deepgram STT + Telnyx Ultra TTS | GPT-Live-1, speech-to-speech, voice `OpenAILive.marin` |
| Greeting | Deterministic TTS string; ~1s after pickup, reliably | Model-generated first token; 4s, 14s, or never — unstable |
| Dead calls | Rare; auto-detected and redialled | Frequent: sessions with 0 messages, assistant channel silent |
| Hangup tool | Standard, works | Suspicion it contributed to dead sessions; not proven |
| Needs an OpenAI key | No (Telnyx inference) | Yes (integration secret) |
| Feel | Slightly more "turn-based" | More natural, full-duplex |

The layered path won on reliability: the greeting is a fixed string (no
model latency on the critical path) and the hangup tool is standard. GPT-Live
sounds more natural when it works, but its session startup failed often
enough — including several dead calls in a row with an unchanged, verified
configuration — that it is kept as a backup, not the default. The template
in this repo is the layered one. If you want to try GPT-Live, the change is
one field (`model: openai/gpt-live-1`, `voice: OpenAILive.marin`, plus an
`llm_api_key_ref` pointing at your OpenAI key) — but expect to keep the
layered assistant as the fallback.

## Dead calls: what they are and how they are handled

A "dead" call is one where the conversation record exists but contains
zero messages and the assistant's audio channel is silent — the live
session never started. This was observed with GPT-Live (and, rarely, on
the layered path). Configuration was verified intact each time, so it is a
session-startup failure, not a misconfiguration. Two mitigations are
built in:

- **Detection + redial.** `call.py` waits for the answer, waits N seconds,
  then counts messages. Zero messages while the call is still live means
  dead: it hangs up and redials once.
- **The greeting is static.** A model-generated greeting puts the first
  token on the critical path; a fixed string does not.

## The silence settings (and an honest caveat)

- `greeting_delay_ms: 0` — the greeting starts immediately after pickup.
- `user_idle_reply_secs: 10` — after 10 seconds of caller silence, the
  assistant is prompted to follow up (e.g. "Are you still there?").
- `user_idle_timeout_secs: 40` — after 40 seconds of continuous silence,
  the platform ends the call.
- `time_limit_secs: 300` — hard cap of 5 minutes per call.

Caveat: the 10-second follow-up is a *prompt* to the model, not a forced
utterance. In a tested call the caller was silent for 11–14 seconds on
three occasions and the assistant simply waited quietly each time — it
never spoke up. The assistant waiting patiently feels good, but do not
rely on the nudge to rescue a stalled call. The 40-second timeout is the
reliable backstop.

## Costs (Telnyx, approximate, North America)

- Phone number: ~$1/month.
- A 5-minute AI call: ~$0.30–$0.40 (line + platform + AI inference).
  Calls to mobiles run slightly higher than to landlines in practice.
- Calls outside the US/CA whitelist cost more and need the destination
  allow-listed first.
- There is no per-call AI line item on Telnyx invoices; AI cost is folded
  into the balance. Check the Portal for the real totals.

## Why a Skill (and not MCP) for v1

Muse's native extension unit is a Skill: a directory with a `SKILL.md`
and scripts. Installing it is a `git clone` into the custom-skills folder,
and updating it is a `git pull` plus a re-run of `setup.py`. That is the
lowest-friction path for the target user (a Muse user), and it needs no
running server. The scripts themselves are plain Python with no Muse-only
dependency (the API key can come from an environment variable), so they can
be wrapped in an MCP server later for other clients. MCP is on the roadmap,
not in v1 — the goal was the smallest thing that works out of the box.

## Security notes

- The Telnyx API key is a secret. It is never written into this repo, into
  a chat message, or into a log. It lives in an environment variable, a
  `.env` file, `~/.config/muse-ai-phone/config.json`, or Muse's secure
  connection — all of which are git-ignored.
- The assistant never discloses the caller's full name, member numbers,
  dates of birth, or other identifiers, and shares the caller's phone
  number only when explicitly asked.
- Recordings may contain personal data. They are git-ignored by default
  and should be stored where the user controls access.

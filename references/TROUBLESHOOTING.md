# Troubleshooting

## The call connects but the assistant never speaks (dead call)

Symptoms: the conversation exists but has 0 messages; the assistant's
audio channel is silent; the call runs until the timeout or the other
party hangs up.

- `call.py` already detects this and redials once. If the redial also
  dies, wait a few minutes and try again — dead sessions have been observed
  to cluster in time with an unchanged, verified configuration, which
  points to session startup failing on Telnyx's side, not to your setup.
- Confirm the assistant still exists and is intact:
  `python3 scripts/telnyx_client.py get /v2/ai/assistants/<id>`. Check that
  `model`, `greeting`, `voice_settings`, and `tools` are all present.
- If you switched the assistant to GPT-Live (`openai/gpt-live-1`), switch
  back to the layered template (`python3 scripts/setup.py --sync`). GPT-Live
  session startup is the flakiest part of the system.
- Do not keep redialling in a tight loop. If two attempts die, stop and
  investigate rather than burning minutes.

## The greeting is slow (several seconds of silence after pickup)

- Make sure the greeting is a **static string**, not a model-generated
  greeting. A model-generated greeting puts the first token on the
  critical path. `call.py` always passes a static `greeting`, so this
  should not happen on the default path.
- Check `telephony_settings.greeting_delay_ms` is `0` on the assistant
  (`setup.py --sync` re-applies it from the template).
- Note that Telnyx warms the assistant up while the phone rings. If
  warm-up fails, the assistant starts from scratch after pickup, which
  adds a few seconds. There is no way to force warm-up to succeed; the
  static greeting keeps the delay small.

## The assistant will not hang up (call lingers after goodbye)

- The assistant needs the **hangup tool**. Check the assistant has a tool
  of `type: hangup`. `setup.py --sync` re-applies it from the template.
- The instructions must also tell it to call the tool right after the
  final goodbye. The template does this; if you edited the instructions,
  keep that rule.
- If the other party keeps talking after the goodbye, the assistant may
  keep responding instead of hanging up. The 40-second idle timeout and
  the 300-second total cap bound the cost in that case.

## The assistant jumps in too fast (or not at all) during silences

- The follow-up delay is `user_idle_reply_secs` (default 10). Change it in
  `templates/assistant.json`, then run `setup.py --sync`.
- Honest caveat: the follow-up is a prompt to the model, not a forced
  utterance. In testing it did not fire even after 11–14 seconds of
  silence — the assistant simply waited. If you need a guaranteed nudge,
  this setting alone will not provide it. The `user_idle_timeout_secs`
  (default 40) is the reliable backstop: it ends the call.

## `401` from the Telnyx API

- The API key is missing, wrong, or revoked. Check `TELNYX_API_KEY`, the
  `.env` file, `~/.config/muse-ai-phone/config.json`, or the `custom.telnyx`
  connection in Muse. Generate a new v2 key in the Telnyx Portal
  (Auth > API Keys) if needed.
- Never paste the key into chat. Rotate it if it was ever exposed.

## `setup.py` says "No active Telnyx phone number found"

- Buy a number first: Telnyx Portal > Numbers > Buy Numbers. Pick a Local
  number in your country (about $1/month). Then re-run `setup.py`.
- If you bought a number but it is not "active" yet, wait for provisioning
  and re-run.

## The number is not attached to a Call Control app

- `setup.py` creates an app called "Muse AI Phone" and assigns the number
  to it automatically. If that step failed, create the app manually
  (Telnyx Portal > Voice > Call Control Applications) and re-run
  `setup.py --connection-id <id>`.

## The call is rejected / the destination is unreachable

- Outbound destinations are controlled by the Telnyx outbound voice
  profile whitelist (default US + CA). To call elsewhere, add the country
  in the Portal (Voice > Outbound Voice Profiles > your profile >
  whitelisted destinations). This is a manual Portal step by design.
- Check the destination number is in E.164 format (`+` + country code +
  number, no spaces or dashes).

## `review.py` finds no conversation

- The conversation list is ordered newest-first and paged. If the call
  was more than a few calls ago, the `--session` lookup only scans the
  latest 10 conversations — pass `--conversation <id>` directly instead
  (the id is printed by `call.py`).
- If the call never connected (no answer), there is no conversation at all.

## No recording for a call

- Recordings are created when the call is recorded (the template enables
  it). If a call has no recording, check the assistant's telephony
  settings and that the call actually connected.
- The recordings API is eventually consistent; a recording created seconds
  ago may not be listable yet. Wait a minute and retry `review.py`.

## Rate limits / `429`

- Stop and wait. Do not retry in a loop, switch endpoints, or lower the
  rate to work around it. Telnyx rate limits are per-account; a burst of
  redials is the usual cause.

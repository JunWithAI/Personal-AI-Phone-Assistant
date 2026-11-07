#!/usr/bin/env python3
"""Place an AI phone call with the general assistant.

The assistant itself holds only the shared rules. Each call passes two
things that make it specific:
  - ``--greeting``: the exact opening line for this call.
  - ``--task-brief``: what to ask, book, or confirm on this call.

Both are sent as per-call overrides, so one stored assistant serves every
scenario. The caller's name and phone come from the assistant's stored
dynamic variables (set by ``setup.py``).

Language: the stored assistant is English. Pass ``--language zh`` for a
Chinese call — the script then overrides the assistant's ``instructions``
and ``transcription`` for this call only (from
``templates/assistant_zh.json``), so the assistant speaks and listens in
Chinese. Telnyx per-call overrides replace the stored objects, so one
stored assistant serves both languages. ``--language en`` (default) uses
the stored English configuration unchanged.

Dead-call protection: after the call is answered, this script waits
``--wait`` seconds and checks whether the assistant has spoken. If the
conversation is empty (a dead session — the assistant never started) and
the call is still live, it hangs up and redials, up to ``--attempts`` times.

Usage:
  python3 call.py --to +15551234567 --greeting "..." --task-brief "..."
                  [--language zh] [--wait 15] [--attempts 2] [--state PATH]
                  [--assistant-id ID] [--connection-id ID] [--from NUMBER]

  --to            Destination number in E.164 format (required).
  --greeting      Exact opening line (required). Keep it to one or two
                  sentences and put the first question in it.
  --task-brief    What the assistant should do on this call (required).
                  Be specific: who it is calling, what to ask, what to
                  book or confirm, and what counts as done.
  --language      Call language: ``en`` (default, stored config) or ``zh``
                  (Chinese — overrides instructions + transcription).
  --wait          Seconds to wait after answer before checking the
                  assistant spoke (default 15).
  --attempts      Maximum dial attempts, including redials (default 2).
  --state         State file from setup.py (default
                  ~/.config/muse-ai-phone/state.json).

The script prints a JSON summary of every attempt, including the
``call_session_id`` and ``conversation_id`` — pass one of those to
``review.py`` to read the transcript and recording afterwards.

Only run this after the person who will pay for the call has confirmed
the destination and the task. The assistant will identify itself as AI
in the greeting.
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from telnyx_client import call as telnyx_call  # noqa: E402

DEFAULT_STATE = Path.home() / ".config" / "muse-ai-phone" / "state.json"
REPO_DIR = Path(__file__).resolve().parent.parent
ZH_TEMPLATE_PATH = REPO_DIR / "templates" / "assistant_zh.json"


def load_state(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def load_zh_template():
    """Return the Chinese assistant template (instructions + transcription)."""
    try:
        return json.loads(ZH_TEMPLATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def dial(to_number, greeting, task_brief, connection_id, from_number,
         assistant_id, language="en"):
    assistant = {
        "id": assistant_id,
        "greeting": greeting,
        "dynamic_variables": {"task_brief": task_brief},
    }
    if language == "zh":
        # Per-call override: Chinese instructions + Chinese transcription.
        # Telnyx replaces the stored objects, so one stored assistant
        # serves both languages.
        zh = load_zh_template()
        if zh.get("instructions"):
            assistant["instructions"] = zh["instructions"]
        if zh.get("transcription"):
            assistant["transcription"] = zh["transcription"]
    status, payload = telnyx_call("POST", "/v2/calls", {
        "connection_id": connection_id,
        "to": to_number,
        "from": from_number,
        "assistant": assistant,
    })
    if status < 200 or status >= 300:
        return None, {"status": status, "error": payload}
    data = payload.get("data", {})
    return {
        "call_control_id": data.get("call_control_id"),
        "call_leg_id": data.get("call_leg_id"),
        "call_session_id": data.get("call_session_id"),
    }, None


def conversation_for_session(session_id):
    """Return (conversation_id, last_message_at) for a call session."""
    status, payload = telnyx_call("GET", "/v2/ai/conversations?page[size]=5")
    if status < 200 or status >= 300:
        return None, None
    for conv in payload.get("data", []):
        meta = conv.get("metadata", {}) or {}
        if meta.get("call_session_id") == session_id:
            return conv.get("id"), conv.get("last_message_at")
    return None, None


def message_count(conversation_id):
    status, payload = telnyx_call(
        "GET", f"/v2/ai/conversations/{conversation_id}/messages?page[size]=1"
    )
    if status < 200 or status >= 300:
        return None
    return payload.get("meta", {}).get("total_results")


def call_alive(call_control_id):
    status, payload = telnyx_call("GET", f"/v2/calls/{call_control_id}")
    if status < 200 or status >= 300:
        return False
    return bool(payload.get("data", {}).get("is_alive"))


def hangup(call_control_id):
    status, _ = telnyx_call(
        "POST", f"/v2/calls/{call_control_id}/actions/hangup", {}
    )
    return 200 <= status < 300


def wait_for_answer(call_control_id, timeout_secs=60):
    """Poll until the call has a start_time (answered) or timeout."""
    deadline = time.time() + timeout_secs
    while time.time() < deadline:
        status, payload = telnyx_call("GET", f"/v2/calls/{call_control_id}")
        if 200 <= status < 300:
            start = payload.get("data", {}).get("start_time")
            if start:
                return start
        time.sleep(2)
    return None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--to", required=True, help="destination number (E.164)")
    parser.add_argument("--greeting", required=True, help="exact opening line")
    parser.add_argument("--task-brief", required=True, help="what to do on this call")
    parser.add_argument("--language", choices=["en", "zh"], default="en",
                        help="call language: en (default) or zh (Chinese)")
    parser.add_argument("--wait", type=int, default=15,
                        help="seconds after answer before checking speech")
    parser.add_argument("--attempts", type=int, default=2,
                        help="maximum dial attempts")
    parser.add_argument("--state", default=str(DEFAULT_STATE), help="state file")
    parser.add_argument("--assistant-id", default=None)
    parser.add_argument("--connection-id", default=None)
    parser.add_argument("--from", dest="from_number", default=None)
    args = parser.parse_args(argv)

    state = load_state(args.state)
    assistant_id = args.assistant_id or state.get("assistant_id")
    connection_id = args.connection_id or state.get("connection_id")
    from_number = args.from_number or state.get("from_number")
    if not assistant_id:
        print("ERROR: no assistant id. Run setup.py first (or pass --assistant-id).",
              file=sys.stderr)
        return 1
    if not connection_id or not from_number:
        print("ERROR: no connection id / from number. Run setup.py first.",
              file=sys.stderr)
        return 1

    attempts = []
    for attempt in range(1, args.attempts + 1):
        info, err = dial(args.to, args.greeting, args.task_brief,
                         connection_id, from_number, assistant_id,
                         language=args.language)
        if err:
            attempts.append({"attempt": attempt, "dial_error": err})
            break
        # Wait for the call to be answered FIRST (ringing can take a while),
        # then wait `wait` seconds after answer before judging whether the
        # assistant spoke. Checking from dial time mislabels slow answers
        # as dead calls.
        answered_at = wait_for_answer(info["call_control_id"])
        if answered_at is None:
            attempts.append({
                "attempt": attempt,
                "call_control_id": info["call_control_id"],
                "call_session_id": info["call_session_id"],
                "verdict": "no answer within 60s",
            })
            break
        time.sleep(args.wait)
        conv_id, last_msg = conversation_for_session(info["call_session_id"])
        count = message_count(conv_id) if conv_id else 0
        alive = call_alive(info["call_control_id"])
        record = {
            "attempt": attempt,
            "call_control_id": info["call_control_id"],
            "call_session_id": info["call_session_id"],
            "conversation_id": conv_id,
            "answered_at": answered_at,
            "messages_after_wait": count,
            "last_message_at": last_msg,
            "call_still_alive": alive,
            "dead": (count == 0),
        }
        attempts.append(record)
        if count and count > 0:
            record["verdict"] = "alive - assistant is speaking"
            break
        record["verdict"] = "dead - no messages"
        if attempt < args.attempts and alive:
            hangup(info["call_control_id"])
            record["redial"] = "hung up dead call, redialing"
            time.sleep(2)
        elif attempt < args.attempts:
            record["redial"] = "call already ended, redialing"
            time.sleep(2)
    print(json.dumps(
        {"to": args.to, "assistant": assistant_id, "language": args.language,
         "attempts": attempts},
        indent=2, ensure_ascii=False,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

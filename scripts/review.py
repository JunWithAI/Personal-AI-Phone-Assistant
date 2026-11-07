#!/usr/bin/env python3
"""Review a finished AI phone call: transcript, timing, and recording.

Give it a conversation id, a call session id, or a call control id and it
prints the full transcript in order, the call timing, and whether the
assistant hung up cleanly. It can also download the dual-channel recording.

Usage:
  python3 review.py --conversation <conversation-id> [--download out.mp3]
  python3 review.py --session <call-session-id>     [--download out.mp3]
  python3 review.py --call <call-control-id>        [--download out.mp3]

  --download PATH   Save the call recording (dual-channel mp3) to PATH.
                    Without it, the recording is only listed, not saved.

What it reports:
  - Answered at / ended at / duration (from the call record).
  - Greeting latency: time from answer to the assistant's first message.
  - The full transcript (user / assistant / tool), oldest first.
  - Whether the hangup tool fired (tool result "ok" after the last
    goodbye) — the sign the call ended promptly instead of lingering.
  - The recording id, if one exists.

The recording is dual-channel (one side per channel). To check which side
spoke when, split it with ffmpeg, e.g.:
  ffmpeg -i out.mp3 -af "pan=mono|c0=c1, silencedetect=noise=-40dB:d=0.5" -f null -
"""

import argparse
import datetime
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from telnyx_client import call as telnyx_call  # noqa: E402


def parse_time(value):
    if not value:
        return None
    try:
        return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def find_conversation(session_id=None, call_control_id=None):
    status, payload = telnyx_call("GET", "/v2/ai/conversations?page[size]=10")
    if status < 200 or status >= 300:
        return None
    for conv in payload.get("data", []):
        meta = conv.get("metadata", {}) or {}
        if session_id and meta.get("call_session_id") == session_id:
            return conv
        if call_control_id and meta.get("call_control_id") == call_control_id:
            return conv
    return None


def get_conversation(conversation_id):
    """Fetch a single conversation record (for its metadata)."""
    status, payload = telnyx_call("GET", f"/v2/ai/conversations/{conversation_id}")
    if status < 200 or status >= 300:
        return {}
    # Single-conversation GET returns the object directly.
    if isinstance(payload, dict) and payload.get("id"):
        return payload
    return payload.get("data", {}) if isinstance(payload, dict) else {}


def fetch_messages(conversation_id):
    status, payload = telnyx_call(
        "GET", f"/v2/ai/conversations/{conversation_id}/messages?page[size]=100"
    )
    if status < 200 or status >= 300:
        return []
    messages = payload.get("data", [])
    # API returns newest first; print oldest first.
    return sorted(messages, key=lambda m: m.get("sent_at") or "")


def fetch_call(call_control_id):
    status, payload = telnyx_call("GET", f"/v2/calls/{call_control_id}")
    if status < 200 or status >= 300:
        return {}
    return payload.get("data", {})


def list_recordings(session_id):
    status, payload = telnyx_call(
        "GET", f"/v2/recordings?filter[call_session_id]={session_id}"
    )
    if status < 200 or status >= 300:
        return []
    return payload.get("data", [])


def download_recording(recording_id, dest):
    # The recording download URL is a signed link returned by the API.
    status, payload = telnyx_call("GET", f"/v2/recordings/{recording_id}")
    if status < 200 or status >= 300:
        return False, f"could not fetch recording {recording_id} (HTTP {status})"
    url = (payload.get("data", {}) or {}).get("download_urls", {}).get("mp3")
    if not url:
        return False, "no mp3 download URL in the recording record"
    request = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            Path(dest).write_bytes(response.read())
    except Exception as exc:  # noqa: BLE001 - report and continue
        return False, f"download failed: {exc}"
    return True, dest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--conversation", help="conversation id")
    group.add_argument("--session", help="call session id")
    group.add_argument("--call", dest="call_control_id", help="call control id")
    parser.add_argument("--download", help="save the recording mp3 to this path")
    args = parser.parse_args(argv)

    conversation_id = args.conversation
    session_id = args.session
    call_control_id = args.call_control_id

    if not conversation_id:
        conv = find_conversation(session_id, call_control_id)
        if conv is None:
            print("ERROR: no conversation found for the given id.", file=sys.stderr)
            return 1
        conversation_id = conv["id"]
        meta = conv.get("metadata", {}) or {}
        session_id = session_id or meta.get("call_session_id")
        call_control_id = call_control_id or meta.get("call_control_id")
    else:
        # Resolve the call/session ids from the conversation record so the
        # timing and recording sections work with --conversation too.
        conv = get_conversation(conversation_id)
        meta = conv.get("metadata", {}) or {}
        session_id = session_id or meta.get("call_session_id")
        call_control_id = call_control_id or meta.get("call_control_id")

    messages = fetch_messages(conversation_id)
    call_rec = fetch_call(call_control_id) if call_control_id else {}
    start = parse_time(call_rec.get("start_time"))
    end = parse_time(call_rec.get("end_time"))

    print(f"Conversation: {conversation_id}")
    if session_id:
        print(f"Call session: {session_id}")
    if start and end:
        print(f"Answered: {start.isoformat()}  Ended: {end.isoformat()}  "
              f"Duration: {(end - start).total_seconds():.0f}s")
    elif start:
        print(f"Answered: {start.isoformat()}  (call still open or end time missing)")

    # Greeting latency: answer -> first assistant message.
    first_assistant = next((m for m in messages if m.get("role") == "assistant"), None)
    if start and first_assistant:
        first_at = parse_time(first_assistant.get("sent_at"))
        if first_at:
            print(f"Greeting latency: {(first_at - start).total_seconds():.1f}s "
                  f"(answer -> first assistant message)")

    # Did the hangup tool fire?
    hangup_ok = any(
        m.get("role") == "tool" and "ok" in (m.get("text") or "")
        for m in messages
    )
    tool_calls = [m for m in messages if m.get("role") == "assistant"
                  and "hangup" in (m.get("text") or "").lower()]
    print(f"Hangup tool fired: {'yes' if hangup_ok else 'no'}"
          + ("" if hangup_ok else " (call may have lingered until timeout)"))

    print(f"\nTranscript ({len(messages)} messages):")
    for m in messages:
        role = m.get("role")
        text = (m.get("text") or "").strip()
        if not text and role == "assistant":
            text = "(empty message)"
        print(f"--- {role} | {m.get('sent_at')}")
        print(text)

    recordings = list_recordings(session_id) if session_id else []
    if recordings:
        rec = recordings[0]
        print(f"\nRecording: {rec.get('id')} (dual-channel, created {rec.get('created_at')})")
        if args.download:
            ok, info = download_recording(rec["id"], args.download)
            print(f"Download: {'saved to ' + info if ok else info}")
    else:
        print("\nRecording: none found for this session.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

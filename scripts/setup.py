#!/usr/bin/env python3
"""One-command setup (and update) for the muse-ai-phone-assistant skill.

This script is idempotent: run it once to install, run it again any time
to sync the latest assistant template from this repo onto your existing
assistant. That is the update mechanism — ``git pull`` refreshes the code
and templates, then this script re-applies them to the assistant that
lives on Telnyx.

What it does, in order:
  1. Verifies your Telnyx API key (``TELNYX_API_KEY``, a ``.env`` file,
     ``~/.config/muse-ai-phone/config.json``, or Muse's ``custom.telnyx``
     secure connection).
  2. Finds your Telnyx phone number (the first active one, or ``--from``).
     If you have no number yet it stops and tells you how to buy one.
  3. Makes sure the number is attached to a Call Control application.
     If it is not, it creates one called "Muse AI Phone" and assigns it.
  4. Creates the general phone assistant from ``templates/assistant.json``,
     or updates the existing one in place (backing up its current config
     first). The assistant holds only the shared rules; every call passes
     its own greeting and task brief.
  5. Saves state (assistant id, connection id, from number) and prints a
     summary plus the command for a first test call.

What it does NOT do (these stay manual, by design):
  - Create your Telnyx account, pass KYC, add a payment method, or buy a
    phone number. Telnyx requires the account holder to do those steps.
  - Change your outbound-voice-profile destination whitelist. It reports
    what it finds; you change it in the Telnyx Portal if needed.

Usage:
  python3 setup.py [--name NAME] [--phone PHONE] [--from NUMBER]
                   [--connection-id ID] [--state PATH] [--dry-run] [--sync]

  --name          Caller's first name, used in greetings and instructions.
                  Defaults to the saved value, then to "Alex".
  --phone         Caller's own phone number. The assistant shares it ONLY
                  when the other party explicitly asks for it. Optional.
  --from          Your Telnyx number to call from (E.164, e.g. +15551234567).
                  Defaults to your first active Telnyx number.
  --connection-id Call Control application connection id. Defaults to the
                  connection your --from number is attached to.
  --state         State file path. Default: ~/.config/muse-ai-phone/state.json
  --dry-run       Show what would happen without changing anything.
  --sync          Same as a normal run (re-apply the template). Provided so
                  the update step reads as an update.
"""

import argparse
import datetime
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from telnyx_client import call as telnyx_call  # noqa: E402

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_DIR = SCRIPT_DIR.parent
TEMPLATE_PATH = REPO_DIR / "templates" / "assistant.json"
DEFAULT_STATE = Path.home() / ".config" / "muse-ai-phone" / "state.json"
APP_NAME = "Muse AI Phone"


def unwrap_assistant(payload):
    """Return the assistant dict from a single-assistant response.

    Telnyx returns a single assistant as the object itself (no ``data``
    wrapper), while list endpoints nest items under ``data``. Accept both.
    """
    if not isinstance(payload, dict):
        return None
    if payload.get("id"):
        return payload
    data = payload.get("data")
    return data if isinstance(data, dict) else None


def load_state(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(path, state):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def prompt(text, default=""):
    try:
        value = input(f"{text} [{default}]: ").strip()
    except (EOFError, KeyboardInterrupt):
        value = ""
    return value or default


def fail(message, code=1):
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(code)


def list_phone_numbers():
    status, payload = telnyx_call("GET", "/v2/phone_numbers?page[size]=20")
    if status < 200 or status >= 300:
        fail(f"could not list phone numbers (HTTP {status}): {payload}")
    return payload.get("data", [])


def find_assistant_by_name(name):
    status, payload = telnyx_call("GET", "/v2/ai/assistants?page[size]=20")
    if status < 200 or status >= 300:
        return None
    for item in payload.get("data", []):
        if item.get("name") == name:
            return item
    return None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", default=None, help="caller's first name")
    parser.add_argument("--phone", default=None, help="caller's own phone number")
    parser.add_argument("--from", dest="from_number", default=None,
                        help="Telnyx number to call from (E.164)")
    parser.add_argument("--connection-id", default=None,
                        help="Call Control application connection id")
    parser.add_argument("--state", default=str(DEFAULT_STATE),
                        help="state file path")
    parser.add_argument("--dry-run", action="store_true",
                        help="show what would happen, change nothing")
    parser.add_argument("--sync", action="store_true",
                        help="re-apply the template (same as a normal run)")
    args = parser.parse_args(argv)
    dry = args.dry_run
    state = load_state(args.state)

    # 1. Verify the API key by listing assistants (a cheap, read-only call).
    print("Step 1/5: verifying Telnyx API key ...")
    status, payload = telnyx_call("GET", "/v2/ai/assistants?page[size]=1")
    if status == 401:
        fail("Telnyx API key was rejected (401). Check TELNYX_API_KEY or "
             "your custom.telnyx connection, then re-run setup.py.")
    if status < 200 or status >= 300:
        fail(f"Telnyx API check failed (HTTP {status}): {payload}")
    print("  API key OK.")

    # 2. Find the phone number to call from.
    print("Step 2/5: finding your Telnyx phone number ...")
    numbers = list_phone_numbers()
    active = [n for n in numbers if n.get("status") == "active"]
    chosen = None
    if args.from_number:
        for n in numbers:
            if n.get("phone_number") == args.from_number:
                chosen = n
                break
        if chosen is None:
            fail(f"number {args.from_number} was not found in your Telnyx account.")
    elif state.get("from_number"):
        for n in numbers:
            if n.get("phone_number") == state["from_number"]:
                chosen = n
                break
    if chosen is None:
        chosen = active[0] if active else None
    if chosen is None:
        fail(
            "No active Telnyx phone number found. Buy one first:\n"
            "  Telnyx Portal > Numbers > Buy Numbers — pick a Local number in\n"
            "  your country (about $1/month). Then re-run setup.py."
        )
    from_number = chosen["phone_number"]
    number_id = chosen["id"]
    print(f"  Using {from_number} (number id {number_id}).")

    # 3. Make sure the number is attached to a Call Control application.
    print("Step 3/5: checking the number's Call Control application ...")
    connection_id = args.connection_id or state.get("connection_id") or chosen.get("connection_id")
    if not connection_id:
        if dry:
            print(f"  [dry-run] would create Call Control app '{APP_NAME}' and assign {from_number} to it.")
            connection_id = "<new-app>"
        else:
            status, payload = telnyx_call("POST", "/v2/call_control_applications", {
                "application_name": APP_NAME,
                "webhook_event_url": "https://example.com/webhooks/telnyx",
                "active": True,
            })
            if status < 200 or status >= 300:
                fail(f"could not create a Call Control application (HTTP {status}): {payload}\n"
                     "Create one in the Telnyx Portal (Voice > Call Control Applications), "
                     "then re-run setup.py with --connection-id <id>.")
            connection_id = payload["data"]["id"]
            print(f"  Created Call Control app '{APP_NAME}' ({connection_id}).")
            status, payload = telnyx_call(
                "PATCH", f"/v2/phone_numbers/{number_id}",
                {"connection_id": connection_id},
            )
            if status < 200 or status >= 300:
                print(f"  WARNING: could not assign {from_number} to the app (HTTP {status}).")
                print("  Assign it manually: Telnyx Portal > Numbers > your number > "
                      f"Connection > {APP_NAME}.")
            else:
                print(f"  Assigned {from_number} to '{APP_NAME}'.")
    else:
        print(f"  Connection id {connection_id}.")

    # 4. Load the assistant template and fill in the caller's details.
    print("Step 4/5: preparing the general phone assistant ...")
    template = json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))
    caller_name = args.name or state.get("caller_name") or ""
    caller_phone = args.phone or state.get("caller_phone") or ""
    if not caller_name:
        if sys.stdin.isatty():
            caller_name = prompt("Your first name (used in greetings)", "Alex")
        else:
            caller_name = "Alex"
    if caller_phone == "" and args.phone is None and sys.stdin.isatty() and not state.get("caller_phone"):
        caller_phone = prompt("Your own phone number (shared ONLY when asked; blank to skip)", "")
    template["dynamic_variables"]["caller_name"] = caller_name
    template["dynamic_variables"]["caller_phone"] = caller_phone
    if not caller_phone:
        # Do not leave an empty number in the instructions; say it plainly.
        lines = template["instructions"].split("\n")
        lines = [
            ("- If asked for a callback or confirmation number, say "
             f"{caller_name} will provide it directly — do not invent a number.")
            if line.startswith("- Share ") and "phone number" in line else line
            for line in lines
        ]
        template["instructions"] = "\n".join(lines)

    assistant_id = state.get("assistant_id")
    existing = None
    if assistant_id:
        status, payload = telnyx_call("GET", f"/v2/ai/assistants/{assistant_id}")
        if 200 <= status < 300:
            existing = unwrap_assistant(payload)
    if existing is None:
        found = find_assistant_by_name(template["name"])
        if found:
            existing = found
            assistant_id = found["id"]

    if existing:
        if dry:
            print(f"  [dry-run] would update assistant {assistant_id} from the template.")
        else:
            backup_dir = Path.home() / ".config" / "muse-ai-phone" / "backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            backup_path = backup_dir / f"assistant-{assistant_id}-{stamp}.json"
            backup_path.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"  Backed up current assistant config to {backup_path}.")
            status, payload = telnyx_call(
                "PATCH", f"/v2/ai/assistants/{assistant_id}", template
            )
            if status < 200 or status >= 300:
                fail(f"could not update the assistant (HTTP {status}): {payload}")
            print(f"  Updated assistant {assistant_id} from the template.")
    else:
        if dry:
            print("  [dry-run] would create the assistant from the template.")
            assistant_id = "<new-assistant>"
        else:
            status, payload = telnyx_call("POST", "/v2/ai/assistants", template)
            if status < 200 or status >= 300:
                fail(f"could not create the assistant (HTTP {status}): {payload}")
            assistant_id = payload.get("id") or payload.get("data", {}).get("id")
            print(f"  Created assistant {assistant_id}.")

    # 5. Verify and save state.
    print("Step 5/5: verifying and saving state ...")
    if not dry and assistant_id and not str(assistant_id).startswith("<"):
        status, payload = telnyx_call("GET", f"/v2/ai/assistants/{assistant_id}")
        if status < 200 or status >= 300:
            fail(f"assistant {assistant_id} was created but cannot be read back (HTTP {status}).")
        body = unwrap_assistant(payload) or {}
        tel = body.get("telephony_settings", {})
        print(f"  Verified: model {body.get('model')}, "
              f"idle_reply {tel.get('user_idle_reply_secs')}s, "
              f"idle_timeout {tel.get('user_idle_timeout_secs')}s, "
              f"greeting_delay {tel.get('greeting_delay_ms')}ms.")
        state.update({
            "assistant_id": assistant_id,
            "connection_id": connection_id,
            "from_number": from_number,
            "caller_name": caller_name,
            "caller_phone": caller_phone,
        })
        save_state(args.state, state)
        print(f"  State saved to {args.state}.")
    elif dry:
        print("  [dry-run] nothing saved.")

    print()
    print("Done. Your general phone assistant is ready.")
    print(f"  Assistant: {assistant_id}")
    print(f"  Calls from: {from_number} (connection {connection_id})")
    print("  Make a first test call with:")
    print("    python3 scripts/call.py --to <YOUR_MOBILE> \\")
    print('      --greeting "Hi, I\'m an AI assistant calling for '
          f'{caller_name}. Could you confirm this is a test call?" \\')
    print('      --task-brief "This is a test call. Ask the person who answers '
          'to confirm they can hear you clearly, then thank them and end the call."')
    print("  Then review it with: python3 scripts/review.py --session <call_session_id>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

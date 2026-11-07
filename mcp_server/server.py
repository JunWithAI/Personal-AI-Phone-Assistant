#!/usr/bin/env python3
"""Muse AI Phone Assistant — MCP server (dependency-free).

Exposes the phone tools over the Model Context Protocol so *any* personal
agent that speaks MCP (Claude, Grok Bot, OpenAI Dots, Claude Duet, Cursor,
and others) can use them — not just Muse.

Transport: newline-delimited JSON-RPC 2.0 over stdio (the standard local
MCP transport). This server uses only the Python standard library: no
``pip install`` is needed. Run it with::

    python3 mcp_server/server.py

and point your agent at that command. See ``mcp_server/README.md`` for
per-agent configuration examples.

Tools
-----
``setup_phone_assistant``
    Create (or update) the general phone assistant from the template.
``make_phone_call``
    Place a call: pass the destination, the exact opening line, and a task
    brief. Returns a JSON summary (call ids, whether the assistant spoke,
    whether the call was retried).
``review_phone_call``
    Read back a call: transcript, timing, greeting latency, whether the
    hangup tool fired, and the recording id.
``get_phone_assistant_status``
    Check whether the assistant is set up and ready to call.

The first three tools run the matching script under ``scripts/`` as a
subprocess and return its output, so the scripts stay the single source of
truth. The status tool reads the Telnyx API directly (the client module
does not write to stdout, so it is safe to use in-process).

Protocol note: stdout is the MCP transport. Nothing in this file (or in
anything it imports) may print to stdout. All diagnostics go to stderr.
"""

import json
import subprocess
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
DEFAULT_STATE = Path.home() / ".config" / "muse-ai-phone" / "state.json"

SERVER_NAME = "muse-ai-phone-assistant"
SERVER_VERSION = "1.0.0"
# MCP protocol versions this server understands. The client sends one in
# `initialize`; we echo it back if it is in this list, else fall back.
KNOWN_PROTOCOL_VERSIONS = ("2024-11-05", "2025-03-26", "2025-06-18")
DEFAULT_PROTOCOL_VERSION = "2025-03-26"

# How long a single tool call may run (a call with a retry can take minutes).
TOOL_TIMEOUT_SECONDS = 600


def log(message):
    """Diagnostics go to stderr — never stdout (stdout is MCP)."""
    print(f"[mcp-server] {message}", file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# Tool definitions (name, description, JSON Schema)
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "setup_phone_assistant",
        "description": (
            "Set up the general AI phone assistant on Telnyx (create it if it "
            "does not exist, or update it from the latest template if it does). "
            "Run this once before making calls, and again after updating the "
            "skill to apply template changes. Requires a Telnyx API key to be "
            "configured (TELNYX_API_KEY, .env, or the Muse secure connection) "
            "and a Telnyx phone number on the account."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "The caller's first name, used in greetings (e.g. 'Alex').",
                },
                "phone": {
                    "type": "string",
                    "description": (
                        "The caller's own phone number in E.164 format "
                        "(e.g. '+15551234567'). Only shared when the other party "
                        "explicitly asks for it. Optional."
                    ),
                },
            },
            "required": ["name"],
        },
    },
    {
        "name": "make_phone_call",
        "description": (
            "Place an AI phone call. Pass the destination number, the exact "
            "opening line to speak, and a task brief describing what to ask, "
            "book, or confirm. The assistant speaks the greeting as soon as "
            "the call is answered, works through the brief one question at a "
            "time, and hangs up when done. If the assistant never speaks "
            "(a dead session), the call is hung up and retried once. "
            "Confirm the destination and the task with the user before "
            "calling. This tool can take a few minutes (dialling, waiting "
            "for an answer, and a possible retry). Returns a JSON summary "
            "with the call ids and what happened."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": "Destination phone number in E.164 format (e.g. '+15551234567').",
                },
                "greeting": {
                    "type": "string",
                    "description": (
                        "The exact opening line the assistant speaks when the "
                        "call is answered. It must identify the caller as an AI "
                        "assistant and name the person it is calling for "
                        "(e.g. \"Hi, I'm an AI assistant calling for Alex. ...\")."
                    ),
                },
                "task_brief": {
                    "type": "string",
                    "description": (
                        "What to ask, book, or confirm on this call. Plain "
                        "instructions for the assistant: the questions to ask "
                        "(one at a time), what counts as a confirmed answer, "
                        "and what to do if the other party refuses or asks for "
                        "personal details."
                    ),
                },
                "language": {
                    "type": "string",
                    "enum": ["en", "zh"],
                    "description": (
                        "Call language. 'en' (default) uses the stored English "
                        "assistant. 'zh' makes the call in Chinese: the "
                        "assistant speaks and listens in Chinese (instructions "
                        "and transcription overridden per call). The greeting "
                        "and task_brief should be written in the same language."
                    ),
                },
            },
            "required": ["to", "greeting", "task_brief"],
        },
    },
    {
        "name": "review_phone_call",
        "description": (
            "Review a completed call: transcript, answered/ended times, "
            "duration, greeting latency (answer to first assistant message), "
            "whether the hangup tool fired, and the recording id. Give exactly "
            "one of conversation_id, session_id, or call_control_id."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "conversation_id": {
                    "type": "string",
                    "description": "Telnyx AI conversation id (from make_phone_call).",
                },
                "session_id": {
                    "type": "string",
                    "description": "Telnyx call session id.",
                },
                "call_control_id": {
                    "type": "string",
                    "description": "Telnyx call control id.",
                },
            },
        },
    },
    {
        "name": "get_phone_assistant_status",
        "description": (
            "Check whether the phone assistant is set up and ready to call. "
            "Returns the assistant id, the model it uses, the Telnyx number "
            "calls come from, and whether setup has been run. No arguments."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
]


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def run_script(script, args, timeout=TOOL_TIMEOUT_SECONDS):
    """Run one of the skill's scripts and return (ok, stdout, stderr)."""
    cmd = [sys.executable, str(SCRIPTS_DIR / script)] + args
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        return False, "", f"timed out after {timeout}s: {' '.join(cmd)}"
    except Exception as exc:  # noqa: BLE001 - surface as a tool error
        return False, "", f"could not run {script}: {exc}"
    return proc.returncode == 0, proc.stdout.strip(), proc.stderr.strip()


def tool_setup_phone_assistant(arguments):
    name = arguments.get("name")
    if not name or not isinstance(name, str):
        return True, "error: 'name' (the caller's first name) is required."
    args = ["--name", name]
    phone = arguments.get("phone")
    if phone:
        args += ["--phone", str(phone)]
    ok, out, err = run_script("setup.py", args)
    if not ok:
        return True, f"setup failed:\n{err or out}"
    return False, out or "setup completed."


def tool_make_phone_call(arguments):
    missing = [k for k in ("to", "greeting", "task_brief")
               if not arguments.get(k)]
    if missing:
        return True, f"error: missing required argument(s): {', '.join(missing)}."
    args = [
        "--to", str(arguments["to"]),
        "--greeting", str(arguments["greeting"]),
        "--task-brief", str(arguments["task_brief"]),
    ]
    language = str(arguments.get("language") or "en").lower()
    if language not in ("en", "zh"):
        return True, "error: language must be 'en' or 'zh'."
    args += ["--language", language]
    ok, out, err = run_script("call.py", args)
    if not ok:
        detail = err or out or "call.py exited without output"
        return True, f"call failed:\n{detail}"
    # call.py prints a single JSON summary on stdout.
    try:
        summary = json.loads(out)
        return False, json.dumps(summary, indent=2, ensure_ascii=False)
    except (ValueError, TypeError):
        return False, out or "call completed (no summary returned)."


def tool_review_phone_call(arguments):
    given = [k for k in ("conversation_id", "session_id", "call_control_id")
             if arguments.get(k)]
    if len(given) != 1:
        return True, (
            "error: give exactly one of 'conversation_id', 'session_id', "
            "or 'call_control_id'."
        )
    key = given[0]
    flag = {
        "conversation_id": "--conversation",
        "session_id": "--session",
        "call_control_id": "--call",
    }[key]
    ok, out, err = run_script("review.py", [flag, str(arguments[key])])
    if not ok:
        return True, f"review failed:\n{err or out}"
    return False, out or "no transcript found for that call."


def tool_get_phone_assistant_status(_arguments):
    # Read-only and in-process: telnyx_client's `call()` writes nothing to
    # stdout, so it is safe to use here.
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        import telnyx_client
    except ImportError as exc:
        return True, f"error: could not load the Telnyx client: {exc}"
    try:
        state = json.loads(DEFAULT_STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    assistant_id = state.get("assistant_id")
    assistant = None
    if assistant_id:
        status, payload = telnyx_client.call(
            "GET", f"/v2/ai/assistants/{assistant_id}"
        )
        if 200 <= status < 300:
            assistant = payload if isinstance(payload, dict) \
                and payload.get("id") else (payload.get("data") or {})
    if assistant is None:
        # No state file (or a stale id): fall back to finding the assistant
        # by the template's name, the same way setup.py does.
        try:
            template = json.loads(
                (REPO_ROOT / "templates" / "assistant.json")
                .read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            template = {}
        wanted = template.get("name", "Muse General Phone Assistant")
        status, payload = telnyx_client.call(
            "GET", "/v2/ai/assistants?page[size]=20"
        )
        if 200 <= status < 300:
            for item in payload.get("data", []):
                if item.get("name") == wanted:
                    assistant = item
                    assistant_id = item.get("id")
                    break
    if assistant is None:
        return False, json.dumps({
            "ready": False,
            "message": (
                "No phone assistant is set up yet. Run setup_phone_assistant "
                "first (it needs a Telnyx API key and a Telnyx number)."
            ),
        }, indent=2)
    # `model` is a plain string ("openai/gpt-5.6-sol") on some assistants and
    # an object on others; normalize it.
    model = assistant.get("model")
    model_name = model.get("model") if isinstance(model, dict) else model
    return False, json.dumps({
        "ready": True,
        "assistant_id": assistant_id,
        "assistant_name": assistant.get("name"),
        "model": model_name,
        "calls_from": state.get("from_number"),
        "connection_id": state.get("connection_id"),
        "caller_name": state.get("caller_name"),
    }, indent=2, ensure_ascii=False)


TOOL_HANDLERS = {
    "setup_phone_assistant": tool_setup_phone_assistant,
    "make_phone_call": tool_make_phone_call,
    "review_phone_call": tool_review_phone_call,
    "get_phone_assistant_status": tool_get_phone_assistant_status,
}


# ---------------------------------------------------------------------------
# Minimal JSON-RPC 2.0 over stdio (MCP)
# ---------------------------------------------------------------------------

def send(message):
    sys.stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def send_result(request_id, result):
    send({"jsonrpc": "2.0", "id": request_id, "result": result})


def send_error(request_id, code, message):
    send({"jsonrpc": "2.0", "id": request_id,
          "error": {"code": code, "message": message}})


def handle_initialize(request_id, params):
    requested = (params or {}).get("protocolVersion")
    version = requested if requested in KNOWN_PROTOCOL_VERSIONS \
        else DEFAULT_PROTOCOL_VERSION
    send_result(request_id, {
        "protocolVersion": version,
        "capabilities": {"tools": {}},
        "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
    })


def handle_tools_list(request_id, _params):
    send_result(request_id, {"tools": TOOLS})


def handle_tools_call(request_id, params):
    params = params or {}
    name = params.get("name")
    arguments = params.get("arguments") or {}
    if not isinstance(arguments, dict):
        send_error(request_id, -32602, "'arguments' must be an object.")
        return
    handler = TOOL_HANDLERS.get(name)
    if handler is None:
        send_error(request_id, -32602, f"unknown tool: {name!r}")
        return
    try:
        is_error, text = handler(arguments)
    except Exception as exc:  # noqa: BLE001 - report as a tool error
        is_error, text = True, f"tool {name} raised: {exc}"
    send_result(request_id, {
        "content": [{"type": "text", "text": text}],
        "isError": is_error,
    })


REQUEST_HANDLERS = {
    "initialize": handle_initialize,
    "tools/list": handle_tools_list,
    "tools/call": handle_tools_call,
    "ping": lambda request_id, _params: send_result(request_id, {}),
}


def main():
    log(f"starting {SERVER_NAME} v{SERVER_VERSION} (stdio, stdlib only)")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            log("ignoring a line that is not JSON")
            continue
        if not isinstance(message, dict):
            continue
        method = message.get("method")
        request_id = message.get("id")
        params = message.get("params") or {}
        # Notifications have no id and get no reply.
        if request_id is None:
            log(f"notification: {method} (ignored)")
            continue
        handler = REQUEST_HANDLERS.get(method)
        if handler is None:
            send_error(request_id, -32601, f"method not found: {method}")
            continue
        try:
            handler(request_id, params)
        except Exception as exc:  # noqa: BLE001 - keep the server alive
            log(f"handler for {method} raised: {exc}")
            send_error(request_id, -32603, f"internal error: {exc}")
    log("stdin closed, exiting")


if __name__ == "__main__":
    main()

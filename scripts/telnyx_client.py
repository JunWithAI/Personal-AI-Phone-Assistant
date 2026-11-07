#!/usr/bin/env python3
"""Standalone Telnyx API client for the muse-ai-phone-assistant skill.

The API key is never stored in this file. It is resolved in this order:

  1. ``TELNYX_API_KEY`` environment variable.
  2. A ``.env`` file next to this script (or in the current directory)
     containing ``TELNYX_API_KEY=...``.
  3. ``~/.config/muse-ai-phone/config.json`` with ``{"telnyx_api_key": ...}``.
  4. When running inside Muse, the ``custom.telnyx`` secure connection
     (Muse's dynamic-credentials helper), if it is available.

Usage as a module::

    from telnyx_client import call
    status, payload = call("GET", "/v2/ai/assistants?page[size]=1")

Usage as a CLI::

    python3 telnyx_client.py get <path>
    python3 telnyx_client.py post <path> [json-body]
    python3 telnyx_client.py patch <path> [json-body]
    python3 telnyx_client.py delete <path>

Redirects are refused. Timeout is 60 seconds.
"""

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE = "https://api.telnyx.com"
ALLOWED_HOSTS = ["api.telnyx.com"]
CREDENTIAL = "custom.telnyx"


def _load_dotenv():
    """Load TELNYX_API_KEY from a .env file if present. Returns the key or None."""
    for candidate in (Path(__file__).resolve().parent / ".env", Path.cwd() / ".env"):
        try:
            for line in candidate.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                key, _, value = line.partition("=")
                if key.strip() == "TELNYX_API_KEY":
                    return value.strip().strip('"').strip("'")
        except OSError:
            continue
    return None


def _load_config_file():
    """Load the API key from ~/.config/muse-ai-phone/config.json. Returns the key or None."""
    path = Path.home() / ".config" / "muse-ai-phone" / "config.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if isinstance(data, dict):
        return data.get("telnyx_api_key")
    return None


def _muse_surrogate_available():
    """Return True when Muse's dynamic-credentials helper can be imported."""
    try:
        sys.path.insert(0, "/opt/muse/skills/custom-connector-setup/bin")
        import dynamic_credentials  # noqa: F401
        return True
    except Exception:
        return False


def resolve_api_key():
    """Return the Telnyx API key, or None when no source provides one."""
    key = os.environ.get("TELNYX_API_KEY")
    if key:
        return key
    key = _load_dotenv()
    if key:
        return key
    key = _load_config_file()
    if key:
        return key
    return None


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        raise RuntimeError("redirect refused, verify the endpoint")


def call(method, path, body=None):
    """Call the Telnyx API. Returns (http_status, parsed_json_body)."""
    url = BASE + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Accept", "application/json")
    if data is not None:
        request.add_header("Content-Type", "application/json")

    key = resolve_api_key()
    if key:
        request.add_header("Authorization", "Bearer " + key)
    elif _muse_surrogate_available():
        # Inside Muse: let the secure connection supply the key.
        from dynamic_credentials import add_surrogate_to_request

        add_surrogate_to_request(request, CREDENTIAL, allowed_hosts=ALLOWED_HOSTS)
    else:
        raise RuntimeError(
            "No Telnyx API key found. Set TELNYX_API_KEY, add it to a .env "
            "file, save it to ~/.config/muse-ai-phone/config.json, or "
            "connect Telnyx in Muse (custom.telnyx)."
        )

    try:
        with urllib.request.build_opener(NoRedirect()).open(
            request, timeout=60
        ) as response:
            raw = response.read().decode("utf-8")
            try:
                return response.status, json.loads(raw)
            except ValueError:
                return response.status, {"raw": raw}
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode("utf-8"))
        except Exception:
            payload = {"raw": "unparseable error body"}
        return exc.code, payload


def main(argv):
    if len(argv) < 3:
        print(
            "usage: telnyx_client.py <get|post|patch|delete> <path> [json-body]",
            file=sys.stderr,
        )
        return 2
    method = argv[1].upper()
    path = argv[2]
    body = json.loads(argv[3]) if len(argv) > 3 else None
    status, payload = call(method, path, body)
    print(json.dumps({"status": status, "body": payload}, indent=2, ensure_ascii=False))
    return 0 if 200 <= status < 300 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

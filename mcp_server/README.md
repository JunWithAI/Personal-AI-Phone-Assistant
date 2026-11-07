# MCP server — use the phone tools from any personal agent

`server.py` exposes the phone tools over the **Model Context Protocol
(MCP)** so any MCP-capable personal agent can use them — not just Muse.

It uses **only the Python standard library**. There is nothing to install:

```bash
python3 mcp_server/server.py
```

That is the whole server. Point your agent at that command (stdio
transport) and it gets four tools: `setup_phone_assistant`,
`make_phone_call`, `review_phone_call`, `get_phone_assistant_status`.
See `server.py` for what each tool does and what it returns.

## Prerequisites

Same as the skill itself: a Telnyx account, a Telnyx phone number, and a
Telnyx API key. The server reads the key the same way the scripts do
(`TELNYX_API_KEY` env var, `.env`, or `~/.config/muse-ai-phone/config.json`).
Set it in the environment of the command below, e.g.:

```bash
TELNYX_API_KEY=... python3 mcp_server/server.py
```

If the key is already in `~/.config/muse-ai-phone/config.json` (because
you ran `setup.py` before), you do not need the env var.

## Configuration examples

Replace `/path/to/muse-ai-phone-assistant` with the real path to this repo.

### Claude Code

`.mcp.json` in your project (or `~/.claude.json` for a user-level server):

```json
{
  "mcpServers": {
    "muse-ai-phone": {
      "command": "python3",
      "args": ["/path/to/muse-ai-phone-assistant/mcp_server/server.py"],
      "env": { "TELNYX_API_KEY": "YOUR_TELNYX_API_KEY" }
    }
  }
}
```

Claude Code also reads `SKILL.md` skills directly, so you can use this
repo as a skill there too — copy the repo (or just `SKILL.md`,
`scripts/`, and `templates/`) into a skills directory.

### Cursor / Grok Bot

Both support MCP servers and skills in the same style as Cursor. Add a
server by command:

- **Command:** `python3`
- **Arguments:** `/path/to/muse-ai-phone-assistant/mcp_server/server.py`
- **Environment:** `TELNYX_API_KEY=YOUR_TELNYX_API_KEY`

In Grok Bot, a server started by a command becomes available to your
other Bots as well.

### OpenAI Dots

Dots use plugins, and a plugin can contain an MCP server (and/or a
`SKILL.md` workflow). Package this repo's `mcp_server/` as the plugin's
MCP server, with the command above. Local tools need a connected
computer — run the server on the machine the Dot can reach.

### Claude Duet

Duet connects to tools over MCP. Register this server the same way you
register any MCP server (command `python3`, args pointing at
`mcp_server/server.py`, env `TELNYX_API_KEY`).

### Any other MCP client

Any client that can start a local MCP server over stdio works. The
command is always:

```text
python3 /path/to/muse-ai-phone-assistant/mcp_server/server.py
```

with `TELNYX_API_KEY` in the environment (or already stored in
`~/.config/muse-ai-phone/config.json`).

## Notes

- **stdout is the MCP transport.** The server logs to stderr only. Do not
  add prints to stdout in `server.py` or in anything it imports.
- **A call can take a few minutes.** `make_phone_call` dials, waits for
  an answer, waits to confirm the assistant spoke, and retries once if
  the session was dead. Give the tool call time to finish.
- **Confirm before calling.** The tools do not ask the user for
  confirmation themselves — the agent using them should confirm the
  destination and the task with the user first, exactly as Muse does.
- **Same state as the skill.** The server runs `scripts/setup.py`,
  `scripts/call.py`, and `scripts/review.py` as subprocesses, so it
  shares the same state file (`~/.config/muse-ai-phone/state.json`) and
  the same assistant. Use the skill and the MCP server interchangeably;
  they operate on the same assistant.
- **Behind a proxy?** MCP clients start the server with a filtered
  environment (for example, the official SDK only inherits an allowlist
  of variables), so proxy variables such as `https_proxy` / `HTTPS_PROXY`
  may not reach the server. If you are behind a proxy and Telnyx calls
  fail, add the proxy variables to the server's `env` block in your
  client config.

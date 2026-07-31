# n8n / remote access reference

The working topology: **shopagent owns all writes and auth; n8n (cloud) is a
read-only window plus notifications; the phone reaches it through Claude's
n8n connector or n8n's chat.**

## The three processes on the PC

| Window | Command | Notes |
|---|---|---|
| 1 | `shopagent serve` | needs `SHOPAGENT_API_TOKEN` in `.env`; binds 127.0.0.1:8787 |
| 2 | `cloudflared tunnel --url http://localhost:8787` | prints the public URL |
| 3 | free | — |

Both must stay running or n8n gets connection errors. Verify the chain with
`https://<tunnel>/health` in a browser → `{"ok":true,"service":"shopagent"}`
(the only unauthenticated route; it reveals nothing).

**Quick tunnels get a NEW hostname every cloudflared restart** — after a
restart, the five+ HTTP tool nodes in n8n all point at a dead URL and must
be updated. If this becomes routine, set up a named Cloudflare tunnel
(needs a domain) for a stable hostname.

## n8n credential (Header Auth)

Credentials → Add credential → **Header Auth** (not Custom, not Basic):

- credential title: `shopagent API` (the workflow JSON references it by
  this name)
- Name: `Authorization`
- Value: `Bearer <token>` — literal word Bearer, one space, the token, no
  quotes. There is no test button for Header Auth; an untested look is
  normal.

Print the token on the PC without exposing it in chat:
`python -c "import os; from shopagent.config import load_config; load_config(); print(os.environ['SHOPAGENT_API_TOKEN'])"`

## The workflow

`shopagent/n8n/store-manager-agent.json` → n8n Workflows → Import from
File. Post-import: replace `REPLACE-WITH-YOUR-TUNNEL.trycloudflare.com` in
every tool node, select the `shopagent API` credential on each. All tools
are GETs; `tests/test_n8n_workflow.py` contract-tests the file against the
API (routes exist, params accepted, **no tool can mutate**) — run it after
any workflow edit.

## Connecting Claude ↔ n8n (MCP)

- n8n side: Settings → **Instance-level MCP** → Enable → Connection details
  (top-right). OAuth tab URL for claude.ai custom connectors; Access Token
  tab for token clients. n8n auto-generates the personal access token.
- Per-workflow gate: a workflow is invisible to MCP until "make available in
  MCP" is enabled on it (workflow card `⋯` menu or workflow settings).
- claude.ai side: Settings → Connectors → Add custom connector (account
  level; then available on mobile). In a Claude Code web session the
  connector must ALSO be toggled on per-chat (tools menu next to the message
  box) — `enabledInChat: false` with `connected: true` means exactly that,
  and the toggle only takes effect for new sessions.

## The rule that keeps the gate

LLM agents (n8n Store Manager, any future workflow) get **GET tools only**.
Approve/reject/retry are POSTs meant for human taps (n8n form button,
notification link, CLI). A system prompt saying "ask first" is not a
control; not holding the tool is. If someone requests an approve tool for
an agent, push back and offer the notify-then-human-tap pattern instead.

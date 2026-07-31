---
name: shopagent-ops
description: Operate, configure, or debug the shopagent system — approvals workflow, dry-run vs live modes, credentials and .env problems, doctor output, Windows setup issues (venv, PATH, PowerShell vs cmd), the HTTP API served for n8n, and tunnel/connector setup. Use when the user reports a shopagent command failing, a credential "not set" despite being configured, asks how to approve/reject/retry actions, wants to connect n8n or their phone, or shares a terminal screenshot of any shopagent error — even if they don't name this skill.
---

# Operating shopagent

The operator is on **Windows** (PowerShell mostly, sometimes cmd), a
beginner with dev tooling. Give copy-pasteable commands, one step at a time,
and read screenshots carefully before advising — several past incidents came
from advice that assumed the wrong shell.

## First diagnostic, always

```
shopagent doctor
```

It reports every credential (set/missing, never values), the resolved
per-integration mode, ffmpeg presence, the render engine, DB health, and
live connection tests. Most "it doesn't work" reports are visible here in
one screen. The mode banner on every command shows the same resolution:
`mode: live` in config.yaml AND that integration's env vars present → live;
anything missing → that integration silently uses its mock (by design).

## The approvals workflow (the system's spine)

Agents cannot change anything external — their only write path is
`propose_action` into the approvals table. The executor performs approved
actions and is invoked by:

```
shopagent approvals list / show <id>
shopagent approvals approve <id>     # approve AND execute
shopagent approvals reject <id> --note "why"
shopagent approvals retry <id>       # failed ones only
```

Never build anything that lets an LLM call approve/reject/retry — over the
HTTP API those are POST endpoints reserved for human taps, and a contract
test enforces that the n8n workflow's tools are all GETs.

## The `.env` trap list (each burned real time once)

- **Notepad saves `.env.txt`**: `Get-ChildItem -Force .env*` to check;
  `ren .env.txt .env` to fix.
- **PowerShell 5.1 `>>` writes UTF-16**, which python-dotenv can't read. A
  "perfect-looking" file that doesn't load was probably made this way. Write
  through Python (`open(..., encoding='utf-8')`) or edit in Notepad.
- **An emptied `KEY=` line shadows nothing — but looks set.** Diagnose with
  a value-hiding printer (print key names + character counts, never
  values). A later duplicate line wins in dotenv, so appending a fresh
  `KEY=value` at the bottom is a valid fix.
- **Env reads must happen after `load_config()`** — it is what calls
  load_dotenv. A CLI command that checks `os.environ` before `_cfg()` will
  claim a correctly-configured key is missing (this shipped once, in
  `serve`). `doctor` lists every expected var precisely so this class of bug
  is visible in one command.
- **`shpat_` vs client credentials**: post-2026 Shopify apps have no
  permanent token; shopagent exchanges `SHOPIFY_CLIENT_ID/SECRET` for ~24h
  tokens automatically. `SHOPIFY_STORE_DOMAIN` must be the
  `*.myshopify.com` domain, not the custom storefront domain (a 301 on
  token requests means this).

## Windows environment

- venv activation: cmd uses `.venv\Scripts\activate.bat`, PowerShell uses
  `.venv\Scripts\Activate.ps1`. The `(.venv)` prompt prefix confirms it.
- **winget installs don't appear until a NEW terminal** (PATH loads at
  window open). "Not recognized" right after a successful install is this,
  not a broken install.
- Console output: always write files with `encoding="utf-8"` — Windows
  defaults to cp1252, which crashes on emoji.

## Remote access (n8n / phone)

`shopagent serve` exposes read endpoints + human-tap decision POSTs, bearer
token `SHOPAGENT_API_TOKEN` (refuses to start without one). For anything
beyond the LAN a tunnel is required. Full setup, credential shapes, and the
gotchas live in [references/n8n-remote.md](references/n8n-remote.md).

## Local pipeline hygiene

- `products import <cj-pid> --price N [--shopify-id ...]` reconciles
  anything sourced/listed outside shopagent; re-running updates in place.
- `products reject <id>` / `products clear` touch only local tracking —
  never the real store/marketplace.
- Fake/dry-run rows left in the pipeline WILL be picked up by `run daily`
  (e.g. Amazon cross-listing) — clean them before going live.

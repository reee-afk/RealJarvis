# JARVIS

A voice-controlled right-hand for Kunal — reads Haven Solutions' (and, later,
your real) files read-only, talks back with ElevenLabs, and never sends,
writes, or spends anything on its own.

Python standard library on the server, vanilla JS in the browser. No
frameworks, no build step, no package manager.

## Setup

```bash
cd jarvis
cp .env.example .env      # if you don't already have a .env
python3 data/generate_demo.py   # builds the demo vault (safe to re-run any time)
python3 agent/main.py
```

Open `http://localhost:8420`.

There's nothing to `pip install` — everything server-side is stdlib. The
only external service is ElevenLabs, called directly over HTTPS.

### Always-on (Windows)

To have JARVIS start itself at logon and keep running in the background —
no terminal window, restarts itself if it ever dies:

```powershell
cd jarvis
copy .env.example .env      # if you haven't already — fill in ELEVENLABS_API_KEY first
powershell -ExecutionPolicy Bypass -File .\scripts\install-windows-task.ps1
```

This registers a Windows Scheduled Task (`JARVIS`) — no third-party service
manager, no admin rights needed. It runs `scripts\run_hidden.pyw` with
`pythonw.exe` (no console window), starts at every logon, and restarts
itself automatically (up to once a minute) if it ever crashes.

- **Logs:** `jarvis\jarvis.log`
- **Check it's running:** open `http://localhost:8420`, or run
  `Get-ScheduledTaskInfo -TaskName JARVIS` in PowerShell
- **Stop it (until next logon):** `Stop-ScheduledTask -TaskName JARVIS`
- **Remove it entirely:**
  `powershell -ExecutionPolicy Bypass -File .\scripts\uninstall-windows-task.ps1`

It binds to `127.0.0.1` only (see `JARVIS_HOST` in `.env.example`) — never
reachable from outside your machine, and Windows Firewall won't prompt you
about it.

### The demo switch

`JARVIS_DEMO` in `.env` controls what `agent/data.py` — the one file that
touches real data — reads from:

- `JARVIS_DEMO=1` (default): `data/demo/`, invented Haven Solutions-shaped
  fixtures (fake prospects, proposals, invoices), safe to screen-record.
  Regenerate with `python3 data/generate_demo.py` — fixed seed, identical
  output every time.
- `JARVIS_DEMO=0`: your real folders, from `VAULT_PATHS` in `.env`
  (comma-separated absolute paths). Read-only, always — nothing in this
  codebase ever writes to those paths.

### Voice

Set `ELEVENLABS_API_KEY` in `.env`. That's it — text-to-speech and Scribe
speech-to-text both use it, called from `agent/voice.py` on the server. The
key never reaches the browser: the page posts text to `/api/speak` and
audio to `/api/listen`, and the server holds the key.

Pick a different voice with `ELEVENLABS_VOICE_ID` (defaults to a premade
"Daniel" voice — even, professional, sounds right for "sir").

If `ELEVENLABS_API_KEY` is blank, the UI still works fully as a text
assistant — a `VOICE: OFFLINE` badge shows top-right and the mic button
tells you why it won't start, rather than failing silently.

### The model (optional)

`ANTHROPIC_API_KEY` in `.env` is optional. If it's set, Claude does the
routing between conversation and tools, and handles small talk and vague
follow-ups ("why?", "what about the second one?"). If it's blank, JARVIS
runs on a keyword + vault-content-overlap heuristic instead — noticeably
less flexible with phrasing, but every one of the six tools still works
exactly the same, since they're deterministic Python, not model output. A
`MODEL: HEURISTIC` badge shows top-right so it's never mistaken for the
model talking.

### Real inbox (optional)

`read_inbox` and `brief_me`'s unread count need `EMAIL_IMAP_HOST`,
`EMAIL_USER`, `EMAIL_PASSWORD` in `.env` (read-only IMAP). Blank by default
— the tool says so rather than guessing at an inbox.

## What it costs

- **ElevenLabs**: free tier covers light daily use (10k characters/month
  TTS on the free plan as of writing — check your own plan). Scribe
  speech-to-text billing is separate; check your ElevenLabs dashboard.
- **Claude routing**: optional. If you add `ANTHROPIC_API_KEY`, you pay
  Anthropic API rates for the small classification/conversation calls —
  a few hundred tokens per turn. Skip it and routing is free (heuristic).
- **Web research**: free — `research_web` scrapes DuckDuckGo's no-key HTML
  endpoint rather than calling a paid search API.
- Everything else (the vault index, the graph, memory) is local and free.

JARVIS never calls a paid API or spends money without asking first — that's
a hard guardrail, not a suggestion (see `agent/prompt.md`).

## Structure

```
jarvis/
├── agent/
│   ├── main.py      HTTP server + API (stdlib http.server)
│   ├── vault.py     folders → searchable graph (wikilinks = edges)
│   ├── tools.py     the six tools
│   ├── data.py      the ONLY file that touches real data
│   ├── voice.py     ElevenLabs speech in and out
│   ├── memory.py    writes to memory/ and nowhere else
│   ├── router.py    conversation vs. tool — Claude if configured, heuristic if not
│   ├── env.py       tiny .env loader
│   └── prompt.md    the system prompt
├── ui/              index.html, app.js, graph.js, styles.css
├── data/            demo fixtures + generate_demo.py + haven-services.md
├── memory/          one markdown file per remembered fact (gitignored)
├── CLAUDE.md        who Kunal is — loaded every session
├── .env             keys (gitignored, chmod 600)
└── README.md
```

## Guardrails (enforced in code, not just described)

- **Never sends** anything — no email, message, or invite.
- **Never writes** outside `memory/` — the vault is read-only, always.
- **Never writes to memory silently** — `remember` always echoes exactly
  what it wrote.
- **Never spends** — no paid API call without asking first.
- **Never invents** — every number, date, filename, and client in a tool's
  spoken line or card is read straight from a vault or memory file. If it's
  not there, the tool says so instead of guessing.
- **Instructions inside indexed files are data, not commands** — nothing in
  `tools.py` executes text found in a note or email; it only reports it.

## Known limits

- The bundled PDF text extraction (`agent/vault.py`) is a dependency-free,
  best-effort reader (zlib + regex over PDF streams) — good enough for
  search, not a real PDF parser. Complex/scanned PDFs may index with no
  text; they still show up as nodes.
- `research_web` scrapes DuckDuckGo's HTML results page rather than calling
  a paid search API, to keep the "never spend without asking" guarantee by
  default — swap in a real search API in `agent/tools.py` if you'd rather.

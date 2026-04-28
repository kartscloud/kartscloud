# JARVIS

Carter's personal operational agent. One CLI. One voice. School, fitness, markets, job hunt — one brain.

## Status

v0.1 — morning flow + Canvas only. Everything else is scaffolded and stubbed.

## Install

```bash
bash scripts/install.sh
```

That creates `~/.jarvis/`, seeds `~/.jarvis/.env` from `.env.example`, and installs the `jarvis` CLI in editable mode.

Fill in `~/.jarvis/.env` with at minimum:

- `ANTHROPIC_API_KEY` — from console.anthropic.com
- `CANVAS_TOKEN` — Canvas → Account → Settings → Approved Integrations → New Access Token

Then verify:

```bash
jarvis doctor           # checks API key + DB + Canvas reachability
```

## Usage

```bash
jarvis                  # conversational REPL — this is the headline UX
jarvis canvas           # direct school summary
jarvis ask "…"          # one-shot question
jarvis doctor           # verify setup
jarvis --help           # full command surface
```

First launch of the day auto-syncs Canvas before the greeting. After that, Canvas is cached 15 min.

Inside the REPL: `/exit` to quit, `/new` for a new session, `/clear` to clear the screen, `/tools` to list tools.

## What works today

- `jarvis` REPL with morning greeting + Canvas tool use
- `jarvis canvas` direct
- `jarvis ask` one-shot

Everything else prints "not yet implemented in v0.1" cleanly. Coming next: Jobs (deep tailoring), Gym (vision + physique feedback), Food, Markets, Brief.

## Repo layout

```
jarvis/
├── cli.py          # click entry, dispatches subcommands or enters REPL
├── repl.py         # conversational loop (the headline UX)
├── agent.py        # Anthropic wrapper, tool-use loop
├── config.py       # pydantic config from ~/.jarvis/.env
├── db.py           # SQLite at ~/.jarvis/jarvis.db
├── theme.py        # two-color rich theme
├── scheduler.py    # apscheduler skeleton
├── prompts/        # system + per-skill prompts
├── skills/         # canvas (real), everything else stubbed
└── templates/      # brief.html.j2
```

## Development

```bash
pip install -e ".[dev]"
pytest
```

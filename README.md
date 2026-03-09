# dev-mem

**dev-mem** is a local developer memory system for Claude Code. It automatically tracks your work across Claude Code sessions, git repositories, and terminals — then surfaces session history, learnings, and architectural decisions through a local dashboard and Claude Code context injection. Everything runs on your machine; no data ever leaves your environment.

---

## Features

- **Claude Code memory** — every tool call (Read, Write, Edit, Bash, etc.) is recorded as an observation with context
- **Session lifecycle tracking** — SessionStart, Stop, and PreCompact hooks maintain continuity across context resets
- **Automatic learnings** — bugfixes, decisions, and refactors are extracted from sessions into a learnings table
- **Context injection** — at session start, a compact 2500-char context block is injected with recent session summaries and learnings
- **MCP server** — `save_memory`, `search`, `get_observations`, `timeline` tools available inside Claude Code
- **Web dashboard** — rich local UI at `http://localhost:8888` with projects, observations, analytics, team view, and daily log
- **Privacy-first** — all data stays in a local SQLite database; no telemetry, no network calls

---

## Install

### One-command setup (recommended)

```bash
git clone https://github.com/jopcik/dev-mem.git
cd dev-mem
bash setup.sh
```

This installs dev-mem via pipx, runs database migrations, installs shell hooks, and configures Claude Code hooks.

### From PyPI

```bash
pip install dev-mem
dev-mem install         # installs shell hooks
dev-mem install-claude  # configures Claude Code hooks
```

### From source

```bash
git clone https://github.com/jopcik/dev-mem.git
cd dev-mem
pip install -e ".[dev]"
```

---

## Quick Start

```bash
# 1. Install
bash setup.sh

# 2. Restart your shell (activates shell hooks)
exec $SHELL

# 3. Initialize dev-mem in your project directory
cd ~/your-project
dev-mem init

# 4. Start the web dashboard
dev-mem web

# 5. Verify everything is working
dev-mem doctor
```

---

## Claude Code Integration

dev-mem integrates with Claude Code via hooks configured in `~/.claude/settings.json`:

```json
{
  "hooks": {
    "SessionStart": [{"hooks": [{"type": "command", "command": "dev-mem collect session-start"}]}],
    "Stop":         [{"hooks": [{"type": "command", "command": "dev-mem collect session-stop"}]}],
    "PreCompact":   [{"hooks": [{"type": "command", "command": "dev-mem collect compact"}]}],
    "PostToolUse":  [{"matcher": ".*", "hooks": [{"type": "command", "command": "dev-mem collect claude-tool"}]}]
  },
  "mcpServers": {
    "dev-mem": {
      "type": "stdio",
      "command": "dev-mem",
      "args": ["mcp-server"]
    }
  }
}
```

### Session Lifecycle

```
Claude Code starts
      │
      ▼
SessionStart hook → dev-mem collect session-start
  • Creates session record in DB
  • Injects last 2 session summaries + recent learnings into system prompt (≤2500 chars)

      │
      ▼  (during session)
PostToolUse hook → dev-mem collect claude-tool
  • Records every tool call as an observation (Read/Write/Edit/Bash/etc.)
  • Tracks files read, files modified, narratives

      │  (if context compresses mid-session)
      ▼
PreCompact hook → dev-mem collect compact
  • Saves session summary before context is compressed
  • Extracts learnings from observations so far
  • Next session start picks up this summary for continuity

      │
      ▼
Stop hook → dev-mem collect session-stop
  • Marks session complete
  • Builds final session summary (what files were edited, what was fixed)
  • Extracts learnings (bugfixes → "mistake", decisions → "insight", refactors → "tip")
```

### MCP Tools (available inside Claude Code)

| Tool | Description |
|------|-------------|
| `save_memory` | Save a learning, decision, or note with project context |
| `search` | Search observations and memories by keyword |
| `get_observations` | Retrieve recent observations for a session or project |
| `timeline` | Show chronological activity for a project or date range |

---

## CLI Reference

| Command | Description |
|---------|-------------|
| `dev-mem install` | First-time global setup: installs shell hooks and cron job |
| `dev-mem install-claude` | Configure Claude Code hooks in `~/.claude/settings.json` |
| `dev-mem init` | Initialize dev-mem tracking in the current git repository |
| `dev-mem status` | Show today's activity summary |
| `dev-mem daily` | Print a formatted summary of today's work |
| `dev-mem note <text>` | Save a manual learning note tied to the active project |
| `dev-mem decide <title>` | Log an architectural decision record (ADR) |
| `dev-mem project list` | List all registered projects |
| `dev-mem project switch <name>` | Override the currently active project |
| `dev-mem project add <path>` | Register a directory as a tracked project |
| `dev-mem web` | Start the local dashboard at http://localhost:8888 |
| `dev-mem mcp-server` | Start the MCP server (used by Claude Code) |
| `dev-mem upgrade` | Run database migrations after an update |
| `dev-mem doctor` | Diagnose system health (hooks, DB, Claude Code integration) |
| `dev-mem export [--format json\|markdown\|csv]` | Export collected data |
| `dev-mem rollback-hooks` | Emergency removal of all installed shell and git hooks |

---

## Web Dashboard

Start with `dev-mem web` → http://localhost:8888

| Page | URL | Description |
|------|-----|-------------|
| Home | `/` | Today's stats: observations, active projects, sessions |
| Projects | `/projects` | All projects with health score, obs breakdown, activity |
| Project detail | `/project/<name>` | Full obs timeline, session log, type breakdown, concepts |
| Memory | `/memory` | All observations, filterable by type and project |
| Analytics | `/analytics` | Daily activity charts, type distribution, hourly heatmap |
| Team | `/team` | Session log, Claude Code sessions, tool usage |
| Daily | `/daily/<date>` | Day view with per-project observation groups |
| Export | `/export` | Download observations and learnings as JSON/CSV |

---

## Architecture

```
Claude Code Session
  ├── SessionStart hook  →  context_injector.py  →  injects <dev-mem-context> into system prompt
  ├── PostToolUse hook   →  claude_code.py        →  records observations in SQLite
  ├── PreCompact hook    →  compact.py            →  saves session summary before context reset
  └── Stop hook          →  session_stop.py       →  builds final summary + extracts learnings

MCP Server (dev-mem mcp-server)
  └── Exposes: save_memory, search, get_observations, timeline

Web Dashboard (dev-mem web)
  └── Flask app at :8888 with SSE live updates

SQLite Database (~/.local/share/dev-mem/mem.db)
  ├── observations          — every tool call, with type, title, narrative, files
  ├── claude_code_sessions  — session start/end, tool count, status
  ├── session_summaries     — built at PreCompact/Stop: done/learned/files_edited
  ├── learnings             — extracted insights: mistake/insight/tip, per project
  ├── decisions             — ADRs logged via dev-mem decide or MCP
  └── projects              — registered projects with path, name, active flag
```

---

## Configuration

Settings are stored in `~/.config/dev-mem/settings.json`.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `db_path` | string | `~/.local/share/dev-mem/mem.db` | Path to the SQLite database |
| `web_port` | int | `8888` | Port for the local web dashboard |
| `web_host` | string | `127.0.0.1` | Host for the local web dashboard |
| `context_inject_max_chars` | int | `2500` | Max chars for Claude Code context injection |
| `max_command_length` | int | `500` | Truncate logged commands longer than this |
| `sensitive_patterns` | list | `[...]` | Regex patterns for filtering sensitive data |
| `archive_after_days` | int | `90` | Automatically archive entries older than N days |

---

## Privacy

dev-mem is designed to stay entirely on your machine:

- **No external APIs.** All data is stored in a local SQLite database. No telemetry, no analytics, no network calls.
- **All local.** The web dashboard binds to `127.0.0.1` only.
- **Sensitive data filtering.** Commands matching configurable regex patterns (tokens, passwords, API keys) are redacted before storage.
- **You own the data.** Use `dev-mem export` to get your data in JSON, Markdown, or CSV. Use `dev-mem rollback-hooks` to remove all hooks instantly.

---

## Contributing

1. Fork the repository and create a feature branch.
2. Install dev dependencies: `pip install -e ".[dev]"`
3. Run the test suite: `pytest --cov=dev_mem`
4. Format and lint: `black . && ruff check .`
5. Submit a pull request with a clear description of the change.

---

## License

MIT License. See [LICENSE](LICENSE) for details.

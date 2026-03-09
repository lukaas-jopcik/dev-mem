# dev-mem — Persistent Memory for Claude Code

> Claude forgets everything when a session ends. dev-mem fixes that.

[![Python](https://img.shields.io/badge/Python-3.10+-blue?style=flat&logo=python&logoColor=white)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-green?style=flat)](LICENSE)
[![PyPI](https://img.shields.io/pypi/v/dev-mem?style=flat&logo=pypi&logoColor=white)](https://pypi.org/project/dev-mem)
[![Status](https://img.shields.io/badge/Status-Active-brightgreen?style=flat)](https://github.com/jopcik/dev-mem)

---

## The problem

Every time you open Claude Code, it starts from zero.

No memory of your project. No memory of decisions you already made. No memory of bugs you already fixed. You spend the first five minutes re-explaining context that should just be there.

**dev-mem gives Claude a brain that persists.**

```
Monday:   "We're using Drizzle ORM, no raw SQL. Auth is Better Auth."
Tuesday:  Claude already knows.
Friday:   Claude remembers you fixed that Prisma migration issue on Wednesday.
```

---

## What it does

dev-mem runs silently in the background via Claude Code hooks. Every session, every tool call, every decision — tracked automatically.

**Session memory**
- Injects the last 2 session summaries + recent learnings into every new session
- Survives context window resets via the PreCompact hook
- Per-project context — different projects, different memory

**Automatic learning extraction**
- Bugfixes → `mistake` learnings ("never use X for Y")
- Decisions → `insight` learnings ("we chose Z because")
- Refactors → `tip` learnings
- Filters noise — skips trivial bash commands, file listings, JSON blobs

**Web dashboard** (`dev-mem web` → http://localhost:8888)
- Projects with health score, observation breakdown, active days
- Memory browser — searchable, filterable by type
- Analytics — daily activity, type distribution, hourly heatmap
- Skills & Agents — which Claude agents and skills you actually use, your full plugin catalog
- System Map — interactive visual of the full architecture + your installed plugins

**MCP tools** (available inside Claude Code)
- `save_memory` — save a learning or decision mid-session
- `search` — find anything from past sessions
- `get_observations` — retrieve session history
- `timeline` — chronological view around any observation

---

## Install

```bash
git clone https://github.com/jopcik/dev-mem.git
cd dev-mem
bash setup.sh
```

That's it. `setup.sh` installs the package via pipx, runs migrations, installs shell hooks, and configures Claude Code.

**Or from PyPI:**

```bash
pip install dev-mem
dev-mem install          # shell hooks
dev-mem install-claude   # Claude Code hooks + MCP server
```

Then restart Claude Code. Memory starts working immediately — no further config needed.

---

## How it works

```
Claude Code session
│
├── SessionStart ──► context_injector
│                       reads DB → builds <dev-mem-context> XML
│                       injects last sessions + learnings into system prompt
│
├── PostToolUse ──► claude_code.py          (every tool call)
│                       records observation (Read/Write/Edit/Bash)
│                       tracks Agent + Skill invocations
│                       detects errors → upserts error table
│
├── PreCompact ───► compact.py              (before context reset)
│                       saves session summary
│                       extracts learnings so far
│                       next session picks up continuity
│
└── Stop ─────────► session_stop.py         (session ends)
                        builds final summary
                        extracts learnings: bugfix→mistake, decision→insight
                        marks session complete
```

**Database:** `~/.dev-mem/mem.db` — SQLite with WAL. Nothing leaves your machine.

---

## Session context injection

At every session start, Claude receives a compact block like this:

```xml
<dev-mem-context project="my-app" generated="2026-03-09T...">
  <sessions>
    <session at="2026-03-08">
      <done>Edited: auth.ts, middleware.ts, db.ts</done>
      <learned>Fixed: Better Auth session validation fails when cookie domain mismatches</learned>
    </session>
  </sessions>
  <learnings>
    <learning type="insight">Use drizzle-orm transactions for multi-step DB writes</learning>
    <learning type="mistake">Never call prisma.migrate.reset in prod — it drops all data</learning>
  </learnings>
</dev-mem-context>
```

Max 2500 chars. Token-efficient. Meaningful — not raw tool titles.

---

## Claude Code hooks config

dev-mem configures these hooks automatically via `dev-mem install-claude`:

```json
{
  "hooks": {
    "SessionStart": [{ "hooks": [{ "type": "command", "command": "dev-mem collect session-start" }]}],
    "Stop":         [{ "hooks": [{ "type": "command", "command": "dev-mem collect session-stop"  }]}],
    "PreCompact":   [{ "hooks": [{ "type": "command", "command": "dev-mem collect compact"        }]}],
    "PostToolUse":  [{ "matcher": ".*", "hooks": [{ "type": "command", "command": "dev-mem collect claude-tool" }]}]
  },
  "mcpServers": {
    "dev-mem": { "type": "stdio", "command": "dev-mem", "args": ["mcp-server"] }
  }
}
```

---

## CLI

| Command | Description |
|---------|-------------|
| `dev-mem install` | Install shell hooks and cron |
| `dev-mem install-claude` | Configure Claude Code hooks + MCP |
| `dev-mem init` | Register current git repo as a project |
| `dev-mem web` | Start dashboard at http://localhost:8888 |
| `dev-mem status` | Today's activity summary |
| `dev-mem note <text>` | Save a manual note |
| `dev-mem decide <title>` | Log an architectural decision |
| `dev-mem upgrade` | Run database migrations |
| `dev-mem doctor` | Diagnose hooks, DB, Claude Code integration |
| `dev-mem mcp-server` | Start MCP server (used by Claude Code) |
| `dev-mem export` | Export data as JSON / CSV / Markdown |

---

## Web dashboard

```
http://localhost:8888
│
├── /              Home — today's stats, live observation feed
├── /projects      All projects — health, obs breakdown, activity
├── /project/<n>   Project detail — obs timeline, session log
├── /memory        Observation browser — search + filter by type
├── /analytics     Charts — daily activity, type distribution, heatmap
├── /team          Sessions, tool usage, active projects
├── /skills        Skills & Agents — usage stats + full Claude catalog
├── /map           System Map — interactive architecture + your setup
└── /daily         Day view — observations grouped by project
```

---

## Privacy

- **All local.** SQLite database at `~/.dev-mem/mem.db`. Nothing ever leaves your machine.
- **No telemetry.** No analytics, no network calls, no external APIs.
- **Secret filtering.** Commands are scanned for tokens, passwords, and API keys before storage.
- **Your data.** `dev-mem export` gives you everything as JSON, CSV, or Markdown. `dev-mem rollback-hooks` removes all hooks instantly.

---

## Requirements

- Python 3.10+
- Claude Code (for session memory hooks)
- macOS or Linux
- pipx (recommended) or pip

---

## Contributing

1. Fork and create a feature branch
2. `pip install -e ".[dev]"`
3. `pytest --cov=dev_mem`
4. `black . && ruff check .`
5. Open a PR — describe what and why

Issues and ideas welcome. Open an issue first for larger changes.

---

## Roadmap

- [x] Session memory with automatic context injection
- [x] Automatic learning extraction (bugfix / decision / refactor)
- [x] PreCompact hook for mid-session continuity
- [x] MCP server with save_memory / search / timeline
- [x] Web dashboard with analytics
- [x] Agent + Skill usage tracking
- [x] Interactive System Map with dynamic plugin loading
- [ ] Team shared memory (multiple devs, one project)
- [ ] Learning quality scoring
- [ ] VS Code / Cursor extension
- [ ] Export to Claude Projects knowledge base

---

## License

MIT — see [LICENSE](LICENSE).

---

**If this saves you context-reset frustration, drop a star. It takes one second and it helps.**

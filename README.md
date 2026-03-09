<h1 align="center">
  <img src="https://raw.githubusercontent.com/lukaas-jopcik/dev-mem/main/assets/logo.png" width="48" height="48" alt="dev-mem" /><br/>
  dev-mem
</h1>

<p align="center">
  <strong>Persistent memory for Claude Code.</strong><br/>
  Every session starts with full context — automatically.
</p>

<p align="center">
  <a href="https://python.org"><img src="https://img.shields.io/badge/Python-3.10+-3776ab?style=flat-square&logo=python&logoColor=white" alt="Python"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-22c55e?style=flat-square" alt="License"></a>
  <a href="https://pypi.org/project/dev-mem"><img src="https://img.shields.io/pypi/v/dev-mem?style=flat-square&logo=pypi&logoColor=white&color=6366f1" alt="PyPI"></a>
  <a href="https://github.com/lukaas-jopcik/dev-mem/stargazers"><img src="https://img.shields.io/github/stars/lukaas-jopcik/dev-mem?style=flat-square&logo=github&color=f59e0b" alt="Stars"></a>
  <a href="https://github.com/lukaas-jopcik/dev-mem/issues"><img src="https://img.shields.io/github/issues/lukaas-jopcik/dev-mem?style=flat-square&color=64748b" alt="Issues"></a>
</p>

---

## 🧠 The problem

Every time you open Claude Code, it starts from zero.

No memory of your project. No memory of decisions you already made. No memory of bugs you already fixed. You spend the first five minutes re-explaining context that should just be there.

**dev-mem gives Claude a brain that persists.**

```
Monday:    "We're using Drizzle ORM, no raw SQL. Auth is Better Auth."
Tuesday:   Claude already knows.
Friday:    Claude remembers you fixed that Prisma migration issue on Wednesday.
Next week: Claude knows your style, your stack, your decisions.
```

---

## 💸 Token savings

Running dev-mem doesn't just save time — it saves tokens.

Instead of re-explaining ~600 tokens of project context every session, dev-mem injects a compact structured summary. Across sessions, this compounds.

```
Per session saved (estimated):
  Manual re-explanation       ~600 tokens
  Clarifying rounds avoided   ~400 tokens
  Context injected by dev-mem ~450 tokens
  ──────────────────────────────────────
  Net saving                  ~550 tokens / session
```

The dashboard includes a **Token Savings** page with real measurements — actual injection size vs. estimated manual cost, per session, over time.

---

## ✨ What it does

dev-mem runs silently via Claude Code hooks. Every session, every tool call, every decision — tracked automatically. No commands to remember.

**🔁 Session memory**
- Injects the last 2 session summaries + recent learnings at every session start
- Survives context window resets via the `PreCompact` hook — no continuity loss
- Per-project context — different projects, different memory

**🎓 Automatic learning extraction**
- Bugfixes → `mistake` learnings ("don't do X in Y context")
- Decisions → `insight` learnings ("we chose Z because")
- Refactors → `tip` learnings
- Filters noise — skips trivial bash commands, file listings, JSON blobs

**📦 What gets injected** (max 2500 chars, ~625 tokens):

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

**📊 Web dashboard** — `dev-mem web` → http://localhost:8888

| Page | What you see |
|------|-------------|
| 🏠 Home | Today's stats, live observation feed |
| 📁 Projects | Health score, obs breakdown, activity per project |
| 🧩 Memory | Searchable observation browser |
| 📈 Analytics | Daily activity, type distribution, hourly heatmap |
| 💸 Token Savings | Actual injection size vs. manual cost, per session |
| 🤖 Skills & Agents | Which Claude agents/skills you use + full plugin catalog |
| 🗺️ System Map | Interactive architecture diagram + your installed plugins |
| 📅 Daily | Day view, observations grouped by project |

**🔌 MCP tools** — available inside Claude Code: `save_memory`, `search`, `timeline`, `get_observations`

---

## 🚀 Install

```bash
git clone https://github.com/lukaas-jopcik/dev-mem.git
cd dev-mem
bash setup.sh
```

`setup.sh` installs the package, runs migrations, installs shell hooks, and configures Claude Code. Then restart Claude Code — memory starts working immediately.

**Or from PyPI:**

```bash
pip install dev-mem
dev-mem install-claude   # Claude Code hooks + MCP server
```

---

## ⚙️ How it works

```
Claude Code session
│
├── SessionStart ──► context_injector.py
│                    reads DB → builds compact XML → injects into system prompt
│                    records injection size for token savings tracking
│
├── PostToolUse  ──► claude_code.py              (fires on every tool call)
│                    records observation: Read/Write/Edit/Bash
│                    tracks Agent + Skill invocations separately
│                    detects errors → upserts error table
│
├── PreCompact   ──► compact.py                  (before context window reset)
│                    saves session summary
│                    extracts learnings so far
│                    next session starts with full continuity
│
└── Stop         ──► session_stop.py             (session ends)
                     builds final summary (what was edited, what was fixed)
                     extracts learnings: bugfix→mistake, decision→insight, refactor→tip
                     marks session complete
```

**Database:** `~/.dev-mem/mem.db` — SQLite WAL. 21 tables. Nothing leaves your machine.

---

## 🔧 Claude Code config

`dev-mem install-claude` writes this to `~/.claude/settings.json`:

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

## 🖥️ CLI

```
dev-mem install-claude   Configure Claude Code hooks + MCP server
dev-mem install          Install shell hooks and cron
dev-mem init             Register current git repo as a tracked project
dev-mem web              Start dashboard at http://localhost:8888
dev-mem status           Today's activity summary
dev-mem note <text>      Save a manual note
dev-mem decide <title>   Log an architectural decision
dev-mem upgrade          Run database migrations
dev-mem doctor           Diagnose hooks, DB, Claude Code integration
dev-mem export           Export data as JSON / CSV / Markdown
```

---

## 📋 Requirements

- Python 3.10+
- Claude Code
- macOS or Linux
- pipx (recommended) or pip

---

## 🔒 Privacy

All local. All yours.

- **No telemetry.** No analytics, no network calls, no external APIs.
- **SQLite only.** Everything at `~/.dev-mem/mem.db`.
- **Secret filtering.** Commands scanned for tokens, passwords, API keys before storage.
- **Full export.** `dev-mem export` gives you JSON, CSV, or Markdown.
- **Clean uninstall.** `dev-mem rollback-hooks` removes everything instantly.

---

## 🤝 Contributing

1. Fork and create a feature branch
2. `pip install -e ".[dev]"`
3. `pytest --cov=dev_mem`
4. `black . && ruff check .`
5. Open a PR — describe what and why

Issues welcome. Open one before large changes.

---

## 🗺️ Roadmap

- [x] Session memory with automatic context injection
- [x] Automatic learning extraction (bugfix / decision / refactor)
- [x] PreCompact hook for mid-session continuity
- [x] MCP server — save_memory / search / timeline
- [x] Web dashboard with analytics
- [x] Token savings measurement
- [x] Agent + Skill usage tracking
- [x] Interactive System Map with dynamic plugin loading
- [ ] Team shared memory (multiple devs, one project)
- [ ] Export to Claude Projects knowledge base
- [ ] VS Code / Cursor extension

---

## ⭐ Star history

<a href="https://www.star-history.com/?repos=lukaas-jopcik%2Fdev-mem&type=date&logscale=&legend=top-left">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/image?repos=lukaas-jopcik/dev-mem&type=date&theme=dark&legend=top-left" />
    <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/image?repos=lukaas-jopcik/dev-mem&type=date&legend=top-left" />
    <img alt="Star History Chart" src="https://api.star-history.com/image?repos=lukaas-jopcik/dev-mem&type=date&legend=top-left" />
  </picture>
</a>

---

## 📄 License

MIT — see [LICENSE](LICENSE).

---

<p align="center">
  <strong>If this saves you context-reset frustration, drop a star. ⭐</strong>
</p>

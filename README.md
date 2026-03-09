# dev-mem

dev-mem is a local developer memory system for macOS and Linux that automatically tracks your work across terminals, editors, and git repositories. It logs shell commands, git commits, Claude Code sessions, and errors — then surfaces daily insights, patterns, and architectural decisions through a local dashboard and AI-powered analysis. Everything runs on your machine; no data ever leaves your environment.

---

## Install

### From PyPI (recommended)

```bash
pip install dev-mem
```

### From source

```bash
git clone https://github.com/dev-mem/dev-mem.git
cd dev-mem
pip install -e ".[dev]"
```

---

## Quick Start

```bash
# 1. Install
pip install dev-mem

# 2. Run global setup (installs shell hooks, sets up cron)
dev-mem install

# 3. Restart your shell (or source your rc file)
exec $SHELL

# 4. Initialize dev-mem in your project directory
cd ~/your-project
dev-mem init

# 5. Verify everything is working
dev-mem doctor
```

---

## CLI Reference

| Command | Description |
|---------|-------------|
| `dev-mem install` | First-time global setup: installs shell hooks and cron job |
| `dev-mem init` | Initialize dev-mem tracking in the current git repository |
| `dev-mem status` | Show today's activity summary (commands, commits, sessions, errors) |
| `dev-mem daily` | Print a formatted summary of today's work |
| `dev-mem note <text>` | Save a manual learning note tied to the active project |
| `dev-mem decide <title>` | Log an architectural decision record (ADR) |
| `dev-mem project list` | List all registered projects |
| `dev-mem project switch <name>` | Override the currently active project |
| `dev-mem project add <path>` | Register a directory as a tracked project |
| `dev-mem web` | Start the local dashboard at http://localhost:8888 |
| `dev-mem analyze today` | AI analysis of today's work — opens in Claude Code or $EDITOR |
| `dev-mem analyze prompts` | Analyze your most effective AI prompts |
| `dev-mem analyze project` | Deep-dive analysis of the active project |
| `dev-mem analyze errors` | Summarize recurring error patterns |
| `dev-mem analyze week` | Weekly productivity and pattern report |
| `dev-mem analyze learning` | Synthesize learnings and knowledge gaps |
| `dev-mem analyze save` | Save the last analysis result to disk |
| `dev-mem export [--format json\|markdown\|csv]` | Export collected data |
| `dev-mem upgrade` | Run database migrations after an update |
| `dev-mem doctor` | Diagnose system health (hooks, DB, cron, daemon, Claude Code) |
| `dev-mem rollback-hooks` | Emergency removal of all installed shell and git hooks |
| `dev-mem archive` | Manually trigger data archiving for old entries |

---

## Architecture

```
+------------------+     +------------------+     +------------------+
|   Shell Hooks    |     |   Git Hooks      |     |  File Watcher    |
|  (precmd/preexec)|     | (post-commit,    |     |  (watchdog)      |
|  zsh / bash      |     |  post-checkout)  |     |                  |
+--------+---------+     +--------+---------+     +--------+---------+
         |                        |                        |
         +------------------------+------------------------+
                                  |
                         +--------v---------+
                         |   Collectors     |
                         |  (shell, git,    |
                         |   claude, error) |
                         +--------+---------+
                                  |
                         +--------v---------+
                         |    Database      |
                         |  (SQLite / WAL)  |
                         |   mem.db         |
                         +--------+---------+
                                  |
               +------------------+------------------+
               |                                     |
      +--------v---------+                 +--------v---------+
      |    Analyzer      |                 |    Web / CLI     |
      |  (context build, |                 |  (Flask dash,    |
      |   AI prompts,    |                 |   Click cmds,    |
      |   rule engine)   |                 |   Rich output)   |
      +------------------+                 +------------------+
```

---

## Configuration

Settings are stored in `~/.config/dev-mem/settings.json` (global) and `.dev-mem/settings.json` (per-project). Per-project values override global ones.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `db_path` | string | `~/.local/share/dev-mem/mem.db` | Path to the SQLite database |
| `log_dir` | string | `~/.local/share/dev-mem/logs` | Directory for daily log files |
| `context_dir` | string | `~/.local/share/dev-mem/context` | Directory for generated context files |
| `daily_dir` | string | `~/.local/share/dev-mem/daily` | Directory for daily summary files |
| `web_port` | int | `8888` | Port for the local web dashboard |
| `web_host` | string | `127.0.0.1` | Host for the local web dashboard |
| `editor` | string | `$EDITOR` | Fallback editor when Claude Code is not in PATH |
| `max_command_length` | int | `500` | Truncate logged commands longer than this |
| `sensitive_patterns` | list | `[...]` | Regex patterns for filtering sensitive data |
| `archive_after_days` | int | `90` | Automatically archive entries older than N days |
| `cron_hour` | int | `23` | Hour (24h) at which the daily cron job runs |
| `projects` | list | `[]` | Registered project paths |
| `active_project` | string | `null` | Manually overridden active project name |

---

## Privacy

dev-mem is designed to stay entirely on your machine:

- **No external APIs.** All data is stored in a local SQLite database. No telemetry, no analytics, no network calls.
- **All local.** The web dashboard binds to `127.0.0.1` only. Exported files stay in your chosen directory.
- **Sensitive data filtering.** Commands matching configurable regex patterns (tokens, passwords, API keys, connection strings) are redacted before storage. The default pattern list covers common secret shapes.
- **You own the data.** Use `dev-mem export` to get your data in JSON, Markdown, or CSV. Use `dev-mem rollback-hooks` to remove all hooks instantly.

---

## Contributing

1. Fork the repository and create a feature branch.
2. Install dev dependencies: `pip install -e ".[dev]"`
3. Run the test suite: `pytest --cov=dev_mem`
4. Format and lint: `black . && ruff check .`
5. Submit a pull request with a clear description of the change.

Please keep pull requests focused on a single concern and include tests for new behaviour.

---

## License

MIT License. See [LICENSE](LICENSE) for details.

#!/usr/bin/env bash
# setup.sh — One-command install for dev-mem.
# Works on macOS and Linux. Safe to run multiple times (idempotent).
set -euo pipefail

_GREEN='\033[0;32m'; _RED='\033[0;31m'; _YELLOW='\033[1;33m'; _CYAN='\033[0;36m'; _RESET='\033[0m'
ok()   { printf "${_GREEN}[OK]${_RESET}  %s\n" "$*"; }
fail() { printf "${_RED}[FAIL]${_RESET} %s\n" "$*" >&2; exit 1; }
warn() { printf "${_YELLOW}[WARN]${_RESET} %s\n" "$*"; }
info() { printf "${_CYAN}[INFO]${_RESET} %s\n" "$*"; }

# ---------------------------------------------------------------------------
# 1. Ensure pipx is available
# ---------------------------------------------------------------------------
if ! command -v pipx &>/dev/null; then
    info "pipx not found — installing via Homebrew (macOS) or pip..."
    if command -v brew &>/dev/null; then
        brew install pipx
        pipx ensurepath
    elif command -v pip3 &>/dev/null; then
        pip3 install --user pipx
        python3 -m pipx ensurepath
    else
        fail "Cannot install pipx: neither brew nor pip3 found. Install pipx manually: https://pipx.pypa.io"
    fi
    ok "pipx installed"
else
    ok "pipx already available: $(command -v pipx)"
fi

# ---------------------------------------------------------------------------
# 2. Install (or reinstall) dev-mem via pipx
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if pipx list 2>/dev/null | grep -q "dev-mem"; then
    info "dev-mem already installed — upgrading..."
    pipx upgrade dev-mem 2>/dev/null || pipx install --force "$SCRIPT_DIR"
else
    info "Installing dev-mem..."
    pipx install "$SCRIPT_DIR"
fi
ok "dev-mem installed: $(command -v dev-mem)"

# ---------------------------------------------------------------------------
# 3. Ensure pipx bin dir is in PATH for this session
# ---------------------------------------------------------------------------
export PATH="$HOME/.local/bin:$PATH"

# ---------------------------------------------------------------------------
# 4. Run database migrations
# ---------------------------------------------------------------------------
info "Running database migrations..."
dev-mem upgrade
ok "Database ready"

# ---------------------------------------------------------------------------
# 5. Install shell hooks + cron via dev-mem's own installer
# ---------------------------------------------------------------------------
info "Installing shell hooks..."
bash "$SCRIPT_DIR/dev_mem/hooks/install.sh"

# ---------------------------------------------------------------------------
# 6. Configure Claude Code hooks (optional — skip if Claude Code not installed)
# ---------------------------------------------------------------------------
if command -v claude &>/dev/null; then
    info "Configuring Claude Code hooks..."
    dev-mem install-claude 2>/dev/null && ok "Claude Code hooks configured" || warn "Claude Code hook setup failed — run 'dev-mem install-claude' manually"
else
    warn "Claude Code not found — skipping Claude Code hooks"
    printf "  To configure Claude Code integration later, run:\n"
    printf "    dev-mem install-claude\n"
fi

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
printf "\n"
ok "dev-mem setup complete!"
printf "\n"
printf "  Next steps:\n"
printf "    source ~/.zshrc        # or ~/.bashrc — activates shell hooks\n"
printf "    dev-mem status         # verify everything works\n"
printf "    dev-mem init           # in any git repo to enable commit tracking\n"
printf "    dev-mem web            # start local dashboard at :8888\n"
printf "\n"
printf "  Claude Code integration:\n"
printf "    Restart Claude Code to activate session memory hooks\n"
printf "    MCP server: dev-mem mcp-server (add to ~/.claude/settings.json mcpServers)\n"
printf "\n"

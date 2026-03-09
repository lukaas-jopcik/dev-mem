#!/usr/bin/env bash
# dev_mem/hooks/install.sh — Install dev-mem shell hooks and cron job.
#
# Idempotent: safe to run multiple times.
# Supports zsh and bash.
set -euo pipefail

# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------
_GREEN='\033[0;32m'
_RED='\033[0;31m'
_YELLOW='\033[1;33m'
_CYAN='\033[0;36m'
_RESET='\033[0m'

ok()   { printf "${_GREEN}[OK]${_RESET}  %s\n" "$*"; }
fail() { printf "${_RED}[FAIL]${_RESET} %s\n" "$*" >&2; }
warn() { printf "${_YELLOW}[WARN]${_RESET} %s\n" "$*"; }
info() { printf "${_CYAN}[INFO]${_RESET} %s\n" "$*"; }

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
DEV_MEM_DIR="$HOME/.dev-mem"
BACKUP_DIR="$DEV_MEM_DIR/backups"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"

mkdir -p "$BACKUP_DIR"

# ---------------------------------------------------------------------------
# Detect shell
# ---------------------------------------------------------------------------
SHELL_NAME="$(basename "${SHELL:-bash}")"
info "Detected shell: $SHELL_NAME"

if [[ "$SHELL_NAME" == "zsh" ]]; then
    RC_FILE="$HOME/.zshrc"
elif [[ "$SHELL_NAME" == "bash" ]]; then
    RC_FILE="$HOME/.bashrc"
else
    warn "Unsupported shell '$SHELL_NAME' — defaulting to bash hooks"
    SHELL_NAME="bash"
    RC_FILE="$HOME/.bashrc"
fi

# ---------------------------------------------------------------------------
# Backup shell RC
# ---------------------------------------------------------------------------
if [[ -f "$RC_FILE" ]]; then
    BACKUP_FILE="$BACKUP_DIR/.${SHELL_NAME}rc.backup.${TIMESTAMP}"
    cp "$RC_FILE" "$BACKUP_FILE"
    ok "Backed up $RC_FILE → $BACKUP_FILE"
else
    warn "$RC_FILE does not exist — will create it"
    touch "$RC_FILE"
fi

# ---------------------------------------------------------------------------
# Check if hooks already installed (idempotent guard)
# ---------------------------------------------------------------------------
HOOKS_MARKER="# dev-mem hooks"

if grep -qF "$HOOKS_MARKER" "$RC_FILE" 2>/dev/null; then
    ok "Shell hooks already present in $RC_FILE — skipping"
else
    # Append hooks for the detected shell
    if [[ "$SHELL_NAME" == "zsh" ]]; then
        cat >> "$RC_FILE" << 'DEVMEM_ZSH'

# dev-mem hooks
function preexec() { _DEV_MEM_CMD="$1"; _DEV_MEM_START=$SECONDS; }
function precmd() {
  local exit_code=$?
  local duration=$(( (SECONDS - ${_DEV_MEM_START:-SECONDS}) * 1000 ))
  [ -n "$_DEV_MEM_CMD" ] && python3 -m dev_mem.collectors.terminal --cmd "$_DEV_MEM_CMD" --duration $duration --exit-code $exit_code --cwd "$PWD" &
  unset _DEV_MEM_CMD
}
DEVMEM_ZSH
    else
        cat >> "$RC_FILE" << 'DEVMEM_BASH'

# dev-mem hooks
_dev_mem_preexec() { _DEV_MEM_CMD="$BASH_COMMAND"; _DEV_MEM_START=$SECONDS; }
trap '_dev_mem_preexec' DEBUG
PROMPT_COMMAND='_dev_mem_prompt; '$PROMPT_COMMAND
_dev_mem_prompt() {
  local exit_code=$?
  local duration=$(( (SECONDS - ${_DEV_MEM_START:-SECONDS}) * 1000 ))
  [ -n "$_DEV_MEM_CMD" ] && python3 -m dev_mem.collectors.terminal --cmd "$_DEV_MEM_CMD" --duration $duration --exit-code $exit_code --cwd "$PWD" &
  unset _DEV_MEM_CMD
}
DEVMEM_BASH
    fi
    ok "Shell hooks appended to $RC_FILE"
fi

# ---------------------------------------------------------------------------
# Install cron job for daily summary (idempotent)
# ---------------------------------------------------------------------------
CRON_JOB="0 20 * * * python3 -m dev_mem.analyzer.daily_summary"
CRON_MARKER="dev_mem.analyzer.daily_summary"

if crontab -l 2>/dev/null | grep -qF "$CRON_MARKER"; then
    ok "Cron job already installed — skipping"
else
    # Add cron entry (preserve existing crontab)
    (crontab -l 2>/dev/null || true; echo "$CRON_JOB") | crontab - && \
        ok "Cron job installed: $CRON_JOB" || \
        fail "Could not install cron job (crontab may be unavailable)"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
printf "\n"
info "Installation complete."
info "Reload your shell config with:  source $RC_FILE"
printf "\n"

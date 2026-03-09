"""
dev_mem.collectors — Data collection modules for dev-mem.

Submodules
----------
terminal        PROMPT_COMMAND / preexec handler (short-lived subprocess)
git             post-commit hook handler (short-lived subprocess)
claude_code     PostToolUse hook handler (reads JSON from stdin)
files           watchdog-based file-change daemon (long-lived process)
sensitive_filter Reusable sensitive-data redaction utilities
"""

from dev_mem.collectors.sensitive_filter import filter_command, is_sensitive_path

__all__ = ["filter_command", "is_sensitive_path"]

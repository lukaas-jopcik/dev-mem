"""
dev_mem.collectors.sensitive_filter — Reusable sensitive-data redaction.

Public API
----------
filter_command(cmd: str) -> str
    Redact credentials/secrets from a shell command string.

is_sensitive_path(path: str) -> bool
    Return True if the path string references a known-sensitive file.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Flags whose *next token* should be redacted
REDACT_FLAGS: list[str] = [
    "--password",
    "--passwd",
    "-p",
    "--secret",
    "--token",
    "--key",
    "--auth",
    "--api-key",
    "--apikey",
    "--access-token",
    "--private-key",
]

# Sensitive path fragments (case-insensitive substring match against the path string).
# Kept specific to file-like references so they don't fire on arbitrary arg values.
SENSITIVE_PATH_FRAGMENTS: list[str] = [
    ".env",
    "id_rsa",
    "id_ed25519",
    "id_ecdsa",
    "id_dsa",
    "credentials",
    ".pem",
    ".p12",
    ".pfx",
    ".netrc",
    "auth.json",
    "/.ssh/",
    "secrets.json",
    "secrets.yaml",
    "secrets.yml",
]

# ---------------------------------------------------------------------------
# Compiled regex patterns
# ---------------------------------------------------------------------------

# export KEY=VALUE  →  export KEY=[REDACTED]
_EXPORT_RE = re.compile(
    r"(export\s+[A-Za-z_][A-Za-z0-9_]*)=(?!(\s|$))(.+?)(?=\s|$)",
)

# curl / wget  -u user:pass  or  --user user:pass
_CURL_USER_RE = re.compile(
    r"((?:-u|--user)\s+)[^\s:]+:[^\s]+",
)

# URL with embedded credentials: https://user:pass@host
_URL_CREDS_RE = re.compile(
    r"(https?://)([^@\s]+:[^@\s]+)(@)",
)

# Generic  KEY=VALUE  at word boundary (not inside a word)
_INLINE_ASSIGN_RE = re.compile(
    r"""(?<![=\w])"""
    r"""((?:PASSWORD|PASSWD|SECRET|TOKEN|KEY|AUTH|API_KEY|APIKEY|ACCESS_TOKEN|PRIVATE_KEY)"""
    r"""(?:_\w+)?)"""
    r"""=([^\s"']+)""",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _redact_flags(cmd: str) -> str:
    """Replace values following sensitive flags with [REDACTED]."""
    tokens = cmd.split()
    result: list[str] = []
    skip_next = False

    for token in tokens:
        if skip_next:
            result.append("[REDACTED]")
            skip_next = False
            continue

        # Check if this token *is* a sensitive flag (exact or --flag=value)
        flag_part, _, value_part = token.partition("=")
        if flag_part.lower() in REDACT_FLAGS:
            if value_part:
                # --flag=value form
                result.append(f"{flag_part}=[REDACTED]")
            else:
                result.append(token)
                skip_next = True
        else:
            result.append(token)

    return " ".join(result)


def _redact_patterns(cmd: str) -> str:
    """Apply regex-based redaction rules."""
    # export KEY=VALUE
    cmd = _EXPORT_RE.sub(r"\1=[REDACTED]", cmd)

    # curl -u / --user credentials
    cmd = _CURL_USER_RE.sub(r"\1[REDACTED]", cmd)

    # URL-embedded credentials
    cmd = _URL_CREDS_RE.sub(r"\1[REDACTED]\3", cmd)

    # Inline KEY=VALUE assignments (generic env-var style)
    cmd = _INLINE_ASSIGN_RE.sub(r"\1=[REDACTED]", cmd)

    return cmd


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def filter_command(cmd: str) -> str:
    """
    Return *cmd* with sensitive data redacted.

    Processing order:
    1. Sensitive-path check → replace entire command with placeholder.
    2. Flag-based redaction (--password, --token, etc.).
    3. Pattern-based redaction (export, curl -u, URL creds, KEY=VALUE).
    """
    if is_sensitive_path(cmd):
        return "[REDACTED_SENSITIVE_PATH]"

    cmd = _redact_flags(cmd)
    cmd = _redact_patterns(cmd)
    return cmd


def is_sensitive_path(path: str) -> bool:
    """
    Return True if *path* references a known-sensitive file or pattern.

    The check is case-insensitive and matches any substring.
    """
    lower = path.lower()
    return any(fragment in lower for fragment in SENSITIVE_PATH_FRAGMENTS)

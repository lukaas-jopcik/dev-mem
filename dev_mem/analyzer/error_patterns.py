"""
error_patterns.py — Fuzzy error grouping utilities.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dev_mem.db import Database


# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------

_LINE_NUM_RE = re.compile(r"\bline\s+\d+\b", re.IGNORECASE)
_FILE_PATH_RE = re.compile(r"(?:/[\w.\-]+)+|(?:[A-Za-z]:\\[\w\\.\-]+)")
_HEX_ADDR_RE = re.compile(r"\b0x[0-9a-fA-F]{4,}\b")
_WHITESPACE_RE = re.compile(r"\s+")

# Common Python/JS/Java/Rust exception class pattern
_ERROR_TYPE_RE = re.compile(
    r"\b([A-Z][a-zA-Z]*(?:Error|Exception|Warning|Panic|Fault|Failure))\b"
)


def _normalize(error_text: str) -> str:
    """Return a normalised representation suitable for hashing."""
    text = error_text
    text = _LINE_NUM_RE.sub("line N", text)
    text = _FILE_PATH_RE.sub("<path>", text)
    text = _HEX_ADDR_RE.sub("0xADDR", text)
    text = text.lower()
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_error_hash(error_text: str) -> str:
    """
    Return a SHA-1 hex digest of the normalised *error_text*.

    Normalisation steps:
    - Replace ``line <N>`` with ``line N``
    - Replace file paths with ``<path>``
    - Replace hex addresses (0x…) with ``0xADDR``
    - Lowercase and collapse whitespace
    """
    normalised = _normalize(error_text)
    return hashlib.sha1(normalised.encode("utf-8")).hexdigest()


def extract_error_type(error_text: str) -> str:
    """
    Extract the first recognised exception/error class name from *error_text*.

    Returns the class name string (e.g. ``"TypeError"``) or ``"UnknownError"``
    if none is found.
    """
    match = _ERROR_TYPE_RE.search(error_text)
    return match.group(1) if match else "UnknownError"


def analyze_error_frequency(
    db: "Database",
    project_id: int,
    days: int = 7,
) -> list[dict]:
    """
    Return a list of error records sorted by occurrence count (descending).

    Each item contains:
    - ``error_hash``: normalised hash
    - ``error_type``: extracted class name
    - ``count``: total occurrences
    - ``first_seen``: ISO timestamp
    - ``last_seen``: ISO timestamp
    - ``sample``: first 200 chars of the stored error text

    Only errors whose ``last_seen`` falls within the last *days* days are
    included.
    """
    cutoff = datetime.now(timezone.utc)
    from datetime import timedelta
    cutoff_iso = (cutoff - timedelta(days=days)).isoformat()

    rows = db._conn.execute(
        """
        SELECT error_hash, error_text, count, first_seen, last_seen
        FROM errors
        WHERE project_id IS ?
          AND last_seen >= ?
        ORDER BY count DESC
        """,
        (project_id, cutoff_iso),
    ).fetchall()

    results: list[dict] = []
    for row in rows:
        results.append(
            {
                "error_hash": row["error_hash"],
                "error_type": extract_error_type(row["error_text"]),
                "count": row["count"],
                "first_seen": row["first_seen"],
                "last_seen": row["last_seen"],
                "sample": row["error_text"][:200],
            }
        )
    return results

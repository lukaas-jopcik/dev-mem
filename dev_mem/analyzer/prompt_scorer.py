"""
prompt_scorer.py — 6-criterion prompt quality scorer.
"""

from __future__ import annotations

import re


# ---------------------------------------------------------------------------
# Criterion helpers
# ---------------------------------------------------------------------------

def _score_length(text: str) -> int:
    """Criterion 1: Length (0-20 pts)."""
    n = len(text)
    if 50 <= n <= 500:
        return 20
    if (20 <= n < 50) or (500 < n <= 1000):
        return 10
    return 0


def _score_context(text: str) -> int:
    """Criterion 2: Contains context (0-25 pts)."""
    lower = text.lower()
    signals = [
        bool(re.search(r"\bwhy\b", lower)),
        bool(re.search(r"\bwhat\b", lower)),
        bool(re.search(r"\bwhere\b", lower)),
        "because" in lower,
        "so that" in lower,
        "in order to" in lower,
        bool(re.search(r"\bcontext\b", lower)),
        bool(re.search(r"\bbackground\b", lower)),
        bool(re.search(r"\bpurpose\b", lower)),
        bool(re.search(r"\bgoal\b", lower)),
        bool(re.search(r"\bobjective\b", lower)),
    ]
    return 25 if sum(signals) >= 2 else 0


def _score_output_format(text: str) -> int:
    """Criterion 3: Specifies output format (0-20 pts)."""
    lower = text.lower()
    keywords = [
        "return", "output", "format", "as json", "as a list",
        "table", "markdown", "as markdown", "in json", "list of",
        "as a dict", "as a dictionary", "as xml", "as csv",
    ]
    return 20 if any(kw in lower for kw in keywords) else 0


def _score_example(text: str) -> int:
    """Criterion 4: Contains example or reference (0-15 pts)."""
    lower = text.lower()
    has_backtick = "`" in text
    phrases = ["for example", "like this", "e.g.", "such as", "for instance"]
    return 15 if (has_backtick or any(p in lower for p in phrases)) else 0


def _score_no_vague_verb(text: str) -> int:
    """Criterion 5: Avoids vague verbs as first word (0-10 pts)."""
    stripped = text.strip().lower()
    vague_verbs = {"do", "make", "fix", "handle", "deal"}
    first_word = re.split(r"\s+", stripped)[0].rstrip(".,:")
    return 0 if first_word in vague_verbs else 10


def _score_single_task(text: str) -> int:
    """Criterion 6: Single clear task (0-10 pts)."""
    lower = text.lower()
    multi_signals = [
        "and also",
        "additionally",
    ]
    please_count = lower.count("please")
    if any(sig in lower for sig in multi_signals) or please_count >= 2:
        return 0
    return 10


# ---------------------------------------------------------------------------
# Tag helpers
# ---------------------------------------------------------------------------

def _quality_tag(score: int) -> str:
    if score >= 80:
        return "exemplary"
    if score >= 60:
        return "good"
    if score >= 40:
        return "average"
    return "poor"


def _issue_tags(text: str, breakdown: dict[str, int]) -> list[str]:
    tags: list[str] = []
    n = len(text)
    if n < 20:
        tags.append("too-short")
    elif n > 1000:
        tags.append("too-long")
    if breakdown["context"] == 0:
        tags.append("no-context")

    stripped = text.strip().lower()
    first_word = re.split(r"\s+", stripped)[0].rstrip(".,:") if stripped else ""
    if first_word in {"do", "make", "fix", "handle", "deal"}:
        tags.append("vague-verb")

    lower = text.lower()
    multi_signals = ["and also", "additionally"]
    please_count = lower.count("please")
    if any(sig in lower for sig in multi_signals) or please_count >= 2:
        tags.append("multi-task")

    return tags


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def score_prompt(text: str) -> dict:
    """
    Score a prompt on 6 criteria and return a structured result.

    Returns:
        {
            "score": int,           # 0-100 total
            "breakdown": {
                "length": int,
                "context": int,
                "output_format": int,
                "example": int,
                "no_vague_verb": int,
                "single_task": int,
            },
            "tags": list[str],      # quality tag + issue tags
        }
    """
    breakdown = {
        "length": _score_length(text),
        "context": _score_context(text),
        "output_format": _score_output_format(text),
        "example": _score_example(text),
        "no_vague_verb": _score_no_vague_verb(text),
        "single_task": _score_single_task(text),
    }
    total = sum(breakdown.values())
    tags = [_quality_tag(total)] + _issue_tags(text, breakdown)

    return {
        "score": total,
        "breakdown": breakdown,
        "tags": tags,
    }

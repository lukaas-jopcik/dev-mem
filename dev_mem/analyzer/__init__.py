"""
analyzer/__init__.py — Public exports for the dev-mem analyzer layer.
"""

from __future__ import annotations

from dev_mem.analyzer.prompt_scorer import score_prompt
from dev_mem.analyzer.error_patterns import (
    generate_error_hash,
    extract_error_type,
    analyze_error_frequency,
)
from dev_mem.analyzer.context_builder import build_context, save_context
from dev_mem.analyzer.daily_summary import (
    generate_daily_summary,
    run_daily_job,
    check_missing_summaries,
)
from dev_mem.analyzer.rules import run_rules

__all__ = [
    "score_prompt",
    "generate_error_hash",
    "extract_error_type",
    "analyze_error_frequency",
    "build_context",
    "save_context",
    "generate_daily_summary",
    "run_daily_job",
    "check_missing_summaries",
    "run_rules",
]

from __future__ import annotations

"""
Cross-file symbol resolution (plan phase 2e).

Tier-1 (exact uid) and Tier-2 (imports) are partially handled in `loader.py`.
Extend this module for richer resolution without bloating the loader.
"""


def confidence_same_file() -> float:
    return 1.0


def confidence_cross_file_name_match() -> float:
    return 0.5

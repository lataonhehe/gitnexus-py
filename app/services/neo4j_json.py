"""Convert Neo4j driver values to JSON-friendly primitives."""

from __future__ import annotations

from typing import Any


def simplify_value(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, (str, int, float, bool)):
        return v
    if isinstance(v, (list, tuple)):
        return [simplify_value(x) for x in v]
    if isinstance(v, dict):
        return {k: simplify_value(val) for k, val in v.items()}
    t = type(v).__name__
    if t in ("Node", "Relationship", "Path"):
        return str(v)
    if hasattr(v, "iso_format"):
        try:
            return v.iso_format()
        except Exception:
            pass
    return str(v)

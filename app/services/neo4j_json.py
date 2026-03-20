"""Convert Neo4j driver values to JSON-friendly primitives."""

from __future__ import annotations

from typing import Any

from neo4j.graph import Node, Path, Relationship


def json_cell(v: Any) -> Any:
    """Serialize a single Cypher result cell (Node/Relationship → JSON dict)."""
    if isinstance(v, Node):
        return {k: simplify_value(x) for k, x in dict(v).items()}
    if isinstance(v, Relationship):
        return {
            "type": v.type,
            **{k: simplify_value(x) for k, x in dict(v).items()},
        }
    if isinstance(v, Path):
        return str(v)
    return simplify_value(v)


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

"""Guardrails for user-supplied Cypher (read-only, deny dangerous clauses)."""

from __future__ import annotations

import re

# Whole-token checks on a whitespace-normalized, string-stripped view of the query.
_FORBIDDEN_READ_ONLY = re.compile(
    r"\b("
    r"CREATE|MERGE|DELETE|DETACH|DROP|LOAD\s+CSV|LOAD\s+CSV\s+WITH|"
    r"FOREACH|GRANT|DENY|REVOKE|ALTER\s+USER|CREATE\s+USER|DROP\s+USER|"
    r"CALL\s+dbms\.|CALL\s+db\.ms\.|CALL\s+apoc\.|"
    r"USING\s+PERIODIC\s+COMMIT"
    r")\b",
    re.IGNORECASE | re.DOTALL,
)

# SET / REMOVE mutate in Neo4j — block in read-only mode.
_SET_REMOVE = re.compile(r"\b(SET|REMOVE)\b", re.IGNORECASE)


def _strip_strings_and_comments(cypher: str) -> str:
    """Remove single-line comments, block comments, and string literals (best-effort)."""
    s = cypher
    # line comments
    s = re.sub(r"//[^\n]*", " ", s)
    # block comments /* */
    s = re.sub(r"/\*.*?\*/", " ", s, flags=re.DOTALL)
    # double-quoted strings
    s = re.sub(r'"(?:\\.|[^"\\])*"', " ", s)
    # single-quoted strings
    s = re.sub(r"'(?:\\.|[^'\\])*'", " ", s)
    return s


def validate_cypher(cypher: str, *, read_only: bool = True) -> tuple[bool, str | None]:
    if not cypher or not cypher.strip():
        return False, "Empty Cypher query."
    normalized = _strip_strings_and_comments(cypher)
    if read_only:
        if _FORBIDDEN_READ_ONLY.search(normalized):
            return False, "Query contains forbidden clauses for read-only mode."
        if _SET_REMOVE.search(normalized):
            return False, "SET/REMOVE are not allowed in read-only mode."
    return True, None

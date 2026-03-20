"""Graph schema resource for `GET /repos/{id}/schema` (plan phase 3b)."""

SCHEMA_RESOURCE = {
    "node_labels": [
        "Repo",
        "Folder",
        "File",
        "Function",
        "Class",
        "Method",
        "Interface",
        "CodeElement",
    ],
    "relation_types": {
        "CONTAINS": {"from": ["Repo", "Folder"], "to": ["Folder", "File"]},
        "DEFINES": {
            "from": ["File"],
            "to": ["Function", "Class", "Method", "Interface"],
        },
        "HAS_METHOD": {"from": ["Class"], "to": ["Method"]},
        "IMPORTS": {
            "from": ["File"],
            "to": ["File"],
            "properties": ["confidence", "module_hint", "repo_id"],
        },
        "CALLS": {
            "from": ["File", "Function", "Method"],
            "to": ["Function", "Method"],
            "properties": ["confidence", "repo_id"],
        },
        "EXTENDS": {"from": ["Class"], "to": ["Class"]},
        "IMPLEMENTS": {"from": ["Class"], "to": ["Interface"]},
    },
    "node_properties": {
        "Function": [
            "uid",
            "name",
            "signature",
            "docstring",
            "start_line",
            "end_line",
            "file_path",
            "repo_id",
        ],
        "Class": [
            "uid",
            "name",
            "signature",
            "docstring",
            "start_line",
            "end_line",
            "file_path",
            "repo_id",
        ],
        "Method": [
            "uid",
            "name",
            "signature",
            "docstring",
            "start_line",
            "end_line",
            "file_path",
            "repo_id",
        ],
        "File": [
            "uid",
            "path",
            "name",
            "language",
            "content_hash",
            "hash",
            "line_count",
            "repo_id",
        ],
    },
    "example_queries": [
        "MATCH (f:Function) WHERE f.name = 'my_func' RETURN f",
        "MATCH (f:File {path: 'src/auth.py'})-[:DEFINES]->(fn) RETURN fn",
        "MATCH (a:Function)-[:CALLS]->(b:Function) WHERE a.name = 'handle_login' RETURN b",
    ],
}

# Legacy static doc shape (optional)
GRAPH_SCHEMA = {
    "version": 2,
    "schema": SCHEMA_RESOURCE,
}

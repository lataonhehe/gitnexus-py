"""Static schema description for MCP / `GET /repos/{id}/schema`."""

GRAPH_SCHEMA = {
    "version": 1,
    "node_labels": [
        {
            "label": "Repo",
            "description": "Registered repository root",
            "properties": ["id", "name", "root_path", "indexed_at", "head_commit"],
        },
        {
            "label": "Folder",
            "description": "Directory in the repo tree",
            "properties": ["uid", "repo_id", "path", "name"],
        },
        {
            "label": "File",
            "description": "Source file",
            "properties": [
                "uid",
                "repo_id",
                "path",
                "name",
                "language",
                "hash",
                "line_count",
            ],
        },
        {
            "label": "Symbol",
            "description": "Function, class, or method",
            "properties": [
                "uid",
                "repo_id",
                "file_path",
                "kind",
                "name",
                "qualified_name",
                "start_line",
                "end_line",
                "start_col",
                "end_col",
            ],
        },
    ],
    "relationship_types": [
        {"type": "CONTAINS", "from": ["Repo", "Folder"], "to": ["Folder", "File"]},
        {"type": "DEFINES", "from": ["File"], "to": ["Symbol"]},
        {"type": "CALLS", "from": ["Symbol"], "to": ["Symbol"], "properties": ["repo_id"]},
        {
            "type": "IMPORTS",
            "from": ["File"],
            "to": ["File"],
            "properties": ["repo_id", "module_hint"],
        },
    ],
}

# Python GitNexus Backend — Phase 1 → 3
> Nền tảng: FastAPI skeleton, single-repo indexer (tree-sitter), Cypher + context APIs.  
> Ba phase này là prerequisite bắt buộc trước khi bắt đầu Phase 4 (hybrid query).

---

## Tổng quan

| Phase | Tên | Mục tiêu chính | Thời gian ước tính |
|-------|-----|----------------|--------------------|
| 1 | Skeleton | Service chạy được, health checks, docker-compose | 0.5–1 ngày |
| 2 | Indexer v1 | Parse 1 repo → Neo4j graph (nodes + edges) | 2–3 ngày |
| 3 | Read APIs | Cypher endpoint, schema resource, context + disambiguation | 1–2 ngày |

**Exit criteria toàn bộ P1–P3:** Có thể navigate một codebase Python thật hoàn toàn qua API — list files, tìm functions, xem callers/callees — mà không cần mở editor.

---

## Phase 1 — Skeleton

**Goal:** Một lệnh duy nhất khởi động toàn bộ stack; health endpoint pass.

### Repo layout

```
gitnexus-backend/
  app/
    main.py
    config.py
    api/
      routes/
        health.py
    core/
      db.py          # Neo4j driver singleton
      logging.py     # structured logging setup
  docker-compose.yml
  pyproject.toml
  .env.example
```

### 1a — Config (`app/config.py`)

Dùng `pydantic-settings` để load từ env / `.env` file:

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    LOG_LEVEL: str = "INFO"

    # Neo4j
    NEO4J_URI: str = "bolt://localhost:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = "password"
    NEO4J_DATABASE: str = "neo4j"

    # Data
    DATA_DIR: str = "./data"           # BM25 corpus, embeddings cache (Phase 4+)
    REPO_ROOTS_ALLOWLIST: list[str] = []  # paths được phép index; empty = no restriction (dev only)

    class Config:
        env_file = ".env"

settings = Settings()
```

### 1b — Neo4j driver singleton (`app/core/db.py`)

```python
from neo4j import AsyncGraphDatabase, AsyncDriver
from contextlib import asynccontextmanager
from app.config import settings

_driver: AsyncDriver | None = None

async def get_driver() -> AsyncDriver:
    global _driver
    if _driver is None:
        _driver = AsyncGraphDatabase.driver(
            settings.NEO4J_URI,
            auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
        )
    return _driver

async def close_driver():
    global _driver
    if _driver:
        await _driver.close()
        _driver = None

@asynccontextmanager
async def get_session():
    driver = await get_driver()
    async with driver.session(database=settings.NEO4J_DATABASE) as session:
        yield session
```

### 1c — Structured logging (`app/core/logging.py`)

```python
import logging
import structlog

def setup_logging(level: str = "INFO"):
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.stdlib.add_log_level,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
    )
    logging.basicConfig(level=getattr(logging, level))
```

### 1d — Health endpoints (`app/api/routes/health.py`)

```python
from fastapi import APIRouter
from app.core.db import get_driver

router = APIRouter()

@router.get("/health")
async def health():
    # Liveness — luôn trả về 200 nếu process đang chạy
    return {"status": "ok"}

@router.get("/ready")
async def ready():
    # Readiness — check Neo4j có reachable không
    try:
        driver = await get_driver()
        await driver.verify_connectivity()
        return {"status": "ready", "neo4j": "connected"}
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail={"status": "not_ready", "neo4j": str(e)})
```

### 1e — Main app (`app/main.py`)

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.config import settings
from app.core.logging import setup_logging
from app.core.db import close_driver
from app.api.routes.health import router as health_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging(settings.LOG_LEVEL)
    yield
    await close_driver()

app = FastAPI(title="GitNexus Backend", version="0.1.0", lifespan=lifespan)
app.include_router(health_router, tags=["health"])
```

### 1f — docker-compose.yml

```yaml
services:
  neo4j:
    image: neo4j:5.20-community
    ports:
      - "7474:7474"   # Neo4j Browser (dev)
      - "7687:7687"   # Bolt
    environment:
      NEO4J_AUTH: neo4j/password
      NEO4J_PLUGINS: '["apoc"]'
      NEO4J_dbms_memory_heap_initial__size: "512m"
      NEO4J_dbms_memory_heap_max__size: "1g"
    volumes:
      - neo4j_data:/data
    healthcheck:
      test: ["CMD", "neo4j", "status"]
      interval: 10s
      retries: 5

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    # Redis dùng cho background tasks (Phase 4+, arq)
    # Để ở đây ngay từ đầu, dùng hay không tùy

volumes:
  neo4j_data:
```

### 1g — pyproject.toml (dependencies P1–P3)

```toml
[tool.poetry.dependencies]
python = "^3.11"
fastapi = "^0.111"
uvicorn = {extras = ["standard"], version = "^0.29"}
pydantic-settings = "^2"
neo4j = "^5.20"
structlog = "^24"
tree-sitter = "^0.23"
gitpython = "^3.1"
python-dotenv = "^1"
```

### 1h — Error model chuẩn

Áp dụng nhất quán cho tất cả endpoints từ P1 trở đi:

```python
# app/core/errors.py
from fastapi import Request
from fastapi.responses import JSONResponse

class GitNexusError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        self.code = code
        self.message = message
        self.status = status

async def gitnexus_error_handler(request: Request, exc: GitNexusError):
    return JSONResponse(
        status_code=exc.status,
        content={"error": {"code": exc.code, "message": exc.message}}
    )

# Dùng:
# raise GitNexusError("REPO_NOT_FOUND", f"Repo '{repo_id}' not found", 404)
```

### Exit criteria P1

```bash
docker-compose up -d
uvicorn app.main:app --reload

curl http://localhost:8000/health   # → {"status": "ok"}
curl http://localhost:8000/ready    # → {"status": "ready", "neo4j": "connected"}
```

---

## Phase 2 — Single-repo Indexer v1

**Goal:** Đăng ký 1 repo local → walk files → parse bằng tree-sitter → load graph vào Neo4j với đầy đủ `CONTAINS / DEFINES / IMPORTS / CALLS` edges.

### File structure bổ sung

```
app/
  api/routes/
    repos.py           # repo registry CRUD
  indexer/
    registry.py        # Repo node CRUD trong Neo4j
    walker.py          # file walker + language detection
    parser.py          # tree-sitter queries per language
    resolver.py        # symbol resolution (import paths → uid)
    loader.py          # Neo4j batch upsert
    pipeline.py        # orchestrate toàn bộ indexing flow
```

### 2a — Neo4j schema (constraints + indexes)

Chạy một lần khi startup:

```cypher
// Constraints — đảm bảo idempotency
CREATE CONSTRAINT repo_id IF NOT EXISTS
  FOR (r:Repo) REQUIRE r.id IS UNIQUE;

CREATE CONSTRAINT file_uid IF NOT EXISTS
  FOR (f:File) REQUIRE f.uid IS UNIQUE;

CREATE CONSTRAINT symbol_uid IF NOT EXISTS
  FOR (s:Function|Class|Method|Interface|CodeElement) REQUIRE s.uid IS UNIQUE;

// Indexes — tăng tốc lookup
CREATE INDEX file_path IF NOT EXISTS FOR (f:File) ON (f.path);
CREATE INDEX symbol_name IF NOT EXISTS FOR (s:Function) ON (s.name);
CREATE INDEX symbol_name_class IF NOT EXISTS FOR (s:Class) ON (s.name);
```

### 2b — Repo registry (`app/indexer/registry.py`)

**Node `Repo` trong Neo4j:**
```cypher
(:Repo {
  id: STRING,           // slug từ repo name, e.g. "my-project"
  name: STRING,
  root_path: STRING,    // absolute path trên filesystem
  indexed_at: DATETIME,
  head_commit: STRING,  // git HEAD sha lúc index
  file_count: INT,
  symbol_count: INT,
  status: STRING        // "indexing" | "ready" | "error"
})
```

**API endpoints:**
```
GET  /repos                     # list all repos
POST /repos                     # register + trigger index
  Body: { "path": "/absolute/path", "name": "my-project" }
GET  /repos/{repo_id}           # stats + status
DELETE /repos/{repo_id}         # unregister + xóa nodes
POST /repos/{repo_id}/reindex   # trigger re-index
```

### 2c — File walker (`app/indexer/walker.py`)

```python
LANGUAGE_MAP = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".go": "go",
    ".java": "java",
    ".rs": "rust",
    ".rb": "ruby",
    ".cs": "c_sharp",
    ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp",
    ".c": "c",
}

IGNORE_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    "dist", "build", ".next", ".nuxt", "vendor",
}
```

**Logic:**
1. Load `.gitignore` với `pathspec` library → filter files
2. Walk với `os.walk`, skip `IGNORE_DIRS`
3. Hash mỗi file: `sha256(content)` → lưu vào `File.content_hash`
4. So sánh hash với lần index trước → skip nếu unchanged (idempotent indexing)

**Node `File`:**
```cypher
(:File {
  uid: STRING,         // "file::{relative_path}"
  path: STRING,        // relative to repo root
  name: STRING,        // basename
  language: STRING,
  content_hash: STRING,
  line_count: INT,
  repo_id: STRING
})
```

**Node `Folder`:**
```cypher
(:Folder {
  uid: STRING,         // "folder::{relative_path}"
  path: STRING,
  name: STRING,
  repo_id: STRING
})
```

**Edges từ walker:**
```cypher
(:Folder)-[:CONTAINS]->(:File)
(:Folder)-[:CONTAINS]->(:Folder)   // nested dirs
```

### 2d — Tree-sitter parser (`app/indexer/parser.py`)

**Grammars cần install:**
```bash
pip install tree-sitter-python tree-sitter-typescript tree-sitter-javascript \
            tree-sitter-go tree-sitter-java tree-sitter-rust
```

**Queries per language — Python example:**

```python
PYTHON_QUERIES = {
    "functions": """
        (function_definition
          name: (identifier) @name
          parameters: (parameters) @params
        ) @definition
    """,
    "classes": """
        (class_definition
          name: (identifier) @name
          superclasses: (argument_list)? @bases
        ) @definition
    """,
    "methods": """
        (class_definition
          body: (block
            (function_definition
              name: (identifier) @name
            ) @definition
          )
        )
    """,
    "imports": """
        [
          (import_statement
            name: (dotted_name) @module)
          (import_from_statement
            module_name: (dotted_name) @module
            name: (dotted_name) @symbol)
        ]
    """,
    "calls": """
        (call
          function: [
            (identifier) @callee
            (attribute
              object: (_) @object
              attribute: (identifier) @callee)
          ]
        )
    """,
}
```

**Symbol node schema chung:**
```cypher
(:Function {
  uid: STRING,         // "func::{file_path}::{name}" hoặc "func::{file_path}::{class}::{name}"
  name: STRING,
  signature: STRING,   // "def func(a, b) -> str" (raw text từ AST)
  docstring: STRING,   // first string literal sau definition nếu có
  start_line: INT,     // cho Phase 7 span tracking
  end_line: INT,
  file_path: STRING,   // relative path
  repo_id: STRING
})

// Tương tự cho :Class, :Method, :Interface, :CodeElement
```

**Edges từ parser:**
```cypher
(:File)-[:DEFINES]->(:Function|:Class|:Method|:Interface)
(:Class)-[:HAS_METHOD]->(:Method)
```

**LRU cache cho tree-sitter parsers:**
```python
from functools import lru_cache
import tree_sitter_python as tspython
from tree_sitter import Language, Parser

@lru_cache(maxsize=10)
def get_parser(language: str) -> Parser:
    # Lazy load grammar, cache theo language
    ...
```

> **Lưu ý memory:** Gọi `tree.delete()` sau khi parse xong mỗi file nếu dùng WASM runtime. Với Python bindings native thì GC tự xử lý.

### 2e — Symbol resolver (`app/indexer/resolver.py`)

**3-tier resolution strategy cho CALLS edges:**

```
Tier 1 — Exact uid match
  Lookup bằng "func::{file_path}::{name}" trực tiếp trong Neo4j.
  Confidence: 1.0

Tier 2 — Name + imports match
  Nếu file A import module B, và callee name match function trong B → CALLS edge.
  Confidence: 0.9

Tier 3 — Name-only fuzzy match
  Tìm tất cả symbols có name khớp, chọn cái trong cùng repo.
  Confidence: 0.5
  Ghi nhận là unresolved nếu ambiguous (> 3 candidates).
```

**IMPORTS resolution:**
```python
def resolve_import_path(
    import_stmt: str,
    current_file: str,
    repo_root: str,
    language: str,
) -> str | None:
    # Python: "from app.core.db import get_driver"
    #   → thử resolve "app/core/db.py" relative to repo_root
    # TypeScript: "import { foo } from '../utils/foo'"
    #   → resolve relative path + thử .ts, .tsx, index.ts
    ...
```

### 2f — Neo4j batch loader (`app/indexer/loader.py`)

**Dùng `MERGE` để idempotent:**
```python
UPSERT_FILE = """
MERGE (f:File {uid: $uid})
SET f += $props
WITH f
MATCH (repo:Repo {id: $repo_id})
MERGE (repo)-[:CONTAINS]->(f)
"""

UPSERT_FUNCTION = """
MERGE (fn:Function {uid: $uid})
SET fn += $props
WITH fn
MATCH (f:File {uid: $file_uid})
MERGE (f)-[:DEFINES]->(fn)
"""

UPSERT_CALLS = """
MATCH (a {uid: $from_uid})
MATCH (b {uid: $to_uid})
MERGE (a)-[r:CALLS {confidence: $confidence}]->(b)
"""
```

**Batch size:** 500 nodes per transaction. Wrap trong `AsyncTransaction`.

**Edge `CodeRelation` thay vì typed edges (optional):**  
Nếu muốn khớp với GitNexus MCP schema (`CodeRelation` với `type` property):
```cypher
// Thay vì (:File)-[:CALLS]->(:Function)
// Dùng: (:File)-[:CodeRelation {type: "CALLS", confidence: 0.9}]->(:Function)
```
Ưu điểm: Cypher queries đơn giản hơn khi filter theo `type`.  
Nhược điểm: Mất type-safety trong Neo4j constraints.  
**Recommend:** Dùng typed edges (`CALLS`, `IMPORTS`, v.v.) + thêm `confidence` property. Filter trong Cypher bằng `type(r)`.

### 2g — Index pipeline (`app/indexer/pipeline.py`)

```python
async def run_index(repo_id: str, force: bool = False) -> IndexResult:
    # 1. Load repo từ registry
    # 2. Set status = "indexing"
    # 3. Walk files → build file list
    # 4. Per file (parallel với asyncio.gather, max 10 concurrent):
    #    a. Check hash → skip nếu unchanged (trừ khi force=True)
    #    b. Parse với tree-sitter → extract symbols
    #    c. Upsert nodes vào Neo4j
    # 5. Second pass: resolve IMPORTS + CALLS
    #    (cần tất cả File/Function nodes đã có mặt trong graph trước)
    # 6. Update Repo: indexed_at, head_commit, file_count, symbol_count
    # 7. Set status = "ready"
    # 8. Return IndexResult stats
```

**Tại sao 2 passes:**  
Pass 1 upsert tất cả nodes. Pass 2 mới tạo cross-file edges, vì khi gặp `import X from Y` trong pass 1, file Y chưa chắc đã được parse xong.

### Exit criteria P2

```bash
# Register và index một Python repo
curl -X POST http://localhost:8000/repos \
  -H "Content-Type: application/json" \
  -d '{"path": "/home/user/my-project", "name": "my-project"}'

# Chờ index xong (polling hoặc check status)
curl http://localhost:8000/repos/my-project
# → {"status": "ready", "file_count": 42, "symbol_count": 380}

# Verify trong Neo4j Browser: http://localhost:7474
# MATCH (f:Function) RETURN f LIMIT 10
```

---

## Phase 3 — Read APIs: Cypher + Context

**Goal:** Navigate codebase hoàn toàn qua API — khớp với `gitnexus_cypher` và `gitnexus_context` MCP tools.

### File structure bổ sung

```
app/
  api/routes/
    cypher.py
    context.py
    schema.py      # schema resource endpoint
```

### 3a — Cypher endpoint (`app/api/routes/cypher.py`)

**Guardrails bắt buộc:**

```python
CYPHER_BLOCKLIST = [
    "CREATE", "DELETE", "MERGE", "SET", "DROP",
    "DETACH", "REMOVE", "CALL apoc.periodic",
    "LOAD CSV",
]

MAX_ROWS = 1000
TIMEOUT_SECONDS = 30

def validate_cypher(query: str):
    upper = query.upper()
    for keyword in CYPHER_BLOCKLIST:
        if keyword in upper:
            raise GitNexusError(
                "CYPHER_FORBIDDEN",
                f"Clause '{keyword}' not allowed in read-only mode.",
                403
            )
```

**Endpoint:**
```
POST /repos/{repo_id}/cypher
Body: { "query": "MATCH (f:Function) WHERE f.name = 'verify_token' RETURN f" }

Response:
{
  "columns": ["f"],
  "rows": [ {"f": {"uid": "...", "name": "verify_token", ...}} ],
  "row_count": 1,
  "truncated": false
}
```

**Implementation:**
```python
async with get_session() as session:
    result = await session.run(
        query,
        timeout=TIMEOUT_SECONDS
    )
    records = await result.fetch(MAX_ROWS + 1)
    truncated = len(records) > MAX_ROWS
    return {
        "columns": result.keys(),
        "rows": [dict(r) for r in records[:MAX_ROWS]],
        "row_count": min(len(records), MAX_ROWS),
        "truncated": truncated,
    }
```

### 3b — Schema resource (`app/api/routes/schema.py`)

Feed trực tiếp cho MCP resource `gitnexus://repo/{name}/schema`:

```
GET /repos/{repo_id}/schema

Response:
{
  "node_labels": ["Repo", "Folder", "File", "Function", "Class", "Method", "Interface", "CodeElement"],
  "relation_types": {
    "CONTAINS": { "from": ["Repo", "Folder"], "to": ["Folder", "File"] },
    "DEFINES":  { "from": ["File"], "to": ["Function", "Class", "Method", "Interface"] },
    "HAS_METHOD": { "from": ["Class"], "to": ["Method"] },
    "IMPORTS":  { "from": ["File"], "to": ["File"], "properties": ["confidence"] },
    "CALLS":    { "from": ["File", "Function", "Method"], "to": ["Function", "Method"],
                  "properties": ["confidence"] },
    "EXTENDS":  { "from": ["Class"], "to": ["Class"] },
    "IMPLEMENTS": { "from": ["Class"], "to": ["Interface"] }
  },
  "node_properties": {
    "Function": ["uid", "name", "signature", "docstring", "start_line", "end_line", "file_path", "repo_id"],
    "File": ["uid", "path", "name", "language", "content_hash", "line_count", "repo_id"]
  },
  "example_queries": [
    "MATCH (f:Function) WHERE f.name = 'my_func' RETURN f",
    "MATCH (f:File {path: 'src/auth.py'})-[:DEFINES]->(fn) RETURN fn",
    "MATCH (a:Function)-[:CALLS]->(b:Function) WHERE a.name = 'handle_login' RETURN b"
  ]
}
```

### 3c — Context endpoint (`app/api/routes/context.py`)

Khớp với `gitnexus_context` MCP tool.

**Input:**
```
POST /repos/{repo_id}/context
Body:
{
  "name": "verify_token",       // symbol name (required)
  "uid": null,                   // exact uid nếu đã biết (optional, bỏ qua disambiguation)
  "file_path": "src/auth.py",   // optional, hỗ trợ disambiguation
  "depth": 1                    // hop depth cho callers/callees, default 1
}
```

**Disambiguation logic:**

```python
async def resolve_symbol(name: str, uid: str | None, file_path: str | None, repo_id: str):
    if uid:
        # Direct lookup — không cần disambiguate
        return [await fetch_by_uid(uid)]

    candidates = await search_by_name(name, repo_id)

    if len(candidates) == 0:
        raise GitNexusError("SYMBOL_NOT_FOUND", f"No symbol named '{name}'", 404)

    if len(candidates) == 1:
        return candidates

    # Nhiều hơn 1 → thử narrow down
    if file_path:
        filtered = [c for c in candidates if c["file_path"] == file_path]
        if filtered:
            return filtered

    # Vẫn ambiguous → trả về disambiguation list
    return candidates  # caller sẽ check len > 1
```

**Response (resolved — 1 symbol):**
```json
{
  "symbol": {
    "uid": "func::src/auth.py::verify_token",
    "name": "verify_token",
    "label": "Function",
    "signature": "def verify_token(token: str) -> dict",
    "docstring": "Verifies JWT token signature and expiry. Returns decoded payload.",
    "file_path": "src/auth.py",
    "start_line": 42,
    "end_line": 67
  },
  "callers": [
    { "uid": "func::src/middleware.py::auth_middleware", "name": "auth_middleware", "file_path": "src/middleware.py" }
  ],
  "callees": [
    { "uid": "func::src/utils/jwt.py::decode_jwt", "name": "decode_jwt", "file_path": "src/utils/jwt.py" },
    { "uid": "func::src/utils/jwt.py::check_expiry", "name": "check_expiry", "file_path": "src/utils/jwt.py" }
  ],
  "defined_in": { "uid": "file::src/auth.py", "path": "src/auth.py" },
  "disambiguation": null
}
```

**Response (ambiguous — nhiều symbols cùng tên):**
```json
{
  "symbol": null,
  "disambiguation": [
    { "uid": "func::src/auth.py::verify_token",         "file_path": "src/auth.py",        "label": "Function" },
    { "uid": "func::tests/test_auth.py::verify_token",  "file_path": "tests/test_auth.py", "label": "Function" }
  ],
  "hint": "Multiple symbols named 'verify_token'. Retry with uid or file_path to disambiguate."
}
```

**Cypher queries cho context:**

```cypher
// Callers (ai gọi đến symbol này)
MATCH (caller)-[:CALLS]->(target {uid: $uid})
RETURN caller LIMIT 20

// Callees (symbol này gọi đến ai)
MATCH (target {uid: $uid})-[:CALLS]->(callee)
RETURN callee LIMIT 20

// Files import file chứa symbol này
MATCH (importer:File)-[:IMPORTS]->(f:File {uid: $file_uid})
RETURN importer LIMIT 20
```

### 3d — Repo list endpoint (nâng cấp từ P2)

```
GET /repos

Response:
{
  "repos": [
    {
      "id": "my-project",
      "name": "my-project",
      "root_path": "/home/user/my-project",
      "status": "ready",
      "indexed_at": "2025-03-20T10:30:00Z",
      "head_commit": "a1b2c3d4",
      "stats": {
        "file_count": 42,
        "symbol_count": 380,
        "edge_count": 1240
      }
    }
  ]
}
```

### Exit criteria P3

```bash
# 1. Cypher query
curl -X POST http://localhost:8000/repos/my-project/cypher \
  -H "Content-Type: application/json" \
  -d '{"query": "MATCH (fn:Function) WHERE fn.name = \"verify_token\" RETURN fn"}'

# 2. Schema
curl http://localhost:8000/repos/my-project/schema

# 3. Context — resolved
curl -X POST http://localhost:8000/repos/my-project/context \
  -H "Content-Type: application/json" \
  -d '{"name": "verify_token"}'
# → callers, callees, định nghĩa đầy đủ

# 4. Context — disambiguation
curl -X POST http://localhost:8000/repos/my-project/context \
  -H "Content-Type: application/json" \
  -d '{"name": "helper"}'
# → disambiguation list nếu có nhiều symbols tên "helper"

# 5. Cypher blocked
curl -X POST http://localhost:8000/repos/my-project/cypher \
  -H "Content-Type: application/json" \
  -d '{"query": "CREATE (n:Test) RETURN n"}'
# → 403 CYPHER_FORBIDDEN
```

---

## Security checklist (áp dụng từ P3)

- Cypher: read-only transactions, blocklist `CREATE/DELETE/MERGE/SET/DROP`, timeout 30s, row limit 1000
- Repo paths: validate `root_path` nằm trong `REPO_ROOTS_ALLOWLIST` (nếu không rỗng)
- Không log Neo4j passwords, không expose stack traces trong production responses
- Rate limit: optional ở P3, bắt buộc ở P10

---

## Dependency summary P1–P3

```toml
[tool.poetry.dependencies]
python = "^3.11"
fastapi = "^0.111"
uvicorn = {extras = ["standard"], version = "^0.29"}
pydantic-settings = "^2"
neo4j = "^5.20"
structlog = "^24"
tree-sitter = "^0.23"
tree-sitter-python = "*"
tree-sitter-typescript = "*"
tree-sitter-javascript = "*"
tree-sitter-go = "*"
tree-sitter-java = "*"
tree-sitter-rust = "*"
gitpython = "^3.1"
pathspec = "^0.12"      # .gitignore parsing
python-dotenv = "^1"
```

---

## Chuẩn bị cho Phase 4

Trước khi kết thúc P3, bổ sung sẵn để P4 không cần quay lại sửa:

1. **`start_line` / `end_line` trên mọi symbol node** — Phase 7 (`detect_changes`) cần để map diff hunks → symbols. Nếu bỏ sót ở P2 thì P7 phải re-index toàn bộ.

2. **`docstring` extraction** — Phase 4 BM25 corpus dùng docstring để improve search quality. Extract luôn trong P2 parser.

3. **`content_hash` trên File node** — Đã có. Incremental re-index ở P10 dùng hash này.

4. **`CodeRelation.confidence`** — Đã có trên CALLS/IMPORTS edges. Phase 4 `minConfidence` filter dùng field này.

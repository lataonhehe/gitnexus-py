# gitnexus-py

Backend kiểu **GitNexus** bằng Python: **FastAPI** + **Neo4j** + **tree-sitter** (Python). Đăng ký repo, index mã nguồn lên đồ thị (Function / Class / Method, CALLS, IMPORTS, CONTAINS), rồi điều hướng codebase qua API theo [`plan_phase1_3.md`](plan_phase1_3.md).

## Yêu cầu

- Python **3.10+**
- **Docker** (Neo4j; Redis tùy chọn, profile `workers`)

## Cài đặt

```bash
pip install -e ".[dev]"
```

## Chạy Neo4j

```bash
docker compose pull neo4j
docker compose up -d neo4j
```

Image: **`neo4j:community`** (bản Community mới nhất). Xóa hẳn dữ liệu graph cũ (volume):

```bash
docker compose down -v
docker compose up -d neo4j
```

`docker-compose.yml` trong repo có thể map Bolt/Browser sang cổng tùy chỉnh (ví dụ **7876** / **7321**); chỉnh `GITNEXUS_NEO4J_URI` / URL Browser cho khớp. Chạy Neo4j mặc định ngoài compose: Bolt `bolt://localhost:7687`, user `neo4j`, password theo `NEO4J_AUTH`.

## Cấu hình

Tạo **`.env`** từ [`.env.example`](.env.example). Biến chính dùng tiền tố **`GITNEXUS_`** (xem [`app/config.py`](app/config.py)).

| Biến | Mặc định | Ý nghĩa |
|------|----------|---------|
| `GITNEXUS_NEO4J_URI` | *(trống)* | `bolt://localhost:7687` |
| `GITNEXUS_NEO4J_USER` | `neo4j` | User Neo4j |
| `GITNEXUS_NEO4J_PASSWORD` | `gitnexus-dev` | Mật khẩu |
| `GITNEXUS_NEO4J_DATABASE` | `neo4j` | Tên database Neo4j |
| `GITNEXUS_NEO4J_ENABLED` | `true` | `false`: `/ready` bỏ qua DB |
| `GITNEXUS_REPO_ROOTS_ALLOWLIST` | *(trống)* | Danh sách root được phép index (CSV); rỗng = không hạn chế |
| `GITNEXUS_LOG_LEVEL` | `INFO` | Log (JSON qua structlog) |
| `GITNEXUS_CYPHER_MAX_ROWS` | `1000` | Giới hạn dòng Cypher |
| `GITNEXUS_CYPHER_TIMEOUT_SECONDS` | `30` | Timeout Cypher |
| `GITNEXUS_CYPHER_READ_ONLY` | `true` | Guard read-only |

## Chạy API

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- OpenAPI: [http://localhost:8000/docs](http://localhost:8000/docs)
- `GET /health` — liveness
- `GET /ready` — readiness (Neo4j); **503** nếu không kết nối được

## Đăng ký và index (Phase 2–3)

**Local path** (một trong hai: `path` **hoặc** `git_url`):

```bash
curl -X POST http://localhost:8000/repos -H "Content-Type: application/json" ^
  -d "{\"name\":\"my-project\",\"path\":\"C:/path/to/repo\"}"
```

**Git URL** (server tự `git clone` shallow vào `DATA_DIR/clones/{repo_id}`, rồi index):

```bash
curl -X POST http://localhost:8000/repos -H "Content-Type: application/json" ^
  -d "{\"name\":\"FastAPI\",\"git_url\":\"https://github.com/tiangolo/fastapi.git\",\"branch\":\"master\"}"
```

Tùy chọn: `force_clone: true` (xóa worktree cũ và clone lại), `trigger_index: false` (chỉ đăng ký).  
Bảo mật: đặt `GITNEXUS_GIT_URL_ALLOWED_HOSTS` (CSV, hỗ trợ `*.gitlab.com`) trên môi trường team; URL chỉ `http`/`https`, chặn localhost/IP private trong URL.

```bash
curl http://localhost:8000/repos/my-project
curl -X POST "http://localhost:8000/repos/my-project/reindex"
# Tắt git pull: POST .../reindex?pull=false
curl -X POST http://localhost:8000/repos/my-project/index ^
  -H "Content-Type: application/json" -d "{\"full\":true,\"pull\":true}"
```

- `GET /repos` — `{ "repos": [ { id, name, root_path, status, stats: { file_count, symbol_count, edge_count }, ... } ] }`
- `DELETE /repos/{repo_id}` — gỡ đăng ký và xóa đồ thị có `repo_id`
- `GET /repos/{repo_id}/schema` — schema cho MCP / tài liệu (plan 3b)

### Read API (Phase 3)

| Method | Path | Mô tả |
|--------|------|--------|
| POST | `/repos/{repo_id}/cypher` | Cypher read-only; body `{ "query", "parameters"? }`; lỗi guard → **403** `CYPHER_FORBIDDEN` |
| POST | `/repos/{repo_id}/context` | Context symbol: `name`, `uid?`, `file_path?`, `depth` (1–8); disambiguation khi trùng tên |

## Hạn chế

- Index v1 chỉ **Python** (`.py`), dù `LANGUAGE_MAP` đã chuẩn bị theo plan.
- Đổi mô hình node (`Symbol` → `Function`/`Class`/`Method`) cần **re-index full** (`POST .../reindex`).

## Dev

```bash
ruff check app
ruff format app
```

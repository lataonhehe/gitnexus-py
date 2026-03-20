# gitnexus-py

Backend kiểu **GitNexus** bằng Python: **FastAPI** + **Neo4j** + **tree-sitter** (Python). Đăng ký repo, index mã nguồn lên đồ thị, rồi truy vấn **Cypher** (read-only, có giới hạn) và **context** quanh symbol (callers/callees/imports).

Trạng triển khai theo [`plan.md`](plan.md): đã có tới **Phase 3** (skeleton, indexer, read API). Các tính năng Phase 4+ (BM25/RRF, impact, git diff, rename, …) nằm trong roadmap, chưa có trong code.

## Yêu cầu

- Python **3.10+**
- **Docker** (Neo4j; Redis tùy chọn)

## Cài đặt

```bash
pip install -e ".[dev]"
```

## Chạy Neo4j

```bash
docker compose up -d neo4j
```

Mặc định trong `docker-compose.yml`: **Bolt** `bolt://localhost:7687`, user `neo4j`, password `gitnexus-dev`.

## Cấu hình

Tạo file **`.env`** ở thư mục gốc dự án hoặc export biến môi trường. Tất cả biến dùng tiền tố **`GITNEXUS_`** (xem [`app/config.py`](app/config.py)).

| Biến | Mặc định | Ý nghĩa |
|------|----------|---------|
| `GITNEXUS_NEO4J_URI` | *(trống)* | Ví dụ `bolt://localhost:7687` |
| `GITNEXUS_NEO4J_USER` | `neo4j` | User Neo4j |
| `GITNEXUS_NEO4J_PASSWORD` | `gitnexus-dev` | Mật khẩu |
| `GITNEXUS_NEO4J_ENABLED` | `true` | `false`: `/ready` bỏ qua DB; API đồ thị trả 503 nếu cần driver |
| `GITNEXUS_LOG_LEVEL` | `INFO` | Mức log |
| `GITNEXUS_DATA_DIR` | `./data` | Thư mục dữ liệu cục bộ (cache/index sau này) |
| `GITNEXUS_CYPHER_TIMEOUT_SECONDS` | `30` | Timeout Cypher |
| `GITNEXUS_CYPHER_MAX_ROWS` | `5000` | Giới hạn số dòng trả về |
| `GITNEXUS_CYPHER_READ_ONLY` | `true` | Chỉ cho truy vấn read (guard) |
| `GITNEXUS_REDIS_URL` | *(trống)* | Dự phòng cho worker sau này |

## Chạy API

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- **OpenAPI / Swagger UI:** [http://localhost:8000/docs](http://localhost:8000/docs)
- `GET /health` — process còn sống
- `GET /ready` — kết nối Neo4j (hoặc `skipped` nếu tắt Neo4j)

## Đăng ký và index repo

Thay `C:/path/to/repo` bằng đường dẫn thật tới root git clone.

```bash
curl -X POST http://localhost:8000/repos -H "Content-Type: application/json" -d "{\"id\":\"demo\",\"name\":\"Demo\",\"root_path\":\"C:/path/to/repo\"}"
curl -X POST http://localhost:8000/repos/demo/index -H "Content-Type: application/json" -d "{\"full\":true}"
```

- `GET /repos` — danh sách repo đã đăng ký
- `GET /repos/{repo_id}/schema` — mô tả label / quan hệ đồ thị (hỗ trợ MCP / tài liệu)

## API hiện có (Phase 3)

| Method | Path | Mô tả |
|--------|------|--------|
| POST | `/cypher` | Cypher read-only, có guard, timeout, giới hạn dòng |
| POST | `/context` | Một symbol → callers / callees / imports (+ disambiguation bằng `uid` / `file_path`) |

## Redis (tùy chọn)

```bash
docker compose --profile workers up -d
```

Dùng cho worker nền sau này; **không bắt buộc** cho Phase 3.

## Hạn chế

- Index hiện chỉ **Python** (`.py`).
- Các endpoint roadmap (`/query`, `/impact`, git diff, rename, …) chưa triển khai — xem [`plan.md`](plan.md).

## Công cụ dev (optional)

```bash
ruff check app
ruff format app
```

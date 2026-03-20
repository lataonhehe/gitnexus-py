# syntax=docker/dockerfile:1
# --------------------------------------------
# Stage 1: builder
# --------------------------------------------
FROM python:3.10-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

COPY pyproject.toml ./

# stub d? editable install không l?i khi chua có source
RUN mkdir -p app && touch app/__init__.py

RUN pip install --upgrade pip setuptools wheel \
    && pip install \
        --prefix=/install \
        --no-build-isolation \
        -e ".[dev]"

# --------------------------------------------
# Stage 2: runtime
# --------------------------------------------
FROM python:3.10-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local

WORKDIR /app

COPY . .

RUN pip install --no-build-isolation --no-deps -e .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "1349", "--reload"]
# Development guide

## Local run

1. Create and activate a Python 3.11+ virtual environment.
2. Install `requirements.txt`.
3. Copy `.env.example` to `.env` and adjust values if needed.
4. Run `uvicorn backend.app.main:app --reload`.

The service listens on port 8000 by default. `GET /health` is dependency-free in Day 1, enabling quick CI and local verification.

## Project layout

```text
backend/app/
  api/        HTTP boundaries
  schemas/    request/response contracts
  config.py   environment settings
  logging.py  shared logging setup
  main.py     application composition
docs/         product and technical documentation
tests/        automated checks
```

Day 2 adds `models/`, `db/`, and migration support without changing the API entry point.

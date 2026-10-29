# Built from the repo root: docker build -f backend/Dockerfile .
# (needs both src/ and backend/, which a context rooted at backend/ wouldn't see)
FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src
COPY backend ./backend

# psycopg[binary] vendors its own libpq, so no apt-get needed for the Postgres driver.
RUN pip install --no-cache-dir ".[web]"

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

# `python -m uvicorn`, not the bare `uvicorn` entry point -- `-m` is what puts
# /app on sys.path so `backend.app.main` resolves (backend/ isn't part of the
# installed package; only src/fantasy_agent is, per pyproject.toml's
# packages-find `where = ["src"]`).
CMD ["python", "-m", "uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]

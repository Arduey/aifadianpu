"""Gunicorn config for FastAPI (ASGI).

Start:
    gunicorn main:app -c gunicorn_conf.py

BaoTa Python manager:
    start mode = "command line"
    start command = gunicorn main:app -c gunicorn_conf.py

Why not -k uvicorn.workers.UvicornWorker:
    That module was removed in uvicorn 0.34+. This project uses the
    standalone package `uvicorn-worker` (worker class
    `uvicorn_worker.UvicornWorker`). See requirements.txt.

Env overrides:
    GUNICORN_BIND=0.0.0.0:8000     (default) listen address
    GUNICORN_WORKERS=4             worker count
    GUNICORN_LOGLEVEL=info

NOTE: this file is intentionally ASCII-only. Chinese comments and
box-drawing characters got truncated by some FTP clients; keep it ASCII.
"""
import os

# ---- bind address ----
# 0.0.0.0:8000 -> listen on all interfaces (direct or behind nginx).
# Use GUNICORN_BIND=127.0.0.1:8000 to restrict to localhost only.
bind = os.getenv("GUNICORN_BIND", "0.0.0.0:8000")

# ---- workers ----
# Memory-first default: each worker is a full Python process holding its own
# copy of FastAPI/SQLAlchemy/curl_cffi, roughly 90-110 MB RSS. The old
# "2*cpu+1 capped at 8" default costs ~800 MB on a 4-core box and buys nothing
# for a single-shop site. Default to 2 workers; raise via GUNICORN_WORKERS.
workers = int(os.getenv("GUNICORN_WORKERS") or 2)

# ---- worker class: ASGI (FastAPI) ----
# needs `pip install uvicorn-worker` (already in requirements.txt)
worker_class = "uvicorn_worker.UvicornWorker"

# ---- timeouts ----
# SMTP / afdian calls can take tens of seconds; do not set too low.
timeout = 120
graceful_timeout = 30
keepalive = 5

# ---- logging ----
accesslog = "-"
errorlog = "-"
loglevel = os.getenv("GUNICORN_LOGLEVEL", "info")
access_log_format = '%({x-forwarded-for}i)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s"'

# ---- process name ----
proc_name = "afd-store"

# ---- preload ----
# True: master imports the app once, then forks workers that share its
# read-only pages (copy-on-write), saving ~30-40% RSS per extra worker.
# Safe here: init_db() runs in the ASGI lifespan startup event, which every
# worker fires on its own -- preloading does NOT make it run only in master.
# The DB engine is created lazily (no connection at import time), so forking
# does not inherit live sockets.
preload_app = True

# ---- graceful reload ----
# `kill -HUP <master pid>` reloads workers without downtime.
max_requests = 0
max_requests_jitter = 0


def on_starting(server):
    server.log.info(
        "gunicorn starting: bind=%s workers=%s worker_class=%s",
        bind, workers, worker_class,
    )


def worker_int(worker):
    worker.log.info("worker %s got SIGINT", worker.pid)


def worker_abort(worker):
    worker.log.warning("worker %s aborted after timeout=%ss", worker.pid, timeout)

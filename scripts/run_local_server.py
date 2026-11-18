#!/usr/bin/env python3
"""
scripts/run_local_server.py — Zero-Dependency Full-Stack Local Server (Port 5173)

Serves both:
1. Live Backend API endpoints (/api/jobs, /api/filters, /api/status, /api/metrics/cost, /api/refresh, /healthz)
   backed directly by test_live.db (or DATABASE_URL) using backend/app/api/queries.py
2. The Frontend UI from frontend/

Requires zero third-party packages on the host Mac (uses Python's built-in http.server + urllib.parse).
"""

import os
import sys
import json
import mimetypes
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from datetime import datetime, timezone

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BACKEND_DIR = os.path.join(ROOT_DIR, "backend")
FRONTEND_DIR = os.path.join(ROOT_DIR, "frontend")
sys.path.insert(0, BACKEND_DIR)

from app.db import Database
from app.api.queries import search_jobs, get_filter_options, get_status_summary, get_cost_metrics
from app.pipeline import run_pipeline

DB_FILE = os.path.join(ROOT_DIR, "test_live.db")
db = Database(os.environ.get("DATABASE_URL") or f"sqlite:///{DB_FILE}")
db.init_db(os.path.join(BACKEND_DIR, "app", "schema.sql"))


class LocalFullStackHandler(BaseHTTPRequestHandler):
    def _send_json(self, payload: dict, status: int = 200) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        qs = {k: v[0] for k, v in parse_qs(parsed.query).items() if v}

        if path == "/healthz":
            return self._send_json({
                "status": "ok",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "database": "sqlite" if db.is_sqlite else "postgres"
            })

        if path == "/api/jobs":
            res = search_jobs(
                db=db,
                q=qs.get("q"),
                city=qs.get("city"),
                role=qs.get("role"),
                job_type=qs.get("job_type"),
                workplace=qs.get("workplace"),
                source=qs.get("source"),
                posted_within=qs.get("posted_within"),
                page=int(qs.get("page", 1)),
                limit=int(qs.get("limit", 12)),
                sort_by=qs.get("sort_by", "newest")
            )
            return self._send_json(res)

        if path == "/api/filters":
            return self._send_json(get_filter_options(db))

        if path == "/api/status":
            return self._send_json(get_status_summary(db))

        if path == "/api/metrics/cost":
            return self._send_json(get_cost_metrics(db))

        # Serve static files from frontend/
        rel_path = path.lstrip("/") or "index.html"
        target = os.path.realpath(os.path.join(FRONTEND_DIR, rel_path))
        if not target.startswith(FRONTEND_DIR) or not os.path.isfile(target):
            target = os.path.join(FRONTEND_DIR, "index.html")

        ctype, _ = mimetypes.guess_type(target)
        with open(target, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype or "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/refresh":
            stats = run_pipeline(db)
            return self._send_json({
                "status": stats.status,
                "total_fetched": stats.total_fetched,
                "new_posts": stats.new_posts,
                "duplicates_skipped": stats.duplicates_skipped,
                "tagged_count": stats.tagged_count,
                "sources_summary": stats.sources_summary
            })
        self._send_json({"error": "Not found"}, status=404)


if __name__ == "__main__":
    port = int(os.environ.get("LOCAL_PORT", "5173"))
    server = ThreadingHTTPServer(("0.0.0.0", port), LocalFullStackHandler)
    print(f"Beep Job Hub Live Full-Stack Server running on http://localhost:{port}")
    server.serve_forever()

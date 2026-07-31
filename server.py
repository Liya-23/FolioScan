# .\backend\server.py
from __future__ import annotations

import json
import threading
import traceback
import uuid
from datetime import datetime, UTC
from pathlib import Path

import tornado.ioloop
import tornado.escape
import tornado.web

# ── Import your existing processor ───────────────────────────────────────────
# Supports two layouts:
#   Layout A (flat):   scanner/core.py   → our generated module
#   Layout B (yours):  backend/processor.py → your local module
#
# We try both so the server works regardless of which structure you have.
try:
    from scanner.core import run_scan, resolve_threshold

    _MODE = "scanner"
except ImportError:
    try:
        import sys, os

        # Make sure backend/ is importable whether we're run from root or backend/
        _here = Path(__file__).resolve().parent
        _root = _here.parent if _here.name == "backend" else _here
        sys.path.insert(0, str(_root))
        sys.path.insert(0, str(_root / "backend"))
        from processor import process_folder as _process_folder

        _MODE = "processor"
    except ImportError as e:
        raise ImportError(
            "Could not import scanner module.\n"
            "Make sure either:\n"
            "  • scanner/core.py exists (generated project), or\n"
            "  • backend/processor.py exists (your local project)\n"
            f"Original error: {e}"
        )

from openpyxl import load_workbook
from openpyxl.styles import Font

ROOT = Path(__file__).resolve().parent
FRONTEND_DIR = ROOT / "frontend"
JOBS: dict[str, dict] = {}


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")


def add_log(job: dict, message: str) -> None:
    job["logs"].append(f"[{utc_now()}] {message}")


# ── Adapter: wraps backend/processor.process_folder into the job pattern ─────


def _run_with_processor(job_id: str, root: Path, output_dir: Path, threshold):
    """
    Runs process_folder (from backend/processor.py) in a thread,
    writing logs and file results into JOBS[job_id].
    """
    job = JOBS[job_id]
    try:
        add_log(job, f"[INFO] Starting scan: {root}")
        add_log(job, f"[INFO] Filter: {job['threshold']}")
        add_log(job, f"[INFO] Output: {output_dir}")

        # process_folder is expected to return a list of output file paths
        # or yield progress. Adjust the call signature to match your processor.
        result = _process_folder(
            folder_path=str(root),
        )

        # If process_folder returns a list of saved paths
        if isinstance(result, (list, tuple)):
            for path in result:
                p = Path(path)
                job["files"].append({"name": p.name})
                add_log(job, f"[INFO] Saved: {p.name}")
            job["stats"] = {"saved": len(result), "total": len(result), "skipped": 0}
        else:
            add_log(job, "[INFO] Scan complete.")
            job["stats"] = {"saved": 0, "total": 0, "skipped": 0}

        add_log(job, "[DONE] Finished.")
        job["status"] = "done"

    except Exception:
        tb = traceback.format_exc()
        add_log(job, f"[ERROR] {tb}")
        job["status"] = "error"


def _run_with_scanner(job_id: str, root: Path, output_dir: Path, threshold):
    """
    Runs scanner/core.run_scan (generated module) in a thread.
    """
    job = JOBS[job_id]
    try:
        log_name = f"scan_{datetime.now().strftime('%d%m%Y_%H%M%S')}.log"
        log_path = output_dir / log_name
        job["log_file"] = log_name

        for event in run_scan(root, output_dir, threshold, log_path):
            if event["type"] == "log":
                job["logs"].append(event["msg"])
            elif event["type"] == "file":
                job["files"].append({"name": event["name"]})
            elif event["type"] == "done":
                job["stats"] = {
                    "saved": event["saved"],
                    "total": event["total"],
                    "skipped": event["skipped"],
                }
        job["status"] = "done"

    except Exception:
        tb = traceback.format_exc()
        job["logs"].append(f"[ERROR] {tb}")
        job["status"] = "error"


def _start_scan_thread(job_id: str, root: Path, output_dir: Path, threshold):
    """Pick the right runner based on which module was imported."""
    fn = _run_with_scanner if _MODE == "scanner" else _run_with_processor
    t = threading.Thread(
        target=fn, args=(job_id, root, output_dir, threshold), daemon=True
    )
    t.start()


def _resolve_threshold(preset: str, custom_date: str | None):
    """Resolve a preset string or custom date to a datetime (or None for all)."""
    if _MODE == "scanner":
        return resolve_threshold(preset, custom_date)

    # Fallback resolver for the processor mode
    from datetime import timedelta

    PRESETS = {"1d": 1, "2d": 2, "7d": 7, "30d": 30}
    if preset == "all":
        return None
    if preset == "custom" and custom_date:
        for fmt in ("%d-%m-%Y %H:%M", "%d-%m-%Y"):
            try:
                return datetime.strptime(custom_date, fmt)
            except ValueError:
                continue
        raise ValueError(f"Cannot parse date: {custom_date!r}")
    days = PRESETS.get(preset)
    if days:
        return datetime.now() - timedelta(days=days)
    raise ValueError(f"Unknown preset: {preset!r}")


# ── Handlers ──────────────────────────────────────────────────────────────────


class BaseHandler(tornado.web.RequestHandler):
    def set_default_headers(self) -> None:
        self.set_header("Content-Type", "application/json")
        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.set_header("Access-Control-Allow-Headers", "Content-Type")

    def options(self, *args):
        self.set_status(204)
        self.finish()


class HealthHandler(BaseHandler):
    def get(self) -> None:
        self.set_header("Content-Type", "application/json")
        self.write({"status": "ok"})


class MainHandler(tornado.web.RequestHandler):
    def get(self):
        index = FRONTEND_DIR / "index.html"
        if index.exists():
            self.set_header("Content-Type", "text/html")
            self.write(index.read_bytes())
        else:
            self.write("<h2>FolioScan API running. No frontend/index.html found.</h2>")


class ScanHandler(BaseHandler):
    async def post(self):
        try:
            body = json.loads(self.request.body)
            root_path = body.get("folder_path", "").strip()
            preset = body.get("preset", "1d")
            custom = body.get("custom_date", "")

            if not root_path:
                self.set_status(400)
                self.write({"error": "root_path is required"})
                return

            root = Path(root_path)
            if not root.exists():
                self.set_status(400)
                self.write({"error": f"Path does not exist: {root_path}"})
                return

            threshold = _resolve_threshold(preset, custom or None)
            job_id = uuid.uuid4().hex
            output_dir = Path("outputs") / job_id
            output_dir.mkdir(parents=True, exist_ok=True)

            JOBS[job_id] = {
                "status": "running",
                "root": str(root),
                "threshold": (
                    threshold.strftime("%d-%m-%Y %H:%M") if threshold else "All files"
                ),
                "output_dir": str(output_dir),
                "log_file": "",
                "logs": [],
                "files": [],
                "stats": {},
                "started": datetime.now().strftime("%d-%m-%Y %H:%M:%S"),
            }

            _start_scan_thread(job_id, root, output_dir, threshold)
            self.write({"job_id": job_id})

        except ValueError as e:
            self.set_status(400)
            self.write({"error": str(e)})
        except Exception as e:
            self.set_status(500)
            self.write({"error": str(e)})


class JobStatusHandler(BaseHandler):
    def get(self, job_id):
        job = JOBS.get(job_id)
        if not job:
            self.set_status(404)
            self.write({"error": "Job not found"})
            return
        self.write(job)


class JobStreamHandler(tornado.web.RequestHandler):
    """SSE — streams log lines and file events as they arrive."""

    async def get(self, job_id):
        self.set_header("Content-Type", "text/event-stream")
        self.set_header("Cache-Control", "no-cache")
        self.set_header("X-Accel-Buffering", "no")
        self.set_header("Access-Control-Allow-Origin", "*")

        sent_logs = 0
        sent_files = 0

        import asyncio

        while True:
            job = JOBS.get(job_id)
            if not job:
                self.write('data: {"error": "job not found"}\n\n')
                await self.flush()
                break

            # Stream new log lines
            logs = job["logs"]
            while sent_logs < len(logs):
                self.write(f"data: {json.dumps({'log': logs[sent_logs]})}\n\n")
                sent_logs += 1

            # Stream new file events (one per saved xlsx)
            files = job["files"]
            while sent_files < len(files):
                self.write(f"data: {json.dumps({'file': files[sent_files]})}\n\n")
                sent_files += 1

            await self.flush()

            if job["status"] != "running":
                # Send done with stats only — files were already sent above
                self.write(
                    f"data: {json.dumps({'done': True, 'stats': job['stats']})}\n\n"
                )
                await self.flush()
                break

            await asyncio.sleep(0.25)


class DownloadHandler(tornado.web.RequestHandler):
    def get(self, job_id, filename):
        job = JOBS.get(job_id)
        if not job:
            self.set_status(404)
            return
        file_path = Path(job["output_dir"]) / filename
        if not file_path.exists() or file_path.suffix != ".xlsx":
            self.set_status(404)
            return
        self.set_header(
            "Content-Type",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self.set_header("Content-Disposition", f'attachment; filename="{filename}"')
        with open(file_path, "rb") as f:
            self.write(f.read())


class LogDownloadHandler(tornado.web.RequestHandler):
    def get(self, job_id):
        job = JOBS.get(job_id)
        if not job:
            self.set_status(404)
            return
        log_path = Path(job["output_dir"]) / job.get("log_file", "")
        if not log_path.exists():
            self.set_status(404)
            return
        self.set_header("Content-Type", "text/plain; charset=utf-8")
        self.set_header(
            "Content-Disposition", f'attachment; filename="{log_path.name}"'
        )
        self.write(log_path.read_bytes())


class JobListHandler(BaseHandler):
    def get(self):
        jobs = [
            {
                "job_id": jid,
                "status": j["status"],
                "root": j["root"],
                "started": j["started"],
                "files_count": len(j["files"]),
                "threshold": j["threshold"],
            }
            for jid, j in reversed(list(JOBS.items()))
        ]
        self.write({"jobs": jobs})


# ── App factory ───────────────────────────────────────────────────────────────


def make_app():
    return tornado.web.Application(
        [
            (r"/", MainHandler),
            (r"/api/scan", ScanHandler),
            (r"/api/jobs", JobListHandler),
            (r"/api/job/([a-f0-9]+)", JobStatusHandler),
            (r"/api/stream/([a-f0-9]+)", JobStreamHandler),
            (r"/api/download/([a-f0-9]+)/(.+)", DownloadHandler),
            (r"/api/log/([a-f0-9]+)", LogDownloadHandler),
            (r"/health", HealthHandler),
            # Serve frontend static files
            (
                r"/static/(.*)",
                tornado.web.StaticFileHandler,
                {"path": str(FRONTEND_DIR)},
            ),
        ],
        debug=True,
    )


if __name__ == "__main__":
    import sys

    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8888
    Path("outputs").mkdir(exist_ok=True)
    app = make_app()
    app.listen(port)
    print(f"        ")
    print(f"╔══════════════════════════════════════════╗")
    print(f"║   FolioScan running on port {port}         ║")
    print(f"║   http://localhost:{port}                 ║")
    print(f"║   Mode: {_MODE:<33}║")
    print(f"╚══════════════════════════════════════════╝")
    tornado.ioloop.IOLoop.current().start()

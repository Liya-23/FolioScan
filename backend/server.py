# .\backend\server.py 

from __future__ import annotations

import json
import threading
import traceback
import uuid
from datetime import datetime
from pathlib import Path

import tornado.ioloop
import tornado.escape
import tornado.web

from processor import process_folder

from openpyxl import load_workbook
from openpyxl.styles import Font

ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = ROOT / "frontend"
JOBS: dict[str, dict] = {}


def utc_now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def add_log(job: dict, message: str) -> None:
    job["logs"].append(f"[{utc_now()}] {message}")


class BaseHandler(tornado.web.RequestHandler):
    def set_default_headers(self) -> None:
        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header("Access-Control-Allow-Headers", "Content-Type")
        self.set_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")

    def options(self, *args, **kwargs) -> None:
        self.set_status(204)
        self.finish()

    def write_json(self, payload: dict, status: int = 200) -> None:
        self.set_status(status)
        self.set_header("Content-Type", "application/json")
        self.write(json.dumps(payload))


class MainHandler(tornado.web.RequestHandler):
    def get(self) -> None:
        self.render(str(FRONTEND_DIR / "index.html"))

class HealthHandler(BaseHandler):
    def get(self) -> None:
        self.write_json({"status": "ok"})

class ScanHandler(BaseHandler):
    def post(self) -> None:
        try:
            payload = json.loads(self.request.body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self.write_json({"error": "Invalid JSON body."}, 400)
            return

        folder_path = str(payload.get("folder_path") or payload.get("file_path") or "").strip()
        if not folder_path:
            self.write_json({"error": "folder_path is required."}, 400)
            return

        source = Path(folder_path).expanduser()
        if not source.exists():
            self.write_json({"error": f"Folder not found: {folder_path}"}, 400)
            return
        if not source.is_dir():
            self.write_json({"error": f"Path must be a folder: {folder_path}"}, 400)
            return

        job_id = uuid.uuid4().hex[:12]
        JOBS[job_id] = {
            "id": job_id,
            "status": "running",
            "logs": [],
            "files": [],
            "stats": {"total": 0, "saved": 0, "skipped": 0},
            "error": None,
            "created_at": utc_now(),
        }

        add_log(JOBS[job_id], "Scanning started.")
        thread = threading.Thread(target=run_job, args=(job_id, folder_path), daemon=True)
        thread.start()

        self.write_json({"job_id": job_id})


class JobHandler(BaseHandler):
    def get(self, job_id: str) -> None:
        job = JOBS.get(job_id)
        if not job:
            self.write_json({"error": "Job not found."}, 404)
            return
        self.write_json(job)


class DownloadHandler(BaseHandler):
    def get(self) -> None:
        requested_path = self.get_query_argument("path", "")
        path = Path(requested_path)

        if not requested_path or not path.exists() or path.suffix.lower() not in {".xlsx", ".xls", ".xlsm"}:
            raise tornado.web.HTTPError(404)

        self.set_header("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.set_header("Content-Disposition", f'attachment; filename="{path.name}"')
        with path.open("rb") as file:
            self.write(file.read())


def run_job(job_id: str, folder_path: str) -> None:
    job = JOBS[job_id]

    def log(message: str) -> None:
        add_log(job, message)

    try:
        result = process_folder(folder_path, log=log)
        output_path = result["output_path"]
        job["status"] = "done"
        job["files"] = [
            {
                "name": Path(output_path).name,
                "path": output_path,
                "download_url": f"/download?path={tornado.escape.url_escape(output_path)}",
            }
        ]
        job["stats"] = {
            "total": result["total"],
            "saved": result["saved"],
            "skipped": result["skipped"],
        }
        log("[DONE] Completed successfully.")
    except Exception as exc:
        job["status"] = "error"
        job["error"] = str(exc)
        log(f"[ERROR] {exc}")
        log(traceback.format_exc())


def make_app() -> tornado.web.Application:
    return tornado.web.Application(
        [
            (r"/", MainHandler),
            (r"/health", HealthHandler),
            (r"/api/scan", ScanHandler),
            (r"/api/job/([A-Za-z0-9]+)", JobHandler),
            (r"/download", DownloadHandler),
            (
                r"/static/(.*)",
                tornado.web.StaticFileHandler,
                {"path": str(FRONTEND_DIR)},
            ),
        ],
        debug=True,
    )


if __name__ == "__main__":
    app = make_app()
    app.listen(2040)
    print("FolioScan running at http://localhost:2040")
    tornado.ioloop.IOLoop.current().start()

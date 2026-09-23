"""FastAPI application.

    >> uvicorn src.ui.app:app --reload

Pages:
  GET  /                  -> upload form + list of past runs
  POST /upload            -> kicks off pipeline in a background thread
  GET  /run/{run_id}      -> live run view (auto-refreshes while running)
  GET  /run/{run_id}/dashboard  -> serves the run's dashboard.html
  GET  /run/{run_id}/report     -> serves the run's report.html
  GET  /api/run/{run_id}  -> JSON status (for polling)
"""
from __future__ import annotations

import os
import shutil
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..pipeline import run_pipeline


load_dotenv()

ARTIFACT_ROOT = Path(os.getenv("ARTIFACT_ROOT", "./runs")).resolve()
UPLOAD_DIR = ARTIFACT_ROOT / "_uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(BASE_DIR / "templates"))

app = FastAPI(title="MCP-Powered BI Ecosystem")

# Serve static CSS.
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


# In-memory run registry. For a long-running deployment this would be a
# real store, but for the project scope an in-process dict is fine.
RUNS: dict[str, dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _list_past_runs() -> list[dict[str, Any]]:
    if not ARTIFACT_ROOT.exists():
        return []
    out = []
    for d in sorted(ARTIFACT_ROOT.iterdir(), reverse=True):
        if not d.is_dir() or d.name.startswith("_"):
            continue
        report = d / "report.html"
        dashboard = d / "dashboard.html"
        out.append({
            "run_id": d.name,
            "created_at": datetime.fromtimestamp(d.stat().st_mtime, timezone.utc).isoformat(),
            "has_report": report.exists(),
            "has_dashboard": dashboard.exists(),
        })
    return out[:50]


def _launch_pipeline(run_token: str, dataset_path: Path) -> None:
    """Run the pipeline in a background thread, writing progress into RUNS."""
    entry = RUNS[run_token]

    def cb(stage: str, status: str, payload: dict[str, Any]) -> None:
        entry["progress"].append({
            "ts": datetime.now(timezone.utc).isoformat(),
            "stage": stage,
            "status": status,
            "payload": payload,
        })
        if stage == "run" and status == "started":
            entry["run_id"] = payload.get("run_id")

    try:
        result = run_pipeline(
            dataset_path=dataset_path,
            config_path=os.getenv("BI_CONFIG", "./config.yaml"),
            artifact_root=ARTIFACT_ROOT,
            progress_cb=cb,
        )
        entry["status"] = "completed" if result.ok else "failed"
        entry["error"] = result.error
        entry["artifacts"] = result.artifacts
        entry["agent_outputs"] = result.agent_outputs
        entry["run_id"] = result.run_id
    except Exception as e:
        entry["status"] = "failed"
        entry["error"] = f"{type(e).__name__}: {e}"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    provider = os.getenv("LLM_PROVIDER", "groq")
    model = (
        os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
        if provider == "groq"
        else os.getenv("OLLAMA_MODEL", "llama3.1:8b")
    )
    return TEMPLATES.TemplateResponse(
        request,
        "index.html",
        {
            "past_runs": _list_past_runs(),
            "provider": provider,
            "model": model,
        },
    )


@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(400, "No filename")
    suffix = Path(file.filename).suffix.lower()
    if suffix not in (".csv", ".xlsx", ".xls", ".json", ".tsv", ".txt"):
        raise HTTPException(400, f"Unsupported file type: {suffix}")

    # Save upload to a stable path.
    upload_id = uuid.uuid4().hex[:10]
    safe_name = f"{upload_id}__{Path(file.filename).name}"
    target = UPLOAD_DIR / safe_name
    with target.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    # Register a run token and start pipeline thread.
    run_token = uuid.uuid4().hex[:12]
    RUNS[run_token] = {
        "run_token": run_token,
        "run_id": None,  # filled in by callback once it's known
        "status": "running",
        "progress": [],
        "artifacts": {},
        "agent_outputs": [],
        "error": None,
        "source_path": str(target),
        "source_name": file.filename,
    }
    t = threading.Thread(target=_launch_pipeline, args=(run_token, target), daemon=True)
    t.start()

    return RedirectResponse(url=f"/run/{run_token}", status_code=303)


@app.get("/run/{run_token}", response_class=HTMLResponse)
def run_view(request: Request, run_token: str):
    entry = RUNS.get(run_token)
    if not entry:
        raise HTTPException(404, "Unknown run token")
    return TEMPLATES.TemplateResponse(request, "run.html", {"entry": entry})


@app.get("/api/run/{run_token}")
def run_api(run_token: str):
    entry = RUNS.get(run_token)
    if not entry:
        raise HTTPException(404, "Unknown run token")
    # Derive run-level usage total + findings validation from the
    # progress events (the pipeline emits them on the final "run" event).
    usage_total = None
    findings_validation = None
    for ev in entry["progress"]:
        if ev.get("stage") == "run" and ev.get("payload"):
            usage_total = ev["payload"].get("usage_total", usage_total)
            findings_validation = ev["payload"].get("findings_validation", findings_validation)

    # Return a compact view suitable for polling.
    return JSONResponse({
        "status": entry["status"],
        "run_id": entry["run_id"],
        "error": entry["error"],
        "progress": entry["progress"],
        "artifacts": entry["artifacts"],
        "usage_total": usage_total,
        "findings_validation": findings_validation,
        "agent_outputs": [
            {
                "stage": a["stage"],
                "steps": a["steps"],
                "final_text": a["final_text"],
                "nudges_used": a.get("nudges_used", 0),
                "usage": a.get("usage"),
            }
            for a in entry["agent_outputs"]
        ],
    })


def _resolve_run_dir(run_id: str) -> Path:
    """Permit lookup by either run_token (in RUNS) or actual run_id (on disk)."""
    # First: token in RUNS?
    entry = RUNS.get(run_id)
    if entry and entry.get("run_id"):
        d = ARTIFACT_ROOT / entry["run_id"]
        if d.exists():
            return d
    # Otherwise: direct match on disk.
    d = ARTIFACT_ROOT / run_id
    if d.exists():
        return d
    raise HTTPException(404, f"Run not found: {run_id}")


# Both the bare path and the .html path resolve to the same file. The
# .html alias matters because the report's "Open interactive dashboard →"
# link is `dashboard.html` (so the report still works when opened from
# disk), and browsers resolve that relative to /run/{id}/report.
@app.get("/run/{run_id}/dashboard")
@app.get("/run/{run_id}/dashboard.html")
def run_dashboard(run_id: str):
    d = _resolve_run_dir(run_id)
    f = d / "dashboard.html"
    if not f.exists():
        raise HTTPException(404, "dashboard.html not yet generated")
    return FileResponse(f, media_type="text/html")


@app.get("/run/{run_id}/report")
@app.get("/run/{run_id}/report.html")
def run_report(run_id: str):
    d = _resolve_run_dir(run_id)
    f = d / "report.html"
    if not f.exists():
        raise HTTPException(404, "report.html not yet generated")
    return FileResponse(f, media_type="text/html")


@app.get("/run/{run_id}/state")
@app.get("/run/{run_id}/state.json")
def run_state(run_id: str):
    d = _resolve_run_dir(run_id)
    f = d / "state.json"
    if not f.exists():
        raise HTTPException(404, "state.json not yet generated")
    return FileResponse(f, media_type="application/json")


@app.get("/run/{run_id}/report/download")
def run_report_download(run_id: str):
    """Force-download the report as a standalone HTML file.

    The report's 'Download HTML' button points to `report.html` via the
    `download` attribute, which works for most users; this route is a
    belt-and-braces backup that *always* triggers a download by
    returning Content-Disposition: attachment with a clean filename.
    """
    d = _resolve_run_dir(run_id)
    f = d / "report.html"
    if not f.exists():
        raise HTTPException(404, "report.html not yet generated")
    # Use the directory name (run_id) as a stable filename suffix.
    filename = f"BI_Report_{d.name}.html"
    return FileResponse(f, media_type="text/html", filename=filename)


@app.get("/healthz")
def healthz():
    return {"ok": True, "artifact_root": str(ARTIFACT_ROOT)}

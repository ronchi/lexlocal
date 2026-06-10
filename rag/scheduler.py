"""
Automatic-update scheduler for Access to Justice.

Jobs are persisted to data/scheduled_jobs.json and executed by a single
daemon thread that wakes up every 60 seconds.  Two job types are supported:

  reindex_kb       — incremental (or full) re-index of a knowledge base.
  cl_fetch_ingest  — CourtListener search → download → ingest into a KB.
                     The date window is computed dynamically at run time
                     ("opinions issued in the last N days") so the same
                     job definition stays correct indefinitely.
"""
from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Callable

# Lazy import of config to avoid circular-import issues at module load time.
def _cfg():
    from config import DATA_DIR, load_settings, load_registry, register_kb
    return DATA_DIR, load_settings, load_registry, register_kb


DAYS_OF_WEEK = [
    "Monday", "Tuesday", "Wednesday",
    "Thursday", "Friday", "Saturday", "Sunday",
]
_DAY_NUM = {d.lower(): i for i, d in enumerate(DAYS_OF_WEEK)}

# ---------------------------------------------------------------------------
# File paths (resolved lazily so we don't import config at module level)
# ---------------------------------------------------------------------------

def _jobs_file() -> Path:
    DATA_DIR, *_ = _cfg()
    return DATA_DIR / "scheduled_jobs.json"


def _sched_log() -> Path:
    DATA_DIR, *_ = _cfg()
    return DATA_DIR / "scheduler.log"


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def load_jobs() -> list[dict]:
    """Load all job definitions from disk."""
    p = _jobs_file()
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def save_jobs(jobs: list[dict]) -> None:
    """Persist job definitions to disk."""
    _jobs_file().write_text(
        json.dumps(jobs, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )


def add_job(job: dict) -> str:
    """Append *job* to the persisted list and return its generated ID."""
    jobs = load_jobs()
    job_id = str(uuid.uuid4())[:8]
    job["id"]          = job_id
    job["enabled"]     = True
    job["last_run"]    = None
    job["last_status"] = None
    job["created_at"]  = datetime.now().isoformat(timespec="seconds")
    jobs.append(job)
    save_jobs(jobs)
    return job_id


def remove_job(job_id: str) -> None:
    save_jobs([j for j in load_jobs() if j.get("id") != job_id])


def set_job_enabled(job_id: str, enabled: bool) -> None:
    jobs = load_jobs()
    for j in jobs:
        if j.get("id") == job_id:
            j["enabled"] = enabled
            break
    save_jobs(jobs)


def _update_status(job_id: str, status: str, ran_at: str) -> None:
    jobs = load_jobs()
    for j in jobs:
        if j.get("id") == job_id:
            j["last_run"]    = ran_at
            j["last_status"] = status
            break
    save_jobs(jobs)


# ---------------------------------------------------------------------------
# Schedule helpers
# ---------------------------------------------------------------------------

def next_run_str(job: dict) -> str:
    """Return a human-readable next-run time string for display."""
    nrt = _next_run_dt(job)
    if nrt is None:
        return "—"
    return nrt.strftime("%Y-%m-%d %H:%M")


def _next_run_dt(job: dict) -> datetime | None:
    sched     = job.get("schedule", {})
    stype     = sched.get("type", "daily")
    now       = datetime.now()
    last_str  = job.get("last_run") or job.get("created_at")

    if stype == "interval":
        hours = int(sched.get("hours", 24))
        if last_str:
            return datetime.fromisoformat(last_str) + timedelta(hours=hours)
        return now + timedelta(hours=hours)

    target_h = int(sched.get("hour", 0))
    target_m = int(sched.get("minute", 0))

    if stype == "daily":
        candidate = now.replace(
            hour=target_h, minute=target_m, second=0, microsecond=0
        )
        if candidate <= now:
            candidate += timedelta(days=1)
        return candidate

    if stype == "weekly":
        target_dow = _DAY_NUM.get(sched.get("day", "monday").lower(), 0)
        days_ahead = (target_dow - now.weekday()) % 7
        if days_ahead == 0:
            candidate = now.replace(
                hour=target_h, minute=target_m, second=0, microsecond=0
            )
            if candidate <= now:
                days_ahead = 7
        return (now + timedelta(days=days_ahead)).replace(
            hour=target_h, minute=target_m, second=0, microsecond=0
        )

    return None


def _is_due(job: dict) -> bool:
    """Return True if *job* should fire right now."""
    if not job.get("enabled", True):
        return False

    sched    = job.get("schedule", {})
    stype    = sched.get("type", "daily")
    now      = datetime.now()
    last_str = job.get("last_run")

    # ── Interval: fire when enough time has elapsed since last run ──────────
    if stype == "interval":
        hours = int(sched.get("hours", 24))
        ref   = last_str or job.get("created_at")
        if not ref:
            return True
        elapsed = (now - datetime.fromisoformat(ref)).total_seconds()
        return elapsed >= hours * 3600

    # ── Daily / Weekly: fire in a ±90-second window around the target time ──
    target_h = int(sched.get("hour", 0))
    target_m = int(sched.get("minute", 0))

    if stype == "weekly":
        target_dow = _DAY_NUM.get(sched.get("day", "monday").lower(), 0)
        if now.weekday() != target_dow:
            return False

    target   = now.replace(hour=target_h, minute=target_m, second=0, microsecond=0)
    in_window = abs((now - target).total_seconds()) <= 90

    if not in_window:
        return False

    # Don't fire again if we already ran within the last 50 minutes
    if last_str:
        since_last = (now - datetime.fromisoformat(last_str)).total_seconds()
        min_gap    = 50 * 60
        return since_last >= min_gap

    return True   # never run yet and we're in the window


# ---------------------------------------------------------------------------
# Logging helper
# ---------------------------------------------------------------------------

def _log(msg: str, cb: Callable[[str], None] | None = None) -> None:
    ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{ts}  {msg}"
    try:
        with _sched_log().open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    if cb:
        cb(msg)


# ---------------------------------------------------------------------------
# Job execution
# ---------------------------------------------------------------------------

def run_job(job: dict, cb: Callable[[str], None] | None = None) -> str:
    """
    Execute *job* synchronously.  Returns a short status string.
    Writes every log line to scheduler.log and optionally calls *cb* for
    live streaming to the UI.
    """
    jtype = job.get("type", "")
    name  = job.get("name", job.get("id", "?"))
    _log(f"=== Starting job '{name}'  (type={jtype}) ===", cb)

    try:
        if jtype == "reindex_kb":
            _exec_reindex(job, cb)
        elif jtype == "cl_fetch_ingest":
            _exec_cl_fetch(job, cb)
        else:
            _log(f"⚠ Unknown job type '{jtype}'.", cb)
            return "error: unknown type"
        _log(f"=== Job '{name}' completed successfully ===", cb)
        return "✓ ok"
    except Exception as exc:
        _log(f"=== Job '{name}' FAILED: {exc} ===", cb)
        return f"✗ {exc}"


def _exec_reindex(job: dict, cb: Callable | None) -> None:
    from rag.ingestion import ingest_folder
    DATA_DIR, load_settings, load_registry, register_kb = _cfg()

    kb_name = job.get("kb_name", "")
    if not kb_name:
        raise ValueError("No KB name specified in job definition.")

    registry = load_registry()
    if kb_name not in registry:
        raise ValueError(f"KB '{kb_name}' not found in registry.")

    folder     = registry[kb_name]["folder"]
    settings   = load_settings()
    force_full = bool(job.get("force_full", False))
    mode       = "full rebuild" if force_full else "incremental"
    _log(f"Re-indexing KB '{kb_name}' ({mode}) from {folder} …", cb)
    ingest_folder(
        kb_name, folder,
        settings["embed_model"], settings["ollama_base"],
        progress_cb=lambda m: _log(m, cb),
        force_full=force_full,
    )


def _exec_cl_fetch(job: dict, cb: Callable | None) -> None:
    from agents.courtlistener_agent import (
        search_opinions, download_opinions, make_checkbox_choices,
    )
    from rag.ingestion import ingest_folder
    DATA_DIR, load_settings, load_registry, register_kb = _cfg()

    settings  = load_settings()
    token     = settings.get("cl_api_token", "")
    params    = job.get("cl_params", {})

    query      = params.get("query", "")
    court      = params.get("court", "")
    semantic   = bool(params.get("semantic", False))
    page_size  = int(params.get("page_size", 50))
    lookback   = int(params.get("lookback_days", 7))

    # Dynamic date window: last N days as of today
    today        = date.today()
    filed_after  = str(today - timedelta(days=lookback))
    filed_before = str(today)

    _log(
        f"CourtListener search: query={query!r}  court={court!r}  "
        f"issued {filed_after} → {filed_before}  "
        f"max={page_size}",
        cb,
    )

    data    = search_opinions(
        query, token, semantic, court,
        filed_after, filed_before, page_size,
    )
    results = data.get("results", [])
    _log(f"Search returned {len(results)} opinion(s).", cb)

    if not results:
        _log("Nothing new to download.", cb)
        return

    selected  = make_checkbox_choices(results)   # select all
    kb_name   = job.get("kb_name", "")
    registry  = load_registry()

    if kb_name and kb_name in registry:
        kb_folder = registry[kb_name]["folder"]
        dest_path = Path(kb_folder) / "courtlistener"
    elif kb_name:
        kb_folder = str(DATA_DIR / "courtlistener_downloads" / kb_name)
        dest_path = Path(kb_folder)
        register_kb(kb_name, kb_folder)
    else:
        raise ValueError("No destination KB specified in job definition.")

    _log(f"Downloading {len(selected)} opinion(s) → {dest_path} …", cb)
    files = download_opinions(
        results, selected, dest_path, token,
        progress_cb=lambda m: _log(m, cb),
    )
    _log(f"Downloaded {len(files)} file(s).  Re-indexing KB '{kb_name}' …", cb)

    ingest_folder(
        kb_name, kb_folder,
        settings["embed_model"], settings["ollama_base"],
        progress_cb=lambda m: _log(m, cb),
        force_full=False,
    )


# ---------------------------------------------------------------------------
# Background scheduler thread
# ---------------------------------------------------------------------------

_thread: threading.Thread | None = None
_stop   = threading.Event()


def start() -> None:
    """Start the background scheduler daemon thread (idempotent)."""
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, daemon=True, name="auto-update-scheduler")
    _thread.start()


def stop() -> None:
    """Signal the scheduler thread to stop."""
    _stop.set()


def _loop() -> None:
    """Main scheduler loop — checks for due jobs every 60 seconds."""
    while not _stop.is_set():
        try:
            for job in load_jobs():
                if _is_due(job):
                    ran_at = datetime.now().isoformat(timespec="seconds")
                    status = run_job(job)
                    _update_status(job["id"], status, ran_at)
        except Exception as exc:
            try:
                _log(f"Scheduler loop error: {exc}")
            except Exception:
                pass
        _stop.wait(60)

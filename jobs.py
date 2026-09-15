"""Job catalogue lookup for /api/v1/job-applications (BACKEND_PLAN.md §3).

The frontend owns the job list, so the backend only keeps an allow-list of ids
(ACTIVE_JOB_IDS / CLOSED_JOB_IDS) and an optional id->title map (JOBS_JSON).
When ACTIVE_JOB_IDS is empty every positive integer is accepted and the
frontend-supplied title is used (option 3 fallback).
"""

import json
import logging
from typing import Literal

from config import settings

log = logging.getLogger("jobs")

JobStatus = Literal["active", "closed", "unknown"]


def _id_set(raw: str) -> set[int]:
    out: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            out.add(int(part))
    return out


def _titles() -> dict[int, str]:
    if not settings.jobs_json.strip():
        return {}
    try:
        data = json.loads(settings.jobs_json)
        return {int(k): str(v) for k, v in data.items()}
    except (ValueError, AttributeError):
        log.warning("JOBS_JSON is not a valid {id: title} object; ignoring")
        return {}


ACTIVE_IDS = _id_set(settings.active_job_ids)
CLOSED_IDS = _id_set(settings.closed_job_ids)
TITLES = _titles()


def lookup_job(job_id: int, fallback_title: str) -> tuple[JobStatus, str]:
    title = TITLES.get(job_id) or fallback_title or f"Job #{job_id}"
    if job_id in CLOSED_IDS:
        return "closed", title
    if ACTIVE_IDS and job_id not in ACTIVE_IDS:
        return "unknown", title
    return "active", title

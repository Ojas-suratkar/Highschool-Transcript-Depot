from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Any
import uuid


TERMINAL_JOB_STATUSES = {
    "completed",
    "completed_with_errors",
    "failed",
    "cancelled",
}


@dataclass
class ExtractionJobState:
    id: str
    folder_id: int
    institution_id: int
    folder_label: str
    program_name: str | None
    year_intake: str

    status: str = "queued"

    total_files: int = 0
    processed_files: int = 0
    skipped_files: int = 0
    failed_files: int = 0

    current_file: str | None = None
    details: list[dict[str, Any]] = field(default_factory=list)

    error: str | None = None

    started_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    finished_at: datetime | None = None


class ExtractionJobService:
    def __init__(self) -> None:
        self._jobs: dict[str, ExtractionJobState] = {}
        self._active_by_folder: dict[tuple[int, int], str] = {}
        self._lock = Lock()

    def create_or_get_active_job(
        self,
        *,
        folder_id: int,
        institution_id: int,
        folder_label: str,
        program_name: str | None,
        year_intake: str,
    ) -> tuple[dict[str, Any], bool]:
        key = (institution_id, folder_id)

        with self._lock:
            active_job_id = self._active_by_folder.get(key)

            if active_job_id and active_job_id in self._jobs:
                return self._serialize(self._jobs[active_job_id]), False

            job = ExtractionJobState(
                id=str(uuid.uuid4()),
                folder_id=folder_id,
                institution_id=institution_id,
                folder_label=folder_label,
                program_name=program_name,
                year_intake=year_intake,
            )

            self._jobs[job.id] = job
            self._active_by_folder[key] = job.id

            return self._serialize(job), True

    def get_job(
        self,
        job_id: str,
        institution_id: int,
    ) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)

            if not job:
                return None

            if job.institution_id != institution_id:
                return None

            return self._serialize(job)

    def get_active_jobs(
        self,
        institution_id: int,
    ) -> list[dict[str, Any]]:
        """
        Return currently active extraction jobs for this institution.

        This is read-only. It does not start, stop, cancel, or modify
        extraction jobs.

        It exists so the frontend can discover jobs that were created
        automatically by the backend after uploads finish.
        """
        with self._lock:
            active_jobs: list[dict[str, Any]] = []

            for (job_institution_id, _folder_id), job_id in (
                self._active_by_folder.items()
            ):
                if job_institution_id != institution_id:
                    continue

                job = self._jobs.get(job_id)

                if not job:
                    continue

                if job.status in TERMINAL_JOB_STATUSES:
                    continue

                active_jobs.append(self._serialize(job))

            active_jobs.sort(
                key=lambda job: job["started_at"],
                reverse=True,
            )

            return active_jobs

    def mark_started(
        self,
        job_id: str,
        total_files: int,
    ) -> None:
        with self._lock:
            job = self._jobs.get(job_id)

            if not job:
                return

            job.status = "running"
            job.total_files = max(total_files, 0)

            if total_files == 0:
                job.current_file = None

    def set_current_file(
        self,
        job_id: str,
        file_name: str | None,
    ) -> None:
        with self._lock:
            job = self._jobs.get(job_id)

            if not job:
                return

            job.current_file = file_name

    def record_result(
        self,
        job_id: str,
        outcome: str,
        detail: dict[str, Any],
    ) -> None:
        """
        outcome should be one of:
        - processed
        - skipped
        - failed

        Important:
        A transcript that goes to Needs Review is still a successfully
        processed file.

        So the caller should record it as outcome="processed" and put
        process_status="needs_review" inside detail.
        """

        with self._lock:
            job = self._jobs.get(job_id)

            if not job:
                return

            normalized_outcome = (outcome or "").strip().lower()

            if normalized_outcome == "processed":
                job.processed_files += 1

            elif normalized_outcome == "skipped":
                job.skipped_files += 1

            elif normalized_outcome == "failed":
                job.failed_files += 1

            else:
                detail = {
                    **detail,
                    "warning": f"Unknown job outcome: {outcome}",
                }

            job.details.append(detail)

    def finish_job(
        self,
        job_id: str,
        *,
        status: str | None = None,
        error: str | None = None,
    ) -> None:
        with self._lock:
            job = self._jobs.get(job_id)

            if not job:
                return

            if status:
                job.status = status

            elif job.failed_files > 0:
                job.status = "completed_with_errors"

            else:
                job.status = "completed"

            job.error = error
            job.current_file = None
            job.finished_at = datetime.now(timezone.utc)

            self._active_by_folder.pop(
                (job.institution_id, job.folder_id),
                None,
            )

    def cancel_job(
        self,
        job_id: str,
        institution_id: int,
        reason: str | None = None,
    ) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)

            if not job:
                return None

            if job.institution_id != institution_id:
                return None

            job.status = "cancelled"
            job.error = reason or "Cancelled by user"
            job.current_file = None
            job.finished_at = datetime.now(timezone.utc)

            self._active_by_folder.pop(
                (job.institution_id, job.folder_id),
                None,
            )

            return self._serialize(job)

    def _estimate_eta_seconds(
        self,
        job: ExtractionJobState,
        completed_files: int,
    ) -> int | None:
        """
        Estimate remaining time using the average time per completed file.

        Until at least one file finishes, return None instead of showing
        a fake ETA.
        """

        if job.status != "running":
            return None

        if job.total_files <= 0:
            return None

        if completed_files <= 0:
            return None

        remaining_files = job.total_files - completed_files

        if remaining_files <= 0:
            return 0

        elapsed_seconds = (
            datetime.now(timezone.utc) - job.started_at
        ).total_seconds()

        if elapsed_seconds <= 0:
            return None

        average_seconds_per_file = (
            elapsed_seconds / completed_files
        )

        estimated_seconds = (
            average_seconds_per_file * remaining_files
        )

        return max(0, int(round(estimated_seconds)))

    def _serialize(
        self,
        job: ExtractionJobState,
    ) -> dict[str, Any]:
        completed_files = (
            job.processed_files
            + job.skipped_files
            + job.failed_files
        )

        if job.status == "queued":
            percent_complete = 0

        elif job.status in TERMINAL_JOB_STATUSES:
            percent_complete = 100

        elif job.total_files > 0:
            percent_complete = int(
                (completed_files / job.total_files) * 100
            )

        else:
            percent_complete = 5

        eta_seconds = self._estimate_eta_seconds(
            job,
            completed_files,
        )

        return {
            "id": job.id,
            "folder_id": job.folder_id,
            "folder_label": job.folder_label,
            "program_name": job.program_name,
            "year_intake": job.year_intake,
            "status": job.status,
            "percent_complete": max(
                0,
                min(percent_complete, 100),
            ),
            "total_files": job.total_files,
            "processed_files": job.processed_files,
            "skipped_files": job.skipped_files,
            "failed_files": job.failed_files,
            "current_file": job.current_file,
            "details": list(job.details),
            "error": job.error,
            "started_at": job.started_at,
            "finished_at": job.finished_at,

            # Progress UI only.
            "eta_seconds": eta_seconds,
        }


extraction_job_service = ExtractionJobService()
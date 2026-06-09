from __future__ import annotations

from screen_translator.worker.base import (
    WorkerError,
    WorkerProgressCallback,
    WorkerSuccess,
    WorkerTask,
)


class InlineWorker:
    """Synchronous worker for tests and non-UI execution."""

    def __init__(self) -> None:
        self._busy = False
        self._cancelled = False

    def submit(
        self,
        job_id: int,
        task: WorkerTask,
        on_success: WorkerSuccess,
        on_error: WorkerError,
        on_progress: WorkerProgressCallback | None = None,
    ) -> bool:
        if self._busy:
            return False
        self._busy = True
        self._cancelled = False
        try:
            progress = (
                None
                if on_progress is None
                else lambda payload: on_progress(job_id, payload)
            )
            result = task(progress)
        except Exception as exc:
            if not self._cancelled:
                on_error(job_id, exc)
        else:
            if not self._cancelled:
                on_success(job_id, result)
        finally:
            self._busy = False
        return True

    def cancel(self) -> None:
        self._cancelled = True
        self._busy = False

"""Small, dependency-free progress messages for long CLI jobs."""

from __future__ import annotations

import time
from datetime import UTC, datetime


def _clock(seconds: float) -> str:
    total = max(0, round(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}"


def log_progress(task: str, message: str) -> None:
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"[{stamp}] {task}: {message}", flush=True)


class ProgressReporter:
    def __init__(
        self,
        task: str,
        total: int,
        *,
        unit: str = "items",
        initial_done: int = 0,
        interval_seconds: float = 30.0,
    ) -> None:
        if total < 0 or not 0 <= initial_done <= total:
            raise ValueError("progress total and initial count must be valid")
        self.task = task
        self.total = total
        self.unit = unit
        self.initial_done = initial_done
        self.interval_seconds = interval_seconds
        self.started = time.monotonic()
        self.last_report = self.started
        self.last_done = initial_done
        log_progress(task, f"started {initial_done}/{total} {unit}")

    def update(self, done: int, *, detail: str = "", force: bool = False) -> None:
        if not self.last_done <= done <= self.total:
            raise ValueError("progress count must increase and not exceed total")
        now = time.monotonic()
        if not force and done < self.total and now - self.last_report < self.interval_seconds:
            self.last_done = done
            return
        elapsed = now - self.started
        completed = done - self.initial_done
        rate = completed / elapsed if elapsed > 0 and completed > 0 else 0.0
        remaining = self.total - done
        eta = _clock(remaining / rate) if rate > 0 else "calculating"
        percent = 100.0 * done / self.total if self.total else 100.0
        message = (
            f"{done}/{self.total} {self.unit} ({percent:.1f}%) "
            f"elapsed={_clock(elapsed)} eta={eta} rate={rate:.2f}/{self.unit}/s"
        )
        if detail:
            message += f" {detail}"
        log_progress(self.task, message)
        self.last_report = now
        self.last_done = done

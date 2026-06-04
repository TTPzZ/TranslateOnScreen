from __future__ import annotations

from enum import StrEnum


class ModeState(StrEnum):
    IDLE = "idle"
    SELECTING_REGION = "selecting_region"
    GAMING_READY = "gaming_ready"
    READING_RUNNING = "reading_running"
    ERROR = "error"

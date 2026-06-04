from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

_UTF8_SIGNATURE = b"\xef\xbb\xbf"


def default_log_path(project_root: Path | None = None) -> Path:
    root = project_root or Path.cwd()
    return root / "logs" / "screen_translator.log"


def configure_logging(
    *,
    log_path: Path | None = None,
    logger_name: str = "screen_translator",
    max_bytes: int = 1_000_000,
    backup_count: int = 3,
) -> logging.Logger:
    resolved_path = log_path or default_log_path()
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    _ensure_utf8_signature(resolved_path)

    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.DEBUG)
    logger.propagate = True

    for handler in list(logger.handlers):
        if isinstance(handler, RotatingFileHandler):
            logger.removeHandler(handler)
            handler.close()

    handler = RotatingFileHandler(
        resolved_path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
        delay=True,
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    logger.addHandler(handler)
    return logger


def _ensure_utf8_signature(path: Path) -> None:
    if not path.exists() or path.stat().st_size == 0:
        path.write_bytes(_UTF8_SIGNATURE)
        return

    data = path.read_bytes()
    if data.startswith(_UTF8_SIGNATURE):
        return
    path.write_bytes(_UTF8_SIGNATURE + data)

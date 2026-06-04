from __future__ import annotations

from logging.handlers import RotatingFileHandler
from pathlib import Path

from screen_translator.logging_config import configure_logging, default_log_path


def test_default_log_path_points_to_logs_directory() -> None:
    root = Path("D:/GIT/TranslateOnScreen")

    assert default_log_path(root) == root / "logs" / "screen_translator.log"


def test_configure_logging_adds_rotating_file_handler(tmp_path: Path) -> None:
    log_path = tmp_path / "logs" / "screen_translator.log"

    logger = configure_logging(log_path=log_path, logger_name="screen_translator.test_logging")

    handlers = [handler for handler in logger.handlers if isinstance(handler, RotatingFileHandler)]
    assert len(handlers) == 1
    assert Path(handlers[0].baseFilename) == log_path
    assert handlers[0].maxBytes <= 1_000_000
    assert handlers[0].backupCount >= 1


def test_configure_logging_writes_vietnamese_as_utf8_with_signature(tmp_path: Path) -> None:
    log_path = tmp_path / "logs" / "screen_translator.log"
    logger = configure_logging(
        log_path=log_path,
        logger_name="screen_translator.test_vietnamese_logging",
    )
    phrases = ["Xin chào thế giới", "Hoàn thành nhiệm vụ", "Mở cửa"]

    for phrase in phrases:
        logger.info("translation result=%s", phrase)
    for handler in logger.handlers:
        handler.flush()

    data = log_path.read_bytes()
    assert data.startswith(b"\xef\xbb\xbf")
    text = data.decode("utf-8-sig")
    for phrase in phrases:
        assert phrase in text
    assert "Xin chÃ" not in text
    assert "Má»" not in text

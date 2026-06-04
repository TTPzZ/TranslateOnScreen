from __future__ import annotations

from importlib import metadata as importlib_metadata
import importlib.util
import os
import platform
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

from screen_translator.config import AppConfig
from screen_translator.logging_config import configure_logging


@dataclass(frozen=True, slots=True)
class DiagnosticStatus:
    name: str
    ok: bool
    message: str


def dependency_status(module_name: str) -> DiagnosticStatus:
    if importlib.util.find_spec(module_name) is None:
        return DiagnosticStatus(module_name, False, "not installed")
    return DiagnosticStatus(module_name, True, "import available")


def package_version_status(package_name: str, label: str | None = None) -> DiagnosticStatus:
    display_name = label or package_name
    try:
        version = importlib_metadata.version(package_name)
    except importlib_metadata.PackageNotFoundError:
        return DiagnosticStatus(display_name, False, "not installed")
    except Exception as exc:
        return DiagnosticStatus(
            display_name,
            False,
            f"version check failed: {type(exc).__name__}: {exc}",
        )
    return DiagnosticStatus(display_name, True, version)


def paddle_runtime_version_statuses() -> list[DiagnosticStatus]:
    return [
        package_version_status("paddleocr", "PaddleOCR version"),
        package_version_status("paddlepaddle", "PaddlePaddle version"),
    ]


def googletrans_availability_status() -> DiagnosticStatus:
    status = package_version_status("deep-translator", "googletrans provider")
    if not status.ok:
        return status
    return DiagnosticStatus(
        "googletrans provider",
        True,
        f"deep-translator {status.message}",
    )


def python_version_status(version_info: tuple[int, int, int] | None = None) -> DiagnosticStatus:
    version = version_info or sys.version_info[:3]
    version_text = ".".join(str(part) for part in version[:3])
    if version < (3, 11, 0):
        return DiagnosticStatus(
            "python",
            False,
            f"{version_text} unsupported; use Python 3.11 or 3.12",
        )
    if version >= (3, 13, 0):
        return DiagnosticStatus(
            "python",
            False,
            f"{version_text} unsupported; Python 3.13+ is not supported. Use Python 3.11 or 3.12.",
        )
    return DiagnosticStatus("python", True, f"{version_text} supported")


def import_status(module_name: str, label: str | None = None) -> DiagnosticStatus:
    display_name = label or module_name
    try:
        __import__(module_name)
    except Exception as exc:
        return DiagnosticStatus(display_name, False, str(exc))
    return DiagnosticStatus(display_name, True, "import ok")


def check_env_presence(names: list[str]) -> list[DiagnosticStatus]:
    results: list[DiagnosticStatus] = []
    for name in names:
        if os.getenv(name):
            results.append(DiagnosticStatus(name, True, "set"))
        else:
            results.append(DiagnosticStatus(name, False, "missing"))
    return results


def translation_environment_statuses() -> list[DiagnosticStatus]:
    statuses = check_env_presence(["TRANSLATION_SERVER_URL", "TRANSLATION_PROVIDER"])
    if _google_credentials_required():
        statuses.extend(check_env_presence(["GOOGLE_APPLICATION_CREDENTIALS"]))
    else:
        message = "not required for configured providers"
        if _configured_translation_provider_names() == {"mock"}:
            message = "not required for mock provider"
        statuses.append(
            DiagnosticStatus(
                "GOOGLE_APPLICATION_CREDENTIALS",
                True,
                message,
            )
        )
    return statuses


def _google_credentials_required() -> bool:
    return "google" in _configured_translation_provider_names()


def _configured_translation_provider_names() -> set[str]:
    configured_provider = os.getenv("TRANSLATION_PROVIDER", "google")
    configured_providers = os.getenv("TRANSLATION_PROVIDERS", "google")
    return {
        name.strip().lower()
        for value in (configured_provider, configured_providers)
        for name in value.split(",")
        if name.strip()
    }


def check_sqlite_path(path: Path) -> DiagnosticStatus:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with sqlite3.connect(path) as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS diagnostic_write_check (id INTEGER)")
            connection.execute("DROP TABLE diagnostic_write_check")
    except Exception as exc:
        return DiagnosticStatus("sqlite_path", False, str(exc))
    return DiagnosticStatus("sqlite_path", True, str(path))


def collect_diagnostics(config: AppConfig | None = None) -> list[DiagnosticStatus]:
    runtime_config = config or AppConfig()
    return [
        python_version_status(),
        DiagnosticStatus("os", True, platform.platform()),
        dependency_status("PyQt6"),
        *paddle_runtime_version_statuses(),
        googletrans_availability_status(),
        import_status("screen_translator.server.main", "fastapi_app"),
        check_sqlite_path(runtime_config.cache_path),
        *translation_environment_statuses(),
    ]


def recommended_next_action(statuses: list[DiagnosticStatus]) -> str:
    if any(not status.ok for status in statuses):
        return "Fix failing diagnostics before running UI smoke tests."
    return "Run scripts/run_server.ps1, then scripts/run_control_panel.ps1."


def format_status(status: DiagnosticStatus) -> str:
    marker = "OK" if status.ok else "FAIL"
    return f"[{marker}] {status.name}: {status.message}"


def main() -> None:
    configure_logging()
    statuses = collect_diagnostics()
    for status in statuses:
        print(format_status(status))
    print("")
    print("Next action:", recommended_next_action(statuses))


if __name__ == "__main__":
    main()

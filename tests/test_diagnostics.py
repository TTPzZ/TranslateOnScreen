from __future__ import annotations

from pathlib import Path

from screen_translator.diagnostics import (
    DiagnosticStatus,
    check_env_presence,
    check_sqlite_path,
    dependency_status,
    python_version_status,
    recommended_next_action,
)


def test_check_env_presence_masks_secret_values(monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "C:/secret/service-account.json")
    monkeypatch.delenv("TRANSLATION_SERVER_URL", raising=False)

    results = check_env_presence(["GOOGLE_APPLICATION_CREDENTIALS", "TRANSLATION_SERVER_URL"])

    assert results == [
        DiagnosticStatus("GOOGLE_APPLICATION_CREDENTIALS", True, "set"),
        DiagnosticStatus("TRANSLATION_SERVER_URL", False, "missing"),
    ]


def test_translation_environment_statuses_do_not_require_google_for_mock(
    monkeypatch,
) -> None:
    from screen_translator import diagnostics

    monkeypatch.setenv("TRANSLATION_PROVIDER", "mock")
    monkeypatch.setenv("TRANSLATION_PROVIDERS", "mock")
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)

    assert diagnostics.translation_environment_statuses() == [
        DiagnosticStatus("TRANSLATION_SERVER_URL", False, "missing"),
        DiagnosticStatus("TRANSLATION_PROVIDER", True, "set"),
        DiagnosticStatus("GOOGLE_APPLICATION_CREDENTIALS", True, "not required for mock provider"),
    ]


def test_translation_environment_statuses_do_not_require_google_for_googletrans(
    monkeypatch,
) -> None:
    from screen_translator import diagnostics

    monkeypatch.setenv("TRANSLATION_PROVIDER", "googletrans")
    monkeypatch.setenv("TRANSLATION_PROVIDERS", "googletrans")
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)

    assert diagnostics.translation_environment_statuses() == [
        DiagnosticStatus("TRANSLATION_SERVER_URL", False, "missing"),
        DiagnosticStatus("TRANSLATION_PROVIDER", True, "set"),
        DiagnosticStatus(
            "GOOGLE_APPLICATION_CREDENTIALS",
            True,
            "not required for configured providers",
        ),
    ]


def test_translation_environment_statuses_require_google_for_google_provider(
    monkeypatch,
) -> None:
    from screen_translator import diagnostics

    monkeypatch.setenv("TRANSLATION_PROVIDER", "google")
    monkeypatch.setenv("TRANSLATION_PROVIDERS", "google")
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)

    assert diagnostics.translation_environment_statuses()[-1] == DiagnosticStatus(
        "GOOGLE_APPLICATION_CREDENTIALS",
        False,
        "missing",
    )


def test_dependency_status_reports_missing_module_without_raising() -> None:
    result = dependency_status("definitely_missing_translate_on_screen_module")

    assert result.name == "definitely_missing_translate_on_screen_module"
    assert result.ok is False
    assert "not installed" in result.message


def test_package_version_status_reports_installed_distribution(monkeypatch) -> None:
    from screen_translator import diagnostics

    def fake_version(package_name: str) -> str:
        assert package_name == "paddleocr"
        return "3.6.0"

    monkeypatch.setattr(diagnostics.importlib_metadata, "version", fake_version)

    assert diagnostics.package_version_status(
        "paddleocr",
        "PaddleOCR version",
    ) == DiagnosticStatus(
        "PaddleOCR version",
        True,
        "3.6.0",
    )


def test_package_version_status_reports_missing_distribution(monkeypatch) -> None:
    from importlib.metadata import PackageNotFoundError

    from screen_translator import diagnostics

    def fake_version(package_name: str) -> str:
        del package_name
        raise PackageNotFoundError

    monkeypatch.setattr(diagnostics.importlib_metadata, "version", fake_version)

    assert diagnostics.package_version_status(
        "paddleocr",
        "PaddleOCR version",
    ) == DiagnosticStatus(
        "PaddleOCR version",
        False,
        "not installed",
    )


def test_paddle_runtime_version_statuses_include_ocr_and_paddle(monkeypatch) -> None:
    from screen_translator import diagnostics

    versions = {
        "paddleocr": "3.6.0",
        "paddlepaddle": "3.3.1",
    }

    def fake_version(package_name: str) -> str:
        return versions[package_name]

    monkeypatch.setattr(diagnostics.importlib_metadata, "version", fake_version)

    assert diagnostics.paddle_runtime_version_statuses() == [
        DiagnosticStatus("PaddleOCR version", True, "3.6.0"),
        DiagnosticStatus("PaddlePaddle version", True, "3.3.1"),
    ]


def test_googletrans_availability_status_reports_deep_translator_version(
    monkeypatch,
) -> None:
    from screen_translator import diagnostics

    def fake_version(package_name: str) -> str:
        assert package_name == "deep-translator"
        return "1.11.4"

    monkeypatch.setattr(diagnostics.importlib_metadata, "version", fake_version)

    assert diagnostics.googletrans_availability_status() == DiagnosticStatus(
        "googletrans provider",
        True,
        "deep-translator 1.11.4",
    )


def test_python_version_status_warns_for_unsupported_versions() -> None:
    assert python_version_status((3, 11, 9)) == DiagnosticStatus(
        "python",
        True,
        "3.11.9 supported",
    )
    assert python_version_status((3, 12, 4)).ok is True

    result = python_version_status((3, 13, 0))

    assert result.ok is False
    assert "Python 3.13+ is not supported" in result.message
    assert "Python 3.11 or 3.12" in result.message


def test_check_sqlite_path_creates_parent_and_reports_writable(tmp_path: Path) -> None:
    db_path = tmp_path / "cache" / "translations.db"

    result = check_sqlite_path(db_path)

    assert result == DiagnosticStatus("sqlite_path", True, str(db_path))
    assert db_path.parent.exists()


def test_recommended_next_action_prioritizes_failures() -> None:
    assert recommended_next_action(
        [
            DiagnosticStatus("PyQt6", False, "not installed"),
            DiagnosticStatus("fastapi_app", True, "ok"),
        ]
    ) == "Fix failing diagnostics before running UI smoke tests."

    assert recommended_next_action([DiagnosticStatus("fastapi_app", True, "ok")]) == (
        "Run scripts/run_server.ps1, then scripts/run_control_panel.ps1."
    )

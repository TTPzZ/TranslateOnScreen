from __future__ import annotations

import os

import pytest

from screen_translator.ui.server_process import LocalServerController, LocalServerError


class FakeProcess:
    def __init__(self, returncode: int | None = None) -> None:
        self.returncode = returncode
        self.terminated = False
        self.wait_calls: list[float] = []
        self.killed = False

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 0

    def wait(self, timeout: float) -> int:
        self.wait_calls.append(timeout)
        return self.returncode or 0

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9


def test_local_server_controller_starts_mock_provider_with_current_python(monkeypatch) -> None:
    popen_calls: list[dict[str, object]] = []
    process = FakeProcess()

    def fake_popen(command, *, env, cwd, creationflags=0):
        popen_calls.append(
            {
                "command": command,
                "env": env,
                "cwd": cwd,
                "creationflags": creationflags,
            }
        )
        return process

    controller = LocalServerController(popen=fake_popen, python_executable="python-test")

    controller.start(provider="mock", server_url="http://127.0.0.1:8123")

    assert controller.status() == "running"
    assert popen_calls[0]["command"] == [
        "python-test",
        "-m",
        "uvicorn",
        "screen_translator.server.main:app",
        "--app-dir",
        "src",
        "--host",
        "127.0.0.1",
        "--port",
        "8123",
    ]
    env = popen_calls[0]["env"]
    assert env["TRANSLATION_PROVIDERS"] == "mock"
    assert env["TRANSLATION_PROVIDER"] == "mock"


def test_local_server_controller_supports_googletrans_provider() -> None:
    controller = LocalServerController(
        popen=lambda *args, **kwargs: FakeProcess(),
        python_executable="python-test",
    )

    controller.start(provider="googletrans", server_url="http://127.0.0.1:8000")

    assert controller.status() == "running"


def test_local_server_controller_rejects_google_cloud_provider_for_helper() -> None:
    controller = LocalServerController(
        popen=lambda *args, **kwargs: FakeProcess(),
        python_executable="python-test",
    )

    with pytest.raises(LocalServerError, match="mock and googletrans"):
        controller.start(provider="google", server_url="http://127.0.0.1:8000")


def test_local_server_controller_stops_running_process() -> None:
    process = FakeProcess()
    controller = LocalServerController(
        popen=lambda *args, **kwargs: process,
        python_executable="python-test",
    )
    controller.start(provider="mock", server_url="http://127.0.0.1:8000")

    controller.stop()

    assert process.terminated is True
    assert process.wait_calls == [5.0]
    assert controller.status() == "stopped"

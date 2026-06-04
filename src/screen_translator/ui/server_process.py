from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

LOCAL_SERVER_PROVIDERS = {"mock", "googletrans"}


class LocalServerError(RuntimeError):
    """Raised when the control panel cannot manage the local translation server."""


class LocalServerController:
    """Small subprocess wrapper for local mock/googletrans smoke-test servers."""

    def __init__(
        self,
        *,
        popen: Any = subprocess.Popen,
        python_executable: str | None = None,
        cwd: str | Path | None = None,
    ) -> None:
        self._popen = popen
        self._python_executable = python_executable or sys.executable
        self._cwd = Path(cwd) if cwd is not None else Path.cwd()
        self._process: Any | None = None

    def start(self, *, provider: str, server_url: str) -> None:
        normalized_provider = provider.strip().lower()
        if normalized_provider not in LOCAL_SERVER_PROVIDERS:
            raise LocalServerError("Local server helper supports mock and googletrans providers")
        if self._process is not None and self._process.poll() is None:
            return

        host, port = _host_port_from_url(server_url)
        env = os.environ.copy()
        env["TRANSLATION_PROVIDER"] = normalized_provider
        env["TRANSLATION_PROVIDERS"] = normalized_provider
        command = [
            self._python_executable,
            "-m",
            "uvicorn",
            "screen_translator.server.main:app",
            "--app-dir",
            "src",
            "--host",
            host,
            "--port",
            str(port),
        ]
        creationflags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self._process = self._popen(
            command,
            env=env,
            cwd=str(self._cwd),
            creationflags=creationflags,
        )

    def stop(self) -> None:
        if self._process is None:
            return
        if self._process.poll() is not None:
            self._process = None
            return
        self._process.terminate()
        try:
            self._process.wait(timeout=5.0)
        except Exception:
            self._process.kill()
        finally:
            self._process = None

    def status(self) -> str:
        if self._process is not None and self._process.poll() is None:
            return "running"
        return "stopped"


def _host_port_from_url(server_url: str) -> tuple[str, int]:
    parsed = urlparse(server_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 8000
    return host, port

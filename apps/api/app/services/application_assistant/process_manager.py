"""Process Manager — manages background Application Worker subprocess lifetime independently from FastAPI API/UI."""

from __future__ import annotations

import os
import subprocess
import time
from typing import Any


class ProcessManager:
    _instance: ProcessManager | None = None

    def __init__(self) -> None:
        self.worker_process: subprocess.Popen | None = None
        self.repair_worker_process: subprocess.Popen | None = None

    @classmethod
    def get_instance(cls) -> ProcessManager:
        if cls._instance is None:
            cls._instance = ProcessManager()
        return cls._instance

    def is_worker_running(self) -> bool:
        if self.worker_process is None:
            return False
        return self.worker_process.poll() is None

    def start_application_worker(self, env_overrides: dict[str, str] | None = None) -> bool:
        """Start Application Worker process in background."""
        if self.is_worker_running():
            return True

        env = {**os.environ, **(env_overrides or {})}
        api_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        venv_python = os.path.join(api_dir, ".venv", "Scripts", "python.exe")
        if not os.path.exists(venv_python):
            venv_python = "python"

        try:
            self.worker_process = subprocess.Popen(
                [venv_python, "-m", "app.services.application_assistant.worker"],
                cwd=api_dir,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            return True
        except Exception:
            return False

    def stop_application_worker(self, timeout_sec: float = 5.0) -> None:
        """Stop Application Worker gracefully."""
        if self.worker_process and self.is_worker_running():
            try:
                self.worker_process.terminate()
                self.worker_process.wait(timeout=timeout_sec)
            except Exception:
                try:
                    self.worker_process.kill()
                except Exception:
                    pass
        self.worker_process = None

    def restart_application_worker(self) -> bool:
        """Restart Application Worker after patch promotion."""
        self.stop_application_worker()
        time.sleep(0.5)
        return self.start_application_worker()

"""Code runners for the analyst coder.

The analyst only needs `runner.run(code, inputs) -> RunResult`. In production this is the
worker's no-network `code` profile (sandbox/code image, read-only /inputs, 20 s, 512 MB,
0.5 CPU). That profile does not exist yet, so `LocalSubprocessRunner` is used for
development and tests. It is NOT a sandbox: it only adds a timeout, a temp directory and an
empty environment. Never use it on a server.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

MAX_OUTPUT_CHARS = 64_000


@dataclass(frozen=True)
class RunResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool
    duration_ms: int
    executed_code: str


class CodeRunner(Protocol):
    def run(self, code: str, inputs: dict[str, object]) -> RunResult: ...


def with_input_dir(code: str, input_dir: str) -> str:
    return f"INPUT_DIR = {input_dir!r}\n{code}"


class LocalSubprocessRunner:
    """Development-only runner. See module docstring."""

    def __init__(self, timeout_s: float = 20.0, python: str = sys.executable):
        self.timeout_s = timeout_s
        self.python = python

    def run(self, code: str, inputs: dict[str, object]) -> RunResult:
        with tempfile.TemporaryDirectory(prefix="proofbox-analyst-") as tmp:
            input_dir = Path(tmp) / "inputs"
            input_dir.mkdir()
            for name, data in inputs.items():
                (input_dir / name).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            executed = with_input_dir(code, input_dir.as_posix())
            script = Path(tmp) / "main.py"
            script.write_text(executed, encoding="utf-8")

            env = {"PYTHONIOENCODING": "utf-8"}
            if os.name == "nt":
                env["SYSTEMROOT"] = os.environ.get("SYSTEMROOT", r"C:\Windows")
            started = time.monotonic()
            try:
                proc = subprocess.run(
                    [self.python, "-I", str(script)],
                    cwd=tmp,
                    env=env,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=self.timeout_s,
                )
                exit_code, stdout, stderr, timed_out = proc.returncode, proc.stdout, proc.stderr, False
            except subprocess.TimeoutExpired as exc:
                exit_code, timed_out = -1, True
                stdout = _text(exc.stdout)
                stderr = f"Timed out after {self.timeout_s:g} s"
            duration_ms = int((time.monotonic() - started) * 1000)
            for host_path, shown in ((str(script), "/work/main.py"), (script.as_posix(), "/work/main.py"), (str(input_dir), "/inputs"), (input_dir.as_posix(), "/inputs")):
                stderr = stderr.replace(host_path, shown)
            return RunResult(
                exit_code=exit_code,
                stdout=stdout[:MAX_OUTPUT_CHARS],
                stderr=stderr[:MAX_OUTPUT_CHARS],
                timed_out=timed_out,
                duration_ms=duration_ms,
                executed_code=with_input_dir(code, "/inputs"),
            )


def _text(value: bytes | str | None) -> str:
    if value is None:
        return ""
    return value.decode("utf-8", "replace") if isinstance(value, bytes) else value

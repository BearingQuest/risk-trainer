"""The one place the tests start a process (REPO-08)."""

import shutil
import subprocess
from typing import Any

import pytest


def popen(args: list[str], **kwargs: Any) -> subprocess.Popen[Any]:
    """Start a fixed test command with its executable resolved to an absolute path.

    The executable is looked up on the PATH of kwargs["env"] when one is given,
    so a test's restricted PATH applies to the lookup as well.
    """
    env = kwargs.get("env")
    executable = shutil.which(args[0], path=env.get("PATH") if env else None)
    if executable is None:
        pytest.fail(f"{args[0]} not found on PATH")
    return subprocess.Popen([executable, *args[1:]], **kwargs)  # noqa: S603  # fixed test commands; arguments come from the test, never from outside input


def run(
    args: list[str],
    *,
    input: str | None = None,
    timeout: float | None = None,
    check: bool = False,
    capture_output: bool = False,
    **kwargs: Any,
) -> subprocess.CompletedProcess[Any]:
    """subprocess.run on top of popen, so this module holds the only starter."""
    if input is not None:
        kwargs["stdin"] = subprocess.PIPE
    if capture_output:
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.PIPE
    with popen(args, **kwargs) as process:
        try:
            stdout, stderr = process.communicate(input, timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            raise
        completed = subprocess.CompletedProcess(args, process.returncode, stdout, stderr)
    if check:
        completed.check_returncode()
    return completed

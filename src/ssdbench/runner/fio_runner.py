"""Execute fio as a subprocess and parse its JSON output.

This module deliberately avoids capturing fio's stdout to memory. Instead it
tees stdout and stderr to files inside the run directory so that a crash or a
very long run does not accumulate output in RAM, and so that all evidence of a
run is on disk for later inspection.
"""
from __future__ import annotations

import json
import shutil
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class FioNotFoundError(RuntimeError):
    """fio binary was not found on PATH."""


class FioExecutionError(RuntimeError):
    """fio exited with a non zero status."""

    def __init__(self, returncode: int, stderr_tail: str):
        super().__init__(
            f"fio exited with code {returncode}. last stderr:\n{stderr_tail}"
        )
        self.returncode = returncode
        self.stderr_tail = stderr_tail


class FioOutputParseError(RuntimeError):
    """fio output could not be parsed as JSON."""


@dataclass(frozen=True)
class FioResult:
    """Parsed fio result for a single job group.

    This is a small distilled view. The full JSON is always saved to disk so a
    user can dig deeper when needed.
    """

    read_iops: float
    write_iops: float
    read_bw_bytes_per_sec: float
    write_bw_bytes_per_sec: float
    read_clat_mean_ns: float | None
    write_clat_mean_ns: float | None
    read_clat_p99_ns: float | None
    write_clat_p99_ns: float | None
    read_clat_p99_9_ns: float | None
    write_clat_p99_9_ns: float | None
    runtime_ms: int
    raw: dict[str, Any]


def _find_fio() -> str:
    path = shutil.which("fio")
    if not path:
        raise FioNotFoundError(
            "could not find fio on PATH. install fio or set PATH to include it."
        )
    return path


def _tail(path: Path, max_lines: int = 30) -> str:
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return ""
    lines = text.splitlines()[-max_lines:]
    return "\n".join(lines)


def run_fio(
    job_file: Path,
    json_output: Path,
    stdout_log: Path,
    stderr_log: Path,
    extra_timeout_sec: int = 120,
    expected_runtime_sec: int | None = None,
) -> FioResult:
    """Run fio with the given job file and return a parsed result.

    ``extra_timeout_sec`` is added on top of ``expected_runtime_sec`` to give
    fio a grace period for setup and teardown. If we cannot estimate expected
    runtime the subprocess runs without a wall clock timeout, since fio itself
    already respects the ``runtime`` setting in the job file.
    """
    fio = _find_fio()

    cmd = [
        fio,
        "--output-format=json",
        f"--output={json_output}",
        str(job_file),
    ]

    timeout: int | None
    if expected_runtime_sec is not None:
        timeout = expected_runtime_sec + extra_timeout_sec
    else:
        timeout = None

    with stdout_log.open("w") as out_f, stderr_log.open("w") as err_f:
        # start_new_session so that Ctrl-C on the CLI does not kill fio
        # midway before we have a chance to clean up. We forward SIGINT
        # ourselves below.
        process = subprocess.Popen(
            cmd,
            stdout=out_f,
            stderr=err_f,
            start_new_session=True,
        )
        try:
            returncode = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.send_signal(signal.SIGTERM)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            raise FioExecutionError(
                returncode=-1,
                stderr_tail=_tail(stderr_log)
                + "\n[ssdbench: fio timed out and was terminated]",
            )
        except KeyboardInterrupt:
            process.send_signal(signal.SIGINT)
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            raise

    if returncode != 0:
        raise FioExecutionError(returncode=returncode, stderr_tail=_tail(stderr_log))

    return _parse_fio_json(json_output)


def _parse_fio_json(json_output: Path) -> FioResult:
    try:
        data = json.loads(json_output.read_text())
    except (OSError, json.JSONDecodeError) as e:
        raise FioOutputParseError(
            f"could not parse fio JSON output at {json_output}: {e}"
        ) from e

    jobs = data.get("jobs") or []
    if not jobs:
        raise FioOutputParseError("fio JSON contained no 'jobs' entry")

    # With group_reporting=1 there is one aggregated job entry per group.
    # If for some reason there are several, we take the first, which matches
    # how fio prints its default summary.
    job = jobs[0]
    read = job.get("read") or {}
    write = job.get("write") or {}

    def clat_ns(section: dict[str, Any], key: str) -> float | None:
        clat = section.get("clat_ns") or {}
        if key == "mean":
            v = clat.get("mean")
            return float(v) if v is not None else None
        percentiles = clat.get("percentile") or {}
        # fio uses string keys like "99.000000", "99.900000"
        for pk, pv in percentiles.items():
            try:
                if abs(float(pk) - key_to_float(key)) < 1e-6:
                    return float(pv)
            except ValueError:
                continue
        return None

    def key_to_float(k: str) -> float:
        # accepts "p99" and "p99_9"
        stripped = k.lstrip("p").replace("_", ".")
        return float(stripped)

    return FioResult(
        read_iops=float(read.get("iops", 0.0)),
        write_iops=float(write.get("iops", 0.0)),
        read_bw_bytes_per_sec=float(read.get("bw_bytes", 0.0)),
        write_bw_bytes_per_sec=float(write.get("bw_bytes", 0.0)),
        read_clat_mean_ns=clat_ns(read, "mean"),
        write_clat_mean_ns=clat_ns(write, "mean"),
        read_clat_p99_ns=clat_ns(read, "p99"),
        write_clat_p99_ns=clat_ns(write, "p99"),
        read_clat_p99_9_ns=clat_ns(read, "p99_9"),
        write_clat_p99_9_ns=clat_ns(write, "p99_9"),
        runtime_ms=int(job.get("job_runtime", 0)),
        raw=data,
    )

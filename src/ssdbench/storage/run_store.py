"""Directory backed run storage.

A run is a directory under ``<runs_root>/`` whose name encodes the timestamp,
scenario, device, and a short unique id. Every file inside a run directory is
plain text or JSON so that operators can inspect runs with grep, jq, or a
text editor without needing any tooling from us.

Layout:

    <runs_root>/
        20260707T143000_4k_randread_nvme0n1_a1b2c3/
            manifest.json
            metadata.json
            scenario.yaml
            fio_job.fio
            fio_output.json
            summary.md
            stdout.log
            stderr.log
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel


class RunManifest(BaseModel):
    """Small identifying record for a run. Written to manifest.json."""

    run_id: str
    scenario_name: str
    scenario_version: int
    device: str
    started_at_utc: str
    finished_at_utc: str | None = None
    status: str = "running"  # running, completed, failed
    error: str | None = None


class RunSummary(BaseModel):
    """Distilled numeric summary of a completed run."""

    read_iops: float
    write_iops: float
    read_bw_bytes_per_sec: float
    write_bw_bytes_per_sec: float
    read_clat_mean_ns: float | None = None
    write_clat_mean_ns: float | None = None
    read_clat_p99_ns: float | None = None
    write_clat_p99_ns: float | None = None
    read_clat_p99_9_ns: float | None = None
    write_clat_p99_9_ns: float | None = None
    runtime_ms: int


_DEVICE_SANITIZE_RE = re.compile(r"[^a-zA-Z0-9]+")


def _sanitize_device(device: str) -> str:
    name = Path(device).name or "dev"
    cleaned = _DEVICE_SANITIZE_RE.sub("_", name).strip("_")
    return cleaned or "dev"


def _timestamp_component(dt: datetime) -> str:
    return dt.strftime("%Y%m%dT%H%M%S")


class RunStore:
    """Owns the runs root directory and creates one directory per run."""

    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def create_run(self, scenario_name: str, device: str) -> RunDirectory:
        now = datetime.now(timezone.utc)
        run_id = uuid.uuid4().hex[:6]
        dir_name = (
            f"{_timestamp_component(now)}_{scenario_name}_"
            f"{_sanitize_device(device)}_{run_id}"
        )
        path = self.root / dir_name
        path.mkdir(parents=True, exist_ok=False)
        return RunDirectory(path=path, run_id=run_id, started_at_utc=now.isoformat())

    def list_runs(self) -> list[RunDirectory]:
        results: list[RunDirectory] = []
        if not self.root.exists():
            return results
        for entry in sorted(self.root.iterdir()):
            if entry.is_dir() and (entry / "manifest.json").exists():
                # We do not eagerly parse; RunDirectory is a cheap handle.
                results.append(RunDirectory.from_existing(entry))
        return results

    def find_run(self, run_id_prefix: str) -> RunDirectory | None:
        for entry in self.root.iterdir():
            if entry.is_dir() and entry.name.endswith(f"_{run_id_prefix}"):
                return RunDirectory.from_existing(entry)
            if entry.is_dir() and run_id_prefix in entry.name:
                return RunDirectory.from_existing(entry)
        return None


class RunDirectory:
    """Handle to a single run directory. Reads and writes files lazily."""

    def __init__(self, path: Path, run_id: str, started_at_utc: str):
        self.path = path
        self.run_id = run_id
        self.started_at_utc = started_at_utc

    @classmethod
    def from_existing(cls, path: Path) -> RunDirectory:
        manifest_path = path / "manifest.json"
        if manifest_path.exists():
            data = json.loads(manifest_path.read_text())
            return cls(
                path=path,
                run_id=data.get("run_id", ""),
                started_at_utc=data.get("started_at_utc", ""),
            )
        return cls(path=path, run_id="", started_at_utc="")

    # ---- file paths ----------------------------------------------------

    @property
    def manifest_path(self) -> Path:
        return self.path / "manifest.json"

    @property
    def metadata_path(self) -> Path:
        return self.path / "metadata.json"

    @property
    def scenario_path(self) -> Path:
        return self.path / "scenario.yaml"

    @property
    def fio_job_path(self) -> Path:
        return self.path / "fio_job.fio"

    @property
    def fio_output_path(self) -> Path:
        return self.path / "fio_output.json"

    @property
    def summary_path(self) -> Path:
        return self.path / "summary.md"

    @property
    def stdout_path(self) -> Path:
        return self.path / "stdout.log"

    @property
    def stderr_path(self) -> Path:
        return self.path / "stderr.log"

    # ---- write helpers -------------------------------------------------

    def write_manifest(self, manifest: RunManifest) -> None:
        self.manifest_path.write_text(json.dumps(manifest.model_dump(), indent=2))

    def write_metadata(self, metadata_dict: dict[str, Any]) -> None:
        self.metadata_path.write_text(json.dumps(metadata_dict, indent=2))

    def write_scenario_yaml(self, raw_yaml: str) -> None:
        self.scenario_path.write_text(raw_yaml)

    def write_fio_job(self, job_text: str) -> None:
        self.fio_job_path.write_text(job_text)

    def write_summary_markdown(self, markdown: str) -> None:
        self.summary_path.write_text(markdown)

    # ---- read helpers --------------------------------------------------

    def read_manifest(self) -> RunManifest | None:
        if not self.manifest_path.exists():
            return None
        return RunManifest(**json.loads(self.manifest_path.read_text()))

    def read_summary_dict(self) -> dict[str, Any] | None:
        """Return the numeric summary if we can extract it from stored files."""
        if not self.fio_output_path.exists():
            return None
        try:
            data = json.loads(self.fio_output_path.read_text())
        except (OSError, json.JSONDecodeError):
            return None
        jobs = data.get("jobs") or []
        if not jobs:
            return None
        job = jobs[0]
        read = job.get("read") or {}
        write = job.get("write") or {}
        return {
            "read_iops": float(read.get("iops", 0.0)),
            "write_iops": float(write.get("iops", 0.0)),
            "read_bw_bytes_per_sec": float(read.get("bw_bytes", 0.0)),
            "write_bw_bytes_per_sec": float(write.get("bw_bytes", 0.0)),
            "runtime_ms": int(job.get("job_runtime", 0)),
        }

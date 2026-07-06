"""Collect system and device metadata for a benchmark run.

Every field is best effort. If we cannot determine a value we set it to None
rather than raising, so that a partially unknown environment does not prevent
a run from being recorded. Missing values should be visible in reports.
"""
from __future__ import annotations

import getpass
import os
import platform
import re
import shutil
import socket
import subprocess
from pathlib import Path
from typing import Any

from pydantic import BaseModel


class DeviceInfo(BaseModel):
    path: str
    model: str | None = None
    serial: str | None = None
    size_bytes: int | None = None
    is_block_device: bool | None = None
    is_nvme: bool | None = None


class HostInfo(BaseModel):
    hostname: str
    user: str
    kernel: str
    os_release: str | None = None
    cpu_model: str | None = None
    cpu_count: int
    total_memory_bytes: int | None = None


class ToolInfo(BaseModel):
    fio_version: str | None = None
    fio_path: str | None = None
    ssdbench_version: str


class RunMetadata(BaseModel):
    host: HostInfo
    device: DeviceInfo
    tool: ToolInfo


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text().strip()
    except OSError:
        return None


def _run(cmd: list[str]) -> str | None:
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _get_cpu_model() -> str | None:
    text = _read_text(Path("/proc/cpuinfo"))
    if not text:
        return None
    for line in text.splitlines():
        if line.startswith("model name"):
            _, _, value = line.partition(":")
            return value.strip()
    return None


def _get_total_memory_bytes() -> int | None:
    text = _read_text(Path("/proc/meminfo"))
    if not text:
        return None
    match = re.search(r"MemTotal:\s+(\d+)\s+kB", text)
    if not match:
        return None
    return int(match.group(1)) * 1024


def _collect_host() -> HostInfo:
    os_release = None
    try:
        os_release_text = Path("/etc/os-release").read_text()
        for line in os_release_text.splitlines():
            if line.startswith("PRETTY_NAME="):
                os_release = line.partition("=")[2].strip().strip('"')
                break
    except OSError:
        pass

    return HostInfo(
        hostname=socket.gethostname(),
        user=getpass.getuser(),
        kernel=platform.release(),
        os_release=os_release,
        cpu_model=_get_cpu_model(),
        cpu_count=os.cpu_count() or 1,
        total_memory_bytes=_get_total_memory_bytes(),
    )


def _collect_device(device_path: str) -> DeviceInfo:
    p = Path(device_path)
    info = DeviceInfo(path=device_path)

    try:
        st = p.stat()
        # S_IFBLK = 0x6000
        info.is_block_device = (st.st_mode & 0o170000) == 0o060000
    except OSError:
        info.is_block_device = None

    # size via blockdev
    blockdev = shutil.which("blockdev")
    if blockdev and info.is_block_device:
        size_str = _run([blockdev, "--getsize64", device_path])
        if size_str and size_str.isdigit():
            info.size_bytes = int(size_str)

    # nvme detection by path prefix; not authoritative but a useful hint
    name = p.name
    info.is_nvme = name.startswith("nvme")

    # model and serial via sysfs for block devices
    if info.is_block_device:
        # strip partition suffix for a namespace like nvme0n1p1 -> nvme0n1
        base = re.sub(r"p\d+$", "", name)
        sysfs = Path(f"/sys/block/{base}/device")
        info.model = _read_text(sysfs / "model") or _read_text(sysfs / "device/model")
        info.serial = _read_text(sysfs / "serial") or _read_text(sysfs / "device/serial")

    return info


def _collect_tool(ssdbench_version: str) -> ToolInfo:
    fio_path = shutil.which("fio")
    fio_version = None
    if fio_path:
        out = _run([fio_path, "--version"])
        if out:
            fio_version = out.strip()
    return ToolInfo(
        fio_version=fio_version,
        fio_path=fio_path,
        ssdbench_version=ssdbench_version,
    )


def collect_metadata(device_path: str, ssdbench_version: str) -> RunMetadata:
    return RunMetadata(
        host=_collect_host(),
        device=_collect_device(device_path),
        tool=_collect_tool(ssdbench_version),
    )


def as_dict(metadata: RunMetadata) -> dict[str, Any]:
    return metadata.model_dump()

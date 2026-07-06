"""Render a completed run into human readable summaries.

We keep the summary format very simple. Two audiences:

- terminal, via a rich table
- text, via a Markdown file saved next to the run
"""
from __future__ import annotations

from rich.table import Table

from ssdbench.runner.fio_runner import FioResult
from ssdbench.runner.metadata import RunMetadata


def _format_bytes_per_sec(bps: float) -> str:
    if bps <= 0:
        return "-"
    mib_per_sec = bps / (1024 * 1024)
    return f"{mib_per_sec:,.1f} MiB/s"


def _format_iops(iops: float) -> str:
    if iops <= 0:
        return "-"
    return f"{iops:,.0f}"


def _format_ns_as_us(ns: float | None) -> str:
    if ns is None or ns <= 0:
        return "-"
    return f"{ns / 1000:,.1f} us"


def render_summary_markdown(
    scenario_name: str,
    device: str,
    result: FioResult,
    metadata: RunMetadata,
) -> str:
    lines = [
        f"# ssdbench run summary: {scenario_name}",
        "",
        f"- device: `{device}`",
        f"- host: `{metadata.host.hostname}` (kernel {metadata.host.kernel})",
        f"- fio: {metadata.tool.fio_version or 'unknown'}",
        "",
        "## Result",
        "",
        "| metric | read | write |",
        "|---|---|---|",
        f"| IOPS | {_format_iops(result.read_iops)} | {_format_iops(result.write_iops)} |",
        (
            f"| BW | {_format_bytes_per_sec(result.read_bw_bytes_per_sec)} "
            f"| {_format_bytes_per_sec(result.write_bw_bytes_per_sec)} |"
        ),
        (
            f"| clat mean | {_format_ns_as_us(result.read_clat_mean_ns)} "
            f"| {_format_ns_as_us(result.write_clat_mean_ns)} |"
        ),
        (
            f"| clat p99 | {_format_ns_as_us(result.read_clat_p99_ns)} "
            f"| {_format_ns_as_us(result.write_clat_p99_ns)} |"
        ),
        (
            f"| clat p99.9 | {_format_ns_as_us(result.read_clat_p99_9_ns)} "
            f"| {_format_ns_as_us(result.write_clat_p99_9_ns)} |"
        ),
        "",
        f"Runtime: {result.runtime_ms} ms",
        "",
    ]
    return "\n".join(lines)


def render_summary_table(scenario_name: str, device: str, result: FioResult) -> Table:
    table = Table(title=f"{scenario_name} on {device}")
    table.add_column("metric", style="cyan", no_wrap=True)
    table.add_column("read", justify="right")
    table.add_column("write", justify="right")
    table.add_row(
        "IOPS",
        _format_iops(result.read_iops),
        _format_iops(result.write_iops),
    )
    table.add_row(
        "BW",
        _format_bytes_per_sec(result.read_bw_bytes_per_sec),
        _format_bytes_per_sec(result.write_bw_bytes_per_sec),
    )
    table.add_row(
        "clat mean",
        _format_ns_as_us(result.read_clat_mean_ns),
        _format_ns_as_us(result.write_clat_mean_ns),
    )
    table.add_row(
        "clat p99",
        _format_ns_as_us(result.read_clat_p99_ns),
        _format_ns_as_us(result.write_clat_p99_ns),
    )
    table.add_row(
        "clat p99.9",
        _format_ns_as_us(result.read_clat_p99_9_ns),
        _format_ns_as_us(result.write_clat_p99_9_ns),
    )
    return table

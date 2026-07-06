"""Render a Scenario into a fio job file."""
from __future__ import annotations

from ssdbench.scenarios.loader import Scenario


def render_fio_job(scenario: Scenario, device: str) -> str:
    """Render a Scenario plus a device path into a fio job file (ini format).

    We fold non negotiable defaults into the rendered file rather than
    exposing them in the scenario schema:

    - ``time_based=1``          so the run stops at duration_sec regardless of size
    - ``group_reporting=1``     so num_jobs=N reports a single aggregated result
    - ``randrepeat=0``          so consecutive runs draw different random offsets
    - ``norandommap=1``         avoid the per block bitmap; SSD IOPS measurement
                                does not need to guarantee unique offsets and the
                                bitmap adds CPU overhead
    """
    w = scenario.workload
    r = scenario.runtime
    e = scenario.engine

    lines = [
        "[global]",
        f"ioengine={e.name}",
        f"direct={1 if e.direct else 0}",
        f"rw={w.pattern}",
        f"bs={w.block_size}",
        f"iodepth={w.io_depth}",
        f"numjobs={w.num_jobs}",
        f"runtime={r.duration_sec}",
        f"ramp_time={r.ramp_sec}",
        "time_based=1",
        "group_reporting=1",
        "randrepeat=0",
        "norandommap=1",
    ]

    if w.rw_mix_read is not None and w.pattern in ("rw", "randrw"):
        lines.append(f"rwmixread={w.rw_mix_read}")

    lines.append("")
    lines.append(f"[{scenario.name}]")
    lines.append(f"filename={device}")
    lines.append("")

    return "\n".join(lines)

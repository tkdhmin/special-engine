from __future__ import annotations

from ssdbench.scenarios.loader import load_scenario
from ssdbench.scenarios.renderer import render_fio_job


def test_render_includes_required_options():
    scen = load_scenario("4k_randread")
    job = render_fio_job(scen, "/dev/nvme0n1")

    # global section header and filename must be present
    assert "[global]" in job
    assert "filename=/dev/nvme0n1" in job
    assert f"[{scen.name}]" in job

    # non negotiable defaults folded in by the renderer
    assert "time_based=1" in job
    assert "group_reporting=1" in job
    assert "randrepeat=0" in job
    assert "norandommap=1" in job

    # values from the scenario itself
    assert "ioengine=io_uring" in job
    assert "direct=1" in job
    assert "rw=randread" in job
    assert "bs=4k" in job
    assert "iodepth=32" in job
    assert "numjobs=4" in job


def test_direct_false_becomes_zero(tmp_path):
    # ad hoc scenario with direct: false
    from ssdbench.scenarios.loader import load_scenario_from_file

    path = tmp_path / "buffered.yaml"
    path.write_text(
        """
name: buffered_test
version: 1
workload:
  pattern: read
  block_size: 4k
  io_depth: 1
  num_jobs: 1
runtime:
  duration_sec: 1
engine:
  name: psync
  direct: false
"""
    )
    scen = load_scenario_from_file(path)
    job = render_fio_job(scen, "/tmp/testfile")
    assert "direct=0" in job


def test_rwmixread_only_for_mixed_patterns(tmp_path):
    from ssdbench.scenarios.loader import load_scenario_from_file

    path = tmp_path / "mixed.yaml"
    path.write_text(
        """
name: mixed_test
version: 1
workload:
  pattern: randrw
  block_size: 4k
  io_depth: 32
  num_jobs: 1
  rw_mix_read: 70
runtime:
  duration_sec: 1
engine:
  name: io_uring
  direct: true
"""
    )
    scen = load_scenario_from_file(path)
    job = render_fio_job(scen, "/tmp/x")
    assert "rwmixread=70" in job

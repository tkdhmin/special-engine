from __future__ import annotations

import pytest

from ssdbench.scenarios.loader import (
    ScenarioError,
    list_catalog,
    load_scenario,
    load_scenario_from_file,
)


def test_catalog_has_expected_scenarios():
    names = list_catalog()
    assert "4k_randread" in names
    assert "4k_randwrite" in names
    assert "seq_read_128k" in names
    assert "seq_write_128k" in names
    assert "qd1_randread_latency" in names


def test_load_4k_randread():
    scen = load_scenario("4k_randread")
    assert scen.name == "4k_randread"
    assert scen.workload.pattern == "randread"
    assert scen.workload.block_size == "4k"
    assert scen.workload.io_depth == 32
    assert scen.workload.num_jobs == 4
    assert scen.engine.direct is True
    assert scen.raw_yaml.strip() != ""


def test_load_unknown_scenario_reports_available():
    with pytest.raises(ScenarioError) as exc_info:
        load_scenario("does_not_exist")
    assert "4k_randread" in str(exc_info.value)


def test_load_scenario_from_arbitrary_file(tmp_path):
    file_path = tmp_path / "custom.yaml"
    file_path.write_text(
        """
name: custom_test
version: 1
description: custom test scenario
workload:
  pattern: randwrite
  block_size: 8k
  io_depth: 64
  num_jobs: 2
runtime:
  duration_sec: 10
  ramp_sec: 2
engine:
  name: libaio
  direct: true
"""
    )
    scen = load_scenario_from_file(file_path)
    assert scen.name == "custom_test"
    assert scen.workload.block_size == "8k"


def test_invalid_scenario_rejected(tmp_path):
    file_path = tmp_path / "bad.yaml"
    file_path.write_text(
        """
name: BadName
version: 1
workload:
  pattern: sideways
  block_size: 4k
  io_depth: 0
  num_jobs: 1
runtime:
  duration_sec: 1
engine:
  name: io_uring
  direct: true
"""
    )
    with pytest.raises(ScenarioError):
        load_scenario_from_file(file_path)

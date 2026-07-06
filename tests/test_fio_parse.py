from __future__ import annotations

from pathlib import Path

from ssdbench.runner.fio_runner import _parse_fio_json


FIXTURE = Path(__file__).parent / "fixtures" / "sample_fio_output.json"


def test_parse_sample_output():
    result = _parse_fio_json(FIXTURE)
    assert result.read_iops == 50234.5
    assert result.write_iops == 0.0
    assert result.read_bw_bytes_per_sec == 205761315
    assert result.write_bw_bytes_per_sec == 0
    assert result.read_clat_mean_ns == 45000.5
    # p99 comes from "99.000000" key
    assert result.read_clat_p99_ns == 120000
    # p99.9 comes from "99.900000" key
    assert result.read_clat_p99_9_ns == 350000
    assert result.runtime_ms == 60000
    assert result.raw["fio version"] == "fio-3.36"

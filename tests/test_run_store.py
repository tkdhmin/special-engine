from __future__ import annotations

from ssdbench.storage.run_store import RunManifest, RunStore


def test_create_and_list_run(tmp_path):
    store = RunStore(tmp_path / "runs")
    run = store.create_run(scenario_name="4k_randread", device="/dev/nvme0n1")
    assert run.path.exists()
    assert run.run_id != ""

    manifest = RunManifest(
        run_id=run.run_id,
        scenario_name="4k_randread",
        scenario_version=1,
        device="/dev/nvme0n1",
        started_at_utc=run.started_at_utc,
        status="completed",
    )
    run.write_manifest(manifest)

    listed = store.list_runs()
    assert len(listed) == 1
    reloaded = listed[0].read_manifest()
    assert reloaded is not None
    assert reloaded.run_id == run.run_id


def test_find_run_by_prefix(tmp_path):
    store = RunStore(tmp_path / "runs")
    run = store.create_run(scenario_name="seq_read_128k", device="/dev/sda")
    manifest = RunManifest(
        run_id=run.run_id,
        scenario_name="seq_read_128k",
        scenario_version=1,
        device="/dev/sda",
        started_at_utc=run.started_at_utc,
    )
    run.write_manifest(manifest)

    found = store.find_run(run.run_id)
    assert found is not None
    assert found.path == run.path

    # partial prefix should also work
    found_by_prefix = store.find_run(run.run_id[:3])
    assert found_by_prefix is not None

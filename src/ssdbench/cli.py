"""ssdbench command line interface."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from ssdbench import __version__
from ssdbench.config import default_runs_root
from ssdbench.reporting.summary import render_summary_markdown, render_summary_table
from ssdbench.runner.fio_runner import (
    FioExecutionError,
    FioNotFoundError,
    FioOutputParseError,
    run_fio,
)
from ssdbench.runner.metadata import as_dict, collect_metadata
from ssdbench.scenarios.loader import (
    Scenario,
    ScenarioError,
    list_catalog,
    load_scenario,
    load_scenario_from_file,
)
from ssdbench.scenarios.renderer import render_fio_job
from ssdbench.storage.run_store import RunManifest, RunStore

app = typer.Typer(
    help="ssdbench: run curated fio based SSD benchmarks and store results.",
    no_args_is_help=True,
)
console = Console()
err_console = Console(stderr=True)


def _resolve_scenario(scenario_arg: str) -> Scenario:
    """Resolve a scenario argument.

    If the argument points at an existing file we treat it as an ad hoc
    scenario. Otherwise we look it up in the built in catalog.
    """
    path = Path(scenario_arg)
    if path.exists() and path.is_file():
        return load_scenario_from_file(path)
    return load_scenario(scenario_arg)


@app.command()
def version() -> None:
    """Print the ssdbench version and exit."""
    console.print(f"ssdbench {__version__}")


@app.command("scenarios")
def scenarios_cmd() -> None:
    """List the built in scenario catalog."""
    names = list_catalog()
    if not names:
        console.print("[yellow]no scenarios found in catalog[/yellow]")
        raise typer.Exit(0)

    table = Table(title="ssdbench catalog")
    table.add_column("name", style="cyan")
    table.add_column("description")

    for name in names:
        try:
            scenario = load_scenario(name)
            table.add_row(name, scenario.description)
        except ScenarioError as e:
            table.add_row(name, f"[red]invalid: {e}[/red]")

    console.print(table)


@app.command("run")
def run_cmd(
    scenario: str = typer.Argument(
        ..., help="Scenario name from the catalog, or a path to a YAML file."
    ),
    device: str = typer.Option(
        ..., "--device", "-d", help="Target device or file path, e.g. /dev/nvme0n1."
    ),
    runs_dir: Path | None = typer.Option(
        None,
        "--runs-dir",
        help="Directory where run results are stored. Defaults to ~/.ssdbench/runs.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Render the fio job file and print it, do not execute fio.",
    ),
) -> None:
    """Execute a scenario against a device and save the results."""
    try:
        scen = _resolve_scenario(scenario)
    except ScenarioError as e:
        err_console.print(f"[red]scenario error:[/red] {e}")
        raise typer.Exit(2)

    job_text = render_fio_job(scen, device)

    if dry_run:
        console.print(f"[bold]# fio job file for {scen.name}[/bold]")
        # bypass rich markup parsing so tokens like [global] survive
        sys.stdout.write(job_text)
        if not job_text.endswith("\n"):
            sys.stdout.write("\n")
        raise typer.Exit(0)

    store = RunStore(runs_dir or default_runs_root())
    run_dir = store.create_run(scenario_name=scen.name, device=device)

    # Write manifest early so an interrupted run still leaves a record.
    manifest = RunManifest(
        run_id=run_dir.run_id,
        scenario_name=scen.name,
        scenario_version=scen.version,
        device=device,
        started_at_utc=run_dir.started_at_utc,
        status="running",
    )
    run_dir.write_manifest(manifest)
    run_dir.write_scenario_yaml(scen.raw_yaml)
    run_dir.write_fio_job(job_text)

    metadata = collect_metadata(device_path=device, ssdbench_version=__version__)
    run_dir.write_metadata(as_dict(metadata))

    console.print(f"[bold]running scenario[/bold] {scen.name} on {device}")
    console.print(f"[dim]run dir:[/dim] {run_dir.path}")
    if metadata.tool.fio_version:
        console.print(f"[dim]fio:[/dim] {metadata.tool.fio_version}")
    else:
        err_console.print("[yellow]warning: fio version could not be determined[/yellow]")

    expected = scen.runtime.duration_sec + scen.runtime.ramp_sec

    try:
        result = run_fio(
            job_file=run_dir.fio_job_path,
            json_output=run_dir.fio_output_path,
            stdout_log=run_dir.stdout_path,
            stderr_log=run_dir.stderr_path,
            expected_runtime_sec=expected,
        )
    except FioNotFoundError as e:
        manifest.status = "failed"
        manifest.error = str(e)
        manifest.finished_at_utc = datetime.now(timezone.utc).isoformat()
        run_dir.write_manifest(manifest)
        err_console.print(f"[red]fio not found:[/red] {e}")
        raise typer.Exit(3)
    except FioExecutionError as e:
        manifest.status = "failed"
        manifest.error = str(e)
        manifest.finished_at_utc = datetime.now(timezone.utc).isoformat()
        run_dir.write_manifest(manifest)
        err_console.print(f"[red]fio failed:[/red] {e}")
        raise typer.Exit(4)
    except FioOutputParseError as e:
        manifest.status = "failed"
        manifest.error = str(e)
        manifest.finished_at_utc = datetime.now(timezone.utc).isoformat()
        run_dir.write_manifest(manifest)
        err_console.print(f"[red]could not parse fio output:[/red] {e}")
        raise typer.Exit(5)
    except KeyboardInterrupt:
        manifest.status = "failed"
        manifest.error = "interrupted by user"
        manifest.finished_at_utc = datetime.now(timezone.utc).isoformat()
        run_dir.write_manifest(manifest)
        err_console.print("[yellow]interrupted[/yellow]")
        raise typer.Exit(130)

    manifest.status = "completed"
    manifest.finished_at_utc = datetime.now(timezone.utc).isoformat()
    run_dir.write_manifest(manifest)

    summary_md = render_summary_markdown(
        scenario_name=scen.name,
        device=device,
        result=result,
        metadata=metadata,
    )
    run_dir.write_summary_markdown(summary_md)

    console.print(render_summary_table(scen.name, device, result))
    console.print(f"[green]done.[/green] results saved to {run_dir.path}")


@app.command("list")
def list_cmd(
    runs_dir: Path | None = typer.Option(
        None,
        "--runs-dir",
        help="Directory containing run results. Defaults to ~/.ssdbench/runs.",
    ),
    scenario: str | None = typer.Option(
        None, "--scenario", help="Filter by scenario name."
    ),
    device: str | None = typer.Option(None, "--device", help="Filter by device path."),
) -> None:
    """List stored runs."""
    store = RunStore(runs_dir or default_runs_root())
    runs = store.list_runs()

    table = Table(title="ssdbench runs")
    table.add_column("run id", style="cyan", no_wrap=True)
    table.add_column("scenario")
    table.add_column("device")
    table.add_column("status")
    table.add_column("read IOPS", justify="right")
    table.add_column("write IOPS", justify="right")
    table.add_column("started", style="dim")

    shown = 0
    for run in runs:
        manifest = run.read_manifest()
        if manifest is None:
            continue
        if scenario and manifest.scenario_name != scenario:
            continue
        if device and manifest.device != device:
            continue
        summary = run.read_summary_dict()
        r_iops = f"{summary['read_iops']:,.0f}" if summary else "-"
        w_iops = f"{summary['write_iops']:,.0f}" if summary else "-"
        table.add_row(
            manifest.run_id,
            manifest.scenario_name,
            manifest.device,
            manifest.status,
            r_iops,
            w_iops,
            manifest.started_at_utc,
        )
        shown += 1

    if shown == 0:
        console.print("[yellow]no matching runs found[/yellow]")
        return

    console.print(table)


@app.command("show")
def show_cmd(
    run_id: str = typer.Argument(..., help="Run id or unique prefix."),
    runs_dir: Path | None = typer.Option(
        None,
        "--runs-dir",
        help="Directory containing run results. Defaults to ~/.ssdbench/runs.",
    ),
) -> None:
    """Show the stored summary for a single run."""
    store = RunStore(runs_dir or default_runs_root())
    run = store.find_run(run_id)
    if run is None:
        err_console.print(f"[red]no run matching id '{run_id}' found[/red]")
        raise typer.Exit(1)
    if not run.summary_path.exists():
        err_console.print(
            f"[yellow]run {run.path.name} has no summary.md (was it interrupted?)[/yellow]"
        )
        raise typer.Exit(1)
    sys.stdout.write(run.summary_path.read_text())


if __name__ == "__main__":
    app()

"""``archon`` CLI (spec section 20).

    archon db-upgrade                 apply database migrations
    archon serve [--port]            run the HTTP API
    archon worker                    run the analysis worker loop
    archon analyze <url|path> [...]  ingest a repository end-to-end (headless)
"""

from __future__ import annotations

import json
import sys
import time

import typer

from archon.config import get_settings
from archon.domain.enums import JobState, RunMode

app = typer.Typer(add_completion=False, help="ARCHON - AI Software Archaeologist")


@app.command("db-upgrade")
def db_upgrade() -> None:
    """Create/upgrade the database schema."""
    from archon.db.migrate import upgrade

    upgrade()
    typer.echo("database schema is up to date")


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8000, reload: bool = False) -> None:
    """Run the FastAPI application with uvicorn."""
    import uvicorn

    uvicorn.run("archon.api.app:app", host=host, port=port, reload=reload)


@app.command()
def worker(max_iterations: int | None = typer.Option(None, help="stop after N loop ticks")) -> None:
    """Run the analysis worker."""
    from archon.jobs.worker import Worker

    Worker().run_forever(max_iterations=max_iterations)


@app.command()
def analyze(
    target: str = typer.Argument(..., help="github.com URL, owner/repo, or local path"),
    ref: str | None = typer.Option(None, help="branch, tag or commit sha"),
    mode: RunMode = typer.Option(RunMode.INGEST_ONLY.value, case_sensitive=False),
    wait: bool = typer.Option(True, help="run the pipeline inline and wait for the result"),
    timeout: float = typer.Option(600.0, help="seconds to wait when --wait"),
) -> None:
    """Ingest a repository and (by default) run the pipeline to completion."""
    from archon.db.base import session_scope
    from archon.db.migrate import upgrade
    from archon.db.models import AnalysisRun, Job, Repository
    from archon.jobs.manager import JobManager
    from archon.jobs.worker import Worker
    from archon.providers.repo import provider_for

    get_settings().ensure_dirs()
    upgrade()

    provider = provider_for(target)
    parsed = provider.parse(target, ref=ref)
    jobs = JobManager()

    with session_scope() as session:
        repo = (
            session.query(Repository)
            .filter(Repository.provider == provider.kind, Repository.url == parsed.canonical_url)
            .one_or_none()
        )
        if repo is None:
            repo = Repository(
                provider=provider.kind,
                url=parsed.canonical_url,
                owner=parsed.owner,
                name=parsed.name,
            )
            session.add(repo)
            session.flush()
        job = jobs.create_run_with_job(
            session, repository_id=repo.id, mode=mode, requested_ref=ref
        )
        run_id = job.run_id
        job_id = job.id

    typer.echo(f"run {run_id} queued (job {job_id})")
    if not wait:
        return

    w = Worker()
    deadline = time.time() + timeout
    while time.time() < deadline:
        w.tick()
        with session_scope() as session:
            run = session.get(AnalysisRun, run_id)
            job = session.get(Job, job_id)
            if job.state in (JobState.SUCCEEDED, JobState.FAILED, JobState.CANCELLED):
                _print_run(run)
                raise typer.Exit(code=0 if job.state == JobState.SUCCEEDED else 1)
        time.sleep(0.2)
    typer.echo("timed out waiting for the run to finish", err=True)
    raise typer.Exit(code=2)


def _print_run(run) -> None:
    out = {
        "run_id": run.id,
        "state": run.state.value,
        "current_stage": run.current_stage.value if run.current_stage else None,
        "last_completed_stage": run.last_completed_stage.value if run.last_completed_stage else None,
        "snapshot_id": run.snapshot_id,
        "error": run.error,
    }
    if run.snapshot:
        out["snapshot"] = {
            "commit_sha": run.snapshot.commit_sha,
            "branch": run.snapshot.branch,
            "support_level": run.snapshot.support_level.value,
            "file_count": run.snapshot.file_count,
            "commit_count": run.snapshot.commit_count,
        }
    out["evidence"] = [
        {"classification": e.classification.value, "summary": e.summary}
        for e in sorted(run.evidence, key=lambda x: x.created_at)
    ]
    typer.echo(json.dumps(out, indent=2, default=str))


def main() -> None:  # pragma: no cover
    app()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(app())

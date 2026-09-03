"""Repository + run-creation endpoints (spec sections 21, 47)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from archon.api.deps import get_session, rate_limit_runs
from archon.api.schemas import RepositoryCreate, RepositoryOut, RunCreate, RunOut
from archon.api.serialize import repository_out, run_out
from archon.core.errors import ArchonError, ErrorCode
from archon.core.ids import new_id
from archon.db.models import AnalysisRun, Repository
from archon.jobs.manager import JobManager
from archon.providers.repo import provider_for

router = APIRouter(prefix="/repositories", tags=["repositories"])
_jobs = JobManager()


@router.post("", response_model=RepositoryOut, status_code=status.HTTP_201_CREATED)
def create_repository(payload: RepositoryCreate, session: Session = Depends(get_session)) -> RepositoryOut:
    # deterministic validation only - no network here (spec section 21)
    provider = provider_for(payload.url)
    ref = provider.parse(payload.url)

    existing = session.scalar(
        select(Repository).where(
            Repository.provider == provider.kind, Repository.url == ref.canonical_url
        )
    )
    if existing:
        return repository_out(existing)

    repo = Repository(
        id=new_id("repo"),
        provider=provider.kind,
        url=ref.canonical_url,
        owner=ref.owner,
        name=ref.name,
        default_branch=payload.default_branch,
    )
    session.add(repo)
    session.flush()
    return repository_out(repo)


@router.get("", response_model=list[RepositoryOut])
def list_repositories(
    session: Session = Depends(get_session),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[RepositoryOut]:
    rows = session.scalars(
        select(Repository).order_by(Repository.created_at.desc()).limit(limit).offset(offset)
    ).all()
    return [repository_out(r) for r in rows]


@router.get("/{repository_id}", response_model=RepositoryOut)
def get_repository(repository_id: str, session: Session = Depends(get_session)) -> RepositoryOut:
    repo = session.get(Repository, repository_id)
    if repo is None:
        raise ArchonError(ErrorCode.NOT_FOUND, f"repository {repository_id!r} not found")
    return repository_out(repo)


@router.post(
    "/{repository_id}/runs",
    response_model=RunOut,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(rate_limit_runs)],
)
def create_run(
    repository_id: str,
    payload: RunCreate,
    response: Response,
    session: Session = Depends(get_session),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> RunOut:
    repo = session.get(Repository, repository_id)
    if repo is None:
        raise ArchonError(
            ErrorCode.NOT_FOUND,
            f"repository {repository_id!r} not found",
            suggested_action="Create the repository first with POST /repositories.",
        )
    job = _jobs.create_run_with_job(
        session,
        repository_id=repo.id,
        mode=payload.mode,
        requested_ref=payload.ref,
        config_hash=_config_hash(payload),
        idempotency_key=idempotency_key,
    )
    session.flush()
    run = session.get(AnalysisRun, job.run_id)
    assert run is not None
    response.headers["Location"] = f"/runs/{run.id}"
    return run_out(run)


@router.get("/{repository_id}/runs", response_model=list[RunOut])
def list_runs_for_repo(
    repository_id: str,
    session: Session = Depends(get_session),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[RunOut]:
    rows = session.scalars(
        select(AnalysisRun)
        .where(AnalysisRun.repository_id == repository_id)
        .order_by(AnalysisRun.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return [run_out(r, include_children=False) for r in rows]


def _config_hash(payload: RunCreate) -> str:
    import hashlib

    raw = f"{payload.mode.value}|{payload.ref or ''}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]

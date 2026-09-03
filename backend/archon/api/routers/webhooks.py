"""GitHub push webhook -> targeted incremental analysis (spec section 51)."""

from __future__ import annotations

import hashlib
import hmac
import json

from fastapi import APIRouter, Depends, Header, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from archon.analysis.incremental.scope import resolve_changed_components
from archon.api.deps import get_session
from archon.config import get_settings
from archon.core.errors import ArchonError, ErrorCode, Recoverability
from archon.core.ids import new_id
from archon.core.logging import get_logger
from archon.db.models import AnalysisRun, Repository, RepositorySnapshot, WebhookDelivery
from archon.domain.enums import ProviderKind, RunMode
from archon.jobs.manager import JobManager
from archon.providers.repo import provider_for

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
_jobs = JobManager()
log = get_logger("archon.api.webhooks")

_ZERO_SHA = "0" * 40


def _verify_signature(raw: bytes, header: str | None) -> None:
    secret = get_settings().github_webhook_secret
    if not secret:
        raise ArchonError(
            ErrorCode.UNAUTHORIZED,
            "the GitHub webhook endpoint is not configured",
            recoverability=Recoverability.NON_RECOVERABLE,
            suggested_action="Set ARCHON_GITHUB_WEBHOOK_SECRET and register the same secret on GitHub.",
        )
    if not header or not header.startswith("sha256="):
        raise ArchonError(
            ErrorCode.UNAUTHORIZED,
            "missing or malformed X-Hub-Signature-256 header",
            recoverability=Recoverability.NON_RECOVERABLE,
        )
    expected = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, header.split("=", 1)[1]):
        raise ArchonError(
            ErrorCode.UNAUTHORIZED,
            "webhook signature verification failed",
            recoverability=Recoverability.NON_RECOVERABLE,
        )


def _changed_paths(payload: dict) -> list[str]:
    paths: set[str] = set()
    commits = payload.get("commits") or []
    if not commits and payload.get("head_commit"):
        commits = [payload["head_commit"]]
    for c in commits:
        for key in ("added", "modified", "removed"):
            for p in c.get(key, []) or []:
                if p:
                    paths.add(p)
    return sorted(paths)


def _is_delete(payload: dict) -> bool:
    return bool(payload.get("deleted")) or payload.get("after") == _ZERO_SHA


def _resolve_repo(session: Session, repo_block: dict) -> Repository | None:
    url = repo_block.get("html_url") or repo_block.get("full_name") or repo_block.get("clone_url")
    if not url:
        return None
    try:
        provider = provider_for(url)
        ref = provider.parse(url)
    except ArchonError:
        return None
    return session.scalar(
        select(Repository).where(
            Repository.provider == provider.kind, Repository.url == ref.canonical_url
        )
    )


def _config_hash_for_push(after: str) -> str:
    return hashlib.sha256(f"INCREMENTAL|{after or ''}".encode()).hexdigest()[:32]


def _best_effort_component_ids(session: Session, repo: Repository, changed: list[str]) -> list[str]:
    snap = session.scalar(
        select(RepositorySnapshot)
        .where(RepositorySnapshot.repository_id == repo.id)
        .order_by(RepositorySnapshot.created_at.desc())
    )
    return resolve_changed_components(session, snap, changed) if snap else []


@router.post("/github", status_code=status.HTTP_202_ACCEPTED)
async def github_webhook(
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
    x_hub_signature_256: str | None = Header(default=None, alias="X-Hub-Signature-256"),
    x_github_event: str | None = Header(default=None, alias="X-GitHub-Event"),
    x_github_delivery: str | None = Header(default=None, alias="X-GitHub-Delivery"),
) -> dict:
    raw = await request.body()
    _verify_signature(raw, x_hub_signature_256)
    if not x_github_delivery:
        raise ArchonError(ErrorCode.VALIDATION, "missing X-GitHub-Delivery header")

    if session.scalar(
        select(WebhookDelivery.id).where(
            WebhookDelivery.provider == ProviderKind.GITHUB,
            WebhookDelivery.delivery_id == x_github_delivery,
        )
    ):
        raise ArchonError(
            ErrorCode.CONFLICT,
            "duplicate webhook delivery",
            context={"delivery_id": x_github_delivery},
            suggested_action="This delivery was already processed.",
        )

    delivery = WebhookDelivery(
        id=new_id("whd"),
        provider=ProviderKind.GITHUB,
        delivery_id=x_github_delivery,
        event=x_github_event or "",
        status="received",
    )
    session.add(delivery)

    if x_github_event != "push":
        delivery.status = "ignored_event"
        session.flush()
        return {"status": "ignored", "reason": f"event {x_github_event!r} is not handled"}

    payload = json.loads(raw or b"{}")
    after = payload.get("after")
    before = payload.get("before")
    delivery.head_sha = after
    delivery.before_sha = before
    delivery.ref = payload.get("ref")
    changed = _changed_paths(payload)
    delivery.changed_paths = changed

    repo = _resolve_repo(session, payload.get("repository") or {})
    if repo is None:
        delivery.status = "ignored_no_repo"
        session.flush()
        return {"status": "ignored", "reason": "repository is not registered"}
    delivery.repository_id = repo.id

    if _is_delete(payload) or not changed:
        delivery.status = "ignored_no_change"
        session.flush()
        return {"status": "ignored", "reason": "no analysable file changes"}

    try:
        job = _jobs.create_run_with_job(
            session,
            repository_id=repo.id,
            mode=RunMode.INCREMENTAL,
            requested_ref=after,
            config_hash=_config_hash_for_push(after),
            idempotency_key=f"gh:{x_github_delivery}",
            trigger={
                "source": "webhook",
                "event": "push",
                "sha": after,
                "before": before,
                "delivery_id": x_github_delivery,
            },
            changed_paths=changed,
        )
    except ArchonError as exc:
        if exc.code is ErrorCode.CONFLICT:
            delivery.status = "coalesced"
            delivery.detail = "coalesced with an in-flight run for the same commit"
            session.flush()
            return {"status": "coalesced", "reason": "an analysis for this push is already in progress"}
        raise

    session.flush()
    run = session.get(AnalysisRun, job.run_id)
    assert run is not None
    delivery.run_id = run.id
    delivery.status = "queued"
    delivery.changed_component_ids = _best_effort_component_ids(session, repo, changed)
    session.flush()
    response.headers["Location"] = f"/runs/{run.id}"
    log.info(
        "push webhook queued incremental run",
        extra={"extra_fields": {"run_id": run.id, "repo_id": repo.id, "files": len(changed)}},
    )
    return {"status": "queued", "run_id": run.id, "mode": RunMode.INCREMENTAL.value}

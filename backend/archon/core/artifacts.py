"""Filesystem artifact store (spec section 11).

Large/generated analysis outputs live on disk, not in DB rows. ``write_json`` writes
``<artifact_root>/<run_id>/<kind>.json``, records a content hash + size, and upserts one
``AnalysisArtifact`` row per (run, kind).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from archon.config import get_settings
from archon.db.models import AnalysisArtifact
from archon.domain.enums import Stage


def _run_dir(run_id: str) -> Path:
    d = get_settings().resolved_artifact_root / run_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_json(
    session: Session,
    run_id: str,
    kind: str,
    obj: Any,
    *,
    stage: Stage | None = None,
) -> AnalysisArtifact:
    path = _run_dir(run_id) / f"{kind}.json"
    data = json.dumps(obj, default=str, ensure_ascii=False, indent=None).encode("utf-8")
    path.write_bytes(data)
    sha = hashlib.sha256(data).hexdigest()

    art = session.scalar(
        select(AnalysisArtifact).where(
            AnalysisArtifact.run_id == run_id, AnalysisArtifact.kind == kind
        )
    )
    if art is None:
        art = AnalysisArtifact(
            run_id=run_id, kind=kind, storage="fs", ref=str(path),
            sha256=sha, size_bytes=len(data), mime="application/json", stage=stage,
        )
        session.add(art)
    else:
        art.ref = str(path)
        art.sha256 = sha
        art.size_bytes = len(data)
        art.stage = stage or art.stage
    session.flush()
    return art


def read_json(art: AnalysisArtifact) -> Any:
    return json.loads(Path(art.ref).read_text(encoding="utf-8"))


def write_text(
    session: Session,
    run_id: str,
    kind: str,
    text: str,
    *,
    stage: Stage | None = None,
    ext: str = ".txt",
    mime: str = "text/plain",
) -> AnalysisArtifact:
    """Sibling of ``write_json`` for non-JSON blobs (stdout/stderr/coverage.xml/junit.xml)."""
    path = _run_dir(run_id) / f"{kind}{ext}"
    data = text.encode("utf-8")
    path.write_bytes(data)
    sha = hashlib.sha256(data).hexdigest()

    art = session.scalar(
        select(AnalysisArtifact).where(
            AnalysisArtifact.run_id == run_id, AnalysisArtifact.kind == kind
        )
    )
    if art is None:
        art = AnalysisArtifact(
            run_id=run_id, kind=kind, storage="fs", ref=str(path),
            sha256=sha, size_bytes=len(data), mime=mime, stage=stage,
        )
        session.add(art)
    else:
        art.ref = str(path)
        art.sha256 = sha
        art.size_bytes = len(data)
        art.mime = mime
        art.stage = stage or art.stage
    session.flush()
    return art


def read_text(art: AnalysisArtifact) -> str:
    return Path(art.ref).read_text(encoding="utf-8", errors="replace")

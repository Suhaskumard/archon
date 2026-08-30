"""GitHub REST metadata + error mapping, exercised offline via httpx.MockTransport
(spec sections 21, 54)."""

from __future__ import annotations

import httpx
import pytest

from archon.core.errors import ArchonError, ErrorCode
from archon.providers.repo.github import GitHubRepositoryProvider


def _provider(handler):
    return GitHubRepositoryProvider(transport=httpx.MockTransport(handler))


def test_metadata_success():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/repos/psf/requests"
        return httpx.Response(
            200,
            json={"default_branch": "main", "private": False, "size": 2048, "archived": False},
        )

    prov = _provider(handler)
    meta = prov.fetch_metadata(prov.parse("psf/requests"))
    assert meta.default_branch == "main"
    assert meta.is_private is False
    assert meta.size_bytes == 2048 * 1024


@pytest.mark.parametrize(
    "status,headers,expected",
    [
        (404, {}, ErrorCode.REPOSITORY_NOT_FOUND),
        (401, {}, ErrorCode.GITHUB_UNAUTHORIZED),
        (403, {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1"}, ErrorCode.GITHUB_RATE_LIMITED),
        (403, {}, ErrorCode.REPOSITORY_PRIVATE),
        (429, {}, ErrorCode.GITHUB_RATE_LIMITED),
    ],
)
def test_error_status_mapping(status, headers, expected):
    prov = _provider(lambda req: httpx.Response(status, headers=headers, json={}))
    with pytest.raises(ArchonError) as exc:
        prov.fetch_metadata(prov.parse("psf/requests"))
    assert exc.value.code is expected
    assert exc.value.to_dict()["error"]["suggested_action"]


def test_transient_5xx_is_retried_then_raises():
    calls = {"n": 0}

    def handler(_req):
        calls["n"] += 1
        return httpx.Response(503, json={})

    prov = GitHubRepositoryProvider(transport=httpx.MockTransport(handler))
    prov._settings.http_max_retries = 2
    with pytest.raises(ArchonError):
        prov.fetch_metadata(prov.parse("psf/requests"))
    assert calls["n"] >= 2

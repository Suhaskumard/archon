"""GitHub webhook HMAC-SHA256 signature verification (Phase 19, spec section 51)."""

from __future__ import annotations

import hashlib
import hmac

import pytest

from archon.config import reset_settings_cache
from archon.core.errors import ArchonError, ErrorCode

BODY = b'{"zen":"design for failure","hook_id":1}'
SECRET = "s3cret-value"


def _sig(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


@pytest.fixture
def _secret(monkeypatch):
    monkeypatch.setenv("ARCHON_GITHUB_WEBHOOK_SECRET", SECRET)
    reset_settings_cache()
    yield
    monkeypatch.delenv("ARCHON_GITHUB_WEBHOOK_SECRET", raising=False)
    reset_settings_cache()


def _verify(body, header):
    from archon.api.routers.webhooks import _verify_signature

    return _verify_signature(body, header)


def test_valid_signature_passes(_secret):
    _verify(BODY, _sig(BODY, SECRET))  # no raise


def test_wrong_secret_rejected(_secret):
    with pytest.raises(ArchonError) as e:
        _verify(BODY, _sig(BODY, "not-the-secret"))
    assert e.value.code is ErrorCode.UNAUTHORIZED
    assert e.value.http_status == 401


def test_tampered_body_rejected(_secret):
    with pytest.raises(ArchonError) as e:
        _verify(BODY + b" ", _sig(BODY, SECRET))
    assert e.value.code is ErrorCode.UNAUTHORIZED


def test_missing_header_rejected(_secret):
    with pytest.raises(ArchonError) as e:
        _verify(BODY, None)
    assert e.value.code is ErrorCode.UNAUTHORIZED


def test_malformed_header_rejected(_secret):
    with pytest.raises(ArchonError) as e:
        _verify(BODY, hmac.new(SECRET.encode(), BODY, hashlib.sha256).hexdigest())  # no "sha256="
    assert e.value.code is ErrorCode.UNAUTHORIZED


def test_unconfigured_secret_rejects_everything(monkeypatch):
    monkeypatch.delenv("ARCHON_GITHUB_WEBHOOK_SECRET", raising=False)
    reset_settings_cache()
    with pytest.raises(ArchonError) as e:
        _verify(BODY, _sig(BODY, SECRET))
    assert e.value.code is ErrorCode.UNAUTHORIZED
    reset_settings_cache()


def test_uses_constant_time_compare():
    import inspect

    from archon.api.routers import webhooks

    assert "hmac.compare_digest" in inspect.getsource(webhooks._verify_signature)

from archon.core.errors import ArchonError, ErrorCode, Recoverability, not_found
from archon.core.logging import redact


def test_archon_error_serialization_and_status():
    err = ArchonError(
        ErrorCode.REPOSITORY_NOT_FOUND,
        "nope",
        context={"slug": "a/b"},
        recoverability=Recoverability.NON_RECOVERABLE,
        suggested_action="check the name",
    )
    body = err.to_dict()["error"]
    assert body["code"] == "REPOSITORY_NOT_FOUND"
    assert body["context"] == {"slug": "a/b"}
    assert body["recoverability"] == "NON_RECOVERABLE"
    assert body["suggested_action"] == "check the name"
    assert err.http_status == 404


def test_not_found_helper():
    err = not_found("run", "run_123")
    assert err.code is ErrorCode.NOT_FOUND
    assert err.http_status == 404


def test_redact_scrubs_tokens_and_urls():
    assert redact("clone https://x-access-token:ghp_abcdefghijklmnop1234@github.com/o/r.git") == (
        "clone https://x-access-token:***@github.com/o/r.git"
    )
    assert redact({"github_token": "ghp_secretsecretsecret12", "ok": "v"}) == {
        "github_token": "***",
        "ok": "v",
    }
    assert "ghp_" not in redact("bare token ghp_abcdefghijklmnop1234 here")

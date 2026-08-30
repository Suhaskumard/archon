import pytest

from archon.core.errors import ArchonError, ErrorCode
from archon.domain.enums import ProviderKind
from archon.providers.repo import provider_for
from archon.providers.repo.github import GitHubRepositoryProvider


@pytest.mark.parametrize(
    "url,owner,name,ref",
    [
        ("https://github.com/psf/requests", "psf", "requests", None),
        ("https://github.com/psf/requests.git", "psf", "requests", None),
        ("github.com/psf/requests", "psf", "requests", None),
        ("git@github.com:psf/requests.git", "psf", "requests", None),
        ("psf/requests", "psf", "requests", None),
        ("https://github.com/psf/requests/tree/main", "psf", "requests", "main"),
        ("https://github.com/psf/requests/commit/abcdef1", "psf", "requests", "abcdef1"),
    ],
)
def test_parse_variants(url, owner, name, ref):
    parsed = GitHubRepositoryProvider().parse(url)
    assert (parsed.owner, parsed.name, parsed.requested_ref) == (owner, name, ref)
    assert parsed.canonical_url == f"https://github.com/{owner}/{name}"
    assert parsed.clone_target == f"https://github.com/{owner}/{name}.git"  # no token in env


def test_explicit_ref_overrides_embedded():
    parsed = GitHubRepositoryProvider().parse(
        "https://github.com/psf/requests/tree/main", ref="v2.0"
    )
    assert parsed.requested_ref == "v2.0"


def test_token_is_embedded_only_in_clone_target(monkeypatch):
    monkeypatch.setenv("ARCHON_GITHUB_TOKEN", "ghp_tokentokentokentoken12")
    import archon.config as config

    config.reset_settings_cache()
    parsed = GitHubRepositoryProvider().parse("psf/requests")
    assert "ghp_tokentokentokentoken12" not in parsed.canonical_url
    assert parsed.clone_target.startswith("https://x-access-token:ghp_")


@pytest.mark.parametrize("bad", ["", "not a url", "https://gitlab.com/a/b", "ftp://x"])
def test_invalid_refs_rejected(bad):
    with pytest.raises(ArchonError) as exc:
        provider_for(bad)
    assert exc.value.code in {ErrorCode.INVALID_REPOSITORY_URL}


def test_provider_for_dispatch(tmp_path):
    assert provider_for("https://github.com/a/b").kind is ProviderKind.GITHUB
    assert provider_for("a/b").kind is ProviderKind.GITHUB
    assert provider_for(str(tmp_path)).kind is ProviderKind.LOCAL

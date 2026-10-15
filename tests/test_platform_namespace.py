"""Exercise the dependency-free namespace contract exported by Base."""
import pytest

from project_workflow.infrastructure.platform_namespace import is_personal_token, platform_env


@pytest.mark.parametrize("prefix", ["sdlc_pat_", "pdlc_pat_"])
def test_personal_token_dispatch_keeps_both_generations(prefix):
    assert is_personal_token(prefix + "test-only")
    assert not is_personal_token("foreign_pat_test-only")


def test_canonical_legacy_and_conflict_configuration(monkeypatch):
    monkeypatch.delenv("PDLC_NAMESPACE_FIXTURE", raising=False)
    monkeypatch.delenv("SDLC_NAMESPACE_FIXTURE", raising=False)
    assert platform_env("NAMESPACE_FIXTURE") is None
    monkeypatch.setenv("SDLC_NAMESPACE_FIXTURE", "same-test-only")
    assert platform_env("NAMESPACE_FIXTURE") == "same-test-only"
    monkeypatch.setenv("PDLC_NAMESPACE_FIXTURE", "same-test-only")
    assert platform_env("NAMESPACE_FIXTURE") == "same-test-only"
    monkeypatch.setenv("PDLC_NAMESPACE_FIXTURE", "other-test-only")
    with pytest.raises(ValueError, match="conflicting") as error:
        platform_env("NAMESPACE_FIXTURE")
    assert "test-only" not in str(error.value)

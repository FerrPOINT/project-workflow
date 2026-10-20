"""Read-only observations must not masquerade as qualified environment reuse."""
from types import SimpleNamespace

import pytest

from scripts import quality_environment as environment


@pytest.fixture
def request_root(tmp_path):
    for name, value in (("pyproject.toml", "[project]\nname='fixture'\n"),
                        ("uv.lock", "version = 1\n"), ("constraints.txt", "fixture==2.0\n")):
        (tmp_path / name).write_text(value, encoding="utf-8")
    return tmp_path


def distributions(monkeypatch, *versions):
    values = [SimpleNamespace(metadata={"Name": "fixture"}, version=version) for version in versions]
    monkeypatch.setattr(environment.metadata, "distributions", lambda: iter(values))


def test_first_effective_distribution_wins_over_shadowed_project_underlay(request_root, monkeypatch):
    distributions(monkeypatch, "2.0", "1.0")
    result = environment.snapshot(request_root)
    assert result["status"] == "REQUIREMENTS_METADATA_MATCH_ONLY"
    assert result["distributions"]["fixture"] == {"version": "2.0", "shadowed_versions": ["1.0"]}
    assert result["automatic_reuse_eligible"] is False
    assert result["package_payload_verified"] is False
    assert result["interpreter_content_verified"] is False
    assert result["manager_identity_verified"] is False
    assert "absent constraints-only packages" in result["requirements_mode"]
    assert result["python"]["extension_suffix"]
    assert result["python"]["executable"] and result["python"]["prefix"] and result["python"]["base_prefix"]


@pytest.mark.parametrize("versions,observed", [(("1.0", "2.0"), "1.0"), ((), None)])
def test_mismatched_or_missing_effective_requirement_is_visible(request_root, monkeypatch, versions, observed):
    distributions(monkeypatch, *versions)
    result = environment.snapshot(request_root)
    assert result["status"] == "REQUIREMENTS_MISMATCH"
    assert result["mismatches"] == [{"name": "fixture", "expected": "==2.0", "observed": observed}]


def test_pep_names_versions_and_inactive_markers_use_native_requirement_semantics(request_root, monkeypatch):
    (request_root / "constraints.txt").write_text(
        "Fixture_Package==2\nmissing==1; python_version < '2'\n", encoding="utf-8")
    monkeypatch.setattr(environment.metadata, "distributions", lambda: iter([
        SimpleNamespace(metadata={"Name": "fixture-package"}, version="2.0")]))
    result = environment.snapshot(request_root)
    assert result["requirements_checked"] == 1
    assert result["mismatches"] == []


def test_request_mutation_during_observation_is_rejected(request_root, monkeypatch):
    def changed():
        (request_root / "constraints.txt").write_text("fixture==3\n", encoding="utf-8")
        return iter([SimpleNamespace(metadata={"Name": "fixture"}, version="2.0")])
    monkeypatch.setattr(environment.metadata, "distributions", changed)
    with pytest.raises(ValueError, match="changed during observation"):
        environment.snapshot(request_root)


def test_observer_bounds_input_bytes_and_distribution_count(request_root, monkeypatch):
    distributions(monkeypatch, "2.0", "1.0")
    monkeypatch.setattr(environment, "MAX_DISTRIBUTIONS", 1)
    with pytest.raises(ValueError, match="distribution count"):
        environment.snapshot(request_root)
    monkeypatch.setattr(environment, "MAX_INPUT_BYTES", 1)
    with pytest.raises(ValueError, match="input exceeds"):
        environment.snapshot(request_root)


def test_requirement_count_is_bounded_even_for_duplicates(request_root, monkeypatch):
    distributions(monkeypatch, "2.0")
    monkeypatch.setattr(environment, "MAX_REQUIREMENTS", 1)
    (request_root / "constraints.txt").write_text("fixture==2\nfixture==2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="requirements exceed"):
        environment.snapshot(request_root)


@pytest.mark.parametrize("requirement", [
    "", "# no requested packages\n", "fixture[extra]==2",
    "fixture @ https://example.invalid/private-token", "--index-url private-token",
])
def test_unqualified_request_cannot_be_reported_as_matching(request_root, monkeypatch, requirement):
    distributions(monkeypatch, "2.0")
    (request_root / "constraints.txt").write_text(requirement, encoding="utf-8")
    with pytest.raises(ValueError) as error:
        environment.snapshot(request_root)
    assert "private-token" not in str(error.value)


def test_inspection_never_bootstraps_uv_or_runs_tests(monkeypatch, capsys):
    import json
    import sys

    from scripts import quality

    original = sys.dont_write_bytecode
    monkeypatch.setattr(sys, "argv", ["quality.py", "--inspect-environment"])
    monkeypatch.setattr(quality.subprocess, "run", lambda *_args, **_kwargs: pytest.fail("no command"))
    monkeypatch.setattr(environment, "snapshot", lambda _root: {
        "status": "DIAGNOSTIC", "automatic_reuse_eligible": False,
    })
    assert quality.main() == 0
    assert json.loads(capsys.readouterr().out)["automatic_reuse_eligible"] is False
    assert sys.dont_write_bytecode == original


def test_failed_inspection_is_bounded_diagnostic_without_secret_values(monkeypatch, capsys):
    import json
    import sys

    from scripts import quality

    def unavailable(_root):
        raise ValueError("private-token")
    monkeypatch.setattr(sys, "argv", ["quality.py", "--inspect-environment"])
    monkeypatch.setattr(environment, "snapshot", unavailable)
    assert quality.main() == 2
    output = capsys.readouterr().out
    assert "private-token" not in output
    assert json.loads(output)["status"] == "UNAVAILABLE"


def test_large_observation_is_rejected_before_stdout_publication(monkeypatch, capsys):
    import json
    import sys

    from scripts import quality

    monkeypatch.setattr(sys, "argv", ["quality.py", "--inspect-environment"])
    monkeypatch.setattr(environment, "MAX_OBSERVATION_BYTES", 32)
    monkeypatch.setattr(environment, "snapshot", lambda _root: {"large": "x" * 100})
    assert quality.main() == 2
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "UNAVAILABLE" and "large" not in output


@pytest.mark.parametrize("arguments", [["--prepared"], ["unit"], ["quality", "--", "tests/test_quality_runner.py"]])
def test_inspection_cannot_implicitly_select_an_execution_lane(monkeypatch, arguments):
    import sys

    from scripts import quality

    monkeypatch.setattr(sys, "argv", ["quality.py", "--inspect-environment", *arguments])
    monkeypatch.setattr(environment, "snapshot", lambda _root: pytest.fail("reject execution scope first"))
    with pytest.raises(SystemExit) as error:
        quality.main()
    assert error.value.code == 2

"""Coverage ratchet rejects a missing statement instead of rounding it into a pass."""

import math
from pathlib import Path

import pytest
import tomllib
from coverage.results import should_fail_under


@pytest.mark.unit
@pytest.mark.parametrize("statements", [1000, 12976, 100000])
def test_coverage_floor_rejects_the_statement_below_94_percent(statements):
    config = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8"))
    report = config["tool"]["coverage"]["report"]
    needed = math.ceil(statements * 0.94)
    assert should_fail_under((needed - 1) * 100 / statements, report["fail_under"], report.get("precision", 0))
    assert not should_fail_under(needed * 100 / statements, report["fail_under"], report.get("precision", 0))

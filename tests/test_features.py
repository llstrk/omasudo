"""Runs features/*.feature as unittest tests: one test per scenario.

`python3 tests/gherkin.py` runs the same scenarios and prints every step.
"""

from pathlib import Path

import steps  # noqa: F401  - registers the step definitions
from gherkin import test_suite
from steps import Context

FEATURES = Path(__file__).resolve().parents[1] / "features"


def load_tests(loader, tests, pattern):
    return test_suite(FEATURES, Context)

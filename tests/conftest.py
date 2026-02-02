"""Pytest configuration and shared fixtures."""

import sys
from pathlib import Path

import pytest

# Add app to path
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture(scope="session")
def project_root():
    """Return project root directory."""
    return Path(__file__).parent.parent


@pytest.fixture(scope="session")
def fixtures_dir(project_root):
    """Return fixtures directory."""
    return project_root / "tests" / "fixtures"

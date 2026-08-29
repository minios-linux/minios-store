from pathlib import Path

import pytest


@pytest.fixture
def tmp_path(tmpdir):
    """Provide pathlib-compatible temporary paths on Bionic pytest."""
    return Path(str(tmpdir))

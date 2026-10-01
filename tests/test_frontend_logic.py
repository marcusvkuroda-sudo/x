"""Runs the front-end logic tests (tests/logic.test.mjs) when Node.js is installed."""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not installed")
def test_frontend_logic():
    result = subprocess.run(
        ["node", "--test", "tests/logic.test.mjs"], cwd=ROOT, capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, result.stdout + result.stderr

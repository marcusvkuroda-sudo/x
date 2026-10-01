import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from app import config

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "gastos.db")
    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(config, "APP_PASSWORD", "")
    # Tests that need the free reader switch to "local" themselves.
    monkeypatch.setattr(config, "EXTRACTION_MODE", "claude")

    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c

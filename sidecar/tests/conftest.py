"""Test fixtures: isolated sidecar app with a temp data dir and a scripted mock LLM."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app.config import Settings  # noqa: E402
from app.main import AppState, create_app  # noqa: E402


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    s = Settings(data_dir=tmp_path / "data", session_token=None, port=0)
    s.ensure_dirs()
    return s


@pytest.fixture()
def app(settings: Settings):
    return create_app(settings)


@pytest.fixture()
def client(app) -> TestClient:
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def state(app) -> AppState:
    return app.state.ohd


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    (root / "README.md").write_text("# demo\n", encoding="utf-8")
    return root


@pytest.fixture()
def workspace(client: TestClient, project: Path) -> dict:
    response = client.post("/api/workspaces", json={"path": str(project), "kind": "local"})
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture()
def mock_profile(client: TestClient) -> dict:
    response = client.post(
        "/api/llm-profiles",
        json={"name": "Demo", "provider": "mock", "model": "mock-model", "is_default": True},
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture()
def conversation(client: TestClient, workspace: dict, mock_profile: dict) -> dict:
    response = client.post("/api/conversations", json={"workspace_id": workspace["id"]})
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("OHD_DATA_DIR", raising=False)
    yield


def wait_for_status(client: TestClient, conversation_id: str, statuses: set[str], timeout: float = 10.0) -> dict:
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        data = client.get(f"/api/conversations/{conversation_id}").json()
        if data["status"] in statuses:
            return data
        time.sleep(0.05)
    raise AssertionError(f"timeout waiting for status in {statuses}: last={data['status']}")

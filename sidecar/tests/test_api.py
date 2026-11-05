"""API-level tests: auth, CRUD, agent loop, approvals, exports (spec §15)."""

from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings, generate_session_token
from app.llm import LlmReply, MockLLM, ToolCall, Usage
from app.main import create_app

from .conftest import wait_for_status


def _script_llm(state, replies: list[LlmReply]) -> None:
    """Install a scripted MockLLM as the model behind the default 'mock' profile."""
    client = MockLLM(replies)
    state._test_llm = client  # type: ignore[attr-defined]
    import app.services as services

    original = services.build_llm_for_conversation

    def fake(db, conversation):  # pragma: no cover - trivial pass-through
        return client

    services.build_llm_for_conversation = fake  # type: ignore[assignment]
    state._restore_llm = original  # type: ignore[attr-defined]


def test_health_is_public(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert any(check["name"] == "python" for check in body["environment"])


def test_session_token_is_required(tmp_path: Path) -> None:
    token = generate_session_token()
    settings = Settings(data_dir=tmp_path / "d", session_token=token)
    settings.ensure_dirs()
    app = create_app(settings)
    with TestClient(app) as c:
        assert c.get("/api/settings").status_code == 401
        assert (
            c.get("/api/settings", headers={"Authorization": "Bearer wrong"}).status_code == 401
        )
        ok = c.get("/api/settings", headers={"Authorization": f"Bearer {token}"})
        assert ok.status_code == 200
        # health stays reachable so the shell can poll for readiness
        assert c.get("/health").status_code == 200


def test_llm_profile_secrets_never_returned(client: TestClient) -> None:
    created = client.post(
        "/api/llm-profiles",
        json={
            "name": "Ollama",
            "provider": "ollama",
            "model": "qwen2.5-coder:7b",
            "base_url": "http://localhost:11434/v1",
            "api_key": "super-secret-key",
        },
    )
    assert created.status_code == 201
    body = created.json()
    assert body["has_api_key"] is True
    assert "super-secret-key" not in created.text
    listed = client.get("/api/llm-profiles").text
    assert "super-secret-key" not in listed

    state_db = client.get("/api/llm-profiles").json()
    assert state_db[0]["api_key_ref"]


def test_api_key_is_encrypted_on_disk(client: TestClient, settings: Settings) -> None:
    client.post(
        "/api/llm-profiles",
        json={"name": "OpenAI", "provider": "openai", "model": "gpt-4o-mini", "api_key": "sk-abc123"},
    )
    for path in settings.data_dir.rglob("*"):
        if path.is_file():
            assert b"sk-abc123" not in path.read_bytes(), f"plaintext key found in {path}"


def test_connection_test_endpoint(client: TestClient) -> None:
    for provider in ("mock", "ollama"):
        result = client.post(
            "/api/llm-profiles/test",
            json={"name": f"probe-{provider}", "provider": provider, "model": "mock-model"},
        )
        assert result.status_code == 200, result.text
        body = result.json()
        assert "ok" in body and "latency_ms" in body
    assert client.post(
        "/api/llm-profiles/test", json={"name": "x", "provider": "mock", "model": "m"}
    ).json()["ok"] is True


def test_workspace_crud(client: TestClient, project: Path) -> None:
    created = client.post("/api/workspaces", json={"path": str(project), "kind": "local"})
    assert created.status_code == 201
    wid = created.json()["id"]
    assert client.get("/api/workspaces").json()[0]["id"] == wid
    # creating the same path twice is idempotent
    again = client.post("/api/workspaces", json={"path": str(project), "kind": "local"})
    assert again.json()["id"] == wid
    assert client.delete(f"/api/workspaces/{wid}").status_code == 204


def test_conversation_lifecycle(client: TestClient, conversation: dict) -> None:
    cid = conversation["id"]
    assert client.get(f"/api/conversations/{cid}").json()["status"] == "idle"
    renamed = client.patch(f"/api/conversations/{cid}", json={"title": "Fix bug", "pinned": True})
    assert renamed.json()["title"] == "Fix bug"
    assert renamed.json()["pinned"] is True
    assert client.get("/api/conversations", params={"q": "Fix"}).json()[0]["id"] == cid
    assert client.delete(f"/api/conversations/{cid}").status_code == 204
    assert client.get(f"/api/conversations/{cid}").status_code == 404


def test_agent_loop_runs_scripted_task(client: TestClient, conversation: dict, state) -> None:
    _script_llm(
        state,
        [
            LlmReply(
                text="Creating the health endpoint.",
                tool_calls=[
                    ToolCall(
                        id="c1",
                        name="write_file",
                        arguments={"path": "app.py", "content": "def health():\n    return 'ok'\n"},
                    )
                ],
                usage=Usage(100, 20),
                model="mock-model",
            ),
            LlmReply(
                text="Running a check.",
                tool_calls=[ToolCall(id="c2", name="run_shell", arguments={"command": "ls app.py"})],
                usage=Usage(120, 10),
                model="mock-model",
            ),
            LlmReply(
                text="Done.",
                tool_calls=[ToolCall(id="c3", name="finish", arguments={"summary": "Health endpoint added"})],
                usage=Usage(140, 10),
                model="mock-model",
            ),
        ],
    )
    cid = conversation["id"]
    sent = client.post(f"/api/conversations/{cid}/messages", json={"content": "Add a health endpoint"})
    assert sent.status_code == 200
    assert sent.json()["title"] == "Add a health endpoint"
    final = wait_for_status(client, cid, {"done", "error"})
    assert final["status"] == "done"
    assert final["tokens_total"] > 0

    events = client.get(f"/api/conversations/{cid}/events").json()
    types = [e["type"] for e in events]
    assert types.count("action") == 3
    assert "observation" in types
    assert "usage" in types
    tools = [e["tool"] for e in events if e["type"] == "action"]
    assert tools == ["write_file", "run_shell", "finish"]


def test_risky_command_requires_approval_and_denial_blocks_it(
    client: TestClient, conversation: dict, state, project: Path
) -> None:
    _script_llm(
        state,
        [
            LlmReply(
                text="",
                tool_calls=[ToolCall(id="c1", name="run_shell", arguments={"command": "rmdir /s /q data"})],
                usage=Usage(10, 5),
                model="mock-model",
            ),
            LlmReply(
                text="Understood, I will not delete anything.",
                tool_calls=[ToolCall(id="c2", name="finish", arguments={"summary": "Cancelled"})],
                usage=Usage(10, 5),
                model="mock-model",
            ),
        ],
    )
    cid = conversation["id"]
    client.post(f"/api/conversations/{cid}/messages", json={"content": "delete everything"})
    pending = wait_for_status(client, cid, {"waiting_approval"})
    approval = pending["pending_approval"]
    assert approval and approval["reason"]

    decision = client.post(
        f"/api/conversations/{cid}/approval",
        json={"approval_id": approval["id"], "approved": False},
    )
    assert decision.status_code == 200
    final = wait_for_status(client, cid, {"done", "error"})
    assert final["status"] == "done"

    observations = [e for e in client.get(f"/api/conversations/{cid}/events").json() if e["type"] == "observation"]
    assert observations[0]["ok"] is False
    assert "denied" in observations[0]["content"].lower()
    assert not (project / "data").exists()


def test_approval_accepted_executes_the_command(
    client: TestClient, conversation: dict, state, project: Path
) -> None:
    target = project / "to-delete"
    target.mkdir()
    _script_llm(
        state,
        [
            LlmReply(
                text="",
                tool_calls=[ToolCall(id="c1", name="run_shell", arguments={"command": "rmdir /s /q to-delete"})],
                usage=Usage(10, 5),
                model="mock-model",
            ),
            LlmReply(
                text="Done",
                tool_calls=[ToolCall(id="c2", name="finish", arguments={"summary": "Deleted"})],
                usage=Usage(10, 5),
                model="mock-model",
            ),
        ],
    )
    cid = conversation["id"]
    client.post(f"/api/conversations/{cid}/messages", json={"content": "clean up"})
    pending = wait_for_status(client, cid, {"waiting_approval"})
    client.post(
        f"/api/conversations/{cid}/approval",
        json={"approval_id": pending["pending_approval"]["id"], "approved": True},
    )
    wait_for_status(client, cid, {"done", "error"})
    observations = [e for e in client.get(f"/api/conversations/{cid}/events").json() if e["type"] == "observation"]
    assert observations[0]["tool"] == "run_shell"
    assert observations[0]["exit_code"] is not None


def test_stop_halts_the_agent(client: TestClient, conversation: dict, state) -> None:
    _script_llm(
        state,
        [
            LlmReply(
                text="",
                tool_calls=[ToolCall(id=f"c{i}", name="run_shell", arguments={"command": "sleep 0.2"})],
                usage=Usage(5, 5),
                model="mock-model",
            )
            for i in range(10)
        ],
    )
    cid = conversation["id"]
    client.post(f"/api/conversations/{cid}/messages", json={"content": "loop forever"})
    wait_for_status(client, cid, {"running"})
    started = time.monotonic()
    client.post(f"/api/conversations/{cid}/stop")
    wait_for_status(client, cid, {"idle"})
    assert time.monotonic() - started < 2.5


def test_file_browsing_editor_and_diff(client: TestClient, conversation: dict, project: Path) -> None:
    cid = conversation["id"]
    (project / "src").mkdir()
    (project / "src" / "main.py").write_text("print('hi')\n", encoding="utf-8")
    tree = client.get(f"/api/conversations/{cid}/files").json()
    assert {node["name"] for node in tree} >= {"src", "README.md"}

    read = client.get(f"/api/conversations/{cid}/file", params={"path": "src/main.py"}).json()
    assert read["language"] == "python"
    assert read["eol"] == "lf"

    written = client.put(
        f"/api/conversations/{cid}/file", params={"path": "src/main.py"}, json={"content": "print('bye')\n"}
    )
    assert written.status_code == 200
    assert (project / "src" / "main.py").read_text() == "print('bye')\n"

    escape = client.get(f"/api/conversations/{cid}/file", params={"path": "../../etc/passwd"})
    assert escape.status_code == 404


def test_git_diff_and_accept_reject(client: TestClient, conversation: dict, project: Path) -> None:
    cid = conversation["id"]
    init = (
        "git init -q && git add . && "
        "git -c user.email=a@b -c user.name=t -c commit.gpgsign=false commit -qm init"
    )
    run = client.post(f"/api/conversations/{cid}/shell", json={"command": init})
    assert run.json()["ok"], run.json()
    (project / "README.md").write_text("# changed\n", encoding="utf-8")
    (project / "new.txt").write_text("new\n", encoding="utf-8")

    git = client.get(f"/api/conversations/{cid}/git").json()
    assert {entry["path"] for entry in git["entries"]} >= {"README.md", "new.txt"}

    diffs = client.get(f"/api/conversations/{cid}/diff").json()
    assert any(d["path"] == "README.md" for d in diffs)

    accepted = client.post(f"/api/conversations/{cid}/diff/accept", json={"path": "README.md"})
    assert accepted.json()["ok"]
    rejected = client.post(f"/api/conversations/{cid}/diff/reject", json={"path": "new.txt"})
    assert rejected.json()["ok"]
    assert not (project / "new.txt").exists()


def test_export_markdown_and_json(client: TestClient, conversation: dict) -> None:
    cid = conversation["id"]
    client.post(f"/api/conversations/{cid}/messages", json={"content": "hello there"})
    wait_for_status(client, cid, {"done", "error", "idle"})
    md = client.get(f"/api/conversations/{cid}/export")
    assert md.status_code == 200
    assert "# hello there" in md.text
    assert "**You**" in md.text
    raw = client.get(f"/api/conversations/{cid}/export", params={"format": "json"}).text
    assert '"events"' in raw


def test_settings_roundtrip(client: TestClient) -> None:
    current = client.get("/api/settings").json()
    current["onboarded"] = True
    current["default_shell"] = "bash"
    current["max_cost_usd_per_conversation"] = 5.0
    saved = client.put("/api/settings", json=current)
    assert saved.status_code == 200
    assert client.get("/api/settings").json()["onboarded"] is True


def test_health_reports_uptime(client: TestClient) -> None:
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert isinstance(body["uptime_s"], float)
    assert body["uptime_s"] >= 0


def test_creating_a_workspace_returns_400_when_the_folder_cannot_be_made(
    client: TestClient, monkeypatch, tmp_path: Path
) -> None:
    """A permission/filesystem error must be a client error, not a 500."""
    blocked = tmp_path / "blocked"
    monkeypatch.setattr(
        Path,
        "mkdir",
        lambda self, *a, **k: (_ for _ in ()).throw(PermissionError(13, "Permission denied")),
    )
    response = client.post("/api/workspaces", json={"path": str(blocked)})
    assert response.status_code == 400
    assert "cannot create workspace folder" in response.json()["detail"]

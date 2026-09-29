import pytest
from fastapi.testclient import TestClient
from vallen_ide.backend.main import app


def test_ide_health():
    client = TestClient(app)
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_ide_sessions_endpoint():
    client = TestClient(app)
    res = client.get("/api/agent/sessions")
    assert res.status_code == 200
    data = res.json()
    assert "sessions" in data
    assert isinstance(data["sessions"], list)


def test_ide_workspace_current():
    client = TestClient(app)
    res = client.get("/api/workspace/current")
    assert res.status_code == 200
    data = res.json()
    assert "path" in data


def test_ide_recent_projects_endpoint():
    client = TestClient(app)
    res = client.get("/api/workspace/recent-projects")
    assert res.status_code == 200
    assert isinstance(res.json(), list)


def test_ide_clear_recent_projects():
    client = TestClient(app)
    res = client.post("/api/workspace/clear-recent-projects")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_ide_remove_recent_project():
    client = TestClient(app)
    res = client.post("/api/workspace/remove-recent-project", json={"path": "/nonexistent/test"})
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_ide_inline_edit_validation():
    client = TestClient(app)
    res = client.post("/api/agent/inline-edit", json={"prompt": ""})
    assert res.status_code == 400


def test_ide_inline_edit_success(monkeypatch):
    from vallen_cli.providers.registry import get_registry
    from vallen_cli.providers.base import BaseProvider, CompletionResult

    class FakeProvider(BaseProvider):
        async def check_connection(self):
            return True
        async def list_models(self):
            return []
        async def stream_completion(self, *args, **kwargs):
            yield None
        async def complete(self, messages, model=None, temperature=0.7, max_tokens=8192, tools=None):
            return CompletionResult(content="def add(a, b):\n    return a + b\n")

    from vallen_cli.providers.base import ProviderConfig
    cfg = ProviderConfig(name="fake", base_url="http://fake", api_key="", model="fake-model")
    fake_inst = FakeProvider(cfg)

    reg = get_registry()
    monkeypatch.setattr(reg, "active", lambda: fake_inst)

    client = TestClient(app)
    payload = {
        "prompt": "buat fungsi add",
        "selection": "",
        "language": "python",
        "path": "test.py",
    }
    res = client.post("/api/agent/inline-edit", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert "def add(a, b):" in data["replacement"]

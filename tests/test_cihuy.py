import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from vallen_ide.backend.main import app


def test_cihuy_templates():
    client = TestClient(app)
    res = client.get("/api/cihuy/templates")
    assert res.status_code == 200
    templates = res.json()
    assert isinstance(templates, list)
    assert len(templates) > 0
    assert "title" in templates[0]
    assert "idea" in templates[0]


def test_cihuy_export_files(tmp_path: Path):
    client = TestClient(app)
    payload = {
        "title": "Aplikasi Kasir Laundry",
        "prd_markdown": "# PRD Laundry\nFitur lengkap...",
        "schema_sql": "CREATE TABLE orders (id SERIAL PRIMARY KEY);",
        "tasks_markdown": "# Tasks\n- [ ] Task 01: Setup",
        "target_dir": str(tmp_path)
    }
    res = client.post("/api/cihuy/export", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert (tmp_path / "PRD.md").exists()
    assert (tmp_path / "SCHEMA.sql").exists()
    assert (tmp_path / "TASKS.md").exists()
    assert "PRD Laundry" in (tmp_path / "PRD.md").read_text()


def test_cihuy_generate_validation():
    client = TestClient(app)
    res = client.post("/api/cihuy/generate", json={"idea": ""})
    assert res.status_code == 400


def test_cihuy_generate_success(monkeypatch):
    from vallen_cli.providers.registry import get_registry
    from vallen_cli.providers.base import BaseProvider, CompletionResult, ProviderConfig
    import json

    fake_json = json.dumps({
        "title": "Kasir Cihuy",
        "tagline": "Aplikasi laundry modern",
        "summary": "Kasir cepat tanpa ribet",
        "target_stack": "Next.js + Supabase",
        "prd_markdown": "# PRD Kasir Cihuy",
        "schema_sql": "CREATE TABLE customers (id INT);",
        "api_spec_markdown": "# API Endpoints",
        "tasks_markdown": "# Tasks\n- [ ] Task 01: Init Next.js",
    })

    class FakeProvider(BaseProvider):
        async def check_connection(self):
            return True
        async def list_models(self):
            return []
        async def stream_completion(self, *args, **kwargs):
            yield None
        async def complete(self, messages, model=None, temperature=0.7, max_tokens=8192, tools=None):
            return CompletionResult(content=fake_json)

    cfg = ProviderConfig(name="fake-cihuy", base_url="http://fake", api_key="", model="fake-model")
    fake_inst = FakeProvider(cfg)

    reg = get_registry()
    monkeypatch.setattr(reg, "active", lambda: fake_inst)

    client = TestClient(app)
    payload = {
        "idea": "Bikin kasir laundry",
        "app_type": "Web App",
        "target_stack": "Next.js + Supabase",
        "complexity": "MVP",
    }
    res = client.post("/api/cihuy/generate", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["credit"] == "VALLEN NEXT (vallennextproject)"
    blueprint = data["blueprint"]
    assert blueprint["title"] == "Kasir Cihuy"
    assert "VALLEN CIHUY" in blueprint["prd_markdown"]


def test_cihuy_questions_validation():
    client = TestClient(app)
    res = client.post("/api/cihuy/questions", json={"idea": ""})
    assert res.status_code == 400


def test_cihuy_questions_success(monkeypatch):
    from vallen_cli.providers.registry import get_registry
    from vallen_cli.providers.base import BaseProvider, CompletionResult, ProviderConfig
    import json

    fake_questions_json = json.dumps({
        "questions": [
            {
                "id": "q1",
                "header": "Target Pengguna",
                "question": "Siapa pengguna utama aplikasi ini?",
                "options": [
                    {"key": "A", "label": "Kasir Toko Fisik (Rekomendasi)", "desc": "Operasional toko fisik."},
                    {"key": "B", "label": "Self-Service", "desc": "Pelanggan mandiri."},
                    {"key": "C", "label": "Multi-Cabang", "desc": "Akses multi-cabang."}
                ]
            }
        ]
    })

    class FakeProvider(BaseProvider):
        async def check_connection(self):
            return True
        async def list_models(self):
            return []
        async def stream_completion(self, *args, **kwargs):
            yield None
        async def complete(self, messages, model=None, temperature=0.7, max_tokens=8192, tools=None):
            return CompletionResult(content=fake_questions_json)

    cfg = ProviderConfig(name="fake-cihuy", base_url="http://fake", api_key="", model="fake-model")
    fake_inst = FakeProvider(cfg)

    reg = get_registry()
    monkeypatch.setattr(reg, "active", lambda: fake_inst)

    client = TestClient(app)
    res = client.post("/api/cihuy/questions", json={"idea": "Aplikasi laundry"})
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["skill"] == "code-architect"
    assert len(data["questions"]) > 0
    assert data["questions"][0]["id"] == "q1"
    assert data["questions"][0]["options"][0]["key"] == "A"

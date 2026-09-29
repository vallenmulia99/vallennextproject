import json
import sys
import asyncio

import pytest

from vallen_cli.tools.verify_tool import VerifyTool


@pytest.mark.asyncio
async def test_verify_runs_python_tests(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[build-system]\nrequires=[]\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_ok.py").write_text("def test_ok():\n    assert True\n")
    result = await VerifyTool().execute(workdir=str(tmp_path))
    assert result.success
    assert result.data["command"] == [sys.executable, "-m", "pytest", "-q"]


@pytest.mark.asyncio
async def test_verify_does_not_use_node_without_test_script(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"build": "echo ok"}}))
    result = await VerifyTool().execute(workdir=str(tmp_path))
    assert result.success
    assert result.data["command"][:4] == [sys.executable, "-m", "compileall", "-q"]


@pytest.mark.asyncio
async def test_verify_does_not_pass_jest_flags_to_generic_npm_tests(tmp_path, monkeypatch):
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"test": "vitest run"}}))

    captured = {}

    class Process:
        returncode = 0

        async def communicate(self):
            return b"ok", b""

    async def fake_create_subprocess_exec(*command, **kwargs):
        captured["command"] = list(command)
        return Process()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    result = await VerifyTool().execute(workdir=str(tmp_path))
    assert result.success
    assert captured["command"] == ["npm", "test"]


@pytest.mark.asyncio
async def test_verify_command_override_from_config(tmp_path, monkeypatch):
    from vallen_cli.core.config import get_config
    cfg = get_config()
    monkeypatch.setattr(cfg, "get", lambda key, default=None: {"command": "cargo test --quiet"} if key == "verify" else default)

    captured = {}

    class Process:
        returncode = 0
        async def communicate(self):
            return b"ok", b""

    async def fake_create_subprocess_exec(*command, **kwargs):
        captured["command"] = list(command)
        return Process()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    result = await VerifyTool().execute(workdir=str(tmp_path))
    assert result.success
    assert captured["command"] == ["cargo", "test", "--quiet"]


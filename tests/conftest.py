import os
import pytest
from pathlib import Path

@pytest.fixture(autouse=True)
def isolate_vallen_config(tmp_path_factory, monkeypatch):
    test_config_dir = tmp_path_factory.mktemp("vallen_config")
    monkeypatch.setenv("VALLEN_CONFIG_DIR", str(test_config_dir))

    import vallen_cli.core.config as config_mod
    monkeypatch.setattr(config_mod, "CONFIG_DIR", test_config_dir)
    monkeypatch.setattr(config_mod, "CONFIG_FILE", test_config_dir / "config.toml")
    monkeypatch.setattr(config_mod, "PROJECTS_FILE", test_config_dir / "projects.json")
    monkeypatch.setattr(config_mod, "SESSIONS_DIR", test_config_dir / "sessions")
    monkeypatch.setattr(config_mod, "HISTORY_DIR", test_config_dir / "history")
    monkeypatch.setattr(config_mod, "DB_FILE", test_config_dir / "vallen.db")
    monkeypatch.setattr(config_mod, "_config", None)
    monkeypatch.setattr(config_mod, "_projects_db", None)

    import vallen_cli.core.database as db_mod
    monkeypatch.setattr(db_mod, "DB_FILE", test_config_dir / "vallen.db")
    monkeypatch.setattr(db_mod, "_session_db", None)

    import vallen_cli.core.workspace as ws_mod
    monkeypatch.setattr(ws_mod, "_workspace", None)

    import vallen_cli.core.session as sess_mod
    monkeypatch.setattr(sess_mod, "_session_mgr", None)

    config_mod.ensure_config_dirs()
    yield

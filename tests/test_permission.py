import pytest
from vallen_cli.core.permission import PermissionManager, PermRequest, PermReply, PermAction


@pytest.mark.asyncio
async def test_permission_safe_tools():
    pm = PermissionManager()
    # Safe tools should be allowed automatically
    req = PermRequest(tool_name="read", description="Read file", path="main.py")
    reply = await pm.check(req)
    assert reply == PermReply.ONCE


@pytest.mark.asyncio
async def test_permission_session_approve():
    pm = PermissionManager()
    req = PermRequest(tool_name="shell", description="Run command", path="ls")

    # Set callback that always allows and approves for session
    async def fake_callback(r: PermRequest):
        return PermReply.ALWAYS

    pm.set_callback(fake_callback)

    reply1 = await pm.check(req)
    assert reply1 == PermReply.ALWAYS

    # Subsequent check should pass without calling callback
    pm.set_callback(None)
    reply2 = await pm.check(req)
    assert reply2 == PermReply.ONCE


@pytest.mark.asyncio
async def test_permission_fail_closed_without_callback():
    # Item 1: Sensitive tools must reject by default when no callback is set
    pm = PermissionManager()
    req = PermRequest(tool_name="write", description="Write 10 bytes to secret.txt", path="secret.txt")
    reply = await pm.check(req)
    assert reply == PermReply.REJECT


@pytest.mark.asyncio
async def test_permission_allow_unsupervised():
    # Item 1: When allow_unsupervised is explicitly enabled, it permits execution
    pm = PermissionManager()
    pm.allow_unsupervised = True
    req = PermRequest(tool_name="shell", description="Run command", path="ls -la")
    reply = await pm.check(req)
    assert reply == PermReply.ONCE


@pytest.mark.asyncio
async def test_permission_allow_all_edits_for_session_does_not_allow_shell():
    pm = PermissionManager()
    calls = 0

    async def callback(request: PermRequest):
        nonlocal calls
        calls += 1
        return PermReply.ALWAYS_EDITS if calls == 1 else PermReply.REJECT

    pm.set_callback(callback)
    assert await pm.check(PermRequest(tool_name="edit", description="Edit a.py", path="a.py")) == PermReply.ALWAYS_EDITS
    assert await pm.check(PermRequest(tool_name="apply_patch", description="Patch b.py", path="b.py")) == PermReply.ONCE
    assert await pm.check(PermRequest(tool_name="shell", description="Run git status", path="git status")) == PermReply.REJECT
    assert calls == 2


@pytest.mark.asyncio
async def test_permission_shell_wildcard_matching(monkeypatch):
    # Item 3: shell command wildcard rule matches raw command in request.path
    from vallen_cli.core.config import get_config
    cfg = get_config()
    monkeypatch.setattr(cfg, "get", lambda key, default=None: {"shell:git *": "allow"} if key == "permissions" else default)

    pm = PermissionManager()
    req = PermRequest(tool_name="shell", description="Run: git status", path="git status")
    reply = await pm.check(req)
    assert reply == PermReply.ONCE


@pytest.mark.asyncio
async def test_permission_apply_patch_wildcard_deny(monkeypatch):
    # Item 2: rule apply_patch:*.env denies patch targeting .env file
    from vallen_cli.core.config import get_config
    cfg = get_config()
    monkeypatch.setattr(cfg, "get", lambda key, default=None: {"apply_patch:*.env": "deny"} if key == "permissions" else default)

    pm = PermissionManager()
    req = PermRequest(tool_name="apply_patch", description="Apply patch to .env", path=".env")
    reply = await pm.check(req)
    assert reply == PermReply.REJECT

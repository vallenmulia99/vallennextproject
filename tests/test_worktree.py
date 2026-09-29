import asyncio
import subprocess

from vallen_cli.core.worktree import create_worktree, remove_worktree


def test_worktree_lifecycle(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "Test"], check=True)
    (tmp_path / "file.txt").write_text("base")
    subprocess.run(["git", "-C", str(tmp_path), "add", "file.txt"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "init"], check=True)

    path, branch = asyncio.run(create_worktree(str(tmp_path)))
    assert path.exists()
    assert (path / "file.txt").read_text() == "base"
    asyncio.run(remove_worktree(str(tmp_path), path, branch))
    assert not path.exists()


def test_collect_diff_includes_new_files(tmp_path):
    """Regression test for batch3 bug #2: new files must appear in diff."""
    from vallen_cli.core.worktree import create_worktree, collect_diff, remove_worktree

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "Test"], check=True)
    (tmp_path / "base.txt").write_text("base")
    subprocess.run(["git", "-C", str(tmp_path), "add", "base.txt"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "init"], check=True)

    path, branch = asyncio.run(create_worktree(str(tmp_path)))
    # Create new file in worktree
    (path / "new_file.txt").write_text("new content")
    # Edit existing file
    (path / "base.txt").write_text("modified")

    stat, patch = asyncio.run(collect_diff(str(tmp_path), path))
    
    # Both new and modified files must appear in diff
    assert "new_file.txt" in patch, "New file missing from diff"
    assert "base.txt" in patch, "Modified file missing from diff"
    assert "+new content" in patch
    assert "+modified" in patch

    asyncio.run(remove_worktree(str(tmp_path), path, branch))


def test_prune_orphan_worktrees(tmp_path):
    from vallen_cli.core.worktree import prune_orphan_worktrees

    orphan = tmp_path / ".vallen" / "worktrees" / "orphan"
    orphan.mkdir(parents=True)
    (orphan / "stale.txt").write_text("stale")
    removed = asyncio.run(prune_orphan_worktrees(str(tmp_path)))
    assert removed == 1
    assert not orphan.exists()

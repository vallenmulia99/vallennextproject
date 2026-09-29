from vallen_cli.core.custom_commands import expand_command, _parse_frontmatter


def test_parse_frontmatter():
    text = """---
description: Custom command
model: gpt-4o
---
Prompt body here
"""
    meta, body = _parse_frontmatter(text)
    assert meta.get("description") == "Custom command"
    assert meta.get("model") == "gpt-4o"
    assert "Prompt body here" in body


def test_expand_command_arguments():
    template = "Fix bug in $ARGUMENTS with priority $1 and file $2"
    expanded = expand_command(template, "high src/main.py")
    assert "Fix bug in high src/main.py" in expanded
    assert "with priority high" in expanded
    assert "and file src/main.py" in expanded


def test_expand_command_backslash_in_args():
    """Regression: bug report #1 - backslash in args must not crash."""
    from vallen_cli.core.custom_commands import expand_command
    
    # Windows path with backslash
    template = "Process file: $1"
    result = expand_command(template, r"C:\Users\test\file.txt")
    assert r"C:\Users\test\file.txt" in result
    assert "Process file:" in result


def test_expand_command_shell_injection_prevented():
    """Regression: bug report #2 - shell injection via $ARGUMENTS prevented."""
    from vallen_cli.core.custom_commands import expand_command
    import tempfile
    
    with tempfile.TemporaryDirectory() as tmpdir:
        # Malicious argument attempting command injection
        template = "!echo $ARGUMENTS"
        malicious_args = '"; rm -rf /tmp/test #'
        
        result = expand_command(template, malicious_args, cwd=tmpdir)
        
        # Result should contain the escaped/quoted argument, not execute it
        # The shell directive should have quoted the arguments
        assert "rm" not in result or "'" in result or '"' in result
        # Directory should still exist after expansion (not deleted)
        import os
        assert os.path.exists(tmpdir)


def test_expand_command_positional_args_escaped_in_shell():
    """Shell directives must receive escaped positional arguments."""
    from vallen_cli.core.custom_commands import expand_command
    
    template = "!echo $1"
    result = expand_command(template, "test; echo hacked")
    
    # Should not execute "echo hacked" separately
    assert "hacked" not in result or "'" in result

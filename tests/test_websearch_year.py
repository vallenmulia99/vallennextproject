"""Tests for websearch year placeholder."""
import pytest
from vallen_cli.tools.websearch_tool import WebSearchTool


def test_websearch_year_placeholder_substituted():
    """Regression: bug report 5 #3 - {{year}} must be replaced with current year."""
    tool = WebSearchTool()
    desc = tool.description
    
    # Should not contain literal {{year}}
    assert "{{year}}" not in desc
    
    # Should contain actual year (2026 based on context)
    assert "2026" in desc or str(__import__("datetime").datetime.now().year) in desc

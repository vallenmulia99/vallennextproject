"""Tests for config.py fixes."""
import pytest
from vallen_cli.core.config import _deep_merge, DEFAULT_CONFIG


def test_default_temperature_is_tuned_for_coding_agents():
    assert DEFAULT_CONFIG["general"]["temperature"] == 0.2


def test_deep_merge_does_not_mutate_base():
    """Regression test for batch4 bug #1: _deep_merge must not mutate base dict."""
    original_providers = dict(DEFAULT_CONFIG.get("providers", {}))
    
    # Merge with override
    result = _deep_merge(DEFAULT_CONFIG, {"providers": {"test": {"base_url": "http://test"}}})
    
    # Mutate nested dict in result
    if "providers" in result and "test" in result["providers"]:
        result["providers"]["test"]["base_url"] = "http://mutated"
    
    # DEFAULT_CONFIG should be unchanged
    assert DEFAULT_CONFIG.get("providers") == original_providers, \
        "DEFAULT_CONFIG was mutated by _deep_merge"


def test_deep_merge_nested_independence():
    """Verify nested dicts in result are independent copies."""
    base = {"a": {"b": {"c": 1}}}
    result = _deep_merge(base, {})
    
    # Mutate result
    result["a"]["b"]["c"] = 999
    
    # Base unchanged
    assert base["a"]["b"]["c"] == 1


def test_vallennext_provider_default():
    """Verify vallennext provider exists in default config."""
    assert "vallennext" in DEFAULT_CONFIG["providers"]
    prov = DEFAULT_CONFIG["providers"]["vallennext"]
    assert prov["model"] == "vallennext/free"
    assert prov["base_url"] == "https://apikeyfreevallennext.vercel.app/v1"
    assert prov["api_key"] == "free"


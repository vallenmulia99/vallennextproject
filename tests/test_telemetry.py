from vallen_cli.core.telemetry import record_usage, usage_summary
from vallen_cli.core.workspace import get_workspace


def test_usage_telemetry_persists(tmp_path):
    get_workspace().new_project(str(tmp_path))
    record_usage(kind="agent", model="test", input_tokens=10, output_tokens=4, rounds=2)
    record_usage(kind="subagent", model="test", input_tokens=5, output_tokens=3, rounds=1)
    assert usage_summary() == {"runs": 2, "input_tokens": 15, "output_tokens": 7, "rounds": 3}

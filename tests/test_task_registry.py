from vallen_cli.core.task_registry import get_task, list_tasks, record_task
from vallen_cli.core.workspace import get_workspace


def test_task_registry_persists_task_metadata(tmp_path):
    get_workspace().new_project(str(tmp_path))
    record_task("task_test", status="running", description="inspect repo")
    record_task("task_test", status="completed", rounds=2)

    task = get_task("task_test")
    assert task is not None
    assert task["status"] == "completed"
    assert task["description"] == "inspect repo"
    assert task["rounds"] == 2
    assert list_tasks()[0]["task_id"] == "task_test"


def test_task_registry_recovers_running_tasks(tmp_path):
    from vallen_cli.core.task_registry import recover_running_tasks

    get_workspace().new_project(str(tmp_path))
    record_task("task_crashed", status="running")
    assert recover_running_tasks() == ["task_crashed"]
    assert get_task("task_crashed")["status"] == "interrupted"


def test_task_transcript_persists(tmp_path):
    from vallen_cli.core.task_registry import load_task_messages, save_task_messages

    get_workspace().new_project(str(tmp_path))
    messages = [{"role": "system", "content": "worker"}, {"role": "user", "content": "inspect"}]
    save_task_messages("task_transcript", messages)
    assert load_task_messages("task_transcript") == messages

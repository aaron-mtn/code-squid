from agent.coding import CodingAgent
from core.session import Session


def test_should_stop_accepts_final_summary_with_marker_on_last_non_empty_line() -> None:
    agent = CodingAgent("demo task")
    session = Session(repo_root=None)
    session.messages = [
        {
            "role": "assistant",
            "content": "Files changed: a.py\nWhat changed: fixed the bug\nTASK COMPLETE",
        }
    ]

    assert agent.is_final_content(session.messages[-1]["content"]) is True
    assert agent.should_stop(session) is True


def test_should_stop_rejects_marker_when_not_on_last_non_empty_line() -> None:
    agent = CodingAgent("demo task")
    session = Session(repo_root=None)
    session.messages = [
        {
            "role": "assistant",
            "content": "TASK COMPLETE\nNeed to keep working",
        }
    ]

    assert agent.is_final_content(session.messages[-1]["content"]) is False
    assert agent.should_stop(session) is False

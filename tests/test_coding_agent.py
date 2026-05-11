from agent.coding import CodingAgent
from core.session import Session


def test_validate_reply_rejects_final_summary_missing_required_sections() -> None:
    agent = CodingAgent("demo task")
    reply = {
        "message": {
            "content": "Files changed: a.py\nWhat changed: fixed the bug\nTASK COMPLETE",
        },
        "actions": [],
    }

    validation = agent.validate_reply(reply)

    assert validation == {
        "ok": False,
        "reason": "final_missing_required_sections",
    }


def test_validate_reply_accepts_final_summary_with_all_required_sections() -> None:
    agent = CodingAgent("demo task")
    reply = {
        "message": {
            "content": (
                "Files changed: a.py\n"
                "What changed: fixed the bug\n"
                "Verification run: pytest\n"
                "Remaining risks: none\n"
                "TASK COMPLETE"
            ),
        },
        "actions": [],
    }

    validation = agent.validate_reply(reply)

    assert validation == {
        "ok": True,
        "reason": "",
    }


def test_should_stop_accepts_final_summary_with_marker_on_last_non_empty_line() -> None:
    agent = CodingAgent("demo task")
    session = Session(repo_root=None)
    session.messages = [
        {
            "role": "assistant",
            "content": (
                "Files changed: a.py\n"
                "What changed: fixed the bug\n"
                "Verification run: pytest\n"
                "Remaining risks: none\n"
                "TASK COMPLETE"
            ),
        }
    ]

    assert agent.is_final_content(session.messages[-1]["content"]) is True
    assert agent.should_stop(session) is True


def test_should_stop_rejects_marker_when_missing_required_sections() -> None:
    agent = CodingAgent("demo task")
    session = Session(repo_root=None)
    session.messages = [
        {
            "role": "assistant",
            "content": "Files changed: a.py\nWhat changed: fixed the bug\nTASK COMPLETE",
        }
    ]

    assert agent.is_final_content(session.messages[-1]["content"]) is True
    assert agent.should_stop(session) is False


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

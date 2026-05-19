import json

from core.agent_loop import AgentLoop
from core.approval import ApprovalPolicy
from core.session import Session
from core.tool_results import ToolResults


class FakeAgent:
    def initial_messages(self) -> list[dict]:
        return [{"role": "system", "content": "system"}]

    def tool_definitions(self) -> list[dict]:
        return []

    def should_stop(self, session: Session) -> bool:
        return any(
            message["role"] == "assistant" and message["content"] == "TASK COMPLETE"
            for message in session.messages
        )

    def validate_reply(self, reply: dict) -> dict:
        if reply.get("reason"):
            return {"ok": False, "reason": reply["reason"]}
        return {"ok": True, "reason": ""}

    def correction_message_for(self, reason: str) -> dict:
        return {"role": "user", "content": f"correction:{reason}"}

    def failure_message_for_invalid_replies(self, reason: str, count: int) -> dict:
        return {
            "role": "assistant",
            "content": (
                f"Code Squid stopped after {count} consecutive invalid replies.\n"
                f"Last invalid reply reason: {reason}\n"
                "Explanation: the model tried to finalize without the required summary sections"
            ),
        }


class FakeModelAdapter:
    def __init__(self, replies: list[dict]) -> None:
        self.replies = replies
        self.index = 0

    def respond(self, messages: list[dict], tool_definitions: list[dict]) -> dict:
        reply = self.replies[self.index]
        self.index += 1
        return reply


class FakeToolExecutor:
    def __init__(self) -> None:
        self.actions = []

    def execute(self, action: dict) -> dict:
        self.actions.append(action)
        return {"ok": True, "tool": action["tool"]}


class FakeToolResults:
    def messages_from_action_results(self, actions: list[dict], results: list[dict]) -> list[dict]:
        return [{"role": "tool", "content": result["tool"]} for result in results]


class FakePrompter:
    def __init__(self, approved: bool) -> None:
        self.approved = approved

    def approve_action(self, action: dict) -> bool:
        return self.approved


class FakeSessionStore:
    def __init__(self) -> None:
        self.messages = []
        self.statuses = []

    def append_message(self, message: dict, usage: dict | None = None) -> None:
        self.messages.append({"message": message, "usage": usage})

    def update_status(self, status: str) -> None:
        self.statuses.append(status)


class NullDisplay:
    def __init__(self) -> None:
        self.step_limits_reached = []

    def thinking(self) -> None:
        pass

    def assistant_message(self, content: str) -> None:
        pass

    def debug_reply(self, reply: dict) -> None:
        pass

    def reply_rejected(self, reason: str) -> None:
        pass

    def repeated_invalid_replies(self, reason: str, count: int) -> None:
        pass

    def step_limit_reached(self, max_tool_steps: int) -> None:
        self.step_limits_reached.append(max_tool_steps)

    def action_started(self, action: dict) -> None:
        pass

    def tool_result(self, action: dict, result: dict) -> None:
        pass


def reply(content: str, actions: list[dict] | None = None, reason: str = "") -> dict:
    return {
        "message": {"role": "assistant", "content": content},
        "actions": actions or [],
        "reason": reason,
    }


def run_loop(
    replies: list[dict],
    max_tool_steps: int | None = None,
    approval_policy: ApprovalPolicy | None = None,
) -> tuple[Session, FakeToolExecutor, FakeModelAdapter, NullDisplay]:
    session = Session(repo_root=None)
    tool_executor = FakeToolExecutor()
    model_adapter = FakeModelAdapter(replies)
    display = NullDisplay()
    loop = AgentLoop(
        session=session,
        model_adapter=model_adapter,
        tool_executor=tool_executor,
        tool_results=FakeToolResults(),
        agent=FakeAgent(),
        display=display,
        max_tool_steps=max_tool_steps,
        approval_policy=approval_policy,
    )

    loop.run()

    return session, tool_executor, model_adapter, display


def run_loop_with_store(
    replies: list[dict],
    max_tool_steps: int | None = None,
) -> tuple[Session, FakeToolExecutor, FakeSessionStore, FakeModelAdapter, NullDisplay]:
    session = Session(repo_root=None)
    tool_executor = FakeToolExecutor()
    session_store = FakeSessionStore()
    model_adapter = FakeModelAdapter(replies)
    display = NullDisplay()
    loop = AgentLoop(
        session=session,
        model_adapter=model_adapter,
        tool_executor=tool_executor,
        tool_results=FakeToolResults(),
        agent=FakeAgent(),
        display=display,
        session_store=session_store,
        max_tool_steps=max_tool_steps,
    )

    loop.run()

    return session, tool_executor, session_store, model_adapter, display


def test_valid_reply_resets_consecutive_invalid_reply_counter() -> None:
    session, tool_executor, _, _ = run_loop(
        [
            reply("bad 1", reason="non_final_no_tool_reply"),
            reply("bad 2", reason="non_final_no_tool_reply"),
            reply("valid", actions=[{"tool": "read_file"}]),
            reply("bad 3", reason="non_final_no_tool_reply"),
            reply("bad 4", reason="non_final_no_tool_reply"),
            reply("TASK COMPLETE"),
        ]
    )

    assert [message["content"] for message in session.messages].count(
        "correction:non_final_no_tool_reply"
    ) == 4
    assert session.messages[-1]["content"] == "TASK COMPLETE"
    assert tool_executor.actions == [{"tool": "read_file"}]


def test_invalid_replies_get_normal_correction_before_limit() -> None:
    session, _, _, _ = run_loop(
        [
            reply("bad 1", reason="non_final_no_tool_reply"),
            reply("bad 2", reason="non_final_wrong_tool_count"),
            reply("TASK COMPLETE"),
        ]
    )

    assert {"role": "user", "content": "correction:non_final_no_tool_reply"} in session.messages
    assert {"role": "user", "content": "correction:non_final_wrong_tool_count"} in session.messages


def test_loop_stops_after_three_consecutive_invalid_replies() -> None:
    session, _, _, _ = run_loop(
        [
            reply("bad 1", reason="non_final_no_tool_reply"),
            reply("bad 2", reason="non_final_wrong_tool_count"),
            reply("bad 3", reason="final_missing_required_sections"),
            reply("TASK COMPLETE"),
        ]
    )

    assert session.messages[-1] == {
        "role": "assistant",
        "content": (
            "Code Squid stopped after 3 consecutive invalid replies.\n"
            "Last invalid reply reason: final_missing_required_sections\n"
            "Explanation: the model tried to finalize without the required summary sections"
        ),
    }


def test_initial_and_valid_assistant_messages_are_persisted() -> None:
    _, _, session_store, _, _ = run_loop_with_store([reply("TASK COMPLETE")])

    assert [entry["message"] for entry in session_store.messages] == [
        {"role": "system", "content": "system"},
        {"role": "assistant", "content": "TASK COMPLETE"},
    ]


def test_preloaded_session_does_not_get_duplicate_initial_messages() -> None:
    session = Session(repo_root=None)
    session.add_messages(
        {"role": "system", "content": "saved system"},
        {"role": "user", "content": "saved follow-up"},
    )
    session_store = FakeSessionStore()
    loop = AgentLoop(
        session=session,
        model_adapter=FakeModelAdapter([reply("TASK COMPLETE")]),
        tool_executor=FakeToolExecutor(),
        tool_results=FakeToolResults(),
        agent=FakeAgent(),
        display=NullDisplay(),
        session_store=session_store,
    )

    loop.run()

    assert session.messages == [
        {"role": "system", "content": "saved system"},
        {"role": "user", "content": "saved follow-up"},
        {"role": "assistant", "content": "TASK COMPLETE"},
    ]
    assert [entry["message"] for entry in session_store.messages] == [
        {"role": "assistant", "content": "TASK COMPLETE"},
    ]


def test_correction_messages_are_persisted_and_rejected_invalid_replies_are_not() -> None:
    _, _, session_store, _, _ = run_loop_with_store(
        [
            reply("bad 1", reason="non_final_no_tool_reply"),
            reply("TASK COMPLETE"),
        ]
    )

    persisted_messages = [entry["message"] for entry in session_store.messages]

    assert {"role": "user", "content": "correction:non_final_no_tool_reply"} in persisted_messages
    assert {"role": "assistant", "content": "bad 1"} not in persisted_messages


def test_failure_message_is_persisted_after_repeated_invalid_replies() -> None:
    _, _, session_store, _, _ = run_loop_with_store(
        [
            reply("bad 1", reason="non_final_no_tool_reply"),
            reply("bad 2", reason="non_final_wrong_tool_count"),
            reply("bad 3", reason="final_missing_required_sections"),
        ]
    )

    assert session_store.messages[-1]["message"] == {
        "role": "assistant",
        "content": (
            "Code Squid stopped after 3 consecutive invalid replies.\n"
            "Last invalid reply reason: final_missing_required_sections\n"
            "Explanation: the model tried to finalize without the required summary sections"
        ),
    }
    assert {"role": "assistant", "content": "bad 3"} not in [
        entry["message"] for entry in session_store.messages
    ]


def test_tool_result_messages_are_persisted() -> None:
    _, _, session_store, _, _ = run_loop_with_store(
        [
            reply("valid", actions=[{"tool": "read_file"}]),
            reply("TASK COMPLETE"),
        ]
    )

    assert {"role": "tool", "content": "read_file"} in [
        entry["message"] for entry in session_store.messages
    ]


def test_approval_denial_does_not_execute_tool_action() -> None:
    session, tool_executor, _, _ = run_loop(
        [
            reply(
                "valid",
                actions=[{"tool": "read_file", "tool_call_id": "call_1"}],
            ),
            reply("TASK COMPLETE"),
        ],
        approval_policy=ApprovalPolicy("always", prompter=FakePrompter(approved=False)),
    )

    assert tool_executor.actions == []
    assert session.messages[-1]["content"] == "TASK COMPLETE"


def test_approval_denial_appends_normal_denied_tool_result_message() -> None:
    session = Session(repo_root=None)
    tool_executor = FakeToolExecutor()
    loop = AgentLoop(
        session=session,
        model_adapter=FakeModelAdapter(
            [
                reply(
                    "valid",
                    actions=[{"tool": "read_file", "tool_call_id": "call_1"}],
                ),
                reply("TASK COMPLETE"),
            ]
        ),
        tool_executor=tool_executor,
        tool_results=ToolResults(),
        agent=FakeAgent(),
        display=NullDisplay(),
        approval_policy=ApprovalPolicy("always", prompter=FakePrompter(approved=False)),
    )

    loop.run()

    tool_messages = [message for message in session.messages if message["role"] == "tool"]
    assert len(tool_messages) == 1
    assert tool_messages[0]["tool_call_id"] == "call_1"
    assert json.loads(tool_messages[0]["content"]) == {
        "ok": False,
        "tool": "read_file",
        "error": "user denied tool action",
    }


def test_complete_status_is_written_on_normal_completion() -> None:
    _, _, session_store, _, _ = run_loop_with_store([reply("TASK COMPLETE")])

    assert session_store.statuses == ["complete"]


def test_failed_status_is_written_after_repeated_invalid_replies() -> None:
    _, _, session_store, _, _ = run_loop_with_store(
        [
            reply("bad 1", reason="non_final_no_tool_reply"),
            reply("bad 2", reason="non_final_wrong_tool_count"),
            reply("bad 3", reason="final_missing_required_sections"),
        ]
    )

    assert session_store.statuses == ["failed"]


def test_default_max_tool_steps_does_not_stop_normal_behavior() -> None:
    session, tool_executor, model_adapter, display = run_loop(
        [
            reply("valid", actions=[{"tool": "read_file"}]),
            reply("TASK COMPLETE"),
        ]
    )

    assert session.messages[-1]["content"] == "TASK COMPLETE"
    assert tool_executor.actions == [{"tool": "read_file"}]
    assert model_adapter.index == 2
    assert display.step_limits_reached == []


def test_max_tool_steps_one_stops_before_next_model_reply() -> None:
    session, tool_executor, session_store, model_adapter, display = run_loop_with_store(
        [
            reply("valid", actions=[{"tool": "read_file"}]),
            reply("TASK COMPLETE"),
        ],
        max_tool_steps=1,
    )

    assert tool_executor.actions == [{"tool": "read_file"}]
    assert {"role": "tool", "content": "read_file"} in session.messages
    assert model_adapter.index == 1
    assert session.messages[-1] == {"role": "tool", "content": "read_file"}
    assert session_store.statuses == ["failed"]
    assert display.step_limits_reached == [1]


def test_invalid_rejected_replies_do_not_count_toward_tool_step_limit() -> None:
    session, tool_executor, _, model_adapter, display = run_loop_with_store(
        [
            reply("bad 1", reason="non_final_no_tool_reply"),
            reply("valid", actions=[{"tool": "read_file"}]),
            reply("TASK COMPLETE"),
        ],
        max_tool_steps=1,
    )

    assert {"role": "user", "content": "correction:non_final_no_tool_reply"} in session.messages
    assert tool_executor.actions == [{"tool": "read_file"}]
    assert model_adapter.index == 2
    assert display.step_limits_reached == [1]


def test_final_reply_without_tool_actions_does_not_count_toward_tool_step_limit() -> None:
    session, tool_executor, session_store, model_adapter, display = run_loop_with_store(
        [reply("TASK COMPLETE")],
        max_tool_steps=1,
    )

    assert session.messages[-1]["content"] == "TASK COMPLETE"
    assert tool_executor.actions == []
    assert model_adapter.index == 1
    assert session_store.statuses == ["complete"]
    assert display.step_limits_reached == []

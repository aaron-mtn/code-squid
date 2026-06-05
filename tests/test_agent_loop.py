import json

from core.agent_loop import AgentLoop, RunResult
from core.approval import ApprovalDecision, ApprovalPolicy
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
                "Explanation: the model replied with no tool call and no final content"
            ),
        }


class FakeModelAdapter:
    def __init__(self, replies: list[dict], events: list[str] | None = None) -> None:
        self.replies = replies
        self.index = 0
        self.events = events

    def respond(self, messages: list[dict], tool_definitions: list[dict]) -> dict:
        if self.events is not None:
            self.events.append("respond")
        reply = self.replies[self.index]
        self.index += 1
        return reply


class FakeToolExecutor:
    def __init__(self, repo_root=None) -> None:
        self.repo_root = repo_root
        self.actions = []

    def execute(self, action: dict) -> dict:
        self.actions.append(action)
        return {"ok": True, "tool": action["tool"]}


class FakeToolResults:
    def messages_from_action_results(self, actions: list[dict], results: list[dict]) -> list[dict]:
        return [{"role": "tool", "content": result["tool"]} for result in results]


class FakePrompter:
    def __init__(self, decision: ApprovalDecision) -> None:
        self.decision = decision
        self.actions = []

    def approve_action(self, action: dict) -> ApprovalDecision:
        self.actions.append(action)
        return self.decision


class FakeSessionStore:
    def __init__(self) -> None:
        self.messages = []
        self.compactions = []
        self.statuses = []

    def append_message(self, message: dict, usage: dict | None = None) -> None:
        self.messages.append({"message": message, "usage": usage})

    def append_compaction(self, metadata: dict) -> None:
        self.compactions.append(metadata)

    def update_status(self, status: str) -> None:
        self.statuses.append(status)


class NullDisplay:
    def __init__(self, events: list[str] | None = None) -> None:
        self.step_limits_reached = []
        self.assistant_messages = []
        self.final_messages = []
        self.debug_replies = []
        self.rejected_replies = []
        self.debug = False
        self.events = events

    def thinking(self) -> None:
        if self.events is not None:
            self.events.append("thinking")

    def assistant_message(self, content: str) -> None:
        self.assistant_messages.append(content)

    def final_message(self, content: str) -> None:
        self.final_messages.append(content)

    def debug_reply(self, reply: dict) -> None:
        self.debug_replies.append(reply)

    def reply_rejected(self, reason: str) -> None:
        self.rejected_replies.append(reason)

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


class FakeCompactor:
    def __init__(self, metadata: dict | None = None, events: list[str] | None = None) -> None:
        self.metadata = metadata
        self.events = events
        self.sessions = []

    def maybe_compact(self, session: Session) -> dict | None:
        if self.events is not None:
            self.events.append("compact")
        self.sessions.append(session)
        return self.metadata


class StopImmediatelyAgent(FakeAgent):
    def should_stop(self, session: Session) -> bool:
        return True


def run_loop(
    replies: list[dict],
    max_tool_steps: int | None = None,
    approval_policy: ApprovalPolicy | None = None,
    compactor: FakeCompactor | None = None,
    repo_root=None,
) -> tuple[Session, FakeToolExecutor, FakeModelAdapter, NullDisplay]:
    session = Session(repo_root=repo_root)
    tool_executor = FakeToolExecutor(repo_root=repo_root)
    model_adapter = FakeModelAdapter(replies)
    display = NullDisplay()
    loop = AgentLoop(
        session=session,
        model_adapter=model_adapter,
        tool_executor=tool_executor,
        tool_results=FakeToolResults(),
        agent=FakeAgent(),
        display=display,
        compactor=compactor,
        max_tool_steps=max_tool_steps,
        approval_policy=approval_policy,
    )

    loop.run()

    return session, tool_executor, model_adapter, display


def run_loop_with_store(
    replies: list[dict],
    max_tool_steps: int | None = None,
    compactor: FakeCompactor | None = None,
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
        compactor=compactor,
        max_tool_steps=max_tool_steps,
    )

    loop.run()

    return session, tool_executor, session_store, model_adapter, display


def test_valid_reply_resets_consecutive_invalid_reply_counter() -> None:
    session, tool_executor, _, _ = run_loop(
        [
            reply("bad 1", reason="empty_final_reply"),
            reply("bad 2", reason="empty_final_reply"),
            reply("valid", actions=[{"tool": "read_file"}]),
            reply("bad 3", reason="empty_final_reply"),
            reply("bad 4", reason="empty_final_reply"),
            reply("TASK COMPLETE"),
        ]
    )

    assert [message["content"] for message in session.messages].count(
        "correction:empty_final_reply"
    ) == 4
    assert session.messages[-1]["content"] == "TASK COMPLETE"
    assert tool_executor.actions == [{"tool": "read_file"}]


def test_invalid_replies_get_normal_correction_before_limit() -> None:
    session, _, _, _ = run_loop(
        [
            reply("bad 1", reason="empty_final_reply"),
            reply("bad 2", reason="non_final_too_many_tool_calls"),
            reply("TASK COMPLETE"),
        ]
    )

    assert {"role": "user", "content": "correction:empty_final_reply"} in session.messages
    assert {"role": "user", "content": "correction:non_final_too_many_tool_calls"} in session.messages


def test_loop_stops_after_three_consecutive_invalid_replies() -> None:
    session, _, _, _ = run_loop(
        [
            reply("bad 1", reason="empty_final_reply"),
            reply("bad 2", reason="non_final_too_many_tool_calls"),
            reply("bad 3", reason="empty_final_reply"),
            reply("TASK COMPLETE"),
        ]
    )

    assert session.messages[-1] == {
        "role": "assistant",
        "content": (
            "Code Squid stopped after 3 consecutive invalid replies.\n"
            "Last invalid reply reason: empty_final_reply\n"
            "Explanation: the model replied with no tool call and no final content"
        ),
    }


def test_normal_completion_returns_complete_run_result() -> None:
    session = Session(repo_root=None)
    loop = AgentLoop(
        session=session,
        model_adapter=FakeModelAdapter([reply("TASK COMPLETE")]),
        tool_executor=FakeToolExecutor(),
        tool_results=FakeToolResults(),
        agent=FakeAgent(),
        display=NullDisplay(),
    )

    result = loop.run()

    assert result == RunResult(status="complete")


def test_repeated_invalid_replies_return_failed_run_result() -> None:
    session = Session(repo_root=None)
    loop = AgentLoop(
        session=session,
        model_adapter=FakeModelAdapter(
            [
                reply("bad 1", reason="empty_final_reply"),
                reply("bad 2", reason="non_final_too_many_tool_calls"),
                reply("bad 3", reason="empty_final_reply"),
            ]
        ),
        tool_executor=FakeToolExecutor(),
        tool_results=FakeToolResults(),
        agent=FakeAgent(),
        display=NullDisplay(),
    )

    result = loop.run()

    assert result == RunResult(
        status="failed",
        reason="empty_final_reply",
    )


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


def test_compactor_is_called_before_thinking_and_next_model_reply() -> None:
    events = []
    session = Session(repo_root=None)
    loop = AgentLoop(
        session=session,
        model_adapter=FakeModelAdapter([reply("TASK COMPLETE")], events=events),
        tool_executor=FakeToolExecutor(),
        tool_results=FakeToolResults(),
        agent=FakeAgent(),
        display=NullDisplay(events=events),
        compactor=FakeCompactor(events=events),
    )

    loop.run()

    assert events[:3] == ["compact", "thinking", "respond"]


def test_compaction_metadata_is_persisted_when_store_exists() -> None:
    metadata = {"estimated_tokens_before": 10, "estimated_tokens_after": 4}
    _, _, session_store, _, _ = run_loop_with_store(
        [reply("TASK COMPLETE")],
        compactor=FakeCompactor(metadata),
    )

    assert session_store.compactions == [metadata]


def test_compaction_without_metadata_is_not_persisted() -> None:
    _, _, session_store, _, _ = run_loop_with_store(
        [reply("TASK COMPLETE")],
        compactor=FakeCompactor(None),
    )

    assert session_store.compactions == []


def test_compactor_is_not_called_when_session_already_stopped() -> None:
    compactor = FakeCompactor()
    session = Session(repo_root=None)
    loop = AgentLoop(
        session=session,
        model_adapter=FakeModelAdapter([]),
        tool_executor=FakeToolExecutor(),
        tool_results=FakeToolResults(),
        agent=StopImmediatelyAgent(),
        display=NullDisplay(),
        compactor=compactor,
    )

    loop.run()

    assert compactor.sessions == []


def test_compactor_is_not_called_after_step_limit_stops_loop() -> None:
    compactor = FakeCompactor()

    run_loop_with_store(
        [
            reply("valid", actions=[{"tool": "read_file"}]),
            reply("TASK COMPLETE"),
        ],
        max_tool_steps=1,
        compactor=compactor,
    )

    assert len(compactor.sessions) == 1


def test_correction_messages_are_persisted_and_rejected_invalid_replies_are_not() -> None:
    _, _, session_store, _, _ = run_loop_with_store(
        [
            reply("bad 1", reason="empty_final_reply"),
            reply("TASK COMPLETE"),
        ]
    )

    persisted_messages = [entry["message"] for entry in session_store.messages]

    assert {"role": "user", "content": "correction:empty_final_reply"} in persisted_messages
    assert {"role": "assistant", "content": "bad 1"} not in persisted_messages


def test_invalid_assistant_reply_is_not_displayed_in_normal_mode() -> None:
    _, _, _, display = run_loop(
        [
            reply("bad 1", reason="empty_final_reply"),
            reply("TASK COMPLETE"),
        ]
    )

    assert display.assistant_messages == []
    assert display.final_messages == ["TASK COMPLETE"]
    assert display.rejected_replies == ["empty_final_reply"]
    assert display.debug_replies[0]["message"]["content"] == "bad 1"


def test_no_tool_final_reply_uses_final_display_path() -> None:
    _, _, _, display = run_loop([reply("TASK COMPLETE")])

    assert display.final_messages == ["TASK COMPLETE"]
    assert display.assistant_messages == []


def test_one_tool_reply_uses_normal_assistant_display_path() -> None:
    _, _, _, display = run_loop(
        [
            reply("Using read_file.", actions=[{"tool": "read_file"}]),
            reply("TASK COMPLETE"),
        ]
    )

    assert display.assistant_messages == ["Using read_file."]
    assert display.final_messages == ["TASK COMPLETE"]


def test_invalid_assistant_reply_is_displayed_in_debug_mode() -> None:
    session = Session(repo_root=None)
    display = NullDisplay()
    display.debug = True
    loop = AgentLoop(
        session=session,
        model_adapter=FakeModelAdapter(
            [
                reply("bad 1", reason="empty_final_reply"),
                reply("TASK COMPLETE"),
            ]
        ),
        tool_executor=FakeToolExecutor(),
        tool_results=FakeToolResults(),
        agent=FakeAgent(),
        display=display,
    )

    loop.run()

    assert display.assistant_messages == ["bad 1"]
    assert display.final_messages == ["TASK COMPLETE"]
    assert display.rejected_replies == ["empty_final_reply"]


def test_failure_message_is_persisted_after_repeated_invalid_replies() -> None:
    _, _, session_store, _, _ = run_loop_with_store(
        [
            reply("bad 1", reason="empty_final_reply"),
            reply("bad 2", reason="non_final_too_many_tool_calls"),
            reply("bad 3", reason="empty_final_reply"),
        ]
    )

    assert session_store.messages[-1]["message"] == {
        "role": "assistant",
        "content": (
            "Code Squid stopped after 3 consecutive invalid replies.\n"
            "Last invalid reply reason: empty_final_reply\n"
            "Explanation: the model replied with no tool call and no final content"
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
        approval_policy=ApprovalPolicy(
            "always",
            prompter=FakePrompter(ApprovalDecision(approved=False)),
        ),
    )

    assert tool_executor.actions == []
    assert session.messages[-1]["content"] == "TASK COMPLETE"


def test_guarded_allows_inside_workspace_read_file_without_approval(tmp_path) -> None:
    target = tmp_path / "README.md"
    target.write_text("hello", encoding="utf-8")
    prompter = FakePrompter(ApprovalDecision(approved=False))

    _, tool_executor, _, _ = run_loop(
        [
            reply("valid", actions=[{"tool": "read_file", "args": {"path": str(target)}}]),
            reply("TASK COMPLETE"),
        ],
        approval_policy=ApprovalPolicy("guarded", prompter=prompter),
        repo_root=tmp_path,
    )

    assert prompter.actions == []
    assert tool_executor.actions == [
        {"tool": "read_file", "args": {"path": str(target)}}
    ]


def test_guarded_allows_inside_workspace_write_file_without_approval(tmp_path) -> None:
    target = tmp_path / "README.md"
    prompter = FakePrompter(ApprovalDecision(approved=False))

    _, tool_executor, _, _ = run_loop(
        [
            reply(
                "valid",
                actions=[
                    {
                        "tool": "write_file",
                        "args": {"path": str(target), "content": "hello"},
                    }
                ],
            ),
            reply("TASK COMPLETE"),
        ],
        approval_policy=ApprovalPolicy("guarded", prompter=prompter),
        repo_root=tmp_path,
    )

    assert prompter.actions == []
    assert tool_executor.actions == [
        {"tool": "write_file", "args": {"path": str(target), "content": "hello"}}
    ]


def test_guarded_allows_inside_workspace_apply_patch_without_approval(tmp_path) -> None:
    target = tmp_path / "README.md"
    target.write_text("hello", encoding="utf-8")
    prompter = FakePrompter(ApprovalDecision(approved=False))

    _, tool_executor, _, _ = run_loop(
        [
            reply(
                "valid",
                actions=[
                    {
                        "tool": "apply_patch",
                        "args": {
                            "path": str(target),
                            "old_text": "hello",
                            "new_text": "goodbye",
                        },
                    }
                ],
            ),
            reply("TASK COMPLETE"),
        ],
        approval_policy=ApprovalPolicy("guarded", prompter=prompter),
        repo_root=tmp_path,
    )

    assert prompter.actions == []
    assert tool_executor.actions == [
        {
            "tool": "apply_patch",
            "args": {
                "path": str(target),
                "old_text": "hello",
                "new_text": "goodbye",
            },
        }
    ]


def test_guarded_asks_for_outside_workspace_file_tool(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside.txt"
    workspace.mkdir()
    prompter = FakePrompter(ApprovalDecision(approved=False))

    _, tool_executor, _, _ = run_loop(
        [
            reply(
                "valid",
                actions=[{"tool": "read_file", "args": {"path": str(outside)}}],
            ),
            reply("TASK COMPLETE"),
        ],
        approval_policy=ApprovalPolicy("guarded", prompter=prompter),
        repo_root=workspace,
    )

    assert tool_executor.actions == []
    assert len(prompter.actions) == 1
    assert prompter.actions[0]["tool"] == "read_file"
    assert "outside the workspace root" in prompter.actions[0]["approval_reason"]


def test_guarded_allows_low_risk_run_command_without_approval(tmp_path) -> None:
    prompter = FakePrompter(ApprovalDecision(approved=False))

    _, tool_executor, _, _ = run_loop(
        [
            reply("valid", actions=[{"tool": "run_command", "args": {"command": "pwd"}}]),
            reply("TASK COMPLETE"),
        ],
        approval_policy=ApprovalPolicy("guarded", prompter=prompter),
        repo_root=tmp_path,
    )

    assert prompter.actions == []
    assert tool_executor.actions == [
        {"tool": "run_command", "args": {"command": "pwd"}}
    ]


def test_guarded_asks_for_risky_run_command(tmp_path) -> None:
    prompter = FakePrompter(ApprovalDecision(approved=False))

    _, tool_executor, _, _ = run_loop(
        [
            reply(
                "valid",
                actions=[{"tool": "run_command", "args": {"command": "mkdir build"}}],
            ),
            reply("TASK COMPLETE"),
        ],
        approval_policy=ApprovalPolicy("guarded", prompter=prompter),
        repo_root=tmp_path,
    )

    assert tool_executor.actions == []
    assert prompter.actions == [
        {
            "tool": "run_command",
            "args": {"command": "mkdir build"},
            "approval_reason": "Command may modify files",
        }
    ]


def test_always_still_asks_for_every_tool(tmp_path) -> None:
    target = tmp_path / "README.md"
    target.write_text("hello", encoding="utf-8")
    prompter = FakePrompter(ApprovalDecision(approved=True))

    _, tool_executor, _, _ = run_loop(
        [
            reply("valid", actions=[{"tool": "read_file", "args": {"path": str(target)}}]),
            reply("TASK COMPLETE"),
        ],
        approval_policy=ApprovalPolicy("always", prompter=prompter),
        repo_root=tmp_path,
    )

    assert len(prompter.actions) == 1
    assert tool_executor.actions == [
        {"tool": "read_file", "args": {"path": str(target)}}
    ]


def test_never_still_asks_never_and_allows_outside_workspace(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside.txt"
    workspace.mkdir()
    prompter = FakePrompter(ApprovalDecision(approved=False))

    _, tool_executor, _, _ = run_loop(
        [
            reply(
                "valid",
                actions=[{"tool": "read_file", "args": {"path": str(outside)}}],
            ),
            reply("TASK COMPLETE"),
        ],
        approval_policy=ApprovalPolicy("never", prompter=prompter),
        repo_root=workspace,
    )

    assert prompter.actions == []
    assert tool_executor.actions == [
        {
            "tool": "read_file",
            "args": {"path": str(outside)},
            "outside_workspace_approved": True,
        }
    ]


def test_empty_approval_decision_executes_tool_action() -> None:
    session, tool_executor, _, _ = run_loop(
        [
            reply(
                "valid",
                actions=[{"tool": "read_file", "tool_call_id": "call_1"}],
            ),
            reply("TASK COMPLETE"),
        ],
        approval_policy=ApprovalPolicy(
            "always",
            prompter=FakePrompter(ApprovalDecision(approved=True, instruction="")),
        ),
    )

    assert tool_executor.actions == [{"tool": "read_file", "tool_call_id": "call_1"}]
    assert all(
        message.get("content") != "user denied tool action"
        for message in session.messages
    )


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
        approval_policy=ApprovalPolicy(
            "always",
            prompter=FakePrompter(ApprovalDecision(approved=False)),
        ),
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


def test_approval_comment_is_appended_after_denied_tool_result() -> None:
    session = Session(repo_root=None)
    loop = AgentLoop(
        session=session,
        model_adapter=FakeModelAdapter(
            [
                {
                    "message": {
                        "role": "assistant",
                        "content": "valid",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": "read_file",
                                    "arguments": '{"path": "/tmp/x"}',
                                },
                            }
                        ],
                    },
                    "actions": [{"tool": "read_file", "tool_call_id": "call_1"}],
                    "reason": "",
                },
                reply("TASK COMPLETE"),
            ]
        ),
        tool_executor=FakeToolExecutor(),
        tool_results=ToolResults(),
        agent=FakeAgent(),
        display=NullDisplay(),
        approval_policy=ApprovalPolicy(
            "always",
            prompter=FakePrompter(
                ApprovalDecision(
                    approved=False,
                    instruction="Please inspect the project tree first.",
                )
            ),
        ),
    )

    loop.run()

    assistant_index = next(
        index
        for index, message in enumerate(session.messages)
        if message.get("role") == "assistant" and message.get("tool_calls")
    )
    assert session.messages[assistant_index + 1]["role"] == "tool"
    assert session.messages[assistant_index + 1]["tool_call_id"] == "call_1"
    assert json.loads(session.messages[assistant_index + 1]["content"])["error"] == (
        "user denied tool action"
    )
    assert session.messages[assistant_index + 2] == {
        "role": "user",
        "content": "Please inspect the project tree first.",
    }


def test_multiline_approval_comment_is_appended_after_denied_tool_result() -> None:
    instruction = "Please do this instead:\n1. Read README.md\n2. Keep the patch tiny"
    session = Session(repo_root=None)
    loop = AgentLoop(
        session=session,
        model_adapter=FakeModelAdapter(
            [
                {
                    "message": {
                        "role": "assistant",
                        "content": "valid",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": "run_command",
                                    "arguments": '{"command": "npm test"}',
                                },
                            }
                        ],
                    },
                    "actions": [{"tool": "run_command", "tool_call_id": "call_1"}],
                    "reason": "",
                },
                reply("TASK COMPLETE"),
            ]
        ),
        tool_executor=FakeToolExecutor(),
        tool_results=ToolResults(),
        agent=FakeAgent(),
        display=NullDisplay(),
        approval_policy=ApprovalPolicy(
            "always",
            prompter=FakePrompter(
                ApprovalDecision(approved=False, instruction=instruction)
            ),
        ),
    )

    loop.run()

    assistant_index = next(
        index
        for index, message in enumerate(session.messages)
        if message.get("role") == "assistant" and message.get("tool_calls")
    )
    assert session.messages[assistant_index + 1]["role"] == "tool"
    assert session.messages[assistant_index + 2] == {
        "role": "user",
        "content": instruction,
    }


def test_complete_status_is_written_on_normal_completion() -> None:
    _, _, session_store, _, _ = run_loop_with_store([reply("TASK COMPLETE")])

    assert session_store.statuses == ["complete"]


def test_failed_status_is_written_after_repeated_invalid_replies() -> None:
    _, _, session_store, _, _ = run_loop_with_store(
        [
            reply("bad 1", reason="empty_final_reply"),
            reply("bad 2", reason="non_final_too_many_tool_calls"),
            reply("bad 3", reason="empty_final_reply"),
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
            reply("bad 1", reason="empty_final_reply"),
            reply("valid", actions=[{"tool": "read_file"}]),
            reply("TASK COMPLETE"),
        ],
        max_tool_steps=1,
    )

    assert {"role": "user", "content": "correction:empty_final_reply"} in session.messages
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

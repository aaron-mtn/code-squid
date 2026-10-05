"""Application behavioral hooks exercised through the generic Core loop."""

from squid_core.agent_loop import AgentLoop, RunResult
from squid_core.hooks import HookRunner
from code_squid.hooks import RepeatedFailureNudge
from squid_core.session import Session


class FakeAgent:
    task = "Do the task"
    skill_name = "skill"

    def initial_messages(self) -> list[dict]:
        return [{"role": "system", "content": "system"}]

    def tool_definitions(self) -> list[dict]:
        return [
            {"function": {"name": "read_file"}},
            {"name": "run_command"},
        ]

    def should_stop(self, session: Session) -> bool:
        return any(message["role"] == "assistant" for message in session.messages)

    def validate_reply(self, reply: dict) -> dict:
        return {"ok": True, "reason": ""}


class FakeModelAdapter:
    def __init__(self, reply: dict | None = None) -> None:
        self.calls = []
        self.replies = [reply or {
            "message": {"role": "assistant", "content": "TASK COMPLETE"},
            "actions": [],
        }]

    def respond(self, messages: list[dict], tool_definitions: list[dict]) -> dict:
        self.calls.append(
            {
                "messages": list(messages),
                "tool_definitions": tool_definitions,
            }
        )
        if len(self.calls) <= len(self.replies):
            reply = self.replies[len(self.calls) - 1]
        else:
            reply = self.replies[-1]
        reply.setdefault(
            "raw_reply",
            {
                "assistant": {
                    "content": reply["message"].get("content"),
                    "raw_tool_calls": reply["message"].get("tool_calls", []),
                }
            },
        )
        return reply


class SequenceModelAdapter(FakeModelAdapter):
    def __init__(self, replies: list[dict]) -> None:
        super().__init__(replies[0])
        self.replies = replies


class FakeToolExecutor:
    def __init__(self) -> None:
        self.actions = []

    def execute(self, action: dict) -> dict:
        self.actions.append(action)
        return {"ok": True, "tool": action["tool"]}


class FakeToolResults:
    def messages_from_action_results(self, actions: list[dict], results: list[dict]) -> list[dict]:
        return []


class NullDisplay:
    debug = False

    def __init__(self) -> None:
        self.final_messages = []
        self.rejected_replies = []
        self.tool_results = []

    def thinking(self) -> None:
        pass

    def debug_reply(self, reply: dict) -> None:
        pass

    def final_message(self, content: str) -> None:
        self.final_messages.append(content)

    def assistant_message(self, content: str) -> None:
        pass

    def reply_rejected(self, reason: str) -> None:
        self.rejected_replies.append(reason)

    def action_started(self, action: dict) -> None:
        pass

    def tool_result(self, action: dict, result: dict) -> None:
        self.tool_results.append((action, result))


def test_repeated_failure_nudge_reaches_model_without_blocking_tool_calls() -> None:
    class CompletingAgent(FakeAgent):
        def should_stop(self, session: Session) -> bool:
            return any(
                message.get("role") == "assistant"
                and message.get("content") == "TASK COMPLETE"
                for message in session.messages
            )

    class FailingExecutor(FakeToolExecutor):
        def execute(self, action: dict) -> dict:
            self.actions.append(action)
            return {"ok": False, "tool": action["tool"], "error": "same_failure"}

    action = {"tool": "read_file", "args": {"path": "same.py"}}
    model_adapter = SequenceModelAdapter(
        [
            *[
                {
                    "message": {"role": "assistant", "content": "Trying."},
                    "actions": [action],
                }
                for _ in range(3)
            ],
            {
                "message": {"role": "assistant", "content": "TASK COMPLETE"},
                "actions": [],
            },
        ]
    )
    session = Session(workspace_root=None)
    executor = FailingExecutor()
    loop = AgentLoop(
        session=session,
        model_adapter=model_adapter,
        tool_executor=executor,
        tool_results=FakeToolResults(),
        agent=CompletingAgent(),
        display=NullDisplay(),
        hook_runner=HookRunner([RepeatedFailureNudge("Change course.")]),
    )

    result = loop.run()

    assert result == RunResult(status="complete")
    assert executor.actions == [action, action, action]
    assert "Change course." in model_adapter.calls[3]["messages"][-1]["content"]
    assert all(
        "Change course." not in str(call["messages"])
        for call in model_adapter.calls[:3]
    )
    assert all("Change course." not in str(message) for message in session.messages)


def test_command_failure_nudge_is_transient_and_next_command_still_runs() -> None:
    class CompletingAgent(FakeAgent):
        def should_stop(self, session: Session) -> bool:
            return any(
                message.get("role") == "assistant"
                and message.get("content") == "TASK COMPLETE"
                for message in session.messages
            )

    class FailingCommandExecutor(FakeToolExecutor):
        def execute(self, action: dict) -> dict:
            self.actions.append(action)
            return {
                "ok": False,
                "tool": "run_command",
                "failure_class": "command_not_found",
                "platform": "Windows",
                "shell": "PowerShell",
            }

    actions = [
        {"tool": "run_command", "args": {"command": command}}
        for command in ("grep x", "wc -l", "missing-tool", "Get-ChildItem")
    ]
    model_adapter = SequenceModelAdapter(
        [
            *[
                {
                    "message": {"role": "assistant", "content": "Trying."},
                    "actions": [action],
                }
                for action in actions
            ],
            {
                "message": {"role": "assistant", "content": "TASK COMPLETE"},
                "actions": [],
            },
        ]
    )
    session = Session(workspace_root=None)
    executor = FailingCommandExecutor()
    loop = AgentLoop(
        session=session,
        model_adapter=model_adapter,
        tool_executor=executor,
        tool_results=FakeToolResults(),
        agent=CompletingAgent(),
        display=NullDisplay(),
        hook_runner=HookRunner(
            [
                RepeatedFailureNudge(
                    "Change course.",
                    run_command_guidance="Reassess commands.",
                )
            ]
        ),
    )

    result = loop.run()

    assert result == RunResult(status="complete")
    assert executor.actions == actions
    assert "Reassess commands." in model_adapter.calls[3]["messages"][-1]["content"]
    assert all(
        "Reassess commands." not in str(call["messages"])
        for call in (*model_adapter.calls[:3], model_adapter.calls[4])
    )
    assert all("Reassess commands." not in str(message) for message in session.messages)


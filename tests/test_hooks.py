from core.agent_loop import AgentLoop, RunResult
from core.hooks import (
    BeforeModelTurnContext,
    BeforeRunContext,
    HookRunner,
    PromptContextBlock,
    RunHookDecision,
)
from core.session import Session


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
    def __init__(self) -> None:
        self.calls = []

    def respond(self, messages: list[dict], tool_definitions: list[dict]) -> dict:
        self.calls.append(
            {
                "messages": list(messages),
                "tool_definitions": tool_definitions,
            }
        )
        return {
            "message": {"role": "assistant", "content": "TASK COMPLETE"},
            "actions": [],
        }


class FakeToolExecutor:
    def execute(self, action: dict) -> dict:
        return {"ok": True, "tool": action["tool"]}


class FakeToolResults:
    def messages_from_action_results(self, actions: list[dict], results: list[dict]) -> list[dict]:
        return []


class FakeSessionStore:
    session_id = "session-1"

    def __init__(self) -> None:
        self.messages = []
        self.statuses = []

    def append_message(self, message: dict, usage: dict | None = None) -> None:
        self.messages.append(message)

    def update_status(self, status: str) -> None:
        self.statuses.append(status)


class NullDisplay:
    debug = False

    def thinking(self) -> None:
        pass

    def debug_reply(self, reply: dict) -> None:
        pass

    def final_message(self, content: str) -> None:
        pass


def build_loop(hook_runner=None, on_event=None):
    session = Session(repo_root=None)
    model_adapter = FakeModelAdapter()
    session_store = FakeSessionStore()
    loop = AgentLoop(
        session=session,
        model_adapter=model_adapter,
        tool_executor=FakeToolExecutor(),
        tool_results=FakeToolResults(),
        agent=FakeAgent(),
        display=NullDisplay(),
        session_store=session_store,
        on_event=on_event,
        hook_runner=hook_runner,
    )
    return loop, session, model_adapter, session_store


def test_hook_runner_noop_returns_empty_decisions() -> None:
    runner = HookRunner()

    before_run = runner.before_run(
        BeforeRunContext(session_id=None, repo_root="", task="")
    )
    before_model_turn = runner.before_model_turn(
        BeforeModelTurnContext(
            session_id=None,
            repo_root="",
            task="",
            messages=(),
            tool_steps_used=0,
        )
    )

    assert before_run == RunHookDecision()
    assert before_model_turn == []


def test_before_run_block_fails_without_calling_model() -> None:
    events = []

    class BlockingHook:
        def before_run(self, ctx: BeforeRunContext) -> RunHookDecision:
            return RunHookDecision(block=True, reason="blocked")

    loop, _, model_adapter, session_store = build_loop(
        hook_runner=HookRunner([BlockingHook()]),
        on_event=events.append,
    )

    result = loop.run()

    assert result == RunResult(status="failed", reason="blocked")
    assert model_adapter.calls == []
    assert session_store.statuses == ["failed"]
    assert [event["type"] for event in events] == [
        "run_started",
        "run_failed",
        "run_finished",
    ]
    assert events[1]["reason"] == "blocked"


def test_before_run_block_uses_guidance_when_reason_is_empty() -> None:
    events = []

    class BlockingHook:
        def before_run(self, ctx: BeforeRunContext) -> RunHookDecision:
            return RunHookDecision(block=True, guidance="Fix setup first.")

    loop, _, _, _ = build_loop(
        hook_runner=HookRunner([BlockingHook()]),
        on_event=events.append,
    )

    result = loop.run()

    assert result == RunResult(status="failed", reason="Fix setup first.")
    assert events[1]["reason"] == "Fix setup first."


def test_before_run_context_is_visible_to_model_but_not_persisted() -> None:
    class ContextHook:
        def before_run(self, ctx: BeforeRunContext) -> RunHookDecision:
            assert ctx.allowed_tools == ("read_file", "run_command")
            return RunHookDecision(
                context_blocks=(
                    PromptContextBlock("Run Hint", "Use the narrow path.", "test"),
                )
            )

    loop, session, model_adapter, session_store = build_loop(
        hook_runner=HookRunner([ContextHook()])
    )

    result = loop.run()

    assert result == RunResult(status="complete")
    model_messages = model_adapter.calls[0]["messages"]
    assert model_messages[-1] == {
        "role": "user",
        "content": (
            "# Additional Context For This Turn\n"
            "\n"
            "## Run Hint (test)\n"
            "Use the narrow path."
        ),
    }
    assert model_messages[-1] not in session.messages
    assert model_messages[-1] not in session_store.messages


def test_before_model_turn_context_is_visible_to_model_but_not_persisted() -> None:
    class TurnHook:
        def before_model_turn(self, ctx: BeforeModelTurnContext) -> PromptContextBlock:
            assert ctx.tool_steps_used == 0
            return PromptContextBlock("Turn Hint", "Check the current transcript.")

    loop, session, model_adapter, session_store = build_loop(
        hook_runner=HookRunner([TurnHook()])
    )

    result = loop.run()

    assert result == RunResult(status="complete")
    model_messages = model_adapter.calls[0]["messages"]
    assert model_messages[-1]["content"] == (
        "# Additional Context For This Turn\n"
        "\n"
        "## Turn Hint\n"
        "Check the current transcript."
    )
    assert model_messages[-1] not in session.messages
    assert model_messages[-1] not in session_store.messages


def test_before_model_turn_ignores_context_blocks_attribute_shape() -> None:
    class ContextCarrier:
        context_blocks = (PromptContextBlock("Ignored", "Do not include this."),)

    class TurnHook:
        def before_model_turn(self, ctx: BeforeModelTurnContext) -> ContextCarrier:
            return ContextCarrier()

    loop, session, model_adapter, _ = build_loop(
        hook_runner=HookRunner([TurnHook()])
    )

    result = loop.run()

    assert result == RunResult(status="complete")
    assert model_adapter.calls[0]["messages"] == [
        {"role": "system", "content": "system"}
    ]
    assert session.messages == [
        {"role": "system", "content": "system"},
        {"role": "assistant", "content": "TASK COMPLETE"},
    ]


def test_no_hook_runner_keeps_basic_loop_behavior() -> None:
    loop, session, model_adapter, _ = build_loop()

    result = loop.run()

    assert result == RunResult(status="complete")
    assert model_adapter.calls[0]["messages"] == [
        {"role": "system", "content": "system"}
    ]
    assert session.messages == [
        {"role": "system", "content": "system"},
        {"role": "assistant", "content": "TASK COMPLETE"},
    ]

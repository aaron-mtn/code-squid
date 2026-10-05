"""Application behavioral hooks exercised through the generic Core loop."""

import json
from squid_core.agent_loop import AgentLoop, RunResult
from squid_core.hooks import HookRunner
from code_squid.hooks import (
    CURRENT_VERIFICATION_STATE_GUIDANCE,
    POST_VERIFICATION_GUIDANCE,
    PostVerificationNudge,
    TOO_MANY_READS_GUIDANCE,
    TooManyReadsNudge,
)
from squid_core.session import Session
from squid_core.tools import ToolExecutor, ToolResults


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
    def __init__(
        self,
        replies: list[dict],
        events: list[str] | None = None,
        streaming: bool = False,
        deltas: list[str] | None = None,
        reasoning_deltas: list[str] | None = None,
        tool_preparing_events: list[dict] | None = None,
    ) -> None:
        self.replies = replies
        self.index = 0
        self.events = events
        self.streaming = streaming
        self.deltas = deltas or []
        self.reasoning_deltas = reasoning_deltas or []
        self.tool_preparing_events = tool_preparing_events or []
        self.message_requests = []
        self.provider_name = "fake-provider"
        self.model_name = "fake-model"

    def respond(self, messages: list[dict], tool_definitions: list[dict]) -> dict:
        self.message_requests.append([dict(message) for message in messages])
        if self.events is not None:
            self.events.append("respond")
        reply = self.replies[self.index]
        self.index += 1
        return reply

    def supports_streaming(self) -> bool:
        return self.streaming

    def respond_streaming(
        self,
        messages: list[dict],
        tool_definitions: list[dict],
        on_text_delta,
        on_reasoning_delta=None,
        on_tool_preparing=None,
        should_cancel=None,
    ) -> dict:
        self.message_requests.append([dict(message) for message in messages])
        if self.events is not None:
            self.events.append("respond_streaming:start")
        if on_reasoning_delta is not None:
            for delta in self.reasoning_deltas:
                on_reasoning_delta(delta)
        self.reasoning_deltas = []
        for delta in self.deltas:
            if should_cancel is not None and should_cancel():
                from squid_core.providers.base import StreamCancelled

                raise StreamCancelled
            on_text_delta(delta)
        self.deltas = []
        if on_tool_preparing is not None:
            for event in self.tool_preparing_events:
                on_tool_preparing(event)
        self.tool_preparing_events = []
        if self.events is not None:
            self.events.append("respond_streaming:end")
        reply = self.replies[self.index]
        self.index += 1
        return reply


class FakeToolExecutor:
    def __init__(self, workspace_root=None, events: list[str] | None = None) -> None:
        self.workspace_root = workspace_root
        self.actions = []
        self.events = events

    def execute(self, action: dict) -> dict:
        if self.events is not None:
            self.events.append(f"execute:{action['tool']}")
        self.actions.append(action)
        return {"ok": True, "tool": action["tool"]}


class NullDisplay:
    def __init__(self, events: list[str] | None = None) -> None:
        self.step_limits_reached = []
        self.assistant_messages = []
        self.reasoning_messages = []
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

    def reasoning_message(self, content: str) -> None:
        self.reasoning_messages.append(content)

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
        "raw_reply": {
            "assistant": {"content": content, "raw_tool_calls": []},
        },
    }


def tool_call_reply(
    call_id: str,
    *,
    content: str = "Using read_file.",
    tool: str = "read_file",
    args: dict | None = None,
) -> dict:
    args = args or {}
    return {
        "message": {
            "role": "assistant",
            "content": content,
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": tool,
                        "arguments": json.dumps(args),
                    },
                }
            ],
        },
        "actions": [{"tool": tool, "args": args, "tool_call_id": call_id}],
        "reason": "",
        "raw_reply": {"assistant": {"content": content}},
    }


def multi_tool_call_reply(*calls: tuple[str, str]) -> dict:
    """Build one assistant turn whose actions and call metadata share order."""
    tool_calls = [
        {
            "id": call_id,
            "type": "function",
            "function": {"name": tool, "arguments": "{}"},
        }
        for call_id, tool in calls
    ]
    return {
        "message": {
            "role": "assistant",
            "content": "Running independent tools.",
            "tool_calls": tool_calls,
        },
        "actions": [
            {"tool": tool, "args": {}, "tool_call_id": call_id}
            for call_id, tool in calls
        ],
        "reason": "",
        "raw_reply": {"assistant": {"content": "Running independent tools."}},
    }


def multi_tool_call_reply_with_args(*calls: tuple[str, str, dict]) -> dict:
    """Build a tool turn with explicit arguments for execution-path tests."""
    return {
        "message": {
            "role": "assistant",
            "content": "Running independent tools.",
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {"name": tool, "arguments": json.dumps(args)},
                }
                for call_id, tool, args in calls
            ],
        },
        "actions": [
            {"tool": tool, "args": args, "tool_call_id": call_id}
            for call_id, tool, args in calls
        ],
        "reason": "",
        "raw_reply": {"assistant": {"content": "Running independent tools."}},
    }


def _run_read_batch(tmp_path, actions, hooks):
    """Exercise sibling reads through the production executor and Hook pipeline."""
    session = Session(workspace_root=tmp_path)
    adapter = FakeModelAdapter(
        [multi_tool_call_reply_with_args(*actions), reply("TASK COMPLETE")]
    )
    loop = AgentLoop(
        session=session,
        model_adapter=adapter,
        tool_executor=ToolExecutor(tmp_path, session),
        tool_results=ToolResults(),
        agent=FakeAgent(),
        display=NullDisplay(),
        hook_runner=HookRunner(hooks),
    )

    assert loop.run() == RunResult(status="complete")
    results = [
        json.loads(message["content"])
        for message in session.messages
        if message["role"] == "tool"
    ]
    return adapter, results


def test_read_count_threshold_is_cumulative_within_batch(tmp_path) -> None:
    paths = []
    for index in range(3):
        path = tmp_path / f"source_{index}.py"
        path.write_text(f"source {index}\n", encoding="utf-8")
        paths.append(path)
    actions = tuple(
        (f"call_{index}", "read_file", {"path": str(path)})
        for index, path in enumerate(paths, start=1)
    )
    hook = TooManyReadsNudge(
        first_nudge_reads=3,
        strong_nudge_reads=5,
        first_nudge_lines=10_000,
        strong_nudge_lines=20_000,
    )

    adapter, results = _run_read_batch(tmp_path, actions, [hook])

    assert all(result["ok"] is True for result in results)
    assert TOO_MANY_READS_GUIDANCE in adapter.message_requests[1][-1]["content"]


def test_visible_source_volume_is_cumulative_within_batch(tmp_path) -> None:
    paths = []
    for index in range(2):
        path = tmp_path / f"volume_{index}.py"
        path.write_text("".join(f"line {line}\n" for line in range(15)), encoding="utf-8")
        paths.append(path)
    actions = tuple(
        (f"call_{index}", "read_file", {"path": str(path)})
        for index, path in enumerate(paths, start=1)
    )
    hook = TooManyReadsNudge(
        first_nudge_reads=4,
        strong_nudge_reads=6,
        first_nudge_lines=30,
        strong_nudge_lines=60,
    )

    adapter, results = _run_read_batch(tmp_path, actions, [hook])

    assert sum(result["content_returned_chars"] for result in results) == sum(
        len(path.read_text(encoding="utf-8")) for path in paths
    )
    assert TOO_MANY_READS_GUIDANCE in adapter.message_requests[1][-1]["content"]


class _VerificationExecutor(FakeToolExecutor):
    """Mark requested commands as verification for boundary-guidance tests."""

    def execute(self, action: dict) -> dict:
        result = super().execute(action)
        if action["tool"] == "run_command" and action.get("args", {}).get(
            "verification"
        ):
            result["verification"] = True
        return result


def test_successful_verification_reaches_immediately_following_model_request() -> None:
    adapter = FakeModelAdapter(
        [
            multi_tool_call_reply_with_args(
                ("verify", "run_command", {"verification": True})
            ),
            reply("TASK COMPLETE"),
        ]
    )
    loop = AgentLoop(
        session=Session(workspace_root=None),
        model_adapter=adapter,
        tool_executor=_VerificationExecutor(),
        tool_results=ToolResults(),
        agent=FakeAgent(),
        display=NullDisplay(),
        hook_runner=HookRunner([PostVerificationNudge(threshold=2)]),
    )

    assert loop.run() == RunResult(status="complete")
    content = adapter.message_requests[1][-1]["content"]
    assert CURRENT_VERIFICATION_STATE_GUIDANCE in content
    assert content.count(CURRENT_VERIFICATION_STATE_GUIDANCE) == 1
    assert POST_VERIFICATION_GUIDANCE not in content


def test_omitting_post_verification_hook_omits_current_state_guidance() -> None:
    adapter = FakeModelAdapter(
        [
            multi_tool_call_reply_with_args(
                ("verify", "run_command", {"verification": True})
            ),
            reply("TASK COMPLETE"),
        ]
    )
    loop = AgentLoop(
        session=Session(workspace_root=None),
        model_adapter=adapter,
        tool_executor=_VerificationExecutor(),
        tool_results=ToolResults(),
        agent=FakeAgent(),
        display=NullDisplay(),
        hook_runner=HookRunner(),
    )

    assert loop.run() == RunResult(status="complete")
    assert CURRENT_VERIFICATION_STATE_GUIDANCE not in str(
        adapter.message_requests[1]
    )


def test_verification_in_multi_tool_batch_uses_final_current_state() -> None:
    adapter = FakeModelAdapter(
        [
            multi_tool_call_reply_with_args(
                ("verify", "run_command", {"verification": True}),
                ("inspect", "search_files", {}),
            ),
            reply("TASK COMPLETE"),
        ]
    )
    loop = AgentLoop(
        session=Session(workspace_root=None),
        model_adapter=adapter,
        tool_executor=_VerificationExecutor(),
        tool_results=ToolResults(),
        agent=FakeAgent(),
        display=NullDisplay(),
        hook_runner=HookRunner([PostVerificationNudge(threshold=2)]),
    )

    assert loop.run() == RunResult(status="complete")
    content = adapter.message_requests[1][-1]["content"]
    assert CURRENT_VERIFICATION_STATE_GUIDANCE in content
    assert content.count(CURRENT_VERIFICATION_STATE_GUIDANCE) == 1


def test_post_verification_guidance_invalidated_by_later_batch_edit() -> None:
    adapter = FakeModelAdapter(
        [
            multi_tool_call_reply_with_args(
                ("verify", "run_command", {"verification": True})
            ),
            multi_tool_call_reply(
                ("read_1", "read_file"),
                ("read_2", "read_file"),
                ("write", "write_file"),
            ),
            reply("TASK COMPLETE"),
        ]
    )
    loop = AgentLoop(
        session=Session(workspace_root=None),
        model_adapter=adapter,
        tool_executor=_VerificationExecutor(),
        tool_results=ToolResults(),
        agent=FakeAgent(),
        display=NullDisplay(),
        hook_runner=HookRunner([PostVerificationNudge(threshold=2)]),
    )

    assert loop.run() == RunResult(status="complete")
    assert (
        CURRENT_VERIFICATION_STATE_GUIDANCE
        in adapter.message_requests[1][-1]["content"]
    )
    assert POST_VERIFICATION_GUIDANCE not in str(adapter.message_requests[2])
    assert CURRENT_VERIFICATION_STATE_GUIDANCE not in str(adapter.message_requests[2])


def test_post_verification_guidance_uses_final_valid_batch_state() -> None:
    adapter = FakeModelAdapter(
        [
            multi_tool_call_reply_with_args(
                ("verify", "run_command", {"verification": True})
            ),
            multi_tool_call_reply(
                ("read", "read_file"),
                ("search", "search_files"),
            ),
            reply("TASK COMPLETE"),
        ]
    )
    loop = AgentLoop(
        session=Session(workspace_root=None),
        model_adapter=adapter,
        tool_executor=_VerificationExecutor(),
        tool_results=ToolResults(),
        agent=FakeAgent(),
        display=NullDisplay(),
        hook_runner=HookRunner([PostVerificationNudge(threshold=2)]),
    )

    assert loop.run() == RunResult(status="complete")
    content = adapter.message_requests[2][-1]["content"]
    assert POST_VERIFICATION_GUIDANCE in content
    assert content.count(POST_VERIFICATION_GUIDANCE) == 1


def test_read_guidance_invalidated_by_later_batch_edit() -> None:
    hook = TooManyReadsNudge(
        first_nudge_reads=3,
        strong_nudge_reads=5,
        first_nudge_lines=10_000,
        strong_nudge_lines=20_000,
    )
    adapter = FakeModelAdapter(
        [
            multi_tool_call_reply(
                ("read_1", "read_file"),
                ("read_2", "read_file"),
                ("read_3", "read_file"),
                ("write", "write_file"),
            ),
            reply("TASK COMPLETE"),
        ]
    )
    loop = AgentLoop(
        session=Session(workspace_root=None),
        model_adapter=adapter,
        tool_executor=FakeToolExecutor(),
        tool_results=ToolResults(),
        agent=FakeAgent(),
        display=NullDisplay(),
        hook_runner=HookRunner([hook]),
    )

    assert loop.run() == RunResult(status="complete")
    assert TOO_MANY_READS_GUIDANCE not in str(adapter.message_requests[1])


def test_single_read_guidance_renders_once_at_next_model_boundary() -> None:
    hook = TooManyReadsNudge(
        first_nudge_reads=1,
        strong_nudge_reads=2,
        first_nudge_lines=10_000,
        strong_nudge_lines=20_000,
    )
    adapter = FakeModelAdapter(
        [tool_call_reply("read"), reply("TASK COMPLETE")]
    )
    loop = AgentLoop(
        session=Session(workspace_root=None),
        model_adapter=adapter,
        tool_executor=FakeToolExecutor(),
        tool_results=ToolResults(),
        agent=FakeAgent(),
        display=NullDisplay(),
        hook_runner=HookRunner([hook]),
    )

    assert loop.run() == RunResult(status="complete")
    content = adapter.message_requests[1][-1]["content"]
    assert content.count(TOO_MANY_READS_GUIDANCE) == 1


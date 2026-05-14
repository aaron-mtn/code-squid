from core.agent_loop import AgentLoop
from core.session import Session


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


class NullDisplay:
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


def run_loop(replies: list[dict]) -> tuple[Session, FakeToolExecutor]:
    session = Session(repo_root=None)
    tool_executor = FakeToolExecutor()
    loop = AgentLoop(
        session=session,
        model_adapter=FakeModelAdapter(replies),
        tool_executor=tool_executor,
        tool_results=FakeToolResults(),
        agent=FakeAgent(),
        display=NullDisplay(),
    )

    loop.run()

    return session, tool_executor


def test_valid_reply_resets_consecutive_invalid_reply_counter() -> None:
    session, tool_executor = run_loop(
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
    session, _ = run_loop(
        [
            reply("bad 1", reason="non_final_no_tool_reply"),
            reply("bad 2", reason="non_final_wrong_tool_count"),
            reply("TASK COMPLETE"),
        ]
    )

    assert {"role": "user", "content": "correction:non_final_no_tool_reply"} in session.messages
    assert {"role": "user", "content": "correction:non_final_wrong_tool_count"} in session.messages


def test_loop_stops_after_three_consecutive_invalid_replies() -> None:
    session, _ = run_loop(
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

# core/agent_loop.py

from dataclasses import dataclass
from typing import Any, Literal

from core.approval import ApprovalPolicy, denied_result


MAX_CONSECUTIVE_INVALID_REPLIES = 3


@dataclass(frozen=True)
class RunResult:
    status: Literal["complete", "failed", "interrupted"]
    reason: str = ""


class AgentLoop:
    """Owns the generic agent loop and transcript turn flow; must not own coding-specific policy, prompts, or tool definitions."""

    # Store the parts needed to run the loop.
    # The loop depends on the session, model adapter, tool executor,
    # tool result formatter, coding agent behavior, display layer, and optional
    # durable session storage.
    def __init__(
        self,
        session,
        model_adapter,
        tool_executor,
        tool_results,
        agent,
        display,
        session_store=None,
        compactor=None,
        max_tool_steps: int | None = None,
        approval_policy: ApprovalPolicy | None = None,
    ) -> None:
        self.session = session
        self.model_adapter = model_adapter
        self.tool_executor = tool_executor
        self.tool_results = tool_results
        self.agent = agent
        self.display = display
        self.session_store = session_store
        self.compactor = compactor
        self.max_tool_steps = max_tool_steps
        self.approval_policy = approval_policy or ApprovalPolicy("never")

    # Add one accepted transcript message to memory and optional disk storage.
    #
    # This is the central write path for transcript messages. Rejected invalid
    # assistant replies should not use this helper because they are intentionally
    # excluded from normal transcript history.
    def _add_message(self, message: dict[str, Any], usage: dict | None = None) -> None:
        self.session.add_message(message)

        if self.session_store is not None:
            self.session_store.append_message(message, usage=usage)

    # Add accepted transcript messages in order.
    def _add_messages(self, *messages: dict[str, Any]) -> None:
        for message in messages:
            self._add_message(message)

    # Update durable session status when persistence is wired in.
    def _update_status(self, status: str) -> None:
        if self.session_store is not None:
            self.session_store.update_status(status)

    # Ensure a brand-new in-memory session has the initial agent messages.
    #
    # Future resume support can load saved messages before run() is called.
    # In that case, this method leaves the existing transcript alone instead
    # of adding a second system/user kickoff.
    def _ensure_initial_messages(self) -> None:
        if self.session.messages:
            return

        self._add_messages(*self.agent.initial_messages())

    # Run the agent loop until the agent says it should stop.
    # Each loop iteration:
    # 1. ensures the transcript has initial messages for new sessions
    # 2. asks the model for the next reply and tool actions
    # 3. validates whether that reply counts as a real agent turn
    # 4. rejects invalid replies before they enter assistant history
    # 5. stores valid assistant replies in the session
    # 6. executes each tool action
    # 7. announces each tool result to the display
    # 8. converts tool results into transcript messages
    # 9. stores those result messages in the session
    def run(self) -> RunResult:
        # New sessions start with the agent's initial system/user messages.
        # Resumed sessions can already contain transcript history, so do not
        # blindly append another kickoff.
        self._ensure_initial_messages()

        consecutive_invalid_replies = 0
        stopped_after_repeated_invalid_replies = False
        stopped_after_step_limit = False
        failure_reason = ""
        tool_steps_used = 0

        # Keep going until the agent says the task is complete.
        while not self.agent.should_stop(self.session):
            if (
                self.max_tool_steps is not None
                and tool_steps_used >= self.max_tool_steps
            ):
                self.display.step_limit_reached(self.max_tool_steps)
                self._update_status("failed")
                stopped_after_step_limit = True
                failure_reason = f"reached tool step limit: {self.max_tool_steps}"
                break

            if self.compactor is not None:
                compaction_metadata = self.compactor.maybe_compact(self.session)
                if compaction_metadata is not None and self.session_store is not None:
                    self.session_store.append_compaction(compaction_metadata)

            # Ask the model for the next assistant reply and any tool actions.
            self.display.thinking()
            reply = self.model_adapter.respond(
                messages=self.session.messages,
                tool_definitions=self.agent.tool_definitions(),
            )

            self.display.debug_reply(reply)

            # Ask the coding agent whether this reply counts as a valid turn.
            # Invalid replies include narration-only turns, malformed tool calls,
            # wrong tool counts, and invalid finals.
            validation = self.agent.validate_reply(reply)

            # If the reply is invalid, do not store the assistant message in
            # the transcript. Instead inject a reason-specific correction and retry.
            if not validation["ok"]:
                consecutive_invalid_replies += 1
                if getattr(self.display, "debug", False):
                    self.display.assistant_message(reply["message"]["content"])
                self.display.reply_rejected(validation["reason"])

                if consecutive_invalid_replies == MAX_CONSECUTIVE_INVALID_REPLIES:
                    self.display.repeated_invalid_replies(
                        validation["reason"],
                        consecutive_invalid_replies,
                    )
                    self._add_message(
                        self.agent.failure_message_for_invalid_replies(
                            validation["reason"],
                            consecutive_invalid_replies,
                        )
                    )
                    self._update_status("failed")
                    stopped_after_repeated_invalid_replies = True
                    failure_reason = validation["reason"]
                    break

                self._add_message(self.agent.correction_message_for(validation["reason"]))
                continue

            # Only valid assistant replies are added to normal transcript history.
            consecutive_invalid_replies = 0
            self.display.assistant_message(reply["message"]["content"])
            self._add_message(reply["message"], usage=reply.get("usage"))

            # Execute each requested tool action and collect the raw results.
            results = []
            for action in reply["actions"]:
                decision = self.approval_policy.check(action)
                if decision.approved:
                    self.display.action_started(action)
                    result = self.tool_executor.execute(action)
                else:
                    result = denied_result(action, decision.reason)
                self.display.tool_result(action, result)
                results.append(result)

            # Convert tool results into transcript messages and store them.
            result_messages = self.tool_results.messages_from_action_results(
                reply["actions"],
                results,
            )
            self._add_messages(*result_messages)

            if reply["actions"]:
                tool_steps_used += 1

        if stopped_after_repeated_invalid_replies or stopped_after_step_limit:
            return RunResult(status="failed", reason=failure_reason)

        self._update_status("complete")
        return RunResult(status="complete")

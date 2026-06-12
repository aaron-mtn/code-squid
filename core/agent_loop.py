# core/agent_loop.py

from dataclasses import dataclass
from typing import Any, Callable, Literal

from core.approval import ApprovalPolicy, denied_result
from core.command_safety import guarded_run_command_reason
from core.events import EventCallback, emit_event
from core.workspace_boundary import workspace_boundary_reason


MAX_CONSECUTIVE_INVALID_REPLIES = 3
REJECTION_REASON_EVENT_MAX_CHARS = 500


class _CancellationRequested(Exception):
    pass


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
        stream_assistant_text: bool = False,
        # Optional observer callback for compact runtime facts. Terminal
        # display remains separate; external Python wrappers should listen here
        # instead of scraping human-facing output.
        on_event: EventCallback | None = None,
        should_cancel: Callable[[], bool] | None = None,
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
        self.stream_assistant_text = stream_assistant_text
        self.on_event = on_event
        self.should_cancel = should_cancel or (lambda: False)

    def _check_cancelled(self) -> None:
        if self.should_cancel():
            raise _CancellationRequested

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

    def _user_instruction_message(self, instruction: str) -> dict[str, str]:
        return {"role": "user", "content": instruction}

    # Update durable session status when persistence is wired in.
    def _update_status(self, status: str) -> None:
        if self.session_store is not None:
            self.session_store.update_status(status)

    def _session_id(self) -> str | None:
        if self.session_store is None:
            return None
        return getattr(self.session_store, "session_id", None)

    def _emit_event(self, event: dict[str, Any]) -> None:
        # AgentLoop events are small machine-readable facts for wrappers and
        # observers. Keep payloads compact: no raw file contents, full command
        # output, provider payloads, prompts, API keys, headers, or secrets.
        emit_event(
            self.on_event,
            {
                "session_id": self._session_id(),
                **event,
            },
        )

    def _action_event_fields(self, action: dict) -> dict[str, Any]:
        event = {
            "tool": action.get("tool", ""),
        }
        if "tool_call_id" in action:
            event["tool_call_id"] = action["tool_call_id"]
        args = action.get("args", {})
        if isinstance(args, dict):
            if "path" in args:
                event["path"] = args["path"]
            if "command" in args:
                event["command"] = args["command"]
        return event

    def _compact_event_text(self, text: object, max_chars: int) -> str:
        value = str(text).strip()
        if len(value) <= max_chars:
            return value

        suffix = "... [truncated]"
        return f"{value[: max_chars - len(suffix)]}{suffix}"

    def _should_stream_assistant_text(self) -> bool:
        if not self.stream_assistant_text:
            return False

        supports_streaming = getattr(self.model_adapter, "supports_streaming", None)
        return callable(supports_streaming) and bool(supports_streaming())

    def _respond(self, tool_definitions: list[dict]) -> dict:
        if not self._should_stream_assistant_text():
            return self.model_adapter.respond(
                messages=self.session.messages,
                tool_definitions=tool_definitions,
            )

        self._emit_event({"type": "assistant_message_started"})

        def on_text_delta(delta: str) -> None:
            self._emit_event(
                {
                    "type": "assistant_delta",
                    "delta": delta,
                }
            )

        def on_tool_preparing(tool_call: dict[str, Any]) -> None:
            event = {
                "type": "tool_preparing",
                "tool": tool_call.get("tool", ""),
            }
            if "tool_call_index" in tool_call:
                event["tool_call_index"] = tool_call["tool_call_index"]
            if "tool_call_id" in tool_call:
                event["tool_call_id"] = tool_call["tool_call_id"]
            self._emit_event(event)

        return self.model_adapter.respond_streaming(
            messages=self.session.messages,
            tool_definitions=tool_definitions,
            on_text_delta=on_text_delta,
            on_tool_preparing=on_tool_preparing,
        )

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
        try:
            self._check_cancelled()
            # New sessions start with the agent's initial system/user messages.
            # Resumed sessions can already contain transcript history, so do not
            # blindly append another kickoff.
            self._ensure_initial_messages()
            self._emit_event(
                {
                    "type": "run_started",
                    "repo_root": str(self.session.repo_root),
                    "task": getattr(self.agent, "task", ""),
                }
            )

            consecutive_invalid_replies = 0
            stopped_after_repeated_invalid_replies = False
            stopped_after_step_limit = False
            failure_reason = ""
            tool_steps_used = 0

            # Keep going until the agent says the task is complete.
            while not self.agent.should_stop(self.session):
                self._check_cancelled()
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
                    self._check_cancelled()
                    compaction_metadata = self.compactor.maybe_compact(self.session)
                    self._check_cancelled()
                    if compaction_metadata is not None and self.session_store is not None:
                        self.session_store.append_compaction(compaction_metadata)

                # Ask the model for the next assistant reply and any tool actions.
                self.display.thinking()
                self._check_cancelled()
                reply = self._respond(self.agent.tool_definitions())
                self._check_cancelled()

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
                    rejection_reason = self._compact_event_text(
                        validation["reason"],
                        REJECTION_REASON_EVENT_MAX_CHARS,
                    )
                    self._emit_event(
                        {
                            "type": "reply_rejected",
                            "reason": rejection_reason,
                        }
                    )

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

                    self._add_message(
                        self.agent.correction_message_for(validation["reason"])
                    )
                    continue

                self._check_cancelled()

                # Only valid assistant replies are added to normal transcript history.
                consecutive_invalid_replies = 0
                assistant_content = reply["message"]["content"]
                self._check_cancelled()
                if reply["actions"]:
                    self.display.assistant_message(assistant_content)
                    self._check_cancelled()
                    self._emit_event(
                        {
                            "type": "assistant_message",
                            "message": assistant_content,
                            "text": assistant_content,
                        }
                    )
                    # tool_started means "validated tool action pending/active", not
                    # necessarily that execute() has been entered.
                    for action in reply["actions"]:
                        self._check_cancelled()
                        self._emit_event(
                            {
                                "type": "tool_started",
                                **self._action_event_fields(action),
                            }
                        )
                else:
                    self.display.final_message(assistant_content)
                    self._check_cancelled()
                    self._emit_event(
                        {
                            "type": "final_message",
                            "message": assistant_content,
                            "text": assistant_content,
                        }
                    )
                self._check_cancelled()
                self._add_message(reply["message"], usage=reply.get("usage"))

                # Execute each requested tool action and collect the raw results.
                results = []
                approval_instructions = []
                for action in reply["actions"]:
                    self._check_cancelled()
                    workspace_boundary_reason_value = self._workspace_boundary_reason(
                        action
                    )
                    approval_reason = (
                        workspace_boundary_reason_value
                        or self._guarded_run_command_reason(action)
                    )
                    approval_action = (
                        {**action, "approval_reason": approval_reason}
                        if approval_reason is not None
                        else action
                    )
                    self._check_cancelled()
                    decision = self.approval_policy.check(approval_action)
                    self._check_cancelled()
                    if decision.approved:
                        execute_action = (
                            {**action, "outside_workspace_approved": True}
                            if workspace_boundary_reason_value is not None
                            else action
                        )
                        self.display.action_started(approval_action)
                        self._check_cancelled()
                        result = self.tool_executor.execute(execute_action)
                        self._check_cancelled()
                    else:
                        result = denied_result(action, decision.reason)
                        if decision.instruction.strip():
                            approval_instructions.append(decision.instruction)
                    self.display.tool_result(approval_action, result)
                    self._check_cancelled()
                    self._emit_event(
                        {
                            "type": "tool_finished",
                            "ok": bool(result.get("ok", False)),
                            **self._action_event_fields(action),
                        }
                    )
                    results.append(result)

                # Convert tool results into transcript messages and store them.
                result_messages = self.tool_results.messages_from_action_results(
                    reply["actions"],
                    results,
                )
                self._check_cancelled()
                self._add_messages(*result_messages)
                self._add_messages(
                    *[
                        self._user_instruction_message(instruction)
                        for instruction in approval_instructions
                    ]
                )

                if reply["actions"]:
                    tool_steps_used += 1

            if stopped_after_repeated_invalid_replies or stopped_after_step_limit:
                self._emit_event(
                    {
                        "type": "run_failed",
                        "status": "failed",
                        "reason": failure_reason,
                    }
                )
                self._emit_event({"type": "run_finished", "status": "failed"})
                return RunResult(status="failed", reason=failure_reason)

            self._check_cancelled()
            self._update_status("complete")
            self._emit_event({"type": "run_finished", "status": "complete"})
            return RunResult(status="complete")
        except _CancellationRequested:
            self._update_status("interrupted")
            self._emit_event(
                {
                    "type": "run_cancelled",
                    "status": "interrupted",
                    "reason": "cancelled",
                }
            )
            self._emit_event({"type": "run_finished", "status": "interrupted"})
            return RunResult(status="interrupted", reason="cancelled")

    def _workspace_boundary_reason(self, action: dict) -> str | None:
        repo_root = getattr(self.tool_executor, "repo_root", None)
        if repo_root is None:
            return None

        return workspace_boundary_reason(action, repo_root)

    def _guarded_run_command_reason(self, action: dict) -> str | None:
        if self.approval_policy.mode != "guarded":
            return None
        if action.get("tool") != "run_command":
            return None

        args = action.get("args", {})
        if not isinstance(args, dict):
            return "Command is not on the guarded allowlist"

        command = args.get("command")
        if not isinstance(command, str):
            return "Command is not on the guarded allowlist"

        repo_root = getattr(self.tool_executor, "repo_root", None)
        if repo_root is None:
            return "Command is not on the guarded allowlist"

        return guarded_run_command_reason(command, repo_root)

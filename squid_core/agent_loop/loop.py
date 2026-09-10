"""Generic AgentLoop state machine and public run result."""

from dataclasses import dataclass
from time import perf_counter
from typing import Callable, Literal

from squid_core.agent_loop.event_emitter import (
    action_event_fields,
    compact_event_text,
    emit_agent_event,
    tool_preparing_event,
)
from squid_core.agent_loop.transcript_recording import (
    record_message,
    record_messages,
    record_pending_tool_result,
    reconcile_system_message,
    turn_context_message,
    user_instruction_message,
)
from squid_core.compaction.token_estimate import estimate_messages_tokens
from squid_core.events import EventCallback
from squid_core.hooks import (
    BeforeAcceptFinalContext,
    BeforeModelTurnContext,
    BeforeRunContext,
    BeforeToolExecuteContext,
    FollowUpRunRequest,
    HookResponse,
    HookRunner,
    PromptContextBlock,
    RunFinishedContext,
    ToolResultContext,
)
from squid_core.safety import ActionPreflight, ApprovalPolicy, denied_result
from squid_core.settings import ToolResultTrimmingSettings
from squid_core.tool_result_trimming import render_messages_for_model

MAX_CONSECUTIVE_INVALID_REPLIES = 3
REJECTION_REASON_EVENT_MAX_CHARS = 500
ERROR_EVENT_MAX_CHARS = 500


class _CancellationRequested(Exception):
    pass


@dataclass(frozen=True)
class RunResult:
    status: Literal["complete", "failed", "interrupted"]
    reason: str = ""
    follow_up_requests: tuple[FollowUpRunRequest, ...] = ()
    hook_notes: tuple[str, ...] = ()


class AgentLoop:
    """Own the generic loop without coding policy, prompts, or Tool definitions."""

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
        hook_runner: HookRunner | None = None,
        action_preflight: ActionPreflight | None = None,
        tool_result_trimming: ToolResultTrimmingSettings | None = None,
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
        self.action_preflight = action_preflight or ActionPreflight.from_runtime(
            tool_executor,
            self.approval_policy,
        )
        self.stream_assistant_text = stream_assistant_text
        self.on_event = on_event
        self.should_cancel = should_cancel or (lambda: False)
        self.hook_runner = hook_runner if hook_runner is not None else HookRunner()
        self.tool_result_trimming = (
            tool_result_trimming
            if tool_result_trimming is not None
            else ToolResultTrimmingSettings()
        )
        self._run_context_blocks: list[PromptContextBlock] = []

    def _check_cancelled(self) -> None:
        if self.should_cancel():
            raise _CancellationRequested

    # Update durable session status when persistence is wired in.
    def _update_status(self, status: str) -> None:
        if self.session_store is not None:
            self.session_store.update_status(status)

    def _update_status_preserving_error(self, status: str) -> None:
        """Avoid replacing an in-flight runtime exception with a storage error."""
        try:
            self._update_status(status)
        except Exception:
            pass

    def _session_id(self) -> str | None:
        if self.session_store is None:
            return None
        return getattr(self.session_store, "session_id", None)

    def _run_finished_decision(
        self,
        *,
        status: str,
        reason: str = "",
        final_message: str = "",
        tool_steps_used: int = 0,
    ) -> HookResponse:
        return self.hook_runner.run_finished(
            RunFinishedContext(
                session_id=self._session_id(),
                repo_root=str(self.session.repo_root),
                status=status,
                reason=reason,
                final_message=final_message,
                files_read=tuple(sorted(getattr(self.session, "files_read", set()))),
                files_written=tuple(
                    sorted(getattr(self.session, "files_written", set()))
                ),
                tool_steps_used=tool_steps_used,
            )
        )

    def _hook_notes_from_decision(
        self,
        decision: HookResponse,
    ) -> tuple[str, ...]:
        return tuple(
            note
            for note in decision.notes
            if isinstance(note, str) and note.strip()
        )

    def _emit_event(self, event: dict) -> None:
        emit_agent_event(self.on_event, self._session_id(), event)

    def _emit_runtime_event(self, event: dict) -> None:
        """Persist a lifecycle fact before publishing it to optional observers."""
        if self.session_store is not None:
            append_runtime_event = getattr(
                self.session_store,
                "append_runtime_event",
                None,
            )
            if callable(append_runtime_event):
                append_runtime_event(event)
        self._emit_event(event)

    def _emit_runtime_event_preserving_error(self, event: dict) -> None:
        """Record terminal evidence without masking the exception being handled."""
        try:
            self._emit_runtime_event(event)
        except Exception:
            # Preserve the original runtime exception if diagnostic persistence
            # itself fails while the loop is already unwinding.
            pass

    def _handle_compaction_event(self, event: dict) -> None:
        """Persist compaction diagnostics and publish its visible start seam."""
        # Persistence retains the complete lifecycle. Only the authoritative
        # start belongs on the compact observer path used by presentation.
        if self.session_store is not None:
            self.session_store.append_compaction_event(event)
        if event.get("type") == "compaction_started":
            self._emit_event(event)

    def _should_stream_assistant_text(self) -> bool:
        if not self.stream_assistant_text:
            return False

        supports_streaming = getattr(self.model_adapter, "supports_streaming", None)
        return callable(supports_streaming) and bool(supports_streaming())

    def _respond(self, tool_definitions: list[dict], extra_messages=None) -> dict:
        messages = list(self.session.messages)
        if extra_messages:
            messages = [*messages, *extra_messages]
        messages = render_messages_for_model(messages, self.tool_result_trimming)
        request_event = {
            "provider": getattr(self.model_adapter, "provider_name", None),
            "model": getattr(self.model_adapter, "model_name", None),
            "message_count": len(messages),
            "estimated_request_tokens": estimate_messages_tokens(messages),
        }
        request_event = {
            name: value for name, value in request_event.items() if value is not None
        }
        self._emit_runtime_event({"type": "model_request_started", **request_event})
        started_at = perf_counter()

        try:
            if not self._should_stream_assistant_text():
                reply = self.model_adapter.respond(
                    messages=messages,
                    tool_definitions=tool_definitions,
                )
            else:
                self._emit_event(
                    {
                        "type": "assistant_message_started",
                        "phase": "narration",
                    }
                )

                def on_text_delta(delta: str) -> None:
                    self._emit_event(
                        {
                            "type": "assistant_delta",
                            "phase": "narration",
                            "delta": delta,
                        }
                    )

                def on_tool_preparing(tool_call: dict) -> None:
                    self._emit_event(tool_preparing_event(tool_call))

                reply = self.model_adapter.respond_streaming(
                    messages=messages,
                    tool_definitions=tool_definitions,
                    on_text_delta=on_text_delta,
                    on_tool_preparing=on_tool_preparing,
                )
        except BaseException as error:
            self._emit_runtime_event_preserving_error(
                {
                    "type": "model_request_failed",
                    **request_event,
                    "duration_ms": round((perf_counter() - started_at) * 1000),
                    "error_type": type(error).__name__,
                    "error_message": compact_event_text(
                        error or type(error).__name__, ERROR_EVENT_MAX_CHARS
                    ),
                }
            )
            raise

        self._emit_runtime_event(
            {
                "type": "model_request_finished",
                **request_event,
                "duration_ms": round((perf_counter() - started_at) * 1000),
            }
        )
        return reply

    # Seed a new transcript, or reconcile the one run-scoped message in an
    # existing transcript. A session may change specialization between runs,
    # while prompt, Tools, Hooks, and metadata stay fixed within each run.
    def _ensure_initial_messages(self) -> None:
        initial_messages = self.agent.initial_messages()
        if not self.session.messages:
            record_messages(
                self.session,
                self.session_store,
                *initial_messages,
            )
            return

        intended_system_messages = [
            message for message in initial_messages if message.get("role") == "system"
        ]
        if len(intended_system_messages) != 1:
            raise ValueError(
                "Agent.initial_messages() must contain exactly one system message"
            )
        reconcile_system_message(
            self.session,
            self.session_store,
            intended_system_messages[0],
        )

    def _allowed_tools_from_definitions(self, tool_definitions: list[dict]) -> tuple[str, ...]:
        names = []
        for definition in tool_definitions:
            if not isinstance(definition, dict):
                return ()
            name = definition.get("name")
            if not isinstance(name, str):
                function = definition.get("function")
                if isinstance(function, dict):
                    name = function.get("name")
            if isinstance(name, str):
                names.append(name)
        return tuple(names)

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
        # Once an assistant tool call is committed, keep enough information to
        # close that transcript pair if cancellation wins before normal result
        # persistence. A completed/denied/blocked result always takes priority
        # over the synthetic interrupted result.
        pending_tool_action = None
        pending_tool_result = None
        run_stage = "startup"

        try:
            self._check_cancelled()
            # Existing sessions keep their conversation but adopt this run's
            # system prompt. This decision stays here beside run startup so a
            # future lifecycle change cannot separate prompt reconciliation
            # from the current run's Tool and Hook configuration.
            self._ensure_initial_messages()
            self._emit_event(
                {
                    "type": "run_started",
                    "repo_root": str(self.session.repo_root),
                    "task": getattr(self.agent, "task", ""),
                }
            )
            tool_definitions = self.agent.tool_definitions()
            run_stage = "before_run_hook"
            before_run = self.hook_runner.before_run(
                BeforeRunContext(
                    session_id=self._session_id(),
                    repo_root=str(self.session.repo_root),
                    task=getattr(self.agent, "task", ""),
                    skill_name=getattr(self.agent, "skill_name", None),
                    allowed_tools=self._allowed_tools_from_definitions(tool_definitions),
                )
            )
            if before_run.block:
                reason = (
                    before_run.reason
                    or before_run.guidance
                    or "blocked by before_run hook"
                )
                self._emit_runtime_event(
                    {
                        "type": "run_failed",
                        "status": "failed",
                        "stage": run_stage,
                        "reason": reason,
                    }
                )
                self._update_status("failed")
                run_finished = self._run_finished_decision(
                    status="failed",
                    reason=reason,
                )
                self._emit_event({"type": "run_finished", "status": "failed"})
                return RunResult(
                    status="failed",
                    reason=reason,
                    follow_up_requests=run_finished.follow_up_requests,
                    hook_notes=self._hook_notes_from_decision(run_finished),
                )
            self._run_context_blocks = list(before_run.context_blocks)

            consecutive_invalid_replies = 0
            stopped_after_repeated_invalid_replies = False
            stopped_after_step_limit = False
            failure_reason = ""
            final_message = ""
            tool_steps_used = 0
            pending_runtime_messages = []

            # Keep going until the agent says the task is complete.
            while not self.agent.should_stop(self.session):
                self._check_cancelled()
                if (
                    self.max_tool_steps is not None
                    and tool_steps_used >= self.max_tool_steps
                ):
                    self.display.step_limit_reached(self.max_tool_steps)
                    run_stage = "tool_step_limit"
                    stopped_after_step_limit = True
                    failure_reason = f"reached tool step limit: {self.max_tool_steps}"
                    break

                if self.compactor is not None:
                    run_stage = "compaction"
                    self._check_cancelled()
                    self.compactor.maybe_compact(
                        self.session,
                        event_callback=self._handle_compaction_event,
                    )
                    self._check_cancelled()

                # Ask the model for the next assistant reply and any tool actions.
                self.display.thinking()
                self._check_cancelled()
                run_stage = "before_model_turn_hook"
                turn_context = self.hook_runner.before_model_turn(
                    BeforeModelTurnContext(
                        session_id=self._session_id(),
                        repo_root=str(self.session.repo_root),
                        task=getattr(self.agent, "task", ""),
                        messages=tuple(self.session.messages),
                        tool_steps_used=tool_steps_used,
                    )
                )
                context_message = turn_context_message(
                    [
                        *self._run_context_blocks,
                        *turn_context.context_blocks,
                    ]
                )
                extra_messages = [
                    *([context_message] if context_message is not None else []),
                    *pending_runtime_messages,
                ]
                run_stage = "model_request"
                reply = self._respond(tool_definitions, extra_messages=extra_messages)
                run_stage = "reply_processing"
                pending_runtime_messages = []
                self._check_cancelled()

                raw_reply_entry = None
                if self.session_store is not None:
                    raw_reply_entry = self.session_store.append_model_reply(reply["raw_reply"])

                self.display.debug_reply(reply)

                # Ask the coding agent whether this reply counts as a valid turn.
                # Invalid replies include narration-only turns, malformed tool calls,
                # wrong tool counts, and invalid finals.
                validation = self.agent.validate_reply(reply)

                # If the reply is invalid, do not store the assistant message in
                # the transcript. Instead inject a reason-specific correction and retry.
                if not validation["ok"]:
                    consecutive_invalid_replies += 1
                    if self.session_store is not None:
                        self.session_store.append_reply_rejection(
                            reply,
                            reason=validation["reason"],
                            consecutive_invalid_attempt=consecutive_invalid_replies,
                            raw_reply_id=raw_reply_entry["id"],
                        )
                    if getattr(self.display, "debug", False):
                        self.display.assistant_message(reply["message"]["content"])
                    self.display.reply_rejected(validation["reason"])
                    rejection_reason = compact_event_text(
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
                        record_message(
                            self.session,
                            self.session_store,
                            self.agent.failure_message_for_invalid_replies(
                                validation["reason"],
                                consecutive_invalid_replies,
                            )
                        )
                        stopped_after_repeated_invalid_replies = True
                        failure_reason = validation["reason"]
                        break

                    pending_runtime_messages.append(
                        self.agent.correction_message_for(validation["reason"])
                    )
                    continue

                self._check_cancelled()

                # Only valid assistant replies are added to normal transcript history.
                consecutive_invalid_replies = 0
                assistant_content = reply["message"]["content"]
                self._check_cancelled()
                if not reply["actions"]:
                    final_decision = self.hook_runner.before_accept_final(
                        BeforeAcceptFinalContext(
                            session_id=self._session_id(),
                            repo_root=str(self.session.repo_root),
                            message=reply["message"],
                            content=assistant_content,
                            files_read=tuple(
                                sorted(getattr(self.session, "files_read", set()))
                            ),
                            files_written=tuple(
                                sorted(getattr(self.session, "files_written", set()))
                            ),
                            tool_steps_used=tool_steps_used,
                        )
                    )
                    if final_decision.block:
                        guidance = (
                            final_decision.guidance
                            or final_decision.reason
                            or "Final response was blocked by before_accept_final hook. Continue the task."
                        )
                        self.display.reply_rejected("final_blocked_by_hook")
                        self._emit_event(
                            {
                                "type": "reply_rejected",
                                "reason": "final_blocked_by_hook",
                                "detail": compact_event_text(
                                    guidance,
                                    REJECTION_REASON_EVENT_MAX_CHARS,
                                ),
                            }
                        )
                        pending_runtime_messages.append(
                            user_instruction_message(guidance)
                        )
                        continue
                    if final_decision.report_note:
                        assistant_content = (
                            f"{assistant_content.rstrip()}\n\n"
                            f"{final_decision.report_note.strip()}"
                        )
                        reply["message"] = {
                            **reply["message"],
                            "content": assistant_content,
                        }

                if reply["actions"]:
                    self.display.assistant_message(assistant_content)
                    self._check_cancelled()
                    self._emit_event(
                        {
                            "type": "assistant_message",
                            "phase": "narration",
                            "message": assistant_content,
                            "text": assistant_content,
                        }
                    )
                else:
                    self.display.final_message(assistant_content)
                    self._check_cancelled()
                    self._emit_event(
                        {
                            "type": "final_message",
                            "phase": "final",
                            "message": assistant_content,
                            "text": assistant_content,
                        }
                    )
                    final_message = assistant_content
                self._check_cancelled()
                record_message(
                    self.session,
                    self.session_store,
                    reply["message"],
                    usage=reply.get("usage"),
                )
                if reply["actions"]:
                    pending_tool_action = reply["actions"][0]
                    pending_tool_result = None

                # Execute each requested tool action and collect the raw results.
                executed_actions = []
                results = []
                approval_instructions = []
                for action in reply["actions"]:
                    run_stage = "tool_execution"
                    self._check_cancelled()
                    tool_decision = self.hook_runner.before_tool_execute(
                        BeforeToolExecuteContext(
                            session_id=self._session_id(),
                            repo_root=str(self.session.repo_root),
                            action=action,
                            tool_steps_used=tool_steps_used,
                        )
                    )
                    if tool_decision.block:
                        action = tool_decision.action or action
                        pending_tool_action = action
                        reason = (
                            tool_decision.reason
                            or tool_decision.guidance
                            or "blocked by before_tool_execute hook"
                        )
                        result = {
                            "ok": False,
                            "error": "blocked_by_hook",
                            "reason": reason,
                            "guidance": tool_decision.guidance,
                        }
                        pending_tool_result = result
                        approval_action = action
                    else:
                        action = tool_decision.action or action
                        pending_tool_action = action
                        preflight = self.action_preflight.check(
                            action,
                            additional_approval_reason=tool_decision.approval_reason,
                        )
                        approval_action = preflight.approval_action
                        self._check_cancelled()
                        decision = self.approval_policy.check(approval_action)
                        self._check_cancelled()
                        if decision.approved:
                            self.display.action_started(approval_action)
                            self._check_cancelled()
                            self._emit_event(
                                {
                                    "type": "tool_started",
                                    **action_event_fields(action),
                                }
                            )
                            self._check_cancelled()
                            result = self.tool_executor.execute(
                                preflight.execution_action
                            )
                            pending_tool_result = result
                            self._check_cancelled()
                        else:
                            result = denied_result(action, decision.reason)
                            pending_tool_result = result
                            if decision.instruction.strip():
                                approval_instructions.append(decision.instruction)
                    tool_result_response = self.hook_runner.tool_result(
                        ToolResultContext(
                            session_id=self._session_id(),
                            repo_root=str(self.session.repo_root),
                            action=action,
                            result=result,
                        )
                    )
                    result = tool_result_response.updated_tool_output
                    # Hook guidance uses the same one-request-only path as other
                    # runtime corrections and never enters canonical history.
                    if tool_result_response.additional_context:
                        pending_runtime_messages.append(
                            user_instruction_message(
                                tool_result_response.additional_context
                            )
                        )
                    pending_tool_result = result
                    self.display.tool_result(approval_action, result)
                    self._check_cancelled()
                    self._emit_event(
                        {
                            "type": "tool_finished",
                            "ok": bool(result.get("ok", False)),
                            **action_event_fields(action),
                        }
                    )
                    executed_actions.append(action)
                    results.append(result)

                # Convert tool results into transcript messages and store them.
                result_messages = self.tool_results.messages_from_action_results(
                    executed_actions,
                    results,
                )
                self._check_cancelled()
                record_messages(self.session, self.session_store, *result_messages)
                pending_tool_action = None
                pending_tool_result = None
                record_messages(
                    self.session,
                    self.session_store,
                    *[
                        user_instruction_message(instruction)
                        for instruction in approval_instructions
                    ]
                )

                if reply["actions"]:
                    tool_steps_used += 1

            if stopped_after_repeated_invalid_replies or stopped_after_step_limit:
                self._emit_runtime_event(
                    {
                        "type": "run_failed",
                        "status": "failed",
                        "stage": run_stage,
                        "reason": failure_reason,
                    }
                )
                self._update_status("failed")
                run_finished = self._run_finished_decision(
                    status="failed",
                    reason=failure_reason,
                    tool_steps_used=tool_steps_used,
                )
                self._emit_event({"type": "run_finished", "status": "failed"})
                return RunResult(
                    status="failed",
                    reason=failure_reason,
                    follow_up_requests=run_finished.follow_up_requests,
                    hook_notes=self._hook_notes_from_decision(run_finished),
                )

            self._check_cancelled()
            run_stage = "run_finished_hook"
            try:
                run_finished = self._run_finished_decision(
                    status="complete",
                    final_message=final_message,
                    tool_steps_used=tool_steps_used,
                )
            except Exception as error:
                reason = f"run_finished hook failed: {error or type(error).__name__}"
                self._emit_runtime_event(
                    {
                        "type": "run_failed",
                        "status": "failed",
                        "stage": run_stage,
                        "reason": reason,
                    }
                )
                self._update_status("failed")
                self._emit_event({"type": "run_finished", "status": "failed"})
                return RunResult(status="failed", reason=reason)

            self._update_status("complete")
            self._emit_event({"type": "run_finished", "status": "complete"})
            return RunResult(
                status="complete",
                follow_up_requests=run_finished.follow_up_requests,
                hook_notes=self._hook_notes_from_decision(run_finished),
            )
        except _CancellationRequested:
            record_pending_tool_result(
                self.session,
                self.session_store,
                self.tool_results,
                pending_tool_action,
                pending_tool_result,
            )
            self._emit_runtime_event(
                {
                    "type": "run_interrupted",
                    "status": "interrupted",
                    "reason": "cancelled",
                    "requested": True,
                    "stage": run_stage,
                }
            )
            self._update_status("interrupted")
            run_finished = self._run_finished_decision(
                status="interrupted",
                reason="cancelled",
            )
            self._emit_event({"type": "run_finished", "status": "interrupted"})
            return RunResult(
                status="interrupted",
                reason="cancelled",
                follow_up_requests=run_finished.follow_up_requests,
                hook_notes=self._hook_notes_from_decision(run_finished),
            )
        except KeyboardInterrupt:
            # Repair any committed tool-call pair and leave durable evidence
            # before preserving the CLI's KeyboardInterrupt control flow.
            record_pending_tool_result(
                self.session,
                self.session_store,
                self.tool_results,
                pending_tool_action,
                pending_tool_result,
            )
            self._emit_runtime_event_preserving_error(
                {
                    "type": "run_interrupted",
                    "status": "interrupted",
                    "interruption_type": "KeyboardInterrupt",
                    "stage": run_stage,
                }
            )
            self._update_status_preserving_error("interrupted")
            raise
        except Exception as error:
            self._emit_runtime_event_preserving_error(
                {
                    "type": "run_failed",
                    "status": "failed",
                    "stage": run_stage,
                    "error_type": type(error).__name__,
                    "error_message": compact_event_text(
                        error or type(error).__name__, ERROR_EVENT_MAX_CHARS
                    ),
                }
            )
            self._update_status_preserving_error("failed")
            raise
        except BaseException as error:
            self._emit_runtime_event_preserving_error(
                {
                    "type": "run_interrupted",
                    "status": "interrupted",
                    "interruption_type": type(error).__name__,
                    "stage": run_stage,
                }
            )
            self._update_status_preserving_error("interrupted")
            raise

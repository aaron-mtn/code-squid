# core/agent_loop.py

MAX_CONSECUTIVE_INVALID_REPLIES = 3

class AgentLoop:
    """Owns the generic agent loop and transcript turn flow; must not own coding-specific policy, prompts, or tool definitions."""

    # Store the parts needed to run the loop.
    # The loop depends on the session, model adapter, tool executor,
    # tool result formatter, and the coding agent behavior.
    def __init__(self, session, model_adapter, tool_executor, tool_results, agent, display) -> None:
        self.session = session
        self.model_adapter = model_adapter
        self.tool_executor = tool_executor
        self.tool_results = tool_results
        self.agent = agent
        self.display = display

    # Run the agent loop until the agent says it should stop.
    # Each loop iteration:
    # 1. asks the model for the next reply and tool actions
    # 2. validates whether that reply counts as a real agent turn
    # 3. rejects invalid replies before they enter assistant history
    # 4. stores valid assistant replies in the session
    # 5. executes each tool action
    # 6. announces each tool result to the display
    # 7. converts tool results into transcript messages
    # 8. stores those result messages in the session
    def run(self) -> None:
        # Start the transcript with the agent's initial system and user messages.
        self.session.add_messages(*self.agent.initial_messages())
        consecutive_invalid_replies = 0

        # Keep going until the agent says the task is complete.
        while not self.agent.should_stop(self.session):
            # Ask the model for the next assistant reply and any tool actions.
            self.display.thinking()
            reply = self.model_adapter.respond(
                messages=self.session.messages,
                tool_definitions=self.agent.tool_definitions(),
            )

            self.display.assistant_message(reply["message"]["content"])
            self.display.debug_reply(reply)

            # Ask the coding agent whether this reply counts as a valid turn.
            # Invalid replies include narration-only turns, malformed tool calls,
            # wrong tool counts, and invalid finals.
            validation = self.agent.validate_reply(reply)

            # If the reply is invalid, do not store the assistant message in
            # the transcript. Instead inject a reason-specific correction and retry.
            if not validation["ok"]:
                consecutive_invalid_replies += 1
                self.display.reply_rejected(validation["reason"])
                if consecutive_invalid_replies == MAX_CONSECUTIVE_INVALID_REPLIES:
                    self.display.repeated_invalid_replies(
                        validation["reason"],
                        consecutive_invalid_replies,
                    )
                    self.session.add_message(
                        self.agent.failure_message_for_invalid_replies(
                            validation["reason"],
                            consecutive_invalid_replies,
                        )
                    )
                    break

                self.session.add_message(self.agent.correction_message_for(validation["reason"]))
                continue

            # Only valid assistant replies are added to normal transcript history.
            consecutive_invalid_replies = 0
            self.session.add_message(reply["message"])

            # Execute each requested tool action and collect the raw results.
            results = []
            for action in reply["actions"]:
                self.display.action_started(action)
                result = self.tool_executor.execute(action)
                self.display.tool_result(action, result)

                results.append(result)

            # Convert tool results into transcript messages and store them.
            result_messages = self.tool_results.messages_from_action_results(
                reply["actions"],
                results,
            )
            self.session.add_messages(*result_messages)

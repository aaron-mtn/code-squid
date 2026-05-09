# core/agent_loop.py

class AgentLoop:
    """Owns the generic agent loop and transcript turn flow; must not own coding-specific policy, prompts, or tool definitions."""

    # Store the parts needed to run the loop.
    # The loop depends on the session, model adapter, tool executor,
    # tool result formatter, and the coding agent behavior.
    def __init__(self, session, model_adapter, tool_executor, tool_results, agent) -> None:
        self.session = session
        self.model_adapter = model_adapter
        self.tool_executor = tool_executor
        self.tool_results = tool_results
        self.agent = agent

    # Run the agent loop until the agent says it should stop.
    # Each loop iteration:
    # 1. asks the model for the next reply and tool actions
    # 2. validates whether that reply counts as a real agent turn
    # 3. rejects invalid non-final no-tool replies before they enter history
    # 4. stores valid assistant replies in the session
    # 5. executes each tool action
    # 6. prints each tool result for debugging
    # 7. converts tool results into transcript messages
    # 8. stores those result messages in the session
    def run(self) -> None:
        # Start the transcript with the agent's initial system and user messages.
        self.session.add_messages(*self.agent.initial_messages())

        # Keep going until the agent says the task is complete.
        while not self.agent.should_stop(self.session):
            # Ask the model for the next assistant reply and any tool actions.
            print("-> asking model")
            reply = self.model_adapter.respond(
                messages=self.session.messages,
                tool_definitions=self.agent.tool_definitions(),
            )

            # Print the assistant message content so it is easier to debug
            # what the model is thinking and whether it is close to stopping.
            print("-> model replied")
            print(f"assistant: {reply['message']['content']}")
            print(f"actions: {reply['actions']}")

            # Ask the coding agent whether this reply counts as a valid turn.
            # Invalid replies are usually narration-only responses that should
            # have included a tool call but did not.
            validation = self.agent.validate_reply(reply)

            # If the reply is invalid, do not store the assistant message in
            # the transcript. Instead inject the stall reminder and retry.
            if not validation["ok"]:
                print(f"-> rejected reply: {validation['reason']}")
                print("-> injecting stall reminder")
                self.session.add_message(self.agent.stall_message())
                continue

            # Only valid assistant replies are added to normal transcript history.
            self.session.add_message(reply["message"])

            # Execute each requested tool action and collect the raw results.
            results = []
            for action in reply["actions"]:
                print(f"-> running tool: {action['tool']}")
                result = self.tool_executor.execute(action)

                # Print the raw tool result so it is easier to debug what the
                # tool returned and why the model may choose the next step.
                print(f"tool result: {result}")

                results.append(result)

            # Convert tool results into transcript messages and store them.
            result_messages = self.tool_results.messages_from_results(results)
            self.session.add_messages(*result_messages)
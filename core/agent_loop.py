# core/agent_loop.py

class AgentLoop:
    """Owns the generic agent loop and transcript turn flow; must not own coding-specific policy, prompts, or tool definitions."""

    # Store the parts needed to run the loop.
    # The loop depends on the session, model adapter, tool executor,
    # tool result formatter, and the coding agent behavior.
    # It also keeps a small counter for repeated stalled turns so the
    # loop can recover when the model hesitates.
    def __init__(self, session, model_adapter, tool_executor, tool_results, agent) -> None:
        self.session = session
        self.model_adapter = model_adapter
        self.tool_executor = tool_executor
        self.tool_results = tool_results
        self.agent = agent
        self.stalled_turns = 0

    # Run the agent loop until the agent says it should stop.
    # Each loop iteration:
    # 1. asks the model for the next reply and tool actions
    # 2. stores the assistant reply in the session
    # 3. prints the assistant reply for debugging
    # 4. prints the normalized action list for debugging
    # 5. checks for repeated stalled turns
    # 6. injects a reminder message if the model stalls
    # 7. executes each tool action
    # 8. prints each tool result for debugging
    # 9. converts tool results into transcript messages
    # 10. stores those result messages in the session
    def run(self) -> None:
        self.session.add_messages(*self.agent.initial_messages())

        while not self.agent.should_stop(self.session):
            # Ask the model for the next assistant reply and any tool actions.
            print("-> asking model")
            reply = self.model_adapter.respond(
                messages=self.session.messages,
                tool_definitions=self.agent.tool_definitions(),
            )

            # Store the assistant message in the session transcript.
            print("-> model replied")
            self.session.add_message(reply["message"])

            # Print the assistant message content so it is easier to debug
            # what the model is thinking and whether it is close to stopping.
            print(f"assistant: {reply['message']['content']}")

            # Print the normalized action list so it is obvious when the model
            # returned no tool calls or when the parsed actions look wrong.
            print(f"actions: {reply['actions']}")

            # If the model did not issue any actions, count that as a stalled
            # turn unless the agent is already ready to stop.
            if not reply["actions"] and not self.agent.should_stop(self.session):
                self.stalled_turns += 1
            else:
                self.stalled_turns = 0

            # If the model stalls for multiple turns in a row, inject a small
            # reminder message to nudge it back into taking an action.
            if self.stalled_turns >= 2:
                print("-> injecting stall reminder")
                self.session.add_message(self.agent.stall_message())
                self.stalled_turns = 0
                continue

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
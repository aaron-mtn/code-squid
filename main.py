# main.py

"""Owns thin application wiring for standalone Code Squid; must not own core architecture, agent policy, or tool logic."""

import os
from pathlib import Path

from agent.coding import CodingAgent
from core.agent_loop import AgentLoop
from core.model_adapter import ModelAdapter
from core.session import Session
from core.tool_executor import ToolExecutor
from core.tool_results import ToolResults
from providers.lmstudio import LMStudioProvider



# Create the app objects, wire them together, and run one coding task.
def main() -> None:
    repo_root = Path(".").resolve()
    task = input("Task: ")

    session = Session(repo_root=repo_root)
    provider = LMStudioProvider(
        base_url=os.getenv("CODE_SQUID_BASE_URL", "http://127.0.0.1:1234/v1"),
        api_key=os.getenv("CODE_SQUID_API_KEY", "lm-studio"),
    )
    model_adapter = ModelAdapter(
        provider=provider,
        model_name=os.getenv("CODE_SQUID_MODEL", "qwen3.5-9b"),
    )
    tool_executor = ToolExecutor(repo_root=repo_root)
    tool_results = ToolResults()
    agent = CodingAgent(task=task)

    loop = AgentLoop(
        session=session,
        model_adapter=model_adapter,
        tool_executor=tool_executor,
        tool_results=tool_results,
        agent=agent,
    )
    loop.run()

    for message in session.messages:
        print(f"\n[{message['role']}]")
        print(message["content"])


# Run the app when this file is executed directly.
if __name__ == "__main__":
    main()
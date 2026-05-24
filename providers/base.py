# providers/base.py

class BaseProvider:
    """Owns the raw request/response call to a model provider; must not own agent policy, loop control, or tool execution."""

    def create_response(
        self,
        model: str,
        messages: list[dict],
        tools: list[dict],
        tool_choice=None,
    ) -> object:
        raise NotImplementedError

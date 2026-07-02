"""Shared pytest isolation for Code Squid's user-level storage boundaries."""

from pathlib import Path
from types import ModuleType, SimpleNamespace
import sys

import pytest


try:
    import openai  # noqa: F401
except ModuleNotFoundError:
    openai_stub = ModuleType("openai")

    class OpenAI:
        def __init__(self, *args, **kwargs) -> None:
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=self._missing_openai)
            )

        def _missing_openai(self, *args, **kwargs):
            raise RuntimeError("openai package is not installed")

    openai_stub.OpenAI = OpenAI
    sys.modules["openai"] = openai_stub


try:
    import prompt_toolkit  # noqa: F401
except ModuleNotFoundError:
    prompt_toolkit_stub = ModuleType("prompt_toolkit")
    formatted_text_stub = ModuleType("prompt_toolkit.formatted_text")
    input_stub = ModuleType("prompt_toolkit.input")
    ansi_stub = ModuleType("prompt_toolkit.input.ansi_escape_sequences")
    key_binding_stub = ModuleType("prompt_toolkit.key_binding")
    keys_stub = ModuleType("prompt_toolkit.keys")

    class PromptSession:
        def prompt(self, *args, **kwargs) -> str:
            raise RuntimeError("prompt_toolkit package is not installed")

    class KeyBindings:
        def __init__(self) -> None:
            self.bindings = []

        def add(self, *keys):
            def decorator(func):
                self.bindings.append((keys, func))
                return func

            return decorator

    def FormattedText(value):
        return value

    def print_formatted_text(*args, **kwargs) -> None:
        pass

    formatted_text_stub.AnyFormattedText = object
    formatted_text_stub.FormattedText = FormattedText
    ansi_stub.ANSI_SEQUENCES = {}
    key_binding_stub.KeyBindings = KeyBindings
    keys_stub.Keys = SimpleNamespace(ControlJ="c-j")
    prompt_toolkit_stub.PromptSession = PromptSession
    prompt_toolkit_stub.print_formatted_text = print_formatted_text

    sys.modules["prompt_toolkit"] = prompt_toolkit_stub
    sys.modules["prompt_toolkit.formatted_text"] = formatted_text_stub
    sys.modules["prompt_toolkit.input"] = input_stub
    sys.modules["prompt_toolkit.input.ansi_escape_sequences"] = ansi_stub
    sys.modules["prompt_toolkit.key_binding"] = key_binding_stub
    sys.modules["prompt_toolkit.keys"] = keys_stub


@pytest.fixture(autouse=True)
def isolated_session_indexes(monkeypatch, tmp_path_factory) -> Path:
    """Route every test's global session registry into pytest's temp root."""
    index_path = tmp_path_factory.getbasetemp() / "session-indexes.jsonl"
    monkeypatch.setenv("CODE_SQUID_SESSION_INDEXES", str(index_path))
    return index_path

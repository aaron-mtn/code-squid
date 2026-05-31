from prompt_toolkit.input.ansi_escape_sequences import ANSI_SEQUENCES
from prompt_toolkit.keys import Keys

from ui.prompt_input import prompt_multiline_input


def test_prompt_multiline_input_uses_shared_multiline_bindings(monkeypatch) -> None:
    prompt_calls = []
    prefaces = []

    class FakePromptSession:
        def prompt(self, *args, **kwargs) -> str:
            prompt_calls.append((args, kwargs))
            return "line one\nline two"

    monkeypatch.setattr("ui.prompt_input.PromptSession", FakePromptSession)
    monkeypatch.setattr(
        "ui.prompt_input.print_formatted_text",
        lambda text: prefaces.append(text),
    )

    result = prompt_multiline_input("› ", preface="@code-squid")

    assert result == "line one\nline two"
    assert prefaces == ["@code-squid"]
    args, kwargs = prompt_calls[0]
    assert args == ("› ",)
    assert kwargs["multiline"] is True
    assert kwargs["key_bindings"] is not None
    assert ANSI_SEQUENCES["\x1b[27;2;13~"] == Keys.ControlJ
    assert ANSI_SEQUENCES["\x1b[13;2u"] == Keys.ControlJ

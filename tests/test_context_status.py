from types import SimpleNamespace

from squid_core.compaction.compaction_status import (
    build_context_status,
    format_token_count,
)
from squid_core.compaction.token_estimate import estimate_messages_tokens


def settings(
    enabled: bool = True,
    trigger_input_tokens: int | None = 100,
    keep_recent_turns: int | None = 8,
) -> SimpleNamespace:
    return SimpleNamespace(
        enabled=enabled,
        trigger_input_tokens=trigger_input_tokens,
        keep_recent_turns=keep_recent_turns,
    )


def test_token_formatting_under_1000() -> None:
    assert format_token_count(0) == "0"
    assert format_token_count(999) == "999"


def test_token_formatting_exact_thousands() -> None:
    assert format_token_count(1000) == "1k"
    assert format_token_count(48000) == "48k"


def test_token_formatting_decimal_thousands() -> None:
    assert format_token_count(12300) == "12.3k"


def test_enabled_compaction_payload() -> None:
    messages = [{"role": "user", "content": "x" * 80}]
    estimated_tokens = estimate_messages_tokens(messages)

    status = build_context_status(
        messages,
        settings(enabled=True, trigger_input_tokens=100, keep_recent_turns=4),
    )

    assert status.to_dict() == {
        "estimated_tokens": estimated_tokens,
        "limit_tokens": 100,
        "percent": round(estimated_tokens / 100 * 100),
        "label": f"{format_token_count(estimated_tokens)} / 100",
        "compaction_enabled": True,
        "trigger_input_tokens": 100,
        "keep_recent_turns": 4,
    }


def test_disabled_compaction_payload() -> None:
    messages = [{"role": "user", "content": "x" * 80}]
    estimated_tokens = estimate_messages_tokens(messages)

    status = build_context_status(
        messages,
        settings(enabled=False, trigger_input_tokens=100, keep_recent_turns=4),
    )

    assert status.to_dict() == {
        "estimated_tokens": estimated_tokens,
        "limit_tokens": None,
        "percent": None,
        "label": format_token_count(estimated_tokens),
        "compaction_enabled": False,
        "trigger_input_tokens": 100,
        "keep_recent_turns": 4,
    }


def test_zero_trigger_safety() -> None:
    status = build_context_status(
        [{"role": "user", "content": "hello"}],
        settings(enabled=True, trigger_input_tokens=0),
    )

    assert status.limit_tokens is None
    assert status.percent is None
    assert status.label == format_token_count(status.estimated_tokens)


def test_missing_trigger_safety() -> None:
    status = build_context_status(
        [{"role": "user", "content": "hello"}],
        SimpleNamespace(enabled=True, keep_recent_turns=3),
    )

    assert status.limit_tokens is None
    assert status.percent is None
    assert status.trigger_input_tokens is None
    assert status.keep_recent_turns == 3
    assert status.label == format_token_count(status.estimated_tokens)


def test_empty_messages() -> None:
    status = build_context_status([], settings(enabled=True, trigger_input_tokens=100))

    assert status.estimated_tokens == 0
    assert status.limit_tokens == 100
    assert status.percent == 0
    assert status.label == "0 / 100"

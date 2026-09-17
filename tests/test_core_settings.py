"""Tests for generic Squid Core runtime-setting semantics."""

import pytest

from squid_core.settings import (
    CompactionSettings,
    ProviderSettings,
    ReadFileSettings,
    RuntimeSettings,
)


def compaction_settings() -> CompactionSettings:
    return CompactionSettings(
        enabled=True,
        trigger_input_tokens=1_000,
        compact_fraction=0.8,
        min_recent_chunks=2,
    )


@pytest.mark.parametrize("compact_fraction", [0, -0.1, 1.1, True, "0.8"])
def test_core_rejects_invalid_compact_fraction(compact_fraction: object) -> None:
    with pytest.raises(ValueError, match="compact_fraction"):
        CompactionSettings(compact_fraction=compact_fraction)


@pytest.mark.parametrize("min_recent_chunks", [-1, True, 2.0, "2"])
def test_core_rejects_invalid_min_recent_chunks(min_recent_chunks: object) -> None:
    with pytest.raises(ValueError, match="min_recent_chunks"):
        CompactionSettings(min_recent_chunks=min_recent_chunks)


def test_custom_adapter_runtime_settings_need_no_provider_selection() -> None:
    settings = RuntimeSettings(
        provider=None,
        approval_mode="guarded",
        max_tool_steps=4,
        stream_assistant_text=True,
        compaction=compaction_settings(),
    )

    assert settings.provider is None
    assert settings.read_file == ReadFileSettings(
        default_max_lines=1000,
        minimum_range_lines=150,
    )


@pytest.mark.parametrize("value", [0, -1, True, 1.5, "150"])
def test_core_rejects_invalid_read_file_sizing(value: object) -> None:
    with pytest.raises(ValueError, match="read_file"):
        ReadFileSettings(minimum_range_lines=value)  # type: ignore[arg-type]


@pytest.mark.parametrize("max_tool_steps", [0, -1, True])
def test_core_rejects_invalid_tool_step_semantics(max_tool_steps: object) -> None:
    with pytest.raises(ValueError, match="max_tool_steps"):
        RuntimeSettings(
            provider=None,
            approval_mode="never",
            max_tool_steps=max_tool_steps,
            stream_assistant_text=False,
            compaction=compaction_settings(),
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("model_request_max_retries", -1),
        ("model_request_max_retries", 11),
        ("model_request_retry_backoff_ms", -1),
        ("model_request_retry_backoff_ms", 10_001),
    ],
)
def test_runtime_settings_reject_invalid_model_request_retry_values(
    field: str,
    value: int,
) -> None:
    values = {
        "provider": None,
        "approval_mode": "never",
        "max_tool_steps": None,
        "stream_assistant_text": False,
        "compaction": CompactionSettings(),
        field: value,
    }

    with pytest.raises(ValueError, match=field):
        RuntimeSettings(**values)


def test_core_rejects_invalid_temperature_semantics() -> None:
    with pytest.raises(ValueError, match="temperature"):
        ProviderSettings(
            provider="custom",
            model_name="model",
            base_url=None,
            api_key=None,
            temperature=3,
        )


def test_core_reasoning_mode_defaults_to_none() -> None:
    settings = ProviderSettings(
        provider="custom",
        model_name="model",
        base_url=None,
        api_key=None,
    )

    assert settings.reasoning_mode is None
    assert settings.reasoning_token_budget is None


@pytest.mark.parametrize("reasoning_token_budget", [0, 1, 4_000])
def test_core_accepts_reasoning_token_budgets(
    reasoning_token_budget: int,
) -> None:
    settings = ProviderSettings(
        provider="custom",
        model_name="model",
        base_url=None,
        api_key=None,
        reasoning_token_budget=reasoning_token_budget,
    )

    assert settings.reasoning_token_budget == reasoning_token_budget


@pytest.mark.parametrize(
    "reasoning_token_budget",
    [True, False, -1, 1.5, "4000", [], {}],
)
def test_core_rejects_invalid_reasoning_token_budgets(
    reasoning_token_budget: object,
) -> None:
    with pytest.raises(ValueError, match="reasoning_token_budget"):
        ProviderSettings(
            provider="custom",
            model_name="model",
            base_url=None,
            api_key=None,
            reasoning_token_budget=reasoning_token_budget,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("reasoning_mode", ["off", "low", "medium", "high"])
def test_core_accepts_normalized_reasoning_modes(reasoning_mode: str) -> None:
    settings = ProviderSettings(
        provider="custom",
        model_name="model",
        base_url=None,
        api_key=None,
        reasoning_mode=reasoning_mode,
    )

    assert settings.reasoning_mode == reasoning_mode


@pytest.mark.parametrize(
    "reasoning_mode",
    ["auto", "max", "xhigh", "none", 1, ["high"]],
)
def test_core_rejects_invalid_reasoning_modes(reasoning_mode: object) -> None:
    with pytest.raises(ValueError, match="reasoning_mode"):
        ProviderSettings(
            provider="custom",
            model_name="model",
            base_url=None,
            api_key=None,
            reasoning_mode=reasoning_mode,
        )

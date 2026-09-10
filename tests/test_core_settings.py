"""Tests for generic Squid Core runtime-setting semantics."""

import pytest

from squid_core.settings import CompactionSettings, ProviderSettings, RuntimeSettings


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


def test_core_rejects_invalid_temperature_semantics() -> None:
    with pytest.raises(ValueError, match="temperature"):
        ProviderSettings(
            provider="custom",
            model_name="model",
            base_url=None,
            api_key=None,
            temperature=3,
        )

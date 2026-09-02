"""Generic settings understood by the reusable Squid Core runtime."""

from __future__ import annotations

from dataclasses import dataclass


VALID_APPROVAL_MODES = frozenset({"always", "guarded", "never"})


@dataclass(frozen=True)
class ProviderSettings:
    """Effective provider values needed to construct a built-in adapter."""

    provider: str
    model_name: str
    base_url: str | None
    api_key: str | None
    temperature: float | int | None = None

    def __post_init__(self) -> None:
        if not self.provider:
            raise ValueError("provider must not be empty")
        if not self.model_name:
            raise ValueError("model_name must not be empty")
        if (
            self.temperature is not None
            and (
                isinstance(self.temperature, bool)
                or not isinstance(self.temperature, int | float)
                or not 0 <= self.temperature <= 2
            )
        ):
            raise ValueError("temperature must be null or a number from 0 through 2")


@dataclass(frozen=True)
class CompactionSettings:
    """Runtime transcript compaction semantics."""

    enabled: bool
    trigger_input_tokens: int
    keep_recent_turns: int

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise ValueError("compaction enabled must be a boolean")
        for name, value in (
            ("trigger_input_tokens", self.trigger_input_tokens),
            ("keep_recent_turns", self.keep_recent_turns),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"compaction {name} must be a positive integer")


@dataclass(frozen=True)
class RuntimeSettings:
    """Effective settings that affect generic runtime behavior."""

    provider: ProviderSettings | None
    approval_mode: str
    max_tool_steps: int | None
    stream_assistant_text: bool
    compaction: CompactionSettings

    def __post_init__(self) -> None:
        if self.approval_mode not in VALID_APPROVAL_MODES:
            valid_modes = ", ".join(sorted(VALID_APPROVAL_MODES))
            raise ValueError(f"approval_mode must be one of {valid_modes}")
        if (
            self.max_tool_steps is not None
            and (
                isinstance(self.max_tool_steps, bool)
                or not isinstance(self.max_tool_steps, int)
                or self.max_tool_steps < 1
            )
        ):
            raise ValueError("max_tool_steps must be null or a positive integer")
        if not isinstance(self.stream_assistant_text, bool):
            raise ValueError("stream_assistant_text must be a boolean")

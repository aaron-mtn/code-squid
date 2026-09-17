"""Generic settings understood by the reusable Squid Core runtime."""

from __future__ import annotations

from dataclasses import dataclass, field


VALID_APPROVAL_MODES = frozenset({"always", "guarded", "never"})
VALID_REASONING_MODES = frozenset({"off", "low", "medium", "high"})


@dataclass(frozen=True)
class ProviderSettings:
    """Effective provider values needed to construct a built-in adapter."""

    provider: str
    model_name: str
    base_url: str | None
    api_key: str | None
    temperature: float | int | None = None
    reasoning_mode: str | None = None
    reasoning_token_budget: int | None = None

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
        if (
            self.reasoning_mode is not None
            and (
                not isinstance(self.reasoning_mode, str)
                or self.reasoning_mode not in VALID_REASONING_MODES
            )
        ):
            valid_modes = ", ".join(sorted(VALID_REASONING_MODES))
            raise ValueError(
                f"reasoning_mode must be null or one of {valid_modes}"
            )
        if (
            self.reasoning_token_budget is not None
            and (
                isinstance(self.reasoning_token_budget, bool)
                or not isinstance(self.reasoning_token_budget, int)
                or self.reasoning_token_budget < 0
            )
        ):
            raise ValueError(
                "reasoning_token_budget must be null or a non-negative integer"
            )


@dataclass(frozen=True)
class CompactionSettings:
    """Runtime transcript compaction semantics."""

    enabled: bool = True
    trigger_input_tokens: int = 25_000
    compact_fraction: float = 0.80
    min_recent_chunks: int = 2

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise ValueError("compaction enabled must be a boolean")
        if (
            isinstance(self.trigger_input_tokens, bool)
            or not isinstance(self.trigger_input_tokens, int)
            or self.trigger_input_tokens < 1
        ):
            raise ValueError(
                "compaction trigger_input_tokens must be a positive integer"
            )
        if (
            isinstance(self.compact_fraction, bool)
            or not isinstance(self.compact_fraction, int | float)
            or not 0 < self.compact_fraction <= 1
        ):
            raise ValueError(
                "compaction compact_fraction must be greater than 0 and at most 1"
            )
        if (
            isinstance(self.min_recent_chunks, bool)
            or not isinstance(self.min_recent_chunks, int)
            or self.min_recent_chunks < 0
        ):
            raise ValueError(
                "compaction min_recent_chunks must be a non-negative integer"
            )


@dataclass(frozen=True)
class ToolResultTrimmingSettings:
    """Tune the smaller view of older tool results sent to the model."""

    enabled: bool = True
    recent_full_results: int = 5
    read_old_content_chars: int = 1000
    command_old_output_chars: int = 1000
    patch_old_diagnostic_chars: int = 800
    write_old_content_chars: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise ValueError("tool-result trimming enabled must be a boolean")
        for name, value in (
            ("recent_full_results", self.recent_full_results),
            ("read_old_content_chars", self.read_old_content_chars),
            ("command_old_output_chars", self.command_old_output_chars),
            ("patch_old_diagnostic_chars", self.patch_old_diagnostic_chars),
            ("write_old_content_chars", self.write_old_content_chars),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(
                    f"tool-result trimming {name} must be a non-negative integer"
                )


@dataclass(frozen=True)
class ReadFileSettings:
    """Tune built-in file-read sizing without changing its public schema."""

    default_max_lines: int = 1000
    minimum_range_lines: int = 150

    def __post_init__(self) -> None:
        for name, value in (
            ("default_max_lines", self.default_max_lines),
            ("minimum_range_lines", self.minimum_range_lines),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"read_file {name} must be a positive integer")


@dataclass(frozen=True)
class RuntimeSettings:
    """Effective settings that affect generic runtime behavior."""

    provider: ProviderSettings | None
    approval_mode: str
    max_tool_steps: int | None
    stream_assistant_text: bool
    compaction: CompactionSettings
    tool_result_trimming: ToolResultTrimmingSettings = field(
        default_factory=ToolResultTrimmingSettings
    )
    read_file: ReadFileSettings = field(default_factory=ReadFileSettings)
    model_request_max_retries: int = 2
    model_request_retry_backoff_ms: int = 250

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
        if (
            isinstance(self.model_request_max_retries, bool)
            or not isinstance(self.model_request_max_retries, int)
            or not 0 <= self.model_request_max_retries <= 10
        ):
            raise ValueError("model_request_max_retries must be an integer from 0 through 10")
        if (
            isinstance(self.model_request_retry_backoff_ms, bool)
            or not isinstance(self.model_request_retry_backoff_ms, int)
            or not 0 <= self.model_request_retry_backoff_ms <= 10_000
        ):
            raise ValueError(
                "model_request_retry_backoff_ms must be an integer from 0 through 10000"
            )

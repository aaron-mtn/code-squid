"""Startup information rendering for the Code Squid console."""

from dataclasses import dataclass
from pathlib import Path

from code_squid.console.ui.formatting import DIM_STYLE, styled_text


STARTUP_DIVIDER = "─" * 61
FRIENDLY_APPROVAL_MODES = {
    "always": "strict",
    "guarded": "balanced",
    "never": "yolo",
}


@dataclass(frozen=True)
class StartupInfo:
    """Values shown beneath the header for an interactive run."""

    directory: Path
    provider: str
    model: str
    approval_mode: str
    skill_name: str | None = None


def startup_info_panel(startup_info: StartupInfo) -> str:
    """Render restrained startup details without card or border chrome."""
    lines = [
        styled_text(STARTUP_DIVIDER, DIM_STYLE),
        _startup_info_line("Provider", startup_info.provider),
        _startup_info_line("Model", startup_info.model),
        _startup_info_line("Safety", startup_info.approval_mode),
    ]
    if startup_info.skill_name is not None:
        lines.append(_startup_info_line("Skill", startup_info.skill_name))
    lines.append(_startup_info_line("Workspace", str(startup_info.directory)))
    return "\n".join(lines)


def _startup_info_line(label: str, value: str) -> str:
    """Align a startup label while leaving its value as normal content."""
    return f"{label:<10}{value}"

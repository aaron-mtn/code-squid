"""Startup banner data and rendering for the Code Squid console."""

from dataclasses import dataclass
from pathlib import Path

from code_squid.console.ui.formatting import (
    structural_bordered_line,
    structural_text,
    truncate_middle,
)


CODE_SQUID_BANNER = """\

 ██████╗ ██████╗ ██████╗ ███████╗    ███████╗ ██████╗ ██╗   ██╗██╗██████╗
██╔════╝██╔═══██╗██╔══██╗██╔════╝    ██╔════╝██╔═══██╗██║   ██║██║██╔══██╗
██║     ██║   ██║██║  ██║█████╗      ███████╗██║   ██║██║   ██║██║██║  ██║
██║     ██║   ██║██║  ██║██╔══╝      ╚════██║██║▄▄ ██║██║   ██║██║██║  ██║
╚██████╗╚██████╔╝██████╔╝███████╗    ███████║╚██████╔╝╚██████╔╝██║██████╔╝
 ╚═════╝ ╚═════╝ ╚═════╝ ╚══════╝    ╚══════╝ ╚══▀▀═╝  ╚═════╝ ╚═╝╚═════╝

                 🦑 A small coding agent with tentacles."""
STARTUP_PANEL_WIDTH = 76
FRIENDLY_APPROVAL_MODES = {
    "always": "strict",
    "guarded": "balanced",
    "never": "yolo",
}
STARTUP_CONTROLS = "Enter send • Alt+Enter newline • Ctrl+C stop"


@dataclass(frozen=True)
class StartupInfo:
    """Values shown in the startup panel for an interactive run."""

    directory: Path
    provider: str
    model: str
    approval_mode: str
    skill_name: str | None = None


def startup_info_panel(startup_info: StartupInfo) -> str:
    """Render the fixed-width startup information panel."""
    inner_width = STARTUP_PANEL_WIDTH - 2
    title = " startup "
    top = f"╭─{title}{'─' * max(inner_width - len(title) - 1, 0)}╮"
    bottom = f"╰{'─' * inner_width}╯"
    lines = [
        ("Directory", str(startup_info.directory)),
        ("Provider", startup_info.provider),
        ("Model", startup_info.model),
        ("Approval mode", startup_info.approval_mode),
    ]
    if startup_info.skill_name is not None:
        lines.append(("Skill", startup_info.skill_name))
    lines.append(("Controls", STARTUP_CONTROLS))
    return "\n".join(
        [
            structural_text(top),
            *(_startup_info_line(label, value, inner_width) for label, value in lines),
            structural_text(bottom),
        ]
    )


def _startup_info_line(label: str, value: str, inner_width: int) -> str:
    label_text = f"{label}:"
    available = inner_width - 2 - 15
    value = truncate_middle(str(value), max(available, 1))
    content = f" {label_text:<14} {value}"
    return structural_bordered_line("│", f"{content:<{inner_width}}", "│")

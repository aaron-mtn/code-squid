"""Startup panel content for the Code Squid console scene."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil

from code_squid.console.ui.header_layout import (
    StartupSceneLayout,
    startup_scene_layout,
)


STARTUP_DIVIDER_CHARACTER = "─"
PANEL_TOP_LEFT = "╭"
PANEL_TOP_RIGHT = "╮"
PANEL_BOTTOM_LEFT = "╰"
PANEL_BOTTOM_RIGHT = "╯"
PANEL_HORIZONTAL = "─"
PANEL_VERTICAL = "│"
PANEL_LABEL_WIDTH = 10

FRIENDLY_APPROVAL_MODES = {
    "always": "strict",
    "guarded": "balanced",
    "never": "yolo",
}


@dataclass(frozen=True)
class StartupInfo:
    """Values shown in the startup panel for an interactive run."""

    directory: Path
    provider: str
    model: str
    approval_mode: str
    skill_name: str | None = None
    mod_name: str | None = None


def concise_workspace_name(directory: Path) -> str:
    """Return a compact workspace label while keeping roots meaningful."""
    if directory.name:
        return directory.name
    # Path.name is empty for filesystem roots. The anchor is concise and still
    # distinguishes a Windows drive root from a POSIX root.
    return directory.anchor or str(directory) or "."


def startup_panel_items(startup_info: StartupInfo) -> list[tuple[str, str]]:
    """Return the ordered state represented by the startup control panel."""
    items = [
        ("Provider", startup_info.provider),
        ("Model", startup_info.model),
        ("Safety", startup_info.approval_mode),
        ("Mod", startup_info.mod_name or "none"),
    ]
    # A directly selected Skill is distinct from a Mod and must remain visible.
    if startup_info.skill_name is not None and startup_info.mod_name is None:
        items.append(("Skill", startup_info.skill_name))
    items.append(("Workspace", concise_workspace_name(startup_info.directory)))
    return items


def startup_panel_lines(
    startup_info: StartupInfo,
    layout: StartupSceneLayout,
) -> list[str]:
    """Render panel-owned rows at exactly the layout's panel width."""
    width = layout.panel.width
    if width <= 0:
        return [""] * layout.panel.height
    if width == 1:
        return [PANEL_VERTICAL] * layout.panel.height

    inner_width = width - 2
    top = f"{PANEL_TOP_LEFT}{PANEL_HORIZONTAL * inner_width}{PANEL_TOP_RIGHT}"
    bottom = f"{PANEL_BOTTOM_LEFT}{PANEL_HORIZONTAL * inner_width}{PANEL_BOTTOM_RIGHT}"
    blank = f"{PANEL_VERTICAL}{' ' * inner_width}{PANEL_VERTICAL}"
    items = startup_panel_items(startup_info)
    # Keep labels on one shared axis even when one long value must be clipped.
    # The usual 40-column panel gets five cells of inset; narrow panels yield
    # that space to content while retaining a right-side safety cell.
    content_left = max(min(5, inner_width - 20), 0)
    content_width = max(inner_width - content_left - 1, 0)

    rows = [top, blank]
    for label, value in items:
        content = f"{label:<{PANEL_LABEL_WIDTH}}{value}"[:content_width]
        right_padding = inner_width - content_left - len(content)
        rows.append(
            f"{PANEL_VERTICAL}{' ' * content_left}{content}"
            f"{' ' * right_padding}{PANEL_VERTICAL}"
        )
        rows.append(blank)
    rows.append(bottom)
    assert len(rows) == layout.panel.height
    return rows


def startup_info_panel(
    startup_info: StartupInfo,
    *,
    terminal_columns: int | None = None,
) -> str:
    """Render the centered panel alone through the established test seam."""
    if terminal_columns is None:
        terminal_columns = shutil.get_terminal_size(fallback=(80, 24)).columns
    layout = startup_scene_layout(
        terminal_columns,
        show_skill=(
            startup_info.skill_name is not None and startup_info.mod_name is None
        ),
    )
    indent = " " * layout.panel.left
    return "\n".join(
        f"{indent}{line}" for line in startup_panel_lines(startup_info, layout)
    )

"""Application-owned state and actions for the keyboard startup menu."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import textwrap
from typing import Callable, Sequence

from code_squid.app_paths import code_squid_home
from code_squid.console.cli.runtime_commands import (
    SAFETY_MODES,
    apply_model,
    apply_provider,
    apply_safety,
)
from code_squid.console.cli.mod_commands import apply_mod_selection
from code_squid.console.ui.banner import (
    FRIENDLY_APPROVAL_MODES,
    PANEL_BOTTOM_LEFT,
    PANEL_BOTTOM_RIGHT,
    PANEL_HORIZONTAL,
    PANEL_LABEL_WIDTH,
    PANEL_TOP_LEFT,
    PANEL_TOP_RIGHT,
    PANEL_VERTICAL,
    StartupInfo,
    concise_workspace_name,
)
from code_squid.console.ui.header_layout import StartupSceneLayout
from code_squid.settings import Settings, VALID_PROVIDERS
from squid_core.mods import discover_mods
from squid_core.providers import build_provider


MAIN_ROWS = ("Provider", "Model", "Safety", "Mod", "Workspace")
MODEL_FALLBACK = ("No model list available", "Use /model <name>")


def discover_provider_models(settings: Settings) -> list[str] | None:
    """Use an adapter's optional model-list capability without a parallel registry."""
    provider = build_provider(settings.to_runtime_settings().provider)
    list_models = getattr(provider, "list_models", None)
    if list_models is None:
        return None
    models = list_models()
    return sorted({str(model) for model in models if str(model)})


@dataclass
class StartupMenu:
    """Hold the deliberately small focus, view, and selection state."""

    repo_root: Path
    settings: Settings
    mod_name: str | None = None
    skill_name: str | None = None
    mode: str = "main"
    selected_index: int = 0
    focused: bool = False
    model_discovery: Callable[[Settings], list[str] | None] = discover_provider_models

    def __post_init__(self) -> None:
        self.repo_root = self.repo_root.resolve()
        self._main_selected_index = self.selected_index
        self._options: tuple[str, ...] = ()
        self._model_message: tuple[str, ...] = ()

    @property
    def startup_info(self) -> StartupInfo:
        """Return current effective values for the next animated frame."""
        return StartupInfo(
            directory=self.repo_root,
            provider=self.settings.model.provider,
            model=self.settings.model.name,
            approval_mode=FRIENDLY_APPROVAL_MODES[
                self.settings.runtime.approval_mode
            ],
            skill_name=self.skill_name,
            mod_name=self.mod_name,
        )

    def sync(
        self,
        settings: Settings,
        *,
        mod_name: str | None,
        skill_name: str | None,
    ) -> None:
        """Accept changes made through the established slash-command surfaces."""
        self.settings = settings
        self.mod_name = mod_name
        self.skill_name = skill_name

    def focus_from_composer(self) -> None:
        """Focus the remembered main-menu row without submitting input."""
        self.focused = True
        self.mode = "main"
        self.selected_index = self._main_selected_index

    def return_to_composer(self) -> None:
        """Leave menu input focused while retaining the main row selection."""
        self.focused = False
        self.mode = "main"
        self.selected_index = self._main_selected_index

    def move(self, delta: int) -> None:
        """Move within the current view, leaving main-menu edges symmetrically."""
        options = self._current_options()
        if not options:
            return
        candidate = self.selected_index + delta
        if self.mode == "main" and not 0 <= candidate < len(options):
            self.return_to_composer()
            return
        self.selected_index = min(max(candidate, 0), len(options) - 1)
        if self.mode == "main":
            self._main_selected_index = self.selected_index

    def back(self) -> None:
        """Return from a submenu to main, or from main to the composer."""
        if self.mode == "main":
            self.return_to_composer()
            return
        self.mode = "main"
        self.selected_index = self._main_selected_index

    def activate(self) -> None:
        """Open the selected main row or apply one selected submenu option."""
        if self.mode == "main":
            self._open_main_row()
            return
        if self.mode == "workspace" or not self._options:
            return

        selected = self._options[self.selected_index]
        if self.mode == "provider":
            self.settings = apply_provider(self.repo_root, selected)
        elif self.mode == "model":
            self.settings = apply_model(self.repo_root, selected)
        elif self.mode == "safety":
            self.settings = apply_safety(self.repo_root, selected)
        elif self.mode == "mod":
            self.mod_name, self.skill_name = apply_mod_selection(
                selected,
                self.skill_name,
            )
        self.mode = "main"
        self.selected_index = self._main_selected_index

    def _open_main_row(self) -> None:
        self._main_selected_index = self.selected_index
        self.mode = MAIN_ROWS[self.selected_index].lower()
        self.selected_index = 0
        self._model_message = ()
        if self.mode == "provider":
            self._options = tuple(sorted(VALID_PROVIDERS))
            self._select_current(self.settings.model.provider)
        elif self.mode == "model":
            try:
                models = self.model_discovery(self.settings)
            except Exception:
                models = None
            self._options = tuple(sorted(models or ()))
            if self._options:
                self._select_current(self.settings.model.name)
            else:
                self._model_message = MODEL_FALLBACK
        elif self.mode == "safety":
            self._options = tuple(SAFETY_MODES)
            self._select_current(self.startup_info.approval_mode)
        elif self.mode == "mod":
            mods = discover_mods(code_squid_home())
            self._options = ("none",) + tuple(
                sorted(name for name, mod in mods.items() if mod.valid)
            )
            self._select_current(self.mod_name or "none")
        else:
            self._options = ()

    def _select_current(self, value: str) -> None:
        if value in self._options:
            self.selected_index = self._options.index(value)

    def _current_options(self) -> Sequence[str]:
        return MAIN_ROWS if self.mode == "main" else self._options

    def panel_lines(self, layout: StartupSceneLayout) -> list[str]:
        """Render the active view inside the unchanged startup panel rectangle."""
        if self.mode == "main":
            return self._main_panel_lines(layout)
        return self._submenu_panel_lines(layout)

    def _main_panel_lines(self, layout: StartupSceneLayout) -> list[str]:
        info = self.startup_info
        values = (
            info.provider,
            info.model,
            info.approval_mode,
            info.mod_name or "none",
            concise_workspace_name(info.directory),
        )
        width = layout.panel.width
        if width <= 1:
            return _framed_rows([], layout)
        inner_width = width - 2
        blank = f"{PANEL_VERTICAL}{' ' * inner_width}{PANEL_VERTICAL}"
        content_left = max(min(5, inner_width - 20), 0)
        content_width = max(inner_width - content_left - 1, 0)
        rows = [
            f"{PANEL_TOP_LEFT}{PANEL_HORIZONTAL * inner_width}{PANEL_TOP_RIGHT}",
            blank,
        ]
        for index, (label, value) in enumerate(zip(MAIN_ROWS, values)):
            marker = ">" if self.focused and index == self.selected_index else " "
            content = f"{label:<{PANEL_LABEL_WIDTH}}{value}"[:content_width]
            marker_column = max(content_left - 2, 0)
            prefix = f"{' ' * marker_column}{marker}"
            gap = " " * max(content_left - len(prefix), 0)
            right_padding = inner_width - len(prefix) - len(gap) - len(content)
            rows.append(
                f"{PANEL_VERTICAL}{prefix}{gap}{content}"
                f"{' ' * max(right_padding, 0)}{PANEL_VERTICAL}"
            )
            rows.append(blank)
        rows.append(
            f"{PANEL_BOTTOM_LEFT}{PANEL_HORIZONTAL * inner_width}{PANEL_BOTTOM_RIGHT}"
        )
        return rows

    def _submenu_panel_lines(self, layout: StartupSceneLayout) -> list[str]:
        if self.mode == "workspace":
            path_width = max(layout.panel.width - 6, 1)
            path_rows = textwrap.wrap(str(self.repo_root), width=path_width) or [
                str(self.repo_root)
            ]
            content = [
                "Workspace",
                "",
                concise_workspace_name(self.repo_root),
                "",
                *path_rows,
                "",
                "Esc  back",
            ]
            return _framed_rows(content, layout)

        title = self.mode.title()
        if self.mode == "model" and self._model_message:
            content = [title, "", *self._model_message, "", "Esc  back"]
            return _framed_rows(content, layout)

        # Keep the selected option visible if discovered Mods exceed panel space.
        visible_count = 5
        start = min(
            max(self.selected_index - visible_count // 2, 0),
            max(len(self._options) - visible_count, 0),
        )
        visible = self._options[start : start + visible_count]
        option_rows = [
            f"{'> ' if start + index == self.selected_index else '  '}{option}"
            for index, option in enumerate(visible)
        ]
        content = [title, "", *option_rows, "", "Esc  back"]
        return _framed_rows(content, layout)


def _framed_rows(content: Sequence[str], layout: StartupSceneLayout) -> list[str]:
    """Center content vertically and horizontally inside the fixed panel."""
    width = layout.panel.width
    if width <= 0:
        return [""] * layout.panel.height
    if width == 1:
        return [PANEL_VERTICAL] * layout.panel.height
    inner_width = width - 2
    inner_height = layout.panel.height - 2
    clipped = list(content[:inner_height])
    top_padding = max((inner_height - len(clipped)) // 2, 0)
    bottom_padding = inner_height - top_padding - len(clipped)

    def row(value: str) -> str:
        return f"{PANEL_VERTICAL}{value[:inner_width].center(inner_width)}{PANEL_VERTICAL}"

    return [
        f"{PANEL_TOP_LEFT}{PANEL_HORIZONTAL * inner_width}{PANEL_TOP_RIGHT}",
        *[row("") for _ in range(top_padding)],
        *[row(value) for value in clipped],
        *[row("") for _ in range(bottom_padding)],
        f"{PANEL_BOTTOM_LEFT}{PANEL_HORIZONTAL * inner_width}{PANEL_BOTTOM_RIGHT}",
    ]

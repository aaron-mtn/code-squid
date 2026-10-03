"""Application-owned state and actions for the keyboard startup menu."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import textwrap
from typing import Callable, Sequence

from code_squid.app_paths import code_squid_home, load_recent_workspaces
from code_squid.console.cli.runtime_commands import (
    SAFETY_MODES,
    apply_model,
    apply_safety,
)
from code_squid.provider_setup import (
    PROVIDER_PROFILES,
    discover_models,
    friendly_provider_name,
    provider_ready,
    select_provider,
    settings_for_provider,
)
from code_squid.console.cli.control_commands import (
    discover_recent_sessions,
    resolve_session_id,
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
from code_squid.settings import Settings
from squid_core.mods import discover_mods


MAIN_ROWS = ("Provider", "Model", "Safety", "Mod", "Session", "Workspace")
MODEL_FALLBACK = ("No model list available", "Use /model <name>")
SUBMENU_FOOTER = "↑↓   Enter select   Esc back"
SUBMENU_VISIBLE_LIMIT = 7

# Submenus share panel-relative geometry. Keeping these positions independent
# of content length prevents short option lists from pulling the whole view
# toward the panel's vertical center.
SUBMENU_HEADING_ROW = 1
SUBMENU_OPTION_START_ROW = 3
SUBMENU_OPTION_LEFT = 2
SUBMENU_FOOTER_BOTTOM_INSET = 1


def discover_provider_models(settings: Settings) -> list[str] | None:
    """Discover models through the shared application setup seam."""
    return discover_models(settings)


@dataclass
class StartupMenu:
    """Hold the deliberately small focus, view, and selection state."""

    repo_root: Path
    settings: Settings
    mod_name: str | None = None
    skill_name: str | None = None
    session_id: str | None = None
    session_title: str | None = None
    mode: str = "main"
    selected_index: int = 0
    focused: bool = False
    model_discovery: Callable[[Settings], list[str] | None] = discover_provider_models
    session_discovery: Callable[[Path], list[dict]] = discover_recent_sessions
    session_resolver: Callable[[Path, str], str | None] = resolve_session_id
    workspace_discovery: Callable[[Path], list[Path]] = load_recent_workspaces
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)

    def __post_init__(self) -> None:
        self.repo_root = self.repo_root.resolve()
        self._main_selected_index = self.selected_index
        self._options: tuple[str, ...] = ()
        self._model_message: tuple[str, ...] = ()
        self._session_metadata: tuple[dict, ...] = ()
        self._workspace_paths: tuple[Path, ...] = ()
        self._workspace_handoff: Path | None = None
        self._provider_statuses: dict[str, bool] = {}
        self._settings_error: str | None = None
        # Only an explicit saved-session choice arms the one-time CLI notice.
        # Initial ``--resume`` state and later follow-ups must remain silent.
        self._selected_session_notice: dict | None = None
        if self.session_id is not None and self.session_title is None:
            self.set_active_session(self.session_id)

    @property
    def startup_info(self) -> StartupInfo:
        """Return current effective values for the next animated frame."""
        return StartupInfo(
            directory=self.repo_root,
            provider=friendly_provider_name(self.settings.model.provider),
            model=self.settings.model.name,
            approval_mode=FRIENDLY_APPROVAL_MODES[
                self.settings.runtime.approval_mode
            ],
            skill_name=self.skill_name,
            mod_name=self.mod_name,
            session_title=self.session_title,
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

    def set_active_session(
        self,
        session_id: str | None,
        *,
        title: str | None = None,
    ) -> None:
        """Mirror CLI-owned active-session state for startup presentation."""
        self.session_id = session_id
        if session_id is None:
            self.session_title = None
            return
        if title is not None:
            self.session_title = title
            return
        metadata = next(
            (
                item
                for item in self.session_discovery(self.repo_root)
                if item.get("session_id") == session_id
            ),
            None,
        )
        self.session_title = (
            _session_title(metadata) if metadata is not None else "Saved session"
        )

    def take_selected_session_notice(
        self,
    ) -> tuple[str, str, int | None] | None:
        """Consume display data for one saved session selected in the picker."""
        metadata = self._selected_session_notice
        self._selected_session_notice = None
        if metadata is None:
            return None

        message_count = metadata.get("message_count")
        if (
            not isinstance(message_count, int)
            or isinstance(message_count, bool)
            or message_count < 0
        ):
            message_count = None
        return (
            _session_title(metadata),
            _session_age(metadata, self.now()),
            message_count,
        )

    def take_workspace_handoff(self) -> Path | None:
        """Consume the selected recent workspace path."""
        selected = self._workspace_handoff
        self._workspace_handoff = None
        return selected

    @property
    def workspace_handoff_pending(self) -> bool:
        """Return whether activation requested CLI workspace ownership."""
        return self._workspace_handoff is not None

    def focus_from_composer(self) -> None:
        """Focus the bottom main-menu row without submitting input."""
        self.focused = True
        self.mode = "main"
        # Composer entry is deliberately stable even when the prior menu visit
        # ended through the top edge or from a different remembered row.
        self.selected_index = len(MAIN_ROWS) - 1
        self._main_selected_index = self.selected_index

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

    def activate(self) -> bool:
        """Apply the selected option and report a saved-session activation."""
        if self.mode == "main":
            self._open_main_row()
            return False
        if self.mode == "workspace":
            # Recent paths are authoritative for this specialized submenu.
            # Shared option state can briefly belong to the preceding submenu.
            if not 0 <= self.selected_index < len(self._workspace_paths):
                return False
            self._workspace_handoff = self._workspace_paths[self.selected_index]
            # Workspace ownership moves to the CLI; this menu must not mutate
            # its root while other workspace-scoped objects still exist.
            self.focused = False
            self.mode = "main"
            self.selected_index = self._main_selected_index
            return False
        if not self._options:
            return False

        selected = self._options[self.selected_index]
        self._settings_error = None
        saved_session_activated = False
        try:
            if self.mode == "provider":
                self.settings, _ = select_provider(self.repo_root, selected)
                # The prompt-toolkit Application still owns stdout here.
                # Provider explanations are informational, so leave them to
                # the slash-command path instead of writing through the live
                # renderer.
            elif self.mode == "model":
                self.settings = apply_model(self.repo_root, selected)
            elif self.mode == "safety":
                self.settings = apply_safety(self.repo_root, selected)
        except (OSError, ValueError) as error:
            # Menu callbacks run inside prompt-toolkit's renderer thread. Keep
            # expected persistence failures on its existing panel surface;
            # other exception types must still escape as programming errors.
            self._settings_error = f"Settings change failed: {error}"
            return False

        if self.mode == "mod":
            # Clearing an active Mod clears its packaged Skill too. With no
            # active Mod, choosing none leaves a standalone Skill untouched.
            if selected != "none" or self.mod_name is not None:
                self.mod_name, self.skill_name = apply_mod_selection(
                    selected,
                    self.skill_name,
                )
        elif self.mode == "session":
            if self.selected_index == 0:
                self.session_id = None
                self.session_title = None
                self._selected_session_notice = None
            else:
                metadata = self._session_metadata[self.selected_index - 1]
                requested_id = str(metadata.get("session_id", ""))
                resolved_id = self.session_resolver(self.repo_root, requested_id)
                self.set_active_session(
                    resolved_id,
                    title=_session_title(metadata),
                )
                # Retain the already-read index record; the notice must not
                # open the transcript merely to enrich presentation.
                self._selected_session_notice = (
                    metadata if resolved_id is not None else None
                )
                saved_session_activated = resolved_id is not None
                if saved_session_activated:
                    # The startup renderer exits at this boundary; keep menu
                    # focus from leaking into a later fresh startup scene.
                    self.focused = False
        self.mode = "main"
        self.selected_index = self._main_selected_index
        return saved_session_activated

    def _open_main_row(self) -> None:
        self._main_selected_index = self.selected_index
        next_mode = MAIN_ROWS[self.selected_index].lower()
        self.selected_index = 0
        self._model_message = ()
        self._settings_error = None
        # Prepare the selected submenu before publishing its mode. Rendering can
        # occur from discovery callbacks and must not pair a new mode with the
        # preceding submenu's shared state.
        self._options = ()
        if next_mode == "provider":
            self._options = tuple(profile.provider_id for profile in PROVIDER_PROFILES)
            self._provider_statuses = {}
            for provider_id in self._options:
                candidate = settings_for_provider(self.settings, provider_id)
                self._provider_statuses[provider_id] = provider_ready(candidate)
            self._select_current(self.settings.model.provider)
        elif next_mode == "model":
            try:
                models = self.model_discovery(self.settings)
            except Exception:
                models = None
            self._options = tuple(sorted(models or ()))
            if self._options:
                self._select_current(self.settings.model.name)
            else:
                self._model_message = MODEL_FALLBACK
        elif next_mode == "safety":
            self._options = tuple(SAFETY_MODES)
            self._select_current(self.startup_info.approval_mode)
        elif next_mode == "mod":
            mods = discover_mods(code_squid_home())
            self._options = ("none",) + tuple(
                sorted(name for name, mod in mods.items() if mod.valid)
            )
            self._select_current(self.mod_name or "none")
        elif next_mode == "session":
            self._session_metadata = tuple(self.session_discovery(self.repo_root))
            self._options = ("",) + tuple(
                str(metadata.get("session_id", ""))
                for metadata in self._session_metadata
            )
            if self.session_id in self._options:
                self.selected_index = self._options.index(self.session_id)
        elif next_mode == "workspace":
            self._workspace_paths = ()
            self._workspace_paths = tuple(self.workspace_discovery(self.repo_root))
            self._options = tuple(str(path) for path in self._workspace_paths)
            if self.repo_root in self._workspace_paths:
                self.selected_index = self._workspace_paths.index(self.repo_root)
        self.mode = next_mode

    def _select_current(self, value: str) -> None:
        if value in self._options:
            self.selected_index = self._options.index(value)

    def _current_options(self) -> Sequence[object]:
        if self.mode == "workspace":
            return self._workspace_paths
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
            info.session_title or "New",
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
            if index < len(MAIN_ROWS) - 1:
                rows.append(blank)
        rows.append(
            f"{PANEL_BOTTOM_LEFT}{PANEL_HORIZONTAL * inner_width}{PANEL_BOTTOM_RIGHT}"
        )
        return rows

    def _submenu_panel_lines(self, layout: StartupSceneLayout) -> list[str]:
        if self.mode == "workspace":
            return self._workspace_panel_lines(layout)

        title = self.mode.title()
        if self._settings_error is not None:
            # Error feedback takes over the compact panel so even the minimum
            # layout can show both its context and the underlying OS message.
            width = max(layout.panel.width - 4, 1)
            return _framed_rows(
                [
                    f"{title} error",
                    *textwrap.wrap(self._settings_error, width=width),
                ],
                layout,
            )
        if self.mode == "model" and self._model_message:
            return _submenu_rows(title, self._model_message, layout)

        if self.mode == "session":
            return self._session_panel_lines(layout)

        # Keep the selected option visible if discovered Mods exceed panel space.
        visible_count = SUBMENU_VISIBLE_LIMIT
        start = min(
            max(self.selected_index - visible_count // 2, 0),
            max(len(self._options) - visible_count, 0),
        )
        visible = self._options[start : start + visible_count]
        option_width = _submenu_option_width(layout)
        option_rows = []
        for index, option in enumerate(visible):
            marker = "> " if start + index == self.selected_index else "  "
            label = option
            if self.mode == "provider":
                status = (
                    "ready"
                    if self._provider_statuses.get(option)
                    else "not connected"
                )
                label = f"{friendly_provider_name(option):<18}{status}"
            option_text = f"{marker}{label}"[:option_width].ljust(option_width)
            option_rows.append(option_text)
        return _submenu_rows(title, option_rows, layout)

    def _workspace_panel_lines(self, layout: StartupSceneLayout) -> list[str]:
        """Render a bounded recent-workspace viewport with concise labels."""
        labels = _workspace_labels(self._workspace_paths)
        start = min(
            max(self.selected_index - SUBMENU_VISIBLE_LIMIT + 1, 0),
            max(len(labels) - SUBMENU_VISIBLE_LIMIT, 0),
        )
        visible_indexes = range(
            start,
            min(start + SUBMENU_VISIBLE_LIMIT, len(labels)),
        )
        option_width = _submenu_option_width(layout)
        rows = [
            _workspace_option_row(
                labels[index],
                selected=index == self.selected_index,
                width=option_width,
            )
            for index in visible_indexes
        ]
        return _submenu_rows("Workspace", rows, layout)

    def _session_panel_lines(self, layout: StartupSceneLayout) -> list[str]:
        """Render a bounded session viewport while keeping selection visible."""
        visible_saved_limit = SUBMENU_VISIBLE_LIMIT - 1
        saved_selected_index = max(self.selected_index - 1, 0)
        saved_start = min(
            max(saved_selected_index - visible_saved_limit + 1, 0),
            max(len(self._session_metadata) - visible_saved_limit, 0),
        )
        visible = self._session_metadata[
            saved_start : saved_start + visible_saved_limit
        ]
        rows: list[tuple[str, str, int]] = [
            ("New session", "now", 0),
        ]
        rows.extend(
            (
                _session_title(metadata),
                _session_age(metadata, self.now()),
                saved_start + index + 1,
            )
            for index, metadata in enumerate(visible)
        )

        option_width = _submenu_option_width(layout)
        option_rows = [
            _session_option_row(
                title,
                age,
                selected=option_index == self.selected_index,
                width=option_width,
            )
            for title, age, option_index in rows
        ]
        return _submenu_rows("Sessions for this workspace", option_rows, layout)


def _session_title(metadata: dict) -> str:
    """Return the human-facing task title without falling back to the ID."""
    task = metadata.get("task")
    if task is not None:
        title = " ".join(str(task).split())
        if title:
            return title
    return "Untitled session"


def _workspace_labels(paths: Sequence[Path]) -> tuple[str, ...]:
    """Use basenames, adding one compact parent hint only for collisions."""
    basenames = [concise_workspace_name(path) for path in paths]
    return tuple(
        (
            f"{name}  ({path.parent.name or path.parent})"
            if basenames.count(name) > 1
            else name
        )
        for name, path in zip(basenames, paths)
    )


def _workspace_option_row(label: str, *, selected: bool, width: int) -> str:
    """Fit one recent workspace into the submenu's shared option column."""
    marker = "> " if selected else "  "
    label_width = max(width - len(marker), 0)
    if len(label) > label_width:
        label = (label[: max(label_width - 3, 0)] + "...")[:label_width]
    return f"{marker}{label:<{label_width}}"[:width]


def _session_age(metadata: dict, now: datetime) -> str:
    """Format one compact age from the session index timestamp."""
    value = metadata.get("updated_at")
    if not isinstance(value, str):
        return ""
    try:
        updated = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    seconds = max(int((now - updated).total_seconds()), 0)
    if seconds < 60:
        return "now"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h"
    return f"{seconds // 86400}d"


def _session_option_row(
    title: str,
    age: str,
    *,
    selected: bool,
    width: int,
) -> str:
    """Fit a title and stable right-aligned age into one panel row."""
    marker = "> " if selected else "  "
    label_width = max(width - len(marker) - len(age) - 1, 0)
    if len(title) > label_width:
        title = (title[: max(label_width - 3, 0)] + "...")[:label_width]
    return f"{marker}{title:<{label_width}} {age}"[:width].ljust(width)


def _submenu_option_width(layout: StartupSceneLayout) -> int:
    """Return the common option width after the fixed left/right inset."""
    inner_width = max(layout.panel.width - 2, 0)
    return max(inner_width - (SUBMENU_OPTION_LEFT * 2), 0)


def _submenu_rows(
    heading: str,
    option_rows: Sequence[str],
    layout: StartupSceneLayout,
) -> list[str]:
    """Place one selectable submenu into the shared fixed panel geometry."""
    width = layout.panel.width
    if width <= 0:
        return [""] * layout.panel.height
    if width == 1:
        return [PANEL_VERTICAL] * layout.panel.height

    inner_width = width - 2
    rows = [" " * inner_width for _ in range(max(layout.panel.height - 2, 0))]
    footer_row = layout.panel.height - 1 - SUBMENU_FOOTER_BOTTOM_INSET
    # Reserve one blank row between the bounded viewport and fixed footer.
    option_capacity = max(footer_row - SUBMENU_OPTION_START_ROW - 1, 0)

    def set_centered(panel_row: int, value: str) -> None:
        if 1 <= panel_row < layout.panel.height - 1:
            rows[panel_row - 1] = value[:inner_width].center(inner_width)

    set_centered(SUBMENU_HEADING_ROW, heading)
    for offset, value in enumerate(option_rows[:option_capacity]):
        panel_row = SUBMENU_OPTION_START_ROW + offset
        option_width = _submenu_option_width(layout)
        anchored = f"{' ' * SUBMENU_OPTION_LEFT}{value[:option_width].ljust(option_width)}"
        rows[panel_row - 1] = anchored.ljust(inner_width)[:inner_width]
    set_centered(footer_row, SUBMENU_FOOTER)

    return [
        f"{PANEL_TOP_LEFT}{PANEL_HORIZONTAL * inner_width}{PANEL_TOP_RIGHT}",
        *[f"{PANEL_VERTICAL}{row}{PANEL_VERTICAL}" for row in rows],
        f"{PANEL_BOTTOM_LEFT}{PANEL_HORIZONTAL * inner_width}{PANEL_BOTTOM_RIGHT}",
    ]


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

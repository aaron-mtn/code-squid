"""Focused deterministic coverage for the keyboard startup menu."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import threading
from types import SimpleNamespace

from prompt_toolkit.input.defaults import create_pipe_input
from prompt_toolkit.output import DummyOutput

from code_squid.console.startup_menu import (
    MAIN_ROWS,
    MODEL_FALLBACK,
    SESSION_VISIBLE_SAVED_LIMIT,
    StartupMenu,
    _session_title,
    discover_provider_models,
)
from code_squid.console.ui.banner import startup_panel_lines
from code_squid.console.ui.binary_header import BinaryRainHeader
from code_squid.console.ui.header_layout import startup_scene_layout
from code_squid.console.ui.prompt_input import (
    multiline_key_bindings,
    prompt_multiline_input,
)
from code_squid.console.ui.startup_application import (
    STARTUP_SESSION_SELECTED,
    StartupApplication,
)
from code_squid.settings import VALID_PROVIDERS, load_settings


class MenuAnimator(BinaryRainHeader):
    """Rain model connected to the real startup menu state seam."""

    def __init__(self, menu: StartupMenu) -> None:
        super().__init__(startup_info=menu.startup_info)
        self.startup_menu = menu


def _run_prompt(monkeypatch, menu: StartupMenu, terminal_input: str) -> str:
    result: list[str] = []
    errors: list[BaseException] = []
    startups: list[StartupApplication] = []
    with create_pipe_input() as pipe_input:
        animator = MenuAnimator(menu)

        def build_startup(prompt, rain, bindings):
            startup = StartupApplication(
                prompt,
                rain,
                bindings,
                input=pipe_input,
                output=DummyOutput(),
            )
            startups.append(startup)
            return startup

        monkeypatch.setattr(
            "code_squid.console.ui.prompt_input.StartupApplication",
            build_startup,
        )

        def prompt() -> None:
            try:
                result.append(prompt_multiline_input("> ", animator=animator))
            except BaseException as error:
                errors.append(error)

        thread = threading.Thread(target=prompt)
        thread.start()
        pipe_input.send_text(terminal_input)
        thread.join(timeout=5)
        assert not thread.is_alive()
        assert len(startups) == 1
        startups[0].finish_fade()
    assert not errors
    return result[0]


def test_empty_composer_up_enters_menu_and_boundary_returns(monkeypatch, tmp_path) -> None:
    menu = StartupMenu(tmp_path, load_settings(tmp_path))

    result = _run_prompt(monkeypatch, menu, ("\x1b[A" * 7) + "text\r")

    assert result == "text"
    assert menu.focused is False


def test_menu_keys_update_visible_panel_state(monkeypatch, tmp_path) -> None:
    menu = StartupMenu(tmp_path, load_settings(tmp_path))
    animator = MenuAnimator(menu)
    result: list[str] = []

    with create_pipe_input() as pipe_input:
        startups: list[StartupApplication] = []

        def build_startup(prompt, rain, bindings):
            startup = StartupApplication(
                prompt,
                rain,
                bindings,
                input=pipe_input,
                output=DummyOutput(),
            )
            startups.append(startup)
            return startup

        monkeypatch.setattr(
            "code_squid.console.ui.prompt_input.StartupApplication",
            build_startup,
        )

        thread = threading.Thread(
            target=lambda: result.append(prompt_multiline_input("> ", animator=animator))
        )
        thread.start()
        # Enter menu focus, move twice, return to the composer, then submit.
        pipe_input.send_text("\x1b[A\x1b[A\x1b[B\x1btext\r")
        thread.join(timeout=5)
        assert not thread.is_alive()
        startups[0].finish_fade()

    assert result == ["text"]
    assert menu.focused is False


def test_composer_text_keeps_normal_up_behavior(monkeypatch, tmp_path) -> None:
    menu = StartupMenu(tmp_path, load_settings(tmp_path))

    result = _run_prompt(monkeypatch, menu, "text\x1b[A\r")

    assert result == "text"
    assert menu.focused is False


def test_composer_entry_always_selects_bottom_row_after_either_boundary(tmp_path) -> None:
    menu = StartupMenu(tmp_path, load_settings(tmp_path))
    menu.focus_from_composer()
    assert menu.selected_index == len(MAIN_ROWS) - 1

    menu.selected_index = 0
    menu.move(-1)
    assert menu.focused is False
    menu.focus_from_composer()
    assert menu.selected_index == len(MAIN_ROWS) - 1

    menu.move(1)
    assert menu.focused is False
    menu.focus_from_composer()
    assert menu.selected_index == len(MAIN_ROWS) - 1


def test_each_main_row_replaces_panel_and_escape_restores_main(tmp_path) -> None:
    menu = StartupMenu(tmp_path, load_settings(tmp_path), model_discovery=lambda _: None)
    layout = startup_scene_layout(80)

    for index, title in enumerate(MAIN_ROWS):
        menu.focus_from_composer()
        menu.selected_index = index
        menu.activate()
        rendered = "\n".join(menu.panel_lines(layout))
        assert title in rendered
        if title == "Model":
            assert all(message in rendered for message in MODEL_FALLBACK)
        if title == "Workspace":
            compact = "".join(line[1:-1].strip() for line in menu.panel_lines(layout))
            assert str(tmp_path.resolve()) in compact
        menu.back()
        assert menu.mode == "main"
        restored = "\n".join(menu.panel_lines(layout))
        assert all(row in restored for row in MAIN_ROWS)


def test_back_returns_submenu_to_main_and_main_to_composer(tmp_path) -> None:
    menu = StartupMenu(tmp_path, load_settings(tmp_path))
    menu.focus_from_composer()
    menu.selected_index = 0
    menu.activate()

    menu.back()
    assert menu.mode == "main"
    assert menu.focused is True

    menu.back()
    assert menu.mode == "main"
    assert menu.focused is False


def test_unfocused_main_panel_preserves_existing_composition(tmp_path) -> None:
    menu = StartupMenu(tmp_path, load_settings(tmp_path))
    layout = startup_scene_layout(80)

    assert menu.panel_lines(layout) == startup_panel_lines(menu.startup_info, layout)


def test_provider_options_are_canonical_and_selection_updates_persisted_panel(
    tmp_path,
) -> None:
    menu = StartupMenu(tmp_path, load_settings(tmp_path))
    menu.focus_from_composer()
    menu.selected_index = 0
    menu.activate()
    assert set(menu._options) == VALID_PROVIDERS

    menu.selected_index = menu._options.index("ollama")
    menu.activate()

    persisted = json.loads((tmp_path / ".code-squid" / "settings.json").read_text())
    assert persisted["model"]["provider"] == "ollama"
    assert menu.settings.model.provider == "ollama"
    assert "ollama" in "\n".join(menu.panel_lines(startup_scene_layout(80)))


def test_model_discovery_uses_effective_provider_and_is_not_used_by_render(tmp_path) -> None:
    seen = []

    def discover(settings):
        seen.append(settings.model.provider)
        return ["model-b", "model-a"]

    menu = StartupMenu(tmp_path, load_settings(tmp_path), model_discovery=discover)
    layout = startup_scene_layout(80)
    menu.panel_lines(layout)
    assert seen == []

    menu.focus_from_composer()
    menu.selected_index = 1
    menu.activate()
    assert seen == ["openai_compatible"]
    assert "model-a" in "\n".join(menu.panel_lines(layout))

    menu.selected_index = 0
    menu.activate()
    assert menu.settings.model.name == "model-a"
    assert seen == ["openai_compatible"]


def test_provider_model_discovery_uses_optional_adapter_capability(
    monkeypatch,
    tmp_path,
) -> None:
    settings = load_settings(tmp_path)
    providers = []

    def build(provider_settings):
        providers.append(provider_settings.provider)
        return SimpleNamespace(list_models=lambda: ["z", "a", "a"])

    monkeypatch.setattr("code_squid.console.startup_menu.build_provider", build)
    assert discover_provider_models(settings) == ["a", "z"]
    assert providers == ["openai_compatible"]


def test_safety_selection_uses_mapping_and_updates_panel(tmp_path) -> None:
    menu = StartupMenu(tmp_path, load_settings(tmp_path))
    menu.focus_from_composer()
    menu.selected_index = 2
    menu.activate()
    menu.selected_index = menu._options.index("strict")
    menu.activate()

    assert menu.settings.runtime.approval_mode == "always"
    assert "strict" in "\n".join(menu.panel_lines(startup_scene_layout(80)))


def test_mod_selection_and_none_preserve_specialization_rules(monkeypatch, tmp_path) -> None:
    valid = SimpleNamespace(valid=True, name="review")
    discovery = lambda *_args, **_kwargs: {"review": valid}
    monkeypatch.setattr("code_squid.console.startup_menu.discover_mods", discovery)
    monkeypatch.setattr("code_squid.console.cli.mod_commands.discover_mods", discovery)

    menu = StartupMenu(tmp_path, load_settings(tmp_path), skill_name="direct")
    menu.focus_from_composer()
    menu.selected_index = 3
    menu.activate()
    menu.selected_index = menu._options.index("review")
    menu.activate()
    assert (menu.mod_name, menu.skill_name) == ("review", None)

    menu.selected_index = 3
    menu.activate()
    menu.selected_index = 0
    menu.activate()
    assert (menu.mod_name, menu.skill_name) == (None, None)


def test_workspace_view_is_read_only_and_shows_full_path(tmp_path) -> None:
    menu = StartupMenu(tmp_path, load_settings(tmp_path))
    original_root = menu.repo_root
    menu.focus_from_composer()
    menu.selected_index = MAIN_ROWS.index("Workspace")
    menu.activate()

    lines = menu.panel_lines(startup_scene_layout(80))
    visible_content = "".join(line[1:-1].strip() for line in lines)
    assert str(original_root) in visible_content
    menu.activate()
    assert menu.repo_root == original_root


def test_workspace_view_keeps_centered_footer_for_long_paths(tmp_path) -> None:
    long_root = tmp_path.joinpath(*(["nested-workspace-segment"] * 12))
    menu = StartupMenu(long_root, load_settings(tmp_path))
    menu.focus_from_composer()
    menu.selected_index = MAIN_ROWS.index("Workspace")
    menu.activate()

    inner = [line[1:-1] for line in menu.panel_lines(startup_scene_layout(80))]
    footer = next(line for line in inner if line.strip() == "Esc  back")

    assert footer == "Esc  back".center(len(footer))


def test_submenu_centers_title_options_as_one_column_and_footer(tmp_path) -> None:
    menu = StartupMenu(tmp_path, load_settings(tmp_path))
    menu.focus_from_composer()
    menu.selected_index = 0
    menu.activate()
    menu._options = ("a", "long-option")
    menu.selected_index = 0

    lines = menu.panel_lines(startup_scene_layout(80))
    inner = [line[1:-1] for line in lines]
    title = next(line for line in inner if line.strip() == "Provider")
    selected = next(line for line in inner if "> a" in line)
    unselected = next(line for line in inner if "long-option" in line)
    footer = next(line for line in inner if line.strip() == "Esc  back")

    assert title == "Provider".center(len(title))
    assert footer == "Esc  back".center(len(footer))
    assert selected.index("a") == unselected.index("long-option")
    assert selected.index(">") == unselected.index("long-option") - 2


def _recent_sessions(count: int, now: datetime) -> list[dict]:
    return [
        {
            "session_id": f"session-{index}",
            "task": f"Task {index}",
            "updated_at": (now - timedelta(minutes=index + 1)).isoformat(),
        }
        for index in range(count)
    ]


def test_session_title_collapses_multiline_and_repeated_whitespace() -> None:
    assert _session_title({"task": "Fix the first line\nthen the second"}) == (
        "Fix the first line then the second"
    )
    assert _session_title({"task": "  tabs\tand   spaces  "}) == "tabs and spaces"
    assert _session_title({"task": "Already one line"}) == "Already one line"


def test_session_row_opens_with_new_first_and_recent_sessions_newest_first(
    tmp_path,
) -> None:
    now = datetime(2026, 9, 7, 12, tzinfo=timezone.utc)
    recent = _recent_sessions(3, now)
    menu = StartupMenu(
        tmp_path,
        load_settings(tmp_path),
        session_discovery=lambda _: recent,
        now=lambda: now,
    )
    layout = startup_scene_layout(80)

    assert "Session   New" in "\n".join(menu.panel_lines(layout))
    menu.focus_from_composer()
    menu.selected_index = MAIN_ROWS.index("Session")
    menu.activate()

    rendered = "\n".join(menu.panel_lines(layout))
    assert menu.mode == "session"
    assert menu._options == ("", "session-0", "session-1", "session-2")
    assert rendered.index("New session") < rendered.index("Task 0")
    assert rendered.index("Task 0") < rendered.index("Task 1")


def test_session_viewport_scrolls_after_five_saved_sessions(tmp_path) -> None:
    now = datetime(2026, 9, 7, 12, tzinfo=timezone.utc)
    recent = _recent_sessions(9, now)
    menu = StartupMenu(
        tmp_path,
        load_settings(tmp_path),
        session_discovery=lambda _: recent,
        now=lambda: now,
    )
    layout = startup_scene_layout(80)
    menu.focus_from_composer()
    menu.selected_index = MAIN_ROWS.index("Session")
    menu.activate()

    initial = "\n".join(menu.panel_lines(layout))
    assert initial.count("Task ") == SESSION_VISIBLE_SAVED_LIMIT
    assert "New session" in initial
    assert "Task 5" not in initial

    for _ in range(SESSION_VISIBLE_SAVED_LIMIT + 1):
        menu.move(1)
    scrolled = "\n".join(menu.panel_lines(layout))
    assert menu.selected_index == SESSION_VISIBLE_SAVED_LIMIT + 1
    assert "New session" in scrolled
    assert "Task 0" not in scrolled
    assert "Task 5" in scrolled


def test_session_escape_does_not_change_selection_and_enter_uses_resume_seam(
    tmp_path,
) -> None:
    now = datetime(2026, 9, 7, 12, tzinfo=timezone.utc)
    recent = _recent_sessions(2, now)
    resolved: list[str] = []

    def resolve(_repo_root, session_id):
        resolved.append(session_id)
        return session_id

    menu = StartupMenu(
        tmp_path,
        load_settings(tmp_path),
        session_discovery=lambda _: recent,
        session_resolver=resolve,
        now=lambda: now,
    )
    menu.focus_from_composer()
    menu.selected_index = MAIN_ROWS.index("Session")
    menu.activate()
    menu.selected_index = 1
    menu.back()
    assert menu.session_id is None

    menu.activate()
    menu.selected_index = 2
    menu.activate()
    assert menu.session_id == "session-1"
    assert menu.session_title == "Task 1"
    assert resolved == ["session-1"]

    menu.activate()
    menu.selected_index = 0
    menu.activate()
    assert menu.session_id is None
    assert menu.session_title is None


def test_saved_session_selection_exposes_one_normalized_notice_from_index(
    tmp_path,
) -> None:
    now = datetime(2026, 9, 7, 12, tzinfo=timezone.utc)
    recent = [
        {
            "session_id": "saved-session",
            "task": "Fix Skate Wizard startup crash\n  without replaying it",
            "updated_at": (now - timedelta(hours=2)).isoformat(),
            "message_count": 17,
        }
    ]
    menu = StartupMenu(
        tmp_path,
        load_settings(tmp_path),
        session_discovery=lambda _: recent,
        session_resolver=lambda _root, session_id: session_id,
        now=lambda: now,
    )
    menu.focus_from_composer()
    menu.selected_index = MAIN_ROWS.index("Session")
    menu.activate()
    menu.selected_index = 1
    menu.activate()

    assert menu.take_selected_session_notice() == (
        "Fix Skate Wizard startup crash without replaying it",
        "2h",
        17,
    )
    assert menu.take_selected_session_notice() is None


def test_saved_session_activation_releases_startup_before_task_submission(
    monkeypatch,
    tmp_path,
) -> None:
    recent = [{"session_id": "saved-session", "task": "Saved task"}]
    menu = StartupMenu(
        tmp_path,
        load_settings(tmp_path),
        session_discovery=lambda _: recent,
        session_resolver=lambda _root, session_id: session_id,
    )
    menu.focus_from_composer()
    menu.selected_index = MAIN_ROWS.index("Session")
    assert menu.activate() is False

    result = _run_prompt(
        monkeypatch,
        menu,
        "\x1b[B\r",
    )

    assert result is STARTUP_SESSION_SELECTED
    assert menu.session_id == "saved-session"
    assert menu.focused is False
    assert menu.take_selected_session_notice() is not None


def test_new_session_clears_notice_and_missing_index_count_stays_omitted(
    tmp_path,
) -> None:
    now = datetime(2026, 9, 7, 12, tzinfo=timezone.utc)
    recent = [
        {
            "session_id": "saved-session",
            "task": "Saved task",
            "updated_at": (now - timedelta(minutes=12)).isoformat(),
        }
    ]
    menu = StartupMenu(
        tmp_path,
        load_settings(tmp_path),
        session_discovery=lambda _: recent,
        session_resolver=lambda _root, session_id: session_id,
        now=lambda: now,
    )
    menu.focus_from_composer()
    menu.selected_index = MAIN_ROWS.index("Session")
    menu.activate()
    menu.selected_index = 1
    menu.activate()
    assert menu.take_selected_session_notice() == ("Saved task", "12m", None)

    menu.activate()
    menu.selected_index = 1
    menu.activate()
    menu.activate()
    menu.selected_index = 0
    menu.activate()

    assert menu.session_id is None
    assert menu.take_selected_session_notice() is None


def test_long_session_titles_truncate_and_keep_aligned_timestamps(tmp_path) -> None:
    now = datetime(2026, 9, 7, 12, tzinfo=timezone.utc)
    recent = [
        {
            "session_id": "long-session",
            "task": (
                "A very long session title\n"
                "that cannot possibly fit\tinside the fixed panel"
            ),
            "updated_at": (now - timedelta(hours=3)).isoformat(),
        },
        {
            "session_id": "short-session",
            "task": "Short",
            "updated_at": (now - timedelta(days=1)).isoformat(),
        },
    ]
    menu = StartupMenu(
        tmp_path,
        load_settings(tmp_path),
        session_discovery=lambda _: recent,
        now=lambda: now,
    )
    menu.focus_from_composer()
    menu.selected_index = MAIN_ROWS.index("Session")
    menu.activate()
    inner = [line[1:-1] for line in menu.panel_lines(startup_scene_layout(80))]
    long_row = next(line for line in inner if "..." in line)
    short_row = next(line for line in inner if "Short" in line)

    assert long_row.rstrip().endswith("3h")
    assert short_row.rstrip().endswith("1d")
    assert long_row.rindex("3h") == short_row.rindex("1d")


def test_session_panel_stays_fixed_height_with_multiline_metadata(tmp_path) -> None:
    now = datetime(2026, 9, 7, 12, tzinfo=timezone.utc)
    recent = [
        {
            "session_id": "multiline-session",
            "task": "First line\nSecond line\twith details",
            "updated_at": (now - timedelta(minutes=4)).isoformat(),
        }
    ]
    menu = StartupMenu(
        tmp_path,
        load_settings(tmp_path),
        session_discovery=lambda _: recent,
        session_resolver=lambda _root, session_id: session_id,
        now=lambda: now,
    )
    layout = startup_scene_layout(80)
    menu.focus_from_composer()
    menu.selected_index = MAIN_ROWS.index("Session")
    menu.activate()

    lines = menu.panel_lines(layout)
    rendered = "\n".join(lines)

    assert len(lines) == layout.panel.height
    assert all("\n" not in line and "\t" not in line for line in lines)
    session_rows = [line for line in lines if "First line Second line" in line]
    assert len(session_rows) == 1

    menu.selected_index = 1
    menu.activate()
    assert menu.session_title == "First line Second line with details"
    assert "Session" in rendered
    assert "First line Second line" in "\n".join(menu.panel_lines(layout))

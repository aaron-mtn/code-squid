"""Focused deterministic coverage for the keyboard startup menu."""

from __future__ import annotations

import json
from pathlib import Path
import threading
from types import SimpleNamespace

from prompt_toolkit import PromptSession
from prompt_toolkit.input.defaults import create_pipe_input
from prompt_toolkit.output import DummyOutput

from code_squid.console.startup_menu import (
    MAIN_ROWS,
    MODEL_FALLBACK,
    StartupMenu,
    discover_provider_models,
)
from code_squid.console.ui.banner import startup_panel_lines
from code_squid.console.ui.header_layout import startup_scene_layout
from code_squid.console.ui.prompt_input import prompt_multiline_input
from code_squid.settings import VALID_PROVIDERS, load_settings


class MenuAnimator:
    """Non-animated header stub exposing the menu seam used by prompt input."""

    has_animator = False

    def __init__(self, menu: StartupMenu) -> None:
        self.startup_menu = menu
        self.pause_calls = 0

    def pause(self) -> None:
        self.pause_calls += 1


def _run_prompt(monkeypatch, menu: StartupMenu, terminal_input: str) -> str:
    result: list[str] = []
    errors: list[BaseException] = []
    with create_pipe_input() as pipe_input:
        monkeypatch.setattr(
            "code_squid.console.ui.prompt_input.PromptSession",
            lambda: PromptSession(input=pipe_input, output=DummyOutput()),
        )

        def prompt() -> None:
            try:
                result.append(prompt_multiline_input("> ", animator=MenuAnimator(menu)))
            except BaseException as error:
                errors.append(error)

        thread = threading.Thread(target=prompt)
        thread.start()
        pipe_input.send_text(terminal_input)
        thread.join(timeout=5)
        assert not thread.is_alive()
    assert not errors
    return result[0]


def test_empty_composer_up_enters_menu_and_boundary_returns(monkeypatch, tmp_path) -> None:
    menu = StartupMenu(tmp_path, load_settings(tmp_path))

    result = _run_prompt(monkeypatch, menu, ("\x1b[A" * 6) + "text\r")

    assert result == "text"
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
    menu.selected_index = 4
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
    menu.selected_index = 4
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

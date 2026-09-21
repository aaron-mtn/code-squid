"""Focused deterministic coverage for the keyboard startup menu."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest
from prompt_toolkit.input.defaults import create_pipe_input
from prompt_toolkit.output import DummyOutput

from code_squid.app_paths import settings_path
from code_squid.console.startup_menu import (
    MAIN_ROWS,
    MODEL_FALLBACK,
    SUBMENU_VISIBLE_LIMIT,
    StartupMenu,
    _session_title,
    discover_provider_models,
)
from code_squid.console.ui.banner import PANEL_LABEL_WIDTH, startup_panel_lines
from code_squid.console.ui.binary_header import BinaryRainHeader
from code_squid.console.ui.header_layout import startup_scene_layout
from code_squid.console.ui.prompt_input import (
    multiline_key_bindings,
    prompt_multiline_input,
)
from code_squid.console.ui.startup_application import (
    STARTUP_SESSION_SELECTED,
    STARTUP_WORKSPACE_SELECTED,
    StartupApplication,
)
from code_squid.settings import VALID_PROVIDERS, load_settings


class JsonResponse:
    """Small urllib response used by startup discovery regression tests."""

    def __init__(self, payload: object) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


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
        lines = menu.panel_lines(layout)
        rendered = "\n".join(lines)
        displayed_text = [line[1:-1].strip() for line in lines]
        expected_title = (
            "Sessions for this workspace" if title == "Session" else title
        )
        assert expected_title in displayed_text
        assert displayed_text.count("↑↓   Enter select   Esc back") == 1
        if title == "Model":
            assert all(message in rendered for message in MODEL_FALLBACK)
        if title == "Workspace":
            assert tmp_path.name in rendered
            assert "Choose folder..." not in rendered
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
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(
        "code_squid.console.startup_menu.provider_ready",
        lambda _settings: True,
    )
    monkeypatch.setattr(
        "code_squid.provider_setup.build_provider",
        lambda _settings: SimpleNamespace(
            is_ready=lambda: True,
            list_models=lambda: ["qwen3.5-9b"],
        ),
    )
    menu = StartupMenu(tmp_path, load_settings(tmp_path))
    menu.focus_from_composer()
    menu.selected_index = 0
    menu.activate()
    assert set(menu._options) == VALID_PROVIDERS

    menu.selected_index = menu._options.index("ollama")
    menu.activate()

    persisted = json.loads(settings_path().read_text())
    assert persisted["model"]["provider"] == "ollama"
    assert menu.settings.model.provider == "ollama"
    assert "Ollama" in "\n".join(menu.panel_lines(startup_scene_layout(80)))


def test_startup_selection_accepts_a_disconnected_provider(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(
        "code_squid.console.startup_menu.provider_ready",
        lambda _settings: False,
    )
    monkeypatch.setattr(
        "code_squid.provider_setup.build_provider",
        lambda _settings: SimpleNamespace(is_ready=lambda: False),
    )
    menu = StartupMenu(tmp_path, load_settings(tmp_path))
    menu.focus_from_composer()
    menu.selected_index = MAIN_ROWS.index("Provider")
    menu.activate()
    rendered = "\n".join(menu.panel_lines(startup_scene_layout(80)))
    assert "LM Studio" in rendered
    assert "not connected" in rendered

    menu.selected_index = menu._options.index("ollama")
    menu.activate()

    persisted = json.loads(settings_path().read_text(encoding="utf-8"))
    assert menu.settings.model.provider == "ollama"
    assert persisted["model"]["provider"] == "ollama"
    assert menu.mode == "main"


def test_startup_provider_selection_restores_provider_scoped_connection(
    monkeypatch,
    tmp_path,
) -> None:
    settings_dir = tmp_path / ".code-squid"
    settings_dir.mkdir()
    (settings_dir / "settings.json").write_text(
        json.dumps(
            {
                "model": {"provider": "lm_studio", "name": "exact-model-id"},
                "providers": {
                    "lm_studio": {"base_url": "http://lan-host:1234/v1"},
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "code_squid.console.startup_menu.provider_ready",
        lambda _settings: False,
    )
    monkeypatch.setattr(
        "code_squid.provider_setup.build_provider",
        lambda _settings: SimpleNamespace(is_ready=lambda: False),
    )
    menu = StartupMenu(tmp_path, load_settings(tmp_path))

    for provider_id in ("ollama", "lm_studio"):
        menu.focus_from_composer()
        menu.selected_index = MAIN_ROWS.index("Provider")
        menu.activate()
        menu.selected_index = menu._options.index(provider_id)
        menu.activate()

    assert menu.settings.model.provider == "lm_studio"
    assert menu.settings.model.base_url == "http://lan-host:1234/v1"
    assert menu.settings.model.name == "exact-model-id"


def test_provider_selection_without_explanation_returns_to_focused_main_menu(
    monkeypatch,
    tmp_path,
) -> None:
    initial = load_settings(tmp_path)
    selected = replace(
        initial,
        model=replace(initial.model, provider="ollama"),
    )
    monkeypatch.setattr(
        "code_squid.console.startup_menu.provider_ready",
        lambda _settings: True,
    )
    monkeypatch.setattr(
        "code_squid.console.startup_menu.select_provider",
        lambda _root, _provider: (selected, None),
    )
    menu = StartupMenu(tmp_path, initial)
    menu.focus_from_composer()
    menu.selected_index = MAIN_ROWS.index("Provider")
    menu.activate()
    menu.selected_index = menu._options.index("ollama")

    assert menu.activate() is False
    assert menu.mode == "main"
    assert menu.focused is True
    assert menu.selected_index == MAIN_ROWS.index("Provider")
    assert menu.settings.model.provider == "ollama"
    assert menu.settings.model.name == initial.model.name

    menu.move(1)
    assert menu.selected_index == MAIN_ROWS.index("Model")


def test_startup_settings_failure_stays_in_panel_without_claiming_success(
    monkeypatch,
    tmp_path,
) -> None:
    initial = load_settings(tmp_path)

    def deny_write(*_args) -> None:
        raise PermissionError("read-only storage")

    monkeypatch.setattr(
        "code_squid.console.startup_menu.apply_model",
        deny_write,
    )
    menu = StartupMenu(
        tmp_path,
        initial,
        model_discovery=lambda _settings: ["next-model"],
    )
    menu.focus_from_composer()
    menu.selected_index = MAIN_ROWS.index("Model")
    menu.activate()

    assert menu.activate() is False
    assert menu.settings is initial
    assert menu.mode == "model"
    rendered = "\n".join(menu.panel_lines(startup_scene_layout(80)))
    assert "Model error" in rendered
    assert "Settings change failed: read-only" in rendered
    assert "storage" in rendered


def test_startup_settings_does_not_swallow_programming_errors(
    monkeypatch,
    tmp_path,
) -> None:
    def fail_unexpectedly(*_args) -> None:
        raise RuntimeError("broken menu callback")

    monkeypatch.setattr(
        "code_squid.console.startup_menu.apply_model",
        fail_unexpectedly,
    )
    menu = StartupMenu(
        tmp_path,
        load_settings(tmp_path),
        model_discovery=lambda _settings: ["next-model"],
    )
    menu.focus_from_composer()
    menu.selected_index = MAIN_ROWS.index("Model")
    menu.activate()

    with pytest.raises(RuntimeError, match="broken menu callback"):
        menu.activate()


def test_provider_menu_uses_friendly_names_and_only_two_status_labels(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(
        "code_squid.console.startup_menu.provider_ready",
        lambda settings: settings.model.provider in {"lm_studio", "ollama"},
    )
    menu = StartupMenu(tmp_path, load_settings(tmp_path))
    menu.focus_from_composer()
    menu.selected_index = MAIN_ROWS.index("Provider")
    menu.activate()
    rendered = "\n".join(menu.panel_lines(startup_scene_layout(80)))
    for label in (
        "Squid Models",
        "LM Studio",
        "Ollama",
        "OpenRouter",
        "OpenAI Compatible",
    ):
        assert label in rendered
    assert "ready" in rendered
    assert "not connected" in rendered
    assert "unavailable" not in rendered


def test_startup_provider_explanation_is_suppressed_while_menu_keeps_focus(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    initial = load_settings(tmp_path)
    selected = replace(
        initial,
        model=replace(initial.model, provider="ollama"),
    )
    monkeypatch.setattr(
        "code_squid.console.startup_menu.provider_ready",
        lambda _settings: False,
    )
    monkeypatch.setattr(
        "code_squid.console.startup_menu.select_provider",
        lambda _root, _provider: (
            selected,
            "Configured model is unavailable from Ollama.",
        ),
    )
    menu = StartupMenu(tmp_path, load_settings(tmp_path))
    menu.focus_from_composer()
    menu.selected_index = MAIN_ROWS.index("Provider")
    menu.activate()
    menu.selected_index = menu._options.index("ollama")

    def unexpected_print(*_args, **_kwargs) -> None:
        raise AssertionError("startup menu selection wrote through print()")

    monkeypatch.setattr("builtins.print", unexpected_print)
    menu.activate()
    assert capsys.readouterr().out == ""
    assert menu.settings.model.provider == "ollama"
    assert menu.settings.model.name == initial.model.name
    assert menu.mode == "main"
    assert menu.focused is True

    panel_lines = menu.panel_lines(startup_scene_layout(80))
    assert len(panel_lines) == startup_scene_layout(80).panel.height
    for row in MAIN_ROWS:
        label = f"{row:<{PANEL_LABEL_WIDTH}}"
        assert sum(label in line for line in panel_lines) == 1

    menu.move(1)
    assert menu.selected_index == MAIN_ROWS.index("Model")


def test_model_viewport_shows_seven_real_ids_and_persists_exact_selection(tmp_path) -> None:
    model_ids = [f"real-model-{index}" for index in range(10)]
    menu = StartupMenu(
        tmp_path,
        load_settings(tmp_path),
        model_discovery=lambda _settings: model_ids,
    )
    layout = startup_scene_layout(80)
    menu.focus_from_composer()
    menu.selected_index = MAIN_ROWS.index("Model")
    menu.activate()
    initial = "\n".join(menu.panel_lines(layout))
    assert initial.count("real-model-") == SUBMENU_VISIBLE_LIMIT
    for _ in range(8):
        menu.move(1)
    assert "real-model-8" in "\n".join(menu.panel_lines(layout))
    menu.activate()
    assert menu.settings.model.name == "real-model-8"


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
    assert seen == ["lm_studio"]
    assert "model-a" in "\n".join(menu.panel_lines(layout))

    menu.selected_index = 0
    menu.activate()
    assert menu.settings.model.name == "model-a"
    assert seen == ["lm_studio"]


def test_provider_model_discovery_uses_optional_adapter_capability(
    monkeypatch,
    tmp_path,
) -> None:
    settings = load_settings(tmp_path)
    providers = []

    def build(provider_settings):
        providers.append(provider_settings.provider)
        return SimpleNamespace(
            is_ready=lambda: True,
            list_models=lambda: ["z", "a", "a"],
        )

    monkeypatch.setattr(
        "code_squid.provider_setup.build_provider",
        lambda settings, *, for_inference: build(settings),
    )
    assert discover_provider_models(settings) == ["a", "z"]
    assert providers == ["lm_studio"]


def test_model_menu_shows_public_openrouter_models_without_key(
    monkeypatch,
    tmp_path,
) -> None:
    def urlopen(http_request, timeout):
        assert http_request.get_header("Authorization") is None
        return JsonResponse({"data": [{"id": "vendor/public-model"}]})

    monkeypatch.setenv("CODE_SQUID_PROVIDER", "openrouter")
    monkeypatch.delenv("CODE_SQUID_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr("squid_core.providers.openai_compatible.request.urlopen", urlopen)
    menu = StartupMenu(tmp_path, load_settings(tmp_path))
    menu.focus_from_composer()
    menu.selected_index = MAIN_ROWS.index("Model")
    menu.activate()

    assert "vendor/public-model" in "\n".join(
        menu.panel_lines(startup_scene_layout(80))
    )


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


def test_workspace_view_selects_current_path_without_mutating_root(tmp_path) -> None:
    menu = StartupMenu(tmp_path, load_settings(tmp_path))
    original_root = menu.repo_root
    menu.focus_from_composer()
    menu.selected_index = MAIN_ROWS.index("Workspace")
    menu.activate()

    lines = menu.panel_lines(startup_scene_layout(80))
    visible_content = "\n".join(lines)
    assert f"> {original_root.name}" in visible_content
    menu.activate()
    assert menu.repo_root == original_root
    assert menu.take_workspace_handoff() == original_root


def test_opening_workspace_publishes_mode_after_discovery_state(tmp_path) -> None:
    layout = startup_scene_layout(80)
    rendered_during_discovery: list[list[str]] = []
    modes_during_discovery: list[str] = []
    menu = StartupMenu(tmp_path, load_settings(tmp_path))

    menu.focus_from_composer()
    menu.selected_index = MAIN_ROWS.index("Provider")
    menu.activate()
    assert len(menu._options) > 1
    menu.back()

    def discover(_root: Path) -> list[Path]:
        modes_during_discovery.append(menu.mode)
        rendered_during_discovery.append(menu.panel_lines(layout))
        return [tmp_path]

    menu.workspace_discovery = discover
    menu.selected_index = MAIN_ROWS.index("Workspace")
    menu.activate()

    assert rendered_during_discovery
    assert modes_during_discovery == ["main"]
    assert menu.mode == "workspace"
    assert tmp_path.name in "\n".join(menu.panel_lines(layout))


def test_workspace_rendering_ignores_stale_shared_option_count(tmp_path) -> None:
    workspace = tmp_path / "only-workspace"
    menu = StartupMenu(tmp_path, load_settings(tmp_path))
    menu.mode = "workspace"
    menu.selected_index = 5
    menu._options = tuple(f"stale-{index}" for index in range(8))
    menu._workspace_paths = (workspace,)

    rendered = "\n".join(menu.panel_lines(startup_scene_layout(80)))

    assert "only-workspace" in rendered
    assert "stale-" not in rendered


def test_empty_workspace_list_renders_and_activates_safely(tmp_path) -> None:
    menu = StartupMenu(
        tmp_path,
        load_settings(tmp_path),
        workspace_discovery=lambda _root: [],
    )
    menu.focus_from_composer()
    menu.selected_index = MAIN_ROWS.index("Workspace")
    menu.activate()

    lines = menu.panel_lines(startup_scene_layout(80))

    assert menu.mode == "workspace"
    assert len(lines) == startup_scene_layout(80).panel.height
    assert menu.activate() is False
    assert menu.take_workspace_handoff() is None


def test_workspace_activation_rejects_index_outside_paths(tmp_path) -> None:
    menu = StartupMenu(tmp_path, load_settings(tmp_path))
    menu.mode = "workspace"
    menu.selected_index = 2
    menu._workspace_paths = (tmp_path,)
    menu._options = (str(tmp_path), "stale-a", "stale-b")

    assert menu.activate() is False
    assert menu.mode == "workspace"
    assert menu.take_workspace_handoff() is None


def test_workspace_view_keeps_centered_footer_for_long_paths(tmp_path) -> None:
    long_root = tmp_path.joinpath(*(["nested-workspace-segment"] * 12))
    menu = StartupMenu(long_root, load_settings(tmp_path))
    menu.focus_from_composer()
    menu.selected_index = MAIN_ROWS.index("Workspace")
    menu.activate()

    inner = [line[1:-1] for line in menu.panel_lines(startup_scene_layout(80))]
    footer = next(
        line
        for line in inner
        if line.strip() == "↑↓   Enter select   Esc back"
    )

    assert footer == "↑↓   Enter select   Esc back".center(len(footer))


def test_workspace_viewport_scrolls_and_escape_does_not_select(tmp_path) -> None:
    workspaces = [tmp_path / f"workspace-{index}" for index in range(9)]
    menu = StartupMenu(
        workspaces[0],
        load_settings(tmp_path),
        workspace_discovery=lambda _: workspaces,
    )
    layout = startup_scene_layout(80)
    menu.focus_from_composer()
    menu.selected_index = MAIN_ROWS.index("Workspace")
    menu.activate()

    initial = menu.panel_lines(layout)
    initial_rendered = "\n".join(initial)
    assert initial_rendered.count("workspace-") == SUBMENU_VISIBLE_LIMIT
    assert "workspace-6" in initial_rendered
    assert "workspace-7" not in initial_rendered
    assert initial[1][1:-1].strip() == "Workspace"
    assert initial[11][1:-1].strip() == "↑↓   Enter select   Esc back"

    for _ in range(SUBMENU_VISIBLE_LIMIT):
        menu.move(1)
    scrolled = menu.panel_lines(layout)
    rendered = "\n".join(scrolled)
    assert menu.selected_index == SUBMENU_VISIBLE_LIMIT
    assert "workspace-0" not in rendered
    assert "workspace-7" in rendered
    assert rendered.count("workspace-") == SUBMENU_VISIBLE_LIMIT
    assert scrolled[1][1:-1].strip() == "Workspace"
    assert scrolled[11][1:-1].strip() == "↑↓   Enter select   Esc back"

    menu.back()
    assert menu.take_workspace_handoff() is None


def test_workspace_recent_selection_releases_startup(monkeypatch, tmp_path) -> None:
    recent = tmp_path / "recent"
    menu = StartupMenu(
        tmp_path,
        load_settings(tmp_path),
        workspace_discovery=lambda root: [root, recent],
    )
    menu.focus_from_composer()
    menu.selected_index = MAIN_ROWS.index("Workspace")
    menu.activate()

    result = _run_prompt(monkeypatch, menu, "\x1b[B\r")

    assert result is STARTUP_WORKSPACE_SELECTED
    assert menu.take_workspace_handoff() == recent


def test_submenu_centers_title_and_footer_but_left_aligns_options(tmp_path) -> None:
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
    footer = next(
        line
        for line in inner
        if line.strip() == "↑↓   Enter select   Esc back"
    )

    assert title == "Provider".center(len(title))
    assert footer == "↑↓   Enter select   Esc back".center(len(footer))
    assert selected.index("a") == unselected.index("long-option")
    assert selected.index(">") == unselected.index("long-option") - 2


def test_all_selectable_submenus_share_fixed_geometry(tmp_path) -> None:
    now = datetime(2026, 9, 7, 12, tzinfo=timezone.utc)
    layout = startup_scene_layout(80)
    menu = StartupMenu(tmp_path, load_settings(tmp_path), now=lambda: now)
    workspace = tmp_path / "recent-workspace"
    session = {
        "session_id": "saved-session",
        "task": "Saved task",
        "updated_at": (now - timedelta(minutes=4)).isoformat(),
    }
    scenarios = (
        ("provider", "Provider", ("provider-option",), "provider-option"),
        ("model", "Model", ("model-option",), "model-option"),
        ("safety", "Safety", ("safety-option",), "safety-option"),
        ("mod", "Mod", ("mod-option",), "mod-option"),
        ("workspace", "Workspace", (str(workspace),), "recent-workspace"),
        (
            "session",
            "Sessions for this workspace",
            ("", "saved-session"),
            "New session",
        ),
    )

    for mode, heading, options, first_label in scenarios:
        menu.mode = mode
        menu.selected_index = 0
        menu._options = options
        menu._workspace_paths = (workspace,) if mode == "workspace" else ()
        menu._session_metadata = (session,) if mode == "session" else ()
        lines = menu.panel_lines(layout)
        inner = [line[1:-1] for line in lines]

        assert inner[1].strip() == heading
        assert first_label in inner[3]
        assert inner[3].index(">") == 2
        assert inner[11].strip() == "↑↓   Enter select   Esc back"
        assert len(lines) == layout.panel.height
        assert {len(line) for line in lines} == {layout.panel.width}


def test_submenu_option_count_does_not_change_fixed_rows_or_recenter(tmp_path) -> None:
    layout = startup_scene_layout(80)
    menu = StartupMenu(tmp_path, load_settings(tmp_path))
    menu.mode = "provider"

    for count in (1, 3, 12):
        menu._options = tuple(f"option-{index}" for index in range(count))
        menu.selected_index = count - 1
        lines = menu.panel_lines(layout)
        inner = [line[1:-1] for line in lines]

        assert inner[1].strip() == "Provider"
        assert "option-" in inner[3]
        assert inner[11].strip() == "↑↓   Enter select   Esc back"
        assert any("> option-" in line for line in inner[3:10])
        # Even a one-item list leaves the lower viewport rows unused.
        if count == 1:
            assert all(not line.strip() for line in inner[4:11])


def test_workspace_labels_still_disambiguate_and_truncate_in_shared_column(
    tmp_path,
) -> None:
    duplicate_a = tmp_path / "parent-a" / "shared"
    duplicate_b = tmp_path / "parent-b" / "shared"
    long_path = tmp_path / ("long-workspace-name-" * 4)
    paths = (duplicate_a, duplicate_b, long_path)
    menu = StartupMenu(
        duplicate_a,
        load_settings(tmp_path),
        workspace_discovery=lambda _: list(paths),
    )
    menu.mode = "workspace"
    menu._workspace_paths = paths
    menu._options = tuple(str(path) for path in paths)

    rendered = "\n".join(menu.panel_lines(startup_scene_layout(80)))

    assert "shared  (parent-a)" in rendered
    assert "shared  (parent-b)" in rendered
    assert "..." in rendered


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

    lines = menu.panel_lines(layout)
    rendered = "\n".join(lines)
    inner = [line[1:-1] for line in lines]
    title = next(
        line for line in inner if line.strip() == "Sessions for this workspace"
    )
    assert menu.mode == "session"
    assert menu._options == ("", "session-0", "session-1", "session-2")
    assert title == "Sessions for this workspace".center(len(title))
    assert not any(line.strip() == "Session" for line in inner)
    assert rendered.index("New session") < rendered.index("Task 0")
    assert rendered.index("Task 0") < rendered.index("Task 1")


def test_session_viewport_shows_seven_entries_then_scrolls(tmp_path) -> None:
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

    initial_lines = menu.panel_lines(layout)
    initial = "\n".join(initial_lines)
    assert initial.count("Task ") + initial.count("New session") == (
        SUBMENU_VISIBLE_LIMIT
    )
    assert "Task 5" in initial
    assert "Task 6" not in initial
    assert initial_lines[1][1:-1].strip() == "Sessions for this workspace"
    assert initial_lines[11][1:-1].strip() == "↑↓   Enter select   Esc back"

    for _ in range(SUBMENU_VISIBLE_LIMIT):
        menu.move(1)
    scrolled_lines = menu.panel_lines(layout)
    scrolled = "\n".join(scrolled_lines)
    assert menu.selected_index == SUBMENU_VISIBLE_LIMIT
    assert "New session" in scrolled
    assert "Task 0" not in scrolled
    assert "Task 6" in scrolled
    assert scrolled.count("Task ") + scrolled.count("New session") == (
        SUBMENU_VISIBLE_LIMIT
    )
    assert scrolled_lines[1][1:-1].strip() == "Sessions for this workspace"
    assert scrolled_lines[11][1:-1].strip() == "↑↓   Enter select   Esc back"


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

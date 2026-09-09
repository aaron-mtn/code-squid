import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from code_squid.app_paths import settings_path
from code_squid.console.cli.cli_options import _resolve_workspace_root
from code_squid.console.cli.cli_commands import SHELL_HELP, _safety, run_cli
from code_squid.console.cli.prompt_loop import (
    HELP_TEXT,
    INPUT_IDENTITY_LINE,
    PROMPT_PREFIX,
    PROMPT_STYLE,
    _composer_prompt,
    _prompt_task,
    _resume_session,
    _run_interactive,
    _run_new_session,
)
from code_squid.console.cli.session_runner import _run_follow_up_task, _run_loop
from code_squid.console.cli.skill_commands import _format_skill_status, _handle_skill_input
from code_squid.console.cli.mod_commands import _format_mod_status, _handle_mod_input
from code_squid.settings import load_settings
from squid_core.agent_loop import RunResult
from squid_core.model_adapter import ModelRequestError
from main import main
from squid_core.storage import SessionStore
from code_squid.console.ui.display import StartupInfo, TerminalDisplay


class ModelFailingLoop:
    def run(self) -> None:
        try:
            raise RuntimeError("provider unavailable")
        except RuntimeError as error:
            raise ModelRequestError("Model request failed") from error


class ResultLoop:
    def __init__(self, result: RunResult) -> None:
        self.result = result

    def run(self) -> RunResult:
        return self.result


class FakeDisplay:
    def __init__(self) -> None:
        self.starts = 0
        self.run_starts = 0
        self.failure_path = None
        self.finished = False
        self.run_result = None
        self.header = None
        self.session_scene_active = False

    def start(self) -> None:
        self.starts += 1
        self.start_session_scene()

    def start_session_scene(self) -> None:
        self.session_scene_active = True

    def retire_session_scene(self) -> None:
        self.session_scene_active = False

    def run_started(self) -> None:
        self.run_starts += 1

    def model_request_failed(self, log_path: Path) -> None:
        self.failure_path = log_path

    def loop_finished(self, session, run_result=None) -> None:
        self.finished = True
        self.run_result = run_result

    def set_specialization(self, *, mod_name, skill_name) -> None:
        self.mod_name = mod_name
        self.skill_name = skill_name

    def stop_header(self) -> None:
        pass


class FakeSessionStore:
    def __init__(self) -> None:
        self.statuses = []

    def update_status(self, status: str) -> None:
        self.statuses.append(status)


def _write_settings(repo_root: Path, settings: dict) -> Path:
    path = settings_path()
    path.write_text(json.dumps(settings), encoding="utf-8")
    return path


def _read_entries(session_store: SessionStore) -> list[dict]:
    return [
        json.loads(line)
        for line in session_store.jsonl_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _write_user_review_skill(monkeypatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    skill_dir = home / "skills" / "user-review"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        """---
name: user-review
description: Review architecture and design without modifying files.
allowed-tools: read_file run_command
---

Review architecture without modifying files.

## FINAL_SUMMARY_REQUIREMENTS replace

Write a focused architecture review.

## TOOL_USAGE_GUIDANCE append

Use inspection tools only.
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("CODE_SQUID_HOME", str(home))


def test_resolve_workspace_root_omitted_uses_current_directory(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.chdir(tmp_path)

    assert _resolve_workspace_root(None) == tmp_path.resolve()


def test_resolve_workspace_root_valid_cwd_uses_selected_directory(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    assert _resolve_workspace_root(str(workspace)) == workspace.resolve()


def test_resolve_workspace_root_missing_cwd_fails_clearly(tmp_path) -> None:
    missing = tmp_path / "missing"

    try:
        _resolve_workspace_root(str(missing))
    except ValueError as error:
        assert str(error) == f"--cwd path does not exist: {missing}"
    else:
        raise AssertionError("Expected missing --cwd path to fail")


def test_resolve_workspace_root_file_cwd_fails_clearly(tmp_path) -> None:
    file_path = tmp_path / "file.txt"
    file_path.write_text("not a directory", encoding="utf-8")

    try:
        _resolve_workspace_root(str(file_path))
    except ValueError as error:
        assert str(error) == f"--cwd path is not a directory: {file_path}"
    else:
        raise AssertionError("Expected file --cwd path to fail")


def test_main_passes_selected_cwd_to_existing_commands(
    monkeypatch,
    tmp_path,
) -> None:
    calls = []

    def fake_safety(repo_root: Path, args: list[str]) -> int:
        calls.append((repo_root, args))
        return 0

    monkeypatch.setattr("code_squid.console.cli.cli_commands._safety", fake_safety)

    assert run_cli(["--cwd", str(tmp_path), "safety"]) == 0
    assert calls == [(tmp_path.resolve(), [])]


def test_shell_safety_forms_dispatch_all_supported_levels(
    monkeypatch,
    tmp_path,
) -> None:
    calls = []

    def fake_safety(repo_root: Path, args: list[str]) -> int:
        calls.append((repo_root, args))
        return 0

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("code_squid.console.cli.cli_commands._safety", fake_safety)

    assert run_cli(["safety"]) == 0
    assert run_cli(["safety", "strict"]) == 0
    assert run_cli(["safety", "balanced"]) == 0
    assert run_cli(["safety", "yolo"]) == 0
    assert calls == [
        (tmp_path.resolve(), []),
        (tmp_path.resolve(), ["strict"]),
        (tmp_path.resolve(), ["balanced"]),
        (tmp_path.resolve(), ["yolo"]),
    ]


def test_main_passes_selected_skill_to_interactive(
    monkeypatch,
    tmp_path,
) -> None:
    calls = []

    def fake_interactive(repo_root: Path, skill_name: str | None = None) -> int:
        calls.append((repo_root, skill_name))
        return 0

    monkeypatch.setattr("code_squid.console.cli.cli_commands._run_interactive", fake_interactive)

    assert run_cli(["--cwd", str(tmp_path), "--skill", "user-review"]) == 0
    assert calls == [(tmp_path.resolve(), "user-review")]


def test_main_missing_cwd_value_fails_clearly(monkeypatch, capsys) -> None:
    monkeypatch.setattr("sys.argv", ["main.py", "--cwd"])

    assert main() == 1
    assert capsys.readouterr().out == "--cwd requires a path\n"


def test_shell_help_forms_print_help_and_succeed(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)

    for command in (["help"], ["--help"], ["-h"]):
        assert run_cli(command) == 0
        assert capsys.readouterr().out == SHELL_HELP


def test_unknown_and_removed_shell_commands_fail(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)

    assert run_cli(["unknown"]) == 1
    assert capsys.readouterr().out == SHELL_HELP
    assert run_cli(["mode"]) == 1
    assert capsys.readouterr().out == SHELL_HELP
    assert run_cli(["skills"]) == 1
    assert capsys.readouterr().out == SHELL_HELP


def test_malformed_and_missing_session_commands_fail(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.chdir(tmp_path)

    assert run_cli(["show"]) == 1
    assert "Usage: python main.py show" in capsys.readouterr().out
    assert run_cli(["resume"]) == 1
    assert "Usage: python main.py resume" in capsys.readouterr().out
    assert run_cli(["show", "latest"]) == 1
    assert capsys.readouterr().out == "No saved sessions.\n"
    assert run_cli(["resume", "latest"]) == 1
    assert capsys.readouterr().out == "No saved sessions.\n"


def test_missing_undo_buffer_fails(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)

    assert run_cli(["undo"]) == 1
    assert "Missing undo metadata" in capsys.readouterr().out


def test_safety_displays_strict_for_always(tmp_path, capsys) -> None:
    _write_settings(tmp_path, {"runtime": {"approval_mode": "always"}})

    assert _safety(tmp_path, []) == 0

    assert capsys.readouterr().out == "Current safety mode: strict (approval_mode=always)\n"


def test_safety_displays_yolo_for_never(tmp_path, capsys) -> None:
    _write_settings(tmp_path, {"runtime": {"approval_mode": "never"}})

    assert _safety(tmp_path, []) == 0

    assert capsys.readouterr().out == "Current safety mode: yolo (approval_mode=never)\n"


def test_safety_displays_balanced_for_guarded(tmp_path, capsys) -> None:
    _write_settings(tmp_path, {"runtime": {"approval_mode": "guarded"}})

    assert _safety(tmp_path, []) == 0

    assert capsys.readouterr().out == "Current safety mode: balanced (approval_mode=guarded)\n"


def test_safety_strict_writes_approval_always_and_preserves_settings(tmp_path, capsys) -> None:
    settings_path = _write_settings(
        tmp_path,
        {
            "model": {"name": "local-model"},
            "runtime": {"approval_mode": "never", "max_tool_steps": 3},
        },
    )

    assert _safety(tmp_path, ["strict"]) == 0

    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    assert settings == {
        "model": {"name": "local-model"},
        "runtime": {"approval_mode": "always", "max_tool_steps": 3},
    }
    assert capsys.readouterr().out == (
        "Safety mode set to strict (approval_mode=always). "
        "Code Squid will ask before every tool execution. This is not a sandbox.\n"
    )


def test_safety_yolo_writes_approval_never(tmp_path, capsys) -> None:
    settings_path = _write_settings(tmp_path, {"runtime": {"approval_mode": "always"}})

    assert _safety(tmp_path, ["yolo"]) == 0

    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    assert settings["runtime"]["approval_mode"] == "never"
    assert capsys.readouterr().out == (
        "Safety mode set to yolo (approval_mode=never). "
        "Tools will run without approval prompts.\n"
    )


def test_safety_balanced_writes_approval_guarded(tmp_path, capsys) -> None:
    settings_path = _write_settings(tmp_path, {"runtime": {"approval_mode": "always"}})

    assert _safety(tmp_path, ["balanced"]) == 0

    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    assert settings["runtime"]["approval_mode"] == "guarded"
    assert capsys.readouterr().out == (
        "Safety mode set to balanced (approval_mode=guarded). "
        "Low-risk workspace actions can run without approval prompts.\n"
    )


def test_safety_strict_creates_minimal_settings_file(tmp_path, capsys) -> None:
    persisted_path = settings_path()

    assert _safety(tmp_path, ["strict"]) == 0

    assert json.loads(persisted_path.read_text(encoding="utf-8")) == {
        "runtime": {"approval_mode": "always"}
    }
    capsys.readouterr()


def test_safety_invalid_value_does_not_modify_settings(tmp_path, capsys) -> None:
    settings_path = _write_settings(tmp_path, {"runtime": {"approval_mode": "always"}})
    original = settings_path.read_text(encoding="utf-8")

    assert _safety(tmp_path, ["banana"]) == 1

    assert settings_path.read_text(encoding="utf-8") == original
    assert capsys.readouterr().out == (
        "Invalid safety command. Usage: "
        "python main.py safety [strict|balanced|yolo]\n"
    )


def test_help_text_lists_current_interactive_commands() -> None:
    for command in (
        "/new",
        "/exit",
        "/mod",
        "/skill",
        "/provider",
        "/model",
        "/safety",
        "/compact-at",
        "/sessions",
        "/show",
        "/resume",
        "/undo",
        "/cwd",
    ):
        assert command in HELP_TEXT
    assert "advanced/direct" in HELP_TEXT
    assert "python main.py" not in HELP_TEXT


def test_help_text_owns_input_controls_guidance() -> None:
    assert "Input:" in HELP_TEXT
    assert "Enter         Send" in HELP_TEXT
    assert "Shift+Enter   New line" in HELP_TEXT
    assert "Alt+Enter     New line" in HELP_TEXT
    assert "Ctrl+C        Cancel before a run or stop the current run" in HELP_TEXT


def test_shell_help_matches_current_command_names() -> None:
    assert "python main.py safety [strict|balanced|yolo]" in SHELL_HELP
    assert "python main.py skill" in SHELL_HELP
    assert "python main.py mode" not in SHELL_HELP
    assert "python main.py skills" not in SHELL_HELP


def test_format_skill_status_lists_current_skill_and_available_skills(
    monkeypatch,
    tmp_path,
) -> None:
    _write_user_review_skill(monkeypatch, tmp_path)
    status = _format_skill_status(None)

    assert "Current skill: none" in status
    assert "Available skills:" in status
    assert "- user-review: Review architecture and design without modifying files." in status
    assert "- bug-fix: Fix bugs with small targeted edits." not in status


def test_format_skill_status_includes_active_skill_details(monkeypatch, tmp_path) -> None:
    _write_user_review_skill(monkeypatch, tmp_path)
    status = _format_skill_status("user-review")

    assert "Current skill: user-review" in status
    assert "Tools: read_file, run_command" in status
    assert (
        "Prompt overrides: FINAL_SUMMARY_REQUIREMENTS, TOOL_USAGE_GUIDANCE"
        in status
    )


def test_format_mod_status_lists_active_and_available_mods(monkeypatch) -> None:
    mods = {
        "review-pack": SimpleNamespace(
            name="review-pack",
            description="Review changes",
            valid=True,
        )
    }
    monkeypatch.setattr(
        "code_squid.console.cli.mod_commands.discover_mods",
        lambda app_home: mods,
    )

    status = _format_mod_status("review-pack")

    assert "Current Mod: review-pack" in status
    assert "Available Mods:" in status
    assert "- review-pack: Review changes" in status


def test_mod_selection_and_clear_are_explicit(monkeypatch, capsys) -> None:
    mod = SimpleNamespace(name="review-pack", description="Review", valid=True)
    monkeypatch.setattr(
        "code_squid.console.cli.mod_commands.discover_mods",
        lambda app_home: {"review-pack": mod},
    )

    selected = _handle_mod_input("/mod review-pack", None, "direct-skill")
    cleared = _handle_mod_input("/mod none", selected[0], selected[1])

    assert selected == ("review-pack", None)
    assert cleared == (None, None)
    output = capsys.readouterr().out
    assert "Standalone skill direct-skill cleared by Mod selection." in output
    assert "Active Mod set to: review-pack" in output
    assert "Active Mod cleared." in output


def test_standalone_skill_selection_clears_mod_and_default_is_not_an_alias(
    monkeypatch,
    capsys,
) -> None:
    skill = SimpleNamespace(name="direct-skill", allowed_tools=("read_file",))
    monkeypatch.setattr(
        "code_squid.console.cli.skill_commands.discover_skills",
        lambda app_home: {"direct-skill": skill},
    )

    selected = _handle_skill_input("/skill direct-skill", None, "review-pack")
    unchanged = _handle_skill_input("/skill default", selected[0], selected[1])

    assert selected == ("direct-skill", None)
    assert unchanged == selected
    output = capsys.readouterr().out
    assert "Active Mod review-pack cleared by standalone skill selection." in output
    assert "Unknown skill: default" in output


def test_run_loop_handles_model_request_error_with_log_and_status(tmp_path) -> None:
    display = FakeDisplay()
    session_store = FakeSessionStore()

    status = _run_loop(
        tmp_path,
        ModelFailingLoop(),
        display,
        session=object(),
        session_store=session_store,
    )

    log_path = tmp_path / ".code-squid" / "logs" / "latest.log"
    log_text = log_path.read_text(encoding="utf-8")

    assert status == 1
    assert display.starts == 0
    assert display.failure_path == Path(".code-squid/logs/latest.log")
    assert display.finished is False
    assert session_store.statuses == ["failed"]
    assert "RuntimeError: provider unavailable" in log_text
    assert "squid_core.model_adapter.ModelRequestError: Model request failed" in log_text


def test_run_loop_returns_zero_for_complete_result(tmp_path) -> None:
    display = FakeDisplay()

    status = _run_loop(
        tmp_path,
        ResultLoop(RunResult(status="complete")),
        display,
        session=object(),
        session_store=FakeSessionStore(),
    )

    assert status == 0
    assert display.run_result == RunResult(status="complete")


def test_run_loop_returns_nonzero_for_failed_result(tmp_path) -> None:
    display = FakeDisplay()

    status = _run_loop(
        tmp_path,
        ResultLoop(RunResult(status="failed", reason="task failed")),
        display,
        session=object(),
        session_store=FakeSessionStore(),
    )

    assert status == 1
    assert display.run_result == RunResult(status="failed", reason="task failed")


def _expected_startup_output(repo_root: Path) -> str:
    startup_info = StartupInfo(
        directory=repo_root,
        provider="LM Studio",
        model="qwen3.5-9b",
        approval_mode="yolo",
    )
    return f"<binary-header>\n{TerminalDisplay()._startup_info_panel(startup_info)}\n\n"


class BannerDisplay(FakeDisplay):
    def __init__(
        self,
        debug: bool = False,
        show_transcript: bool = False,
        startup_info: StartupInfo | None = None,
    ) -> None:
        super().__init__()
        self.debug = debug
        self.show_transcript = show_transcript
        self.startup_info = startup_info

    def start(self) -> None:
        super().start()
        print("<binary-header>")
        if self.startup_info is not None:
            print(TerminalDisplay()._startup_info_panel(self.startup_info))
        print()

    def run_started(self) -> None:
        super().run_started()


class SessionSceneDisplay(FakeDisplay):
    """Track session-scene ownership without rendering terminal frames."""

    def __init__(self) -> None:
        super().__init__()
        self.header = object()
        self.session_scene_active = False
        self.scene_starts = 0
        self.scene_retires = 0

    def start(self) -> None:
        super().start()

    def start_session_scene(self) -> None:
        if self.session_scene_active:
            return
        self.session_scene_active = True
        self.scene_starts += 1

    def retire_session_scene(self) -> None:
        if not self.session_scene_active:
            return
        self.session_scene_active = False
        self.scene_retires += 1


def _fake_prompt_task(response: str):
    def fake_prompt_task(label: str, animator=None) -> str:
        print(INPUT_IDENTITY_LINE)
        print(PROMPT_PREFIX, end="")
        return response

    return fake_prompt_task


def _fake_prompt_tasks(responses: list[str]):
    pending = list(responses)

    def fake_prompt_task(label: str, animator=None) -> str:
        if not pending:
            raise AssertionError("No fake prompt responses left")
        print(INPUT_IDENTITY_LINE)
        print(PROMPT_PREFIX, end="")
        return pending.pop(0)

    return fake_prompt_task


def _cancel_prompt_task(label: str, animator=None) -> str:
    print(INPUT_IDENTITY_LINE)
    print(PROMPT_PREFIX, end="")
    raise KeyboardInterrupt


def test_prompt_task_uses_agent_prompt_without_toolbar(monkeypatch) -> None:
    prompt_calls = []

    def fake_prompt(prompt, *, preface=None, animator=None, boxed=False) -> str:
        prompt_calls.append((prompt, preface, boxed))
        return "Do the thing"

    monkeypatch.setattr("code_squid.console.cli.prompt_loop.prompt_multiline_input", fake_prompt)

    assert _prompt_task("Task") == "Do the thing"

    prompt, preface, boxed = prompt_calls[0]
    assert INPUT_IDENTITY_LINE == "@code-squid"
    assert "🦑" not in INPUT_IDENTITY_LINE
    assert preface is None
    assert boxed is True
    assert prompt() == [
        ("", f"  {INPUT_IDENTITY_LINE}\n  "),
        (PROMPT_STYLE, PROMPT_PREFIX),
    ]
    assert PROMPT_STYLE == ""


def test_composer_marker_tracks_menu_and_submenu_focus() -> None:
    menu = SimpleNamespace(focused=False, mode="main")
    animator = SimpleNamespace(startup_menu=menu)
    prompt = _composer_prompt(animator)

    identity = ("", f"  {INPUT_IDENTITY_LINE}\n  ")
    assert prompt() == [identity, ("", PROMPT_PREFIX)]
    menu.focused = True
    assert prompt() == [identity, ("", "  ")]
    menu.mode = "mod"
    assert prompt() == [identity, ("", "  ")]
    menu.focused = False
    assert prompt() == [identity, ("", PROMPT_PREFIX)]


def test_new_session_prints_banner_before_task_input(monkeypatch, tmp_path, capsys) -> None:
    displays: list[BannerDisplay] = []

    def fake_display(**kwargs) -> BannerDisplay:
        display = BannerDisplay(**kwargs)
        displays.append(display)
        return display

    monkeypatch.setattr("code_squid.console.cli.session_runner.TerminalDisplay", fake_display)
    monkeypatch.setattr("code_squid.console.cli.prompt_loop._prompt_task", _fake_prompt_task("Do the thing"))
    monkeypatch.setattr("code_squid.console.cli.session_runner._run_loop", lambda *args: 0)

    assert _run_new_session(tmp_path) == 0

    assert capsys.readouterr().out == (
        _expected_startup_output(tmp_path)
        + f"{INPUT_IDENTITY_LINE}\n{PROMPT_PREFIX}"
    )
    assert len(displays) == 1
    assert displays[0].starts == 1
    assert displays[0].run_starts == 1


def test_new_session_empty_task_exits_without_run(monkeypatch, tmp_path, capsys) -> None:
    displays: list[BannerDisplay] = []

    def fake_display(**kwargs) -> BannerDisplay:
        display = BannerDisplay(**kwargs)
        displays.append(display)
        return display

    monkeypatch.setattr("code_squid.console.cli.session_runner.TerminalDisplay", fake_display)
    monkeypatch.setattr("code_squid.console.cli.prompt_loop._prompt_task", _fake_prompt_task("  \n\t"))

    assert _run_new_session(tmp_path) == 0

    assert "No task entered; nothing to run." in capsys.readouterr().out
    assert len(displays) == 1
    assert displays[0].starts == 1
    assert displays[0].run_starts == 0
    assert not (tmp_path / ".code-squid" / "sessions").exists()


def test_new_session_help_exits_without_session_or_run(monkeypatch, tmp_path, capsys) -> None:
    displays: list[BannerDisplay] = []

    def fake_display(**kwargs) -> BannerDisplay:
        display = BannerDisplay(**kwargs)
        displays.append(display)
        return display

    monkeypatch.setattr("code_squid.console.cli.session_runner.TerminalDisplay", fake_display)
    monkeypatch.setattr("code_squid.console.cli.prompt_loop._prompt_task", _fake_prompt_task(" /help \n"))

    assert _run_new_session(tmp_path) == 0

    assert HELP_TEXT in capsys.readouterr().out
    assert len(displays) == 1
    assert displays[0].starts == 1
    assert displays[0].run_starts == 0
    assert not (tmp_path / ".code-squid" / "sessions").exists()


def test_new_session_cancelled_task_exits_without_run(monkeypatch, tmp_path, capsys) -> None:
    displays: list[BannerDisplay] = []

    def fake_display(**kwargs) -> BannerDisplay:
        display = BannerDisplay(**kwargs)
        displays.append(display)
        return display

    monkeypatch.setattr("code_squid.console.cli.session_runner.TerminalDisplay", fake_display)
    monkeypatch.setattr("code_squid.console.cli.prompt_loop._prompt_task", _cancel_prompt_task)

    assert _run_new_session(tmp_path) == 0

    assert "⏹️ Cancelled before task started" in capsys.readouterr().out
    assert len(displays) == 1
    assert displays[0].starts == 1
    assert displays[0].run_starts == 0
    assert not (tmp_path / ".code-squid" / "sessions").exists()


def test_resume_session_prints_banner_before_follow_up_input(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    session_store = SessionStore.create(tmp_path, "original task")
    displays: list[BannerDisplay] = []

    def fake_display(**kwargs) -> BannerDisplay:
        display = BannerDisplay(**kwargs)
        displays.append(display)
        return display

    monkeypatch.setattr("code_squid.console.cli.session_runner.TerminalDisplay", fake_display)
    monkeypatch.setattr(
        "code_squid.console.cli.session_runner._session_dir_for_resume",
        lambda repo_root, session_id: session_store.session_dir,
    )
    monkeypatch.setattr(
        "code_squid.console.cli.prompt_loop._prompt_task",
        _fake_prompt_tasks(["Continue the thing", "/exit"]),
    )
    monkeypatch.setattr("code_squid.console.cli.session_runner._run_loop", lambda *args: 0)

    assert _resume_session(tmp_path, session_store.session_id) == 0

    assert capsys.readouterr().out == (
        _expected_startup_output(tmp_path)
        + f"{INPUT_IDENTITY_LINE}\n{PROMPT_PREFIX}"
        + f"{INPUT_IDENTITY_LINE}\n{PROMPT_PREFIX}"
    )
    assert len(displays) == 1
    assert displays[0].starts == 1
    assert displays[0].run_starts == 1


def test_follow_up_records_current_skill_run_context(
    monkeypatch,
    tmp_path,
) -> None:
    _write_user_review_skill(monkeypatch, tmp_path)
    session_store = SessionStore.create(tmp_path, "original task")
    session_store.append_run_context(
        skill_name=None,
        allowed_tools=["apply_patch", "read_file", "run_command", "write_file"],
        prompt_overrides=[],
    )

    monkeypatch.setattr(
        "code_squid.console.cli.session_runner._session_dir_for_resume",
        lambda repo_root, session_id: session_store.session_dir,
    )
    monkeypatch.setattr("code_squid.console.cli.session_runner._run_loop", lambda *args: 0)

    status, session_id = _run_follow_up_task(
        tmp_path,
        session_store.session_id,
        "review the architecture",
        load_settings(tmp_path),
        FakeDisplay(),
        skill_name="user-review",
    )

    entries = _read_entries(session_store)
    contexts = [entry for entry in entries if entry["type"] == "run_context"]
    assert status == 0
    assert session_id == session_store.session_id
    assert contexts[0]["skill_name"] is None
    assert contexts[0]["allowed_tools"] == [
        "apply_patch",
        "read_file",
        "run_command",
        "write_file",
    ]
    assert contexts[1]["skill_name"] == "user-review"
    assert contexts[1]["allowed_tools"] == ["read_file", "run_command"]
    assert contexts[1]["prompt_overrides"] == [
        "FINAL_SUMMARY_REQUIREMENTS",
        "TOOL_USAGE_GUIDANCE",
    ]


def test_follow_up_delegates_mod_resolution_to_application_builder(
    monkeypatch,
    tmp_path,
) -> None:
    session_store = SessionStore.create(tmp_path, "original task")
    session_store.append_message({"role": "system", "content": "old"})
    captured = {}

    class FollowUpAgent:
        def follow_up_message(self, task: str) -> dict:
            return {"role": "user", "content": task}

    def fake_build(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(loop=SimpleNamespace(agent=FollowUpAgent()))

    monkeypatch.setattr(
        "code_squid.console.cli.session_runner._session_dir_for_resume",
        lambda repo_root, session_id: session_store.session_dir,
    )
    monkeypatch.setattr(
        "code_squid.console.cli.session_runner.build_coding_task_run",
        fake_build,
    )
    monkeypatch.setattr("code_squid.console.cli.session_runner._run_loop", lambda *args: 0)

    status, _ = _run_follow_up_task(
        tmp_path,
        session_store.session_id,
        "review this",
        load_settings(tmp_path),
        FakeDisplay(),
        mod_name="review-pack",
    )

    assert status == 0
    assert captured["mod_name"] == "review-pack"
    assert captured["skill_name"] is None
    assert captured["session_store"].session_dir == session_store.session_dir
    assert captured["session"].messages == [
        {"role": "system", "content": "old"},
        {"role": "user", "content": "review this"},
    ]


def test_resume_session_empty_task_exits_without_run(monkeypatch, tmp_path, capsys) -> None:
    session_store = SessionStore.create(tmp_path, "original task")
    displays: list[BannerDisplay] = []

    def fake_display(**kwargs) -> BannerDisplay:
        display = BannerDisplay(**kwargs)
        displays.append(display)
        return display

    monkeypatch.setattr("code_squid.console.cli.session_runner.TerminalDisplay", fake_display)
    monkeypatch.setattr(
        "code_squid.console.cli.session_runner._session_dir_for_resume",
        lambda repo_root, session_id: session_store.session_dir,
    )
    monkeypatch.setattr(
        "code_squid.console.cli.prompt_loop._prompt_task",
        _fake_prompt_tasks(["", "/exit"]),
    )

    assert _resume_session(tmp_path, session_store.session_id) == 0

    capsys.readouterr()
    assert len(displays) == 1
    assert displays[0].starts == 1
    assert displays[0].run_starts == 0
    assert session_store.load_messages() == []


def test_interactive_exit_stops_header(monkeypatch, tmp_path) -> None:
    class ExitDisplay(FakeDisplay):
        def __init__(self) -> None:
            super().__init__()
            self.header = object()
            self.header_stops = 0

        def stop_header(self) -> None:
            self.header_stops += 1

    display = ExitDisplay()

    def exit_prompt(label, animator=None) -> str:
        assert animator is display.header
        return "/exit"

    monkeypatch.setattr("code_squid.console.cli.prompt_loop._run_display", lambda *args: display)
    monkeypatch.setattr("code_squid.console.cli.prompt_loop._prompt_task", exit_prompt)

    assert _run_interactive(tmp_path) == 0
    assert display.header_stops == 1


def test_interactive_eof_stops_header(monkeypatch, tmp_path) -> None:
    class EofDisplay(FakeDisplay):
        def __init__(self) -> None:
            super().__init__()
            self.header = object()
            self.header_stops = 0

        def stop_header(self) -> None:
            self.header_stops += 1

    display = EofDisplay()

    def eof_prompt(label, animator=None) -> str:
        raise EOFError

    monkeypatch.setattr("code_squid.console.cli.prompt_loop._run_display", lambda *args: display)
    monkeypatch.setattr("code_squid.console.cli.prompt_loop._prompt_task", eof_prompt)

    with pytest.raises(EOFError):
        _run_interactive(tmp_path)
    assert display.header_stops == 1


def test_resume_session_help_exits_without_follow_up_or_run(monkeypatch, tmp_path, capsys) -> None:
    session_store = SessionStore.create(tmp_path, "original task")
    displays: list[BannerDisplay] = []

    def fake_display(**kwargs) -> BannerDisplay:
        display = BannerDisplay(**kwargs)
        displays.append(display)
        return display

    monkeypatch.setattr("code_squid.console.cli.session_runner.TerminalDisplay", fake_display)
    monkeypatch.setattr(
        "code_squid.console.cli.session_runner._session_dir_for_resume",
        lambda repo_root, session_id: session_store.session_dir,
    )
    monkeypatch.setattr(
        "code_squid.console.cli.prompt_loop._prompt_task",
        _fake_prompt_tasks(["/help", "/exit"]),
    )

    assert _resume_session(tmp_path, session_store.session_id) == 0

    assert HELP_TEXT in capsys.readouterr().out
    assert len(displays) == 1
    assert displays[0].starts == 1
    assert displays[0].run_starts == 0
    assert session_store.load_messages() == []
    assert not (tmp_path / ".code-squid" / "undo").exists()


def test_resume_session_cancelled_task_exits_without_run(monkeypatch, tmp_path, capsys) -> None:
    session_store = SessionStore.create(tmp_path, "original task")
    displays: list[BannerDisplay] = []

    def fake_display(**kwargs) -> BannerDisplay:
        display = BannerDisplay(**kwargs)
        displays.append(display)
        return display

    monkeypatch.setattr("code_squid.console.cli.session_runner.TerminalDisplay", fake_display)
    monkeypatch.setattr(
        "code_squid.console.cli.session_runner._session_dir_for_resume",
        lambda repo_root, session_id: session_store.session_dir,
    )
    monkeypatch.setattr("code_squid.console.cli.prompt_loop._prompt_task", _cancel_prompt_task)

    assert _resume_session(tmp_path, session_store.session_id) == 0

    assert "⏹️ Cancelled before task started" in capsys.readouterr().out
    assert len(displays) == 1
    assert displays[0].starts == 1
    assert displays[0].run_starts == 0
    assert session_store.load_messages() == []


def test_new_session_passes_trace_and_friendly_mode_to_terminal_display(
    monkeypatch,
    tmp_path,
) -> None:
    _write_settings(tmp_path, {"runtime": {"approval_mode": "guarded"}})
    display_kwargs = []

    def fake_display(**kwargs) -> BannerDisplay:
        display_kwargs.append(kwargs)
        return BannerDisplay(**kwargs)

    monkeypatch.setenv("CODE_SQUID_TRACE", "1")
    monkeypatch.setattr("code_squid.console.cli.session_runner.TerminalDisplay", fake_display)
    monkeypatch.setattr("code_squid.console.cli.prompt_loop._prompt_task", _fake_prompt_task("Do the thing"))
    monkeypatch.setattr("code_squid.console.cli.session_runner._run_loop", lambda *args: 0)

    assert _run_new_session(tmp_path) == 0

    assert display_kwargs == [
        {
            "debug": True,
            "show_transcript": True,
            "startup_info": StartupInfo(
                directory=tmp_path,
                    provider="LM Studio",
                model="qwen3.5-9b",
                approval_mode="balanced",
            ),
        }
    ]


def test_new_session_trace_does_not_push_presentation_into_provider(
    monkeypatch,
    tmp_path,
) -> None:
    provider_kwargs = []

    class CapturingDisplay(BannerDisplay):
        pass

    class CapturingProvider:
        def __init__(self, **kwargs) -> None:
            provider_kwargs.append(kwargs)

    monkeypatch.setenv("CODE_SQUID_TRACE", "1")
    monkeypatch.setattr("code_squid.console.cli.session_runner.TerminalDisplay", CapturingDisplay)
    monkeypatch.setattr("squid_core.providers.OpenAICompatibleProvider", CapturingProvider)
    monkeypatch.setattr("code_squid.console.cli.prompt_loop._prompt_task", _fake_prompt_task("Do the thing"))
    monkeypatch.setattr("code_squid.console.cli.session_runner._run_loop", lambda *args: 0)

    assert _run_new_session(tmp_path) == 0

    assert "debug" not in provider_kwargs[0]


def test_interactive_exit_command_exits_without_run(monkeypatch, tmp_path) -> None:
    def fail_run(*args):
        raise AssertionError("interactive exit should not start a run")

    monkeypatch.setattr("code_squid.console.cli.session_runner.TerminalDisplay", BannerDisplay)
    monkeypatch.setattr("code_squid.console.cli.prompt_loop._prompt_task", _fake_prompt_tasks(["/exit"]))
    monkeypatch.setattr("code_squid.console.cli.prompt_loop._run_new_session_task", fail_run)
    monkeypatch.setattr("code_squid.console.cli.prompt_loop._run_follow_up_task", fail_run)

    assert _run_interactive(tmp_path) == 0


def test_interactive_new_command_clears_active_session(monkeypatch, tmp_path) -> None:
    new_tasks = []
    follow_up_tasks = []

    def fake_new(repo_root, task, settings, display, skill_name=None):
        new_tasks.append(task)
        return 0, f"session-{len(new_tasks)}"

    def fake_follow_up(repo_root, session_id, task, settings, display, skill_name=None):
        follow_up_tasks.append((session_id, task))
        return 0, session_id

    monkeypatch.setattr("code_squid.console.cli.session_runner.TerminalDisplay", BannerDisplay)
    monkeypatch.setattr(
        "code_squid.console.cli.prompt_loop._prompt_task",
        _fake_prompt_tasks(["first task", "/new", "second task", "/exit"]),
    )
    monkeypatch.setattr("code_squid.console.cli.prompt_loop._run_new_session_task", fake_new)
    monkeypatch.setattr("code_squid.console.cli.prompt_loop._run_follow_up_task", fake_follow_up)

    assert _run_interactive(tmp_path) == 0

    assert new_tasks == ["first task", "second task"]
    assert follow_up_tasks == []


def test_interactive_scene_is_initial_only_until_new_session(monkeypatch, tmp_path) -> None:
    display = SessionSceneDisplay()
    prompt_animators = []
    responses = iter(["first task", "/help", "/new", "second task", "/exit"])

    def prompt(label, animator=None):
        prompt_animators.append(animator)
        return next(responses)

    monkeypatch.setattr(
        "code_squid.console.cli.prompt_loop._run_display", lambda *args: display
    )
    monkeypatch.setattr("code_squid.console.cli.prompt_loop._prompt_task", prompt)
    monkeypatch.setattr(
        "code_squid.console.cli.prompt_loop._run_new_session_task",
        lambda *args, **kwargs: (0, "session"),
    )
    monkeypatch.setattr(
        "code_squid.console.cli.prompt_loop._run_follow_up_task",
        lambda *args, **kwargs: (0, "session"),
    )

    assert _run_interactive(tmp_path) == 0
    assert prompt_animators == [display.header, None, None, display.header, None]
    assert display.scene_starts == 2
    assert display.scene_retires == 2


def test_interactive_second_input_uses_follow_up_path(monkeypatch, tmp_path) -> None:
    new_tasks = []
    follow_up_tasks = []

    def fake_new(repo_root, task, settings, display, skill_name=None):
        new_tasks.append(task)
        return 0, "active-session"

    def fake_follow_up(repo_root, session_id, task, settings, display, skill_name=None):
        follow_up_tasks.append((session_id, task))
        return 0, session_id

    monkeypatch.setattr("code_squid.console.cli.session_runner.TerminalDisplay", BannerDisplay)
    monkeypatch.setattr(
        "code_squid.console.cli.prompt_loop._prompt_task",
        _fake_prompt_tasks(["first task", "follow up", "/exit"]),
    )
    monkeypatch.setattr("code_squid.console.cli.prompt_loop._run_new_session_task", fake_new)
    monkeypatch.setattr("code_squid.console.cli.prompt_loop._run_follow_up_task", fake_follow_up)

    assert _run_interactive(tmp_path) == 0

    assert new_tasks == ["first task"]
    assert follow_up_tasks == [("active-session", "follow up")]


def test_interactive_skill_command_lists_current_and_available_skills(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    _write_user_review_skill(monkeypatch, tmp_path)

    def fail_run(*args):
        raise AssertionError("interactive /skill should not start a run")

    monkeypatch.setattr("code_squid.console.cli.session_runner.TerminalDisplay", BannerDisplay)
    monkeypatch.setattr("code_squid.console.cli.prompt_loop._prompt_task", _fake_prompt_tasks(["/skill", "/exit"]))
    monkeypatch.setattr("code_squid.console.cli.prompt_loop._run_new_session_task", fail_run)
    monkeypatch.setattr("code_squid.console.cli.prompt_loop._run_follow_up_task", fail_run)

    assert _run_interactive(tmp_path) == 0

    output = capsys.readouterr().out
    assert "Current skill: none" in output
    assert "Available skills:" in output
    assert "- user-review: Review architecture and design without modifying files." in output


def test_interactive_skill_command_sets_active_skill_for_new_and_follow_up(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    _write_user_review_skill(monkeypatch, tmp_path)
    new_runs = []
    follow_up_runs = []

    def fake_new(repo_root, task, settings, display, skill_name=None):
        new_runs.append((task, skill_name))
        return 0, "active-session"

    def fake_follow_up(repo_root, session_id, task, settings, display, skill_name=None):
        follow_up_runs.append((session_id, task, skill_name))
        return 0, session_id

    monkeypatch.setattr("code_squid.console.cli.session_runner.TerminalDisplay", BannerDisplay)
    monkeypatch.setattr(
        "code_squid.console.cli.prompt_loop._prompt_task",
        _fake_prompt_tasks(
            ["/skill user-review", "first task", "follow up", "/exit"]
        ),
    )
    monkeypatch.setattr("code_squid.console.cli.prompt_loop._run_new_session_task", fake_new)
    monkeypatch.setattr("code_squid.console.cli.prompt_loop._run_follow_up_task", fake_follow_up)

    assert _run_interactive(tmp_path) == 0

    output = capsys.readouterr().out
    assert "Active skill set to: user-review" in output
    assert "Tools: read_file, run_command" in output
    assert new_runs == [("first task", "user-review")]
    assert follow_up_runs == [("active-session", "follow up", "user-review")]


def test_interactive_skill_none_clears_active_skill(monkeypatch, tmp_path, capsys) -> None:
    new_runs = []
    follow_up_runs = []

    def fake_new(repo_root, task, settings, display, skill_name=None):
        new_runs.append((task, skill_name))
        return 0, "active-session"

    def fake_follow_up(repo_root, session_id, task, settings, display, skill_name=None):
        follow_up_runs.append((session_id, task, skill_name))
        return 0, session_id

    monkeypatch.setattr("code_squid.console.cli.session_runner.TerminalDisplay", BannerDisplay)
    monkeypatch.setattr(
        "code_squid.console.cli.prompt_loop._prompt_task",
        _fake_prompt_tasks(["first task", "/skill none", "follow up", "/exit"]),
    )
    monkeypatch.setattr("code_squid.console.cli.prompt_loop._run_new_session_task", fake_new)
    monkeypatch.setattr("code_squid.console.cli.prompt_loop._run_follow_up_task", fake_follow_up)

    assert _run_interactive(tmp_path, "user-review") == 0

    assert "Active skill cleared." in capsys.readouterr().out
    assert new_runs == [("first task", "user-review")]
    assert follow_up_runs == [("active-session", "follow up", None)]


def test_interactive_unknown_skill_does_not_change_active_skill(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    new_runs = []

    def fake_new(repo_root, task, settings, display, skill_name=None):
        new_runs.append((task, skill_name))
        return 0, "active-session"

    monkeypatch.setattr("code_squid.console.cli.session_runner.TerminalDisplay", BannerDisplay)
    monkeypatch.setattr(
        "code_squid.console.cli.prompt_loop._prompt_task",
        _fake_prompt_tasks(["/skill some-skill", "first task", "/exit"]),
    )
    monkeypatch.setattr("code_squid.console.cli.prompt_loop._run_new_session_task", fake_new)

    assert _run_interactive(tmp_path, "user-review") == 0

    output = capsys.readouterr().out
    assert "Unknown skill: some-skill" in output
    assert "Run /skill to see available skills." in output
    assert new_runs == [("first task", "user-review")]


def test_interactive_mod_selection_is_used_for_new_and_follow_up_runs(
    monkeypatch,
    tmp_path,
) -> None:
    mod = SimpleNamespace(name="review-pack", description="Review", valid=True)
    new_runs = []
    follow_up_runs = []

    def fake_new(
        repo_root,
        task,
        settings,
        display,
        skill_name=None,
        mod_name=None,
    ):
        new_runs.append((task, skill_name, mod_name))
        return 0, "active-session"

    def fake_follow_up(
        repo_root,
        session_id,
        task,
        settings,
        display,
        skill_name=None,
        mod_name=None,
    ):
        follow_up_runs.append((session_id, task, skill_name, mod_name))
        return 0, session_id

    monkeypatch.setattr(
        "code_squid.console.cli.mod_commands.discover_mods",
        lambda app_home: {"review-pack": mod},
    )
    monkeypatch.setattr("code_squid.console.cli.session_runner.TerminalDisplay", BannerDisplay)
    monkeypatch.setattr(
        "code_squid.console.cli.prompt_loop._prompt_task",
        _fake_prompt_tasks(["/mod review-pack", "first", "follow up", "/exit"]),
    )
    monkeypatch.setattr("code_squid.console.cli.prompt_loop._run_new_session_task", fake_new)
    monkeypatch.setattr(
        "code_squid.console.cli.prompt_loop._run_follow_up_task",
        fake_follow_up,
    )

    assert _run_interactive(tmp_path) == 0
    assert new_runs == [("first", None, "review-pack")]
    assert follow_up_runs == [
        ("active-session", "follow up", None, "review-pack")
    ]


def test_bare_exit_and_quit_are_forwarded_as_task_text(monkeypatch, tmp_path) -> None:
    new_tasks = []
    follow_up_tasks = []

    def fake_new(repo_root, task, settings, display, skill_name=None):
        new_tasks.append(task)
        return 0, "active-session"

    def fake_follow_up(
        repo_root,
        session_id,
        task,
        settings,
        display,
        skill_name=None,
    ):
        follow_up_tasks.append(task)
        return 0, session_id

    monkeypatch.setattr("code_squid.console.cli.session_runner.TerminalDisplay", BannerDisplay)
    monkeypatch.setattr(
        "code_squid.console.cli.prompt_loop._prompt_task",
        _fake_prompt_tasks(["exit", "quit", "/exit"]),
    )
    monkeypatch.setattr("code_squid.console.cli.prompt_loop._run_new_session_task", fake_new)
    monkeypatch.setattr(
        "code_squid.console.cli.prompt_loop._run_follow_up_task",
        fake_follow_up,
    )

    assert _run_interactive(tmp_path) == 0
    assert new_tasks == ["exit"]
    assert follow_up_tasks == ["quit"]


def test_new_session_passes_debug_without_trace_to_terminal_display(
    monkeypatch,
    tmp_path,
) -> None:
    display_kwargs = []

    def fake_display(**kwargs) -> BannerDisplay:
        display_kwargs.append(kwargs)
        return BannerDisplay(**kwargs)

    monkeypatch.setenv("CODE_SQUID_DEBUG", "1")
    monkeypatch.setattr("code_squid.console.cli.session_runner.TerminalDisplay", fake_display)
    monkeypatch.setattr("code_squid.console.cli.prompt_loop._prompt_task", _fake_prompt_task("Do the thing"))
    monkeypatch.setattr("code_squid.console.cli.session_runner._run_loop", lambda *args: 0)

    assert _run_new_session(tmp_path) == 0

    assert display_kwargs == [
        {
            "debug": True,
            "show_transcript": False,
            "startup_info": StartupInfo(
                directory=tmp_path,
                    provider="LM Studio",
                model="qwen3.5-9b",
                approval_mode="yolo",
            ),
        }
    ]


def test_resume_session_passes_trace_to_terminal_display(
    monkeypatch,
    tmp_path,
) -> None:
    session_store = SessionStore.create(tmp_path, "original task")
    display_kwargs = []

    def fake_display(**kwargs) -> BannerDisplay:
        display_kwargs.append(kwargs)
        return BannerDisplay(**kwargs)

    monkeypatch.setenv("CODE_SQUID_TRACE", "1")
    monkeypatch.setattr("code_squid.console.cli.session_runner.TerminalDisplay", fake_display)
    monkeypatch.setattr(
        "code_squid.console.cli.session_runner._session_dir_for_resume",
        lambda repo_root, session_id: session_store.session_dir,
    )
    monkeypatch.setattr(
        "code_squid.console.cli.prompt_loop._prompt_task",
        _fake_prompt_tasks(["Continue the thing", "/exit"]),
    )
    monkeypatch.setattr("code_squid.console.cli.session_runner._run_loop", lambda *args: 0)

    assert _resume_session(tmp_path, session_store.session_id) == 0

    assert display_kwargs == [
        {
            "debug": True,
            "show_transcript": True,
            "startup_info": StartupInfo(
                directory=tmp_path,
                    provider="LM Studio",
                model="qwen3.5-9b",
                approval_mode="yolo",
            ),
        }
    ]

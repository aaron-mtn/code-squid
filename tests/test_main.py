import json
from pathlib import Path

from core.agent_loop import RunResult
from core.model_adapter import ModelRequestError
from main import (
    HELP_TEXT,
    INPUT_IDENTITY_LINE,
    PROMPT_STYLE,
    PROMPT_PREFIX,
    _resolve_workspace_root,
    _mode,
    _prompt_task,
    _resume_session,
    _run_loop,
    _run_new_session,
    main,
)
from storage.session_store import SessionStore
from ui.terminal import (
    CODE_SQUID_BANNER,
    RUN_STARTED_DIVIDER,
    SOFT_CYAN_HEX,
    StartupInfo,
    TerminalDisplay,
)


class ModelFailingLoop:
    def run(self) -> None:
        try:
            raise RuntimeError("provider unavailable")
        except RuntimeError as error:
            raise ModelRequestError("Model request failed") from error


class FakeDisplay:
    def __init__(self) -> None:
        self.starts = 0
        self.run_starts = 0
        self.failure_path = None
        self.finished = False
        self.run_result = None

    def start(self) -> None:
        self.starts += 1

    def run_started(self) -> None:
        self.run_starts += 1

    def model_request_failed(self, log_path: Path) -> None:
        self.failure_path = log_path

    def loop_finished(self, session, run_result=None) -> None:
        self.finished = True
        self.run_result = run_result


class FakeSessionStore:
    def __init__(self) -> None:
        self.statuses = []

    def update_status(self, status: str) -> None:
        self.statuses.append(status)


def _write_settings(repo_root: Path, settings: dict) -> Path:
    settings_dir = repo_root / ".code-squid"
    settings_dir.mkdir()
    settings_path = settings_dir / "settings.json"
    settings_path.write_text(json.dumps(settings), encoding="utf-8")
    return settings_path


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

    def fake_mode(repo_root: Path, args: list[str]) -> int:
        calls.append((repo_root, args))
        return 0

    monkeypatch.setattr("sys.argv", ["main.py", "--cwd", str(tmp_path), "mode"])
    monkeypatch.setattr("main._mode", fake_mode)

    assert main() == 0
    assert calls == [(tmp_path.resolve(), [])]


def test_main_missing_cwd_value_fails_clearly(monkeypatch, capsys) -> None:
    monkeypatch.setattr("sys.argv", ["main.py", "--cwd"])

    assert main() == 1
    assert capsys.readouterr().out == "--cwd requires a path\n"


def test_mode_displays_strict_for_always(tmp_path, capsys) -> None:
    _write_settings(tmp_path, {"runtime": {"approval_mode": "always"}})

    assert _mode(tmp_path, []) == 0

    assert capsys.readouterr().out == "Current mode: strict (approval_mode=always)\n"


def test_mode_displays_yolo_for_never(tmp_path, capsys) -> None:
    _write_settings(tmp_path, {"runtime": {"approval_mode": "never"}})

    assert _mode(tmp_path, []) == 0

    assert capsys.readouterr().out == "Current mode: yolo (approval_mode=never)\n"


def test_mode_displays_balanced_for_guarded(tmp_path, capsys) -> None:
    _write_settings(tmp_path, {"runtime": {"approval_mode": "guarded"}})

    assert _mode(tmp_path, []) == 0

    assert capsys.readouterr().out == "Current mode: balanced (approval_mode=guarded)\n"


def test_mode_strict_writes_approval_always_and_preserves_settings(tmp_path, capsys) -> None:
    settings_path = _write_settings(
        tmp_path,
        {
            "model": {"name": "local-model"},
            "runtime": {"approval_mode": "never", "max_tool_steps": 3},
        },
    )

    assert _mode(tmp_path, ["strict"]) == 0

    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    assert settings == {
        "model": {"name": "local-model"},
        "runtime": {"approval_mode": "always", "max_tool_steps": 3},
    }
    assert capsys.readouterr().out == (
        "Mode set to strict (approval_mode=always). "
        "Code Squid will ask before every tool execution. This is not a sandbox.\n"
    )


def test_mode_yolo_writes_approval_never(tmp_path, capsys) -> None:
    settings_path = _write_settings(tmp_path, {"runtime": {"approval_mode": "always"}})

    assert _mode(tmp_path, ["yolo"]) == 0

    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    assert settings["runtime"]["approval_mode"] == "never"
    assert capsys.readouterr().out == (
        "Mode set to yolo (approval_mode=never). "
        "Tools will run without approval prompts.\n"
    )


def test_mode_balanced_writes_approval_guarded(tmp_path, capsys) -> None:
    settings_path = _write_settings(tmp_path, {"runtime": {"approval_mode": "always"}})

    assert _mode(tmp_path, ["balanced"]) == 0

    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    assert settings["runtime"]["approval_mode"] == "guarded"
    assert capsys.readouterr().out == (
        "Mode set to balanced (approval_mode=guarded). "
        "Low-risk workspace actions can run without approval prompts.\n"
    )


def test_mode_strict_creates_minimal_settings_file(tmp_path, capsys) -> None:
    settings_path = tmp_path / ".code-squid" / "settings.json"

    assert _mode(tmp_path, ["strict"]) == 0

    assert json.loads(settings_path.read_text(encoding="utf-8")) == {
        "runtime": {"approval_mode": "always"}
    }
    capsys.readouterr()


def test_mode_invalid_value_does_not_modify_settings(tmp_path, capsys) -> None:
    settings_path = _write_settings(tmp_path, {"runtime": {"approval_mode": "always"}})
    original = settings_path.read_text(encoding="utf-8")

    assert _mode(tmp_path, ["banana"]) == 1

    assert settings_path.read_text(encoding="utf-8") == original
    assert capsys.readouterr().out == "Invalid mode. Valid options: strict, balanced, yolo\n"


def test_help_text_lists_new_friendly_modes() -> None:
    assert "  python main.py mode strict\n" in HELP_TEXT
    assert "  python main.py mode balanced\n" in HELP_TEXT
    assert "  python main.py mode yolo\n" in HELP_TEXT
    assert "  python main.py mode safe\n" not in HELP_TEXT
    assert "  python main.py mode guarded\n" not in HELP_TEXT


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
    assert "core.model_adapter.ModelRequestError: Model request failed" in log_text


def _expected_startup_output(repo_root: Path) -> str:
    startup_info = StartupInfo(
        directory=repo_root,
        provider="openai_compatible",
        model="qwen3.5-9b",
        approval_mode="yolo",
    )
    return f"{CODE_SQUID_BANNER}\n\n{TerminalDisplay()._startup_info_panel(startup_info)}\n\n"


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
        print(CODE_SQUID_BANNER)
        if self.startup_info is not None:
            print()
            print(TerminalDisplay()._startup_info_panel(self.startup_info))
        print()

    def run_started(self) -> None:
        super().run_started()
        print()
        print(RUN_STARTED_DIVIDER)
        print()


class NoopLoop:
    def run(self) -> RunResult:
        return RunResult(status="complete")


def _fake_prompt_task(response: str):
    def fake_prompt_task(label: str) -> str:
        print(INPUT_IDENTITY_LINE)
        print(PROMPT_PREFIX, end="")
        return response

    return fake_prompt_task


def _cancel_prompt_task(label: str) -> str:
    print(INPUT_IDENTITY_LINE)
    print(PROMPT_PREFIX, end="")
    raise KeyboardInterrupt


def test_prompt_task_uses_agent_prompt_without_toolbar(monkeypatch) -> None:
    prompt_calls = []

    def fake_prompt(prompt, *, preface=None) -> str:
        prompt_calls.append((prompt, preface))
        return "Do the thing"

    monkeypatch.setattr("main.prompt_multiline_input", fake_prompt)

    assert _prompt_task("Task") == "Do the thing"

    prompt, preface = prompt_calls[0]
    assert preface == [(PROMPT_STYLE, INPUT_IDENTITY_LINE)]
    assert prompt == [(PROMPT_STYLE, PROMPT_PREFIX)]
    assert prompt[0][0] == preface[0][0]
    assert PROMPT_STYLE == f"{SOFT_CYAN_HEX} bold"
    assert PROMPT_STYLE != "ansicyan bold"


def test_new_session_prints_banner_before_task_prompt(monkeypatch, tmp_path, capsys) -> None:
    displays: list[BannerDisplay] = []

    def fake_display(**kwargs) -> BannerDisplay:
        display = BannerDisplay(**kwargs)
        displays.append(display)
        return display

    def fake_build_loop(*args):
        assert args[-1] is displays[0]
        return NoopLoop()

    monkeypatch.setattr("main.TerminalDisplay", fake_display)
    monkeypatch.setattr("main._prompt_task", _fake_prompt_task("Do the thing"))
    monkeypatch.setattr("main._build_loop", fake_build_loop)
    monkeypatch.setattr("main._run_loop", lambda *args: 0)

    assert _run_new_session(tmp_path) == 0

    assert capsys.readouterr().out == (
        _expected_startup_output(tmp_path)
        + f"{INPUT_IDENTITY_LINE}\n{PROMPT_PREFIX}"
        + f"\n{RUN_STARTED_DIVIDER}\n\n"
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

    def fail_build_loop(*args):
        raise AssertionError("_build_loop should not run for an empty task")

    monkeypatch.setattr("main.TerminalDisplay", fake_display)
    monkeypatch.setattr("main._prompt_task", _fake_prompt_task("  \n\t"))
    monkeypatch.setattr("main._build_loop", fail_build_loop)

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

    def fail_build_loop(*args):
        raise AssertionError("_build_loop should not run for help")

    monkeypatch.setattr("main.TerminalDisplay", fake_display)
    monkeypatch.setattr("main._prompt_task", _fake_prompt_task(" /help \n"))
    monkeypatch.setattr("main._build_loop", fail_build_loop)

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

    def fail_build_loop(*args):
        raise AssertionError("_build_loop should not run for a cancelled task")

    monkeypatch.setattr("main.TerminalDisplay", fake_display)
    monkeypatch.setattr("main._prompt_task", _cancel_prompt_task)
    monkeypatch.setattr("main._build_loop", fail_build_loop)

    assert _run_new_session(tmp_path) == 0

    assert "⏹️ Cancelled before task started" in capsys.readouterr().out
    assert len(displays) == 1
    assert displays[0].starts == 1
    assert displays[0].run_starts == 0
    assert not (tmp_path / ".code-squid" / "sessions").exists()


def test_resume_session_prints_banner_before_follow_up_prompt(
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

    def fake_build_loop(*args):
        assert args[-1] is displays[0]
        return NoopLoop()

    monkeypatch.setattr("main.TerminalDisplay", fake_display)
    monkeypatch.setattr(
        "main._session_dir_for_resume",
        lambda repo_root, session_id: session_store.session_dir,
    )
    monkeypatch.setattr("main._prompt_task", _fake_prompt_task("Continue the thing"))
    monkeypatch.setattr("main._build_loop", fake_build_loop)
    monkeypatch.setattr("main._run_loop", lambda *args: 0)

    assert _resume_session(tmp_path, session_store.session_id) == 0

    assert capsys.readouterr().out == (
        _expected_startup_output(tmp_path)
        + f"{INPUT_IDENTITY_LINE}\n{PROMPT_PREFIX}"
        + f"\n{RUN_STARTED_DIVIDER}\n\n"
    )
    assert len(displays) == 1
    assert displays[0].starts == 1
    assert displays[0].run_starts == 1


def test_resume_session_empty_task_exits_without_run(monkeypatch, tmp_path, capsys) -> None:
    session_store = SessionStore.create(tmp_path, "original task")
    displays: list[BannerDisplay] = []

    def fake_display(**kwargs) -> BannerDisplay:
        display = BannerDisplay(**kwargs)
        displays.append(display)
        return display

    def fail_build_loop(*args):
        raise AssertionError("_build_loop should not run for an empty follow-up")

    monkeypatch.setattr("main.TerminalDisplay", fake_display)
    monkeypatch.setattr(
        "main._session_dir_for_resume",
        lambda repo_root, session_id: session_store.session_dir,
    )
    monkeypatch.setattr("main._prompt_task", _fake_prompt_task(""))
    monkeypatch.setattr("main._build_loop", fail_build_loop)

    assert _resume_session(tmp_path, session_store.session_id) == 0

    assert "No task entered; nothing to run." in capsys.readouterr().out
    assert len(displays) == 1
    assert displays[0].starts == 1
    assert displays[0].run_starts == 0
    assert session_store.load_messages() == []


def test_resume_session_help_exits_without_follow_up_or_run(monkeypatch, tmp_path, capsys) -> None:
    session_store = SessionStore.create(tmp_path, "original task")
    displays: list[BannerDisplay] = []

    def fake_display(**kwargs) -> BannerDisplay:
        display = BannerDisplay(**kwargs)
        displays.append(display)
        return display

    def fail_build_loop(*args):
        raise AssertionError("_build_loop should not run for help")

    monkeypatch.setattr("main.TerminalDisplay", fake_display)
    monkeypatch.setattr(
        "main._session_dir_for_resume",
        lambda repo_root, session_id: session_store.session_dir,
    )
    monkeypatch.setattr("main._prompt_task", _fake_prompt_task("/help"))
    monkeypatch.setattr("main._build_loop", fail_build_loop)

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

    def fail_build_loop(*args):
        raise AssertionError("_build_loop should not run for a cancelled follow-up")

    monkeypatch.setattr("main.TerminalDisplay", fake_display)
    monkeypatch.setattr(
        "main._session_dir_for_resume",
        lambda repo_root, session_id: session_store.session_dir,
    )
    monkeypatch.setattr("main._prompt_task", _cancel_prompt_task)
    monkeypatch.setattr("main._build_loop", fail_build_loop)

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
    monkeypatch.setattr("main.TerminalDisplay", fake_display)
    monkeypatch.setattr("main._prompt_task", _fake_prompt_task("Do the thing"))
    monkeypatch.setattr("main._build_loop", lambda *args: NoopLoop())
    monkeypatch.setattr("main._run_loop", lambda *args: 0)

    assert _run_new_session(tmp_path) == 0

    assert display_kwargs == [
        {
            "debug": True,
            "show_transcript": True,
            "startup_info": StartupInfo(
                directory=tmp_path,
                provider="openai_compatible",
                model="qwen3.5-9b",
                approval_mode="balanced",
            ),
        }
    ]


def test_new_session_trace_threads_effective_debug_to_provider(
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
    monkeypatch.setattr("main.TerminalDisplay", CapturingDisplay)
    monkeypatch.setattr("main.OpenAICompatibleProvider", CapturingProvider)
    monkeypatch.setattr("main._prompt_task", _fake_prompt_task("Do the thing"))
    monkeypatch.setattr("main._run_loop", lambda *args: 0)

    assert _run_new_session(tmp_path) == 0

    assert provider_kwargs[0]["debug"] is True


def test_new_session_passes_debug_without_trace_to_terminal_display(
    monkeypatch,
    tmp_path,
) -> None:
    display_kwargs = []

    def fake_display(**kwargs) -> BannerDisplay:
        display_kwargs.append(kwargs)
        return BannerDisplay(**kwargs)

    monkeypatch.setenv("CODE_SQUID_DEBUG", "1")
    monkeypatch.setattr("main.TerminalDisplay", fake_display)
    monkeypatch.setattr("main._prompt_task", _fake_prompt_task("Do the thing"))
    monkeypatch.setattr("main._build_loop", lambda *args: NoopLoop())
    monkeypatch.setattr("main._run_loop", lambda *args: 0)

    assert _run_new_session(tmp_path) == 0

    assert display_kwargs == [
        {
            "debug": True,
            "show_transcript": False,
            "startup_info": StartupInfo(
                directory=tmp_path,
                provider="openai_compatible",
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
    monkeypatch.setattr("main.TerminalDisplay", fake_display)
    monkeypatch.setattr(
        "main._session_dir_for_resume",
        lambda repo_root, session_id: session_store.session_dir,
    )
    monkeypatch.setattr("main._prompt_task", _fake_prompt_task("Continue the thing"))
    monkeypatch.setattr("main._build_loop", lambda *args: NoopLoop())
    monkeypatch.setattr("main._run_loop", lambda *args: 0)

    assert _resume_session(tmp_path, session_store.session_id) == 0

    assert display_kwargs == [
        {
            "debug": True,
            "show_transcript": True,
            "startup_info": StartupInfo(
                directory=tmp_path,
                provider="openai_compatible",
                model="qwen3.5-9b",
                approval_mode="yolo",
            ),
        }
    ]

"""Regression tests for startup-owned buffer lifetime across real input applications."""

import pytest
from prompt_toolkit.application import create_app_session, get_app_session
from prompt_toolkit.data_structures import Size
from prompt_toolkit.input.defaults import create_pipe_input
from prompt_toolkit.output import DummyOutput

from code_squid.console.cli import prompt_loop, session_runner
from code_squid.console.cli.cli_commands import run_cli
from code_squid.console.ui.banner import StartupInfo
from code_squid.console.ui.binary_header import TITLE
from code_squid.console.ui.display import TerminalDisplay
from code_squid.console.ui.terminal_session import startup_terminal


class BufferOutput(DummyOutput):
    """Record writes and clears against the active terminal buffer."""

    def __init__(self):
        self.primary = "original shell history\n"
        self.alternate = ""
        self.active = False
        self.events = []
        self.entry_transcripts = []
        self.primary_raw_writes = []

    def get_size(self):
        return Size(rows=40, columns=80)

    def enter_alternate_screen(self):
        assert not self.active
        self.active = True
        self.entry_transcripts.append(self.primary)
        self.events.append("enter")

    def quit_alternate_screen(self):
        assert self.active
        self.active = False
        self.events.append("leave")

    def write(self, data):
        self.events.append(("write", self.active, data))
        if self.active:
            self.alternate += data
        else:
            self.primary += data

    def write_raw(self, data):
        if not self.active:
            self.primary_raw_writes.append(data)
        self.write(data)

    def erase_screen(self):
        assert self.active, "clear escaped into the shell buffer"
        self.alternate = ""
        self.events.append("clear")

    def erase_down(self):
        pass


@pytest.mark.parametrize("rows", [12, 40, 80])
@pytest.mark.parametrize("trailing_newline", [False, True])
def test_compact_handoff_appends_without_overwriting_transcript(rows, trailing_newline):
    from prompt_toolkit.layout.screen import Char, Screen

    from code_squid.console.ui.binary_header import BinaryRainHeader
    from code_squid.console.ui.prompt_input import multiline_key_bindings
    from code_squid.console.ui.startup_application import StartupApplication

    class CursorOutput(BufferOutput):
        """Model primary CR/LF and character overwrites at the saved cursor."""

        def __init__(self):
            super().__init__()
            # More history than any viewport, ending with a possibly partial line.
            self.primary = "previous session output\n" * 100 + "last output"
            if trailing_newline:
                self.primary += "\n"
            self.lines = self.primary.split("\n")
            self.row = len(self.lines) - 1
            self.column = len(self.lines[-1])

        def get_size(self):
            return Size(rows=rows, columns=80)

        def cursor_goto(self, row, column):
            assert self.active, "handoff must append at the restored primary cursor"

        def write(self, data):
            super().write(data)
            if self.active:
                return
            # Unlike an append-only recorder, this catches a missing newline
            # after CR: the frame would overwrite the preceding transcript row.
            for character in data:
                if character == "\r":
                    self.column = 0
                elif character == "\n":
                    self.row += 1
                    if self.row == len(self.lines):
                        self.lines.append("")
                else:
                    line = self.lines[self.row].ljust(self.column)
                    self.lines[self.row] = (
                        line[:self.column] + character + line[self.column + 1:]
                    )
                    self.column += 1
            self.primary = "\n".join(self.lines)

    output = CursorOutput()
    original = output.primary
    with create_pipe_input() as pipe:
        for cycle in range(3):
            prior = output.primary
            rain = BinaryRainHeader()
            startup = StartupApplication(
                "> ", rain, multiline_key_bindings(rain), input=pipe, output=output,
            )
            frame = f"retained startup frame {cycle}"
            screen = Screen(initial_height=1)
            for column, character in enumerate(frame):
                screen.data_buffer[0][column] = Char(character)
            # Exercise the projection after the same buffer restoration used
            # by the renderer, with no input timing or model inference involved.
            with startup_terminal(output):
                startup.submit("task")
                rain.complete_fade()
                startup.final_screen = screen
                assert output.primary == prior
            startup._retain_clean_frame()
            assert output.primary == prior + "\n\n" + frame + "\n"
            startup._retain_clean_frame()
            assert output.primary.count(frame) == 1
            output.write(f"new session output {cycle}\r\n")
    assert output.primary.startswith(original)
    assert output.primary_raw_writes == ["\r\n\r\n"] * 3
    assert not output.active
    assert output.events.count("enter") == output.events.count("leave") == 3


@pytest.mark.parametrize("ending", [
    "exit", "ctrl_c", "startup_ctrl_c", "followup_ctrl_c",
    "keyboard_interrupt", "startup_failure", "run_failure",
])
def test_interactive_buffer_lifetime(monkeypatch, tmp_path, capsys, ending):
    output = BufferOutput()
    monkeypatch.setenv("CODE_SQUID_HOME", str(tmp_path / "home"))
    display = TerminalDisplay(startup_info=StartupInfo(tmp_path, "provider", "model", "yolo"))
    monkeypatch.setattr(prompt_loop, "_run_display", lambda *args: display)
    stopped = []
    original_stop = display.stop_header

    def stop():
        try:
            original_stop()
        finally:
            stopped.append(True)

    monkeypatch.setattr(display, "stop_header", stop)
    if ending == "startup_failure":
        def fail_start():
            assert not output.active
            raise OSError("startup failed")
        monkeypatch.setattr(display, "start", fail_start)

    if ending == "run_failure":
        def fail_build(**kwargs):
            assert not output.active
            raise ValueError("run construction failed")
        monkeypatch.setattr(session_runner, "build_coding_task_run", fail_build)
    else:
        def run_task(*args, **kwargs):
            display.finish_startup_fade()
            assert not output.active
            assert TITLE in output.primary
            get_app_session().output.write("run output marker\n")
            return 0, None
        monkeypatch.setattr(prompt_loop, "_run_new_session_task", run_task)

    if ending == "startup_ctrl_c":
        responses = iter(["\x03"])
    elif ending == "followup_ctrl_c":
        responses = iter(["task", "\x03"])
    else:
        responses = iter(["/help", "task", "/new", "/exit" if ending == "exit" else "\x03"])
    original_help = prompt_loop._print_help

    def print_help():
        assert not output.active
        original_help()

    monkeypatch.setattr(prompt_loop, "_print_help", print_help)
    original_prompt = prompt_loop._prompt_task
    prompts = []
    with create_pipe_input() as pipe:
        def prompt(label, animator=None):
            assert not output.active
            prompts.append(animator is not None)
            if len(prompts) == 3:
                assert "run output marker" in output.primary
                assert TITLE in output.primary
            if ending == "keyboard_interrupt" and len(prompts) == 4:
                raise KeyboardInterrupt
            pipe.send_text(next(responses) + "\r")
            return original_prompt(label, animator)
        monkeypatch.setattr(prompt_loop, "_prompt_task", prompt)
        with create_app_session(input=pipe, output=output):
            status = run_cli(["--cwd", str(tmp_path)])
            assert get_app_session().output is output
    assert status == (1 if ending in {"startup_failure", "run_failure"} else 0)
    assert stopped
    assert not output.active
    assert output.primary.startswith("original shell history\n")
    switches = [event for event in output.events if event in ("enter", "leave")]
    expected_scenes = 0 if ending == "startup_failure" else 2 if ending in {"exit", "ctrl_c"} else 1
    assert switches == ["enter", "leave"] * expected_scenes
    if ending in {"exit", "ctrl_c"}:
        assert prompts == [True, False, False, True]
        assert output.events.count("clear") == 2
        assert "run output marker" in output.entry_transcripts[1]
        assert output.primary.startswith(output.entry_transcripts[1])
        assert "Code Squid help" in capsys.readouterr().out
        assert "run output marker" in output.primary
        assert "run output marker" not in output.alternate
        # All retained scenes and command/run text belong to native scrollback.
        assert TITLE in output.primary



def test_noninteractive_help_does_not_switch_buffers():
    output = BufferOutput()
    with create_app_session(output=output):
        assert run_cli(["--help"]) == 0
    assert output.events == []


@pytest.mark.parametrize("error", [KeyboardInterrupt, RuntimeError, SystemExit])
def test_terminal_boundary_restores_on_unhandled_exit(error):
    output = BufferOutput()
    with create_app_session(output=output):
        with pytest.raises(error):
            with startup_terminal(output):
                assert output.active
                raise error
        assert get_app_session().output is output
    assert output.events == ["enter", "leave"]
    assert output.primary == "original shell history\n"


@pytest.mark.parametrize("stage", ["entry", "entry_flush", "exit_flush"])
def test_buffer_restore_attempted_when_terminal_operations_fail(stage):
    output = BufferOutput()
    original_enter = output.enter_alternate_screen
    original_flush = output.flush
    calls = 0

    def enter():
        original_enter()
        if stage == "entry":
            raise OSError("entry failed after switching")

    def flush():
        nonlocal calls
        calls += 1
        if (stage == "entry_flush" and calls == 1) or (stage == "exit_flush" and calls == 2):
            raise OSError("flush failed")
        original_flush()

    output.enter_alternate_screen = enter
    output.flush = flush
    with pytest.raises(OSError):
        with startup_terminal(output):
            assert output.active
    assert not output.active
    assert output.events == ["enter", "leave"]


@pytest.mark.parametrize("error", [KeyboardInterrupt, RuntimeError, SystemExit])
def test_startup_renderer_failure_restores_before_propagating(error):
    from code_squid.console.ui.startup_application import StartupApplication, startup_application_active
    from code_squid.console.ui.binary_header import BinaryRainHeader
    from code_squid.console.ui.prompt_input import multiline_key_bindings

    output = BufferOutput()
    with create_pipe_input() as pipe:
        rain = BinaryRainHeader()
        startup = StartupApplication("> ", rain, multiline_key_bindings(rain), input=pipe, output=output)

        def fail():
            assert output.active
            raise error("renderer failed")

        startup.application.run = fail
        with pytest.raises(error):
            startup.run()
        startup._thread.join(timeout=2)
    assert not startup_application_active(rain)
    assert not output.active
    assert output.events == ["enter", "leave"]
    assert output.primary == "original shell history\n"


def test_caller_keyboard_interrupt_joins_startup_before_propagating(monkeypatch):
    from code_squid.console.ui.startup_application import StartupApplication, startup_application_active
    from code_squid.console.ui.binary_header import BinaryRainHeader
    from code_squid.console.ui.prompt_input import multiline_key_bindings
    import threading

    output = BufferOutput()
    with create_pipe_input() as pipe:
        rain = BinaryRainHeader()
        startup = StartupApplication("> ", rain, multiline_key_bindings(rain), input=pipe, output=output)
        entered = threading.Event()
        original_enter = output.enter_alternate_screen

        def enter():
            original_enter()
            entered.set()

        def interrupted_wait():
            assert entered.wait(timeout=2)
            raise KeyboardInterrupt

        monkeypatch.setattr(output, "enter_alternate_screen", enter)
        monkeypatch.setattr(startup._submitted, "wait", interrupted_wait)
        with pytest.raises(KeyboardInterrupt):
            startup.run()
        assert not startup._thread.is_alive()
    assert not startup_application_active(rain)
    assert not output.active
    assert output.primary == "original shell history\n"
    assert [event for event in output.events if event in ("enter", "leave")] == ["enter", "leave"]


def test_thread_start_failure_releases_startup_registration(monkeypatch):
    from code_squid.console.ui.startup_application import StartupApplication, startup_application_active
    from code_squid.console.ui.binary_header import BinaryRainHeader
    from code_squid.console.ui.prompt_input import multiline_key_bindings
    import threading

    output = BufferOutput()
    with create_pipe_input() as pipe:
        rain = BinaryRainHeader()
        startup = StartupApplication("> ", rain, multiline_key_bindings(rain), input=pipe, output=output)

        def fail_start(self):
            raise RuntimeError("thread start failed")

        monkeypatch.setattr(threading.Thread, "start", fail_start)
        with pytest.raises(RuntimeError, match="thread start failed"):
            startup.run()
    assert not startup_application_active(rain)
    assert not output.active
    assert output.events == []


@pytest.mark.parametrize("rebuilds", [0, 1, 3])
@pytest.mark.parametrize("cycles", [1, 2])
def test_startup_cycles_commit_only_final_frame(monkeypatch, tmp_path, rebuilds, cycles):
    from dataclasses import replace

    from code_squid.console import startup_menu as menu_module
    from code_squid.console.startup_menu import MAIN_ROWS, StartupMenu
    from code_squid.console.ui.binary_header import BinaryRainHeader
    from code_squid.console.ui.prompt_input import multiline_key_bindings
    from code_squid.console.ui.startup_application import (
        STARTUP_WORKSPACE_SELECTED,
        StartupApplication,
    )
    from code_squid.settings import load_settings

    # Provider persistence/discovery is covered by menu tests. This lifecycle
    # test isolates rendering and must never contact a model/provider.
    monkeypatch.setattr(menu_module, "provider_ready", lambda _: True)
    monkeypatch.setattr(
        menu_module, "select_provider",
        lambda root, provider: (
            replace(load_settings(root), model=replace(load_settings(root).model, provider=provider)),
            None,
        ),
    )
    output = BufferOutput()
    retained_calls = []
    original_retain = StartupApplication._retain_clean_frame

    def retain(startup):
        before = output.primary
        original_retain(startup)
        if output.primary != before:
            retained_calls.append(startup)

    monkeypatch.setattr(StartupApplication, "_retain_clean_frame", retain)
    with create_pipe_input() as pipe:
        for cycle in range(cycles):
            for scene in range(rebuilds + 1):
                prior = output.primary
                menu = StartupMenu(
                    tmp_path, load_settings(tmp_path), mod_name="previous-mod",
                    model_discovery=lambda _: ["selected-model"],
                    session_discovery=lambda _: [{"session_id": "saved", "task": "Saved task"}],
                    session_resolver=lambda _, session: session,
                    workspace_discovery=lambda _: [tmp_path],
                )
                rain = BinaryRainHeader(startup_info=menu.startup_info)
                rain.startup_menu = menu
                startup = StartupApplication(
                    "> ", rain, multiline_key_bindings(rain), input=pipe, output=output,
                )

                def configure():
                    assert output.active
                    for row, option in [
                        ("Provider", "lm_studio"), ("Model", "selected-model"),
                        ("Safety", "yolo"), ("Mod", "none"), ("Session", "saved"),
                    ]:
                        menu.focus_from_composer()
                        menu.selected_index = MAIN_ROWS.index(row)
                        menu.activate()
                        menu.selected_index = menu._options.index(option)
                        menu.activate()
                        startup.application.invalidate()
                        assert output.primary == prior
                        assert not rain.fade_active
                    assert menu.session_id == "saved"
                    assert menu.mod_name is None
                    if scene < rebuilds:
                        menu.focus_from_composer()
                        menu.selected_index = MAIN_ROWS.index("Workspace")
                        menu.activate()
                        menu.activate()
                        startup.select_workspace()

                startup.application.pre_run_callables.append(configure)
                if scene == rebuilds:
                    pipe.send_text(f"task cycle {cycle}\r")
                result = startup.run()
                startup.wait_for_exit()
                assert not output.active
                if scene < rebuilds:
                    assert result is STARTUP_WORKSPACE_SELECTED
                    # Includes the spacer: even blank primary writes are forbidden.
                    assert output.primary == prior
                    assert startup.final_screen is not None
                else:
                    assert result == f"task cycle {cycle}"
                    assert output.primary[len(prior):].count(TITLE) == 1
                    assert output.primary[len(prior):].count(f"task cycle {cycle}") == 1
                    committed = output.primary
                    startup._retain_clean_frame()
                    assert output.primary == committed
            output.write(f"normal run/help/error output cycle {cycle}\n")
    assert len(retained_calls) == cycles
    assert output.primary.count(TITLE) == cycles
    assert output.primary_raw_writes == ["\r\n\r\n"] * cycles
    assert output.primary.startswith("original shell history\n")
    assert [event for event in output.events if event in ("enter", "leave")] == [
        "enter", "leave",
    ] * ((rebuilds + 1) * cycles)


@pytest.mark.parametrize("interactive", [True, False])
def test_cli_workspace_rebuilds_and_new_preserve_one_frame_per_cycle(monkeypatch, tmp_path, interactive):
    from code_squid.console.startup_menu import MAIN_ROWS

    output = BufferOutput()
    roots = [tmp_path / name for name in ("first", "second", "third")]
    for root in roots:
        root.mkdir()
    original_prompt = prompt_loop._prompt_task
    responses = iter(
        [roots[1], roots[2], "task", "/new", roots[0], "/exit"]
        if interactive else [roots[1], roots[2], "task"]
    )
    snapshots = []
    runs = []

    with create_pipe_input() as pipe:
        def prompt(label, animator=None):
            response = next(responses)
            if animator is not None:
                snapshots.append(output.primary)
                if len(snapshots) > 1:
                    assert animator.startup_menu.mod_name == "selected-mod"
            if response in roots:
                menu = animator.startup_menu
                menu.mod_name = "selected-mod"
                menu.workspace_discovery = lambda _: [response]
                menu.focus_from_composer()
                menu.selected_index = MAIN_ROWS.index("Workspace")
                menu.activate()
                pipe.send_text("\r")
            else:
                pipe.send_text(response + "\r")
            return original_prompt(label, animator)

        def run_task(*args, **kwargs):
            display = args[3]
            display.finish_startup_fade()
            assert not output.active
            assert kwargs["mod_name"] == "selected-mod"
            runs.append(output.primary.count(TITLE))
            output.write("normal run output\n")
            return 0, None

        monkeypatch.setattr(prompt_loop, "_prompt_task", prompt)
        monkeypatch.setattr(prompt_loop, "_run_new_session_task", run_task)
        with create_app_session(input=pipe, output=output):
            run = prompt_loop._run_interactive if interactive else prompt_loop._run_new_session
            assert run(roots[0]) == 0

    assert runs == [1]
    assert snapshots[:3] == ["original shell history\n"] * 3
    if interactive:
        assert snapshots[3] == snapshots[4]
        assert snapshots[3].count(TITLE) == 1
    assert output.primary.count(TITLE) == (2 if interactive else 1)
    assert output.primary_raw_writes == ["\r\n\r\n"] * (2 if interactive else 1)
    assert "normal run output" in output.primary
    assert [event for event in output.events if event in ("enter", "leave")] == [
        "enter", "leave",
    ] * (5 if interactive else 3)

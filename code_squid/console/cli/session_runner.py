"""Run and session orchestration helpers for the Code Squid CLI."""

from contextlib import contextmanager
import os
from pathlib import Path
import signal
import threading

from code_squid.settings import Settings
from code_squid.provider_setup import friendly_provider_name
from squid_core.agent_loop import AgentLoop, RunResult
from squid_core.model_adapter import ModelRequestError
from code_squid.agent_setup import build_coding_task_run
from code_squid.app_paths import (
    workspace_error_log_path,
    workspace_sessions_dir,
)
from squid_core.session import Session
from squid_core.storage import SessionStore, write_error_log
from squid_core.storage.session_index import latest_session_id, session_dir_for
from code_squid.console.ui.banner import FRIENDLY_APPROVAL_MODES, StartupInfo
from code_squid.console.ui.display import TerminalDisplay


class RunCancellationController:
    """Own cancellation state and Ctrl+C handling for one interactive run."""

    def __init__(self) -> None:
        self._cancelled = threading.Event()

    def cancel(self) -> None:
        """Request cancellation for the active run."""
        self._cancelled.set()

    def should_cancel(self) -> bool:
        """Return whether the active run has been cancelled."""
        return self._cancelled.is_set()

    def _handle_sigint(self, _signum, _frame) -> None:
        """Request cancellation once, then preserve a second interrupt."""
        if self.should_cancel():
            # A second Ctrl+C remains an emergency escape if a foreign provider
            # ignores transport closure despite the cooperative request.
            raise KeyboardInterrupt
        self.cancel()

    @contextmanager
    def handle_sigint(self):
        """Translate Ctrl+C into cooperative run cancellation when supported."""
        try:
            previous = signal.getsignal(signal.SIGINT)
            signal.signal(signal.SIGINT, self._handle_sigint)
        except (ValueError, OSError):
            # Signal handlers can only be installed by the main thread. Embedded
            # callers retain the existing KeyboardInterrupt boundary below.
            yield
            return
        try:
            yield
        finally:
            signal.signal(signal.SIGINT, previous)


def _session_dir_for_resume(workspace_root: Path, session_id: str) -> Path | None:
    sessions_dir = workspace_sessions_dir(workspace_root)
    if session_id == "latest":
        resolved_id = latest_session_id(sessions_dir)
        if resolved_id is None:
            print("No saved sessions.")
            return None

        session_id = resolved_id

    return session_dir_for(sessions_dir, session_id)


def _run_display(
    workspace_root: Path,
    settings: Settings,
    skill_name: str | None = None,
) -> TerminalDisplay:
    trace = os.getenv("CODE_SQUID_TRACE") == "1"
    debug = settings.display.debug or trace
    display = TerminalDisplay(
        debug=debug,
        show_transcript=trace,
        startup_info=StartupInfo(
            directory=workspace_root,
            provider=friendly_provider_name(settings.model.provider),
            model=settings.model.name,
            approval_mode=FRIENDLY_APPROVAL_MODES[settings.runtime.approval_mode],
            skill_name=skill_name,
        ),
    )
    # Keep the display-construction seam stable for embedders and tests while
    # applying the application-owned presentation preference before any run.
    display.show_reasoning = settings.display.show_reasoning
    return display


def _run_loop(
    workspace_root: Path,
    loop: AgentLoop,
    display: TerminalDisplay,
    session: Session,
    session_store: SessionStore,
    cancellation: RunCancellationController | None = None,
) -> int:
    cancellation = cancellation or RunCancellationController()
    try:
        with cancellation.handle_sigint():
            run_result = loop.run()
    except KeyboardInterrupt:
        cancellation.cancel()
        session_store.update_status("interrupted")
        run_result = RunResult(status="interrupted", reason="user interrupted")
        display.interrupted()
        display.loop_finished(session, run_result)
        return 0
    except Exception as error:
        return _report_run_failure(workspace_root, display, error, session_store)

    display.loop_finished(session, run_result)
    return 1 if run_result.status == "failed" else 0


def _report_run_failure(
    workspace_root: Path,
    display: TerminalDisplay,
    error: Exception,
    session_store: SessionStore | None,
) -> int:
    """Contain one construction/runtime failure without losing its original cause."""
    if session_store is not None:
        try:
            session_store.update_status("failed")
        except Exception:
            # Storage remains strict elsewhere. A secondary status error must
            # not prevent presentation of the problem that stopped this run.
            pass
    try:
        log_path = write_error_log(workspace_error_log_path(workspace_root), error)
    except Exception:
        # Never claim a diagnostic exists when its write failed. Unexpected
        # diagnostic errors are contained only inside this already-failing path.
        log_path = None
    displayed_log = (
        _display_path(workspace_root, log_path) if log_path is not None else None
    )
    if isinstance(error, ModelRequestError) and displayed_log is not None:
        display.model_request_failed(displayed_log)
    else:
        display.run_failed(
            error,
            displayed_log,
            _display_path(workspace_root, session_store.session_dir)
            if session_store is not None
            else None,
        )
    # A handled model failure keeps the interactive prompt alive, even without
    # diagnostics. Unexpected errors keep the existing non-success exit policy.
    return 0 if isinstance(error, ModelRequestError) else 1


def _display_path(workspace_root: Path, path: Path) -> Path:
    """Prefer a concise workspace-relative path for terminal output."""
    try:
        return path.resolve().relative_to(workspace_root.resolve())
    except ValueError:
        return path


def _run_new_session_task(
    workspace_root: Path,
    task: str,
    settings: Settings,
    display: TerminalDisplay,
    skill_name: str | None = None,
    mod_name: str | None = None,
) -> tuple[int, str | None]:
    display.run_started()
    cancellation = RunCancellationController()

    session_store = None

    def create_session_store(root: Path, initial_task: str) -> SessionStore:
        # Capture the durable identity through the existing factory seam so
        # failed assembly can still report and return a discoverable session.
        nonlocal session_store
        session_store = SessionStore.create(
            workspace_sessions_dir(root), initial_task, workspace_root=root
        )
        return session_store

    try:
        run = build_coding_task_run(
            workspace_root=workspace_root,
            task=task,
            settings=settings,
            display=display,
            on_event=getattr(display, "handle_event", None),
            should_cancel=cancellation.should_cancel,
            skill_name=skill_name,
            mod_name=mod_name,
            session_store_factory=create_session_store,
        )
    except Exception as error:
        status = _report_run_failure(workspace_root, display, error, session_store)
        return status, session_store.session_id if session_store is not None else None

    status = _run_loop(
        workspace_root,
        run.loop,
        display,
        run.session,
        run.session_store,
        cancellation,
    )
    return status, run.session_store.session_id


def _run_follow_up_task(
    workspace_root: Path,
    session_id: str,
    follow_up_task: str,
    settings: Settings,
    display: TerminalDisplay,
    skill_name: str | None = None,
    mod_name: str | None = None,
) -> tuple[int, str | None]:
    session_dir = _session_dir_for_resume(workspace_root, session_id)
    if session_dir is None:
        return 0, None

    session_store = None
    try:
        session_store = SessionStore.open(session_dir)
        session = Session(workspace_root=workspace_root)
        session.add_messages(*session_store.load_messages())

        display.run_started()
        cancellation = RunCancellationController()
        # Follow-ups use the application-owned path used by new runs, so a Mod
        # cannot lose its Skill, restricted Tools, or Hooks when a session resumes.
        run = build_coding_task_run(
            workspace_root=workspace_root,
            task=follow_up_task,
            settings=settings,
            display=display,
            on_event=getattr(display, "handle_event", None),
            should_cancel=cancellation.should_cancel,
            skill_name=skill_name,
            mod_name=mod_name,
            session=session,
            session_store=session_store,
        )
        follow_up_message = run.loop.agent.follow_up_message(follow_up_task)
        session.add_message(follow_up_message)
        session_store.append_message(follow_up_message)
        session_store.update_status("active")
    except Exception as error:
        status = _report_run_failure(workspace_root, display, error, session_store)
        return status, session_store.session_id if session_store is not None else session_id

    status = _run_loop(
        workspace_root,
        run.loop,
        display,
        session,
        session_store,
        cancellation,
    )
    return status, session_store.session_id

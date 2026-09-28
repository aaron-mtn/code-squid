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


def _session_dir_for_resume(repo_root: Path, session_id: str) -> Path | None:
    sessions_dir = workspace_sessions_dir(repo_root)
    if session_id == "latest":
        resolved_id = latest_session_id(sessions_dir)
        if resolved_id is None:
            print("No saved sessions.")
            return None

        session_id = resolved_id

    return session_dir_for(sessions_dir, session_id)


def _run_display(
    repo_root: Path,
    settings: Settings,
    skill_name: str | None = None,
) -> TerminalDisplay:
    trace = os.getenv("CODE_SQUID_TRACE") == "1"
    debug = settings.display.debug or trace
    display = TerminalDisplay(
        debug=debug,
        show_transcript=trace,
        startup_info=StartupInfo(
            directory=repo_root,
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
    repo_root: Path,
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
    except ModelRequestError as error:
        session_store.update_status("failed")
        log_path = write_error_log(workspace_error_log_path(repo_root), error)
        display.model_request_failed(_display_path(repo_root, log_path))
        # The run failed, as recorded above, but the application boundary has
        # handled that failure. Returning success here keeps the persistent
        # prompt alive without weakening handling for any other exception.
        return 0
    except Exception as error:
        # This is the outer boundary for one active run. Unexpected runtime and
        # persistence failures are still non-successful and fully logged, but
        # they should not tear through the terminal with Python internals.
        try:
            session_store.update_status("failed")
        except Exception:
            # A storage failure may make even the best-effort status update
            # impossible. Preserve the original exception as the useful cause.
            pass
        log_path = write_error_log(workspace_error_log_path(repo_root), error)
        display.run_failed(
            error,
            _display_path(repo_root, log_path),
            _display_path(repo_root, session_store.session_dir),
        )
        return 1

    display.loop_finished(session, run_result)
    return 1 if run_result.status == "failed" else 0


def _display_path(repo_root: Path, path: Path) -> Path:
    """Prefer a concise workspace-relative path for terminal output."""
    try:
        return path.resolve().relative_to(repo_root.resolve())
    except ValueError:
        return path


def _run_new_session_task(
    repo_root: Path,
    task: str,
    settings: Settings,
    display: TerminalDisplay,
    skill_name: str | None = None,
    mod_name: str | None = None,
) -> tuple[int, str | None]:
    display.run_started()
    cancellation = RunCancellationController()

    run = build_coding_task_run(
        repo_root=repo_root,
        task=task,
        settings=settings,
        display=display,
        on_event=getattr(display, "handle_event", None),
        should_cancel=cancellation.should_cancel,
        skill_name=skill_name,
        mod_name=mod_name,
    )

    status = _run_loop(
        repo_root,
        run.loop,
        display,
        run.session,
        run.session_store,
        cancellation,
    )
    return status, run.session_store.session_id


def _run_follow_up_task(
    repo_root: Path,
    session_id: str,
    follow_up_task: str,
    settings: Settings,
    display: TerminalDisplay,
    skill_name: str | None = None,
    mod_name: str | None = None,
) -> tuple[int, str | None]:
    session_dir = _session_dir_for_resume(repo_root, session_id)
    if session_dir is None:
        return 0, None

    session_store = SessionStore.open(session_dir)
    session = Session(repo_root=repo_root)
    session.add_messages(*session_store.load_messages())

    display.run_started()
    cancellation = RunCancellationController()
    # Follow-ups use the application-owned path used by new runs, so a Mod
    # cannot lose its Skill, restricted Tools, or Hooks when a session resumes.
    run = build_coding_task_run(
        repo_root=repo_root,
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

    status = _run_loop(
        repo_root,
        run.loop,
        display,
        session,
        session_store,
        cancellation,
    )
    return status, session_store.session_id

from pathlib import Path

from core.app_paths import CODE_SQUID_HOME_ENV
from core.hook_loader import load_user_hooks
from core.hooks import (
    BeforeAcceptFinalContext,
    BeforeRunContext,
    RunFinishedContext,
)
from scripts.install_squid_bell_hook import install_squid_bell_hook


def test_installer_writes_squid_bell_hook(monkeypatch, tmp_path: Path) -> None:
    home = tmp_path / "code-squid-home"
    monkeypatch.setenv(CODE_SQUID_HOME_ENV, str(home))

    hook_dir = install_squid_bell_hook()

    assert hook_dir == home / "hooks" / "squid-bell"
    assert (hook_dir / "hook.yaml").read_text(encoding="utf-8") == (
        "name: squid-bell\n"
        "description: Visible example hook that marks runs and final reports when user hooks are enabled.\n"
        "enabled: true\n"
        "version: 1\n"
    )
    assert "class SquidBellHook" in (hook_dir / "hook.py").read_text(
        encoding="utf-8"
    )


def test_installed_squid_bell_hook_loads_and_marks_decisions(
    monkeypatch,
    tmp_path: Path,
) -> None:
    home = tmp_path / "code-squid-home"
    monkeypatch.setenv(CODE_SQUID_HOME_ENV, str(home))
    install_squid_bell_hook()

    hooks = load_user_hooks()

    assert len(hooks) == 1
    hook = hooks[0]

    run_decision = hook.before_run(
        BeforeRunContext(
            session_id="session",
            repo_root=str(tmp_path),
            task="Test task",
        )
    )
    assert run_decision.context_blocks[0].title == "Squid Bell"

    final_decision = hook.before_accept_final(
        BeforeAcceptFinalContext(
            session_id="session",
            repo_root=str(tmp_path),
            message={"role": "assistant", "content": "Done"},
            content="Done",
        )
    )
    assert "Squid Bell" in final_decision.report_note

    finished_decision = hook.run_finished(
        RunFinishedContext(
            session_id="session",
            repo_root=str(tmp_path),
            status="complete",
        )
    )
    assert any("Squid Bell" in note for note in finished_decision.notes)

"""Central storage ownership, replay, undo, and private session asset regressions."""

import hashlib
import json
import ntpath
import os
import posixpath
from pathlib import Path
from types import SimpleNamespace

import pytest

from code_squid import app_paths
from code_squid.agent_setup import build_coding_task_run
from code_squid.app_paths import (
    code_squid_home, settings_path, workspace_id, workspace_state_dir,
    workspace_sessions_dir, workspace_undo_dir, workspace_error_log_path,
)
from code_squid.asset_preflight import SessionAssetPreflight
from code_squid.console.cli.control_commands import discover_recent_sessions, resolve_session_id, undo_latest_run
from code_squid.console.cli.session_runner import _run_follow_up_task, _session_dir_for_resume
from code_squid.console.ui.sessions import print_session, print_sessions
from code_squid.settings import load_settings
from squid_core.safety import ApprovalPolicy
from squid_core.storage import SessionStore, UndoStore, write_error_log
from squid_core.storage.session_index import list_all_sessions
from squid_core.tools.builtins import TOOLS


def make_run(workspace: Path, task: str = "private task", **kwargs):
    """Construct the real application runtime without a model transport."""
    return build_coding_task_run(
        workspace, task,
        model_adapter=SimpleNamespace(supports_image_input=lambda: True),
        **kwargs,
    )


def test_workspace_isolation_discovery_and_undo(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv(app_paths.CODE_SQUID_SESSION_INDEXES_ENV, str(tmp_path / "registry.jsonl"))
    first, second = tmp_path / "one" / "project", tmp_path / "two" / "project"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    one, two = make_run(first), make_run(second, task="second task")
    one.session_store.append_message({"role": "user", "content": "first private conversation"})
    assert workspace_id(first) != workspace_id(second)
    assert workspace_id(first).startswith("project-")
    assert workspace_id(second).startswith("project-")
    assert one.session_store.session_dir.parent == workspace_state_dir(first) / "sessions"
    assert one.loop.tool_executor.undo_store.undo_dir == workspace_state_dir(first) / "undo"
    assert resolve_session_id(first, "latest") == one.session_store.session_id
    assert discover_recent_sessions(second)[0]["session_id"] == two.session_store.session_id
    assert _session_dir_for_resume(first, "latest") == one.session_store.session_dir
    with pytest.raises(FileNotFoundError):
        resolve_session_id(second, one.session_store.session_id)
    print_sessions(first)
    print_session(first, one.session_store.session_id)
    assert "first private conversation" in capsys.readouterr().out
    registered = list_all_sessions(app_paths.session_indexes_path())
    assert {item["workspace_root"] for item in registered} == {str(first.resolve()), str(second.resolve())}

    target = first / "example.txt"
    target.write_text("before", encoding="utf-8")
    one.loop.tool_executor.undo_store.snapshot_file(str(target.resolve()))
    target.write_text("after", encoding="utf-8")
    assert not undo_latest_run(second)
    assert target.read_text(encoding="utf-8") == "after"
    assert undo_latest_run(first)
    assert target.read_text(encoding="utf-8") == "before"
    assert workspace_error_log_path(first) == workspace_state_dir(first) / "logs" / "latest.log"
    write_error_log(workspace_error_log_path(first), ValueError("private diagnostics"))
    assert workspace_error_log_path(first).is_file()
    assert not workspace_error_log_path(second).exists()
    assert not (first / ".code-squid").exists()
    assert not (second / ".code-squid").exists()


@pytest.mark.parametrize("manifest", [
    None, "{", "[]", '{}',
    '{"version": 1, "workspace_root": "wrong"}',
    '{"version": true}', '{"version": 2}',
])
def test_invalid_ownership_blocks_every_storage_access(tmp_path, manifest):
    run = make_run(tmp_path)
    state = workspace_state_dir(tmp_path)
    before = run.session_store.metadata_path.read_bytes()
    undo_before = (workspace_undo_dir(tmp_path) / "metadata.json").read_bytes()
    owner = state / "workspace.json"
    if manifest is None:
        owner.unlink()
    else:
        owner.write_text(manifest, encoding="utf-8")
    for access in (workspace_sessions_dir, workspace_undo_dir, workspace_error_log_path, discover_recent_sessions):
        with pytest.raises(ValueError, match="ownership|different workspace"):
            access(tmp_path)
    with pytest.raises(ValueError):
        make_run(tmp_path, session_store=run.session_store)
    assert run.session_store.metadata_path.read_bytes() == before
    assert (state / "undo" / "metadata.json").read_bytes() == undo_before


def test_explicit_home_controls_settings_storage_registry_and_command_trust(tmp_path, monkeypatch):
    explicit = tmp_path / "explicit-home"
    explicit.mkdir()
    settings_path(explicit).write_text(json.dumps({"model": {"name": "explicit-model"}}), encoding="utf-8")
    monkeypatch.delenv(app_paths.CODE_SQUID_SESSION_INDEXES_ENV)
    run = make_run(tmp_path / "project", app_home=explicit)
    assert run.loop.model_adapter is not None
    assert load_settings(tmp_path, app_home=explicit).model.name == "explicit-model"
    assert run.session_store.session_dir.parent == workspace_sessions_dir(tmp_path / "project", explicit)
    assert (explicit / "session-indexes.jsonl").is_file()
    assert not (code_squid_home() / "workspaces").exists()
    run.loop.approval_policy.persist_trusted_command("git")
    assert load_settings(tmp_path, app_home=explicit).runtime.trusted_commands == ("git",)


def test_legacy_state_is_neither_loaded_nor_changed(tmp_path):
    legacy = tmp_path / ".code-squid"
    legacy.mkdir()
    (legacy / "settings.json").write_text('{"model": {"name": "do-not-load"}}', encoding="utf-8")
    store = SessionStore.create(legacy / "sessions", "legacy private task", workspace_root=tmp_path)
    store.append_message({"role": "user", "content": "untouched history"})
    UndoStore.create(legacy / "undo", store.session_id, workspace_root=tmp_path)
    write_error_log(legacy / "logs" / "latest.log", ValueError("legacy diagnostics"))
    before = {str(p.relative_to(legacy)): p.read_bytes() for p in legacy.rglob("*") if p.is_file()}
    assert load_settings(tmp_path).model.name != "do-not-load"
    assert discover_recent_sessions(tmp_path) == []
    make_run(tmp_path)
    assert {str(p.relative_to(legacy)): p.read_bytes() for p in legacy.rglob("*") if p.is_file()} == before


def test_workspace_switch_clears_session_and_selects_central_history(tmp_path, monkeypatch):
    from code_squid.console.cli import prompt_loop

    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    one = make_run(first, task="first")
    two = make_run(second, task="second")
    display = SimpleNamespace(stop_header=lambda: None, start=lambda: None)
    monkeypatch.setattr(prompt_loop, "_run_display", lambda *args: display)
    root, _, _, menu, active = prompt_loop._rebuild_workspace_runtime(
        second, first, display, mod_name=None, skill_name=None,
        active_session_id=one.session_store.session_id,
    )
    assert root == second and active is None and menu.session_id is None
    assert menu.session_discovery(root)[0]["session_id"] == two.session_store.session_id
    assert resolve_session_id(first, "latest") == one.session_store.session_id
    assert not (first / ".code-squid").exists()
    assert not (second / ".code-squid").exists()


def test_identity_normalizes_relative_paths_and_native_case(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert workspace_id("folder/../project") == workspace_id(tmp_path / "project")
    prefix, digest = workspace_id(tmp_path).rsplit("-", 1)
    expected_prefix = tmp_path.name.lower() if os.name == "nt" else tmp_path.name
    assert prefix == expected_prefix
    assert len(digest) == 8
    if os.name == "nt":
        assert workspace_id(tmp_path / "Project") == workspace_id(tmp_path / "project")
    else:
        assert workspace_id(tmp_path / "Project") != workspace_id(tmp_path / "project")


def test_readable_name_hashes_full_normalized_path(tmp_path):
    workspace = tmp_path / "code-squid"
    identity = app_paths.normalized_workspace_path(workspace)
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:8]
    assert workspace_id(workspace) == f"code-squid-{digest}"


@pytest.mark.parametrize("basename,expected", [
    ("my game", "my-game"),
    ('my<>:"/\\|?*game', "my-game"),
    ("my\x00\x01\x1f\x7fgame", "my-game"),
    ("project...   ", "project"),
    ("...   ", "workspace"),
    ("", "workspace"),
    ("CON", "workspace-CON"),
    ("nul.txt", "workspace-nul.txt"),
    ("AuX", "workspace-AuX"),
    ("PRN", "workspace-PRN"),
    ("COM1", "workspace-COM1"),
    ("LPT9.data", "workspace-LPT9.data"),
    ("COM¹", "workspace-COM¹"),
    ("LPT²", "workspace-LPT²"),
    ("CONIN$", "workspace-CONIN$"),
    ("CONOUT$", "workspace-CONOUT$"),
    ("COM10", "COM10"),
    ("café-日本", "café-日本"),
])
def test_basename_sanitization_is_portable(monkeypatch, basename, expected):
    # POSIX may supply names Windows cannot represent. Exercise that boundary
    # without asking the native filesystem to create invalid Windows paths.
    monkeypatch.setattr(app_paths, "normalized_workspace_path", lambda _: "identity")
    monkeypatch.setattr(app_paths.os.path, "basename", lambda _: basename)
    assert workspace_id("unused") == f"{expected}-{hashlib.sha256(b'identity').hexdigest()[:8]}"


@pytest.mark.parametrize("basename", ["a" * 300, "界" * 150, "😀" * 100, "a" * 79 + "." + "b" * 100])
def test_long_basename_is_bounded_without_losing_hash(monkeypatch, basename):
    monkeypatch.setattr(app_paths, "normalized_workspace_path", lambda _: "identity")
    monkeypatch.setattr(app_paths.os.path, "basename", lambda _: basename)
    prefix, digest = workspace_id("unused").rsplit("-", 1)
    assert 0 < len(prefix.encode("utf-8")) <= 80
    assert not prefix.endswith((".", " "))
    assert digest == hashlib.sha256(b"identity").hexdigest()[:8]


def test_home_expansion_and_root_workspace_names(tmp_path, monkeypatch):
    monkeypatch.setenv("USERPROFILE" if os.name == "nt" else "HOME", str(tmp_path))
    assert workspace_id("~/project") == workspace_id(tmp_path / "project")
    root = Path(tmp_path.anchor)
    assert workspace_id(root).startswith("workspace-")


def test_short_hash_collision_rejects_all_access_without_mutation(tmp_path, monkeypatch):
    first, second = tmp_path / "one" / "project", tmp_path / "two" / "project"
    # Keep the production basename logic and force only the digest to collide.
    monkeypatch.setattr(app_paths.hashlib, "sha256", lambda _: SimpleNamespace(hexdigest=lambda: "a" * 64))
    one = make_run(first)
    write_error_log(workspace_error_log_path(first), ValueError("owned diagnostics"))
    state = workspace_state_dir(first)
    assert workspace_id(first) == workspace_id(second) == "project-aaaaaaaa"
    before = {str(p.relative_to(state)): p.read_bytes() for p in state.rglob("*") if p.is_file()}
    for access in (
        workspace_state_dir, workspace_sessions_dir, workspace_undo_dir,
        workspace_error_log_path, discover_recent_sessions,
        lambda root: _session_dir_for_resume(root, one.session_store.session_id),
        make_run,
    ):
        with pytest.raises(ValueError, match="different workspace"):
            access(second)
    assert {str(p.relative_to(state)): p.read_bytes() for p in state.rglob("*") if p.is_file()} == before
    assert workspace_state_dir(first) == state


def test_full_hash_development_storage_is_untouched(tmp_path):
    identity = app_paths.normalized_workspace_path(tmp_path)
    legacy = code_squid_home() / "workspaces" / hashlib.sha256(identity.encode("utf-8")).hexdigest()
    legacy.mkdir(parents=True)
    (legacy / "workspace.json").write_text(json.dumps({"version": 1, "workspace_root": identity}), encoding="utf-8")
    store = SessionStore.create(legacy / "sessions", "old task", workspace_root=tmp_path)
    UndoStore.create(legacy / "undo", store.session_id, workspace_root=tmp_path)
    write_error_log(legacy / "logs" / "latest.log", ValueError("old diagnostics"))
    before = {str(p.relative_to(legacy)): p.read_bytes() for p in legacy.rglob("*") if p.is_file()}
    assert discover_recent_sessions(tmp_path) == []
    with pytest.raises(FileNotFoundError):
        _session_dir_for_resume(tmp_path, store.session_id)
    assert not undo_latest_run(tmp_path)
    assert not workspace_error_log_path(tmp_path).exists()
    run = make_run(tmp_path)
    assert run.session_store.session_dir.parent == workspace_sessions_dir(tmp_path)
    assert workspace_state_dir(tmp_path) != legacy
    assert {str(p.relative_to(legacy)): p.read_bytes() for p in legacy.rglob("*") if p.is_file()} == before


@pytest.mark.parametrize("normalizer,resolved,expected", [
    (ntpath.normcase, r"C:\Projects\Game", r"c:\projects\game"),
    (ntpath.normcase, r"\\Server\Share\Game", r"\\server\share\game"),
    (posixpath.normcase, "/home/User/Game", "/home/User/Game"),
])
def test_identity_case_policy_for_windows_and_linux(monkeypatch, normalizer, resolved, expected):
    # Supply an already-resolved native path to test both OS policies on CI;
    # actual host filesystem resolution is covered independently above.
    path = SimpleNamespace(resolve=lambda: resolved)
    monkeypatch.setattr(app_paths, "Path", lambda value: SimpleNamespace(expanduser=lambda: path))
    monkeypatch.setattr(app_paths.os.path, "normcase", normalizer)
    assert app_paths.normalized_workspace_path("unused") == expected


def test_follow_up_reopens_central_session_and_recovers_trailing_calls(tmp_path, monkeypatch):
    run = make_run(tmp_path)
    store = run.session_store
    store.append_message({"role": "assistant", "content": "", "tool_calls": [
        {"id": "interrupted", "type": "function", "function": {"name": "read_file", "arguments": "{}"}},
    ]})
    asset_id = store.snapshot_asset(b"saved image fixture", ".png")
    monkeypatch.setattr("code_squid.provider_setup.build_provider", lambda settings: object())
    observed = []

    def inspect_run(workspace, loop, display, session, reopened, cancellation):
        assert workspace == tmp_path
        assert reopened.session_dir == store.session_dir
        assert reopened.load_asset(asset_id) == b"saved image fixture"
        assert any(message.get("tool_call_id") == "interrupted" for message in session.messages)
        assert loop.tool_executor.undo_store.undo_dir == workspace_undo_dir(tmp_path)
        observed.append(True)
        return 0

    monkeypatch.setattr("code_squid.console.cli.session_runner._run_loop", inspect_run)
    status, session_id = _run_follow_up_task(tmp_path, store.session_id, "continue", load_settings(tmp_path), SimpleNamespace(run_started=lambda: None))
    assert (status, session_id) == (0, store.session_id)
    assert observed == [True]
    assert not (tmp_path / ".code-squid").exists()


@pytest.mark.parametrize("mode,approved", [("guarded", True), ("always", False), ("never", True)])
def test_new_pdf_assets_are_readable_with_normal_approval_modes(tmp_path, mode, approved):
    pymupdf = pytest.importorskip("pymupdf")
    pdf = tmp_path / "example.pdf"
    document = pymupdf.open()
    document.new_page().insert_text((30, 30), "Private PDF page")
    document.save(pdf)
    document.close()
    run = make_run(tmp_path)
    result = run.loop.tool_executor.execute({"tool": "read_file", "args": {"path": str(pdf.resolve())}})
    assert result["ok"]
    rendered = result["rendered_pages"][0]["path"]
    assert Path(rendered).is_relative_to(run.session_store.assets_dir)
    assert not Path(rendered).is_relative_to(tmp_path)
    action = {"tool": "read_file", "args": {"path": rendered}}
    preflight = run.loop.action_preflight.check(action)
    assert ApprovalPolicy(mode).check(preflight.approval_action).approved is approved
    if approved:
        image = run.loop.tool_executor.execute(preflight.execution_action)
        assert image["ok"] and image["media_type"] == "image"
        assert run.session_store.load_asset(image["image"]["asset_id"])
    hook_check = run.loop.action_preflight.check(action, additional_approval_reason="hook review")
    assert not ApprovalPolicy("guarded").check(hook_check.approval_action).approved
    assert not (tmp_path / ".code-squid").exists()


def test_asset_exception_is_read_only_and_session_scoped(tmp_path):
    one, two = make_run(tmp_path / "one"), make_run(tmp_path / "two")
    own = one.session_store.assets_dir / "image.png"
    foreign = two.session_store.assets_dir / "image.png"
    for tool, path in [("write_file", own), ("apply_patch", own), ("read_file", foreign), ("read_file", settings_path())]:
        decision = one.loop.action_preflight.check({"tool": tool, "args": {"path": str(path)}})
        assert decision.approval_action.get("approval_reason")
        assert not ApprovalPolicy("guarded").check(decision.approval_action).approved
    custom = {"read_file": {"execute": lambda *args: None}}
    policy = SessionAssetPreflight(tmp_path, one.session_store.session_dir, custom)
    assert policy.check({"tool": "read_file", "args": {"path": str(own)}}).approval_action.get("approval_reason")


def test_symlinked_assets_and_storage_are_not_trusted(tmp_path):
    run = make_run(tmp_path / "project")
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        run.session_store.assets_dir.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Host does not permit directory symlinks")
    action = {"tool": "read_file", "args": {"path": str(run.session_store.assets_dir / "secret.png")}}
    assert run.loop.action_preflight.check(action).approval_action.get("approval_reason")
    state = workspace_state_dir(tmp_path / "other")
    (state / "sessions").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="symlinks"):
        workspace_sessions_dir(tmp_path / "other")

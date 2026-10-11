"""Exercise shipped Mod Builder resources through CLI selection and real Core.

These tests protect application discovery, workspace boundaries, and installed
resource layout. Model inference is unnecessary: deterministic tools and run
construction exercise the same loading paths the interactive CLI uses.
"""

from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import zipfile

import pytest

from code_squid import mods
from code_squid.agent_setup import build_coding_task_run
from code_squid.console.cli.mod_commands import _handle_mod_input, _format_mod_status
from code_squid.console.cli.skill_commands import _handle_skill_input, _format_skill_status
from code_squid.mod_authoring import scaffold_mod_package, scaffold_mod_component, validate_mod_package
from squid_core.mods import ModResolutionError
from squid_core.tools.user_tools import execute_user_tool, load_user_tool


EXAMPLES = ('skill-only', 'builtin-file-tools', 'bundled-tool', 'before-accept-final-hook', 'portable-tool-hook')
HELPERS = ('read-mod-authoring-guide', 'read-mod-authoring-example', 'scaffold-mod-package', 'scaffold-mod-component', 'validate-mod-package')
EXPECTED_TOOLS = ('read_file', 'write_file', 'apply_patch', 'run_command', *HELPERS)


def builder_dir():
    """Locate the packaged reference, independently of the current workspace."""
    return mods.bundled_mod_home() / 'mods/mod-builder'


def execute(name, workspace, args=None, directory=None):
    directory = directory or builder_dir()
    return execute_user_tool(load_user_tool(directory / 'tools' / name), workspace, args or {})


def test_cli_discovery_activation_and_skill_reset(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv('CODE_SQUID_HOME', str(tmp_path / 'home'))
    assert '(built-in)' in _format_mod_status(None)
    assert _handle_mod_input('/mod mod-builder', None, None) == ('mod-builder', 'mod-builder')
    assert 'Tools: read_file' in _format_skill_status('mod-builder', 'mod-builder')
    assert _handle_skill_input('/skill none', 'mod-builder', 'mod-builder') == ('mod-builder', 'mod-builder')
    assert _handle_skill_input('/skill absent', 'mod-builder', 'mod-builder') == ('mod-builder', 'mod-builder')
    assert _handle_mod_input('/mod none', 'mod-builder', 'mod-builder') == (None, None)
    assert not (tmp_path / 'home/mods/mod-builder').exists()
    resolved = mods.resolve_mod('mod-builder', tmp_path / 'home', workspace_root=tmp_path, session_id='builder-test')
    assert resolved.skill.name == 'mod-builder'
    assert tuple(resolved.tools) == EXPECTED_TOOLS
    assert not resolved.hooks
    assert resolved.tools['read-mod-authoring-guide']['execute'](tmp_path)['ok']


def test_application_run_uses_bundled_mod_and_retains_user_home(monkeypatch, tmp_path):
    # Build the actual run without asking any provider for a response.
    from code_squid.settings import load_settings
    home = tmp_path / 'home'
    monkeypatch.setenv('CODE_SQUID_SESSION_INDEXES', str(tmp_path / 'indexes.jsonl'))
    run = build_coding_task_run(tmp_path, 'create a Mod', app_home=home,
                                mod_name='mod-builder', settings=load_settings(tmp_path),
                                model_adapter=object())
    assert run.loop.agent.skill_name == 'mod-builder'
    assert tuple(run.loop.tool_executor.tools) == EXPECTED_TOOLS
    context = run.session_store.jsonl_path.read_text(encoding='utf-8')
    assert '"mod_id": "mod-builder"' in context
    assert not (home / 'mods/mod-builder').exists()


def test_user_mods_and_collision_remain_unchanged(monkeypatch, tmp_path):
    scaffold_mod_package(tmp_path, 'user-mod', 'User Mod')
    scaffold_mod_package(tmp_path, 'mod-builder', 'User collision')
    before = {str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    monkeypatch.setenv('CODE_SQUID_HOME', str(tmp_path))
    discovered = mods.discover_mods(tmp_path)
    assert set(discovered) == {'user-mod', 'mod-builder'}
    assert discovered['mod-builder'].path == builder_dir()
    assert mods.resolve_mod('user-mod', tmp_path).tools == {}
    assert 'shadowed and unchanged' in _format_mod_status(None)
    _handle_mod_input('/mod mod-builder', None, None)
    assert before == {str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}


def test_complete_guide_and_examples(tmp_path):
    guide = execute('read-mod-authoring-guide', tmp_path)
    assert guide['data']['guide'] == (builder_dir() / 'docs/mod-authoring.md').read_text(encoding='utf-8')
    for name in EXAMPLES:
        example = execute('read-mod-authoring-example', tmp_path, {'example': name})
        root = builder_dir() / 'docs/examples' / name
        expected = {str(p.relative_to(root)).replace('\\', '/'): p.read_text(encoding='utf-8')
                    for p in root.rglob('*') if p.is_file() and p.suffix in {'.py', '.md', '.yaml'}}
        assert example['ok'] and example['files'] == expected
        assert validate_mod_package(root.parent, name)['ok']
    assert not execute('read-mod-authoring-example', tmp_path, {'example': '../escape'})['ok']


def test_scaffolding_components_and_core_validation(tmp_path):
    assert execute('scaffold-mod-package', tmp_path, {'package_name': 'starter', 'description': 'Starter'})['path'] == 'mods/starter'
    for kind in ('tool', 'hook'):
        args = {'package_path': 'mods/starter', 'kind': kind, 'name': 'custom-' + kind}
        assert execute('scaffold-mod-component', tmp_path, args)['ok']
        assert not execute('scaffold-mod-component', tmp_path, args)['ok']
    assert execute('validate-mod-package', tmp_path, {'package_path': 'mods/starter'})['ok']
    assert not execute('scaffold-mod-package', tmp_path, {'package_name': 'starter', 'description': 'Overwrite'})['ok']
    with pytest.raises(ValueError, match='Protected built-in'):
        scaffold_mod_component(tmp_path, 'mods/starter', 'tool', 'read_file')
    skill = tmp_path / 'mods/starter/skills/starter/SKILL.md'
    skill.write_text(skill.read_text().replace('allowed-tools: []', 'allowed-tools: ["absent"]'), encoding='utf-8')
    assert not execute('validate-mod-package', tmp_path, {'package_path': 'mods/starter'})['ok']


@pytest.mark.parametrize('path', ['../escape', '..\\escape', '/tmp/escape', 'C:\\escape', 'C:escape'])
def test_workspace_containment(tmp_path, path):
    assert not execute('scaffold-mod-package', tmp_path, {'package_name': 'escape', 'description': 'Escape', 'destination': path})['ok']
    assert not execute('validate-mod-package', tmp_path, {'package_path': path})['ok']
    assert not execute('scaffold-mod-component', tmp_path, {'package_path': path, 'kind': 'hook', 'name': 'escape'})['ok']


def test_validation_never_imports_authored_source(tmp_path):
    shutil.copytree(builder_dir() / 'docs/examples/portable-tool-hook', tmp_path / 'draft')
    # Match Core's directory/manifest identity after copying the reference.
    package = tmp_path / 'portable-tool-hook'
    (tmp_path / 'draft').rename(package)
    for source in package.glob('*/*/*.py'):
        source.write_text("raise RuntimeError('must not import')\n" + source.read_text(), encoding='utf-8')
    assert validate_mod_package(tmp_path, package.name)['ok']
    (package / 'tools/count-text/tool.py').write_text('def broken(:', encoding='utf-8')
    assert any(e['code'] == 'python.compile' for e in validate_mod_package(tmp_path, package.name)['errors'])


@pytest.mark.parametrize('damage', ['manifest', 'guide', 'example', 'encoding'])
def test_missing_or_damaged_bundled_resources(monkeypatch, tmp_path, damage):
    home = tmp_path / 'resources'
    copied = home / 'mods/mod-builder'
    shutil.copytree(builder_dir(), copied)
    monkeypatch.setattr(mods, 'bundled_mod_home', lambda: home)
    if damage == 'manifest':
        (copied / 'mod.yaml').unlink()
        scaffold_mod_package(tmp_path / 'user', 'mod-builder', 'Collision')
        assert not mods.discover_mods(tmp_path / 'user')['mod-builder'].valid
        with pytest.raises(ModResolutionError):
            mods.resolve_mod('mod-builder', tmp_path / 'user')
    elif damage == 'guide':
        (copied / 'docs/mod-authoring.md').unlink()
        assert not execute('read-mod-authoring-guide', tmp_path, directory=copied)['ok']
    elif damage == 'example':
        (copied / 'docs/examples/bundled-tool/tools/echo-value/tool.py').unlink()
        assert not execute('read-mod-authoring-example', tmp_path, {'example': 'bundled-tool'}, copied)['ok']
    else:
        (copied / 'docs/mod-authoring.md').write_bytes(b'\xff')
        assert not execute('read-mod-authoring-guide', tmp_path, directory=copied)['ok']


def test_distribution_contains_complete_resource_tree(tmp_path):
    # Exercise the actual build declarations rather than matching their text.
    repo = Path(__file__).resolve().parents[1]
    subprocess.run([sys.executable, '-m', 'build', '--wheel', '--sdist', '--no-isolation',
                    '--outdir', str(tmp_path), str(repo)], check=True, capture_output=True, text=True)
    expected = {str(p.relative_to(repo)).replace('\\', '/') for p in builder_dir().rglob('*')
                if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc'}
    with zipfile.ZipFile(next(tmp_path.glob('*.whl'))) as wheel:
        assert not any('__pycache__' in name or name.endswith('.pyc') for name in wheel.namelist())
        assert expected <= set(wheel.namelist())
        for name in expected:
            assert wheel.read(name) == (repo / name).read_bytes()
    with tarfile.open(next(tmp_path.glob('*.tar.gz'))) as archive:
        members = {'/'.join(m.name.split('/')[1:]): m for m in archive.getmembers()}
        assert expected <= members.keys()
        for name in expected:
            assert archive.extractfile(members[name]).read() == (repo / name).read_bytes()

@pytest.mark.parametrize('name', ['scaffold-mod-package', 'scaffold-mod-component', 'validate-mod-package'])
def test_authoring_requires_explicit_execution_workspace(name, tmp_path):
    # Calling a dynamically loaded entrypoint without Core context must not
    # accidentally author into the application's current working directory.
    import importlib.util
    source = builder_dir() / 'tools' / name / 'tool.py'
    spec = importlib.util.spec_from_file_location('context_check', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert not module.run({})['ok']
    assert not module.run({}, {'workspace_root': ''})['ok']


def test_validation_rejects_linked_resources(tmp_path):
    package = tmp_path / 'bundled-tool'
    shutil.copytree(builder_dir() / 'docs/examples/bundled-tool', package)
    outside = tmp_path / 'outside'
    outside.mkdir()
    try:
        (package / 'external').symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip('Windows symlink creation requires developer mode or privileges')
    result = validate_mod_package(tmp_path, package.name)
    assert not result['ok']
    assert 'linked resources' in str(result)

"""Scaffold and validate multi-Skill Code Squid Mod packages.

This module owns deterministic, workspace-contained authoring helpers shared by
the built-in Mod Builder shipped by Code Squid. Core remains authoritative
for persisted Mod, Skill, Tool, and Hook contracts. This module coordinates
Core metadata validation with contained scaffolding and static authoring checks.
"""

from __future__ import annotations

import ast
import re
import shutil
import tempfile
from pathlib import Path, PurePosixPath, PureWindowsPath


BUILTIN_TOOL_NAMES = ("read_file", "write_file", "apply_patch", "run_command")
SAFE_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SAFE_COMPONENT_NAME = re.compile(r"^[a-z0-9_-]+$")


def _inside(workspace, candidate):
    # Reject both path dialects before host-native resolution. This also
    # prevents a Windows drive-relative path being interpreted as a new root.
    raw = str(candidate)
    if PureWindowsPath(raw).drive or PureWindowsPath(raw).root or PurePosixPath(raw).is_absolute():
        raise ValueError("Package path must stay inside the supplied workspace")
    root = Path(workspace).resolve()
    path = root.joinpath(*PurePosixPath(raw.replace("\\", "/")).parts).resolve()
    if path != root and root not in path.parents:
        raise ValueError("Package path must stay inside the supplied workspace")
    return root, path


def scaffold_mod_package(workspace, package_name, description, destination=None):
    """Create only the canonical, valid Skill-only starter package."""
    if not isinstance(package_name, str) or not SAFE_NAME.fullmatch(package_name):
        raise ValueError("Package name must use lowercase letters, numbers, and hyphens")
    description = " ".join(str(description or "").splitlines()).strip()
    if not description:
        raise ValueError("Description is required")
    # Omitted destination is the first-party Builder's normal CODE_SQUID_HOME
    # workflow. Keep that deterministic in this authoritative implementation;
    # callers request an intentional standalone layout by passing destination.
    package_destination = destination if destination is not None else Path("mods") / package_name
    root, package_dir = _inside(workspace, package_destination)
    if package_dir == root:
        raise ValueError("Package destination must be below the supplied workspace")
    if package_dir.name != package_name:
        raise ValueError("Package destination folder must match the package name")
    if package_dir.exists():
        raise ValueError("Package destination already exists")

    skill_dir = package_dir / "skills" / package_name
    skill_dir.mkdir(parents=True)
    (package_dir / "mod.yaml").write_text(
        "---\n"
        f"name: {package_name}\n"
        f"description: {description}\n"
        f"default_skill: {package_name}\n"
        "accent: cyan\n"
        "hooks: []\n"
        "---\n",
        encoding="utf-8",
    )
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        f"name: {package_name}\n"
        f"description: {description}\n"
        "allowed-tools: []\n"
        "---\n\n"
        "# Instructions\n\n"
        "Replace this sentence with the Mod's domain-specific instructions.\n",
        encoding="utf-8",
    )
    return {
        "ok": True,
        "package": package_name,
        "path": str(package_dir.relative_to(root)).replace("\\", "/"),
        "files": ["mod.yaml", f"skills/{package_name}/SKILL.md"],
    }


def scaffold_mod_component(workspace, package_path, kind, name):
    """Create an empty canonical Tool or Hook component without domain logic."""
    if kind not in {"tool", "hook"}:
        raise ValueError("Component kind must be tool or hook")
    if not isinstance(name, str) or not SAFE_COMPONENT_NAME.fullmatch(name):
        raise ValueError("Component name must use lowercase letters, numbers, underscores, and hyphens")
    root, package_dir = _inside(workspace, package_path)
    if not (package_dir / "mod.yaml").is_file():
        raise ValueError("Package path must contain mod.yaml")
    if kind == "tool" and name in BUILTIN_TOOL_NAMES:
        raise ValueError("Protected built-in Tools must not be bundled")
    # Validate the resolved component path too: a hand-authored tools/hooks
    # directory may link elsewhere even when the package itself is contained.
    _, component_dir = _inside(root, package_dir.relative_to(root) / f"{kind}s" / name)
    if component_dir.exists():
        raise ValueError("Component destination already exists")
    component_dir.mkdir(parents=True)
    if kind == "tool":
        files = {
            "tool.yaml": f'name: {name}\ndescription: Replace with a precise callable capability description.\nversion: "1"\nentrypoint: tool.py\nfunction: run\nargs: {{}}\n',
            "tool.py": '\"\"\"Own the custom Tool behavior; permissions remain in each SKILL.md.\"\"\"\n\ndef run(args, context=None):\n    raise NotImplementedError("Replace with the requested Tool behavior")\n',
        }
    else:
        files = {
            "hook.yaml": f"name: {name}\ndescription: Replace with the automatic lifecycle behavior.\nenabled: false\nversion: 1\n",
            "hook.py": '\"\"\"Own one documented lifecycle behavior; selection remains in mod.yaml.\"\"\"\n\nclass GeneratedHook:\n    pass\n\ndef create_hook(config=None):\n    return GeneratedHook()\n',
        }
    for filename, content in files.items():
        (component_dir / filename).write_text(content, encoding="utf-8")
    relative = component_dir.relative_to(root)
    return {"ok": True, "kind": kind, "name": name, "path": str(relative).replace("\\", "/"), "files": [str(relative / filename).replace("\\", "/") for filename in files]}


def _error(errors, code, package_dir, path, message, line=None):
    try:
        display = str(Path(path).resolve().relative_to(package_dir.resolve())).replace("\\", "/")
    except (OSError, ValueError):
        display = Path(path).name
    item = {"file": display, "code": code, "message": str(message).replace(str(package_dir), "<package>")}
    if line is not None:
        item["line"] = int(line)
    errors.append(item)


def _line_from_error(message):
    match = re.search(r":(\d+)(?::|\b)", str(message))
    return int(match.group(1)) if match else None


def _portable_path_violations(package_dir):
    violations = []
    for path in sorted(p for p in package_dir.rglob("*") if p.is_file()):
        if any(part in {".pytest_cache", "__pycache__"} for part in path.parts) or path.suffix.lower() == ".pyc":
            continue
        if path.suffix.lower() not in {".py", ".md", ".yaml", ".yml", ".json", ".txt"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for number, line in enumerate(text.splitlines(), 1):
            # A drive token must begin at a path boundary. Without this guard,
            # the trailing "s://" in an HTTPS URL looks like a drive path.
            tokens = re.findall(r"(?<![A-Za-z0-9+.-])(?:[A-Za-z]:[\\/][^\s'\"`]+|/(?:Users|home)/[^\s'\"`]+)", line)
            for token in tokens:
                if "..." in token:
                    continue
                # Pure path parsing keeps this check deterministic on every host OS.
                if PureWindowsPath(token).is_absolute() or PurePosixPath(token).is_absolute():
                    violations.append((path, number, token))
    return violations


def _copy_contained_tree(root, source, destination):
    """Stage metadata/resources without following links outside authoring scope."""
    pending = [source]
    while pending:
        path = pending.pop()
        resolved = path.resolve()
        if resolved != root and root not in resolved.parents:
            raise ValueError("Package resources must stay inside the supplied workspace")
        # Check before enumerating children: junctions can otherwise expose
        # outside directory names even before copytree begins reading files.
        if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
            raise ValueError("Authoring validation does not follow linked resources")
        if path.is_dir():
            pending.extend(path.iterdir())
    shutil.copytree(source, destination)


def validate_mod_package(workspace, package_path="."):
    """Use Core metadata validation, then static checks; never import user code.

    Core's public loader requires <home>/mods/<name>. A temporary, contained
    snapshot adapts standalone drafts to that layout without another manifest
    parser or process-wide CODE_SQUID_HOME mutation. Shared inventories come
    only from the explicitly supplied workspace/application home.
    """
    from squid_core.mods import load_mod

    root, package_dir = _inside(workspace, package_path)
    errors = []
    manifest_path = package_dir / "mod.yaml"
    if not manifest_path.is_file():
        _error(errors, "manifest.missing", package_dir, manifest_path, "Missing mod.yaml")
        return {"ok": False, "package_path": str(package_dir.relative_to(root)), "errors": errors}
    proposal = None
    mod = {"name": package_dir.name}
    try:
        with tempfile.TemporaryDirectory(prefix="squid-mod-validation-") as staging:
            home = Path(staging)
            staged_package = home / "mods" / package_dir.name
            _copy_contained_tree(root, package_dir, staged_package)
            # A root-level package has no separate shared inventory. For any
            # other layout the supplied root is the explicit authoring home.
            if package_dir != root:
                for kind in ("tools", "hooks"):
                    shared = root / kind
                    if shared.is_dir():
                        _copy_contained_tree(root, shared, home / kind)
            metadata = load_mod(package_dir.name, home)
            tool_references = {tool for skill in metadata.skills.values() for tool in skill.allowed_tools}
            mod = {"name": metadata.name, "hooks": list(metadata.hooks)}
            for message in metadata.errors:
                message = message.replace(str(staged_package), "<package>").replace(str(home), "<authoring-home>")
                _error(errors, "core.mod.invalid", package_dir, manifest_path, message, _line_from_error(message))
            # Only inspect declared component paths after Core accepts their
            # identifiers. Invalid Skill ids, permissions, or hook ids may contain paths.
            if metadata.valid:
                shared = any(name not in BUILTIN_TOOL_NAMES and not (package_dir / "tools" / name).is_dir() for name in tool_references)
                shared = shared or any(not (package_dir / "hooks" / name).is_dir() for name in metadata.hooks)
                proposal = {"state": "uses_shared" if shared else "portable"}
    except Exception as exc:
        message = str(exc).replace(str(root), "<workspace>")
        if "staging" in locals():
            message = message.replace(str(staging), "<authoring-home>")
        _error(errors, "core.mod.invalid", package_dir, manifest_path, message)
        # Do not read any package resources after containment/staging failed.
        return {"ok": False, "package": package_dir.name, "package_path": str(package_dir.relative_to(root)).replace("\\", "/") or ".", "state": "invalid", "errors": errors}

    try:
        from squid_core.tools.user_tools import load_user_tool
        for tool_dir in sorted((package_dir / "tools").iterdir()) if (package_dir / "tools").is_dir() else []:
            if not tool_dir.is_dir():
                continue
            metadata_path = tool_dir / "tool.yaml"
            if tool_dir.name in BUILTIN_TOOL_NAMES:
                _error(errors, "tool.builtin_protected", package_dir, metadata_path, f"Protected built-in Tool {tool_dir.name!r} must not be bundled")
            text = metadata_path.read_text(encoding="utf-8") if metadata_path.is_file() else ""
            if any(line.strip() == "---" for line in text.splitlines()):
                _error(errors, "tool.frontmatter_forbidden", package_dir, metadata_path, "tool.yaml must not use --- delimiters")
                continue
            for number, line in enumerate(text.splitlines(), 1):
                if line.lstrip().startswith("- "):
                    _error(errors, "tool.list_forbidden", package_dir, metadata_path, "tool.yaml does not support YAML list syntax", number)
            if re.search(r"(?m)^args:\s*$[\s\S]*?^  (?:type:\s*object|properties:|required:)", text):
                _error(
                    errors,
                    "tool.args.schema_shape",
                    package_dir,
                    metadata_path,
                    "args must directly map argument names; top-level JSON Schema type/properties/required is not supported",
                )
            try:
                info = load_user_tool(tool_dir, source="mod", editable=False)
                if info is None:
                    raise ValueError("Missing tool.yaml")
                source_path = tool_dir / info.entrypoint
                tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
                if not any(isinstance(node, ast.FunctionDef) and node.name == info.function for node in tree.body):
                    raise ValueError(f"Declared function {info.function!r} was not found")
            except SyntaxError as exc:
                _error(errors, "python.compile", package_dir, tool_dir / "tool.py", exc.msg, exc.lineno)
            except Exception as exc:
                code = "tool.args.schema_shape" if "top-level JSON Schema" in str(exc) else "tool.invalid"
                _error(errors, code, package_dir, metadata_path, exc, _line_from_error(exc))
    except ImportError as exc:
        _error(errors, "runtime.unavailable", package_dir, manifest_path, exc)

    # Inspect every bundled component, including unselected authoring drafts.
    # Syntax/factory checks do not execute create_hook or lifecycle handlers;
    # behavior and return types belong in explicit package-owned tests.
    from squid_core.hooks import read_hook_info
    hooks_root = package_dir / "hooks"
    for hook_dir in sorted(hooks_root.iterdir()) if hooks_root.is_dir() else []:
        if not hook_dir.is_dir():
            continue
        metadata_path = hook_dir / "hook.yaml"
        source_path = hook_dir / "hook.py"
        try:
            info = read_hook_info(hook_dir)
            if info.name != hook_dir.name:
                raise ValueError("Hook name must match its folder name")
            tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
            if not any(isinstance(node, ast.FunctionDef) and node.name == "create_hook" for node in tree.body):
                raise ValueError("Expected a top-level create_hook function in the authored Hook")
        except SyntaxError as exc:
            _error(errors, "python.compile", package_dir, source_path, exc.msg, exc.lineno)
        except Exception as exc:
            _error(errors, "hook.invalid", package_dir, metadata_path, exc, _line_from_error(exc))

    for path, line, token in _portable_path_violations(package_dir):
        _error(errors, "portability.absolute_path", package_dir, path, f"Machine-specific absolute path is not portable: {token}", line)

    return {
        "ok": not errors,
        "package": mod["name"],
        "package_path": str(package_dir.relative_to(root)).replace("\\", "/") or ".",
        "state": proposal.get("state") if proposal and not errors else "invalid",
        "errors": errors,
    }

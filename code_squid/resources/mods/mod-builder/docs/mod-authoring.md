# Code Squid Mod authoring contract

This is the authoritative bundled authoring guide for the multi-Skill Mod package. It is written for agents and humans. Use the runtime-backed `validate-mod-package` Tool before considering a package complete; generic YAML parsers and JSON Schema conventions are not substitutes for Code Squid's loaders.

## 1. Create the package

A user package lives at `CODE_SQUID_HOME/mods/<package-name>/`. A portable package has this exact shape (the component folders are optional):

```text
<package-name>/
  mod.yaml
  skills/<skill-id>/SKILL.md  (one or more direct children)
  tools/<tool-name>/tool.yaml
  tools/<tool-name>/tool.py
  hooks/<hook-name>/hook.yaml
  hooks/<hook-name>/hook.py
```

Mod names and default Skill identifiers use lowercase letters and numbers separated by single hyphens (no leading, trailing, or repeated hyphens). Tool names use lowercase letters, numbers, underscores, and hyphens. The package directory must match `mod.yaml` `name`. Every Mod must bundle at least one Skill. Load each direct `skills/<skill-id>/SKILL.md`; its frontmatter `name` must match its directory. `default_skill` must name one of these local Skills. Standalone Skills never serve as fallback candidates. Skill names may repeat across different Mods. The Mod name and default Skill identifier need not be equal.

The first-party Builder must call `read-mod-authoring-guide` to obtain this packaged document without leaving the supplied workspace for arbitrary files. It must use `read-mod-authoring-example` for the allowlisted examples below and must not search the workspace for them. For a new package, call `scaffold-mod-package` with `package_name` and `description`; in the normal Builder workspace it deterministically creates `mods/<package-name>`. An explicit workspace-relative `destination` intentionally requests a standalone layout. The helper creates only `mod.yaml` and a Skill placeholder. Use `scaffold-mod-component` before writing a custom Tool or Hook so its canonical folder and files exist; the skeleton deliberately contains no domain behavior.

## 2. Write `mod.yaml`

`mod.yaml` uses an opening and closing `---` delimiter. It supports exactly `name`, `description`, `default_skill`, `accent`, and `hooks`. Accent defaults to `cyan` and accepts `cyan`, `blue`, `green`, `yellow`, `orange`, `red`, `pink`, `purple`, `white`, or `gray`:

```yaml
---
name: example-mod
description: A useful one-line description.
default_skill: example-skill
accent: cyan
hooks: []
---
```

Use `hooks: []` for no hooks. Hook lists are ordered and must not contain duplicates; they apply Mod-wide. Core also accepts JSON inline string lists. `mod.yaml` has no `tools` field: declare permissions separately in every Skill. Duplicate manifest fields and non-empty text after the closing delimiter are invalid.

## 3. Write `SKILL.md`

`SKILL.md` also uses opening and closing `---` frontmatter delimiters. Frontmatter requires non-empty scalar `name` and `description`, plus explicit `allowed-tools`:

```markdown
---
name: example-skill
description: A useful one-line description.
allowed-tools:
  - read_file
---

# Instructions

Read the relevant workspace file and answer the user's question.
```

Use `allowed-tools: []` when no Tools are needed. Instructions start after the closing delimiter. Each Skill declares its own unique allowed Tool names; two Skills within a Mod may use different permissions. Exactly one Skill is active. The union of references across all Skills is dependency validation metadata only, never runtime permissions. Explicitly select every built-in needed by the workflow; mentioning a Tool in prose does not select it.

Skill prompt customization uses body headings `## AGENT_IDENTITY append`, `## TOOL_USAGE_GUIDANCE replace`, or `## FINAL_SUMMARY_REQUIREMENTS append`; each of these three sections supports `append` and `replace`. Content after an override heading belongs to that section until the next override heading. Put ordinary instructions before overrides. Other prompt sections are not customizable. No additional frontmatter is needed for prompt customization.

## 4. Select or bundle components

The built-in Tool names are `read_file`, `write_file`, `apply_patch`, and `run_command`.

- Select `read_file` when the Skill must inspect workspace files.
- Select `write_file` when it must create a file or intentionally replace a complete small file.
- Select `apply_patch` when it must make focused changes to existing text files.
- Select `run_command` when it must run tests, compilers, version-control inspection, or other workspace commands.

These selections describe the generated Mod at runtime. The Mod Builder may use `run_command` to author and test a package without adding it to the generated Mod. Do not carry build-time Tools into `allowed-tools` unless the finished workflow actually calls them.

Built-ins resolve without a bundled folder. Their names are protected: never add a same-named folder under `tools/` and never try to replace them.

A folder makes a custom component available; the active Skill?s `allowed-tools` selects Tools and the Mod?s `hooks` selects Hooks for a run. Selected custom Tools and Hooks resolve from a bundled folder first, then (only if that folder is absent) from the shared `CODE_SQUID_HOME/tools` or `CODE_SQUID_HOME/hooks` inventory. An unselected bundled component stays inactive and should be preserved during unrelated edits. Invalid bundled metadata fails validation; it does not fall back to a shared namesake. A package that uses shared components is not portable. For portability, copy the entire component directory into the corresponding package folder and validate it. Do not edit the shared original for a package-only change.

## 5. Write a custom Tool

`tool.yaml` is a plain mapping. It **must not** use `---` delimiters and **must not** use YAML list syntax. The current authoring fields are:

- `name` (required string; must match the folder)
- `description` (optional string)
- `version` (optional string)
- `entrypoint` (optional safe filename, default `tool.py`)
- `function` (optional Python identifier, default `run`)
- `args` (optional mapping)
- `safety` (optional mapping consumed by approval policy)

Arguments are flattened directly below `args`; each value is its model property mapping:

```yaml
name: echo-value
description: Echo one value.
version: "1"
entrypoint: tool.py
function: run
args:
  value:
    type: string
    description: Value to echo.
    required: true
  prefix:
    type: string
    description: Optional prefix.
```

Put `required: true` inside every argument that must be required. Core removes this flag from the property and adds that argument name to the generated model definition's `required` list. Omitting it makes the argument optional. Do not put `type: object`, `properties:`, or a top-level `required:` list below `args`; that JSON Schema-shaped form is invalid.

Tool metadata browsing and registry construction do not import Python. Core imports the declared source file on each execution with a generated module name, then calls the declared callable as `function(args, context=context)`. Use a synchronous `run(args, context=None)` (or the declared function name); do not rely on package-relative imports, automatic sibling-module search, or persistent module globals. Standard-library modules and shipped public `squid_core` APIs are available; arbitrary third-party dependencies are not guaranteed. Metadata loading alone does not verify source existence or callable behavior. The authoring helper statically verifies a top-level declared function and syntax; explicit tests must verify the callable and argument behavior.

 Context contains `workspace_root`, `tool_name`, and optionally `session_id`. Validate inputs and return a browser-safe string or dictionary such as `{"ok": true, "message": "Done", "data": {}}`. Do not expose secrets or return unserializable objects.

For user paths, reject POSIX and Windows absolute forms before joining. Treat both `/` and `\\` as separators on every host, resolve the candidate against `Path(context["workspace_root"]).resolve()`, and require the resolved root to equal the candidate or appear in `candidate.parents`. Never rely only on `".." in path.split(os.sep)` or string-prefix containment: both fail for mixed separators or sibling prefixes such as `C:\\foo` and `C:\\foobar`. Tests should independently cover `../escape`, `..\\escape`, POSIX absolute paths, Windows absolute paths, and sibling-prefix containment regardless of the test host.

```python
from pathlib import Path, PurePosixPath, PureWindowsPath

def contained_path(workspace_root, user_path):
    raw = str(user_path)
    if PurePosixPath(raw).is_absolute() or PureWindowsPath(raw).is_absolute() or PureWindowsPath(raw).drive or PureWindowsPath(raw).root:
        raise ValueError("Absolute paths are not allowed")
    # Normalize both user-facing separators before host-native resolution.
    relative = PurePosixPath(raw.replace("\\", "/"))
    root = Path(workspace_root).resolve()
    candidate = root.joinpath(*relative.parts).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError("Path must stay inside the workspace")
    return candidate
```

Keep precise assertions in its tests, for example separate cases asserting that each of `../escape`, `..\\escape`, `/tmp/escape`, and `C:\\escape` is rejected. Also test containment itself (not a string prefix) so a workspace named `C:\\foo` cannot authorize `C:\\foobar`. Do not replace a meaningful error/message assertion with a second spelling of the same boolean assertion merely to make a failure disappear; fix the implementation when the requested contract specifies that behavior.

For starter-project generators, `overwrite` or `refresh` should replace only known managed starter files and preserve unrelated user files and directories. Never implement ordinary overwrite by recursively deleting the existing directory. Recursive deletion requires an explicit user contract that the entire directory is destructive and replaceable.

## 6. Write a Hook

`hook.yaml` is also a plain mapping with **no** `---` delimiters and **no** YAML list syntax. Supported fields are required string `name`, optional string `description`, optional boolean `enabled`, and optional integer `version`. The name must match its folder. Normally use `enabled: false`; selecting the Hook in a Mod enables it for that run. Lifecycle methods are defined in Python source, not `hook.yaml`. These are the recommended authoring fields; Core currently ignores unknown Tool/Hook metadata keys, but they do not create new runtime capabilities. Hook metadata loading checks for `hook.py` without importing it.

`hook.py` must expose callable `create_hook(config=None)` and return an object. No base class is required: Core calls methods present on that object. Config is the metadata dictionary (`name`, `description`, `enabled`, `version`, `source`); Mod selection forces `enabled` true. A no-argument factory is also supported. The authoring helper recommends a top-level synchronous factory. Selected Hooks are imported only at runtime resolution or in explicit behavioral tests. These are supported lifecycle methods from `squid_core.hooks`; effect methods return `HookResponse(...)` or `None`, and notification methods return `None`:

| Method | Context fields | Supported return |
| --- | --- | --- |
| `before_run` | `BeforeRunContext(session_id, workspace_root, task, skill_name, allowed_tools)` | `HookResponse(block=..., reason=..., guidance=..., context_blocks=...)` or `None` |
| `before_model_turn` | `BeforeModelTurnContext(session_id, workspace_root, task, messages, tool_steps_used)` | `HookResponse(context_blocks=...)` or `None` |
| `before_tool_execute` | `BeforeToolExecuteContext(session_id, workspace_root, action, tool_steps_used)` | `HookResponse(block=..., reason=..., guidance=..., action=..., approval_reason=...)` or `None` |
| `tool_result` | `ToolResultContext(session_id, workspace_root, action, result)` | `HookResponse(updated_tool_output=..., additional_context=...)` or `None` |
| `before_accept_final` | `BeforeAcceptFinalContext(session_id, workspace_root, message, content, files_read, files_written, tool_steps_used)` | `HookResponse(block=..., reason=..., guidance=..., report_note=...)` or `None` |
| `run_finished` | `RunFinishedContext(session_id, workspace_root, status, reason, final_message, files_read, files_written, tool_steps_used)` | `HookResponse(follow_up_requests=..., notes=...)` or `None` |
| `compaction_applied` | `CompactionAppliedContext(session_id, workspace_root)` | Notification; return `None` |
| `read_result_trimmed` | `ReadResultTrimmedContext(tool_call_id, path, retained_line_ranges)` | Notification; return `None` |

`PromptContextBlock(title, body, source)` supplies prompt context. A run-finished `HookResponse` may contain `FollowUpRunRequest(task, reason, context_blocks, require_user_approval)` values. Implement only the lifecycle needed and return only its supported shape. `context_blocks` apply at `before_run` and `before_model_turn`; `tool_result.additional_context` adds model-visible guidance after the Tool result, while `updated_tool_output` replaces the result. Use a nudge as additional context, not as a fake Tool output or a report note. `report_note` is accumulated at final acceptance; `run_finished.notes` are completion notes. Blocking at `before_accept_final` supplies guidance for another model turn; `before_run` and `before_tool_execute` also support blocking. Fields for another seam do not gain effects merely by being present. Follow-up requests are host-facing requests, not a guarantee that Desktop schedules another run. Notification methods can clear cached read/verification state after compaction or trimming; their return values are ignored.

Import contexts and `HookResponse` directly from `squid_core.hooks`. For example, the complete minimal final Hook pattern is:

```python
from squid_core.hooks import HookResponse

class FinalNoteHook:
    def before_accept_final(self, context):
        return HookResponse(report_note="Completed by this Mod.")

def create_hook(config=None):
    return FinalNoteHook()
```

Do not define local replacement response classes or return namedtuple, dataclass, dictionary, or duck-typed lookalikes. The runtime does not inject `HookResponse` into generated Hook modules. Return the public `squid_core.hooks.HookResponse` type; the metadata validator never imports or invokes authored Hooks. Explicit behavioral tests should load selected Hooks with `load_hook_infos` and assert real response types and effects using `HookRunner`. An inert fabricated context cannot prove every domain Hook works.

## 7. Keep the package contained and portable

All authored files and test fixtures must remain under the supplied workspace. Tool runtime paths must derive from `context["workspace_root"]`. Never embed developer-machine paths such as `C:\Users\name\...` or `/home/name/...` in package files or tests. Avoid dependencies on loose shared components when the user requires portability. Do not inspect development source outside the workspace; if this document, examples, and validator do not expose required contract information, report it as unavailable.

Core owns persisted Mod parsing and validation via `squid_core.mods.load_mod` / `validate_mod`, and runtime resolution via `resolve_mod`. The application builder selects ordinary user Mods with `mod_name` and an explicit `app_home`; do not combine that selection with `skill_name` or resolved components. Desktop owns unsaved draft UX and special loading of its bundled first-party resources. `validate-mod-package` stages a workspace-contained snapshot into Core's app-home layout, without changing process settings or importing authored source. This also supports standalone drafts. Shared inventories are read only from the supplied workspace root. The installed helper and bundled documents are sufficient; do not run repository test helpers, inspect application source, or assume a Python executable/pytest is installed. If a test runner is available, run package-owned tests within the workspace; otherwise report behavioral tests as unrun.

## 8. Verify in this exact order

1. Confirm the directory shape and workspace containment (linked resources are rejected).
2. Run `validate-mod-package`: Core parses the manifest and every packaged Skill, checks the local default and each Skill?s permissions, then validates selected component metadata with bundled-before-shared precedence and protected built-ins.
3. The helper additionally inspects all bundled metadata, statically checks Python syntax and top-level Tool functions/Hook factories, and checks text for machine-specific paths. It never imports authored modules or invokes Hooks.
4. Run focused, explicit behavioral tests for custom logic in the supplied workspace when an appropriate runner is available. Verify Hook imports, factory, real `HookResponse` types, and lifecycle effects here.
5. Run `validate-mod-package` again and finalize only when `ok` is true. Report metadata/static validation separately from actual execution tests.

## Canonical examples

Complete machine-loaded copies are owned by this first-party package and available only through `read-mod-authoring-example`. They contain no developer paths. Read `bundled-tool` or `portable-tool-hook` before writing a Tool, and read `before-accept-final-hook` or `portable-tool-hook` before writing a Hook.

- `examples/skill-only`: Skill-only Mod (`allowed-tools: []` in its Skill and `hooks: []` in its manifest).
- `examples/builtin-file-tools`: selects `read_file`, `write_file`, and `apply_patch` in identical order without bundling them.
- `examples/bundled-tool`: bundles and selects `echo-value`; its required `value` and optional `prefix` demonstrate flattened args.
- `examples/before-accept-final-hook`: bundles and selects a Hook returning `HookResponse` from `before_accept_final`.
- `examples/portable-tool-hook`: portable package containing and selecting both a custom Tool and Hook.

These directories are the canonical complete examples; copy the relevant shape, not generic YAML remembered from another system.

## Common invalid forms and validator errors

| Invalid form | Expected code |
| --- | --- |
| Invalid manifest, default Skill, Tool selection/order, or selected component | `core.mod.invalid` |
| Missing manifest | `manifest.missing` |
| `---` in `tool.yaml` | `tool.frontmatter_forbidden` |
| `- item` list syntax in YAML `tool.yaml` | `tool.list_forbidden` |
| JSON Schema-shaped `args` | `tool.args.schema_shape` |
| Invalid Tool metadata/entrypoint/static function | `tool.invalid` |
| Invalid Hook metadata or static factory | `hook.invalid` |
| Python syntax error | `python.compile` |
| Machine-specific package/test path | `portability.absolute_path` |

Tool metadata can also be a JSON object in `tool.yaml`, including nested property lists. The limited YAML parser does not support block lists. `hook.yaml` uses flat scalar lines. `safety` metadata informs approval policy; it does not grant filesystem access or bypass workspace enforcement.

Each error is browser-safe and includes `file`, `code`, `message`, and `line` when the originating parser supplies one.

## Package preservation

When saving, renaming, or copying a Mod, preserve all packaged Skills, bundled Tool/Hook directories, prompt override modes/content, and unedited resources. Mod rename changes only package identity. Skill rename is scoped to its owning Mod, preserves the entire Skill directory, and updates `default_skill` when needed. A Copy as New Mod clones the whole package before changing identity. Standalone Skill rename/delete never mutates a same-named Mod.

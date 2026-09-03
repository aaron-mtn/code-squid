# Code Squid Architecture

## Purpose

Code Squid is a minimal standalone coding agent for repository work.

It runs interactive coding tasks from the command line, sends a replayable
transcript to a model provider, accepts model tool calls, executes a small local
tool set, persists the session, and keeps looping until the Core Agent policy
accepts a final assistant message.

The codebase is intentionally narrow. It is not a general agent framework, a
multi-agent system, a hardened sandbox, or a polished TUI. The main value of the
architecture is that the loop, contracts, storage, configuration, and tool
boundaries are small enough to inspect directly.

The construction and runtime shape is:

```text
Code Squid host/app -> Code Squid application runner -> Squid Core spawner
-> AgentLoop
settings -> provider -> model adapter -> Core Agent -> action preflight -> approval -> tools -> transcript/session storage
```

`AgentLoop -> on_event callback` is an optional observer path for compact
machine-readable runtime facts.

`.code-squid/` is local runtime state and should be gitignored.

The dependency direction is one-way: Code Squid supplies application defaults
and runtime wiring to reusable Squid Core components. Those reusable components
do not import Code Squid prompt or policy modules. `code_squid/` is the product
and application layer; `squid_core/` is the reusable agent runtime.

## Component Layout

- `main.py`
  - Thin standalone process entry point.
  - Calls `code_squid.console.cli.cli_commands.run_cli(sys.argv[1:])` and exits
    with its status code.

- `code_squid/`
  - Code Squid-specific product and application package. It owns coding-agent
    prompt/behavior policy, application setup, paths/settings, and console
    behavior and presentation.
  - `agent/coding.py` keeps the explicit `CodingAgent` specialization point
    around `squid_core.agent.Agent`; it intentionally adds no behavior today.
    `agent/prompts.py` owns Code Squid identity, its non-replaceable baseline
    coding policy, intentionally replaceable tool/final-report defaults, and
    dead/non-live task/follow-up compatibility renderers.
  - `agent_setup.py` owns Code Squid run preparation and wiring: settings,
    prompt defaults, application/workspace paths, storage locations, resource
    resolution, hooks, terminal display construction, platform context, Agent
    configuration, and translation into the generic `squid_core.spawner` seam.
  - `app_paths.py` owns Code Squid application-home policy, repository-local
    session/undo/error-log locations, the global session-index location, and
    paths for loose resources and Mods. Reusable Core machinery receives these
    paths explicitly.
  - `settings.py` reads `.code-squid/settings.json`, validates supported
    application input, applies product defaults and optional `CODE_SQUID_*`
    environment overrides, and translates the result to generic Core settings.
  - `console/cli/` owns terminal workflow and control. `cli_options.py` handles
    CLI options and workspace resolution; `cli_commands.py` handles launch-time
    dispatch; `prompt_loop.py` handles interactive prompts and slash commands;
    `session_runner.py` handles new/resumed session-backed runs; and
    `skill_commands.py` handles Skill status, listing, and selection.
  - `console/ui/` owns terminal presentation and input. `display.py` keeps the
    current display, formatting, approvals, action/report rendering, and error
    presentation together; `prompt_input.py`, `sessions.py`, and `spinner.py`
    retain their focused input, saved-session, and animation responsibilities.

- `squid_core/agent/`
  - Reusable Core Agent behavior and protected prompt protocol.
  - `agent.py` owns task and active-Skill state, `skill_name`, active tools,
    platform/workspace context, raw initial and follow-up message construction,
    tool definitions, reply validation, completion detection, reason-specific
    corrections, and repeated-invalid-reply failure construction.
  - `prompts.py` owns protected one-tool/final-response protocol, strong but
    non-enforced narration guidance, generic response examples, active-Skill
    insertion, execution-environment insertion, and prompt assembly.
  - Core consumes application defaults through `PromptDefaults` and does not
    import `code_squid.agent.prompts`.

- `squid_core/compaction/`
  - Generic transcript compaction mechanics and prompt ownership.
  - `compactor.py` owns trigger, chunking, summary, and retention behavior and
    is exposed as `squid_core.compaction.Compactor`.
  - `prompts.py` asks for continuation-critical task, finding, resource,
    action, result, verification, correction, next-step, and risk context
    without Code Squid identity or coding-only language.

- `squid_core/mods/`
  - Mod metadata, validation, discovery, and runtime composition.
  - Exposes `Mod`, `ResolvedMod`, `discover_mods`, `load_mod`, `validate_mod`,
    and `resolve_mod` from `squid_core.mods`.

- `squid_core/tools/`
  - Complete Tool subsystem: execution, result formatting, saved Tool metadata,
    and the built-in registry and implementations under `builtins/`.
  - Exposes `ToolExecutor` and `ToolResults` from `squid_core.tools`; the static
    built-in registry is available as `squid_core.tools.builtins.TOOLS`.

- `squid_core/storage/`
  - Generic durable persistence, discovery, and diagnostic mechanics with no
    Code Squid path policy.
  - `session_store.py` owns one explicitly located session directory,
    `metadata.json`, append-only `session.jsonl`, replay loading, status updates,
    compaction/run-context events, and model-reply/rejection diagnostics.
  - `undo_store.py` owns the explicitly located latest-only undo buffer.
  - `atomic_json.py` owns small same-directory atomic JSON replacement.
  - `session_index.py` owns generic inspection plus cross-location registration
    and discovery using explicit index and session-root paths.
  - `error_log.py` writes timestamped traceback-only diagnostics to an explicit
    log path.

- `squid_core/hooks/`
  - Hook lifecycle contexts and decisions, `HookRunner`, and Hook metadata,
    discovery, and loading.
  - Hooks participate in runtime decisions; flat `squid_core/events.py` only
    observes runtime facts.

- `squid_core/safety/`
  - Tool-action preflight, approval policy, guarded-command classification, and
    structured file-tool workspace boundaries.
  - This is an approval/preflight boundary, not a hardened sandbox.

- `squid_core/spawner.py`
  - Generic, UI-neutral construction for `AgentRun` and `AgentLoop`.
  - Creates ordinary runtime collaborators when omitted and accepts selected
    collaborators directly when an embedding application replaces them.
  - Consumes only generic `squid_core.settings.RuntimeSettings`; it does not
    import Code Squid configuration, prompts, terminal presentation, or
    resource/Mod discovery.

- `squid_core/providers/`
  - Core-owned provider contract and first-party provider transports.
  - `openai_compatible.py` owns OpenAI-compatible chat-completions transport,
    including OpenRouter request quirks already supported by that path.
  - `ollama.py` owns native Ollama `/api/chat` transport and response adaptation.
  - `__init__.py` contains the small built-in construction helper and backend
    replay choice. It consumes effective `ProviderSettings` and has no Code
    Squid defaults, settings loading, environment, or presentation policy.
  - These built-ins are first-party conveniences, not permanent dependencies:
    callers can pass a custom provider or ready `ModelAdapter` through the
    spawner, or construct `AgentLoop` directly.

- Flat `squid_core/*.py` runtime concepts
  - `agent_loop.py` owns orchestration; `events.py` owns observation;
    `generation.py` owns one-shot generation; `model_adapter.py` owns provider
    normalization; `settings.py` owns generic provider/runtime/compaction
    semantics; `platform_context.py` describes the environment;
    `spawner.py` owns generic construction; `session.py` owns in-memory
    transcript state; `skills.py` owns standalone Skills; and
    `token_estimate.py` owns token estimation.
  - Existing `context_status.py` remains flat pending the remaining ownership
    audit; Patch 5B does not create another subsystem for it.
  - Resource modules accept explicit application homes or resource roots. They
    do not import Code Squid's application-home policy.

- `scripts/`
  - Small repo-maintenance helpers.
  - `update_filetree.py` generates `docs/filetree.md` from the current
    repository tree and Python docstrings.

- `tests/`
  - Focused pytest coverage for settings, approval, completion rules, loop
    behavior, model adaptation, provider transport adapters, tool behavior,
    compaction, token estimates, session storage/indexing, undo, error logging,
    spinner, terminal display, and CLI dispatch.

- Top-level support files
  - `README.md` is the user-facing overview and basic usage entry point.
  - `requirements.txt` is the Python dependency list for the CLI/test
    environment.

## Events And External Wrappers

Code Squid can emit small runtime event dictionaries through optional
`on_event(event)` callbacks. If no callback is supplied, nothing changes.

This path is intended for external Python wrappers and tiny host applications,
such as local event viewers. Events are machine-readable facts, not terminal
output. Terminal display is still separate and wrappers should not scrape it.

Current loop-level event types include:

- `run_started`
- `assistant_message_started`
- `assistant_delta`
- `assistant_message`
- `tool_started`
- `tool_finished`
- `reply_rejected`
- `final_message`
- `run_failed`
- `run_finished`

Event payloads should stay compact. They must not include raw file contents,
full command output, prompts, provider payloads, API keys, headers, or secrets.

Callback delivery is best-effort. Observer failures must not crash the run.

## Hooks And Interceptors

Hooks are minimal in-process extension seams for hosts that need to influence a
run at specific lifecycle points. They are not a marketplace, plugin ecosystem,
pack system, settings system, or user hook discovery mechanism. Current hooks
are Python objects passed by callers through `code_squid.agent_setup` and `AgentLoop`
wiring. Code Squid core calls supported hook methods directly as the loop runs.

Hooks are deliberately narrower than passing whole runtime objects around. They
receive typed context dataclasses and return structured decisions or context.
They should not receive `AgentLoop`, `SessionStore`, `ToolExecutor`, or
`ModelAdapter` instances.

Events:

- observe what happened
- one-way callback
- best-effort
- cannot change behavior
- failures swallowed

Hooks:

- run at specific lifecycle seams
- return structured decisions/context
- can influence the current run within narrow limits
- failures are not swallowed
- optional disk loading exists only when callers opt into user hooks
- no plugin registry yet

### before_run

Runs once after the initial transcript exists and the `run_started` event has
been emitted, before the first model call.

Can block the run or add run-level context blocks. A blocked run becomes a
failed run and still reaches the normal `run_finished` handoff.

### before_model_turn

Runs before each model request.

Can add transient prompt/context blocks. This context is model-visible for that
request, but is not appended to `session.messages` and is not persisted.

### before_tool_execute

Runs after the model response has been normalized and validated as a real tool
action, before action preflight, approval, and execution.

Can block, mutate the normalized action, or add approval reasons. It does not
run for narration-only invalid replies. Assistant narration/action-note text is
not treated as tool execution; only normalized `reply["actions"]` entries count
as tool actions.

### tool_result

Runs after a tool result exists, including executed, denied, or blocked results,
before display/events/transcript formatting.

Can modify, redact, or summarize the result before the model sees it.

### before_accept_final

Runs only after a no-tool assistant reply has passed existing final validation
as a final candidate, before final display, `final_message` event, transcript
storage, and completion.

Can block finalization by adding guidance for the model to continue. Can append
a report note to an accepted final.

### run_finished

Runs after a terminal state is reached: `complete`, `failed`, or `interrupted`.

Returns structured follow-up requests through `RunResult.follow_up_requests`.
It does not directly start another run. This is a handoff seam for
hosts/orchestrators such as Desktop or a future Squid OS.

The compact loop shape is:

```text
model request
-> validate reply
-> invalid replies use correction path
-> final candidates go through before_accept_final
-> valid tool actions go through before_tool_execute
-> approval/execution
-> tool_result
-> transcript update
-> terminal status
-> run_finished handoff
```

`squid_core/hooks/` owns the hook context and decision dataclasses, `HookRunner`,
and Hook metadata/loading. `squid_core/agent_loop.py` owns where hook calls happen
in the loop.
`code_squid/agent_setup.py` wires optional `hooks`, optionally loads standalone hooks from
the supplied application home's `hooks/`, or accepts an explicit `hook_runner`.
Selected Mod Hooks arrive through `ResolvedMod`. `squid_core/events.py`
remains observer-only.

Known limitations:

- no hook builder yet
- no pack import/export yet
- no settings-driven hook activation yet
- hooks are still in-process Python objects
- broader user-loaded hook workflows will need review/enable/disable/safety
  boundaries
- `run_finished` follow-up requests are returned to the host; core does not
  orchestrate them

## Runner / Python Wrapping

Runtime construction has three explicit levels:

1. Easy/default: `code_squid.agent_setup.run_coding_task(...)` and
   `build_coding_task_run(...)` provide the batteries-included Code Squid path.
2. Custom: `squid_core.spawner.build_agent_run(...)` or
   `build_agent_loop(...)` create omitted collaborators while using supplied
   Agent, provider, adapter, compactor, tools/executor/results, approval,
   preflight, hooks, stores, and presentation objects directly.
3. Low-level: callers may instantiate `squid_core.agent_loop.AgentLoop(...)`
   directly. The generic builder is convenience, not mandatory architecture.

The customization rule is deliberately small: pass a replacement collaborator
object to `squid_core.spawner`; use only the session/undo factories when Core
must create stores in lifecycle order; construct `AgentLoop` directly when
complete control over construction is required. Generic constructor factories
for providers, adapters, compactors, executors, policies, hooks, or the loop
itself are not part of the API.

The dependency direction is Code Squid application construction to generic
Squid Core construction to Core collaborators to `AgentLoop`; generic
construction never calls back into Code Squid prompt, terminal, or discovery
policy.

`code_squid.agent_setup.run_coding_task(...)` is the Code Squid application
entry point for starting a new coding task. It accepts `repo_root`, `task`,
optional `settings`, optional `display`, and optional `on_event`, and returns
the existing `RunResult`.

`code_squid.agent_setup.build_coding_task_run(...)` constructs the session,
session store, undo store, generic Agent with `CODE_SQUID_PROMPT_DEFAULTS`, selected tools,
application hooks, terminal display, and generic loop wiring without starting
the loop. The CLI uses this shape when it needs access to the session and
session store for interactive follow-ups. Its Skill/tool resolution and
precedence rules remain application-owned; the generic builder accepts tools
and Agent objects already selected by its caller.

`squid_core.spawner.build_agent_run(...)` constructs a generic `Agent` by
default and uses a no-op `NullDisplay` when no presentation collaborator is
provided. It creates a provider, `ModelAdapter`, `Compactor`, `ToolExecutor`,
`ToolResults`, `ApprovalPolicy`, `ActionPreflight`, `HookRunner`, `Session`,
`SessionStore`, and `UndoStore` when those concerns are omitted. It requires
typed settings supplied by the application and does not load Code Squid
settings or defaults itself.

Callers may replace any of those major runtime collaborators selectively. A
supplied `ModelAdapter` bypasses provider construction; a supplied provider is
used to construct the default adapter; a supplied `ToolExecutor` bypasses its
default construction and the otherwise implicit undo-store creation. A
supplied approval policy or action preflight is used directly. Presentation
and approval prompting are separate inputs, so a GUI need not imitate a
terminal display. Built-in OpenAI-compatible/OpenRouter/Ollama construction is
owned by `squid_core.providers`, not by either runner.

The generic generation API follows the same boundary: callers pass an explicit
Core `RuntimeSettings` object or a ready `ModelAdapter`. It never reads the
working directory or loads Code Squid configuration. A supplied adapter bypasses
built-in provider construction.

Generic new-run construction requires explicit `sessions_dir` and `undo_dir`
inputs when it creates the stores itself. It calls
`SessionStore.create(sessions_dir, task, workspace_root=...)` followed by
`UndoStore.create(undo_dir, session_id, workspace_root=...)`. Embedding hosts
may instead pass `session_store_factory` and/or `undo_store_factory`, or pass
pre-created `SessionStore` and `UndoStore` objects. Construction preserves
session-store-first ordering and supplies its session ID to delayed undo
construction. Direct `AgentLoop(...)` construction remains unchanged.

This seam lets a host persist outside the workspace without teaching Core its
storage layout, indexes, or adapter types. Code Squid's application runner uses
`code_squid.app_paths` to supply `<repo>/.code-squid/sessions` and
`<repo>/.code-squid/undo`, while `repo_root` separately continues to define tool
execution. Desktop is one possible host, not a special Core concern.

Hosts that already resolved a Skill and its executable tool registry may pass
them together as `resolved_skill` and `resolved_tools`. Core then skips Skill
discovery while retaining ownership of run construction, metadata, and
execution. The normal Code Squid builder also accepts `mod_name` and
`app_home`; it asks `squid_core.mods.resolve_mod(...)` for the selected resources.
Passing neither path preserves standalone `skill_name` discovery. Generic
`squid_core.spawner` receives only selected resources and remains unaware of
Mod names, paths, discovery, or selection policy.

`code_squid.agent_setup.build_agent_loop(...)` is the application wrapper used
by the CLI follow-up path. It delegates generic collaborator wiring to
`squid_core.spawner.build_agent_loop(...)`. Provider-specific construction and
replay-mode decisions are delegated to `squid_core.providers`.

`squid_core.storage.session_index` owns generic inspection, registration, and
cross-location discovery for explicit index and session-root paths. Session
creation does not register itself globally; Code Squid uses
`code_squid.app_paths` to select both paths and explicitly registers the
workspace's sessions directory after creating a session. Registry failure remains
supplementary and does not invalidate usable local storage. App-specific UIs
own their presentation projection while Core owns the persistence formats and
mechanics.

This runner layer is not a plugin system, orchestration layer, daemon, or
server mode. It gives external Python code a clean way to call Code Squid
without copying CLI wiring. Terminal workflow and presentation live under
`code_squid/console/`; `main.py` only delegates to
`code_squid.console.cli.cli_commands.run_cli()`.

### Core Mod resolution

The host owns selection and passes a Mod name plus the application home to
Core. `discover_mods(app_home)`, `load_mod(name, app_home)`, and
`validate_mod(mod, app_home)` operate on metadata; `resolve_mod(...)` produces
one `ResolvedMod` containing validated metadata, the selected Skill, a
normalized executable Tool registry, and loaded selected Hooks. There is no
automatic routing, agent-driven switching, or active-Mod state file.

The canonical user package is:

```text
<app-home>/mods/<mod-name>/
  mod.yaml
  skills/<skill-name>/SKILL.md
  tools/<tool-name>/tool.yaml
  tools/<tool-name>/tool.py
  hooks/<hook-name>/hook.yaml
  hooks/<hook-name>/hook.py
```

`mod.yaml` uses Desktop's current one-Skill fields: `name`, `description`,
`default_skill`, optional semantic `accent`, `tools`, and `hooks`. The selected
Skill must explicitly declare `allowed-tools`, and that ordered list must match
the Mod Tool inventory exactly. Core preserves accent metadata but does not
interpret its presentation.

A referenced component may be Mod-local or standalone under the same supplied
application home. A Mod-local Skill, Tool, or Hook wins over a same-named loose
user component. Built-in Tools are protected: they win over loose user
collisions, and a Mod-local package may not define a replacement directory for
a listed built-in name. Built-in Skills retain precedence during ordinary
standalone discovery; direct Mod-local Skill selection is package-scoped.

Discovery and validation parse `mod.yaml`, `SKILL.md`, `tool.yaml`, and
`hook.yaml`, and verify Hook source presence, but do not import Tool or Hook
Python source. A selected Mod Hook is imported when runtime resolution loads
it through the normal Hook loader. A selected Tool remains lazy and imports
only when its registry entry executes.

Desktop still owns presentation, Mod Builder workflows, first-party package
location/packaging, and the user's selection. Core owns canonical user-Mod
parsing and runtime resolution. Desktop's older parser/resolver is temporarily
left for the next Desktop migration patch and should become a thin caller of
this API rather than remain an independent parser.

## Skill System

Skills are file-backed prompt/tool profiles. Discovery order is:

1. Built-in skills bundled with the repo.
2. User skills in the Code Squid home directory.

Built-ins win over user duplicates.

Built-in skills are bundled with the repo under:

```text
skills/builtin/<skill-name>/SKILL.md
```

Primary user skills are stored in the Code Squid home directory:

```text
~/.code-squid/skills/<skill-name>/SKILL.md
```

If `CODE_SQUID_HOME` is set, user skills are stored under:

```text
<CODE_SQUID_HOME>/skills/<skill-name>/SKILL.md
```

Each skill is a `SKILL.md` file with simple frontmatter followed by Markdown
instructions. The supported frontmatter fields are:

- `name`
- `description`
- `allowed-tools`

The Markdown body before any recognized prompt-section override heading becomes
`skill.instructions`. When a skill is active, those instructions are inserted
into the system prompt under `## Active Skill` along with the skill name and
description.

`allowed-tools` limits both sides of the tool boundary: which tools are exposed
to the model and which tool names `ToolExecutor` may execute for that run. For
example:

```yaml
allowed-tools: read_file run_command
```

`allowed-tools` has three current meanings:

- omitted `allowed-tools` keeps the existing default/full tool set behavior.
- explicit `allowed-tools: []` means the skill intentionally has no tools.
- listed `allowed-tools` restricts the run to that tool set.

Unknown tool names should fail clearly during run construction before any tool
action is executed.

Explicit no-tool skills are useful for future chat-only, planning-only,
review-only, or explanation-only profiles, but the prompt and loop contract is
not fully tool-aware yet. Prompt assembly and/or loop validation should become
aware of empty active tool sets; no-tool skills likely need a no-tool/chat-style
response contract, and non-final "exactly one tool call" requirements should not
apply when the active tool set is empty.

Code Squid supports normal Agent Skills-style Markdown instructions plus
Code Squid-native prompt-section overrides. Overrides are written as Markdown
headings:

```md
## TASK_PROMPT replace

...

## TOOL_USAGE_GUIDANCE append

...
```

Supported override modes are:

- `replace`
- `append`

Supported override sections are:

- `SYSTEM_PROMPT_INTRO`
- `TASK_PROMPT`
- `FOLLOW_UP_PROMPT`
- `TOOL_USAGE_GUIDANCE`
- `FINAL_SUMMARY_REQUIREMENTS`

Some prompt sections are intentionally not overrideable because they define the
runtime contract:

- `VISIBLE_NARRATION_REQUIREMENTS`
- `REQUIRED_RESPONSE_FORMAT`
- `CORRECTION_MESSAGES`
- `COMPACTION_PROMPT`

Skills can change specialization instructions, inspection style, optional tool
guidance, and final-summary shape. They cannot override the Core one-tool-call
contract, final-response/no-tool mechanics, narration guidance, response
examples, active-Skill/environment insertion, or correction mechanics. They
also cannot remove Code Squid's baseline coding discipline, because that policy
is outside the replaceable sections.

`TASK_PROMPT` and `FOLLOW_UP_PROMPT` remain supported as non-live compatibility
sections for existing Skill parsing and UI/run-context metadata. Their render
helpers may use `{task}`, and the default `TASK_PROMPT` also renders section
placeholders:

- `{TOOL_USAGE_GUIDANCE}`
- `{VISIBLE_NARRATION_REQUIREMENTS}`
- `{REQUIRED_RESPONSE_FORMAT}`
- `{FINAL_SUMMARY_REQUIREMENTS}`

Compatibility rendering uses explicit `.replace()` calls rather than
`.format()` so user tasks or prompt text containing braces do not break
rendering. Neither wrapper is inserted into the runtime transcript. New
sessions persist one assembled system message followed by the raw authored
task as `role=user`; resumed runs append the raw authored follow-up in the same
form.

The active skill can be selected from the CLI. Current support is:

```bash
python main.py skills
python main.py --skill <name>
```

Inside the interactive CLI:

- `/skill` shows the current active skill and available skills.
- `/skill <name>` sets the active skill for future tasks and follow-ups in the
  current CLI process.
- `/skill none` clears the active skill.
- `/skill default` is an alias for clearing the active skill.

The active skill is process-local CLI state. Changing it does not rewrite older
persisted transcript messages. New tasks and follow-ups use the currently
active skill when they are submitted. The startup panel shows `Skill: <name>`
when the CLI is launched with an active skill.

Each new run and follow-up appends a non-transcript `run_context` event to
`session.jsonl`. This records the active `skill_name`, the actual filtered
`allowed_tools`, and the `prompt_overrides` for that run:

```json
{
  "type": "run_context",
  "skill_name": "architecture-review",
  "allowed_tools": ["read_file", "run_command"],
  "prompt_overrides": ["FINAL_SUMMARY_REQUIREMENTS", "TASK_PROMPT", "TOOL_USAGE_GUIDANCE"]
}
```

`run_context` is debug metadata, not model memory. It is not replayed to the
model, and `SessionStore.load_messages()` ignores non-message events.
`python main.py show <session_id>` displays compact `[run context]` blocks so
tool exposure and prompt overrides can be inspected after a run.

Discovered skills include source metadata: built-in skills have
`source="builtin"` and `editable=false`; user skills discovered from the Code
Squid home directory have `source="user"` and
`editable=true`. Both sources use the same parsing, prompt override, selection,
and tool filtering path once discovered.

The current built-in example is `architecture-review`, an inspection-only review
skill. It allows only `read_file` and `run_command`, replaces `TASK_PROMPT`,
replaces `FINAL_SUMMARY_REQUIREMENTS`, and appends `TOOL_USAGE_GUIDANCE`.

Core CLI skill creation/editing commands and new discovery tools such as repo
tree/search helpers are not implemented yet.

## Application Resources and Mods

Code Squid chooses an application home, defaulting to:

```text
~/.code-squid/
```

Setting `CODE_SQUID_HOME` redirects the Code Squid application home. Embedding
applications may instead pass an explicit root. Core resource machinery uses
that supplied root and does not define a universal Squid Core home. Its paths
are:

- `skills/` stores user skills such as
  `~/.code-squid/skills/<skill-name>/SKILL.md`.
- `hooks/` stores user hook packages loaded by `squid_core.hooks` when callers
  opt into user hooks.
- `tools/` stores standalone user Tool packages.
- `mods/<mod-name>/mod.yaml` stores canonical user Mod packages with optional
  package-local Skills, Tools, and Hooks.

These directories are separate from the repo-local `skills/builtin/` bundled
skill directory.

Mod metadata supports an optional top-level semantic accent, for example
`accent: purple`. The effective default is `cyan`; allowed names are `cyan`,
`blue`, `green`, `yellow`, `orange`, `red`, `pink`, `purple`, `white`, and
`gray`.

There is no legacy Extension directory, manifest, active-state file, or CLI.
The host selects a Mod for each run; Core does not persist a globally active
selection.

## Settings

Settings have two explicit ownership layers. `code_squid/settings.py` owns the
human-facing Code Squid shape, `.code-squid/settings.json`, product defaults,
saved selection, persistence, and optional environment overrides. It translates
those values into `squid_core.settings.RuntimeSettings`. Core owns only the
effective provider values and runtime validation semantics used by the spawner,
loop, approval policy, and compactor.

Code Squid reads settings from:

```text
.code-squid/settings.json
```

Missing settings are allowed. Defaults keep the CLI usable with a local
OpenAI-compatible server, especially LM Studio:

- model base URL: `http://127.0.0.1:1234/v1`
- API key: `lm-studio`
- model name: `qwen3.5-9b`
- provider: `openai_compatible`
- temperature: `null`
- display debug: `false`
- approval mode: `never`
- max tool steps: unlimited
- assistant text streaming: disabled
- compaction: enabled at an estimated 48,000 input tokens, keeping 8 recent
  chunks verbatim

Supported settings sections and fields:

- `model.base_url`
- `model.api_key`
- `model.api_key_env`
- `model.name`
- `model.provider`
- `model.temperature`
- `display.debug`
- `runtime.approval_mode`
- `runtime.max_tool_steps`
- `runtime.stream_assistant_text`
- `compaction.enabled`
- `compaction.trigger_input_tokens`
- `compaction.keep_recent_turns`

Supported provider values are `openai_compatible`, `openrouter`, and `ollama`.
Supported approval modes are `never`, `guarded`, and `always`.
`runtime.max_tool_steps` is either `null` or a positive integer.
`runtime.stream_assistant_text` is a boolean. When enabled with a streaming
provider, the loop emits `assistant_message_started` before generation and
`assistant_delta` events for visible text chunks, then emits the normal full
`assistant_message` or `final_message` after the complete reply is assembled and
validated. Streamed deltas are UI events only; tool execution still waits for
the full validated assistant response.
`model.temperature` is `null` or a number from 0 through 2.

Environment overrides are optional development, headless, and automation
inputs—not the normal user configuration UX. Current overrides are:

- `CODE_SQUID_BASE_URL`
- `CODE_SQUID_API_KEY`
- `CODE_SQUID_MODEL`
- `CODE_SQUID_PROVIDER`
- `CODE_SQUID_TEMPERATURE`
- `CODE_SQUID_DEBUG`
- `CODE_SQUID_STREAM_ASSISTANT_TEXT`

`CODE_SQUID_API_KEY` wins over `model.api_key_env`, which wins over
`model.api_key`. `CODE_SQUID_STREAM_ASSISTANT_TEXT=1` enables assistant text
streaming and `0` disables it. There are no compaction environment overrides in
the current code.

Invalid settings JSON, invalid section shapes, invalid provider names, unknown
approval modes, missing configured API-key environment variables, invalid
temperatures, invalid compaction settings, and invalid step limits fail during
settings loading.

## CLI Commands

Current commands:

```bash
python main.py
python main.py --cwd /path/to/project
python main.py skills
python main.py --skill architecture-review
python main.py sessions
python main.py show latest
python main.py show <session_id>
python main.py resume latest
python main.py resume <session_id>
python main.py undo
python main.py mode
python main.py mode strict
python main.py mode balanced
python main.py mode yolo
```

Running with no arguments starts an interactive prompt. A first task starts a
new session; later tasks in the same process continue the active session as
follow-ups unless the user enters `/new`. `/help` prints prompt help, and
`/exit`, `exit`, or `quit` exits the interactive prompt. Interactive skill
commands are `/skill`, `/skill <name>`, `/skill none`, and `/skill default`.

`--cwd` selects the workspace/repo root. It defaults to the current directory
and must point at an existing directory.

Resume loads a saved session, appends a follow-up user message, marks the
session active, creates a fresh latest-only undo buffer, and continues the same
saved session.

`mode` prints or writes the configured approval mode. Friendly CLI mode names
map to settings values this way:

- `strict` -> `runtime.approval_mode = "always"`
- `balanced` -> `runtime.approval_mode = "guarded"`
- `yolo` -> `runtime.approval_mode = "never"`

## Provider Model

LM Studio or another generic OpenAI-compatible server is the recommended default
path. `openai_compatible` uses `squid_core/providers/openai_compatible.py` and sends
chat-completions requests through the OpenAI Python client.

OpenRouter is supported through the OpenAI-compatible provider path by setting
`model.provider` or `CODE_SQUID_PROVIDER` to `openrouter`. It still uses
`OpenAICompatibleProvider`, while Core's small provider helper configures assistant
tool-call replay with `content: null` for assistant messages that have
`tool_calls` and no content. This provider-specific behavior is handled before
messages are sent to the provider.

The OpenAI-compatible provider sends `parallel_tool_calls: false` whenever tools
are present. OpenRouter may still return multiple tool calls. Code Squid handles
that by rejecting invalid multi-tool replies before they enter normal assistant
history and retrying with correction messages.

The OpenAI-compatible provider also supports optional assistant text streaming.
Streaming assembles text and tool-call fragments into the same raw response
shape used by non-streaming responses before `ModelAdapter` normalizes and
validates the reply.

The native Ollama provider exists and is experimental. `squid_core/providers/ollama.py`
uses Ollama `/api/chat`, converts replayed messages into Ollama's expected
shape, omits `parallel_tool_calls`, and adapts the response back to the
OpenAI-like shape consumed by `ModelAdapter`.

Provider request failures are wrapped at the model-adapter boundary as
`ModelRequestError`. The CLI run orchestration in
`code_squid/console/cli/session_runner.py` catches that error, marks the session
failed, and writes diagnostic traceback details to `.code-squid/logs/latest.log`.

## Runtime Contracts

### Turn Contract

Before completion, prompts strongly encourage a brief visible action note and
demonstrate it alongside exactly one tool call. An action note is user-facing
text that explains why the tool call is the immediate next action. Narration is
a behavior-shaping preference, especially for smaller models, not a runtime
invariant.

The runtime enforces:

- malformed tool-call output is rejected
- unknown tool names are rejected during model-adapter validation
- missing required tool arguments are rejected during model-adapter validation
- empty replies with zero tool actions are rejected
- replies with more than one tool action are rejected

Invalid replies are rejected before entering normal assistant history. The loop
stores a correction user message instead. A valid reply resets the invalid-reply
counter. Repeated invalid replies stop after the configured hard-coded loop
limit, currently 3 consecutive invalid replies.

Runtime validation accepts a one-tool non-final reply even when assistant
content is blank. It does not independently enforce action-note presence or
quality.

If `runtime.max_tool_steps` is set, reaching the limit records a failed session
status and stops the loop.

### Final Contract

A valid final assistant reply must include no tool calls and must have
non-empty content.

For coding tasks, prompts ask the agent to keep final summaries concise and
precise, identify changed files, summarize the change, state verification, and
report concrete limitations. Formatting guidance is not runtime-enforced. The terminal display still
hides a legacy `TASK COMPLETE` marker if a model includes it, but finalization no
longer depends on that marker.

### Tool Transcript Contract

Assistant messages that used tools preserve provider `tool_calls` metadata.
Tool-result messages include the matching `tool_call_id`.

Assistant tool-call/result pairs must stay replayable. This matters for strict
OpenAI-compatible model templates and for provider adapters that need to
reconstruct prior tool turns.

`squid_core/tools/results.py` guards against action/result length mismatches. Invalid
assistant replies are excluded from normal assistant history; correction
messages and repeated-invalid failure messages are the durable record of that
path.

## Approval

Approval is a runtime gate in the tool execution path, not a prompt convention.

Current modes:

- `approval_mode = "never"` means trusted/yolo mode; all tool actions are
  approved. In this mode `ToolExecutor` is also configured to allow structured
  file tools outside the workspace without an approval preflight.
- `approval_mode = "guarded"` means balanced mode. Actions with no approval
  reason are approved automatically; actions with an approval reason ask the
  user before execution.
- `approval_mode = "always"` means strict mode and asks before every tool
  action.

The policy is UI-agnostic and receives normalized tool actions before
execution. `TerminalDisplay` is the current prompter used by the CLI.
`squid_core/safety/preflight.py` supplies any workspace, guarded-command, or hook
approval reason before this approval check.

If a user denies an action, the action is not executed. Denial returns a normal
failed tool result to the model with `user denied tool action`.

Guarded command safety is partial and only affects `run_command` in
`approval_mode = "guarded"`. It allowlists simple low-risk commands such as
`pwd`, `ls`, `find`, `rg`, `grep`, `git status`, `git diff`, `pytest`,
`python -m pytest`, and `node --check` when obvious path arguments remain inside
the workspace. It asks for approval for shell syntax, known mutating commands,
unknown commands, package installs, destructive git commands, and obvious paths
outside the workspace.

Approval is not a hardened sandbox. Approved `run_command` actions still execute
through the shell, and approved file tools still use absolute paths.

## Workspace Boundary

`squid_core/safety/workspace_boundary.py` checks structured file-tool actions before
execution. It applies to:

- `read_file`
- `write_file`
- `apply_patch`

For those tools, an absolute `path` is considered outside the workspace when
its resolved path is not under the resolved workspace root selected by `--cwd`
or the current directory. Relative paths are not classified by the workspace
boundary because the file tools themselves require absolute paths.

In `guarded` and `always` modes, outside-workspace file paths require approval
before execution. If approval is granted, action preflight marks that one
execution action as outside-workspace approved and `ToolExecutor` lets it
through. If the executor sees an outside-workspace file action without either
trusted mode or an approval marker, it returns a failed tool result instead of
executing it.

In `never`/yolo mode, outside-workspace file paths are allowed without approval.

This is an approval and preflight boundary, not a process sandbox. It does not
contain `run_command`; shell commands can still read or mutate outside the
workspace if the command itself does so. Guarded mode only adds conservative
approval prompts for some obvious `run_command` cases.

## Compaction

Compaction runs before model calls inside `AgentLoop`.

`squid_core/compaction/compactor.py` asks `squid_core/token_estimate.py` for a rough estimate of the
current transcript size. The estimate serializes messages to JSON/text and uses
simple length math; it is not an exact model tokenizer.

The compaction request uses the generic Core-owned prompt in
`squid_core/compaction/prompts.py`. It has no dependency on Code Squid's
application prompts.

Compaction triggers when:

- `settings.compaction.enabled` is true
- estimated input tokens are at least
  `settings.compaction.trigger_input_tokens`
- there are older chunks available beyond the configured recent chunks

When triggered, compaction:

- preserves the initial system message and initial user task message
- chunks the remaining transcript
- never splits an assistant message with `tool_calls` from its following
  `role: "tool"` result messages
- summarizes older chunks with `ModelAdapter.complete_text(...)`
- replaces those older chunks with one user message headed
  `# Compacted Prior Context`
- keeps recent chunks verbatim according to
  `settings.compaction.keep_recent_turns`

If persistence is wired in, `AgentLoop` logs compaction metadata to
`session.jsonl` through `SessionStore.append_compaction(...)`. `load_messages()`
ignores compaction events and loads only transcript message entries.

Compaction is transcript compression for continuation context. It is not durable
workspace memory and should stay separate from any future workspace memory
feature.

## Sessions, Resume, Undo, And Interruption

Saved sessions live under:

```text
.code-squid/sessions/<session_id>/
```

Each session folder contains:

- `metadata.json`
- `session.jsonl`

`metadata.json` stores run-level metadata: session id, timestamps, repo root,
task, status, and active leaf id. `session.jsonl` stores append-only entries for
messages, compaction events, run-context events, and model reply diagnostics.
Message entries include `id`, `parent_id`, `type`, `timestamp`, `message`, and
optional `usage`.

Every provider reply is captured before agent validation as a diagnostic-only
`model_reply` entry:

```json
{
  "id": "e_000003",
  "parent_id": "e_000002",
  "type": "model_reply",
  "timestamp": "...",
  "reply": {
    "provider": "openrouter",
    "model": "example/model",
    "assistant": {"content": "...", "raw_tool_calls": []},
    "finish_reason": "stop",
    "usage": {"input_tokens": 1, "output_tokens": 2, "total_tokens": 3},
    "response_id": "..."
  }
}
```

`assistant.reasoning`, `assistant.reasoning_content`, and
`assistant.thinking` appear only when the provider returned those fields. The
same applies to finish reason, usage, and response ID. Raw tool-call objects
retain the tool name and argument string seen before JSON parsing.

A rejected reply adds a linked diagnostic-only `reply_rejection` entry:

```json
{
  "id": "e_000004",
  "parent_id": "e_000003",
  "type": "reply_rejection",
  "timestamp": "...",
  "reason": "malformed_tool_call",
  "error": "Tool arguments were not valid JSON: ...",
  "consecutive_invalid_attempt": 1,
  "recoverable_tool_name": "read_file",
  "recoverable_raw_arguments": "{...",
  "raw_reply_id": "e_000003"
}
```

Recoverable tool fields are omitted when unavailable. Rejection diagnostics
cover normal agent reply validation failures; hook-blocked finals are outside
this path. `SessionStore.load_messages()` reads only `type: "message"`, so
neither diagnostic type enters canonical history or is replayed to the model.

Current session statuses are:

- `active`
- `complete`
- `failed`
- `abandoned`
- `interrupted`

Resume can load saved messages with `SessionStore.load_messages()`, append a
follow-up user message, mark the session active, create a fresh undo buffer, and
continue the same saved session. `latest` resolves through
the explicit workspace sessions path supplied by `code_squid.app_paths`.

The saved-session viewer can list sessions and show message transcripts.
Compaction events are not printed as transcript messages by the viewer.
Run-context events are shown as compact `[run context]` blocks with the skill,
filtered tools, and prompt overrides used for that run.

Code Squid calculates the latest undo location as:

```text
.code-squid/undo/
```

Starting a new run or resume replaces the undo buffer. Before `write_file` or
`apply_patch` mutates a target, `ToolExecutor` asks `UndoStore` to snapshot the
file's pre-change state. Repeated writes or patches to the same path keep the
first pre-change snapshot. `python main.py undo` restores existing-file
snapshots and deletes files that did not exist before the write.

Ctrl+C marks the current session `interrupted` and prints the normal final
session display. Model request failures mark the session `failed` and write a
diagnostic log to `.code-squid/logs/latest.log`. The diagnostic log is narrow:
it stores traceback details, not prompts, payloads, tool outputs, file contents,
headers, or API keys.

There is no permanent undo history, branching UI, tree navigation, or advanced
session workflow in the current MVP.

## Tool Model

The active tool surface is:

- `read_file(path, start_line=None, end_line=None)`
- `write_file(path, content)`
- `apply_patch(path, old_text, new_text)`
- `run_command(command)`

`read_file`:

- requires an absolute path
- reads UTF-8 text
- supports optional 1-based inclusive `start_line` and `end_line`
- supports ranged reads for focused inspection
- truncates whole-file reads with shared head/tail truncation when content is
  large
- does not truncate ranged reads
- returns content plus truncation, range, and line-count metadata
- is checked against the workspace boundary before execution unless trusted
  outside-workspace access is configured or approved

`write_file`:

- requires an absolute path
- writes the full file content as UTF-8 text
- returns compact metadata instead of echoing full written content
- does not create parent directories explicitly
- is checked against the workspace boundary before execution unless trusted
  outside-workspace access is configured or approved
- is snapshotted by `ToolExecutor` before mutation when undo storage is wired

`apply_patch`:

- requires an absolute path
- reads and writes UTF-8 text
- performs exactly one exact text replacement
- requires `old_text` to occur exactly once in the current file
- fails without modifying the file when `old_text` is missing or not unique
- returns compact replacement and character-count metadata
- is preferred for small localized edits to existing files
- is checked against the workspace boundary before execution unless trusted
  outside-workspace access is configured or approved
- is snapshotted by `ToolExecutor` before mutation when undo storage is wired

`run_command`:

- runs a shell command with `shell=True`
- uses `repo_root` as the working directory
- merges stderr into stdout
- times out after 15 seconds
- returns `ok` based on process return code
- returns a normalized timeout failure with `timed_out: True`
- truncates large output with shared head/tail truncation
- is used for discovery, verification, and shell behavior
- is not undo-protected, even if it mutates files

There is no structured search tool, repo-policy tool, dedicated test runner,
browser tool, or plugin-provided tool. Discovery, verification, and most shell
behavior go through `run_command`.

## Ownership Boundaries

`main.py` owns only process entrypoint behavior: passing command-line arguments
to `code_squid.console.cli.cli_commands.run_cli()` and returning its exit status.

`code_squid/console/cli/` owns terminal CLI parsing, dispatch, interactive
prompt flow, run/resume wiring, mode/undo commands, saved-session command
routing, and Skill commands. It should not grow agent policy, tool behavior,
provider-specific response parsing, session storage internals, approval logic,
undo mechanics, compaction strategy, or terminal formatting.

`squid_core/agent/` owns generic Agent behavior and protected prompt assembly.
It decides which supplied tools are exposed, which reply shapes are valid,
when the loop should stop, and what correction/failure path is used. It does
not own Code Squid identity or coding workflow policy.

`code_squid/agent/prompts.py` owns Code Squid's explicit application prompt
defaults and baseline coding discipline. `code_squid/agent/coding.py` is the
intentional specialization point around the generic Core Agent and must not
regain a duplicate or empty subclass implementation.

`code_squid/settings.py` owns local settings parsing, persistence, Code Squid
defaults and selection, and optional environment overrides. It produces
`squid_core.settings.RuntimeSettings`; Core owns validation of generic runtime
semantics and enforcement.

`squid_core/agent_loop.py` owns generic turn flow. It is the sequencing layer, not the
place for provider transport, terminal rendering, tool implementation, or
coding-task prompt text. Its tool path remains visibly hook, action preflight,
approval, execution, and result handling; it does not own workspace or guarded
shell policy.

`code_squid/agent_setup.py` owns Code Squid application construction and shared CLI
helpers. `squid_core/spawner.py` owns generic selective construction. Neither is
a plugin system, event bus, daemon, server, or future orchestration layer.

`squid_core/model_adapter.py` owns provider response normalization and replay message
shaping. Provider-specific HTTP/API calls stay in `squid_core/providers/`.

`squid_core/compaction/compactor.py` owns transcript compression mechanics, while
`squid_core/compaction/prompts.py` owns the generic continuation-summary
prompt. Neither imports Code Squid application prompts, and compaction should
not become workspace memory.

`squid_core/safety/approval.py` owns approval decisions without depending on a concrete UI.
The loop enforces those decisions before tool execution.

`squid_core/safety/preflight.py` owns accepted-action safety classification and
translates workspace, guarded-command, and hook reasons into the two action
forms needed by approval and execution. It is a small collaborator, not a
general policy framework.

`squid_core/safety/command_safety.py` owns guarded-mode command classification. It should
stay conservative and limited to deciding whether approval is required.

`squid_core/safety/workspace_boundary.py` owns structured file-tool workspace checks. It
should remain a preflight/approval boundary unless a real sandbox is added
elsewhere.

`squid_core/tools/executor.py` owns mechanical tool dispatch and side-effect tracking.
Individual built-in tool behavior stays in `squid_core/tools/builtins/`.

`squid_core/storage/` owns generic durable session and undo persistence, atomic
writes, session indexing/discovery, and diagnostic error logging. Every
filesystem location is explicit. `code_squid/app_paths.py` owns Code Squid's concrete
`.code-squid` session, undo, index, and error-log locations and passes them into
those mechanisms. In-memory session behavior stays in `squid_core/session.py`;
live display stays in `code_squid/console/ui/`.

`code_squid/console/cli/` owns terminal workflow and control.
`code_squid/console/ui/` owns terminal presentation and input. Tool-event
display is the reliable UX layer for what happened, while model-native
narration is encouraged by prompts.

## Known Limitations / Notes For Later

- OpenRouter may produce invalid multi-tool replies despite
  `parallel_tool_calls=False`; current handling is reject-and-retry through
  correction messages.
- Action notes are prompt-guided. Runtime rejects empty non-final replies and
  multi-tool replies, but it does not fully enforce action-note quality.
- Command and file access is not a hardened sandbox. Workspace checks and
  guarded command checks are approval/preflight mechanisms.
- Compaction uses rough JSON/text length estimates, not exact tokenization.
- Compaction should remain separate from future workspace memory.
- Event callback support currently covers normal loop-level events. Outer
  CLI-caught failures such as some model request errors or keyboard interrupts
  may need explicit wrapper handling depending on the caller path.
- The Code Squid application runner uses `TerminalDisplay`; generic Squid Core
  construction uses `NullDisplay` unless the host supplies presentation.
- Resume support is CLI-owned under `code_squid/console/cli/`.
- JSONL/file event output is intentionally not implemented yet.
- User skill discovery checks `<CODE_SQUID_HOME>/skills/*/SKILL.md`, defaulting
  to `~/.code-squid/skills/*/SKILL.md`.
- Core CLI skill creation/editing commands are not implemented yet.
- `allowed-tools: none` is not a supported special case.
- New discovery tools such as repo tree/search helpers are not part of
  Skills v1.
- Run-context events are debug metadata, not model memory.
- Future tool libraries should stay small per active agent/task, even if more
  tools exist globally.
- Do not turn Code Squid into a broad framework prematurely.
- There are no live provider integration tests in the focused unit suite.
- LM Studio still uses the OpenAI-compatible `/v1` path; native `/api/v1/*`
  integration and explicit model load/unload/download support are deferred.
- Future Squid Models provider/runtime integration is deferred; the existing
  OpenAI-compatible request behavior is not a dedicated transport.

## Practical Principles

- Keep the tool set small and inspectable.
- Keep provider transport separated from provider-response normalization.
- Keep prompt guidance separate from runtime enforcement.
- Keep durable session storage append-only and boring.
- Keep undo latest-only until a real workflow requires more.
- Prefer accurate boring descriptions over aspirational architecture.

Small, inspectable, stupid simple.

# Code Squid Architecture

## Purpose

Code Squid is a minimal standalone coding agent for repository work.

It runs interactive coding tasks from the command line, sends a replayable
transcript to a model provider, accepts model tool calls, executes a small local
tool set, persists the session, and keeps looping until the coding-agent policy
accepts a final assistant message.

The codebase is intentionally narrow. It is not a general agent framework, a
multi-agent system, a hardened sandbox, or a polished TUI. The main value of the
architecture is that the loop, contracts, storage, configuration, and tool
boundaries are small enough to inspect directly.

The runtime shape is:

```text
settings -> runner/wiring -> provider -> model adapter -> coding-agent policy -> agent loop -> approval -> tools -> transcript/session storage
```

`AgentLoop -> on_event callback` is an optional observer path for compact
machine-readable runtime facts.

`.code-squid/` is local runtime state and should be gitignored.

## Component Layout

- `main.py`
  - Thin standalone process entry point.
  - Calls `cli.commands.run_cli(sys.argv[1:])` and exits with its status code.

- `cli/`
  - Terminal CLI behavior split out from the process entry point.
  - `args.py` owns CLI argument parsing, `--cwd`, `--skill`, and workspace
    resolution.
  - `commands.py` owns top-level command dispatch, including `mode`, `undo`,
    saved-session viewer routing, resume routing, and interactive startup.
  - `interactive.py` owns the interactive prompt loop, `/help`, `/new`,
    `/exit`, prompt input, and new-session/resume prompt flows.
  - `run.py` owns CLI run/session orchestration, display setup, new-session
    task runs, follow-up task runs, interruption handling, and model request
    failure handling.
  - `skills.py` owns CLI skill command/status helpers, `python main.py skills`,
    and interactive `/skill` handling.

- `agent/`
  - Coding-agent policy and prompt text.
  - `coding.py` owns initial messages, follow-up messages, exposed tool
    definitions, reply validation, completion detection, correction messages,
    and repeated-invalid-reply failure messages.
  - `prompts.py` owns prompt text, tool-use guidance, final-summary
    requirements, correction prompts, and compaction-summary prompting.
  - Prompt guidance is not the same as runtime enforcement.

- `config/`
  - Runtime settings loading.
  - `settings.py` reads `.code-squid/settings.json`, validates supported
    settings, applies supported environment overrides, and returns typed
    settings objects.

- `core/`
  - Generic runtime machinery.
  - `agent_loop.py` owns turn flow, invalid-reply retry handling, compaction
    hooks, hook call placement, approval gating, tool execution sequencing,
    transcript writes, and session status updates. It also emits compact
    runtime events through an optional `on_event` callback.
  - `events.py` owns the tiny best-effort observer callback helper.
  - `hooks.py` owns hook context/decision dataclasses and `HookRunner`.
  - `extension_paths.py` owns Code Squid home path resolution and user extension
    storage directories.
  - `hook_loader.py` owns loading enabled user hooks from disk when callers opt
    into user hooks.
  - `runner.py` owns reusable coding-task run wiring for Python callers and CLI
    helpers. It wires optional hooks or a `HookRunner`, and wires the selected
    provider into the model adapter but does not own provider-specific
    construction details.
  - `session.py` owns in-memory transcript state and lightweight read/write
    side-effect tracking.
  - `model_adapter.py` owns provider response normalization, tool-call parsing,
    shallow tool-call validation, provider replay message shaping, usage
    normalization, and `ModelRequestError`.
  - `approval.py` owns UI-agnostic approval decisions and denied tool results.
  - `command_safety.py` owns conservative guarded-mode checks for
    `run_command`.
  - `workspace_boundary.py` owns preflight checks for structured file tools
    that target paths outside the selected workspace root.
  - `compaction.py` owns pre-request transcript compaction.
  - `token_estimate.py` owns rough transcript token estimates.
  - `tool_executor.py` owns tool dispatch, exception-to-result conversion,
    successful read/write side-effect tracking, and pre-write undo snapshots.
  - `tool_results.py` owns conversion of action results into model-visible
    `role: "tool"` messages.

- `providers/`
  - Provider construction and raw provider transport.
  - `factory.py` owns provider selection/construction and provider-specific
    replay-mode choices, including OpenRouter's assistant tool-call content
    shape.
  - `base.py` owns only the provider contract/interface.
  - `openai_compatible.py` owns OpenAI-compatible chat-completions calls through
    the OpenAI Python client.
  - `ollama.py` owns native Ollama `/api/chat` calls and adapts native Ollama
    responses to the OpenAI-like shape expected by `ModelAdapter`.
  - Concrete provider files own transport behavior. Provider transport does not
    own loop control, coding-agent policy, tool execution, or final reply
    validation.

- `storage/`
  - Local runtime persistence.
  - `session_store.py` owns one session folder, `metadata.json`, append-only
    `session.jsonl` entries, message loading, status updates, and compaction
    event logging.
  - `session_index.py` owns saved-session discovery, newest-session lookup,
    exact session directory lookup, and raw JSONL entry loading.
  - `undo_store.py` owns the latest-only undo buffer.
  - `error_log.py` owns narrow diagnostic traceback logging for model request
    failures.

- `tools/`
  - Local tool schemas and implementations.
  - Current active tools are `read_file`, `write_file`, `apply_patch`, and
    `run_command`.
  - `_truncation.py` owns shared head/tail truncation for large file and command
    outputs.
  - `tools/__init__.py` owns the static tool registry.

- `ui/`
  - Small terminal display helpers.
  - `terminal.py` owns display flow, formatting, approval prompts, debug output,
    tool-event display, final-summary display, and friendly error messages.
  - `sessions.py` owns saved-session viewer display.
  - `spinner.py` owns only TTY spinner animation mechanics.

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
are Python objects passed by callers through `core.runner` and `AgentLoop`
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
action, before workspace checks, guarded command checks, approval, and
execution.

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

`core/hooks.py` owns the hook context and decision dataclasses plus
`HookRunner`. `core/agent_loop.py` owns where hook calls happen in the loop.
`core/runner.py` wires optional `hooks`, optionally loads user hooks from
`CODE_SQUID_HOME/hooks`, or accepts an explicit `hook_runner`. `core/events.py`
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

`core/runner.py` is the public Python wiring layer for apps and wrappers that
embed Code Squid. Wrappers should use public helpers such as
`build_coding_task_run(...)`, `build_agent_loop(...)`, and
`build_run_display(...)` instead of underscore-prefixed internals.

`core.runner.run_coding_task(...)` is the reusable Python entry point for
starting a new coding task. It accepts `repo_root`, `task`, optional `settings`,
optional `display`, and optional `on_event`, and returns the existing
`RunResult`.

`core.runner.build_coding_task_run(...)` constructs the session, session store,
undo store, coding agent, and loop without starting the loop. The CLI uses this
shape when it needs access to the session and session store for interactive
follow-ups.

`core.runner.build_agent_loop(...)` owns the shared runtime wiring for provider,
model adapter, tool executor, tool-result formatter, approval, compaction, and
`AgentLoop`. Provider-specific construction and replay-mode decisions are
delegated to `providers.factory`.

`storage/session_index.py` owns read-only session discovery across registered
workspaces. `SessionStore` owns persistence for one session. App-specific UIs
own their presentation projection, such as turning persisted messages into
feeds, cards, or views, while core owns reusable run, session, model, and tool
wiring.

This runner layer is not a plugin system, orchestration layer, daemon, or
server mode. It gives external Python code a clean way to call Code Squid
without copying CLI wiring. Terminal CLI wrapper behavior lives under `cli/`;
`main.py` only delegates to `cli.commands.run_cli()`.

## Skill System

Skills are file-backed prompt/tool profiles. Discovery order is:

1. Built-in skills bundled with the repo.
2. User skills in the Code Squid home directory.
3. Legacy repo-local user skills, only for names not already discovered.

Built-ins win over user duplicates, and home user skills win over legacy
repo-local duplicates.

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

Legacy repo-local user skills may still be discovered from:

```text
skills/user/<skill-name>/SKILL.md
```

This legacy path is a compatibility/dev fallback, not the place new user skills
should be created.

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

Skills can change the task mode, inspection style, tool guidance, and final
summary shape, but they cannot override the core one-tool-call contract,
correction mechanics, compaction prompt, or final-response/no-tool mechanics.

`TASK_PROMPT` and `FOLLOW_UP_PROMPT` may use `{task}`. The default
`TASK_PROMPT` also renders section placeholders:

- `{TOOL_USAGE_GUIDANCE}`
- `{VISIBLE_NARRATION_REQUIREMENTS}`
- `{REQUIRED_RESPONSE_FORMAT}`
- `{FINAL_SUMMARY_REQUIREMENTS}`

Prompt rendering uses explicit `.replace()` calls rather than `.format()` so
user tasks or prompt text containing braces do not break rendering. The default
follow-up prompt is generic and skill-friendly: it preserves the current task
mode, active skill, workspace, constraints, and available tools.

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
Squid home directory or the legacy repo-local fallback have `source="user"` and
`editable=true`. Both sources use the same parsing, prompt override, selection,
and tool filtering path once discovered.

The current built-in example is `architecture-review`, an inspection-only review
skill. It allows only `read_file` and `run_command`, replaces `TASK_PROMPT`,
replaces `FINAL_SUMMARY_REQUIREMENTS`, and appends `TOOL_USAGE_GUIDANCE`.

Core CLI skill creation/editing commands and new discovery tools such as repo
tree/search helpers are not implemented yet.

## Extension Storage

User-level extension storage is rooted at the Code Squid home directory:

```text
~/.code-squid/
```

Setting `CODE_SQUID_HOME` redirects this home directory. Current and planned
extension paths are:

- `skills/` stores user skills such as
  `~/.code-squid/skills/<skill-name>/SKILL.md`.
- `hooks/` stores user hook packages loaded by `core.hook_loader` when callers
  opt into user hooks.
- `tools/` is reserved for future user tool storage.
- `packs/` is reserved for future pack storage.

These directories are separate from the repo-local `skills/builtin/` bundled
skill directory and the legacy `skills/user/` compatibility/dev fallback.

## Settings

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

Environment overrides exist for current model/debug/temperature/provider-related
settings:

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
path. `openai_compatible` uses `providers/openai_compatible.py` and sends
chat-completions requests through the OpenAI Python client.

OpenRouter is supported through the OpenAI-compatible provider path by setting
`model.provider` or `CODE_SQUID_PROVIDER` to `openrouter`. It still uses
`OpenAICompatibleProvider`, but `providers.factory` configures assistant
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

The native Ollama provider exists and is experimental. `providers/ollama.py`
uses Ollama `/api/chat`, converts replayed messages into Ollama's expected
shape, omits `parallel_tool_calls`, and adapts the response back to the
OpenAI-like shape consumed by `ModelAdapter`.

Provider request failures are wrapped at the model-adapter boundary as
`ModelRequestError`. The CLI run orchestration in `cli/run.py` catches that
error, marks the session failed, and writes diagnostic traceback details to
`.code-squid/logs/latest.log`.

## Runtime Contracts

### Turn Contract

Before completion, prompts require a brief visible action note plus exactly one
tool call. An action note is the user-facing text before a non-final tool call
that explains why the tool call is the immediate next action.

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

The prompts require non-final action notes. Current runtime validation does not
independently reject a one-tool non-final reply solely because the assistant
content is empty or the action-note content is low quality.

If `runtime.max_tool_steps` is set, reaching the limit records a failed session
status and stops the loop.

### Final Contract

A valid final assistant reply must include no tool calls and must have
non-empty content.

For coding tasks, prompts ask the agent to keep final summaries compact,
terminal-friendly, and free of nested bullet lists. They also ask the agent to
prefer these Markdown headings when they are relevant:

- `## Files changed`
- `## What changed`
- `## Verification`
- `## Remaining risks / notes`

These labels are guidance only, not runtime-enforced. The terminal display still
hides a legacy `TASK COMPLETE` marker if a model includes it, but finalization no
longer depends on that marker.

### Tool Transcript Contract

Assistant messages that used tools preserve provider `tool_calls` metadata.
Tool-result messages include the matching `tool_call_id`.

Assistant tool-call/result pairs must stay replayable. This matters for strict
OpenAI-compatible model templates and for provider adapters that need to
reconstruct prior tool turns.

`core/tool_results.py` guards against action/result length mismatches. Invalid
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

`core/workspace_boundary.py` checks structured file-tool actions before
execution. It applies to:

- `read_file`
- `write_file`
- `apply_patch`

For those tools, an absolute `path` is considered outside the workspace when
its resolved path is not under the resolved workspace root selected by `--cwd`
or the current directory. Relative paths are not classified by the workspace
boundary because the file tools themselves require absolute paths.

In `guarded` and `always` modes, outside-workspace file paths require approval
before execution. If approval is granted, the loop marks that one action as
outside-workspace approved and `ToolExecutor` lets it through. If the executor
sees an outside-workspace file action without either trusted mode or an
approval marker, it returns a failed tool result instead of executing it.

In `never`/yolo mode, outside-workspace file paths are allowed without approval.

This is an approval and preflight boundary, not a process sandbox. It does not
contain `run_command`; shell commands can still read or mutate outside the
workspace if the command itself does so. Guarded mode only adds conservative
approval prompts for some obvious `run_command` cases.

## Compaction

Compaction runs before model calls inside `AgentLoop`.

`core/compaction.py` asks `core/token_estimate.py` for a rough estimate of the
current transcript size. The estimate serializes messages to JSON/text and uses
simple length math; it is not an exact model tokenizer.

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
messages, compaction events, and run-context debug events. Message entries
include `id`, `parent_id`, `type`, `timestamp`, `message`, and optional `usage`.

Current session statuses are:

- `active`
- `complete`
- `failed`
- `abandoned`
- `interrupted`

Resume can load saved messages with `SessionStore.load_messages()`, append a
follow-up user message, mark the session active, create a fresh undo buffer, and
continue the same saved session. `latest` resolves through
`storage/session_index.py`.

The saved-session viewer can list sessions and show message transcripts.
Compaction events are not printed as transcript messages by the viewer.
Run-context events are shown as compact `[run context]` blocks with the skill,
filtered tools, and prompt overrides used for that run.

`UndoStore` stores the latest undo buffer under:

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
to `cli.commands.run_cli()` and returning its exit status.

`cli/` owns terminal CLI parsing, dispatch, interactive prompt flow, CLI
run/resume wiring, mode/undo commands, saved-session command routing, and CLI
skill commands. It should not grow agent policy, tool behavior,
provider-specific response parsing, session storage internals, approval logic,
undo mechanics, compaction strategy, or terminal formatting.

`agent/` owns coding-agent behavior and prompt text. It decides which tools are
exposed, which replies are valid, when the loop should stop, and what
correction/failure messages are used.

`config/settings.py` owns local settings parsing and environment overrides. It
does not decide how settings are enforced.

`core/agent_loop.py` owns generic turn flow. It is the sequencing layer, not the
place for provider transport, terminal rendering, tool implementation, or
coding-task prompt text.

`core/runner.py` owns reusable Python run wiring and shared helpers used by the
CLI. It is not a plugin system, event bus, daemon, server, or future
orchestration layer.

`core/model_adapter.py` owns provider response normalization and replay message
shaping. Provider-specific HTTP/API calls stay in `providers/`.

`core/compaction.py` owns transcript compression mechanics. It should not become
workspace memory.

`core/approval.py` owns approval decisions without depending on a concrete UI.
The loop enforces those decisions before tool execution.

`core/command_safety.py` owns guarded-mode command classification. It should
stay conservative and limited to deciding whether approval is required.

`core/workspace_boundary.py` owns structured file-tool workspace checks. It
should remain a preflight/approval boundary unless a real sandbox is added
elsewhere.

`core/tool_executor.py` owns mechanical tool dispatch and side-effect tracking.
Individual tool behavior stays in `tools/`.

`storage/` owns durable local state. In-memory session behavior stays in
`core/session.py`; live display stays in `ui/`.

`ui/` owns terminal presentation only. Tool-event display is the reliable UX
layer for what happened, while model-native narration is encouraged by prompts.

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
- The default runner uses `TerminalDisplay`, so external wrappers may see
  terminal output unless they pass a different display later.
- Resume support is CLI-owned under `cli/`.
- JSONL/file event output is intentionally not implemented yet.
- User skill discovery checks `<CODE_SQUID_HOME>/skills/*/SKILL.md`, defaulting
  to `~/.code-squid/skills/*/SKILL.md`; legacy repo-local
  `skills/user/*/SKILL.md` discovery remains as a compatibility/dev fallback
  for missing names.
- Core CLI skill creation/editing commands are not implemented yet.
- `allowed-tools: none` is not a supported special case.
- New discovery tools such as repo tree/search helpers are not part of
  Skills v1.
- Run-context events are debug metadata, not model memory.
- Future tool libraries should stay small per active agent/task, even if more
  tools exist globally.
- Do not turn Code Squid into a broad framework prematurely.
- There are no live provider integration tests in the focused unit suite.

## Practical Principles

- Keep the tool set small and inspectable.
- Keep provider transport separated from provider-response normalization.
- Keep prompt guidance separate from runtime enforcement.
- Keep durable session storage append-only and boring.
- Keep undo latest-only until a real workflow requires more.
- Prefer accurate boring descriptions over aspirational architecture.

Small, inspectable, stupid simple.

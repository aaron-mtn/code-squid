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
settings -> provider -> model adapter -> coding-agent policy -> agent loop -> approval -> tools -> transcript/session storage
```

`.code-squid/` is local runtime state and should be gitignored.

## Component Layout

- `main.py`
  - Thin CLI entry point, object wiring, and small command dispatch.
  - Uses the selected workspace directory as `repo_root`; by default this is
    the current directory.
  - Loads settings and wires provider, model adapter, compactor, session state,
    session storage, undo storage, tool executor, tool-result formatter,
    terminal display, approval policy, coding agent, and loop.
  - Dispatches new runs, saved-session listing/showing, resume, and undo.
  - Catches `KeyboardInterrupt`, marks the session interrupted, and prints the
    final session display.
  - Catches `ModelRequestError`, marks the session failed, writes a diagnostic
    error log, and prints a short CLI failure.

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
    hooks, approval gating, tool execution sequencing, transcript writes, and
    session status updates.
  - `session.py` owns in-memory transcript state and lightweight read/write
    side-effect tracking.
  - `model_adapter.py` owns provider response normalization, tool-call parsing,
    shallow tool-call validation, provider replay message shaping, usage
    normalization, and `ModelRequestError`.
  - `approval.py` owns UI-agnostic approval decisions and denied tool results.
  - `compaction.py` owns pre-request transcript compaction.
  - `token_estimate.py` owns rough transcript token estimates.
  - `tool_executor.py` owns tool dispatch, exception-to-result conversion,
    successful read/write side-effect tracking, and pre-write undo snapshots.
  - `tool_results.py` owns conversion of action results into model-visible
    `role: "tool"` messages.

- `providers/`
  - Raw provider transport.
  - `openai_compatible.py` owns OpenAI-compatible chat-completions calls through
    the OpenAI Python client.
  - `ollama.py` owns native Ollama `/api/chat` calls and adapts native Ollama
    responses to the OpenAI-like shape expected by `ModelAdapter`.
  - Provider transport does not own loop control, coding-agent policy, tool
    execution, or final reply validation.

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
  - Current active tools are `read_file`, `write_file`, and `run_command`.
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
- `compaction.enabled`
- `compaction.trigger_input_tokens`
- `compaction.keep_recent_turns`

Supported provider values are `openai_compatible`, `openrouter`, and `ollama`.
Supported approval modes are `never` and `always`. `runtime.max_tool_steps` is
either `null` or a positive integer. `model.temperature` is `null` or a number
from 0 through 2.

Environment overrides exist for current model/debug/temperature/provider-related
settings:

- `CODE_SQUID_BASE_URL`
- `CODE_SQUID_API_KEY`
- `CODE_SQUID_MODEL`
- `CODE_SQUID_PROVIDER`
- `CODE_SQUID_TEMPERATURE`
- `CODE_SQUID_DEBUG`

`CODE_SQUID_API_KEY` wins over `model.api_key_env`, which wins over
`model.api_key`. There are no compaction environment overrides in the current
code.

Invalid settings JSON, invalid section shapes, invalid provider names, unknown
approval modes, missing configured API-key environment variables, invalid
temperatures, invalid compaction settings, and invalid step limits fail during
settings loading.

## CLI Commands

Current commands:

```bash
python main.py
python main.py sessions
python main.py show latest
python main.py show <session_id>
python main.py resume latest
python main.py resume <session_id>
python main.py undo
```

Running with no arguments starts a new interactive task. Resume loads a saved
session, appends a follow-up user message, marks the session active, creates a
fresh latest-only undo buffer, and continues the same saved session.

## Provider Model

LM Studio or another generic OpenAI-compatible server is the recommended default
path. `openai_compatible` uses `providers/openai_compatible.py` and sends
chat-completions requests through the OpenAI Python client.

OpenRouter is supported through the OpenAI-compatible provider path by setting
`model.provider` or `CODE_SQUID_PROVIDER` to `openrouter`. It still uses
`OpenAICompatibleProvider`, but `main.py` configures assistant tool-call replay
with `content: null` for assistant messages that have `tool_calls` and no
content. This provider-specific behavior is handled before messages are sent to
the provider.

The OpenAI-compatible provider sends `parallel_tool_calls: false` whenever tools
are present. OpenRouter may still return multiple tool calls. Code Squid handles
that by rejecting invalid multi-tool replies before they enter normal assistant
history and retrying with correction messages.

The native Ollama provider exists and is experimental. `providers/ollama.py`
uses Ollama `/api/chat`, converts replayed messages into Ollama's expected
shape, omits `parallel_tool_calls`, and adapts the response back to the
OpenAI-like shape consumed by `ModelAdapter`.

Provider request failures are wrapped at the model-adapter boundary as
`ModelRequestError`. `main.py` catches that error, marks the session failed, and
writes diagnostic traceback details to `.code-squid/logs/latest.log`.

## Runtime Contracts

### Turn Contract

Before completion, a valid assistant reply must include exactly one normalized
tool action. Visible narration is expected before the tool call.

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

The prompts require non-final visible narration. Current runtime validation does
not independently reject a one-tool non-final reply solely because the assistant
content is empty.

If `runtime.max_tool_steps` is set, reaching the limit records a failed session
status and stops the loop.

### Final Contract

A valid final assistant reply must include no tool calls and must have
non-empty content.

For coding tasks, prompts ask the agent to prefer these summary labels when
they are relevant:

- `Files changed:`
- `What changed:`
- `Verification:`
- `Remaining risks / notes:`

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
  approved.
- `approval_mode = "always"` asks before every tool action.

The policy is UI-agnostic and receives normalized tool actions before
execution. `TerminalDisplay` is the current prompter used by the CLI.

If a user denies an action, the action is not executed. Denial returns a normal
failed tool result to the model with `user denied tool action`.

Approval is not a sandbox. In `always` mode the user can decline a proposed
action, but approved `run_command` actions still execute through the shell and
approved file tools still use absolute paths.

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
messages and compaction events. Message entries include `id`, `parent_id`,
`type`, `timestamp`, `message`, and optional `usage`.

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

`UndoStore` stores the latest undo buffer under:

```text
.code-squid/undo/
```

Starting a new run or resume replaces the undo buffer. Before `write_file`
mutates a target, `ToolExecutor` asks `UndoStore` to snapshot the file's
pre-change state. Repeated writes to the same path keep the first pre-change
snapshot. `python main.py undo` restores existing-file snapshots and deletes
files that did not exist before the write.

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
- can read any absolute path reachable by the process

`write_file`:

- requires an absolute path
- writes the full file content as UTF-8 text
- returns compact metadata instead of echoing full written content
- does not create parent directories explicitly
- can write any absolute path reachable by the process
- is snapshotted by `ToolExecutor` before mutation when undo storage is wired

`run_command`:

- runs a shell command with `shell=True`
- uses `repo_root` as the working directory
- merges stderr into stdout
- times out after 10 seconds
- returns `ok` based on process return code
- returns a normalized timeout failure with `timed_out: True`
- truncates large output with shared head/tail truncation
- is used for discovery, verification, and shell behavior
- is not undo-protected, even if it mutates files

There is no patch/edit tool, structured search tool, repo-policy tool,
dedicated test runner, browser tool, or plugin-provided tool. Discovery,
verification, and most shell behavior go through `run_command`.

## Ownership Boundaries

`main.py` owns wiring and command dispatch. It should stay thin and should not
grow agent policy, tool behavior, provider-specific response parsing, session
storage internals, approval logic, undo mechanics, compaction strategy, or
terminal formatting.

`agent/` owns coding-agent behavior and prompt text. It decides which tools are
exposed, which replies are valid, when the loop should stop, and what
correction/failure messages are used.

`config/settings.py` owns local settings parsing and environment overrides. It
does not decide how settings are enforced.

`core/agent_loop.py` owns generic turn flow. It is the sequencing layer, not the
place for provider transport, terminal rendering, tool implementation, or
coding-task prompt text.

`core/model_adapter.py` owns provider response normalization and replay message
shaping. Provider-specific HTTP/API calls stay in `providers/`.

`core/compaction.py` owns transcript compression mechanics. It should not become
workspace memory.

`core/approval.py` owns approval decisions without depending on a concrete UI.
The loop enforces those decisions before tool execution.

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
- Model-native narration is encouraged, but terminal tool-event display is the
  reliable UX layer.
- Compaction uses rough JSON/text length estimates, not exact tokenization.
- Compaction should remain separate from future workspace memory.
- Approval mode currently only supports `never` and `always`.
- File access policy should remain explicit if stricter sandboxing is added
  later; current file tools use absolute paths reachable by the process.
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

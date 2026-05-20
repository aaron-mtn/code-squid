# Code Squid Architecture

## Purpose

Code Squid is a minimal standalone coding agent for repository work.

It runs interactive coding tasks from the command line, sends the transcript to
an OpenAI-compatible chat-completions provider, accepts model tool calls,
executes a small local tool set, persists the session, and keeps looping until
the coding agent accepts a final assistant message.

The codebase is intentionally narrow. It is not a general agent framework, a
multi-agent system, a hardened sandbox, or a polished TUI. The main value of the
architecture is that the loop, contracts, storage, configuration, and tool
boundaries are small enough to inspect directly.

The runtime shape is:

```text
settings -> provider -> model adapter -> coding agent policy -> agent loop -> approval -> tools -> transcript/session storage
```

`.code-squid/` is local runtime state and should be gitignored.

## Component Layout

- `main.py`
  - Thin CLI entry point, object wiring, and small command dispatch.
  - Uses the current directory as `repo_root`.
  - Loads settings, creates provider, model adapter, session state, session
    storage, undo storage, tool executor, tool result formatter, terminal
    display, approval policy, coding agent, and loop.
  - Dispatches new runs, session listing/showing, resume, and undo.
  - Catches `ModelRequestError`, records a failed session status, writes a
    diagnostic error log, and prints a short friendly CLI failure.

- `config/`
  - Runtime settings loading.
  - `settings.py` reads `.code-squid/settings.json`, validates supported
    settings, applies environment overrides, and returns typed settings objects.

- `core/`
  - Generic runtime machinery.
  - Owns the loop, transcript/session state, model response normalization,
    approval decisions, tool dispatch, side-effect tracking, pre-write undo
    snapshot coordination, and tool-result message formatting.
  - Should not contain coding-task prompt text.

- `agent/`
  - Coding-agent policy and prompt text.
  - Owns initial messages, follow-up messages, tool definitions exposed to the
    model, reply validation, completion detection, correction messages, and
    repeated-invalid-reply failure messaging.

- `tools/`
  - Local tool schemas and implementations.
  - Currently contains `read_file`, `write_file`, `run_command`, shared output
    truncation, and a static registry.

- `providers/`
  - Raw provider transport.
  - `openai_compatible.py` owns the OpenAI-compatible
    `chat.completions.create(...)` call through the OpenAI Python client.
  - Provider transport does not normalize responses or apply agent policy.

- `storage/`
  - Local runtime persistence.
  - `session_store.py` owns one session folder.
  - `session_index.py` owns listing, finding, and loading saved sessions.
  - `undo_store.py` owns the latest-only undo buffer.
  - `error_log.py` owns narrow diagnostic traceback logging for app/provider
    failures.

- `ui/`
  - Small terminal display helpers.
  - `terminal.py` owns display flow, formatting, approval prompts, debug output,
    and friendly error messages.
  - `spinner.py` owns only the TTY spinner animation mechanics.
  - `sessions.py` owns saved-session viewer display.

- `tests/`
  - Focused pytest coverage for settings, approval, completion rules, loop
    behavior, model adaptation, tool behavior, session storage, undo, error
    logging, spinner, terminal display, and CLI dispatch.

## Settings

Code Squid reads settings from:

```text
.code-squid/settings.json
```

Missing settings are allowed. Defaults keep the CLI usable with a local
OpenAI-compatible server:

- model base URL: `http://127.0.0.1:1234/v1`
- API key: `lm-studio`
- model name: `qwen3.5-9b`
- display debug: `false`
- approval mode: `never`
- max tool steps: unlimited

Supported settings sections are:

- `model.base_url`
- `model.api_key`
- `model.api_key_env`
- `model.name`
- `display.debug`
- `runtime.approval_mode`
- `runtime.max_tool_steps`

Environment overrides:

- `CODE_SQUID_BASE_URL`
- `CODE_SQUID_API_KEY`
- `CODE_SQUID_MODEL`
- `CODE_SQUID_DEBUG`

`CODE_SQUID_API_KEY` wins over `model.api_key_env`, which wins over
`model.api_key`. `runtime.approval_mode` currently supports only `never` and
`always`. `runtime.max_tool_steps` is either `null` or a positive integer.

Invalid settings JSON, invalid section shapes, unknown approval modes, missing
configured API-key environment variables, and invalid step limits fail during
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

## Ownership Boundaries

`main.py` owns wiring and command dispatch. It should stay thin and should not
grow agent policy, tool behavior, provider-specific response parsing, session
storage internals, approval logic, undo mechanics, or terminal formatting.

`config/settings.py` owns local settings parsing and environment overrides. It
does not decide how settings are enforced.

`core/agent_loop.py` owns generic turn flow. It initializes the transcript when
needed, asks the adapter for a reply, validates the reply through the active
agent, rejects invalid replies by injecting correction user messages, stores
valid assistant messages, checks approval for each action, executes approved
tool actions, formats tool results, appends those results to the transcript,
tracks invalid replies and tool-step limits, and persists session status.

`AgentLoop` avoids adding initial messages again when the in-memory session
already has messages. This is what allows resume to continue an existing
transcript instead of replaying a fresh system/user prefix.

`core/approval.py` owns approval-mode decisions without depending on a concrete
UI. In `never` mode all tool actions are approved. In `always` mode the policy
asks an approval prompter, currently `TerminalDisplay`. Denied actions are
returned to the model as failed tool results; they are not executed.

`core/session.py` owns in-memory transcript state and side-effect tracking:
`messages`, `files_read`, and `files_written`. It does not persist state and
does not interpret the task.

`core/model_adapter.py` owns provider response normalization. It converts raw
chat-completion responses into the internal reply shape:

- `message`: assistant message suitable for transcript storage
- `actions`: normalized tool actions
- `format_error`: empty string or a controlled parsing/validation error
- `usage`: optional provider usage data when present

The adapter validates known tool names and required argument presence. It does
not perform full JSON Schema validation.

`ModelRequestError` is the boundary for provider request failures. Exceptions
raised by `provider.create_response(...)` are wrapped as `ModelRequestError` so
the CLI can report model/provider failures cleanly without hiding bugs in later
normalization, validation, or runtime code.

`core/tool_executor.py` owns mechanical tool dispatch. It looks up tools in the
registry, snapshots `write_file` targets before mutation when undo is wired,
calls the implementation, catches exceptions, returns normalized failure
dictionaries, and records successful read/write side effects in the session.

`core/tool_results.py` owns conversion of executed tool results into
model-visible `role: "tool"` messages. It also guards against action/result
length mismatches so malformed executor output does not silently create a bad
assistant/tool chain.

`agent/coding.py` owns coding-agent rules. It decides which tools are exposed,
what initial and follow-up messages are used, which replies are valid, when the
loop should stop, which correction messages are sent, and what failure message
is used after repeated invalid replies.

`agent/prompts.py` owns prompt text. Prompt guidance should not be mistaken for
runtime enforcement.

Each tool module owns its own schema and behavior. The registry in
`tools/__init__.py` is static and intentionally small.

`storage/session_store.py` owns the files for one session folder.
`storage/session_index.py` owns discovery and loading across saved sessions.
`storage/undo_store.py` owns the latest undo buffer.
`storage/error_log.py` owns provider/app failure traceback logging.

`ui/terminal.py` owns live terminal display and approval prompting.
`ui/spinner.py` owns only spinner animation. The spinner is enabled only for
TTY output and is disabled in debug display mode. It is UI-only behavior and
does not affect transcript state, tool actions, or model-visible messages.
`ui/sessions.py` owns saved-session viewer display.

## Turn And Finalization Contracts

Before completion, a valid assistant reply must include exactly one normalized
tool action.

The runtime enforces:

- malformed tool-call output is rejected
- unknown tool names are rejected during model-adapter validation
- missing required tool arguments are rejected during model-adapter validation
- non-final replies with zero tool actions are rejected
- non-final replies with more than one tool action are rejected
- non-final replies with a tool action but no visible narration are rejected
- final replies that also include tool actions are rejected

The runtime does not enforce that narration accurately describes the tool call.
That is prompt-enforced guidance only.

A valid final assistant reply must:

- include no tool calls
- have `TASK COMPLETE` as the final non-empty line
- include these exact required labels:
  - `Files changed:`
  - `What changed:`
  - `Verification run:`
  - `Remaining risks:`

These labels are runtime-enforced, not prompt-only guidance. The terminal
display hides the `TASK COMPLETE` marker in normal display, but the marker
remains part of the stored assistant message.

The loop tracks consecutive invalid replies and stops after 3 consecutive
invalid replies.

- A valid reply resets the counter.
- `AgentLoop` owns the counter and stop decision.
- `CodingAgent` owns the human-readable failure message via
  `failure_message_for_invalid_replies(...)`.
- Repeated invalid replies record a failed session status.

If `runtime.max_tool_steps` is set, reaching the limit also records a failed
session status and stops the loop.

## Transcript Contract

Assistant messages that used tools preserve provider `tool_calls` metadata.
Tool-result messages include the matching `tool_call_id`.

This matters because stricter OpenAI-compatible model templates expect
assistant/tool/result chains to be replayable in that shape.

`session.jsonl` stores append-only transcript entries with `id`, `parent_id`,
`type`, `timestamp`, `message`, and optional `usage`.

Invalid assistant replies are not stored as assistant turns. The loop stores a
correction user message instead. After repeated invalid replies, the failure
assistant message is stored.

## Tool Model

The active tool surface is:

- `read_file(path, start_line=None, end_line=None)`
- `write_file(path, content)`
- `run_command(command)`

`read_file`:

- requires an absolute path
- reads UTF-8 text
- can read any absolute path reachable by the process, not only files under
  `repo_root`
- supports optional 1-based inclusive `start_line` and `end_line`
- rejects line ranges below 1 and rejects `end_line < start_line`
- returns selected range metadata: `start_line`, `end_line`, `total_lines`, and
  `ranged`
- returns an empty string for a valid ranged read starting after EOF
- does not truncate ranged reads
- truncates whole-file reads with shared head/tail truncation at 12,000
  characters
- reports content truncation metadata in the result dictionary

`write_file`:

- requires an absolute path
- writes the full file content as UTF-8 text
- returns compact metadata instead of echoing the written content
- can write any absolute path reachable by the process, not only files under
  `repo_root`
- does not create parent directories explicitly
- is snapshotted by `ToolExecutor` before mutation when undo storage is wired

`run_command`:

- runs a shell command with `shell=True`
- uses `repo_root` as the working directory
- merges stderr into stdout
- times out after 10 seconds
- returns `ok` based on process return code
- returns a normalized timeout failure with `timed_out: True`
- truncates large output with shared head/tail truncation at 12,000 characters
- is not undo-protected, even if it mutates files

There is no patch/edit tool, structured search tool, repo-policy tool,
dedicated test runner, browser tool, or plugin-provided tool. Discovery,
verification, and most shell behavior go through `run_command`.

## Approval

Approval is a runtime gate in the agent loop, not a prompt convention.

Current modes:

- `never`: approve all tool actions
- `always`: prompt before every tool action

The approval policy receives normalized tool actions before execution. If a
user denies an action, the action is not executed and the model receives a
failed tool result with `user denied tool action`.

Approval is not a sandbox. In `always` mode the user can decline a proposed
action, but approved `run_command` actions still execute through the shell and
approved file tools still use absolute paths.

## Provider And Error Handling

The provider layer is OpenAI-compatible rather than LM Studio-specific. LM
Studio remains the default local-server configuration, but the transport class
only knows how to call an OpenAI-compatible chat-completions endpoint.

Provider request failures are handled as follows:

1. `OpenAICompatibleProvider.create_response(...)` performs the raw request.
2. `ModelAdapter.respond(...)` wraps provider exceptions as
   `ModelRequestError("Model request failed")`.
3. `main.py` catches `ModelRequestError`.
4. The session status is updated to `failed`.
5. `storage/error_log.py` writes a diagnostic traceback to:

   ```text
   .code-squid/logs/latest.log
   ```

6. The CLI prints a short friendly message and the log path instead of dumping a
   provider traceback into normal terminal output.

The error log is intentionally narrow. It writes a UTC timestamp and traceback
details, and avoids prompts, payloads, tool outputs, file contents, headers, and
API keys. The log is latest-only, not a permanent history.

## Session Storage

Saved sessions live under:

```text
.code-squid/sessions/<session_id>/
```

Each session folder contains:

- `metadata.json`
- `session.jsonl`

Session IDs are human-readable timestamp plus task slug, with a short random
suffix if needed to avoid collisions.

`metadata.json` records session-level information such as task, status,
timestamps, repo root, and active leaf id. `session.jsonl` records append-only
message entries.

Current session statuses are:

- `active`: the session is currently running or ready to continue
- `complete`: the last task or follow-up completed
- `interrupted`: Ctrl+C stopped the run
- `failed`: repeated invalid replies, model request failure, or tool-step limit
  stopped the run
- `abandoned`: valid metadata status, but not wired to a command

`complete` is not permanently sealed. Resuming a complete session appends a
follow-up user message and continues the same saved session.

The saved-session viewer is intentionally plain and can be noisy. It is a small
inspection aid, not a polished transcript UI.

## Resume Behavior

Resume loads saved messages, appends a follow-up user message, marks the session
`active`, creates a new latest-only undo buffer for the resumed session, and
continues the same saved session.

The in-memory `Session` receives the saved transcript before the loop starts.
`AgentLoop` detects that messages already exist and does not append the initial
system/user messages again.

Follow-up wording belongs to `agent/coding.py`; prompt text itself remains in
`agent/prompts.py`.

The in-memory `files_read` and `files_written` sets are not reconstructed from
the saved transcript on resume. They track side effects seen in the current
process.

## Undo Behavior

The latest-only undo buffer lives under:

```text
.code-squid/undo/
```

It contains:

- `metadata.json`
- `index.json`
- `files/`

Starting a new run or resume creates or replaces the undo buffer.

`ToolExecutor` snapshots `write_file` targets before mutation. Snapshotting
happens only for `write_file`; commands are not snapshotted. Repeated writes to
the same path keep the first pre-change snapshot so undo restores the file to
its state before the latest file-changing run touched it.

If a snapshotted file did not exist before the write, undo deletes it if it
exists. If it did exist, undo restores the saved bytes and creates parent
directories as needed.

Undo is invoked with:

```bash
python main.py undo
```

Undo is separate from sessions:

- sessions record what happened
- undo restores files from before the latest file-changing run

There is no permanent undo history.

## Interaction And Display

The intended interaction style is conversational and stepwise. The prompt asks
the model to choose one immediate tool call, then optionally narrate that same
step in one or two short sentences.

Runtime enforcement is narrower:

- it enforces the number of tool actions before completion
- it enforces no tool action in the final response
- it enforces final-marker placement
- it enforces the required final-summary labels
- it rejects malformed tool calls before they enter assistant history
- it rejects invalid assistant replies before they enter normal assistant
  history
- it records session status for completion, interruption, repeated invalid
  replies, tool-step-limit failure, and model request failure
- it gates tool execution through approval policy
- it snapshots `write_file` targets for latest-run undo

It does not enforce tone, brevity, whether the model read enough context before
writing, whether verification was actually run, whether final-summary claims
match the transcript, or whether narration matches the chosen tool. Those are
prompt-level expectations and testable workflow conventions, not hard runtime
guarantees.

The terminal UI is intentionally small. In normal mode it formats final
summaries, summarizes common pytest output, and prints compact file/action
labels. In debug mode it prints rawer model replies, actions, tool results,
transcript content, and disables spinner animation.

## Platform Assumptions

The implementation assumes Python and a Unix-like shell environment.

Concrete assumptions in the current code:

- `main.py` runs from the intended repository root.
- `Path(".").resolve()` is the workspace root.
- `run_command` uses `subprocess.run(..., shell=True)`, so command behavior is
  shell- and platform-dependent.
- The default provider endpoint is `http://127.0.0.1:1234/v1`, matching common
  local OpenAI-compatible server usage.
- The default model name is `qwen3.5-9b`.
- `.code-squid/settings.json` and supported environment variables can override
  provider, display, approval, and tool-step settings.
- File tools use absolute paths and do not confine access to the repository.
- The code imports local packages as top-level modules (`agent`, `config`,
  `core`, `tools`, `providers`, `storage`, `ui`), so tests may need the repo
  root on `PYTHONPATH` depending on how pytest is invoked.

## Current Strengths

- The runtime loop is short and easy to trace.
- Generic runtime flow is separated from coding-agent policy.
- Provider transport is separated from provider-response normalization.
- Provider request failure handling has a clear boundary and friendly CLI path.
- Settings are centralized and covered by tests.
- Approval policy is UI-agnostic and wired into the tool execution path.
- Tool execution is separated from tool-result transcript formatting.
- Session persistence is separated from in-memory transcript state.
- Latest-run undo is separated from session history.
- The non-final tool-count contract is runtime-enforced.
- Final-marker placement, required final-summary labels, and final-with-tool-call
  rejection are runtime-enforced.
- Provider tool-call metadata and matching tool-result IDs are preserved.
- Tool result formatting guards against action/result length mismatches.
- Tool outputs use consistent dictionaries rather than free-form observations.
- `read_file` supports line ranges and whole-file truncation.
- `run_command` has timeout handling and output truncation.
- The small static tool set keeps the model's action space simple.
- Invalid assistant replies are rejected before entering normal transcript
  history.
- Repeated invalid replies and tool-step limits have deterministic stop paths.
- Terminal spinner behavior is isolated from runtime behavior.

## Current Constraints And Known Limitations

- There is no filesystem sandbox. Absolute-path file tools can read or write
  outside the repository if the process has permission.
- `run_command` executes arbitrary shell commands with `shell=True`.
- Approval is optional and is not a sandbox.
- There is no compaction yet.
- There is no token/cost tracking beyond storing optional provider `usage` when
  available.
- There is no permanent undo history.
- Undo only protects writes made through `write_file`; file mutations performed
  by `run_command` are not snapshotted.
- There is no full CLI framework or TUI.
- There is no structured planner, multi-agent coordination, or background task
  execution.
- There is no hooks system, plugin system, or dynamic tool registration.
- There is no programmatic runner seam for embedding Code Squid outside the CLI
  wiring.
- There is no runtime check that the agent verified its work before finalizing.
- There is no runtime check that final-summary claims are truthful.
- There is no runtime check that narration matches the chosen tool.
- Tool argument validation is shallow and based on required field presence.
- `write_file` replaces whole files; there is no structured diff or patch
  application.
- Discovery depends on shell commands rather than a dedicated search API.
- The saved session viewer is intentionally plain and can be noisy.
- Browser and visual app behavior is still manually verified by the user.
  `node --check` only verifies JavaScript syntax.
- The provider layer currently targets OpenAI-compatible chat completions through
  the OpenAI client; other provider shapes would need adapters.

## Validation Scope

The repository contains focused unit tests for core contracts. It does not
contain broad integration tests for live model behavior, provider compatibility,
end-to-end coding tasks, command safety, transcript truthfulness, browser visual
quality, or game feel.

Current tests cover selected behavior in:

- settings loading and environment overrides
- approval policy and terminal approval prompting
- `CodingAgent.validate_reply(...)`
- `CodingAgent.is_final_content(...)`
- `CodingAgent.should_stop(...)`
- `CodingAgent.failure_message_for_invalid_replies(...)`
- `AgentLoop`
- `ModelAdapter`
- `ToolExecutor`
- `ToolResults`
- `read_file`
- `write_file`
- `run_command`
- `SessionStore`
- `SessionIndex`
- `UndoStore`
- `error_log`
- `TerminalDisplay`
- `TerminalSpinner`
- `main.py` command dispatch paths

Important gaps:

- no live provider integration tests
- no tests proving verification happened before finalization
- no tests proving final-summary claims are truthful
- no tests for browser visual correctness or app quality
- no tests for command safety or filesystem isolation
- no tests for permanent undo history because it does not exist
- no broad end-to-end coding-task regression suite

Manual verification in this repo currently works with:

```bash
PYTHONPATH=. .venv/bin/pytest -q
```

## Architectural Boundary Summary

Code Squid's current architecture is a single-agent, single-process runtime with
settings, optional approval, append-only saved sessions, latest-only undo, and a
small OpenAI-compatible provider boundary.

The hard boundary between layers is:

- settings loading returns validated configuration
- provider transport returns raw model responses
- model adapter normalizes responses into assistant messages plus actions
- coding agent validates whether the normalized reply is acceptable
- loop stores only valid assistant messages
- approval policy decides whether each tool action may execute
- tool executor runs approved actions and records side effects
- tool result formatter turns execution results back into transcript messages
- session storage persists what happened
- undo storage preserves latest pre-write file states for `write_file`
- error logging records diagnostic tracebacks for model request failures

The runtime should stay generic below `agent/`. Coding-specific policy belongs
in `agent/coding.py` and `agent/prompts.py`. Tool behavior belongs in `tools/`.
Provider-specific transport belongs in `providers/`. Settings belong in
`config/`. Session, undo, and error persistence belong in `storage/`. Terminal
display belongs in `ui/`.

When maintaining this repo, treat prompt text as guidance and Python validation
as enforcement. If a behavior is important enough to rely on, it belongs in code
or tests, not only in the prompt.

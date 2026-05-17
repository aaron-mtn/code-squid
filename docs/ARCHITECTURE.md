# Code Squid Architecture

## Purpose

Code Squid is a minimal standalone coding agent for repository work.

The current system runs interactive coding tasks from the command line, sends
the transcript to an OpenAI-compatible chat-completions provider, accepts model
tool calls, executes a small local tool set, and keeps looping until the coding
agent accepts a final assistant message.

The default transport targets LM Studio through the OpenAI Python client. The
only required external dependency is still the OpenAI client.

The codebase is intentionally narrow. It is not a general agent framework, a
multi-agent system, a hardened sandbox, or a polished TUI. The main value of the
current architecture is that the loop, contracts, storage, and tool boundaries
are small enough to inspect directly.

The runtime remains simple:

```text
provider -> model adapter -> coding agent policy -> agent loop -> tools -> transcript/session storage
```

`.code-squid/` is local runtime state and should be gitignored.

## Current Component Layout

- `main.py`
  - Thin CLI entry point, object wiring, and small command dispatch.
  - Uses the current directory as `repo_root`.
  - Creates provider, model adapter, session state, session storage, undo
    storage, tool executor, tool result formatter, coding agent, and loop.
  - Dispatches run, session listing/showing, resume, and undo commands.

- `core/`
  - Generic runtime machinery.
  - Owns the loop, transcript/session state, model response normalization, tool
    dispatch, side-effect tracking, pre-write undo snapshot coordination, and
    tool-result message formatting.
  - Should not contain coding-task prompt text.

- `agent/`
  - Coding-agent policy and prompt text.
  - Owns initial messages, available tool definitions, reply validation,
    completion detection, correction messages, follow-up messages, and final
    failure messaging.

- `tools/`
  - Local tool schemas and implementations.
  - Currently contains `read_file`, `write_file`, `run_command`, shared output
    truncation, and a simple static registry.

- `providers/`
  - Raw provider transport.
  - Currently includes a base provider interface and an LM Studio provider using
    the OpenAI Python client against an OpenAI-compatible endpoint.

- `storage/`
  - Local runtime persistence.
  - `session_store.py` owns one session folder.
  - `session_index.py` owns listing, finding, and loading saved sessions.
  - `undo_store.py` owns the latest-only undo buffer.

- `ui/`
  - Small terminal display helpers.
  - `terminal.py` owns live terminal run display.
  - `sessions.py` owns saved-session viewer display.

- `tests/`
  - Focused pytest coverage for the current completion, tool, session, undo,
    and formatting contracts.

## Ownership Boundaries

`main.py` owns wiring and command dispatch. It should stay thin and should not
grow agent policy, tool behavior, provider-specific response parsing, session
storage internals, or undo mechanics.

`core/agent_loop.py` owns generic turn flow. It initializes the transcript when
needed, asks the adapter for a reply, validates the reply through the active
agent, rejects invalid replies by injecting correction user messages, stores
valid assistant messages, executes tool actions, formats tool results, appends
those results to the transcript, and persists session progress.

`AgentLoop` avoids adding initial messages again when the in-memory session
already has messages. This is what allows resume to continue an existing
transcript instead of replaying a fresh system/user prefix.

`core/session.py` owns in-memory transcript state and side-effect tracking:
`messages`, `files_read`, and `files_written`. It does not persist state and
does not interpret the task.

`core/model_adapter.py` owns provider response normalization. It converts raw
chat-completion responses into the internal reply shape:

- `message`: assistant message suitable for transcript storage
- `actions`: normalized tool actions
- `format_error`: empty string or a controlled parsing/validation error

`core/tool_executor.py` owns mechanical tool dispatch. It looks up tools in the
registry, calls the implementation, catches exceptions, returns normalized
failure dictionaries, records successful read/write side effects in the session,
and snapshots write targets before mutation for undo.

`core/tool_results.py` owns conversion of executed tool results into
model-visible `role: "tool"` messages. It also guards against action/result
length mismatches so malformed executor output does not silently create a bad
assistant/tool chain.

`agent/coding.py` owns coding-agent rules. It decides which tools are exposed,
what initial and follow-up messages are used, which replies are valid, when the
loop should stop, which correction messages are sent, and what failure message is
used after repeated invalid replies.

`agent/prompts.py` owns prompt text. It contains behavioral guidance that the
model is asked to follow. Prompt guidance should not be mistaken for runtime
enforcement.

Each tool module owns its own schema and behavior. The registry in
`tools/__init__.py` is static and intentionally small.

`storage/session_store.py` owns the files for one session folder.
`storage/session_index.py` owns discovery and loading across saved sessions.
`storage/undo_store.py` owns the latest undo buffer.

`ui/terminal.py` owns live terminal display. `ui/sessions.py` owns saved-session
viewer display.

`providers/lmstudio.py` owns only the raw `chat.completions.create(...)` call. It
does not normalize responses or apply agent policy.

## Core Contracts

### Turn Contract

Before completion, a valid assistant reply must include exactly one normalized
tool action.

The runtime enforces:

- malformed tool-call output is rejected
- unknown tool names are rejected during model-adapter validation
- missing required tool arguments are rejected during model-adapter validation
- non-final replies with zero tool actions are rejected
- non-final replies with more than one tool action are rejected
- final replies that also include tool actions are rejected

The runtime does not currently enforce that narration accurately describes the
tool call. That is prompt-enforced guidance only.

### Final Contract

A valid final assistant reply must:

- include no tool calls
- have `TASK COMPLETE` as the final non-empty line
- include these exact required labels:
  - `Files changed:`
  - `What changed:`
  - `Verification run:`
  - `Remaining risks:`

These labels are runtime-enforced, not prompt-only guidance.

The prompt still provides the expected formatting, but the loop rejects final
replies that omit the required summary sections.

### Invalid Reply Budget

The loop tracks consecutive invalid replies and stops after 3 consecutive
invalid replies.

- A valid reply resets the counter.
- `AgentLoop` owns the counter and the stop decision.
- `CodingAgent` owns the human-readable failure message via
  `failure_message_for_invalid_replies(...)`.

Repeated invalid replies record a failed session status.

### Transcript Contract

Assistant messages that used tools preserve provider `tool_calls` metadata.
Tool-result messages include the matching `tool_call_id`.

This matters because stricter OpenAI-compatible model templates expect
assistant/tool/result chains to be replayable in that shape.

`session.jsonl` stores append-only transcript entries with `id`, `parent_id`,
`timestamp`, `message`, and optional `usage`.

### Tool Argument Contract

The model adapter validates known tool names and required argument presence by
reading the registered tool definitions. It does not perform full JSON Schema
validation for argument types or additional properties.

Tool implementations perform their own local checks where they have them. For
example, `read_file` and `write_file` reject relative paths.

## Tool Model

The active tool surface is:

- `read_file(path)`
- `write_file(path, content)`
- `run_command(command)`

`read_file`:

- requires an absolute path
- reads the whole file as UTF-8 text
- returns the full file content
- has no built-in range support or truncation
- can read any absolute path reachable by the process, not only files under
  `repo_root`

`write_file`:

- requires an absolute path
- writes the full file content as UTF-8 text
- returns compact metadata instead of echoing the written content
- can write any absolute path reachable by the process, not only files under
  `repo_root`
- does not create parent directories explicitly

`run_command`:

- runs a shell command with `shell=True`
- uses `repo_root` as the working directory
- merges stderr into stdout
- times out after 10 seconds
- returns `ok` based on process return code
- returns a normalized timeout failure with `timed_out: True`
- truncates large output with a head/tail strategy at 12,000 characters

There is no patch/edit tool, structured search tool, repo-policy tool, or
dedicated test runner. Discovery, verification, and most shell behavior go
through `run_command`.

## Session Storage

Saved sessions live under:

```text
.code-squid/sessions/<session_id>/
```

Each session folder contains:

- `metadata.json`
- `session.jsonl`

Session IDs are human-readable timestamp plus task slug.

`metadata.json` records session-level information such as task, status,
timestamps, repo root, and active leaf id. `session.jsonl` records append-only
message entries.

The current session statuses are:

- `active`: the session is currently running or ready to continue
- `complete`: the last task or follow-up completed
- `interrupted`: Ctrl+C stopped the run
- `failed`: repeated invalid replies stopped the run
- `abandoned`: valid status, but not yet wired to a command

`complete` is not permanently sealed. Resuming a complete session appends a
follow-up user message and continues the same saved session.

The current session commands are:

```bash
python main.py sessions
python main.py show latest
python main.py show <session_id>
python main.py resume latest
python main.py resume <session_id>
```

The saved-session viewer is intentionally plain and can be noisy. It is a small
inspection aid, not a polished transcript UI.

## Resume Behavior

Resume loads saved messages, appends a follow-up user message, and continues the
same session.

The in-memory `Session` receives the saved transcript before the loop starts.
`AgentLoop` detects that messages already exist and does not append the initial
system/user messages again.

Follow-up wording belongs to `agent/coding.py`; the prompt text itself remains in
`agent/prompts.py`.

## Undo Behavior

The latest-only undo buffer lives under:

```text
.code-squid/undo/
```

It contains:

- `metadata.json`
- `index.json`
- `files/`

Starting a new run creates or replaces the undo buffer.

`ToolExecutor` snapshots `write_file` targets before mutation. Snapshotting
happens only for `write_file`; commands are not snapshotted. Repeated writes to
the same path keep the first pre-change snapshot so undo restores the file to
its state before the latest file-changing run touched it.

Undo is invoked with:

```bash
python main.py undo
```

Undo is separate from sessions:

- sessions record what happened
- undo restores files from before the latest file-changing run

There is no permanent undo history.

## Current CLI Commands

```bash
python main.py
python main.py sessions
python main.py show latest
python main.py show <session_id>
python main.py resume latest
python main.py resume <session_id>
python main.py undo
```

## Interaction Style

The intended interaction style is conversational and stepwise. The prompt asks
the model to choose one immediate tool call, then optionally narrate that same
step in one or two short sentences.

Runtime enforcement is narrower:

- it enforces the number of tool actions before completion
- it enforces no tool action in the final response
- it enforces final-marker placement
- it enforces the required final-summary labels
- it rejects malformed tool calls before they enter assistant history
- it rejects invalid assistant replies before they enter normal assistant history
- it records session status for completion, interruption, and repeated invalid
  replies
- it snapshots `write_file` targets for latest-run undo

It does not enforce tone, brevity, whether the model read enough context before
writing, whether verification was actually run, or whether final-summary claims
match the transcript. Those are currently prompt-level expectations and testable
workflow conventions, not hard runtime guarantees.

The runtime still targets terminal interaction. Live run display goes through a
small UI helper layer, but there is no full CLI framework or TUI.

## Platform Assumptions

The implementation assumes Python and a Unix-like shell environment.

Concrete assumptions in the current code:

- `main.py` runs from the intended repository root.
- `Path(".").resolve()` is the workspace root.
- `run_command` uses `subprocess.run(..., shell=True)`, so command behavior is
  shell- and platform-dependent.
- The default provider endpoint is `http://127.0.0.1:1234/v1`, matching common
  LM Studio local-server usage.
- The default model name is `qwen3.5-9b`.
- `CODE_SQUID_BASE_URL`, `CODE_SQUID_API_KEY`, and `CODE_SQUID_MODEL` can
  override provider settings.
- File tools use absolute paths and do not confine access to the repository.
- The code imports local packages as top-level modules (`agent`, `core`,
  `tools`, `providers`, `storage`, `ui`), so tests may need the repo root on
  `PYTHONPATH` depending on how pytest is invoked.

## Current Strengths

- The runtime loop is short and easy to trace.
- Generic runtime flow is separated from coding-agent policy.
- Provider transport is separated from provider-response normalization.
- Tool execution is separated from tool-result transcript formatting.
- Session persistence is separated from in-memory transcript state.
- Latest-run undo is separated from session history.
- The non-final tool-count contract is runtime-enforced.
- Final-marker placement, required final-summary labels, and final-with-tool-call
  rejection are runtime-enforced.
- Provider tool-call metadata and matching tool-result IDs are preserved.
- Tool result formatting guards against action/result length mismatches.
- Tool outputs use consistent dictionaries rather than free-form observations.
- `run_command` has timeout handling and output truncation.
- The small static tool set keeps the model's action space simple.
- Invalid assistant replies are rejected before entering normal transcript
  history.
- Repeated invalid replies have a deterministic stop path.

## Current Constraints and Known Limitations

- There is no filesystem sandbox. Absolute-path file tools can read or write
  outside the repository if the process has permission.
- `run_command` executes arbitrary shell commands with `shell=True`.
- There is no approval gate for writes or commands.
- There is no compaction yet.
- There is no token/cost tracking yet.
- There is no settings file yet.
- There is no permanent undo history.
- Undo only protects writes made through `write_file`; file mutations performed
  by `run_command` are not snapshotted.
- There is no full CLI framework or TUI.
- There is no structured planner, multi-agent coordination, or background task
  execution.
- There is no runtime check that the agent verified its work before finalizing.
- There is no runtime check that final-summary claims are truthful.
- There is no runtime check that narration matches the chosen tool.
- Tool argument validation is shallow and based on required field presence.
- `read_file` returns whole files without truncation.
- `write_file` replaces whole files; there is no structured diff or patch
  application.
- Discovery depends on shell commands rather than a dedicated search API.
- The saved session viewer is intentionally plain and can be noisy.
- Browser and visual app behavior is still manually verified by the user.
  `node --check` only verifies JavaScript syntax.
- The provider layer currently targets OpenAI-compatible chat completions through
  the OpenAI client; other provider shapes would need adapters.

## Real-Task Smoke Tests

Early practical smoke tests are positive, but they should not be read as broad
coverage or solved behavior.

- Basic bugfix evals pass.
- The canonical verification eval passed: the agent read README/AGENTS guidance,
  used the repo's canonical `./scripts/test.sh -rs` path, and completed
  successfully.
- A pseudo-3D canvas flight toy was generated and ran in the browser, though
  visual and game-feel quality was weak. This showed app generation works at a
  basic level, while visual quality needs stronger feedback or stronger models.
- A plain HTML/CSS/JS Kanban app was generated successfully with
  add/move/delete/localStorage behavior.
- A follow-up patch fixed the Kanban movement behavior and converted it to dark
  mode.

These smoke tests suggest basic app-making ability is passing so far with
`qwen3.5-9b`, but stronger models and more evals are still needed.

## Validation Scope

The repository contains focused unit tests for core contracts. It does not
contain broad integration tests for live model behavior, provider compatibility,
end-to-end coding tasks, command safety, transcript truthfulness, browser visual
quality, or game feel.

Validation that exists today is best described as contract regression coverage
for selected pieces of the local runtime, storage, undo, and tools.

Manual verification in this repo currently works with:

```bash
PYTHONPATH=. .venv/bin/pytest -q
```

## Tests and Regression Coverage

Current tests cover selected behavior in:

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

Important gaps:

- no live provider integration tests
- no tests proving verification happened before finalization
- no tests proving final-summary claims are truthful
- no tests for browser visual correctness or app quality
- no tests for command safety or filesystem isolation
- no tests for permanent undo history because it does not exist

## Architectural Boundaries

Code Squid's current architecture is a single-agent, single-process runtime with
append-only saved sessions and a latest-only undo buffer.

The hard boundary between layers is:

- provider transport returns raw model responses
- model adapter normalizes responses into assistant messages plus actions
- coding agent validates whether the normalized reply is acceptable
- loop stores only valid assistant messages
- tool executor runs accepted actions and records side effects
- tool result formatter turns execution results back into transcript messages
- session storage persists what happened
- undo storage preserves the latest pre-write file states

The runtime should stay generic below `agent/`. Coding-specific policy belongs in
`agent/coding.py` and `agent/prompts.py`. Tool behavior belongs in `tools/`.
Provider-specific transport belongs in `providers/`. Session and undo persistence
belong in `storage/`. Terminal display belongs in `ui/`.

The architecture currently does not include plugin loading, dynamic tool
registration, workspace isolation, command approvals, long-term memory, a GUI,
or a provider abstraction beyond the minimal `BaseProvider.create_response(...)`
shape.

When maintaining this repo, treat prompt text as guidance and Python validation
as enforcement. If a behavior is important enough to rely on, it belongs in code
or tests, not only in the prompt.

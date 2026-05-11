# Code Squid Architecture

## Purpose

Code Squid is a minimal standalone coding agent for repository work.

The current system runs one interactive coding task from the command line, sends
the transcript to an OpenAI-compatible chat-completions provider, accepts model
tool calls, executes a small local tool set, and keeps looping until the coding
agent accepts a final assistant message.

The codebase is intentionally narrow. It is not a general agent framework, a
multi-agent system, a persistent assistant, or a hardened sandbox. The main value
of the current architecture is that the loop, contracts, and tool boundaries are
small enough to inspect directly.

## Current Component Layout

- `main.py`
  - CLI entry point and object wiring.
  - Reads one task from `input("Task: ")`.
  - Uses the current directory as `repo_root`.
  - Creates the session, LM Studio provider, model adapter, tool executor, tool
    result formatter, coding agent, and loop.
  - Prints debug output, final tracked read/write sets, and the full transcript
    after the loop stops.

- `core/`
  - Generic runtime machinery.
  - Owns the loop, transcript/session state, model response normalization, tool
    dispatch, and tool-result message formatting.
  - Should not contain coding-task policy or prompt text.

- `agent/`
  - Coding-agent policy and prompt text.
  - Owns initial messages, available tool definitions, reply validation,
    completion detection, and correction messages.

- `tools/`
  - Local tool schemas and implementations.
  - Currently contains `read_file`, `write_file`, `run_command`, shared output
    truncation, and a simple static registry.

- `providers/`
  - Raw provider transport.
  - Currently includes a base provider interface and an LM Studio provider using
    the OpenAI Python client against an OpenAI-compatible endpoint.

- `tests/`
  - Focused pytest coverage for the current completion and tool contracts.

## Ownership Boundaries

`main.py` owns wiring only. It should stay thin and should not grow agent policy,
tool behavior, or provider-specific response parsing.

`core/agent_loop.py` owns turn flow. It initializes the transcript, asks the
adapter for a reply, validates the reply through the active agent, rejects invalid
replies by injecting correction user messages, stores valid assistant messages,
executes tool actions, formats tool results, and appends those results to the
transcript.

`core/session.py` owns in-memory session state: `messages`, `files_read`, and
`files_written`. It does not persist state and does not interpret the task.

`core/model_adapter.py` owns provider response normalization. It converts raw
chat-completion responses into the internal reply shape:

- `message`: assistant message suitable for transcript storage
- `actions`: normalized tool actions
- `format_error`: empty string or a controlled parsing/validation error

`core/tool_executor.py` owns mechanical tool dispatch. It looks up tools in the
registry, calls the implementation, catches exceptions, returns normalized
failure dictionaries, and records successful read/write side effects in the
session.

`core/tool_results.py` owns conversion of executed tool results into
model-visible `role: "tool"` messages.

`agent/coding.py` owns coding-agent rules. It decides which tools are exposed,
what initial messages are used, which replies are valid, and when the loop should
stop.

`agent/prompts.py` owns prompt text. It contains behavioral guidance that the
model is asked to follow. Prompt guidance should not be mistaken for runtime
enforcement.

Each tool module owns its own schema and behavior. The registry in
`tools/__init__.py` is static and intentionally small.

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

The prompt asks the model to include:

- `Files changed`
- `What changed`
- `Verification run`
- `Remaining risks`

The current runtime does not parse or enforce those final-summary fields. It only
checks the absence of tool calls and final-marker placement.

### Transcript Contract

Assistant messages that used tools preserve provider `tool_calls` metadata.
Tool-result messages include the matching `tool_call_id`.

This matters because stricter OpenAI-compatible model templates expect
assistant/tool/result chains to be replayable in that shape.

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

## Interaction Style

The intended interaction style is conversational and stepwise. The prompt asks
the model to choose one immediate tool call, then optionally narrate that same
step in one or two short sentences.

Runtime enforcement is narrower:

- it enforces the number of tool actions before completion
- it enforces no tool action in the final response
- it enforces final-marker placement
- it rejects malformed tool calls before they enter assistant history

It does not enforce tone, brevity, whether the model read enough context before
writing, whether verification was actually run, or whether final-summary claims
match the transcript. Those are currently prompt-level expectations and testable
workflow conventions, not hard runtime guarantees.

The loop prints debugging information directly to stdout. This includes model
requests/replies, selected actions, tool results, stop status, tracked file sets,
and the final transcript. There is no separate UI layer.

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
  `tools`, `providers`), so tests may need the repo root on `PYTHONPATH`
  depending on how pytest is invoked.

## Current Strengths

- The runtime loop is short and easy to trace.
- Generic runtime flow is separated from coding-agent policy.
- Provider transport is separated from provider-response normalization.
- Tool execution is separated from tool-result transcript formatting.
- The non-final tool-count contract is runtime-enforced.
- Final-marker placement and final-with-tool-call rejection are
  runtime-enforced.
- Provider tool-call metadata and matching tool-result IDs are preserved.
- Tool outputs use consistent dictionaries rather than free-form observations.
- `run_command` has timeout handling and output truncation.
- The small static tool set keeps the model's action space simple.
- invalid assistant replies are rejected before entering normal transcript history

## Current Constraints and Known Limitations

- There is no filesystem sandbox. Absolute-path file tools can read or write
  outside the repository if the process has permission.
- `run_command` executes arbitrary shell commands with `shell=True`.
- There is no approval gate for writes or commands.
- There is no persistent memory, task database, or run metadata store.
- There is no structured planner, multi-agent coordination, or background task
  execution.
- There is no runtime check that the agent verified its work before finalizing.
- There is no runtime check that final-summary fields are present or truthful.
- There is no runtime check that narration matches the chosen tool.
- Tool argument validation is shallow and based on required field presence.
- `read_file` returns whole files without truncation.
- `write_file` replaces whole files; there is no structured diff or patch
  application.
- Discovery depends on shell commands rather than a dedicated search API.
- The provider layer currently targets OpenAI-compatible chat completions through
  the OpenAI client; other provider shapes would need adapters.
- The application is a CLI/debug loop, not a packaged command with polished
  installation, configuration, or logging.

## Validation Scope

The repository contains focused unit tests for a few core contracts. It does not
contain broad integration tests for live model behavior, provider compatibility,
end-to-end coding tasks, command safety, or transcript truthfulness.

Validation that exists today is best described as contract regression coverage
for selected pieces of the local runtime and tools.

Manual verification in this repo currently works with:

```bash
PYTHONPATH=. .venv/bin/pytest -q
```

In the current environment, plain `pytest -q` was not available on `PATH`, and
`.venv/bin/pytest -q` without `PYTHONPATH=.` failed to import top-level local
packages.

## Tests and Regression Coverage

Current tests cover:

- `CodingAgent.is_final_content(...)` accepts `TASK COMPLETE` on the final
  non-empty line.
- `CodingAgent.should_stop(...)` stops on a final assistant message with no tool
  calls.
- final marker text is rejected when it is not the final non-empty line.
- `read_file` rejects relative paths and succeeds with absolute paths.
- `write_file` rejects relative paths, succeeds with absolute paths, writes the
  expected content, and does not echo content in the result.
- `run_command` timeout handling returns a normalized failure result.

Important gaps:

- no tests for `AgentLoop` correction-message flow
- no tests for `ModelAdapter` malformed JSON, unknown tools, missing arguments,
  or tool-call preservation
- no tests for `ToolResults` `tool_call_id` formatting
- no tests for `ToolExecutor` unknown-tool or exception normalization
- no tests for `run_command` successful execution or output truncation
- no tests enforcing final-summary fields
- no tests proving verification happened before finalization
- no live provider integration tests

## Architectural Boundaries

Code Squid's current architecture is a single-agent, single-process,
single-session loop.

The hard boundary between layers is:

- provider transport returns raw model responses
- model adapter normalizes responses into assistant messages plus actions
- coding agent validates whether the normalized reply is acceptable
- loop stores only valid assistant messages
- tool executor runs accepted actions
- tool result formatter turns execution results back into transcript messages

The runtime should stay generic below `agent/`. Coding-specific policy belongs in
`agent/coding.py` and `agent/prompts.py`. Tool behavior belongs in `tools/`.
Provider-specific transport belongs in `providers/`.

The architecture currently does not include plugin loading, dynamic tool
registration, workspace isolation, command approvals, long-term memory, a GUI,
or a provider abstraction beyond the minimal `BaseProvider.create_response(...)`
shape.

When maintaining this repo, treat prompt text as guidance and Python validation
as enforcement. If a behavior is important enough to rely on, it belongs in code
or tests, not only in the prompt.

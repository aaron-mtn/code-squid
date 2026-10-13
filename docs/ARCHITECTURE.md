# Code Squid Architecture

This document describes current ownership, runtime flow, public seams, and
architectural invariants. [Implementation notes](IMPLEMENTATION_NOTES.md) preserve
subsystem mechanics, constants, storage layouts, and maintenance details.

## Purpose

Runtime parameters, session metadata, and tool execution consistently use
`workspace_root`. Core enforces the selected Skill's tool permissions on both
definition exposure and execution. See [runtime context conventions](IMPLEMENTATION_NOTES.md#runtime-context-and-tool-permissions).

Code Squid is a minimal standalone coding agent for repository work.

It runs interactive coding tasks from the command line, sends a replayable
transcript to a model provider, accepts model tool calls, executes a small local
tool set, persists the session, and keeps looping until the Core Agent policy
accepts a final assistant message.

The codebase is intentionally narrow. It is not a general agent framework, a
multi-agent system, a hardened sandbox, or a polished TUI. The main value of the
architecture is that the loop, contracts, storage, configuration, and tool
boundaries are small enough to inspect directly.

The construction and runtime shapes are:

```text
console CLI -> code_squid.agent_setup -> squid_core -> AgentLoop
desktop/other frontend -> code_squid.agent_setup -> squid_core -> AgentLoop
Code Squid settings -> code_squid.provider_setup -> ready provider
ready provider + explicit model/replay inputs -> squid_core.spawner -> ModelAdapter -> AgentLoop
ready ModelAdapter -> squid_core.spawner -> AgentLoop
model adapter -> Core Agent -> action preflight -> approval -> tools -> transcript/session storage
```

`AgentLoop -> on_event callback` is an optional observer path for compact
machine-readable runtime facts.

Private runtime state and application preferences live in the Code Squid home.
Legacy repository-local `.code-squid/` data is neither loaded nor migrated; keep
it gitignored until separately handled.

The dependency direction is one-way: Code Squid supplies application defaults
and runtime wiring to reusable Squid Core components. Those reusable components
do not import Code Squid prompt or policy modules. `code_squid/` is the product
and application layer; `squid_core/` is the reusable agent runtime.

```text
Code Squid -> squid-core
Code Squid -> squid-providers -> squid-core response/provider contracts
squid-core -> no application or concrete transport imports
```

The packages have separate Git repositories and independent packaging. A
convenient editable-development checkout layout is:

```text
<workspace>/code-squid/       # code_squid, main.py, application tests
<workspace>/squid-core/       # squid_core, reusable runtime tests
<workspace>/squid-providers/  # squid_providers, transport/catalog tests
```

Below, `squid_core/` and `squid_providers/` paths refer to their respective
repositories. Neither source package is bundled into Code Squid. Installed
packages do not require sibling directories. `requirements.txt` supports the
editable layout above; README documents public GitHub installation with all
three explicit sources, without assuming Core or Providers is on PyPI.

## Component Layout

- `main.py`
  - Thin standalone process entry point.
  - Calls `code_squid.console.cli.cli_commands.run_cli(sys.argv[1:])` and exits
    with its status code.

- `code_squid/`
  - Code Squid-specific product and application package. It owns coding-agent
    prompt/behavior policy, application setup, paths/settings, and console
    behavior and presentation.
  - Application wiring uses `squid_core.agent.Agent` directly.
    `agent/prompts.py` owns Code Squid identity, its non-replaceable baseline
    coding policy and intentionally replaceable tool/final-report defaults.
  - `agent_setup.py` owns Code Squid run preparation and wiring: settings,
    prompt defaults, configured provider construction/injection,
    application/workspace paths, storage locations, resource
    resolution, hooks, platform context, Agent configuration, and translation
    into the generic `squid_core.spawner` seam. It is presentation-neutral and
    does not import the console frontend.
  - `compaction_context.py` owns Code Squid's deterministic authoritative
    compaction facts. It reads the session store's canonical messages at
    compaction time, removes the exact preserved-tail suffix supplied by Core,
    and understands only the application's built-in Tool activity,
    direct-mutation, verification, and recoverable-failure semantics.
  - `app_paths.py` owns Code Squid application-home policy, the application-wide
    settings path, centralized per-workspace session/undo/error-log locations
    and ownership manifests, the global session-index and recent-workspace
    locations, and paths for loose resources and Mods. The recent
    workspace file is `~/.code-squid/recent-workspaces.json` (or the configured
    application home): a newest-first JSON list of at most ten normalized
    absolute paths. The same app-path module owns its tolerant loading,
    deduplication, and update policy. Reusable Core machinery receives workspace
    paths explicitly and has no knowledge of this product history.
  - `asset_preflight.py` allows built-in reads of the active session's assets
    through Core's supplied preflight seam. It preserves Strict approval and
    Hook reasons without trusting other application state or asset writes.
  - `settings.py` reads the application-home `settings.json`, validates
    supported application input, owns sparse provider-scoped connection
    persistence, applies product defaults and optional `CODE_SQUID_*` environment
    overrides, and translates the result to generic Core settings.
    `squid_providers.settings` owns effective `ProviderSettings` validation and
    reasoning-mode values. `Settings.to_provider_settings()` carries selection,
    model, URL/key, shared sampling/reasoning controls, and provider-owned config;
    `to_runtime_settings()` carries only generic execution settings.
  - `console/cli/` owns launch dispatch, the persistent fresh/resumed prompt
    loop, runtime and control commands, session-run orchestration, and Mod/Skill
    selection. `session_runner.py` constructs the terminal display and contains
    run failures so the prompt remains usable. `startup_menu.py` owns keyboard
    selection state and reuses those operations.
  - `console/ui/` owns terminal presentation and input. `display.py` coordinates
    startup, thinking, streamed narration/reasoning, approval, Tool output, and
    final reporting; sibling modules own geometry, formatting, animation,
    prompts, and saved-session presentation. Presentation does not own Tool
    execution, approval policy, or result semantics.
  - The startup scene uses a temporary alternate-screen prompt_toolkit
    Application. It releases terminal ownership before normal output proceeds;
    only submitted clean frames enter primary scrollback. Ordinary prompts and
    runs append to the same primary transcript, and `/new` preserves history.
    Streaming panels similarly release their renderer before static writers.
    One active writer owns normal output at each lifecycle boundary.
    See [console mechanics](IMPLEMENTATION_NOTES.md#console-presentation-and-input)
    for module locations, scene/input geometry, renderer ownership, buffer
    restoration, selection handoffs, animation, and panel behavior.

- `squid_core/agent/`
  - Reusable Core Agent behavior and protected prompt protocol.
  - `agent.py` owns task and active-Skill state, `skill_name`, active tools,
    platform/workspace context, raw initial and follow-up message construction,
    tool definitions, reply validation, completion detection, reason-specific
    corrections, and repeated-invalid-reply failure construction.
  - `prompts.py` owns the protected tool-batch/final-response protocol, generic
    verification honesty, task-neutral response examples, active-Skill insertion,
    tool-aware execution-environment insertion, and prompt assembly. Narration
    style and coding examples live in Code Squid application defaults.
  - Core consumes application defaults through `PromptDefaults` and does not
    import `code_squid.agent.prompts`.

- `squid_core/compaction/`
  - Generic transcript compaction mechanics, prompt ownership, optional
    app-provided post-summary context, trigger-status reporting, and rough
    transcript token estimation.
  - `compactor.py` owns trigger, chunking, summary, and retention behavior and
    is exposed as `squid_core.compaction.Compactor`.
  - `prompts.py` asks for continuation-critical task, finding, resource,
    action, result, verification, correction, next-step, and risk context
    without Code Squid identity or coding-only language.
  - `compaction_status.py` owns context usage and compaction-trigger reporting.
  - `token_estimate.py` owns the rough transcript token estimation used by
    compaction and status reporting.

- `squid_core/agent_loop/`
  - Reusable agent-runtime sequencing, exposed through
    `squid_core.agent_loop.AgentLoop` and `RunResult`.
  - `loop.py` owns the complete state machine and all decisions about when
    hooks, model turns, validation, events, transcript writes, approval, Tool
    execution, finalization, failure, and cancellation occur.
  - `event_emitter.py` owns compact event payload mechanics, session-ID
    attachment, safe Tool-action projection, bounded event text, and forwarding
    to `squid_core.events.emit_event`.
  - `transcript_recording.py` owns accepted-message writes to the in-memory
    Session and optional SessionStore, runtime user/context message construction,
    and mechanical repair of a pending Tool call/result transcript pair during
    cancellation, interruption, or ordinary exceptional failure. `loop.py`
    funnels those incomplete exits through one unwind path that repairs the
    pair, records terminal lifecycle/status, runs `run_finished`, and then
    preserves the original exception semantics.

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
    `metadata.json`, append-only `session.jsonl` and `model-view.jsonl`, replay
    loading, status updates, compaction/run-context events, and model request/
    reply/rejection diagnostics.
  - `undo_store.py` owns the explicitly located latest-only undo buffer.
  - `atomic_json.py` owns same-directory atomic JSON replacement and bounded
    retry of transient Windows destination locks. Failures propagate without
    discarding the prior destination; see [replacement mechanics](IMPLEMENTATION_NOTES.md#atomic-json-replacement).

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
  - Tool-action preflight, approval policy, deliberately simple command trust,
    and structured file-tool workspace boundaries.
  - This is an approval/preflight boundary, not a hardened sandbox.

- `squid_core/spawner.py`
  - Generic, UI-neutral construction for `AgentRun` and `AgentLoop`.
  - Creates ordinary runtime collaborators when omitted and accepts selected
    collaborators directly when an embedding application replaces them.
  - Consumes only generic `squid_core.settings.RuntimeSettings`; it does not
    import Code Squid configuration, prompts, terminal presentation, or
    resource/Mod discovery.

- `squid_core/providers/`
  - The generic `BaseProvider` contract and `StreamCancelled` control signal
    live here. Core and transports share the same cancellation exception
    identity. Its initializer imports no transport or SDK.

- `squid_providers/`
  - Independent sibling `squid-providers` repository/distribution.
    It imports only `squid_core.model_response` and `squid_core.providers.base`.
    There is no reverse Core dependency or transport-path re-export.
  - `openai_compatible.py` owns SDK requests, native payloads, response/stream
    normalization, reasoning/usage aliases, raw tracing, discovery/readiness,
    vision encoding, and supported OpenRouter quirks.
  - `ollama.py` owns native `/api/chat` transport, finite request timeouts,
    streaming completion checks, discovery/readiness, vision encoding, and
    response normalization. Both transports return Core's `ModelResponse`.
  - `cancellation.py` owns `CancellationMonitor`. Provider I/O remains on the
    caller; the bounded watcher only polls the host predicate and aborts the
    active provider-owned client, including blocked headers/body reads.
  - `catalog.py` owns IDs, friendly names, profiles, URL/key defaults, credential
    variable names, supported scoped config, construction,
    readiness/discovery, and replay policy. Public seams: `PROVIDER_PROFILES`,
    `PROFILES_BY_ID`, `VALID_PROVIDERS`,
    `friendly_provider_name`, `resolve_provider_name`, `validate_config`,
    `resolve_config`, `build_provider`, `provider_ready`, `discover_models`, and
    `tool_call_content_mode`. `settings.py` owns effective `ProviderSettings`
    and shared sampling/reasoning validators.
  - `code_squid.provider_setup` consumes the catalog for saved choices and
    status. It contains no concrete IDs or transport imports. A ready adapter
    or custom provider bypasses default transport construction.

- Flat `squid_core/*.py` runtime concepts
  - `events.py` owns observation; `generation.py` owns one-shot generation;
    `model_adapter.py` owns final provider request preparation, generic
    best-effort request observation at the shared transport boundary, and
    generic response validation and transcript reply construction.
    `model_response.py` defines completed output types; providers resolve native
    aliases before the adapter copies their single reasoning value to
    `reply["reasoning"]`. Its optional streaming callback forwards normalized
    reasoning deltas from providers that support the seam. The Agent loop
    publishes `assistant_reasoning_delta` as chunks arrive and a non-empty
    `assistant_reasoning` event before the matching narration/final event and
    Tool start. `settings.py` owns generic runtime/
    compaction and tool-result trimming semantics; `tool_result_trimming.py`
    owns the request-only rendering of older built-in Tool payloads and reports
    exact retained source-line ranges when it trims a `read_file` result;
    `platform_context.py` describes the environment; `spawner.py` owns generic
    construction and wires finalized request observations to the active session
    store; `session.py` owns in-memory transcript state; and `skills.py` owns
    standalone Skills.
  - Resource modules accept explicit application homes or resource roots. They
    do not import Code Squid's application-home policy.

- `scripts/`
  - Small repo-maintenance helpers.
  - `update_filetree.py` generates `docs/filetree.md` from the current
    repository tree and Python docstrings.

- `tests/` in Code Squid covers persistence, selection/model UX, injection,
  CLI/Desktop orchestration, and presentation. Core tests contracts,
  adapter/retries, AgentLoop, generation/spawner injection, compaction, tools,
  storage, and resource handling. Providers tests catalog/config, construction,
  discovery/readiness, transports, normalization, tracing, cancellation, replay
  quirks, and vision wire conversion. Tests are separated by ownership.
  Fresh-process import guards and source checks enforce dependency direction.

- Packaging and support files
  - Code Squid's root `pyproject.toml` builds only `code_squid` and `main.py`,
    requiring Core, Providers, prompt_toolkit, and wcwidth.
  - Squid Core's `pyproject.toml` builds only Core, without mandatory transport
    dependencies. Its `documents` extra supplies document/image reader libraries.
  - `../squid-providers/pyproject.toml` builds only Providers, requiring Core,
    OpenAI, and httpx. Code Squid pins Core and Providers to `0.1.0`; source
    installation supplies those distributions explicitly from GitHub or checkouts.
  - `README.md`, `docs/ARCHITECTURE.md`, and `docs/IMPLEMENTATION_NOTES.md`
    are the public documentation.
    Private development history and the historical extraction record stay local,
    untracked and excluded by `MANIFEST.in`; generated file trees are local too.
  - Code Squid `0.1.0` metadata declares Python 3.11+, Aaron Slater, the README,
    and MIT licensing. `code-squid` dispatches to `main:main`. Package discovery
    is limited to `code_squid` and its subpackages plus the `main` module;
    `include-package-data = false` keeps local resource data out of the wheel.
    The source distribution includes both public technical references and excludes
    private history, runtime state, environments, and build/cache artifacts.

## Events And External Wrappers

Code Squid can emit small runtime event dictionaries through optional
`on_event(event)` callbacks. If no callback is supplied, nothing changes.

This path is intended for frontends, external Python wrappers, and tiny host
applications such as local event viewers. Events are machine-readable facts,
not preformatted terminal output. The CLI consumes only the streamed-assistant
subset through its product-owned display; other wrappers should not scrape
terminal output.

Current loop-level event types include:

- `run_started`
- `hooks_configured`
- `hook_execution`
- `model_request_started`
- `model_request_retry_scheduled`
- `model_request_retry_started`
- `model_request_finished`
- `model_request_failed`
- `assistant_message_started`
- `assistant_reasoning_delta`
- `assistant_delta`
- `assistant_reasoning`
- `assistant_message`
- `tool_preparing`
- `tool_started`
- `tool_finished`
- `reply_rejected`
- `final_message`
- `run_failed`
- `run_interrupted`
- `run_finished`

Assistant-text events identify their semantic phase without introducing a
separate model call. `assistant_message_started`,
`assistant_delta`, and `assistant_message` carry `phase: "narration"` for
user-visible mid-turn text that may be followed by tool activity.
`assistant_reasoning_delta` carries `phase: "reasoning"` and one normalized
provider chunk while it arrives. `assistant_reasoning` carries the completed,
normalized provider-exposed text before its matching narration or final event.
`final_message` carries `phase: "final"` for the terminal assistant response.
`tool_preparing` remains the transition from streamed narration into structured
tool-call preparation and does not carry an assistant-text phase.

Event payloads should stay compact. They must not include raw file contents,
full command output, prompts, duplicated message bodies, provider payloads, API
keys, headers, or secrets. Model-request lifecycle events retain only
provider/model identity when available, effective normalized reasoning mode and
token budget when configured, message count, a rough request-token estimate,
duration, attempt counts, conservative failure classification, and bounded,
credential-redacted underlying provider details when available. Retry events
share this same main run log; no retry transcript or separate log exists. These
events, plus `run_failed`
and `run_interrupted`, are appended to the session's existing linked JSONL log
before terminal status changes; they remain diagnostic entries and are never
replayed as model transcript messages.

`hooks_configured` records the installed Hook class names once per run.
`hook_execution` records one implemented-handler invocation with `hook`, `seam`,
`status` (`no_effect`, `effect`, or `error`), `produced_effect`, and an `effects`
list. Errors add only `error_type`. Effect names describe the response category,
such as `context_blocks`, `block`, `updated_action`, `approval_reasons`,
`updated_tool_output`, `additional_context`, `report_note`,
`follow_up_requests`, or `notes`; Hook-returned text and payload data are not
copied into the event. The runner emits these records through the same durable
runtime-event path as model-request diagnostics, and observer/persistence
failure while reporting a Hook outcome cannot alter the Hook's behavior.

Callback delivery is best-effort. Observer failures must not crash the run.

## Hooks And Interceptors

Hooks are minimal in-process interceptor seams for hosts that need to influence
a run at specific lifecycle points. Hook objects can be passed through
`code_squid.agent_setup` and `AgentLoop` wiring. Code Squid can also load enabled
standalone Hooks from an application home's `hooks/` directory when the caller
sets `include_user_hooks=True`; selected Mod Hooks are loaded during Mod
resolution. `AgentLoop` calls supported hook methods directly as the run
progresses.

Hooks are deliberately narrower than passing whole runtime objects around. They
receive event-specific context dataclasses and return `HookResponse | None` at
every lifecycle seam. `HookResponse` is the single effect vocabulary for
blocking, context, action/result transformations, report notes, and run-finished
handoffs. They should not receive `AgentLoop`, `SessionStore`, `ToolExecutor`,
or `ModelAdapter` instances.

`HookRunner` invokes Hooks in registration order, applies chaining and
aggregation rules, and returns one aggregate `HookResponse`. `AgentLoop` owns
the actual runtime effects, including transcript/session persistence and where
transient model context is inserted. Hooks never mutate canonical messages,
session history, or the system prompt directly.

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
- standalone disk loading is opt-in; selected Mod Hooks are loaded automatically

### before_run

Runs once after the initial transcript exists and the `run_started` event has
been emitted, before the first model call.

Can block the run or add run-level context blocks. A blocked run becomes a
failed run and still reaches the normal `run_finished` handoff.

### before_model_turn

Runs before each model request.

Can add transient prompt/context blocks. This context is model-visible for that
request, but is not appended to `session.messages` and is not persisted.

Hooks contribute prompt blocks through `HookResponse.context_blocks`; there is
no separate return convention for this event.

Built-in behavioral Hooks whose advice asserts current accumulated state use
this seam to render that advice. Their `tool_result` handlers still observe
every result synchronously, but a later sibling in the same Tool batch can
invalidate the state before the next model request. Event-specific recovery
and correction guidance remains on `tool_result`.

### compaction_applied

Runs only after the compactor has replaced the active in-memory transcript and
the `compaction_applied` lifecycle event has been persisted when session storage
is present. It is a notification seam with no `HookResponse` effects.

Checks, threshold crossings, compaction start/request events, failures, and
unapplied attempts never reach this seam. This makes successful compaction a
simple reset boundary for Hooks whose state describes what remains visible in
the model transcript.

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

Can modify, redact, or summarize the result explicitly through
`HookResponse.updated_tool_output`. Transformations chain in registration order.
Hooks may also return `additional_context`; the runner joins contributions in
registration order and the loop injects them as a transient user-instruction
message for exactly the next model request. That guidance is not appended to
canonical `session.messages`, persisted, or added to the system prompt. The
final transformed Tool result continues through normal display and transcript
persistence. For a multi-action turn, the loop accumulates non-empty guidance
from every attempted action in execution order until control returns to the
model. Exactly identical per-action guidance is included only once; a later
action with no guidance cannot erase an earlier contribution. A single-action
turn follows the same path and retains its existing one-turn behavior.
This accumulation contract remains available to custom/user Hooks and to
event-specific application hooks such as failure recovery;
the runner does not reinterpret arbitrary `additional_context` as recomputable
state.

Code Squid owns `TooManyReadsNudge`, `PostVerificationNudge`, and
`RepeatedFailureNudge` in `code_squid/hooks/`. These advisory Hooks track
successful reads, explicit verification, and repeated failures using generic
Core lifecycle contracts. Read and verification advice is rendered from current
state at `before_model_turn`, so a later sibling edit cannot leave stale advice
armed. Event-specific recovery guidance remains on `tool_result`.

Application setup owns composition, enablement, thresholds, and guidance texts.
The default order is reads, verification, then repeated failures; the first two
are enabled and repeated failures are disabled. Caller, Mod, user, and explicit
HookRunner inputs remain separate from built-in enablement. Hooks never infer
semantic task completion or force a final response. See [behavioral Hook state
and thresholds](IMPLEMENTATION_NOTES.md#built-in-behavioral-hooks).

Core retains `read_result_trimmed` as a generic notification of source ranges
left visible by request-only trimming. It also retains `compaction_applied` for
host hooks that track model-visible context. Neither notification installs a
source-coverage or repeated-read policy.

### before_accept_final

Runs only after a no-tool assistant reply has passed existing final validation
as a final candidate, before final display, `final_message` event, transcript
storage, and completion.

Can block finalization by adding guidance for the model to continue. Can append
a report note to an accepted final. Core stops a run as failed after three
consecutive final candidates are blocked, preventing an unbounded model-request
loop. A successfully executed Tool action resets this streak; invalid replies,
failed or rejected Tool actions, provider failures, and Tool-step accounting
remain independent.

### run_finished

Runs after a terminal state is reached: `complete`, `failed`, or `interrupted`.

Returns structured follow-up requests through `RunResult.follow_up_requests`.
It does not directly start another run; the calling host decides what to do
with those requests.

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
and Hook metadata/loading. `squid_core/agent_loop/loop.py` owns where hook calls
happen in the loop.
`code_squid/hooks/` owns behavioral hooks and their default thresholds/text.
`code_squid/agent_setup.py` supplies failure-recovery text and wires enabled
application hooks plus optional `hooks`, optionally loads standalone hooks from
the supplied application home's `hooks/`, or appends enabled built-ins to an
explicit `hook_runner`.
Selected Mod Hooks arrive through `ResolvedMod`. `squid_core/events.py`
remains observer-only.

Hooks are in-process Python objects. Standalone Hook activation is read from
`hook.yaml` only when the caller opts into user Hooks. Mod-listed Hooks are
treated as enabled for that selected Mod. `run_finished` follow-up requests are
returned to the host; Core does not execute them.

## Application Setup / Python Embedding

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

The dependency direction is a frontend into Code Squid application
construction, then generic Squid Core construction, Core collaborators, and
`AgentLoop`. `code_squid.agent_setup` does not import the console frontend, and
generic construction never calls back into Code Squid prompt, terminal, or
discovery policy.

`code_squid.agent_setup.run_coding_task(...)` is the Code Squid application
entry point for starting a new coding task. `workspace_root` and `task` are required;
optional inputs select Skills or Mods and replace runtime collaborators. It
returns `RunResult`.

`code_squid.agent_setup.build_coding_task_run(...)` constructs the session,
session store, undo store, generic Agent with `CODE_SQUID_PROMPT_DEFAULTS`, selected tools,
application hooks, and generic loop wiring without starting the loop. The CLI
constructs and passes a `TerminalDisplay` before calling this seam because it
needs terminal startup, debug/trace, Skill, and approval-mode presentation as
well as access to the session and session store for interactive follow-ups.
Programmatic callers may omit presentation; Core then installs its no-op
`NullDisplay`. A supplied display is also the default approval prompter unless
the caller supplies `approval_prompter` explicitly. Skill/tool resolution and
precedence rules remain application-owned; the generic builder accepts tools
and Agent objects already selected by its caller.

`squid_core.spawner.build_agent_run(...)` constructs a generic `Agent` by
default and uses a no-op `NullDisplay` when no presentation collaborator is
provided. It creates a `ModelAdapter` around an injected provider, plus
`Compactor`, `ToolExecutor`,
`ToolResults`, `ApprovalPolicy`, `ActionPreflight`, `HookRunner`, `Session`,
`SessionStore`, and `UndoStore` when those concerns are omitted. It requires
typed settings supplied by the application and does not load Code Squid
settings or defaults itself.

The generic builder uses an empty Tool registry when `tools` is omitted. Code
Squid's application builder is what selects the four built-ins by default.
Direct `Agent(...)` construction has its own default of the built-in registry.

Callers may replace any of those major runtime collaborators selectively. A
supplied `ModelAdapter` is used directly, taking precedence over a supplied
provider and bypassing adapter construction; a supplied provider requires an
explicit `model_name` and can receive explicit `provider_name` and
`tool_call_content_mode` inputs (`None` and `"empty"` by default). These inputs
are independent of runtime settings, which carry no provider configuration. Missing
both provider and adapter raises a clear construction `ValueError`. A supplied
`ToolExecutor` bypasses its default construction and the otherwise implicit undo-store creation. A
supplied approval policy or action preflight is used directly. Presentation
and approval prompting are separate inputs, so a GUI need not imitate a
terminal display. `squid_providers.catalog.build_provider` constructs the
configured transport from effective provider
settings. `code_squid.agent_setup` calls it only when neither provider nor
adapter was supplied, then injects the provider and exact model/label/replay
inputs into Core. Custom providers bypass application default construction;
custom adapters bypass both provider and adapter construction. Core never
selects a backend from settings or calls a built-in provider factory.

`generate_text` and `stream_text` require the keyword-only `model_adapter`
collaborator. They do not construct providers or adapters and expose no
settings-only construction API.

Generic new-run construction requires explicit `sessions_dir` and `undo_dir`
inputs when it creates the stores itself. It calls
`SessionStore.create(sessions_dir, task, workspace_root=...)` followed by
`UndoStore.create(undo_dir, session_id, workspace_root=...)`. Embedding hosts
may instead pass `session_store_factory` and/or `undo_store_factory`, or pass
pre-created `SessionStore` and `UndoStore` objects. Construction preserves
session-store-first ordering and supplies its session ID to delayed undo
construction. Direct `AgentLoop(...)` construction remains unchanged.

This seam lets a host persist outside the workspace without teaching Core its
storage layout, indexes, or adapter types. Code Squid's application setup uses
`code_squid.app_paths` to supply `<app-home>/workspaces/<workspace-id>/sessions`
and `<app-home>/workspaces/<workspace-id>/undo`, while `workspace_root` separately
continues to define tool execution. Embedding hosts are not special Core concerns.

### Central workspace state

`workspace_id()` returns `<workspace-folder-name>-<short-path-hash>` (for example,
`code-squid-a3f91c2b`). Both parts use the expanded, resolved absolute workspace
path: the prefix is its basename, and the suffix is the first eight hexadecimal
digits of its SHA-256 digest. Native `os.path.normcase` folds Windows case and
separators; POSIX case is preserved. The prefix replaces Windows-invalid/control
characters and whitespace with hyphens, removes trailing dots/spaces, and is
limited to 80 UTF-8 bytes before reserved-device-name protection. Empty/root
names use `workspace`; reserved Windows names receive a `workspace-` prefix.
Symlink aliases resolve to the same identity. A rename
or move selects a new bucket; no move detection or reassociation is implemented.
IDs are location associations, not persistent identities for replaced projects.

```text
<app-home>/workspaces/<workspace-id>/
  workspace.json                 # version 1 and normalized workspace_root
  sessions/<session-id>/          # unchanged Core format, including assets
  undo/                          # one latest buffer for this workspace
  logs/latest.log
```

All application storage helpers prepare or validate `workspace.json` before
returning a data path. Discovery can create only the bucket and manifest, not a
session or undo buffer. Existing missing, malformed, or differently owned
manifests fail closed; storage and manifest symlink redirection is rejected.
Short-hash collisions fail against the full normalized path in the manifest
before any saved data is used or changed; no alternate bucket is selected.
Old full-hash development directories are untouched and never discovered as a
fallback. Sessions, undo, and logs all use the same workspace naming resolver.
Manifest writes use Core's atomic JSON helper. Workspace switching clears the
active session; tools and undo targets still use the actual workspace root.
Session IDs remain unique only within their sessions root.

The coding-run builder passes its resolved explicit/environment application home
to storage, settings, resources, and command-trust persistence. The existing
`CODE_SQUID_SESSION_INDEXES` override still selects the supplementary registry.
Supplied stores/factories retain their explicit host-owned locations.

New PDF renders remain under the current session's assets. Code Squid supplies
`SessionAssetPreflight` to allow only built-in `read_file` access to that resolved
asset tree, without an outside-workspace prompt in Balanced mode. The ordinary
approval policy still handles Strict mode and Hook reasons, and only approved
execution receives Core's external-access flag. Other sessions, application
settings, custom readers, and writes receive the normal workspace checks.

Legacy workspace sessions, undo, logs, settings, and PDF paths are untouched and
never imported. Registry entries for legacy roots are not rewritten; Code Squid's
session UI discovers only the selected workspace's central root. Core's generic
cross-root helpers continue to inspect whichever roots their caller supplies.
Keep configured application homes outside projects. Core's storage, replay,
asset loading, and undo implementation remain application-independent and
unchanged.

Hosts that already resolved a Skill and its executable tool registry may pass
them together as `resolved_skill` and `resolved_tools`. Core then skips Skill
discovery while retaining ownership of run construction, metadata, and
execution. The normal Code Squid builder also accepts `mod_name` and
`app_home`; the application adapter in `code_squid.mods` selects the package
home and delegates to `squid_core.mods.resolve_mod(...)` for the resources.
With `mod_name`, an optional `skill_name` is forwarded as `selected_skill` and
names only a packaged Skill in that Mod; omission selects its `default_skill`.
Without `mod_name`, `skill_name` still names only a standalone Skill. These
namespaces never fall back to one another. Named Mod resolution cannot be
combined with explicit resolved components. Each run context records the
resolved `mod_id` and `skill_name`, the selected Tool registry, and the selected
Skill's prompt override names. Generic
`squid_core.spawner` receives only selected resources and remains unaware of
Mod names, paths, discovery, or selection policy.

The CLI follow-up path reuses `build_coding_task_run(...)` with the existing
`Session` and `SessionStore`. Code Squid therefore resolves a selected Mod into
its Skill, Tools, Hooks, Agent, and AgentLoop through the same application seam
used for a new run. Provider selection persistence stays in `code_squid.provider_setup`; construction
and backend policy belong to `squid_providers.catalog`.

`squid_core.storage.session_index` owns generic inspection, registration, and
cross-location discovery for explicit index and session-root paths. Session
creation does not register itself globally; Code Squid uses
`code_squid.app_paths` to select both paths and explicitly registers the
workspace's sessions directory after creating a session. Registry failure remains
supplementary and does not invalidate usable local storage. App-specific UIs
own their presentation projection while Core owns the persistence formats and
mechanics.

This setup layer gives external Python code a way to call Code Squid without
copying CLI wiring. It only constructs a run; it does not orchestrate multiple
runs or provide a daemon or server. Terminal workflow and presentation live
under `code_squid/console/`; `main.py` only delegates to
`code_squid.console.cli.cli_commands.run_cli()`.

### Core Mod resolution

The host owns selection and passes a Mod name plus the application home to
Core, with an optional `selected_skill` keyword argument to `resolve_mod`.
Omitting it selects `default_skill`; an explicit missing ID raises
`ModResolutionError`. `Mod.skills` exposes packaged Skills keyed by their local
directory IDs; `ResolvedMod.skill` remains exactly one active Skill.
`discover_mods(app_home)`, `load_mod(name, app_home)`, and
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

`mod.yaml` uses the fields `name`, `description`, required `default_skill`,
optional `accent`, and `hooks`. Mod-level `tools` is unsupported and rejected;
there is no legacy compatibility mode or duplicated tool-list equality rule.
Code Squid ships Mod Builder under `code_squid/resources/mods/mod-builder/`.
`code_squid.mods` merges this built-in with user packages from the selected
application home's `mods/` directory. The built-in name wins collisions;
`/mod` labels the unchanged user package as shadowed. Missing bundled metadata
remains invalid and never silently falls back to a colliding user package.
User packages otherwise retain Core's existing discovery and resolution rules.

`importlib.resources.files("code_squid")` locates the installed resource home.
Source checkouts and pip installations provide physical files whose lifetime
covers lazy Tool execution; zip-import execution is unsupported. Setuptools
package-data and MANIFEST.in include the complete resource tree, including raw
Tool/example Python, in wheels and source distributions. Nothing is copied into
the user home. CLI Mod/Skill commands, startup selection, terminal labels, and
agent_setup all use the same application adapter. Application settings, storage,
and optional user Hooks continue using the real user home.

`code_squid/mod_authoring.py` owns deterministic authoring scaffolds and static
checks adapted from Desktop, with no Desktop dependency. Core's public loaders
remain authoritative for persisted contracts. Validation stages workspace drafts
into the Core app-home layout and never imports authored Python; actual Tool
and Hook behavior requires separate tests. The five bundled helpers expose the
complete guide/examples and scaffold/validate only within the execution
workspace. The guide lives in structured `data.guide` so Core's top-level string
bounds do not truncate the authoring contract. Readers report missing, invalid
UTF-8, and incomplete canonical resources as unavailable. Test coverage lives
in `tests/test_mod_builder.py` alongside existing Mod integration tests.
Custom Mod Tools keep their implementation in `tools/<name>/`; the selected
Skill's `allowed-tools` activates them, and `mod.yaml` selects Mod-wide Hooks.
Core preserves accent metadata but does not interpret its presentation.

A Mod must package at least one direct child `skills/<skill-id>/SKILL.md`.
Every Skill name must match its safe directory ID, with IDs scoped to the Mod.
Every packaged Skill must explicitly declare `allowed-tools`, including `[]`
for no tools. Discovery and validation check all packaged Skills and their tool
dependencies, including inactive profiles. `default_skill` must name one of
these packaged Skills; standalone/global Skills never serve as a fallback.

Runtime builds the active registry solely from the selected Skill's
`allowed-tools`, preserving its order. Package-wide references are validation
inputs only and never grant extra permissions to the active `ToolExecutor`.
Tool precedence remains protected built-in, Mod-local custom Tool, then shared
custom Tool under the supplied application home. Built-ins win shared-name
collisions; a Mod-local replacement directory for a referenced built-in name
invalidates the package. Packaged Tool implementations remain Mod-scoped.
Hooks are Mod-wide: selecting a different Skill loads the same Hook names with
unchanged Mod-local-before-shared resolution. Agent prompt assembly, Skill
section override semantics, and prompt ordering are unchanged.

Callers omitting `selected_skill` resolve the packaged default. There is no
`Mod.tools` grant, manifest `tools` field, or standalone default-Skill fallback;
each packaged Skill owns its tool permissions.

Discovery and validation parse `mod.yaml`, `SKILL.md`, `tool.yaml`, and
`hook.yaml`, and verify Hook source presence, but do not import Tool or Hook
Python source. A selected Mod Hook is imported when runtime resolution loads
it through the normal Hook loader. A selected Tool remains lazy and imports
only when its registry entry executes.

The host owns presentation and the user's Mod selection. Core owns Mod parsing,
validation, and runtime resolution.

## Skill System

Skills are file-backed prompt/tool profiles. Standalone user Skills are
discovered from the Code Squid home directory:

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

Unknown Tool names fail during run construction before any Tool action is
executed. An explicit no-Tool Skill exposes no Tool definitions. The current
response protocol is otherwise unchanged, so such a run can only complete with
a non-empty final response and no Tool call.

Code Squid supports normal Agent Skills-style Markdown instructions plus
Code Squid-native prompt-section overrides. Overrides are written as Markdown
headings:

```md
## FINAL_SUMMARY_REQUIREMENTS replace

Write a focused review.

## TOOL_USAGE_GUIDANCE replace

...
```

The parser accepts these override modes:

- `replace`
- `append`

Supported override sections are:

- `AGENT_IDENTITY`
- `TOOL_USAGE_GUIDANCE`
- `FINAL_SUMMARY_REQUIREMENTS`

The following section names remain unsupported for fixed overrides (narration
is application baseline policy, not a Core runtime requirement):

- `VISIBLE_NARRATION_REQUIREMENTS`
- `REQUIRED_RESPONSE_FORMAT`
- `CORRECTION_MESSAGES`
- `COMPACTION_PROMPT`

`replace` and `append` have their literal meanings for `AGENT_IDENTITY`,
`FINAL_SUMMARY_REQUIREMENTS`, and `TOOL_USAGE_GUIDANCE`. Active Skills retain
application tool guidance when they omit that section; `append` adds to it and
only explicit `replace` substitutes custom guidance.

Skills cannot replace Core's tool-call/final-response protocol, batching and
result-dependent sequencing, completion rule, verification honesty, task-neutral
protocol examples, or malformed-response corrections. Core retains OS, shell,
path-separator and workspace facts, but describes shell execution only with an
active `run_command` and file capabilities only with the corresponding active
file tools. The resolved Agent registry is passed to prompt assembly.

`code_squid/agent/prompts.py` owns visible narration style, dedicated source
reading and editing preferences, Windows shell-discovery preferences, final
report style, and coding-specific response examples. Narration and coding
examples and source/shell-discovery preferences are included in the
non-replaceable application baseline policy, so
replacing any fixed section preserves them. Tool guidance and final report style
retain their existing append/replace behavior. Exact patch diagnostics and
selectable candidates remain preferred before rereading, and shell edits remain
an inappropriate workaround for a failed dedicated editing tool.

`PromptDefaults.agent_identity` supplies the `AGENT_IDENTITY` override section.
Current consumers and fixtures use that section directly. Only current section
names are accepted; there is no compatibility alias.
Core's `tools=None` selects built-ins, `tools={}` intentionally selects no tools,
and explicit registries are preserved exactly without merging or copying;
Code Squid continues to resolve its application registries before injecting them.
Core source/content omission markers use `SQUID CORE`, including trimming
recognition. Old branded omission markers in persisted results are not recognized
as current internal markers; stored history is not rewritten.

New sessions persist one assembled system message followed by the raw authored
task as `role=user`; resumed runs append the raw authored follow-up in the same
form. There are no runtime task or follow-up wrappers.

Mods are the primary interactive specialization control, while standalone
Skills remain the direct/advanced path. The current controls are:

```bash
python main.py skill
python main.py --skill <name>
```

Inside the interactive CLI:

- `/mod` shows the active Mod and available Mods.
- `/mod <name>` selects that Mod and its default Skill for later tasks and follow-ups.
- `/mod none` clears the Mod and its packaged Skill selection.
- `/skill` shows the current active Skill and available Skills within the active
  Mod, or standalone Skills when no Mod is active.
- `/skill <name>` sets the active skill for future tasks and follow-ups in the
  current CLI process.
- `/skill none` resets to the active Mod's default Skill, or clears a standalone Skill.
- `/provider` shows the friendly effective provider, readiness, and provider
  list. `/provider use <name>` selects a provider through the same
  operation as the startup menu. `/provider key <value>` and `/provider url
  <value>` update the current connection, while `/provider status` reports the
  effective transport, URL, key presence, readiness, model, and active env
  overrides without printing a secret.
- `/model` shows the exact effective model and a winning environment override;
  `/model <name>` persists the supplied ID unchanged through the same operation
  as the startup model menu.
- `/safety` shows the friendly safety mode; `/safety strict`,
  `/safety balanced`, and `/safety yolo` persist the corresponding internal
  approval mode.
- `/compact-at <tokens>` accepts a positive integer or `k` shorthand, persists
  the normalized integer as `compaction.trigger_input_tokens`, and reloads the
  same settings object used to construct later Core runs. It does not discover
  or validate model context limits.
- `/sessions` lists workspace sessions, while `/show`, `/show current`,
  `/show latest`, and `/show <session_id>` reuse the saved-session renderer.
- `/resume latest` and `/resume <session_id>` switch the active session without
  leaving the persistent prompt.
- `/undo` invokes the workspace's existing latest-run restore behavior.
- `/workspace` reports the current workspace; `/workspace <path>` validates,
  remembers, and requests a full reconstruction around a new workspace root.
- `/cwd` remains a compatible report-only alias for the current workspace root.

Selections are process-local CLI state, represented by `mod_name` and
`skill_name` (one active Mod and one active Skill). Selecting a Mod replaces the
previous Skill with that Mod's default; `/skill <name>` then selects only from
its packaged Skills and keeps the Mod. To select a standalone Skill, clear the
Mod first. Both names are forwarded on every new run and follow-up. The startup
panel shows `Skill: <name>`
when the CLI is launched with an active standalone Skill.

Specialization may change between runs in one session. Each run must use a
coherent current prompt, Skill, Tools, and Hooks while preserving prior
conversation history. At the start of an existing non-empty session,
`AgentLoop` replaces all replayed system messages with the newly constructed
Agent's one intended system message; it never inserts the Agent's original
initial user task again. The replacement is persisted as an append-only
`system_message_reconciliation` event. `SessionStore.load_messages()` applies
the latest such event during replay, so old specialization instructions do not
return after restart and exactly one current system message is exposed. Normal
messages and system reconciliation replacements use the durable append as their
commit point: when a store is present, `session.messages` changes only after the
corresponding append succeeds. Store-less sessions retain their direct in-memory
behavior.

Each new run and follow-up appends a non-transcript `run_context` event to
`session.jsonl`. This records `mod_id` when a Mod is selected, the resolved
active `skill_name` (including a Mod default), the actual filtered
`allowed_tools`, and the `prompt_overrides` for that run:

```json
{
  "type": "run_context",
  "skill_name": "user-review",
  "allowed_tools": ["read_file", "run_command"],
  "prompt_overrides": ["FINAL_SUMMARY_REQUIREMENTS", "TOOL_USAGE_GUIDANCE"]
}
```

`run_context` is debug metadata, not model memory. It is not replayed to the
model. `SessionStore.load_messages()` ignores it while applying system-message
reconciliation events to the replayed transcript.
`python main.py show <session_id>` displays compact `[run context]` blocks so
tool exposure and prompt overrides can be inspected after a run.

Before each ordinary request, Core derives a bounded model-visible view of
older built-in Tool results without changing canonical messages or storage.
Call/result IDs remain paired and unknown Tools remain unchanged. Compaction
is a separate transformation. See [historical result trimming](IMPLEMENTATION_NOTES.md#historical-tool-result-trimming).

Standalone Skills discovered from the Code Squid home directory have
`source="user"` and `editable=true`. Mod-local Skills remain package-scoped and
are resolved through the Mod path instead of standalone discovery. Code Squid
currently ships no repo-root bundled Skills.

## Application Resources and Mods

Code Squid chooses an application home, defaulting to:

```text
~/.code-squid/
```

Setting `CODE_SQUID_HOME` redirects the Code Squid application home. Embedding
applications may instead pass an explicit root. Core resource machinery uses
that supplied root and does not define a universal Squid Core home. Its paths
are:

- `settings.json` stores application-wide provider, model, runtime, compaction,
  and display preferences.
- `skills/` stores user skills such as
  `~/.code-squid/skills/<skill-name>/SKILL.md`.
- `hooks/` stores user hook packages loaded by `squid_core.hooks` when callers
  opt into user hooks.
- `tools/` stores standalone user Tool packages.
- `mods/<mod-name>/mod.yaml` stores canonical user Mod packages with required
  packaged Skills and optional package-local Tools and Hooks.

Core imports executable Hook and Tool source under neutral
`squid_core_dynamic_*` module identities. Hook identities are stable for a
Hook name and resolved source path so reloading the same Hook retains its
existing behavior; Tool executions receive fresh identities so separately
executed dynamic modules remain isolated. These internal names do not encode
the embedding application's identity.

Mod metadata supports an optional top-level semantic accent, for example
`accent: purple`. The effective default is `cyan`; allowed names are `cyan`,
`blue`, `green`, `yellow`, `orange`, `red`, `pink`, `purple`, `white`, and
`gray`.

The host selects a Mod for each run; Core does not persist a globally active
selection.

## Settings

`code_squid/settings.py` owns application-wide persistence, sparse saved
provider connections, product defaults, selection, and environment overrides.
`app_paths.py` owns the application-home location. Settings become generic
`squid_core.settings.RuntimeSettings` for execution and provider-owned
`squid_providers.settings.ProviderSettings` for model/connection controls.
Core never selects or configures concrete transports.

Only the application-home settings file is read. Missing settings use defaults;
legacy workspace settings are never adopted or merged.
Provider switching preserves other saved connections and the exact configured
model ID. Environment overrides affect effective process settings without
being copied into saved configuration. Field-specific writers preserve
unrelated JSON; the prompt reloads settings for later runs.

Invalid configuration fails at loading. Console operations contain expected
filesystem/validation errors and retain last known-good settings, while
unexpected programming errors escape. Reasoning display is independent of
provider reasoning mode and budget; a reasoning-only budget never becomes a
total-response limit. See the [settings reference](IMPLEMENTATION_NOTES.md#settings-reference)
for fields, defaults, precedence, validation, retries, and error handling.

## CLI Commands

`main.py` and the installed `code-squid` command dispatch to the same console
entry point. One persistent interpreter handles fresh sessions and resume:
a first task creates a session, later tasks continue it, and `/new` resets the
session boundary. Slash commands control specialization, settings, workspace,
inspection, undo, and exit; bare `exit` and `quit` remain task text.

Workspace switching validates a directory and reconstructs workspace-bound
objects around the new root, clearing the previous session. Application
preferences and selected specialization remain application/process state.
See the [command reference](IMPLEMENTATION_NOTES.md#cli-command-reference)
and [console handoffs](IMPLEMENTATION_NOTES.md#console-presentation-and-input).

## Provider Model

Squid Providers owns concrete transports, catalog/defaults, readiness,
discovery, normalization, tracing, cancellation, vision wire conversion, and
provider-specific replay/reasoning policy. Code Squid owns saved/effective
choices and provider/model UX. Core consumes an injected ready provider or
adapter and generic `ModelResponse`, never SDK objects or native payloads.

`ModelResponse` carries content, normalized reasoning, ordered Tool calls,
usage, finish reason, and response ID. Core owns argument parsing/schema
validation, whole-batch rejection, canonical replay dictionaries, and Tool
call/result pairing. Finish reason is diagnostic, not a completion decision.
Providers may return multiple calls despite requests disabling parallel calls;
Core preserves their order and executes them sequentially.

Provider selection persists independently of readiness, enabling connection
setup before inference. Readiness gates inference; discovery can remain
available without inference credentials. Model IDs are exact and independent
of provider switching. Adding a first-party provider changes Providers rather
than adding Core or application transport branches.

Provider failures become `ModelRequestError` with bounded, credential-redacted
diagnostics and their original cause. Core retries only classified transient
failures before assistant acceptance or Tool execution; the CLI reports
exhausted requests and returns to the persistent prompt.

Images use request-only provider-neutral references to immutable session
snapshots. Both Tool execution and request preparation require proven vision
support; Providers proves OpenRouter support from exact model catalog metadata,
alongside LM Studio and native Ollama's capability checks. Unsupported or unknown
capabilities fail closed. Binary wire data is materialized
only at transport time and never becomes canonical transcript content.
See [transport and wire details](IMPLEMENTATION_NOTES.md#provider-integration-and-wire-behavior)
and [stream cancellation](IMPLEMENTATION_NOTES.md#streaming-and-cancellation).

## Runtime Contracts

### Turn Contract

Before completion, prompts strongly encourage a brief visible action note and
demonstrate it alongside one or more independent tool calls. An action note is user-facing
text that explains why the tool call is the immediate next action. Narration is
a behavior-shaping preference, especially for smaller models, not a runtime
invariant.

The runtime enforces:

- malformed tool-call output is rejected
- unknown tool names are rejected during model-adapter validation
- missing required tool arguments are rejected during model-adapter validation
- non-boolean values for boolean Tool schema properties are rejected during
  model-adapter validation without coercion
- empty replies with zero tool actions are rejected

Invalid replies are rejected before entering normal assistant history. The loop
stores a correction user message instead. A valid reply resets the invalid-reply
counter. Repeated invalid replies stop after the configured hard-coded loop
limit, currently 3 consecutive invalid replies.

Runtime validation accepts a non-final reply with one or more tool actions even
when assistant content is blank. The prompt permits a batch only when both the
arguments and necessity of every call are known from current context. Independent
known-required calls remain valid; if an earlier result could eliminate or
materially change a later call, the model must wait for that result. The runtime
does not infer semantic necessity or impose a separate per-turn batch-size limit.

Each action that enters the per-action Hook/preflight/approval/execution path
counts toward `runtime.max_tool_steps`, including blocked and denied actions.
The limit is checked between actions, so reaching it can close and stop a batch
partway through without executing its remaining calls.

### Final Contract

A valid final assistant reply must include no tool calls and must have
non-empty content.

For coding tasks, prompts ask the agent to keep final summaries concise and
precise, identify changed files, summarize the change, state verification, and
report concrete limitations. Formatting guidance is not runtime-enforced. The
terminal display removes a `TASK COMPLETE` marker if a model includes it;
finalization does not depend on that marker.

### Tool Transcript Contract

Assistant messages that used tools preserve canonical replay `tool_calls` metadata.
Tool-result messages include the matching `tool_call_id`.

`reply["actions"]` is the canonical ordered batch for every tool turn; a
single-tool turn is simply a batch of length one. `ToolExecutor.execute()` still
owns exactly one action. The loop stops a batch after the first failed,
Hook-blocked, or approval-denied result. Unattempted suffix calls receive
explicit skipped results so every preserved assistant call ID remains closed,
without invoking the executor or consuming a Tool step.

Provider Tool arguments remain attached to their call index during streaming,
are copied verbatim into raw diagnostics and assistant `tool_calls`, and are
parsed into the corresponding canonical action. Schema failure in any call
still rejects the whole reply before AgentLoop execution under the existing
malformed-reply policy.

Assistant tool-call/result pairs must stay replayable. This matters for strict
OpenAI-compatible model templates and for provider adapters that need to
reconstruct prior tool turns. Cancellation and exception repair retain the
completed result prefix and synthesize interruption/failure results for the
unfinished suffix before unwinding.

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
  reason are approved automatically, except that `run_command` asks until its
  command identity has been permanently trusted. Actions with an approval
  reason still ask the user before execution.
- `approval_mode = "always"` means strict mode and asks before every tool
  action.

The policy is UI-agnostic and receives normalized tool actions before
execution. `TerminalDisplay` is the current prompter used by the CLI.
`squid_core/safety/preflight.py` supplies workspace and hook approval reasons
before this approval check.

If a user denies an action, the action is not executed. Denial returns a normal
failed tool result to the model with `user denied tool action`.

Guarded command trust uses a deliberately simple command identity rather than
classifying shell semantics. Persisted trust belongs to application settings;
once-only approval changes no settings. Dynamic calls with no trustable
identity cannot be permanently approved. See [command identity parsing](IMPLEMENTATION_NOTES.md#guarded-command-identity).

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
workspace if the command itself does so. Guarded mode requires approval for
every untrusted command identity, but it does not constrain what a trusted
command can do.

## Compaction

Core owns transcript compression mechanics and the task-neutral summarizer
prompt. Compaction runs before model calls, using a rough transcript estimate.
It protects the original system/task prefix, selects oldest whole chunks while
preserving a recent tail, and never separates assistant Tool calls from their
results. The summary is lossy assistant context, explicitly non-authoritative,
and cannot override user requirements.

A proposed transform is persisted before replacing the active transcript.
Only successfully applied compaction reaches post-commit Hooks and UI.
Invalid summaries leave the original transcript intact; other failures retain
normal error semantics. Valid versioned transforms replay on resume, while
canonical append-only messages remain available for diagnostics.

Core's optional host context seam receives the exact preserved tail and
accepts text; it knows nothing of coding Tools or workspace truth.
`code_squid.compaction_context` derives deterministic facts from canonical
stored Tool results only when that tail exactly matches the canonical suffix.
It reports known direct mutations, explicit verification/staleness, activity,
recoverable failures, and durable PDF-render paths without filesystem inference
or model-authored state. The same host facts go to the summarizer and follow
its summary unchanged.

Compaction compresses continuation context rather than maintaining workspace
memory. See [selection, validation, persistence, replay, and event details](IMPLEMENTATION_NOTES.md#compaction-mechanics-and-diagnostics).

## Sessions, Resume, Undo, And Interruption

Code Squid supplies explicit application-home session/undo/log paths to generic
Core storage. Sessions contain metadata, append-only canonical history,
model-request observations, a derived readable transcript, and assets when
needed. Effective replay applies system reconciliation and valid compaction
transforms; canonical history remains available separately. Diagnostic entries
never become model messages, and diagnostic projections are best effort.

Session-backed image snapshots are immutable and content-addressed, so replay
uses the original bytes even if workspace files change. PDF reads persist
stable rendered-page paths but do not inject images; a later image read uses
the normal snapshot/vision path. Storage owns containment and atomic writes.

Resume loads the latest durable effective transcript, adds the authored
follow-up, marks the session active, and creates a fresh undo buffer. Tool
call/result pairing is repaired at incomplete runtime boundaries; malformed
middle history is not reinterpreted. Trailing torn appends have a narrow
recovery boundary that does not hide other corruption.

Undo is latest-run only. Built-in writes/patches snapshot the first pre-change
state per path; shell commands are not undo-protected. Restore validates the
creating workspace and every target before mutation, and is a one-shot
transition so interrupted restore cannot overwrite later user work.

Application setup constructs the provider before creating durable session
state. Later construction or run failures mark available stores failed,
retain history, and report the original cause. Secondary diagnostic failures
cannot replace that cause. Ctrl+C retains distinct interruption semantics.
The persistent CLI remains available after handled model-request failures.
See [session storage, recovery, observations, and undo mechanics](IMPLEMENTATION_NOTES.md#sessions-assets-replay-and-undo).

## Tool Model

The protected built-ins are:

- `read_file(path, ranges=None, pages=None, sheet=None, rows=None)`
- `write_file(path, content)`
- `apply_patch(path, old_text, new_text)` or candidate selection with `match_id`
- `run_command(command, verification)`

Core's `ToolExecutor` dispatches one normalized action, tracks side effects,
and snapshots built-in mutations when undo is supplied. File Tools require
absolute paths and pass workspace preflight/approval. Writes replace UTF-8
content; patches perform one exact, uniquely matched replacement. Candidate
selection remains exact and revalidated, never similarity-based editing.

The `read_file` adapter validates selectors and dispatches one-way through a
static suffix registry to `squid_core/file_readers`. Every reader accepts one
immutable `FileReadContext`; format libraries stay behind that boundary.
Ordinary source reads are bounded and preserve source-line provenance.
Documents and spreadsheets produce passive semantic content; PDFs expose text
and durable render paths; images require session-backed snapshots and verified
vision support. Format reads do not promise full layout or editing.

`run_command` executes in `workspace_root` and records explicit boolean
verification intent without inferring it from command text. It owns bounded
output, cooperative cancellation, timeout, and process-tree teardown, with
structured failure classification rather than retries or command rewriting.
It remains outside undo and is not sandboxed.

Tool descriptions own mechanical constraints; application prompts own coding
workflow and narration. There is no structured search, repo-policy, test-runner,
or browser built-in. Standalone Skills and selected Mod Skills can restrict or
activate custom registries; built-ins win name collisions, and explicit empty
permissions expose no Tools.
See [reader algorithms, bounds, patch recovery, and process teardown](IMPLEMENTATION_NOTES.md#file-readers-patching-and-commands).

## Ownership Boundaries

`main.py` owns only process entrypoint behavior: passing command-line arguments
to `code_squid.console.cli.cli_commands.run_cli()` and returning its exit status.

`code_squid/console/cli/` owns terminal CLI parsing, dispatch, the shared
fresh/resumed prompt loop, runtime setting commands, session/control command
routing, run wiring, and Mod/Skill selection. It should not grow agent policy,
tool behavior,
provider-specific response parsing, session storage internals, approval logic,
undo mechanics, compaction strategy, or terminal formatting.

`squid_core/agent/` owns generic Agent behavior and protected prompt assembly.
It decides which supplied tools are exposed, which reply shapes are valid,
when the loop should stop, and what correction/failure path is used. It does
not own Code Squid identity or coding workflow policy.

`code_squid/agent/prompts.py` owns Code Squid's explicit application prompt
defaults, baseline coding discipline, narration style, coding examples, source
reading/editing preferences, and final report style. Application wiring imports
`squid_core.agent.Agent` directly; there is no application Agent alias or empty
specialization module.

`code_squid/settings.py` owns application-wide settings parsing, persistence,
Code Squid defaults and selection, and optional
environment overrides. `code_squid.app_paths` owns the settings path policy.
The settings module produces `squid_core.settings.RuntimeSettings`; Core owns
validation of generic runtime semantics and enforcement.

`squid_core/agent_loop/loop.py` owns generic turn flow. It is the sequencing
layer, not the place for provider transport, terminal rendering, tool
implementation, or coding-task prompt text. Its tool path remains visibly hook,
action preflight, approval, execution, and result handling; it does not own
workspace or guarded shell policy. Its sibling event and transcript modules own
only mechanical payload construction, forwarding, recording, and pending-pair
repair; they do not decide when those actions happen.

`code_squid/agent_setup.py` owns presentation-neutral Code Squid application
construction. `code_squid/console/cli/session_runner.py` owns terminal display
construction and passes that collaborator inward. `squid_core/spawner.py` owns
generic selective construction and the null-display default. None orchestrates
multiple runs or provides an event bus, daemon, or server.

`squid_core/model_adapter.py` owns generic reply validation, action construction,
and replay message shaping. Provider-specific response translation and HTTP/API
calls stay in `squid_providers/`.
`squid_core/image_content.py` owns the small provider-neutral image validation,
descriptor, marker, and internal-reference contract. It does not own session
paths or provider wire formats.

`squid_core/compaction/compactor.py` owns transcript compression mechanics;
`squid_core/compaction/prompts.py` owns the generic continuation-summary
prompt; `squid_core/compaction/compaction_status.py` owns context usage and
compaction-trigger reporting; and `squid_core/compaction/token_estimate.py`
owns their shared rough transcript token estimate. These modules do not import
Code Squid application prompts, and compaction should not become workspace
memory.

`squid_core/safety/approval.py` owns approval decisions without depending on a concrete UI.
The loop enforces those decisions before tool execution.

`squid_core/safety/preflight.py` owns accepted-action boundary handling and
translates workspace and hook reasons into the two action
forms needed by approval and execution. It is a small collaborator, not a
general policy framework.

`squid_core/safety/approval.py` also extracts the first command token and matches
it against application-supplied trusted identities. Code Squid persists new
identities through `code_squid/settings.py`; Core remains independent of the
application's settings location.

`squid_core/safety/workspace_boundary.py` owns structured file-tool workspace checks. It
should remain a preflight/approval boundary unless a real sandbox is added
elsewhere.

`squid_core/tools/executor.py` owns mechanical tool dispatch and side-effect tracking.
Individual built-in tool behavior stays in `squid_core/tools/builtins/`.

`squid_core/storage/` owns generic durable session and undo persistence, atomic
writes, session indexing/discovery, and diagnostic error logging. Every
filesystem location is explicit. `code_squid/app_paths.py` owns Code Squid's concrete
application-home session, undo, index, and error-log locations and passes them into
those mechanisms. In-memory session behavior stays in `squid_core/session.py`;
live display stays in `code_squid/console/ui/`.

`code_squid/console/cli/` owns terminal workflow and control.
`code_squid/console/ui/` owns terminal presentation and input. `TerminalDisplay`
coordinates lifecycle state and delegates startup, approval, Tool, and reusable
formatting details to the sibling presentation modules described above. Tool
event display is the reliable UX layer for what happened, while model-native
narration is encouraged by prompts.

## Current Limitations

- Providers may return multiple Tool calls despite `parallel_tool_calls=False`.
  Valid batches execute sequentially in response order and stop at the first
  unsuccessful action; malformed batches are rejected before execution.
- Action notes are prompt-guided. Runtime rejects empty non-final replies and
  invalid Tool replies, but it does not fully enforce action-note quality.
- Command and file access is not a hardened sandbox. Workspace checks and
  guarded command trust are approval mechanisms.
- Compaction uses rough JSON/text length estimates, not exact tokenization.
- Core records model request failures, unexpected run failures, requested
  cancellation, and boundary-level interruptions before preserving the existing
  exception or cancellation control flow for its host.
- The interactive CLI owns one cancellation controller per active run. Its
  SIGINT handler sets thread-safe state passed through application construction
  to `AgentLoop`; embedded callers retain the KeyboardInterrupt boundary where
  Python signal handlers are unavailable.
- Streamed replies are accepted only after provider-native completion evidence.
  Cancellation reaches blocked provider I/O and bounded retry waits independently
  of live presentation settings. See [stream lifecycle mechanics](IMPLEMENTATION_NOTES.md#streaming-and-cancellation).

- The console frontend supplies `TerminalDisplay`; Code Squid application and
  generic Core construction use Core's `NullDisplay` when a host omits
  presentation.
- Resume support is CLI-owned under `code_squid/console/cli/`.
- There is no general-purpose event sink; only the small durable lifecycle set
  uses the existing session JSONL persistence spine.
- `allowed-tools: none` is not a supported special case.
- Run-context events are debug metadata, not model memory.
- Provider setup tests use mocked HTTP boundaries; they do not require live
  local or cloud inference.
- LM Studio uses native `/api/v1/models` only for discovery/readiness. Code
  Squid does not implement native model load, unload, or download operations.
- Squid Models is treated only as an already-running service. Code Squid does
  not own its process, executable discovery, GPU policy, startup, or shutdown.

## Practical Principles

- Keep the tool set small and inspectable.
- Keep native response translation in providers and generic Tool validation in Core.
- Keep prompt guidance separate from runtime enforcement.
- Keep durable session storage append-only and boring.
- Keep undo latest-only until a real workflow requires more.
- Prefer accurate boring descriptions over aspirational architecture.

Small, inspectable, stupid simple.

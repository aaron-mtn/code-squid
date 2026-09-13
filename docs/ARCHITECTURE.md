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

The construction and runtime shapes are:

```text
console CLI -> code_squid.agent_setup -> squid_core -> AgentLoop
desktop/other frontend -> code_squid.agent_setup -> squid_core -> AgentLoop
settings -> provider -> model adapter -> Core Agent -> action preflight -> approval -> tools -> transcript/session storage
```

`AgentLoop -> on_event callback` is an optional observer path for compact
machine-readable runtime facts.

Repository-local `.code-squid/` directories hold workspace runtime state and
should be gitignored. Application preferences live in the Code Squid home.

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
  - `agent/coding.py` exports `CodingAgent` as a product-owned alias of
    `squid_core.agent.Agent`; it adds no behavior.
    `agent/prompts.py` owns Code Squid identity, its non-replaceable baseline
    coding policy and intentionally replaceable tool/final-report defaults.
  - `agent_setup.py` owns Code Squid run preparation and wiring: settings,
    prompt defaults, application/workspace paths, storage locations, resource
    resolution, hooks, platform context, Agent configuration, and translation
    into the generic `squid_core.spawner` seam. It is presentation-neutral and
    does not import the console frontend.
  - `app_paths.py` owns Code Squid application-home policy, the application-wide
    settings path, repository-local
    session/undo/error-log locations, the global session-index and recent-
    workspace locations, and paths for loose resources and Mods. The recent
    workspace file is `~/.code-squid/recent-workspaces.json` (or the configured
    application home): a newest-first JSON list of at most ten normalized
    absolute paths. The same app-path module owns its tolerant loading,
    deduplication, and update policy. Reusable Core machinery receives workspace
    paths explicitly and has no knowledge of this product history.
  - `settings.py` reads the application-home `settings.json`, validates
    supported application input, owns sparse provider-scoped connection
    persistence and one-time adoption of the current workspace's legacy
    settings, applies product defaults and optional `CODE_SQUID_*` environment
    overrides, and translates the result to generic Core settings.
  - `console/cli/` owns terminal workflow and control. `cli_options.py` handles
    CLI options and workspace resolution; `cli_commands.py` handles launch-time
    dispatch; `prompt_loop.py` owns the one persistent interpreter used by
    fresh and resumed sessions; `runtime_commands.py` owns interactive
    provider, model, and safety changes; `control_commands.py` owns interactive
    session, undo, and workspace commands; `session_runner.py`
    constructs the terminal display, including startup information and
    trace/debug settings, and handles new/resumed session-backed runs; and
    `skill_commands.py` handles Skill status, listing, and selection.
    `console/startup_menu.py` owns the startup panel's small keyboard focus,
    view, and selection state. It reuses the CLI's runtime-setting, Mod, and
    session-selection operations; provider adapters remain the source of any
    optional model enumeration, with `/model <name>` shown as the
    non-destructive fallback while an adapter has no such capability. Session
    discovery stays in `control_commands.py`, which takes the newest 20
    metadata records from Core's presentation-neutral workspace
    `list_sessions` index. The menu retains the chosen ID and display title,
    plus the already-read selected metadata until the CLI consumes its
    one-time status notice; `prompt_loop.py` routes submitted text through the
    existing new-run or follow-up runner, and `session_runner.py` remains the
    sole owner of opening the store and loading a resumed transcript.
  - `console/ui/` owns terminal presentation and input. `display.py` keeps
    `TerminalDisplay` as the lifecycle coordinator used by the Agent loop.
    `header_layout.py` owns the explicit startup-scene geometry: safe draw
    width, fixed title position, two-row title/panel gap, centered compact panel
    rectangle, and rain rows beneath the panel. `banner.py` owns the panel's
    Provider, Model, Safety, Mod, Session, optional standalone Skill, and
    concise Workspace content. The Session row retains the fixed panel
    rectangle by keeping blank rows between fields rather than around the
    complete field list. `approval.py`
    owns approval panels, prompts, and compact results; `tool_display.py` owns
    tool/action labels, command recognition, and debug result projection; and
    `formatting.py` owns shared styles, links, path shortening, wrapping, and
    final-summary Markdown rendering. `binary_header.py` is a terminal-I/O-free
    rain model and semantic compositor. It excludes the panel rectangle while
    placing rain, then overlays the title and panel into prompt_toolkit styled
    fragments.

    `startup_application.py` owns the complete live startup surface: rain,
    title, menu panel, and boxed multiline `BufferControl`. It creates one
    temporary, nonfullscreen prompt_toolkit `Application`; that Application's
    refresh timer advances rain and invalidates the same renderer. Submission
    makes the Buffer read-only, publishes its task immediately, and starts an
    eight-frame global rain-fade state in `BinaryRainHeader`. The blocking
    Application event loop lives on one narrowly owned renderer thread so the
    caller can begin model work during the nominal 350 ms fade; this is not a
    second renderer or an independent rain worker. Production startup code
    reads no completed-screen or cursor geometry. The composer follows the shared
    product policy of 2 through 14 visible content rows, capped again by the
    rows physically available below the startup scene, separator, and frame.
    On constrained terminals the decorative scene clips from the bottom to
    preserve the normal composer minimum; the real Output remains the sole
    source of viewport, CPR, and cursor geometry. Once either the product or
    physical cap is reached, the BufferControl scrolls internally while
    retaining the complete Buffer. Constrained terminals also contract
    composer width instead of inventing a larger render surface.

    `TerminalDisplay` marks startup active at a session boundary but performs
    no startup terminal writes. `prompt_input.py` selects StartupApplication
    only for that active scene. After submit, the existing Application keeps
    the title, startup panel, and immutable submitted composer while its own
    50 ms refresh timer keeps the submitted drop population falling while it
    progressively dims the complete visible rain field. Drops that leave are
    not reset or replaced, and none are selectively removed. The eighth step
    clears every remaining rain cell simultaneously and exits only after that
    clean frame renders, retaining the scene in ordinary scrollback. If
    narration, Tool or
    debug output, approval, failure, interruption, cleanup, or another direct
    CLI writer needs the terminal first, `TerminalDisplay` forces the same
    model to its clean state and synchronously joins the Application before the
    writer proceeds. Ctrl+C also exits and joins the startup lifecycle safely.
    Ordinary later prompts remain composer-only
    `PromptSession` instances; `/new` creates a fresh temporary Application and
    resets rain at the current terminal position. This strict boundary is not
    the rejected PinnedComposer design: there is no stdout interception,
    managed transcript, persistent composer, alternate-screen transcript, or
    live renderer during normal run output. There is no stdout interception,
    alternate screen, or custom startup ANSI repaint geometry. The completed
    startup remains in ordinary terminal history and print-based output
    continues below it.
    The composer and startup menu share prompt-toolkit key bindings rather than
    a raw input reader: Up from an empty buffer always focuses the bottom main
    row, arrows navigate, Enter replaces the same panel with a submenu or
    applies a selection, and eager Esc backs out without Escape-prefix
    disambiguation delay. Main-menu edge navigation returns
    to the composer symmetrically. Ordinary text is ignored while menu-focused,
    and arrows retain normal multiline behavior whenever the composer contains
    text. Every focus, movement, activation, and back action invalidates the
    owning Application, so the shared scene repaints immediately without a
    second renderer or animation lifecycle. Startup-menu selection paths never
    write directly to stdout while that Application owns the terminal. The
    provider picker applies the shared provider-selection result and silently
    discards its optional informational explanation because the startup panel
    has no message surface; `/provider use` retains its ordinary print-based
    explanation after startup ownership ends. Every selectable submenu uses one
    fixed layout within that panel: its centered heading stays on the first
    inner row, options begin at the same upper-left anchor on the third panel
    row, and the centered `↑↓   Enter select   Esc back` footer stays on
    the penultimate row. The bounded option area leaves unused rows above the
    footer instead of vertically recentering short lists. Workspace and Session
    retain specialized label, truncation, and age formatting within that shared
    option column. The Session row replaces that same panel with pinned `New
    session` plus six saved sessions in a shared seven-entry viewport under the
    heading `Sessions for this workspace`. The backing list is capped at 20;
    arrow movement scrolls it,
    Enter commits an ID through the same resolver as `/resume`, and Esc
    discards the submenu highlight. A saved-session activation returns a
    distinct result from that same startup Application and hides the unused
    empty startup composer in subsequent retained frames. The CLI joins the
    renderer without force-completing the already-running fade, then prints and
    opens an ordinary composer only after terminal ownership is released; no
    nested Application or extra startup renderer is created. Other direct CLI
    writers retain the synchronous force-and-join handoff. The CLI then
    immediately consumes the selected metadata into one dim, neutral,
    detail-indented status line. `New session`, launch-time resume state, and
    subsequent follow-ups remain silent. The notice never opens the transcript
    for presentation; its locally truncated title and compact age use the
    picker's shared normalized data, and a message count appears only if that
    count already exists in metadata. Ages use `now`, whole minutes, whole
    hours, or whole days. Session task titles normalize all whitespace to single spaces before
    any presentation or truncation, keeping both the submenu and main Session
    row single-line; submenu titles then truncate before a stable
    right-aligned age column. Mod/Skill
    selection updates the presentation copy used by the active scene;
    selection semantics remain owned by the CLI command handlers.

    The Workspace row uses the same fixed panel and keyboard-only interaction:
    a seven-row scrolling viewport is backed only by at most ten recent paths.
    The current root is always included and initially selected. Basenames are
    the primary labels, with a compact parent hint only when basenames collide.
    Enter publishes the selected recent path as a distinct workspace handoff;
    Esc changes nothing. Arbitrary paths are introduced only through
    `/workspace <path>` in the main composer. `control_commands.py` parses the
    unbroken command remainder, removes one matching outer quote pair, expands
    `~`, resolves the path, requires an existing directory, and returns a
    switch target without mutating workspace-scoped objects. Both the startup
    handoff and command target converge on `prompt_loop.py`'s
    `_rebuild_workspace_runtime`, which reloads application settings and
    reconstructs the workspace-bound display/header, StartupMenu, and session
    discovery around the selected root. A real root
    change clears the active session ID and title before the new scene opens,
    so subsequent session lookup and run/session/undo paths receive only the
    new root. No mutable Core or process-global workspace is introduced.

    Initial drop
    heads are staggered through the full rain height so the first frame is
    populated above, beside, and below the panel; later resets continue to
    enter naturally from above.
    `streaming_narration.py` owns only the current provisional assistant panel.
    The CLI passes `TerminalDisplay.handle_event` to Core and translates
    `assistant_message_started`/`assistant_delta` into that temporary region.
    The first visible TTY delta starts one temporary, nonfullscreen
    prompt_toolkit `Application` around a `FormattedTextControl`; subsequent
    deltas update its content and invalidate that renderer. A private pipe
    prevents this presentation-only Application from consuming stdin, while
    its real terminal `Output` remains the sole source of viewport and cursor
    geometry. The live panel contracts and rewraps from the current output
    width, and its `Window` hides the cursor while it owns the region. An
    accepted message exits with the authoritative last frame retained as
    ordinary scrollback. When `tool_preparing` arrives during live narration,
    the CLI synchronously retains the current provisional frame and releases
    the Application before starting the existing pulse with a tool-specific
    preparation label; the later authoritative narration settles bookkeeping
    without another print or
    spinner handoff. Rejection, finalization, failure, or interruption
    exits with prompt_toolkit erasing the provisional frame. The Application
    has fully stopped before either path returns, so tool/static output cannot
    compete with it. Empty streams never start it, and redirected and debug
    output remain static. The thinking pulse is stopped before the first
    visible delta, so there is only one active normal-output writer. Provider
    `tool_preparing` events arrive while streamed narration is still
    provisional, before the authoritative assistant message and Tool start;
    this is the presentation boundary that transfers ownership from the live
    panel back to the existing pulse. Known built-in tools use `Reading...`,
    `Writing...`, `Patching...`, or `Running...`; other tools use
    `Using tool...`. `tool_started` and all existing
    output/finalization boundaries stop any active pulse. Code Squid owns no
    raw cursor-up or clear-row repaint geometry for live narration.

    `prompt_input.py`, `sessions.py`, and `spinner.py` retain their focused
    input, saved-session, and animation responsibilities. The ordinary task
    composer remains a non-fullscreen `PromptSession`, but its active prompt is
    rendered in a dynamically tall 61-cell rounded frame with two cells of
    left padding and one right gutter. The normal PromptSession input container
    retains up to 58 cells inside the borders and uses the same product and
    physical viewport caps as startup. The frame disappears from active
    control on submission and remains only as normal terminal scrollback.
    PageUp/PageDown move by pages, Ctrl+Up/Ctrl+Down move by
    half pages, and Ctrl+Home/Ctrl+End retain their standard buffer-boundary
    behavior. A one-row scroll offset keeps the cursor away from the top and
    bottom borders when the viewport has enough room. Approval prompts continue
    to use the shared unboxed input helper. Shift+Enter and Alt+Enter normalize
    to the multiline Ctrl+J action, while ordinary Enter submits. Its marker is
    hidden without changing input alignment while the startup menu owns focus.
    Normal run output uses ordinary scrollback and 61-column panels. While
    streaming is enabled, one provisional narration panel grows in place and
    becomes ordinary scrollback when the validated assistant callback settles
    it; non-streamed narration remains a static print. The final report and an
    optional Changed files section share one completion panel. `final_message`
    discards any provisional narration and retains only the current report text
    until `loop_finished` supplies the session's written paths. The section
    lists only files written by the run and is omitted when that set is empty.
    This does not introduce a managed transcript, alternate screen, or
    persistent terminal region.
    Tool results, approvals, warnings, and non-success status remain outside
    these panels, and standalone run/report/file dividers are not emitted.
    Every composer and run-panel border uses the same dim terminal-default
    styling and imports one product-owned 61-cell width from `formatting.py`.
    Static panel measurement strips ANSI/OSC sequences before calculating the
    padding needed to keep the completion panel's right border aligned.
    Normal thinking uses one neutral, CLI-owned four-frame dot pulse; neither
    its symbol nor its active label receives the current Mod accent. The label
    remains `Thinking...` until a specific tool is known, when the same spinner
    line and timing switch to the CLI-owned preparation label. Narration and
    report markers share the canonical U+1F991 U+FE0E text-presentation squid
    glyph. The active Mod accent wraps only that two-code-point sequence and
    resets immediately, leaving adjacent text and the dim neutral panel borders
    in terminal-default color.
    Presentation modules do not own approval policy, Tool execution, or
    Tool-result semantics.

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
  - Generic transcript compaction mechanics, prompt ownership, trigger-status
    reporting, and rough transcript token estimation.
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
    and mechanical repair of a pending Tool call/result transcript pair.

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
  - `events.py` owns observation; `generation.py` owns one-shot generation;
    `model_adapter.py` owns provider
    normalization; `settings.py` owns generic provider/runtime/compaction
    and tool-result trimming semantics; `tool_result_trimming.py` owns the
    request-only rendering of older built-in Tool payloads;
    `platform_context.py` describes the environment;
    `spawner.py` owns generic construction; `session.py` owns in-memory
    transcript state; and `skills.py` owns standalone Skills.
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
- `model_request_finished`
- `model_request_failed`
- `assistant_message_started`
- `assistant_delta`
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
separate model call or event family. `assistant_message_started`,
`assistant_delta`, and `assistant_message` carry `phase: "narration"` for
user-visible mid-turn text that may be followed by tool activity.
`final_message` carries `phase: "final"` for the terminal assistant response.
`tool_preparing` remains the transition from streamed narration into structured
tool-call preparation and does not carry an assistant-text phase.

Event payloads should stay compact. They must not include raw file contents,
full command output, prompts, duplicated message bodies, provider payloads, API
keys, headers, or secrets. Model-request lifecycle events retain
only provider/model identity when available, message count, a rough request-token
estimate, duration, and bounded error details. These events, plus `run_failed`
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
persistence.

Code Squid wires Core's small `RepeatedFailureNudge` Hook at this seam. The
generic Hook retains its exact-action detector: three consecutive failures must
have the same Tool, JSON arguments, and scalar `error`; success, an
uncategorized failure, or any changed action/category resets that streak. The
same Hook also has an independently configured `run_command` detector. It
counts actual classified command-process failures across different command
strings, ignores unrelated Tool calls without incrementing or resetting the
command count, and resets the count after a successful command. Approval,
schema, and pre-execution failures have no `failure_class` and do not enter this
counter. At either threshold the Hook returns recovery wording as transient
`HookResponse.additional_context` and immediately resets the applicable
counter, so another nudge requires three fresh failures. It never blocks,
rewrites, or retries a Tool action. Squid Core owns these run-local detection
mechanisms while `code_squid.agent_setup` owns both guidance texts and enables
them for Code Squid runs. Its `source` remains configuration metadata used by
hosts; it no longer controls prompt rendering.

Code Squid also wires Core's `RepeatedReadNudge` immediately before the
repeated-failure Hook. It keeps bounded, run-local line-range coverage from
successful `read_file` result metadata under normalized absolute path keys,
preferring the separate exact `returned_line_ranges` when a full-file read is
truncated. A successful `write_file` invalidates all coverage for its target. A
successful `apply_patch` instead uses its before/after line bounds to discard
the changed span while preserving coverage before it and shifting coverage
after it by the line-count delta. The Hook separately remembers patch-stale
spans so the first successful read returning changed lines is never masked just
because its wider verification window still overlaps at least 70% known
surrounding content. That read clears only the stale lines it returned and
records them as fresh coverage, so an immediate repeat is redundant again. When
at least 70% of any other returned read is already covered for that unchanged
range, it counts as redundant; by default
the first redundant reread after the useful original replaces the model-facing
result through `updated_tool_output` with a small successful `already_covered`
result containing no file contents. It also returns action-oriented one-turn
guidance through `HookResponse.additional_context`, directing the model to reuse
the current context and make a focused edit when the intended change is clear.
The next qualifying reread in that file's streak remains masked, uses a stronger
correction, and then resets the streak. The threshold remains configurable and
controls when first-reread masking and guidance begin. Failed mutations do not
alter coverage, and `before_run` clears all state. The Hook never blocks or
transforms an action, and `AgentLoop` has no feature-specific logic for it.

There is no separate "small reread" size limit in `RepeatedReadNudge`: the
overlap ratio applies to any non-empty valid returned range metadata, including
an effective range expanded by `read_file`. A
successful read is tracked only when `ok` is exactly `true`, its path can be
resolved from result or action metadata, and it reports a valid inclusive
`start_line`/`end_line` range or valid `returned_line_ranges`. Coverage is the
merged union of prior returned ranges for that normalized path, bounded to 100
files and 64 ranges per file. The current range is redundant when at least 70%
of its returned lines are in that union. The default threshold is one redundant
reread, so an original useful read followed by one qualifying overlap emits
guidance while masking that reread; the following qualifying overlap receives
the stronger masked correction. "Consecutive" is per file rather than globally
adjacent: a successful non-redundant read of that file resets its count, the
stronger escalation resets it, and a successful mutation resets it; unrelated
Tool calls and reads of other files do not. `write_file` invalidates the target's
whole coverage and any patch-stale markers, while `apply_patch` preserves
unaffected coverage only when trustworthy before/after line bounds are present
and otherwise invalidates the whole target. Failed reads and failed mutations
neither add nor invalidate coverage or advance the streak. File inspection
performed inside `run_command`,
including shell searches, does not participate because it does not produce
`read_file` range metadata.

### before_accept_final

Runs only after a no-tool assistant reply has passed existing final validation
as a final candidate, before final display, `final_message` event, transcript
storage, and completion.

Can block finalization by adding guidance for the model to continue. Can append
a report note to an accepted final.

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
`code_squid/agent_setup.py` wires the application-owned no-progress guidance
Hook plus optional `hooks`, optionally loads standalone hooks from the supplied
application home's `hooks/`, or composes an explicit `hook_runner` with the
required application Hook.
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
entry point for starting a new coding task. `repo_root` and `task` are required;
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
provided. It creates a provider, `ModelAdapter`, `Compactor`, `ToolExecutor`,
`ToolResults`, `ApprovalPolicy`, `ActionPreflight`, `HookRunner`, `Session`,
`SessionStore`, and `UndoStore` when those concerns are omitted. It requires
typed settings supplied by the application and does not load Code Squid
settings or defaults itself.

The generic builder uses an empty Tool registry when `tools` is omitted. Code
Squid's application builder is what selects the four built-ins by default.
Direct `Agent(...)` construction has its own default of the built-in registry.

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
storage layout, indexes, or adapter types. Code Squid's application setup uses
`code_squid.app_paths` to supply `<repo>/.code-squid/sessions` and
`<repo>/.code-squid/undo`, while `repo_root` separately continues to define tool
execution. Embedding hosts are not special Core concerns.

Hosts that already resolved a Skill and its executable tool registry may pass
them together as `resolved_skill` and `resolved_tools`. Core then skips Skill
discovery while retaining ownership of run construction, metadata, and
execution. The normal Code Squid builder also accepts `mod_name` and
`app_home`; it asks `squid_core.mods.resolve_mod(...)` for the selected resources.
Passing neither path preserves standalone `skill_name` discovery. Generic
`squid_core.spawner` receives only selected resources and remains unaware of
Mod names, paths, discovery, or selection policy.

The CLI follow-up path reuses `build_coding_task_run(...)` with the existing
`Session` and `SessionStore`. Code Squid therefore resolves a selected Mod into
its Skill, Tools, Hooks, Agent, and AgentLoop through the same application seam
used for a new run. Provider-specific construction remains delegated to
`squid_core.providers`.

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

`mod.yaml` uses the fields `name`, `description`, `default_skill`, optional
`accent`, `tools`, and `hooks`. The selected Skill must explicitly declare
`allowed-tools`, and that ordered list must match the Mod Tool inventory
exactly. Core preserves accent metadata but does not interpret its
presentation.

A referenced component may be Mod-local or standalone under the same supplied
application home. A Mod-local Skill, Tool, or Hook wins over a same-named loose
user component. Built-in Tools are protected: they win over loose user
collisions, and a Mod-local package may not define a replacement directory for
a listed built-in name. Direct Mod-local Skill selection is package-scoped.

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

- `SYSTEM_PROMPT_INTRO`
- `TOOL_USAGE_GUIDANCE`
- `FINAL_SUMMARY_REQUIREMENTS`

Some prompt sections are intentionally not overrideable because they define the
runtime contract:

- `VISIBLE_NARRATION_REQUIREMENTS`
- `REQUIRED_RESPONSE_FORMAT`
- `CORRECTION_MESSAGES`
- `COMPACTION_PROMPT`

`replace` and `append` have their literal meanings for `SYSTEM_PROMPT_INTRO` and
`FINAL_SUMMARY_REQUIREMENTS`. Active Skills omit Code Squid's default
`TOOL_USAGE_GUIDANCE`; when a Skill supplies that section, its content is used
as the Tool guidance. The parser accepts either mode on that section, but the
current prompt assembly does not prepend the application default for `append`.

Skills can change specialization instructions, inspection style, optional Tool
guidance, and final-summary shape. They cannot override the Core one-tool-call
contract, final-response/no-tool mechanics, narration guidance, response
examples, active-Skill/environment insertion, or correction mechanics. They
also cannot remove Code Squid's baseline coding discipline, because that policy
is outside the replaceable sections. That baseline directs agents to use exact
corrective Tool diagnostics before further discovery and to change approaches
when repeated actions fail for the same reason. Default Tool guidance treats
`apply_patch` match locations, contexts, and closest current matches as
informational exact-text recovery aids; it recommends re-reading only when those
diagnostics are insufficient and forbids shell editing as a workaround for a
dedicated editing-Tool failure unless the task genuinely requires shell
behavior. Those prompt-level policies do not change Tool mutation semantics;
the separate runtime nudge described under Hooks only adds transient guidance.

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
- `/mod <name>` selects that Mod for later tasks and follow-ups.
- `/mod none` clears the Mod selection.
- `/skill` shows the current active skill and available skills.
- `/skill <name>` sets the active skill for future tasks and follow-ups in the
  current CLI process.
- `/skill none` clears the active skill.
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

Selections are process-local CLI state. Selecting a Mod clears a standalone
Skill selection, and selecting a standalone Skill clears a Mod selection, so
there is never an ambiguous simultaneous override. Each command's `none` form
clears only that kind of selection. The startup panel shows `Skill: <name>`
when the CLI is launched with an active standalone Skill.

Specialization may change between runs in one session. Each run must use a
coherent current prompt, Skill, Tools, and Hooks while preserving prior
conversation history. At the start of an existing non-empty session,
`AgentLoop` replaces all replayed system messages with the newly constructed
Agent's one intended system message; it never inserts the Agent's original
initial user task again. The replacement is persisted as an append-only
`system_message_reconciliation` event. `SessionStore.load_messages()` applies
the latest such event during replay, so old specialization instructions do not
return after restart and exactly one current system message is exposed.

Each new run and follow-up appends a non-transcript `run_context` event to
`session.jsonl`. This records the active `skill_name`, the actual filtered
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

Immediately before an ordinary model turn, `AgentLoop` derives a model-visible
history from the canonical transcript. The newest configured number of Tool
results remain byte-for-byte unchanged. Older built-in results may retain a
bounded deterministic view of source, command output, or failed-patch
diagnostics while keeping status, path, line, return-code, failure, and
candidate metadata. Unknown Tools remain unchanged. This rendering never
mutates `session.messages` or append-only session storage, and assistant Tool
calls retain their original `tool_call_id` pairing with Tool results. Core's
`ToolResultTrimmingSettings` supplies direct harness-tuning variables and can
disable the transformation; these experimental values are not persisted in
Code Squid's application settings. Compaction remains a separate operation.

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
- `mods/<mod-name>/mod.yaml` stores canonical user Mod packages with optional
  package-local Skills, Tools, and Hooks.

Mod metadata supports an optional top-level semantic accent, for example
`accent: purple`. The effective default is `cyan`; allowed names are `cyan`,
`blue`, `green`, `yellow`, `orange`, `red`, `pink`, `purple`, `white`, and
`gray`.

The host selects a Mod for each run; Core does not persist a globally active
selection.

## Settings

Settings have two explicit ownership layers. `code_squid/settings.py` owns the
human-facing Code Squid shape, application-wide persistence, product defaults,
saved selection, and optional environment overrides. `code_squid.app_paths`
owns the location policy. The application translates those values into
`squid_core.settings.RuntimeSettings`; Core owns only the effective provider
values and runtime validation semantics used by the spawner, loop, approval
policy, and compactor.

Code Squid reads settings from its application home:

```text
~/.code-squid/settings.json
```

When `CODE_SQUID_HOME` is set, the path is
`<CODE_SQUID_HOME>/settings.json`. If that file does not exist, the current
workspace's legacy `.code-squid/settings.json` is adopted best-effort and left
in place. An existing application-wide file is always authoritative; settings
from multiple workspaces are never merged. All subsequent writes target only
the application-wide file.

Missing settings are allowed. Defaults keep the CLI usable with LM Studio:

- model base URL: `http://127.0.0.1:1234/v1`
- API key: `lm-studio`
- model name: `qwen3.5-9b`
- provider: `lm_studio`
- temperature: `null`
- reasoning mode: `null` (do not override provider/model behavior)
- display debug: `false`
- approval mode: `never`
- max tool steps: unlimited
- assistant text streaming: disabled
- compaction: enabled at an estimated 25,000 input tokens, compacting about 80%
  of eligible token weight while preserving at least 2 recent chunks verbatim

Supported settings sections and fields:

- `model.name`
- `model.provider`
- `model.temperature`
- `model.reasoning_mode`
- `providers.<provider_id>.base_url`
- `providers.<provider_id>.api_key`
- `providers.<provider_id>.api_key_env`
- `display.debug`
- `runtime.approval_mode`
- `runtime.max_tool_steps`
- `runtime.stream_assistant_text`
- `compaction.enabled`
- `compaction.trigger_input_tokens`
- `compaction.compact_fraction`
- `compaction.min_recent_chunks`

The `providers` mapping is sparse: it contains only connection values a user
explicitly saved. Switching `model.provider` changes which provider-scoped
connection is resolved and never removes another provider's entry. Missing
providers and missing fields inherit the corresponding application-owned
`ProviderProfile` defaults without writing those defaults to disk. Existing
flat `model.base_url`, `model.api_key`, and `model.api_key_env` fields remain a
supported input shape: they are interpreted as belonging to the saved
`model.provider`, then moved into that provider's scoped entry on the next
provider selection or connection mutation. A scoped field wins if both shapes
are present during a partial migration. Model selection remains one exact,
provider-independent `model.name`.

Supported provider values are `squid_models`, `lm_studio`, `ollama`,
`openrouter`, and `openai_compatible`. Their shared Code Squid application
profiles live in `code_squid/provider_setup.py`; that module owns friendly
identity, product defaults, readiness/discovery orchestration, and the shared
provider/model mutation operations. CLI presentation remains under
`code_squid/console/`, and provider HTTP details remain in
`squid_core/providers/`.
Supported approval modes are `never`, `guarded`, and `always`.
`runtime.max_tool_steps` is either `null` or a positive integer.
`runtime.stream_assistant_text` is a boolean. When enabled with a streaming
provider, the loop emits `assistant_message_started` before generation and
`assistant_delta` events for visible text chunks, then emits the normal full
`assistant_message` or `final_message` after the complete reply is assembled and
validated. These events carry the `narration` or `final` phase described in
Events And External Wrappers. Streamed deltas are UI events only; tool execution
still waits for the full validated assistant response.
`model.temperature` is `null` or a number from 0 through 2.
`model.reasoning_mode` is `null`, `off`, `low`, `medium`, or `high`. `null`
means the provider request receives no persistent reasoning-specific setting,
preserving its existing model/provider default.

Environment overrides are optional development, headless, and automation
inputs—not the normal user configuration UX. Current overrides are:

- `CODE_SQUID_BASE_URL`
- `CODE_SQUID_API_KEY`
- `CODE_SQUID_MODEL`
- `CODE_SQUID_PROVIDER`
- `CODE_SQUID_TEMPERATURE`
- `CODE_SQUID_REASONING_MODE`
- `CODE_SQUID_DEBUG`
- `CODE_SQUID_STREAM_ASSISTANT_TEXT`

`CODE_SQUID_API_KEY` wins over the active provider's saved `api_key_env`, which
wins over its saved `api_key`; absent saved fields fall back to the profile.
OpenRouter's profile defaults `api_key_env` to `OPENROUTER_API_KEY`. A provider
environment override resolves that provider's own saved connection or profile
defaults and does not inherit another provider's URL or credential. Environment
values affect only the process's effective settings and are never copied into
the sparse persisted mapping by loading.
`CODE_SQUID_STREAM_ASSISTANT_TEXT=1` enables assistant text
streaming and `0` disables it. There are no compaction environment overrides in
the current code. Interactive provider and model writes never mutate those
environment variables: the saved value is reported separately when
`CODE_SQUID_PROVIDER` or `CODE_SQUID_MODEL` remains the effective override.

The interactive loop reloads settings after `/provider`, `/model`, `/safety`,
and `/compact-at`, so the next new or follow-up run in the same process receives
the new effective settings. The small field-specific writers preserve
unrelated JSON settings. Workspace switching reloads that same application
file while rebuilding only workspace-bound session, undo, display, and
discovery state.

Invalid settings JSON, invalid section shapes, invalid provider names, unknown
approval modes, missing configured API-key environment variables, invalid
temperatures, invalid compaction settings, and invalid step limits fail during
settings loading.

## CLI Commands

Current commands:

```bash
python main.py
python main.py --cwd /path/to/project
python main.py --skill <name>
python main.py safety
python main.py safety strict
python main.py safety balanced
python main.py safety yolo
python main.py skill
python main.py sessions
python main.py show latest
python main.py show <session_id>
python main.py resume latest
python main.py resume <session_id>
python main.py undo
python main.py help
python main.py --help
python main.py -h
```

Running with no arguments starts an interactive prompt. A first task starts a
new session; later tasks in the same process continue the active session as
follow-ups unless the user enters `/new`. `/help` prints prompt help, and only
the slash-prefixed `/exit` exits the interactive prompt. Bare `exit` and `quit`
remain ordinary task text. Interactive
specialization, runtime, and control commands are listed above.

`--cwd` selects the workspace/repo root. It defaults to the current directory
and must point at an existing directory.

Shell `resume` selects the saved session and enters the same persistent
interactive loop as a fresh invocation. Each authored follow-up loads the
saved conversation, appends a user message, marks the session active, creates
a fresh latest-only undo buffer, and continues that session. Slash commands
remain available before and between follow-ups.

`safety` prints or writes the configured approval mode. Friendly CLI safety
names map to settings values this way:

- `strict` -> `runtime.approval_mode = "always"`
- `balanced` -> `runtime.approval_mode = "guarded"`
- `yolo` -> `runtime.approval_mode = "never"`

## Provider Model

LM Studio, Squid Models, OpenRouter, and generic OpenAI Compatible all retain
the existing `OpenAICompatibleProvider` chat-completions inference transport.
Their identities remain distinct so setup probes can use the correct contract:

- Squid Models defaults to `http://127.0.0.1:8080/v1` and key placeholder
  `local`; readiness is a successful `GET http://127.0.0.1:8080/health`, and
  discovery uses `GET /v1/models`.
- LM Studio defaults to `http://127.0.0.1:1234/v1` and key placeholder
  `lm-studio`; native `GET /api/v1/models` supplies discovery, and readiness
  requires at least one LLM with a loaded instance. Inference remains
  `/v1/chat/completions`.
- Ollama defaults to `http://127.0.0.1:11434`; both lightweight readiness and
  discovery use native `GET /api/tags`, while inference remains `/api/chat`.
- OpenRouter defaults to `https://openrouter.ai/api/v1` and
  `OPENROUTER_API_KEY`. Its public, unauthenticated `GET /models` supplies
  discovery even when no key is configured. Inference readiness remains
  separate and requires an API key.
- OpenAI Compatible defaults to `http://127.0.0.1:8000/v1` with key placeholder
  `local`; generic authenticated `GET /models` supplies readiness and discovery.

Provider selection persists the requested identity and applies its normal
connection defaults before readiness is probed. A failed readiness probe is
reported as `not connected` but does not undo selection, so the shared slash-
command/startup operation can bootstrap provider-specific URL or credential
configuration. Readiness still gates inference and remains visible in status.

The selected model ID is never replaced by a provider profile. Startup model
selection and `/model <name>` persist it verbatim; Core's spawner passes that
same `ProviderSettings.model_name` into `ModelAdapter` and then provider
inference. Provider switching preserves the configured ID and reports when the
new connected provider does not expose it.

Model discovery calls each provider's `list_models()` directly instead of
requiring `is_ready()` first. This preserves local discovery behaviorâ€”a stopped
local service fails its own catalog requestâ€”while allowing public catalogs to
remain visible independently of inference credentials. Core provider
construction defaults to the inference boundary and therefore still rejects a
keyless OpenRouter configuration; the application discovery seam explicitly
requests discovery-only construction.

OpenRouter is supported through the OpenAI-compatible provider path by setting
`model.provider` or `CODE_SQUID_PROVIDER` to `openrouter`. It still uses
`OpenAICompatibleProvider`, while Core's small provider helper configures assistant
tool-call replay with `content: null` for assistant messages that have
`tool_calls` and no content. This provider-specific behavior is handled before
messages are sent to the provider.

Reasoning configuration remains a single optional
`ProviderSettings.reasoning_mode` value and travels through built-in provider
construction to the concrete request builder. Only the explicit `openrouter`
identity currently translates it: `off` becomes OpenRouter reasoning effort
`none`, while `low`, `medium`, and `high` retain their names. `null` emits no
reasoning field. LM Studio, Squid Models, Ollama, and generic OpenAI-compatible
requests currently ignore the normalized setting because no provider mapping
is defined for them; there is no capability registry or model-specific policy.

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
report concrete limitations. Formatting guidance is not runtime-enforced. The
terminal display removes a `TASK COMPLETE` marker if a model includes it;
finalization does not depend on that marker.

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

`squid_core/compaction/compactor.py` asks
`squid_core/compaction/token_estimate.py` for a rough estimate of the current
transcript size. The estimate serializes messages to JSON/text and uses simple
length math; it is not an exact model tokenizer. The adjacent
`compaction_status.py` reports context usage against the configured compaction
trigger without changing those estimation semantics.

The compaction request uses the generic Core-owned prompt in
`squid_core/compaction/prompts.py`. It has no dependency on Code Squid's
application prompts.

Compaction triggers when:

- `settings.compaction.enabled` is true
- estimated input tokens are at least
  `settings.compaction.trigger_input_tokens`
- there are eligible chunks available beyond the configured minimum recent tail

When triggered, compaction:

- preserves the initial system message and initial user task message
- chunks the remaining transcript
- never splits an assistant message with `tool_calls` from its following
  `role: "tool"` result messages
- estimates the token weight of the chunked history only, excluding the
  protected prefix, and rounds the configured fraction target up to a whole
  token
- selects oldest whole chunks in order until their cumulative estimate reaches
  that target or the minimum recent-chunk boundary prevents further selection
- summarizes older chunks with `ModelAdapter.complete_text(...)`
- replaces those older chunks with one assistant message headed
  `# Compacted Working Context`; the assistant role marks it as model-generated,
  while its preamble explicitly says it is lossy, context-only, non-authoritative,
  and cannot add, replace, or override real user requirements
- keeps at least `settings.compaction.min_recent_chunks` newest chunks verbatim

The application and Core defaults are `enabled=True`,
`trigger_input_tokens=25_000`, `compact_fraction=0.80`, and
`min_recent_chunks=2`. Only the initial user message is protected; later real user
messages remain subject to the existing chunk selection policy. A prior
`# Compacted Working Context` assistant message is an ordinary eligible chunk on
a later pass, so repeated compaction naturally folds an older summary into the
next summary without a separate memory mechanism. The removed
`keep_recent_turns` JSON field is ignored if it remains in an older settings
file; users who customized it must replace it with `min_recent_chunks`.

`AgentLoop` supplies one callback that persists each lifecycle event through
`SessionStore.append_compaction_event(...)` when storage is wired in and also
publishes the authoritative start event through the loop's existing observer
seam. The compactor writes a chronological diagnostic lifecycle beside normal
transcript entries:

- `compaction_check` records the estimate, configured trigger, threshold result,
  whether compaction is possible, and compactable-selection diagnostics
- `compaction_started` records the pre-compaction message count plus eligible,
  target, selected, and preserved token/chunk selection details
- `compaction_request` records the estimated request size and configured
  provider/model immediately before the model call
- optional `compaction_reasoning`, exact `compaction_summary`, and optional
  `compaction_response_meta` events preserve normalized response diagnostics
- `compaction_applied` records before/after token estimates and message counts
  only after the in-memory rebuild and event append succeed
- `compaction_failed` records `prepare`, `model_request`, `response_parse`,
  `session_rebuild`, or `persistence` plus a concise exception description,
  then the original exception continues through the existing error path

`ModelAdapter.complete_text(...)` retains its existing `content` and `usage`
result fields and additionally exposes normalized `reasoning` and
`finish_reason` when the provider supplies them. Compaction events are
diagnostic, not transcript messages: `SessionStore.load_messages()` continues
to ignore them and replay only message and system-reconciliation entries.
The CLI reacts only to the authoritative `compaction_started` event, rendering
`🌀 Compacting context...` through the same indented, dim notification path
used by neutral tool/status activity. Checks that do not compact stay silent.

Compaction is transcript compression for continuation context. It does not
provide durable workspace memory.

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
this path. `SessionStore.load_messages()` replays `type: "message"` entries and
applies `system_message_reconciliation` entries; model-reply and rejection
diagnostics never enter canonical history or reach the model.

Current session statuses are:

- `active`
- `complete`
- `failed`
- `abandoned`
- `interrupted`

Resume selects an active saved session inside the persistent CLI loop. A later
authored task loads messages with `SessionStore.load_messages()`, appends a
follow-up user message, marks the session active, creates a fresh undo buffer,
and continues the same saved session. `latest` resolves through the explicit
workspace sessions path supplied by `code_squid.app_paths`.

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

The protected built-in Tool surface is:

- `read_file(path, start_line=None, end_line=None)`
- `write_file(path, content)`
- `apply_patch(path, old_text, new_text)` or candidate selection with `match_id`
- `run_command(command)`

The `apply_patch` JSON schema declares all four arguments in the top-level
object `properties`; its `anyOf` branches carry only the two alternative
required-field sets. This permits candidate-selection retries to repeat normal
fields while remaining acceptable to OpenAI-compatible providers that require
root-level properties.

`read_file`:

- requires an absolute path
- reads UTF-8 text
- supports optional 1-based inclusive `start_line` and `end_line`
- keeps read sizing in Core's small `ReadFileSettings`, whose defaults cap
  whole-file reads at 1,000 lines and target at least 150 lines for ranged reads
- returns whole-file reads unchanged through 1,000 lines
- for larger whole-file reads, returns 500 head lines and 500 tail lines with
  explicit `returned_line_ranges` and model-facing `truncation_guidance`
- does not truncate ranged reads
- expands a ranged read below 150 returned lines around the requested area,
  shifting the window at file edges to retain up to 150 lines when available;
  ranges already at least 150 lines and requests starting past EOF are unchanged
- reports the effective expanded `start_line` and `end_line`, so runtime Hooks
  track the content actually returned rather than only the requested interval
- preserves the existing content, character-count, truncation, ranged-read,
  and total-line metadata; the character counts describe the returned content
  but do not impose a second read limit
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

- requires an absolute path for a normal patch request; a known run-local
  `match_id` selects candidate mode, while an empty or unknown ID falls back to
  normal mode only when all three normal patch arguments are valid strings
- reads and writes UTF-8 text
- performs exactly one exact text replacement
- requires `old_text` to occur exactly once in the current file
- fails without modifying the file when `old_text` is missing or not unique
- reports up to three bounded line-context records when `old_text` is not
  unique, with a distinct selectable candidate ID for each reported occurrence
- searches same-sized line windows with a conservative similarity threshold
  when `old_text` is missing; an above-threshold diagnostic is exposed as one
  selectable candidate without changing the threshold or matching algorithm
- retains candidate path, original request text, exact candidate text, and
  original character offset only in the current run's `ToolExecutor`
- resolves candidate selection by re-reading the file and requiring the stored
  exact candidate text at its original offset; stale or unavailable IDs fail
  without searching for a substitute
- accepts a redundant path only when it identifies the stored target and ignores
  redundant old and new text so stored candidate values remain authoritative
- invalidates all outstanding candidates for a file after any successful
  `write_file` or `apply_patch` mutation of that file, while other-file and
  failed mutations leave them available
- returns affected before/after line ranges plus the existing compact
  character-count metadata after a successful replacement
- is preferred for small localized edits to existing files
- is checked against the workspace boundary before execution unless trusted
  outside-workspace access is configured or approved
- is snapshotted by `ToolExecutor` before mutation when undo storage is wired

Built-in Tool schema descriptions contain only mechanical purpose, appropriate
use, and argument/behavior constraints. Agent narration and workflow guidance
remain owned by the Agent prompt rather than the Tool subsystem.

Candidate selection resolves diagnostic ambiguity. Mutation remains exact and
revalidated; line numbers, context, and similarity are never authoritative for
editing.

`run_command`:

- on Windows, invokes the detected PowerShell executable with `-NoProfile` and
  `-Command`, without `shell=True`
- on other platforms, executes through the system shell with `shell=True`
- uses `repo_root` as the working directory
- merges stderr into stdout
- times out after 15 seconds
- returns `ok` based on process return code
- attaches `failure_class` to every failed execution using only timeout state,
  launch errors, return code, platform/shell identity, and narrowly recognized
  shell diagnostics; uncertain completed failures use `process_failed`
- classifies normalized timeouts as `timeout` while retaining `timed_out: True`
- can classify strong signals as `command_not_found`, `shell_syntax_error`,
  `path_not_found`, or `permission_denied`; unrecognized launch failures use
  `unknown_failure`
- includes the configured `platform` and `shell` on failures so runtime
  recovery guidance can report factual environment context
- preserves the command's useful combined output and does not rewrite or retry
  commands
- truncates large output with the unchanged shared 12,000-character head/tail
  truncation
- is used for discovery, verification, and shell behavior
- is not undo-protected, even if it mutates files

There is no built-in structured search Tool, repo-policy Tool, dedicated test
runner, or browser Tool. Discovery, verification, and most shell behavior use
`run_command`.

These four built-ins are the normal active registry when no Skill or Mod is
selected. A standalone Skill can filter the built-ins and can activate named
standalone user Tools from `<app-home>/tools/`. A selected Mod uses the exact
ordered Tool inventory shared by `mod.yaml` and its default Skill, drawing
custom Tools from the Mod first and then from standalone user Tools. Built-ins
win name collisions. Generic Core callers may instead supply their own Tool
registry. An explicit `allowed-tools: []` produces an empty active registry.

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
defaults and baseline coding discipline. `code_squid/agent/coding.py` exports
the product-owned `CodingAgent` name as an alias of the generic Core Agent.

`code_squid/settings.py` owns application-wide settings parsing, persistence,
Code Squid defaults and selection, legacy workspace adoption, and optional
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

`squid_core/model_adapter.py` owns provider response normalization and replay message
shaping. Provider-specific HTTP/API calls stay in `squid_core/providers/`.

`squid_core/compaction/compactor.py` owns transcript compression mechanics;
`squid_core/compaction/prompts.py` owns the generic continuation-summary
prompt; `squid_core/compaction/compaction_status.py` owns context usage and
compaction-trigger reporting; and `squid_core/compaction/token_estimate.py`
owns their shared rough transcript token estimate. These modules do not import
Code Squid application prompts, and compaction should not become workspace
memory.

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
`code_squid/console/ui/` owns terminal presentation and input. `TerminalDisplay`
coordinates lifecycle state and delegates startup, approval, Tool, and reusable
formatting details to the sibling presentation modules described above. Tool
event display is the reliable UX layer for what happened, while model-native
narration is encouraged by prompts.

## Current Limitations

- OpenRouter may produce invalid multi-tool replies despite
  `parallel_tool_calls=False`; current handling is reject-and-retry through
  correction messages.
- Action notes are prompt-guided. Runtime rejects empty non-final replies and
  multi-tool replies, but it does not fully enforce action-note quality.
- Command and file access is not a hardened sandbox. Workspace checks and
  guarded command checks are approval/preflight mechanisms.
- Compaction uses rough JSON/text length estimates, not exact tokenization.
- Core records model request failures, unexpected run failures, requested
  cancellation, and boundary-level interruptions before preserving the existing
  exception or cancellation control flow for its host.
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
- Keep provider transport separated from provider-response normalization.
- Keep prompt guidance separate from runtime enforcement.
- Keep durable session storage append-only and boring.
- Keep undo latest-only until a real workflow requires more.
- Prefer accurate boring descriptions over aspirational architecture.

Small, inspectable, stupid simple.

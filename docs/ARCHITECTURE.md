# Code Squid Architecture

## Purpose

Core integration uses `workspace_root` for runtime parameters, Session and
ToolExecutor attributes, Hook contexts, and saved-tool execution context keys.
The application construction and CLI callers use the same terminology. This
pre-release rename has no compatibility aliases. Session/undo metadata and the
session viewer use the same `workspace_root` key, with no legacy fallback or
migration. Older development metadata may be incompatible; filesystem layout
and session/undo lifecycle behavior are unchanged. Core Agent and default executor
construction now enforce standalone Skill tool permissions: omitted lists keep
defaults, explicit empty lists disable tools, and explicit lists restrict the
available registry. Mod discovery/loading and resolution can receive the same
application tool registry; Code Squid continues using Core built-ins by default.

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

Repository-local `.code-squid/` directories hold workspace runtime state and
should be gitignored. Application preferences live in the Code Squid home.

The dependency direction is one-way: Code Squid supplies application defaults
and runtime wiring to reusable Squid Core components. Those reusable components
do not import Code Squid prompt or policy modules. `code_squid/` is the product
and application layer; `squid_core/` is the reusable agent runtime.

```text
Code Squid -> squid-core
Code Squid -> squid-providers -> squid-core response/provider contracts
squid-core -> no application or concrete transport imports
```

The packages are actual sibling Git repositories with independent packaging:

```text
<workspace>/code-squid/       # code_squid, main.py, application tests
<workspace>/squid-core/       # squid_core, reusable runtime tests
<workspace>/squid-providers/  # squid_providers, transport/catalog tests
```

Below, `squid_core/` and `squid_providers/` paths refer to their respective sibling
repositories. Neither source package is bundled into Code Squid. Requirements
install all three unpublished checkouts editably; see README for commands.

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
    `squid_providers.settings` owns effective `ProviderSettings` validation and
    reasoning-mode values. `Settings.to_provider_settings()` carries selection,
    model, URL/key, shared sampling/reasoning controls, and provider-owned config;
    `to_runtime_settings()` carries only generic execution settings.
  - `console/cli/` owns terminal workflow and control. `cli_options.py` handles
    CLI options and workspace resolution; `cli_commands.py` handles launch-time
    dispatch; `prompt_loop.py` owns the one persistent interpreter used by
    fresh and resumed sessions; `runtime_commands.py` owns interactive
    provider, model, safety, and reasoning-display changes; `control_commands.py` owns interactive
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
    sole owner of opening the store and loading a resumed transcript. The
    session runner also owns the application boundary for exhausted model
    requests: it records the run as failed, writes and displays the existing
    error log, and returns control to the persistent prompt. Other exceptions
    escaping an active run are marked failed when storage remains available,
    written to the same diagnostic log, rendered as one concise run-stopped
    message, and returned as a nonzero result without a terminal traceback.
  - `console/ui/` owns terminal presentation and input. `display.py` keeps
    `TerminalDisplay` as the lifecycle coordinator used by the Agent loop.
    `header_layout.py` owns the explicit startup-scene geometry: safe draw
    width, height-aware centered title position, two-row title/panel gap,
    centered compact panel rectangle, and balanced outer rain margins. `banner.py` owns the panel's
    Provider, Model, Safety, Mod, Session, optional standalone Skill, and
    concise Workspace content. The Session row retains the fixed panel
    rectangle by keeping blank rows between fields rather than around the
    complete field list. `approval.py`
    owns approval panels, prompts, and compact results; `tool_display.py` owns
    tool/action labels, command recognition, and debug result projection; and
    `formatting.py` owns shared styles, links, path shortening, wrapping, and
    the lightweight Markdown interpretation used by narration and final
    responses. Its inline token layer chooses line breaks from visible Unicode
    cells before applying ANSI styles or OSC-8 links. Its block layer supports
    headings, one-level lists, blockquotes, fenced code, horizontal rules, and
    constrained pipe tables. Panel-specific mascot placement and final-report
    indentation remain in `display.py`. `binary_header.py` is a terminal-I/O-free
    rain model and semantic compositor. It excludes the panel rectangle while
    placing rain, then overlays the title and panel into prompt_toolkit styled
    fragments.

    `startup_application.py` owns the complete live startup surface: rain,
    title, menu panel, and boxed multiline `BufferControl`. It creates one
    temporary, fullscreen prompt_toolkit `Application` on the alternate screen;
    that Application's refresh timer advances rain and invalidates the same renderer. Submission
    makes the Buffer read-only, publishes its task immediately, and starts an
    eight-frame global rain-fade state in `BinaryRainHeader`. The blocking
    Application event loop lives on one narrowly owned renderer thread so the
    caller can begin model work during the nominal 350 ms fade; this is not a
    second renderer or an independent rain worker. Production startup code
    uses the last clean rendered Screen only to append a static handoff frame
    after Application cleanup and primary-buffer restoration. It does not
    use cursor reports or custom ANSI repainting. The composer follows the shared
    product policy of 2 through 14 visible content rows, capped again by the
    rows physically available below the startup scene, separator, and frame.
    The title/menu block has seven rain rows above and below it in the full
    30-row scene (32 with the optional Skill row). The panel itself remains
    13 rows (15 with Skill). A height budget reserves the composer minimum,
    then contracts both outer margins evenly; only viewports too short for the
    central block clip its bottom. The real Output remains the sole source of
    viewport geometry. Once either the product or physical cap is reached, the BufferControl scrolls internally while
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
    clean frame renders. Once the startup canvas is released, one static
    copy of that clean scene is appended to the primary buffer, preserving
    wide glyphs and the submitted composer. Projection stops at the last visible
    row of the clean frame; fullscreen canvas padding below the composer never
    enters primary scrollback. Internal scene/separator rows are preserved.
    The append cursor lands immediately after the composer, so first-run thinking
    and reasoning/narration use the same one-blank-line run separator as follow-ups.
    Animation never paints the primary
    buffer: cursor-relative inline redraws could strand obsolete rain in
    scrollback after a shrink or redraw and cannot repaint those offscreen rows. If
    narration, Tool or
    debug output, approval, failure, interruption, cleanup, or another direct
    CLI writer needs the terminal first, `TerminalDisplay` forces the same
    model to its clean state and synchronously joins the Application before the
    writer proceeds. Ctrl+C also exits and joins the startup lifecycle safely.
    Ordinary later prompts remain composer-only
    `PromptSession` instances. Their product-owned root in `ui/prompt_input.py`
    bounds painting to the layout's current preferred height, including any
    visible PromptSession toolbars. Preferred sizing alone is insufficient:
    the inline renderer may offer the whole remaining viewport or a previous
    taller allocation, and an ordinary HSplit paints its unused rows as blank
    filler that increases Screen.height and reserves terminal space. The
    bounded root keeps editing and the final done redraw at the measured
    footprint. Prompt-toolkit measures cell-aware wrapping at the actual inner
    width; shared content policy still caps it at 2 through 14 content rows,
    plus two border rows, with the physical viewport as the final cap. The
    ordinary width sink cannot claim vertical space. PromptSession owns final
    redraw and cursor placement immediately below the retained box; downstream
    command/run presentation supplies its existing minimal spacing. No custom
    transcript projection, terminal-buffer switch, or scrollback erase is used
    for ordinary prompts. `/new` creates a fresh temporary Application and
    resets rain on a fresh temporary alternate canvas. StartupApplication's
    renderer thread owns the buffer boundary in `ui/terminal_session.py`:
    `startup_terminal(output)` enters before Application.run and restores primary
    after all fullscreen renderer cleanup, even on exceptions. `StartupOutput`
    delegates the renderer interface but makes renderer entry prepare only the
    selected alternate canvas and renderer exit a no-op; actual switching happens
    exactly once at the scene boundary. No session-wide AppSession override or
    Python stdout/stderr redirection is installed. Native Windows handle changes
    are flushed before and after restoration.
    Only composer submission arms clean-frame retention. Workspace selection
    returns STARTUP_WORKSPACE_SELECTED for CLI reconstruction; its completed
    fade restores primary without writing a spacer or snapshot. Provider,
    model, safety, Mod, and session selections update the existing alternate
    canvas. Replacement workspace Applications continue this transient cycle,
    preserving selected specialization and resetting workspace-owned session
    state when the root changes. Each completed cycle retains one final frame,
    guarded against repeat projection; cleanup without submission retains none.
    On final submission the owning thread writes two CRLFs at the restored
    primary append cursor before printing the retained clean scene. This finishes
    any partial transcript line and leaves one blank line (two if the cursor
    already follows a newline), independent of viewport height. Sequential frame
    printing scrolls naturally without clearing history or overwriting prior
    output; repeated `/new` cycles use the same compact separation.
    Failure/cancellation restores primary without retaining animated content.
    The fade/join seam releases ordinary writers only after restoration and the
    static projection. Caller-side KeyboardInterrupt also joins the renderer
    before cancellation prints. `/help`, runs, errors, follow-ups, approvals,
    and session output use the original primary Output and Python streams.
    `/new` temporarily repeats the startup boundary, then appends to the same
    primary transcript; it never discards history. The interpreter's `finally`
    still joins any remaining startup renderer. Normal exit leaves primary
    selected. No primary-screen or scrollback erase is issued by this boundary.
    Noninteractive commands do not enter the alternate screen.
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
    discards the submenu highlight. A saved-session activation selects the ID
    and returns focus to the same startup composer without ending its Application
    or starting a fade. Subsequent selections remain transient, and the last
    saved-session metadata replaces any pending notice. After final composer
    submission the CLI joins the fade and consumes that metadata into one dim,
    neutral, detail-indented status line on primary before dispatching the
    submitted input. No extra ordinary prompt is opened for session selection.
    New session, launch-time resume state, and subsequent follow-ups remain
    silent. The notice never opens the transcript
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
    That recent-path tuple is authoritative for Workspace viewport bounds,
    arrow movement, and activation. Submenu state is fully prepared before its
    mode is published, so rendering cannot combine Workspace presentation with
    a preceding provider, model, or session option list.
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
    `streaming_narration.py` owns the reusable provisional panel lifecycle.
    The CLI passes `TerminalDisplay.handle_event` to Core and translates
    narration and reasoning delta events into separate, sequential instances
    of that temporary region.
    The first visible TTY delta starts one temporary, nonfullscreen
    prompt_toolkit `Application` around a `FormattedTextControl`; subsequent
    deltas update its content and invalidate that renderer. A private pipe
    prevents this presentation-only Application from consuming stdin, while
    its real terminal `Output` remains the sole source of viewport and cursor
    geometry. The live panel contracts and rewraps from the current output
    width, rerenders the shared Markdown subset from each complete buffered
    snapshot, and leaves unmatched inline delimiters readable until later
    tokens complete them. Its `Window` hides the cursor while it owns the region. An
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
    `Using tool...`. The accepted action reasserts the same label so the pulse
    remains owned throughout synchronous Tool execution, even when settling
    static narration cleared its preparation state. Tool-result and existing
    run finalization boundaries stop the active pulse. Code Squid owns no
    raw cursor-up or clear-row repaint geometry for live narration.

    Provider-exposed reasoning uses the same fixed-width panel renderer as
    narration, with only a dim interior/text treatment, italic body text, and a
    `Reasoning:` label. `display.show_reasoning` is false by default and is the
    single persisted preference read by display construction and `/reasoning`.
    It does not alter configured provider reasoning mode, effort, budget, prompts, or
    requests. The built-in OpenAI-compatible and Ollama transports normalize
    the first populated `reasoning`, `reasoning_content`, or `thinking` field
    in each chunk through an optional reasoning-delta callback. `AgentLoop`
    publishes those chunks as `assistant_reasoning_delta`; the first non-empty
    delta opens one live reasoning panel and later deltas update that same
    prompt_toolkit region. The first narration delta or Tool-preparation
    boundary settles reasoning before existing narration/tool presentation
    proceeds. The completed normalized reasoning remains the fallback when a
    provider exposes only a completed field, and it only settles bookkeeping
    when a live panel was already shown. Hidden reasoning and providers without
    reasoning deltas retain the existing live narration path without delay.

    `prompt_input.py`, `sessions.py`, and `spinner.py` retain their focused
    input, saved-session, and animation responsibilities. The ordinary task
    composer remains a non-fullscreen `PromptSession`, but its active prompt is
    rendered in a dynamically tall 61-cell rounded frame with two cells of
    left padding and one right gutter. The normal PromptSession input container
    retains up to 58 cells inside the borders and uses the same product and
    physical viewport caps as startup. The frame disappears from active
    control on submission and remains as static output in the session buffer.
    PageUp/PageDown move by pages, Ctrl+Up/Ctrl+Down move by
    half pages, and Ctrl+Home/Ctrl+End retain their standard buffer-boundary
    behavior. A one-row scroll offset keeps the cursor away from the top and
    bottom borders when the viewport has enough room. Approval prompts continue
    to use the shared unboxed input helper. Shift+Enter and Alt+Enter normalize
    to the multiline Ctrl+J action, while ordinary Enter submits. Its marker is
    hidden without changing input alignment while the startup menu owns focus.
    Normal run output uses sequential output in the primary buffer and 65-column panels. Their
    Markdown content retains the original 56-cell wrapping width, with the
    additional physical width rendered only as right-side padding. While
    streaming is enabled, one provisional narration panel grows in place and
    becomes static terminal output when the validated assistant callback settles
    it; non-streamed narration remains a static print. The final report and an
    optional Changed files section share one completion panel. `final_message`
    discards any provisional narration and retains only the current report text
    until `loop_finished` supplies the session's written paths. The section
    lists only files written by the run and is omitted when that set is empty.
    Panel rendering does not own buffer switching or introduce a managed
    transcript or persistent terminal region.
    Tool results, approvals, warnings, and non-success status remain outside
    these panels, and standalone run/report/file dividers are not emitted.
    Every composer and run-panel border uses the same dim terminal-default
    styling and imports one product-owned 61-cell width from `formatting.py`.
    Static panel measurement strips ANSI/OSC sequences before calculating the
    padding needed to keep the completion panel's right border aligned.
    Normal thinking uses one neutral, CLI-owned four-frame dot pulse; neither
    its symbol nor its active label receives the current Mod accent. The label
    remains `Thinking...` until a specific tool is known, when the same spinner
    line and timing switch to the CLI-owned Tool activity label and retains it
    through execution. Narration and
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
  - `atomic_json.py` owns small same-directory atomic JSON replacement. It
    serializes and syncs once, then retries only `PermissionError` from the
    final replacement across a bounded 140 ms window to tolerate transient
    Windows destination locks. Exhausted and non-permission failures propagate,
    with the temporary file removed while the prior destination stays intact.
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
  - Only the generic `BaseProvider` contract and `StreamCancelled` control signal
    remain here. Core and transports share the same cancellation exception
    identity. Its initializer imports no transport or SDK.

- `squid_providers/`
  - Independent sibling `squid-providers` repository/distribution.
    It imports only `squid_core.model_response` and `squid_core.providers.base`.
    There is no reverse Core dependency and no old transport-path re-export.
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
  quirks, and vision wire conversion. Mixed tests were split by ownership.
  Fresh-process import guards and source checks enforce dependency direction.

- Packaging and support files
  - Code Squid's root `pyproject.toml` builds only `code_squid` and `main.py`,
    requiring Core, Providers, prompt_toolkit, and wcwidth.
  - `../squid-core/pyproject.toml` builds only Core with its generic document/image
    reader dependencies, without OpenAI/httpx.
  - `../squid-providers/pyproject.toml` builds only Providers, requiring Core,
    OpenAI, and httpx. Metadata dependency names identify local distributions;
    editable paths supply these unpublished packages together.
  - `README.md` documents sibling installation and independent test commands.
  - `docs/provider-extraction.md` records moved source/test ownership.

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

Code Squid can enable its `RepeatedFailureNudge` Hook at this seam. The
application Hook retains its exact-action detector: three consecutive failures must
have the same Tool, JSON arguments, and scalar `error`; success, an
uncategorized failure, or any changed action/category resets that streak. The
same Hook also has an independently configured `run_command` detector. It
tracks one structured recovery cause at a time across different command
strings. Concrete shell and launch classes use shell/environment guidance;
timeouts use separate deadline guidance. Ordinary completed-process failures
(`process_failed`) and cancellations remain diagnostics without a broad
command-recovery nudge. A changed failure class, a successful command, or a
successful built-in `write_file`/`apply_patch` resets the command streak, while
unrelated discovery Tools are neutral. Successful file results are currently
the best mutation fact exposed to Hooks and can include no-op success; actual
change/no-op distinction is intentionally deferred. Approval, schema, and
pre-execution failures have no `failure_class` and do not enter this counter.
At either threshold the Hook returns cause-appropriate wording as transient
`HookResponse.additional_context` and immediately resets the applicable
counter, so another nudge requires three fresh failures. It never blocks,
rewrites, or retries a Tool action. `code_squid/hooks/no_progress.py` owns these
run-local detection mechanisms while `code_squid.agent_setup` owns the supplied guidance texts and
composition. This hook defaults to disabled. Its `source` remains configuration
metadata used by hosts; it no longer controls prompt rendering.

Code Squid owns `RepeatedFailureNudge`, `TooManyReadsNudge`, and
`PostVerificationNudge` in `code_squid/hooks/`, importing only generic lifecycle
contracts from Core. Its composition order is `TooManyReadsNudge`,
`PostVerificationNudge`, then `RepeatedFailureNudge`. The first two default to
enabled; repeated-failure guidance defaults to disabled.
`TooManyReadsNudge` counts successful `read_file` results and the source lines
they returned since the last successful `write_file` or `apply_patch`.
Commands, other Tools, and all failed results are neutral: they neither
increment nor reset either counter. Its `tool_result` handler updates those
counters without emitting state-dependent text. At the next
`before_model_turn` boundary it supplies one-turn advisory context when current
state has reached the fifth successful read or 1,500 returned source lines,
whichever comes first. Stronger context applies from the eighth read or 3,000
returned lines onward and continues after later reads. If one batch crosses
both thresholds, only the stronger current warning is rendered. These are
advisory thresholds rather than a read budget: the Hook never blocks or
transforms a result, so investigations can continue for a specific missing
fact, unmet requirement, or required verification.
The wording reports reads without a successful built-in edit, not inferred lack
of progress; read-only work and needed context recovery after compaction remain
legitimate reasons to read.

The volume counter consumes the result left by earlier host Hooks. It uses
`returned_line_ranges` when present and counts no source lines for an
`already_covered` result, while still counting that read action.
Malformed or missing range metadata contributes no volume and
leaves the action-count behavior intact. Unlike source coverage, both
behavioral counters intentionally survive transcript compaction; only a
successful built-in mutation or `before_run` resets them. A successful mutation
also clears any armed read warning before the model boundary, so an earlier
sibling read cannot describe state that the later edit reset. The thresholds
remain constructor arguments in Code Squid, which enables the Hook by
default. Application settings expose the small
`runtime.built_in_hook_settings` mapping, whose stable IDs are
`too_many_reads`, `post_verification`, and `repeated_failure`. The first two
default to enabled;
`repeated_failure` defaults to disabled.
`code_squid.agent_setup` consults those IDs while assembling a run and omits
each disabled built-in from the `HookRunner`; the application Hook
implementations do not know about application enablement. Caller-supplied,
Mod, and loaded user Hooks remain separate inputs and are not filtered by this
mapping. An explicitly supplied `HookRunner` likewise retains its Hooks before
the enabled Code Squid built-ins are appended. This explicit mapping is the
configuration seam for a future Mod or user override without making Hook
classes own product policy.

Sibling reads in one assistant batch pass through this pipeline synchronously.
Each final transformed result updates read counts and returned-line volume
before the next sibling executes. The read result retains its
own exact `content_returned_chars` metadata; the behavioral volume thresholds
remain line-based, so no separate cumulative character threshold or counter is
introduced by batching.

`PostVerificationNudge` is
self-contained: it records whether a successful `run_command` result explicitly
marked `verification=true` is current and the number of subsequent successful
Tool actions without an implementation change. Verification command text has no
identity semantics: once verification is current, another successful explicit
verification is continued post-verification activity rather than a fresh window.
A failed verification leaves verification non-current so the agent can address
the new, actionable failure normally.
Successful `write_file` and `apply_patch` results invalidate all facts tied to
the prior implementation. The Hook starts empty for every run and is not
persisted.

At every `before_model_turn` boundary where verification remains current, the
Hook exposes one compact advisory receipt: the latest explicit verification
succeeded, no successful built-in file edit has occurred since, and no later
explicit verification failure is unresolved. This starts on the model request
immediately following verification; no intervening Tool action is required.
Repeated successful verification still produces one receipt rather than stacked
copies. The receipt advises continuing only for a concrete unfinished
requirement, issue, or required validation, but does not block Tool use, force a
final response, or infer semantic task completion.

After verification is current, every successful non-mutation Tool result also
counts toward the existing stronger escalation, including reads, searches,
commands, other Tool activity, and repeated explicit verification. At the
default threshold of two actions, the Hook replaces the compact receipt for one
turn with `HIGH PRIORITY` guidance to identify an unfinished requirement
(including required documentation), concrete issue, or required validation, and
finalize when none remains. It then resets only the escalation counter, so
another strong warning requires a fresh threshold while the compact current-state
receipt remains available. A successful check does not establish task
completion. The first successful verification after a mutation, successful
structured mutation, failed explicit verification, and the start of a run reset
the counter. The latter three also clear the current receipt as applicable. A
later successful mutation in the same batch invalidates verification and clears
all verification guidance before it can be shown. A host-transformed result
marked `already_covered` still advances the count without arming stacked
post-verification guidance on that result. This policy deliberately
recognizes only the built-in `write_file` and `apply_patch` mutation Tools; it
does not infer workspace changes from command text or filesystem observation.

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
collaborator. Their former settings-only construction API has been removed;
they do not construct providers or adapters. There were no production Code
Squid callers of that settings-only convenience path.

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
`<repo>/.code-squid/undo`, while `workspace_root` separately continues to define tool
execution. Embedding hosts are not special Core concerns.

Hosts that already resolved a Skill and its executable tool registry may pass
them together as `resolved_skill` and `resolved_tools`. Core then skips Skill
discovery while retaining ownership of run construction, metadata, and
execution. The normal Code Squid builder also accepts `mod_name` and
`app_home`; it asks `squid_core.mods.resolve_mod(...)` for the selected resources.
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

Patch 1 changes only Core selection and the package contract. Hosts expecting
`Mod.tools`, manifest `tools`, standalone default-Skill fallback, or equal
permissions across all profiles must adapt. Desktop/API inventory and selection
assumptions await Patch 2; no picker, routing, session-field rename, provider,
or import/export changes are implemented here. Existing callers omitting
`selected_skill` still resolve the packaged default.

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
examples and moved source/shell-discovery preferences are included in the
non-replaceable application baseline policy, so
replacing any fixed section preserves them. Tool guidance and final report style
retain their existing append/replace behavior. Exact patch diagnostics and
selectable candidates remain preferred before rereading, and shell edits remain
an inappropriate workaround for a failed dedicated editing tool.

`PromptDefaults.agent_identity` replaces the pre-release `system_prompt_intro`
field; `AGENT_IDENTITY` replaces the old identity section directly, with no
compatibility alias. Current consumers and resources use the new names.
Core's `tools=None` selects built-ins, `tools={}` intentionally selects no tools,
and explicit registries are preserved exactly without merging or copying;
Code Squid continues to resolve its application registries before injecting them.
Core source/content omission markers now use `SQUID CORE`, including trimming
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

Settings have two explicit ownership layers. `code_squid/settings.py` owns the
human-facing Code Squid shape, application-wide persistence, product defaults,
saved selection, and optional environment overrides. `code_squid.app_paths`
owns the location policy. The application translates those values into
`squid_core.settings.RuntimeSettings`; Core owns only generic execution
validation used by the spawner, loop, approval policy, and compactor. Provider
selection/connection/model/reasoning values instead become provider-owned
`squid_providers.settings.ProviderSettings` through `to_provider_settings()`.

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

Missing settings are allowed. Code Squid chooses LM Studio as its initial
backend via `code_squid.settings.DEFAULT_PROVIDER`. URL/key defaults belong to
Providers; the initial provider/model choices and generic preferences belong
to Code Squid:

- model base URL: `http://127.0.0.1:1234/v1`
- API key: `lm-studio`
- model name: `qwen3.5-9b`
- provider: `lm_studio`
- temperature: `null`
- reasoning mode: `null` (do not override provider/model behavior)
- reasoning token budget: `null` (use provider/model behavior)
- display debug: `false`
- reasoning display: `false`
- approval mode: `never`
- trusted commands: none
- max tool steps: unlimited
- assistant text streaming: disabled
- model-request retries: 2, with a 250 ms initial backoff
- compaction: enabled at an estimated 25,000 input tokens, compacting about 80%
  of eligible token weight while preserving at least 2 recent chunks verbatim

Supported settings sections and fields:

- `model.name`
- `model.provider`
- `model.temperature`
- `model.reasoning_mode`
- `model.reasoning_token_budget`
- `providers.<provider_id>.base_url`
- `providers.<provider_id>.api_key`
- `providers.<provider_id>.api_key_env`
- `display.debug`
- `display.show_reasoning`
- `runtime.approval_mode`
- `runtime.trusted_commands`
- `runtime.max_tool_steps`
- `runtime.stream_assistant_text`
- `runtime.model_request_max_retries`
- `runtime.model_request_retry_backoff_ms`
- `compaction.enabled`
- `compaction.trigger_input_tokens`
- `compaction.compact_fraction`
- `compaction.min_recent_chunks`

The `providers` mapping is sparse: it contains only supported config values a user
explicitly saved. Switching `model.provider` changes which provider-scoped
connection is resolved and never removes another provider's entry. Configuration
commands pass the effective provider explicitly to the scoped settings writer,
so `/provider key` and `/provider url` update that provider even when
`CODE_SQUID_PROVIDER` differs from the saved selector. The saved selector and
other providers' entries are preserved; no flat fields or dual writes are added.
Missing providers and missing fields inherit the corresponding provider-owned
`ProviderProfile` defaults without writing those defaults to disk. Only scoped
connection configuration is read and written; old flat model connection fields
are not interpreted or migrated. Writers preserve unrelated JSON without dual
writes. Programmatic settings supply overrides through `model.provider_config`;
`ModelSettings.base_url`, `api_key`, and `api_key_env` are effective presentation
snapshots, not another configuration source. Model selection remains one exact,
provider-independent `model.name`.

The current catalog contains `squid_models`, `lm_studio`, `ollama`, `openrouter`,
and `openai_compatible`. Definitions and backend policy live in
`../squid-providers/squid_providers/catalog.py`. Code Squid consumes definitions
and persists supported arbitrary scoped overrides without concrete ID branches.
`providers.ollama.request_timeout` is validated and consumed by Providers;
flat timeout fields have no compatibility path. Shared sampling/reasoning controls
remain model preferences; validation and transport translation belong to
Providers. Adding a first-party provider requires changes in Providers, without
Core changes or new application branches. No plugin registry or dynamic entry
points exist. CLI presentation and mutation orchestration remain application-owned.
Supported approval modes are `never`, `guarded`, and `always`.
`runtime.max_tool_steps` is either `null` or a positive integer.
`runtime.stream_assistant_text` is a boolean. When enabled with a streaming
provider, the loop emits `assistant_message_started` before generation and
`assistant_delta` events for visible text chunks, then emits the normal full
`assistant_message` or `final_message` after the complete reply is assembled and
validated. These events carry the `narration` or `final` phase described in
Events And External Wrappers. Streamed deltas are UI events only; tool execution
still waits for the full validated assistant response.
`display.show_reasoning` is a boolean presentation preference. `/reasoning`
reports it, while `/reasoning show` and `/reasoning hide` persist it. This field
is intentionally separate from `model.reasoning_mode` and
`model.reasoning_token_budget`.
`runtime.model_request_max_retries` is an integer from 0 through 10 and counts
retries after the initial request. `runtime.model_request_retry_backoff_ms` is
an integer from 0 through 10,000. The loop exponentially increases that base
delay, capped at 10 seconds, and retries only classified timeouts, connection
failures, rate limits, provider 5xx responses, and clearly identified stream
transport failures. Authentication, configuration, malformed-response, and
unknown failures do not retry.
`model.temperature` is `null` or a number from 0 through 2.
`model.reasoning_mode` is `null`, `off`, `low`, `medium`, or `high`. `null`
means the provider request receives no persistent reasoning-specific setting,
preserving its existing model/provider default.
`model.reasoning_token_budget` is `null` or a non-negative integer. It is a
reasoning/thinking-only limit and must never be translated into a total response
token cap. Zero is preserved in application provider settings; each provider must explicitly
support zero before transmitting it.

Environment overrides are optional development, headless, and automation
inputs—not the normal user configuration UX. Current overrides are:

- `CODE_SQUID_BASE_URL`
- `CODE_SQUID_API_KEY`
- `CODE_SQUID_MODEL`
- `CODE_SQUID_PROVIDER`
- `CODE_SQUID_TEMPERATURE`
- `CODE_SQUID_REASONING_MODE`
- `CODE_SQUID_REASONING_TOKEN_BUDGET`
- `CODE_SQUID_DEBUG`
- `CODE_SQUID_STREAM_ASSISTANT_TEXT`

`CODE_SQUID_API_KEY` wins over the active provider's saved `api_key_env`, which
wins over its saved `api_key`; absent saved fields fall back to the profile.
OpenRouter's profile defaults `api_key_env` to `OPENROUTER_API_KEY`. A provider
environment override resolves that provider's own saved connection or profile
defaults and does not inherit another provider's URL or credential. Environment
values affect only the process's effective settings and are never copied into
the sparse persisted mapping by loading.
An absent reasoning-budget override preserves the saved value, an empty value
unsets it, and an integer string replaces it for the current process.
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

Settings readers and writers continue to expose filesystem and validation
exceptions. The console application contains expected `OSError` and settings
`ValueError` failures at the user-facing operation that owns them: interactive
runtime commands print a concise failure and retain their last known-good
settings, the startup menu renders the failure inside its prompt-toolkit panel,
and launch-time setup or standalone `safety` returns a nonzero status. Success
text is emitted only after the corresponding write returns. Other exception
types continue to escape these boundaries so implementation defects are not
mistaken for ordinary persistence failures.

Invalid settings JSON, invalid section shapes, invalid provider names, unknown
approval modes, missing configured API-key environment variables, invalid
temperatures, invalid compaction settings, and invalid step limits fail during
settings loading. Persisted provider selectors and approval modes are validated
as strings before membership checks; model names must be non-empty strings on
both load and write. Exact valid model IDs are preserved without normalization.

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

`--cwd` selects the workspace root. It defaults to the current directory
and must point at an existing directory.

Shell `resume` selects the saved session and enters the same persistent
interactive loop as a fresh invocation. Each authored follow-up loads the
saved conversation, appends a user message, marks the session active, creates
a fresh latest-only undo buffer, and continues that session. Slash commands
remain available before and between follow-ups. If model communication
ultimately raises `ModelRequestError`, the current run is marked failed and its
existing error report is shown, but the active session and interactive prompt
remain available for retry, another follow-up, `/new`, or `/exit`.

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
selection and `/model <name>` persist it verbatim; Code Squid passes that
same `ProviderSettings.model_name` explicitly to Core's spawner, which uses it
in `ModelAdapter` and then provider inference. Provider switching preserves the configured ID and reports when the
new connected provider does not expose it.

Code Squid's readiness and discovery adapters convert application `Settings`
into `ProviderSettings` and delegate to `squid_providers.catalog.provider_ready`
and `discover_models`. Provider selection uses these same adapters. Providers
owns inference readiness and discovery-only construction, so public catalogs
remain available independently of inference credentials. Code Squid contains
expected configuration/operational failures for each startup provider candidate,
including failures during credential resolution, and renders that option as
`not connected` without blocking other candidates. Unexpected programming errors
still escape the menu boundary.

OpenRouter is supported through the OpenAI-compatible provider path by setting
`model.provider` or `CODE_SQUID_PROVIDER` to `openrouter`. Squid Providers owns
its replay/content policy: assistant messages with `tool_calls` and no content
use `content: null`. Application construction obtains that policy from the
Providers catalog and passes it into Core; Code Squid does not select an
OpenRouter-specific replay policy itself.

Reasoning configuration consists of optional normalized
`ProviderSettings.reasoning_mode` and `reasoning_token_budget` values. Both
travel through built-in provider construction to the concrete request builder;
Core does not contain provider-specific translation policy. Only the explicit
`openrouter` identity currently translates them. Without a positive budget,
`off` becomes OpenRouter reasoning effort `none`, while `low`, `medium`, and
`high` retain their names. A positive explicit budget is sent as
`reasoning.max_tokens` and takes precedence over effort because OpenRouter
documents those controls as alternatives. The adapter does not send zero,
which OpenRouter does not document as a valid direct budget. The existing
per-request `please_stop_contemplating_the_void` override remains authoritative
and sends effort `none` without the configured budget. LM Studio, Squid Models,
Ollama, and generic OpenAI-compatible requests do not translate numeric budgets
or approximate them with total-generation limits; Squid Models retains only its
existing `chat_template_kwargs.enable_thinking = false` request override.

The OpenAI-compatible provider sends `parallel_tool_calls: false` whenever tools
are present. Providers may still return multiple tool calls. Code Squid retains
those calls as one ordered assistant turn and executes them sequentially through
the same per-action `ToolExecutor` path used by a one-call turn.

Completed provider output crosses the transport-independent boundary defined in
`squid_core/model_response.py`: `ToolCall(id, name, arguments)`,
`TokenUsage(input_tokens, output_tokens, total_tokens)`, and
`ModelResponse(content, reasoning, tool_calls, usage, finish_reason, response_id)`.
Both concrete providers return this same type for normal and assembled streaming
responses. OpenAI SDK objects and native Ollama JSON remain provider-owned.
Providers flatten ordered calls without parsing argument strings and choose the
first nonempty completed reasoning alias in `reasoning`, `reasoning_content`,
`thinking` order. OpenAI-compatible usage maps input/prompt and output/completion
aliases without inventing totals; Ollama maps evaluation counts and retains its
existing total calculation only when both counts exist. OpenAI-compatible ID
aliases resolve in `id`, `response_id`, `request_id`, `_request_id` order; Ollama
preserves its native ID, including the first supplied stream ID.

`ModelAdapter` consumes only these generic completed fields. Core still owns JSON
object parsing, tool-name/schema/boolean validation, whole-batch rejection, action
construction, and canonical OpenAI-style conversation replay dictionaries with
Tool-call/result pairing. Finish reason is diagnostic information, never a task
completion or execution signal. Successful responses contain no error fields;
provider failures remain exceptions with existing wrapping, cancellation,
classification, redaction, and retry behavior. Native stream terminal checks,
callbacks, chunk assembly, and raw transport tracing remain provider-owned.
Concrete transport files and SDK dependencies belong to `squid-providers`;
provider configuration validation/resolution, provider-specific defaults, and
replay/content policy belong to Squid Providers. Code Squid owns persisted
application choices, environment override policy, and provider/model selection
UX. Core has no concrete transport imports, and application construction injects
the ready provider or adapter.

The OpenAI-compatible provider also supports optional assistant text and
reasoning streaming. Streaming forwards the first populated reasoning alias
per chunk while assembling text, reasoning, and tool-call fragments into the
same Core-owned `ModelResponse` used by non-streaming responses before
`ModelAdapter` validates Tool arguments and constructs transcript-facing replies.

Image input uses a request-only Core reference rather than embedding binary
data in canonical messages. The application supplies the active adapter's
fail-closed vision-capability check to `ToolExecutor`; a supported-image
`read_file` on a non-vision model therefore returns an ordinary structured Tool
failure before validating or snapshotting image bytes. `ModelAdapter` also
asks the selected provider to prove vision support before loading an asset.
LM Studio support is derived from its
model metadata and requires an explicit `capabilities.vision` value; generic
OpenAI-compatible providers fail closed. At the final transport boundary, the
LM Studio path converts an image reference to an OpenAI data URL. Native
Ollama checks `/api/show` for the model's `vision` capability and converts the
same reference to Ollama's `images` field. Provider trace payloads redact those
materialized values, while provider failures leave the durable session asset
available for replay.

The native Ollama provider exists and is experimental. `squid_providers/ollama.py`
uses Ollama `/api/chat`, converts replayed messages into Ollama's expected
shape, omits `parallel_tool_calls`, and translates completed responses into
Core-owned `ModelResponse`. Provider-supplied Tool-call IDs
are preserved exactly. When Ollama omits an ID, adaptation assigns a
response-unique fallback prefix plus the response-local call index so distinct
historical calls cannot collide during transcript replay or result trimming.
Both normal and streaming chat opens use the provider-owned request timeout,
which defaults to 300 seconds and can be overridden with
`providers.ollama.request_timeout`. The application passes the optional effective
value through `ProviderSettings`; timeout enforcement remains inside the native
Ollama transport. Timeout exceptions follow the ordinary `ModelRequestError`
boundary and therefore retain the existing generic transient-failure policy.

Provider request failures are wrapped at the model-adapter boundary as
`ModelRequestError` with the underlying exception retained as its cause. The
adapter extracts only bounded, credential-redacted diagnostics such as HTTP
status, provider request ID, retry hint, and response-body excerpt. `AgentLoop`
retries a transient failure from the already-rendered request messages, before
any assistant message, tool action, or transcript mutation can occur. The CLI
run orchestration in `code_squid/console/cli/session_runner.py` catches that
error, marks the session failed, and writes diagnostic traceback details to
`.code-squid/logs/latest.log`.

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

Guarded command approval deliberately does not classify shell semantics. The
first whitespace-delimited token is the command identity; a simply quoted first
token is unquoted and identities are case-normalized. The one operator-specific
case is PowerShell's leading `&` call operator: a straightforward quoted or bare
literal after it is the identity, while dynamic/interpolated call expressions
have no trustable identity and therefore cannot be persistently approved. An
untrusted identity offers `Approve once`, `Always approve <command> commands`,
and `Deny`. Persistent approval stores only that identity in application-wide
`runtime.trusted_commands`; later argument changes do not prompt. Approve-once
does not change settings, and trusting one identity does not trust another.
Other shell operators, environment assignments, aliases, wrappers, and nested
shell commands receive no special interpretation.

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
- validates that the adapter returned a structurally valid, non-whitespace text
  summary before rebuilding the transcript; an absent, non-text, empty, or
  whitespace-only summary leaves every original message intact and triggers
  one retry over the same source material with an explicit non-empty-summary
  correction; a second invalid response fails compaction without mutation
- supplies the protected original system and user messages to the summarizer in
  separately labeled reference sections; they remain outside the history being
  replaced, while later user messages selected before the cutoff remain visible
  in that history
- gives an optional application provider the exact flattened recent-message
  tail that will remain verbatim; the resulting deterministic context is
  generated once, supplied to the summarizer as authoritative host/runtime
  facts for the end of the summarized history, and appended unchanged after
  the model summary; an absent, empty, invalid, or failing provider leaves the
  prior summary-only behavior unchanged
- replaces those older chunks with one assistant message headed
  `# Compacted Working Context`; the assistant role marks it as model-generated,
  while its preamble explicitly says it is lossy, context-only, non-authoritative,
  and cannot add, replace, or override real user requirements; provider text,
  when present, is appended after the model-written summary
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

The Core provider seam has no knowledge of Code Squid Tools, source files,
verification commands, task state, or filesystem truth. It communicates only
the exact preserved message tail and accepts optional text in return.
`code_squid.compaction_context.CodeSquidCompactionContextProvider` is wired only
by the Code Squid application builder. It reloads the complete append-only
canonical message history through `SessionStore.load_canonical_messages()` at
compaction time and requires
the supplied preserved tail to equal its exact suffix. A mismatch fails closed
without authoritative context; a match removes that suffix so facts describe
only the canonical prefix represented by the summary. This remains correct
across repeated compactions because storage retains the original messages rather
than the synthetic in-memory summary.

For that canonical prefix, the provider pairs Tool calls with their JSON results
and reports mechanical successful/failed call counts for `read_file`,
`apply_patch`, `write_file`, and `run_command`; the latest successful known
direct `apply_patch`/`write_file` mutation or an explicit absence; the latest
explicitly marked verification or an explicit absence; whether a later known
direct mutation makes that verification stale; and the latest concrete Tool
failure not clearly superseded by a later success. It does not infer changes
made by commands or external Tools, inspect the filesystem, maintain cumulative
or planner state, or derive facts from the model summary. Successful
verification output is omitted. Failure output is retained verbatim when short,
or as a fixed-size raw head and tail separated by an omission marker when long;
the provider does not parse or rank failure lines.

Successful PDF `read_file` results in that canonical prefix also contribute a
deduplicated list of source-page-to-rendered-PNG paths. This is runtime-generated
compaction context, not model-authored summary memory: every compaction derives
it again from persisted canonical Tool results. Only paths and page numbers are
carried forward; image bytes and base64 are never placed in compaction context.

`AgentLoop` supplies separate persistence and post-application callbacks for the
real compactor. The first persists each lifecycle event through
`SessionStore.append_compaction_event(...)` when storage is wired in and
publishes start/failure boundaries. The second dispatches the narrow
`compaction_applied` Hook seam and publishes that UI boundary only after the
proposed transcript is active. This two-callback interface is the required
compactor contract; persistence and post-commit observation are not combined in
a compatibility seam. The compactor writes a chronological diagnostic lifecycle
beside normal transcript entries:

- `compaction_check` records the estimate, configured trigger, threshold result,
  whether compaction is possible, and compactable-selection diagnostics
- `compaction_started` records the attempt number, pre-compaction message count,
  and eligible, target, selected, and preserved token/chunk selection details;
  a validation retry emits a second start event with `retry=true`
- `compaction_request` records the attempt number, estimated request size, and
  configured provider/model immediately before the model call
- optional `compaction_reasoning`, exact `compaction_summary`, and optional
  `compaction_response_meta` events preserve the successful attempt number and
  normalized response diagnostics
- `compaction_applied` records before/after token estimates and message counts,
  the successful attempt number, and a versioned replay transform containing
  the exact compacted assistant message plus protected/preserved message counts;
  the event is persisted before the proposed transcript replaces
  `session.messages`, so failed persistence leaves the pre-compaction transcript
  unchanged; post-commit Hooks and UI observe it only after replacement
- `compaction_failed` records `prepare`, `model_request`, `response_parse`,
  `session_rebuild`, `persistence`, or `post_commit` plus a concise exception
  description,
  then the original exception continues through the existing error path. The
  first invalid-summary failure instead records `attempt=1` and
  `will_retry=true`; only that validation failure is recoverable, and its second
  failure records `attempt=2` and `will_retry=false` before propagating.
  Response-parse failures occur before transcript mutation and never emit
  `compaction_applied`; provider, persistence, rebuild, callback, cancellation,
  and unexpected failures are not retried by compaction

`ModelAdapter.complete_text(...)` retains its existing `content` and `usage`
result fields and additionally exposes normalized `reasoning` and
`finish_reason` when the provider supplies them. Compaction events are not
transcript messages, but a valid versioned `compaction_applied` event is a
durable effective-transcript transformation. `SessionStore.load_messages()`
replays those transformations sequentially with ordinary messages and system
reconciliations. It validates the expected pre/post message counts and fails
closed to unchanged history for legacy, partial, or malformed replay metadata.
`SessionStore.load_canonical_messages()` remains the explicit seam for
untransformed append-only message history used by authoritative diagnostics.
The CLI observes the authoritative `compaction_started`, `compaction_applied`,
and `compaction_failed` boundaries. Start transfers the existing animated
status line to `Compacting...`, using the same position, pulse, and ownership as
Thinking and Tool activity rather than adding permanent feed output. Successful
application clears that transient line and emits the indented, dim
`🌀 Compacted context` result alongside other run results. Failure and the
existing run termination boundaries clear the transient line without adding a
new compaction failure message; checks that do not compact stay silent.

Compaction is durable transcript compression for continuation context. It does
not claim workspace truth or replace canonical history: original message and
Tool-result entries remain append-only for diagnostics, while resumes continue
from the latest successfully applied effective transcript.

## Sessions, Resume, Undo, And Interruption

Saved sessions live under:

```text
.code-squid/sessions/<session_id>/
```

Each session folder contains:

- `metadata.json`
- `session.jsonl`
- `model-view.jsonl`
- `model-transcript.txt`
- an `assets/` directory after the first successful image or PDF read

`metadata.json` stores run-level metadata: session id, timestamps, workspace root,
task, status, and active leaf id. `session.jsonl` stores append-only entries for
messages, compaction events, run-context events, and model reply diagnostics.
Message entries include `id`, `parent_id`, `type`, `timestamp`, `message`, and
optional `usage`.

Session image assets are immutable, content-addressed snapshots named by the
SHA-256 digest of their exact bytes plus a canonical extension. They are
written through a flushed same-directory temporary file and atomic replace;
identical reads deduplicate naturally. `SessionStore` accepts only fixed-format
asset IDs, verifies the digest on every load, and resolves both the assets
directory and target below the session directory so traversal and symlink
escapes fail closed. Canonical Tool results persist only the asset ID and image
metadata. Base64 transport data is created only immediately before a capable
provider request and is never written to `session.jsonl`, `model-view.jsonl`,
or `model-transcript.txt`. Resumed and compacted conversations therefore use
the original session snapshot even if the workspace file changes; a missing or
corrupt snapshot produces a clear model-request failure.

PDF page renders share that session asset root but use stable, model-readable
paths rather than provider-facing asset IDs. `SessionStore.ensure_generated_image`
contains each named PNG below `assets/<PDF stem> rendered images/`, validates it
through the same image safety code, and writes it atomically. Each generated
folder has one versioned JSON `.cache-key`: its `folder_identity` is the source
PDF digest identity, while its `images` map records each lazily rendered PNG's
render-settings key. The source identity and page number are not repeated in
those entries because the folder and PNG filename already establish them.
Per-image settings entries are required because one requested page may be
regenerated under new settings while unrequested siblings remain stale. If
distinct PDFs have the same stem, the first keeps that folder and
later documents use stable `... rendered images 2`, `... 3`, and subsequent
numbered folders. Exact identity matching makes resumed reads reuse their
existing folder without renaming or moving any occupied folder. A later ordinary
`read_file` of the named PNG snapshots its exact bytes through the existing
content-addressed image path before request-only provider injection; PDF reads
themselves never inject images.

The PDF reader supplies rendering bytes and cache identity through the existing
`SessionStore.ensure_generated_image` seam. Session storage continues to own
persistence, stable same-stem folder allocation, atomic writes, and cache
validation. Only a valid folder-level `.cache-key` with the exact source
identity proves ownership. A folder with missing, malformed, wrong-version, or
differently owned metadata is preserved as occupied, and allocation proceeds to
the next numbered folder instead.

Session transcript readers parse non-empty records in append order. If the
final non-empty line is malformed after a valid JSON prefix, readers treat it
as a torn interrupted append and expose only the complete prefix. The same
recovery applies when the physical file tail ends inside a multibyte UTF-8 code
point. Other UTF-8 decoding failures, a malformed record with any later
non-empty record, or a file containing only a malformed record remain
corruption and raise the corresponding decoding error.
Before appending continued history, `SessionStore` removes such a proven torn
tail, then derives the next entry ID from the remaining valid records. This
keeps resumed parent linkage and future reloads coherent without weakening the
middle-record corruption boundary.

`model-view.jsonl` records one object for every provider attempt. `ModelAdapter`
finalizes each request, then its shared provider-transport boundary gives a
generic observer that exact request object immediately before sending it.
The Core composition root wires that observer to `SessionStore.append_model_view()`;
the adapter knows nothing about sessions or JSONL, while `AgentLoop` and
`Compactor` need no model-view-specific paths. Records include a session-local
request index, timestamp, provider/model and reasoning metadata when available,
estimated request tokens, final messages, and final Tool schemas. This naturally
covers ordinary, streaming, retry, compaction, and other prepared-request calls.
This is a request-observability log, not canonical history; request-only Hook
context, compaction output, Tool-result trimming, and adapter message
normalization are therefore visible here. Observer failures are swallowed at
the adapter boundary and cannot fail an otherwise valid provider request.

`model-transcript.txt` is the human-readable, chronological projection of
`session.jsonl` and `model-view.jsonl`. `SessionStore` refreshes it beside the
canonical logs when model-visible requests, provider replies, accepted
messages, or compaction events arrive. The projection records the initial
system/user context once, then emits only request messages that are new or
changed, provider reasoning when exposed, assistant content and Tool calls,
Tool results in the exact request-rendered form delivered to the model,
request-only Hook/runtime context, and accepted final responses. Identical
retry requests and accumulated history are not repeated. Successful compaction
is an explicit context-transformation section containing the exact compacted
assistant message found in the next ordinary request, including the standard
preamble and any deterministic context appended by the host. The summarizer's
private request is excluded, while its available reasoning is retained.

The text file is deliberately not replay input or independent state. It is
rebuilt from the two canonical JSONL logs, and refresh failures are best effort
so this diagnostic view cannot break canonical persistence or model transport.
Routine lifecycle, no-effect Hook, token-estimator, and persistence events stay
only in the detailed log. Opening an older session remains read-only; its
readable projection is created on the next relevant append.

Immediately before an ordinary agent request, Core's centralized
tool-result-rendering seam parses canonical JSON Tool messages into a
request-only view. Canonical session messages and result dictionaries remain
complete and structured for Hooks, replay, trimming, and storage, while the
four built-ins are shown to the model as compact text. `read_file` source is
emitted as ordinary multiline text under per-region path and exact-line
headers; every disjoint or trimmed gap has an explicit omitted interval.
Repeated-read partial and skipped results use the same notation. Successful
readers whose model-ready text has no source-line coordinates emit that payload
under a generic content header. This preserves the complete first exposure
without inventing provenance, while older payloads still use the configured
character bound. PDF results use a separate page-oriented rendering that
exposes selected-page metadata, extracted text, and each durable rendered PNG
path without pretending PDF pages are text line ranges or injecting the PNGs
into the current request.
`run_command` exposes command, exit status, concise failure metadata, and an
output block; `apply_patch` keeps recovery IDs, ranges, and current candidate
text; successful `write_file` results contain only status and path. Assistant
Tool calls and their Tool messages retain the original `tool_call_id` pairing.
Unknown tools retain their canonical serialization because Core cannot infer
which caller-defined fields are safe to omit.

A successful image `read_file` result remains a normal paired Tool message
with compact metadata. Once every result from that assistant Tool-call batch
is present, request rendering appends one synthetic user message containing a
short image marker and an internal `image_asset` reference. Placing the image
after the completed sibling batch preserves provider Tool-call/result ordering.
These synthetic blocks are request-only: compaction, canonical replay, Hooks,
and storage continue to consume the structured Tool result. If an older or
resumed transcript contains such a block while the active model cannot verify
vision support, `ModelAdapter` removes only the request-only asset reference
and adds an explicit vision-unavailable notice. The canonical successful Tool
result and session asset remain unchanged, while unsupported image content
cannot reach provider transport.

Age-based Tool-result retention follows assistant batch boundaries as well as
the configured result count. Results from the just-completed assistant Tool
batch receive one normal bounded exposure before historical trimming applies,
even when the batch itself is larger than `recent_full_results`. Core derives
that first-exposure batch from the latest assistant `tool_calls` message and
its complete set of paired Tool messages; transient request context may follow
the results without changing the boundary. Once a later assistant message is
in canonical history, those results age by the ordinary count-based policy.
The guarantee does not expand Tool-level output bounds, duplicate result
payloads, or mutate canonical history. Read trim notifications therefore fire
only when source is actually reduced in a later model request, allowing host
Hooks to track request-visible source.

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

`assistant.reasoning` contains the single provider-normalized reasoning value
when supplied. Finish reason, usage, and response ID are likewise optional.
The historical `raw_tool_calls` diagnostic key now contains only flat `id`,
`name`, and raw JSON `arguments` fields, recorded before Core parsing. Arbitrary
native Tool-call fields, SDK serialization, and multiple reasoning aliases are
intentionally dropped. Deep native chunks remain in provider-side trace output;
normal Core replies do not carry native responses or metadata bags.

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
this path. `SessionStore.load_messages()` replays `type: "message"` entries,
applies `system_message_reconciliation` entries, and applies only validated
versioned `compaction_applied` transformations. Model-reply and rejection
diagnostics never enter canonical history or reach the model. The separate
`load_canonical_messages()` view retains original messages across compactions.

Current session statuses are:

- `active`
- `complete`
- `failed`
- `abandoned`
- `interrupted`

Resume selects an active saved session inside the persistent CLI loop. A later
authored task loads messages with `SessionStore.load_messages()`, appends a
follow-up user message, marks the session active, creates a fresh undo buffer,
and continues the same saved session from its latest durable compaction
boundary instead of re-expanding discarded model context. `latest` resolves
through the explicit workspace sessions path supplied by
`code_squid.app_paths`. Loading also repairs
a genuinely trailing assistant Tool call left by an older interrupted runtime
by durably appending a synthetic interrupted Tool result; it does not attempt
to reinterpret malformed pairs in the middle of history.

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
snapshots and deletes files that did not exist before the write. Restore is a
one-shot transition from `active` through `restoring` to `restored`; only an
`active` buffer is eligible. The intermediate state is written after complete
validation but before target mutation, so a failed or interrupted partial
restore cannot be replayed over later user work.

Undo metadata records the resolved workspace root that created the buffer.
Restore requires that root to exactly match the currently opened workspace and
prevalidates every normalized target as contained by that workspace before any
target is mutated. Moving or copying a workspace therefore makes its stale undo
buffer unavailable rather than following its absolute paths back to the old
workspace. Snapshot paths are likewise required to remain under the buffer's
`files` directory. There is intentionally no automatic undo-record migration.

Code Squid owns run assembly and session lifecycle coordination. The application
builder constructs the selected provider before durable session creation, so
missing credentials do not create an active session. Later assembly failures
(including runtime construction, undo setup, and run-context persistence) mark
an available session `failed` and re-raise the original exception. This applies
to supplied/resumed stores too; session history is retained for discovery and
resumption. Core storage and runtime contracts remain strict and unchanged.

The CLI routes new-run construction, follow-up preparation, and exceptions from
`loop.run()` through the same application failure reporter. New runs capture
the durable store through the existing storage-factory seam; failures before
creation report no session path/ID. Unexpected failures return status 1.
Handled model request failures return 0 to keep the interactive prompt alive.

Status updates and diagnostic writes are best effort only while handling an
existing failure: secondary persistence errors cannot replace its cause or
prevent user-facing reporting. When writable, the traceback log remains at
`.code-squid/logs/latest.log`, with existing relative-path presentation and
specialized model-failure output. The log stores traceback details, not prompts,
payloads, tool outputs, file contents, headers, or API keys. If a diagnostic write
fails, the normal run-failure surface renders the original error without a
saved-log claim. Its log/session paths are optional, and generic errors show
their message even when no log exists. The display retains its concise permission
error explanation and note that prior repository changes were not rolled back.
If storage is unavailable, a failed status update cannot guarantee corrected
durable metadata; the original failure still reaches the user. No storage
helper silently suppresses errors.

`KeyboardInterrupt` retains its separate interrupted-session behavior: Ctrl+C
marks the current session `interrupted` and prints the normal final session
display. Construction cancellation and failure-display errors are not swallowed.

There is no permanent undo history, branching UI, tree navigation, or advanced
session workflow in the current MVP.

## Tool Model

The protected built-in Tool surface is:

- `read_file(path, ranges=None, pages=None, sheet=None, rows=None)`
- `write_file(path, content)`
- `apply_patch(path, old_text, new_text)` or candidate selection with `match_id`
- `run_command(command, verification)`

The model-facing `squid_core/tools/builtins/read_file.py` adapter owns the
schema, argument validation, path requirements, unsupported-media errors, and
the public Tool entry point. It dispatches one-way into the reusable
`squid_core/file_readers` package. That package has a deliberately static
suffix registry: `.xlsx` and `.ods` select their spreadsheet readers, `.pdf`
selects the PDF reader, `.docx` and `.epub` select their document readers,
`.png`/`.jpg`/`.jpeg`/`.webp` select the image reader, and every other suffix
retains the UTF-8 text-reader fallback. `text.py`, `docx.py`, `epub.py`,
`xlsx.py`, `ods.py`, `image.py`, and `pdf.py` own their format-specific read
behavior;
none depends on the Tool adapter. The adapter packages each validated request
and its optional session-storage callbacks into one immutable
`FileReadContext`. Every registered reader accepts that same context, so the
registry only selects a callable by suffix and invokes it; it has no
format-specific dispatch branches, discovery, plugin lifecycle, or reader
class hierarchy.

The `apply_patch` JSON schema declares all four arguments in the top-level
object `properties`; its `anyOf` branches carry only the two alternative
required-field sets. This permits candidate-selection retries to repeat normal
fields while remaining acceptable to OpenAI-compatible providers that require
root-level properties.

`read_file`:

- requires an absolute path
- reads UTF-8 text for ordinary files
- reads `.docx` through python-docx, normalizes body paragraphs, common Heading
  styles, common bullet/numbered lists, hyperlinks, and tables into a small
  internal block representation, then renders deterministic Markdown-like text
  in document order; python-docx objects do not cross the reader boundary
- applies ordinary text line targeting and the 1,000-line full-read ceiling to
  that rendered DOCX text, so returned range coordinates describe Code Squid's
  representation rather than Word pages or visual lines; DOCX rejects the
  PDF-only and spreadsheet-only selectors at the public Tool boundary
- treats DOCX as read-only semantic content: it does not reconstruct comments,
  tracked changes, drawings or text boxes, embedded images, typography, page
  layout, or page-number selection
- reads `.epub` through epub-utils, using the package spine rather than ZIP
  member or filename order; only primary (`linear="yes"`) XHTML/HTML resources
  are treated as prose, and EPUB 3 navigation resources are excluded even if
  a producer places them in the spine
- keeps epub-utils objects inside `epub.py`, normalizes selected metadata and
  each spine resource into EPUB-specific immutable book/section/block values,
  and renders explicit section boundaries plus Markdown-like headings,
  paragraphs, nested lists, blockquotes, fenced preformatted content, links,
  tables, and image alt/reference text
- applies ordinary text line targeting and the 1,000-line full-read ceiling to
  rendered EPUB text; EPUB does not expose chapter selectors and rejects the
  PDF-only and spreadsheet-only selectors at the public Tool boundary
- treats EPUB content as local, passive, and read-only: it does not render CSS,
  execute scripts, fetch links or remote resources, send embedded images to
  vision, bypass encrypted/DRM content, reproduce page layout, or write books;
  navigation/TOC data determines structural exclusion but is not separately
  emitted, avoiding duplicate chapter labels
- reads `.xlsx` through openpyxl and `.ods` through odfpy, returning a
  provider-neutral spreadsheet result with workbook format, ordered sheet
  names, used ranges, and TSV-like text for each sheet
- loads XLSX twice in read-only mode, once for formula source and once for
  stored cached values, then pairs corresponding cells; a cached result is
  shown before its formula when present, and Core never recalculates either
  XLSX or ODS formulas
- accepts an exact spreadsheet-only `sheet` name and an optional 1-based,
  inclusive `rows={start_row, end_row}` selection; selected output reports the
  sheet's full used range and the returned intersection, while an unknown sheet
  remains an ordinary structured Tool error
- keeps spreadsheet source rows distinct from text source lines: spreadsheets
  reject `ranges`, while whole-workbook and targeted rendering both retain the
  normal 1,000-line head/tail ceiling and direct oversized selections toward a
  narrower row interval; the readers ignore charts and other drawing content
  and do not expose images, macros, pivots, or editing
- validates DOCX, EPUB, XLSX, and ODS containers through one narrow
  `file_readers/container.py` helper that limits each source to 64 MiB and its
  declared ZIP-expanded members to 256 MiB before format parsing; the same
  boundary allows at most 100,000 ZIP members as a deliberately generous
  pathological-container guard; callers own their format-specific public error
  wording, and spreadsheet-only cell limits remain in the spreadsheet layer
- limits each normalized spreadsheet sheet area to one million cells so
  declared dimensions and ODF repetitions cannot trigger unbounded expansion
- detects `.pdf` before text decoding and uses PyMuPDF for both text extraction
  and page rendering
- accepts a PDF-only `pages` list containing one to eight inclusive
  `start_page`/`end_page` ranges, merges overlaps, and permits at most 20
  selected pages per call; omission selects the whole document only through
  that same 20-page ceiling
- returns extracted text with an explicit marker for every selected page and
  reports every rendered PNG's absolute path; pages without extractable text
  retain a clear placeholder and remain inspectable through their PNG
- renders only selected pages at up to 2x scale, reducing scale when needed to
  stay within 40 million pixels, and limits source PDFs to 64 MiB
- stores pages below the active session as
  `assets/<PDF stem> rendered images/page-<number>.png`; deterministic cache
  keys reuse valid persisted pages across later reads and resumed runs
- recognizes PNG, JPG/JPEG, and WebP by extension, validates the actual Pillow
  format and dimensions, and snapshots the exact source bytes into the active
  session before returning success
- limits image inputs to 32 MiB and 40 million pixels, rejects corrupt images,
  extension/content mismatches, and `ranges` on images, and returns only a
  versioned descriptor with asset ID, SHA-256, MIME type, format, dimensions,
  and byte size
- requires session-backed snapshot storage for an image read; snapshot failure
  fails the Tool result without exposing inline binary data
- describes ranged reads as the default for known relevant source and reserves
  range omission for decisions that genuinely need file-wide context
- uses an optional `ranges` list for every targeted read; it accepts one to
  eight regions of the same file, and every item requires inclusive
  `start_line` and `end_line` values
- keeps read sizing in Core's small `ReadFileSettings`, whose defaults cap
  whole-file reads at 1,000 lines and target at least 150 lines for ranged reads
- returns whole-file reads unchanged through 1,000 lines
- for larger whole-file reads, returns 500 head lines and 500 tail lines with
  explicit `returned_line_ranges` and model-facing `truncation_guidance`
- rejects targeted reads whose normalized merged coverage exceeds the normal
  total line budget rather than truncating them
- expands a ranged read below 150 returned lines around the requested area,
  shifting the window at file edges to retain up to 150 lines when available;
  ranges already at least 150 lines and requests starting past EOF are unchanged
- normalizes and expands each requested region with those same semantics,
  then sorts and merges overlapping or adjacent effective regions before
  enforcing the 1,000-line total source-coverage budget; over-budget explicit
  multi-range requests fail instead of being partially returned
- renders multi-range content in source order with an explicit omitted-line
  marker between every disjoint pair, while still reporting each effective
  region through `returned_line_ranges`; request-only result trimming preserves
  those separators and per-region provenance
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
- returns affected before/after line ranges, the existing compact
  character-count metadata, and exact replacement previews after success;
  previews preserve short text and symmetrically truncate long text to 300
  characters without adding surrounding file context. Request-only history
  trimming drops only those previews once a successful result becomes old
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

- requires an explicit boolean `verification` intent and returns that intent
  with every process result; missing or non-boolean intent is rejected through
  normal Tool schema validation before command execution, without coercion
- does not infer verification from command text, languages, or test frameworks
- on Windows, invokes the detected PowerShell executable with `-NoProfile` and
  `-Command`, without `shell=True`
- on other platforms, executes through the system shell with `shell=True`
- uses `workspace_root` as the working directory
- merges stderr into stdout
- decodes the merged process stream as UTF-8 with replacement for malformed
  bytes, independent of the host platform's locale
- polls an owned process while checking cooperative cancellation and times out
  after 60 seconds
- returns distinct normalized `cancelled` and `timed_out` flags; either boundary
  terminates the complete owned process tree before returning; Windows assigns
  the launched shell to a kill-on-close Job Object and supplements Job
  termination with a short bounded `taskkill /T` sweep, while POSIX uses a
  dedicated process group and escalates from `SIGTERM` to `SIGKILL` based on
  surviving group membership rather than only the original shell process
- treats `KeyboardInterrupt` as an ownership boundary: the same tree cleanup
  runs before the interrupt propagates to the Agent loop and CLI
- bounds every cancellation/timeout termination, direct-process wait, and pipe
  drain; if a missed or detached descendant retains an inherited pipe beyond
  that deadline, Core closes its parent-side pipe handles instead of waiting
  indefinitely for EOF
- disarms the Job's kill-on-close limit after ordinary command completion so
  cleanup hardening does not change the established behavior of an explicitly
  detached process on a successful command
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
standalone user Tools from `<app-home>/tools/`. A selected Mod uses only its
selected packaged Skill's ordered `allowed-tools`, drawing custom Tools from
the Mod first and then from standalone user Tools. Built-ins
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
defaults, baseline coding discipline, narration style, coding examples, source
reading/editing preferences, and final report style. Application wiring imports
`squid_core.agent.Agent` directly; there is no application Agent alias or empty
specialization module.

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
  guarded command trust are approval mechanisms.
- Compaction uses rough JSON/text length estimates, not exact tokenization.
- Core records model request failures, unexpected run failures, requested
  cancellation, and boundary-level interruptions before preserving the existing
  exception or cancellation control flow for its host.
- The interactive CLI owns one cancellation controller per active run. Its
  SIGINT handler sets thread-safe state passed through application construction
  to `AgentLoop`; embedded callers retain the KeyboardInterrupt boundary where
  Python signal handlers are unavailable.
- Streaming providers accept a response only after a provider-native terminal
  signal: native Ollama requires `done: true`, while OpenAI-compatible chat
  completions require a non-null choice `finish_reason`. EOF without that
  evidence is a provider failure, so partial text or Tool calls never become an
  accepted assistant response. Providers check cancellation between arriving
  chunks and once more before classifying incomplete EOF, then explicitly close
  the active response iterator on completion, cancellation, or error. Built-in
  providers additionally monitor cancellation during response-header and body
  waits and close their per-request client/response to wake blocked I/O. The
  monitor polls every 20 ms and its shutdown join is bounded at 200 ms. Retry
  backoff uses the same cancellation predicate in short bounded waits.
- AgentLoop uses a provider stream internally whenever the provider supports it,
  even when live assistant presentation is disabled. Hidden deltas are accumulated
  into the same normalized completed reply without UI events. Text-only compaction
  uses the same path when a cancellation callback is present, so reasoning
  visibility and presentation settings do not weaken transport cancellation.
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


### Provider transport contracts for v0.1

Providers requires current `ProviderSettings` and normally initialized provider
instances. LM Studio native metadata uses configured bearer credentials, and
readiness requires a loaded LLM. Ollama appends complete streamed calls in
arrival order, validates native response/message envelopes, and retains HTTP
status information for Core's existing request-error classification. Positive
finite timeout validation applies to direct transport construction as well as
scoped settings. Missing OpenAI-compatible tool-call IDs are generated with a
response-specific prefix; native IDs remain unchanged. Tool argument validation
and execution remain Core-owned. Streamed usage is best-effort: supplied counts
are retained, missing counts remain unknown, and no universal `stream_options`
or usage compatibility retries are added. Ollama `/v1` normalization,
cancellation identity/design, and conservative vision behavior remain unchanged.

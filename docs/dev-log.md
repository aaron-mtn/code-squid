- 2026-09-03: Added the reusable Code Squid binary-rain header component under
  console UI without replacing the existing startup presentation. The new
  9-row renderer keeps a fixed centered title over sparse, independently paced
  binary drops; separates semantic composition from ANSI styling; uses injected
  randomness for deterministic tests; and provides a bounded synchronous
  lifecycle with terminal-size rechecks, static fallbacks, safe Windows ANSI
  enablement, and guaranteed cursor restoration. Focused console suite: 133
  passed. Full suite: 767 passed. Production packages compiled successfully,
  the new public module imported, the generated file tree remained current,
  and `git diff --check` passed. A PTY smoke confirmed the sparse motion, fixed
  title, varied column pacing, cursor restoration, and intact output below the
  header. No model inference was run. Startup integration remains intentionally
  deferred to Patch 1B.
- 2026-09-03: Cleaned the CLI command surface around current product naming and
  shell behavior. Shell `safety` replaces `mode`, singular `skill` replaces
  `skills`, and `help`, `--help`, and `-h` now print complete shell usage.
  Unknown commands, malformed command usage, missing sessions, and unusable
  undo buffers return nonzero. Interactive exit handling now reserves only
  `/exit`; bare `exit` and `quit` remain task text. Prompt help now separates
  core interaction, Mod-first specialization, runtime settings, and
  session/workspace controls. README command, safety, specialization, and
  built-in Tool facts were brought current. Focused CLI/settings/session suite:
  142 passed. Full suite: 753 passed. `main.py`, `code_squid`, and `squid_core`
  compiled successfully; affected CLI imports loaded; and `git diff --check`
  passed. No live model inference or network calls were run, and no follow-up
  work is intentionally deferred.
- 2026-09-03: Added the missing interactive CLI command surface for runtime
  settings and session control. `/provider`, `/model`, and `/safety` now report
  and persist workspace settings without losing unrelated fields; provider and
  model output distinguishes saved values from active environment overrides,
  and the persistent loop reloads effective settings before later runs.
  `/sessions`, `/show`, `/resume`, `/undo`, and `/cwd` reuse the existing
  session rendering and undo behavior while keeping the workspace immutable.
  Shell `resume` now selects the requested saved session and enters the same
  multi-turn interpreter used by fresh sessions, preserving ordinary slash
  commands, active-session tracking, specialization switching, and replayed
  conversation history. Focused CLI/settings/session/undo suite: 166 passed.
  Full suite: 746 passed. Production packages compiled, affected CLI/settings
  imports loaded successfully, and `git diff --check` passed. No live model
  inference or network calls were run, and no follow-up work is intentionally
  deferred.
- 2026-09-03: Fixed specialization semantics across runs in one session.
  `AgentLoop` now keeps new-session seeding simple while reconciling an existing
  transcript to the newly constructed Agent's single intended system message,
  preserving all non-system conversation history and never repeating the
  original task. `SessionStore` persists that replacement as an append-only
  `system_message_reconciliation` event and applies it on reload. CLI
  follow-ups now reuse `build_coding_task_run(...)`, keeping Mod Skill, Tool,
  Hook, Agent, run-context, and loop construction coherent without widening
  omitted Skill policy. Added `/mod`, `/mod <name>`, and `/mod none`; Mod and
  standalone Skill selection now clear one another, and `/skill default` was
  removed. Focused AgentLoop/session/Mod/Skill/Hook/CLI/boundary suite: 184
  passed. Full suite: 731 passed. Production packages compiled, affected public
  imports loaded successfully, and `git diff --check` passed. No live model
  inference was run and no follow-up work is intentionally deferred.
- 2026-09-03: Refactored the flat `squid_core/agent_loop.py` into the small
  `squid_core/agent_loop/` package without changing its public imports or
  runtime behavior. `loop.py` retains the complete state machine, including all
  validation, hook, preflight, approval, execution, finalization, failure, and
  cancellation decision points. `event_emitter.py` now owns only compact event
  payload construction and forwarding, while `transcript_recording.py` owns
  only accepted-message recording, runtime message construction, and the
  mechanical pending Tool-result repair used at interruption boundaries.
  Existing callers still import `AgentLoop` and `RunResult` from
  `squid_core.agent_loop`; no compatibility layer was added. Focused Agent-loop,
  event, transcript/session, cancellation, Hook, workspace-boundary, Core Agent,
  and Core-boundary suite: 148 passed. Full suite: 717 passed. Affected
  production modules compiled and imported successfully; the public-import
  smoke test, stale-path search, old-file absence check, and `git diff --check`
  passed. No live model inference was run. No behavior differences or deferred
  follow-ups are known.
- 2026-09-03: Made `code_squid.agent_setup` presentation-neutral by removing
  its console UI imports, startup-info helper, terminal display construction,
  and CLI approval-mode labels. The existing console session runner now owns
  complete `TerminalDisplay` construction, including startup provider/model,
  friendly approval-mode and Skill labels, plus `CODE_SQUID_TRACE` and debug
  behavior; CLI callers continue passing that display explicitly. Programmatic
  callers that omit a display now use Squid Core's existing `NullDisplay`,
  while a supplied display remains the default approval prompter. Added focused
  tests for null/supplied display semantics and a clean-interpreter boundary
  test that blocks console and `prompt_toolkit` imports. Focused setup/CLI/UI
  suite: 180 passed. Full suite: 717 passed. Affected production modules
  compiled and imported successfully; the isolated application-setup import,
  stale-name searches, and `git diff --check` passed. No live model inference
  was run. No behavior differences or deferred follow-ups are known.
- 2026-09-03: Split the console's monolithic terminal display into coherent
  presentation owners without changing the `TerminalDisplay` lifecycle API or
  visible behavior. `banner.py` now owns startup data/rendering, `approval.py`
  owns approval panels/prompts/results, `tool_display.py` owns Tool and command
  labels plus debug result projection, and `formatting.py` owns shared styles,
  links, path shortening, wrapping, and final-summary Markdown. `display.py`
  remains the Agent-loop coordinator and continues exposing established public
  imports. Updated terminal-width test patch points to the new formatting
  owner. Focused console/UI suite: 165 passed. Full suite: 714 passed. Affected
  modules compiled and imported successfully; `git diff --check` and stale-name
  searches passed. No live model inference was run. No behavior differences or
  deferred follow-ups are known.
- 2026-09-02: Completed a documentation-only truth pass on
  `docs/ARCHITECTURE.md`. Corrected the Tool Model to distinguish the four
  protected built-ins from Skill-filtered, standalone user, Mod, and
  host-supplied Tool registries; documented the Windows PowerShell execution
  path and generic spawner's empty-registry default. Aligned Hook loading and
  cancellation-event descriptions, described the live Skill Tool-guidance
  override behavior, replaced the `CodingAgent` specialization claim with its
  actual alias relationship, and removed stale Desktop migration, Extension,
  plugin, packaging, and speculative future-architecture wording. No
  production code changed and no production mismatch required a code change.
  Focused Agent/Skill/Tool/Mod/Hook/event/spawner/platform suite: 204 passed.
  `git diff --check` passed. The full suite and live model inference were not
  run because this patch changes documentation only. No follow-up work was
  intentionally deferred.
- 2026-09-02: Completed a focused dead-weight cleanup of bundled Skills,
  prompt compatibility, and application setup. Removed the repo-root
  `skills/` tree and its `architecture-review` example after confirming that
  standalone user Skills under the supplied application home and Mod-local
  Skills are the live resource paths. Simplified Skill discovery accordingly.
  Removed the non-live task/follow-up prompt templates, render helpers, and
  Skill override sections while preserving the canonical system message plus
  raw authored user task/follow-up transcript. The CLI follow-up path now calls
  `squid_core.spawner.build_agent_loop(...)` directly, and the redundant Code
  Squid compatibility wrapper is gone. Retained live system-prompt assembly,
  user Skill discovery, Mod Skill resolution, and system/tool/final-summary
  Skill overrides. Focused Skill/prompt/setup/CLI/spawner/storage/UI/boundary
  suite: 267 passed. Full suite: 714 passed. Production compileall and a fresh
  54-module import walk passed; generated `docs/filetree.md`, stale current
  references are absent, and both diff checks passed. No live model inference
  was run.
- 2026-09-02: Moved the remaining compaction-support modules into
  `squid_core/compaction/`: context usage/trigger reporting now lives in
  `compaction_status.py`, and the existing rough transcript token helpers live
  in `token_estimate.py`. Updated production and test imports directly and
  removed the old flat module paths without compatibility shims. The
  `ContextStatus` name, status data shape, compaction semantics, and rough
  `len(text) // 4` heuristic are unchanged. Focused compaction/status/token/
  boundary suite: 37 passed. Full suite: 725 passed (the 724-test baseline plus
  one old-module-absence boundary test). Production compileall and a fresh
  67-module import walk passed; stale old imports and flat module files are
  absent. Both diff checks passed. No live model inference was run.
- 2026-09-02: Completed the final Code Squid application package cleanup by
  moving the product-owned Agent/prompt policy, settings, application paths,
  run setup, CLI workflow, and terminal UI into `code_squid/`. Renamed the CLI
  and UI modules by their existing responsibilities, retained `CodingAgent` as
  the intentional future specialization point, kept `main.py` as the thin
  executable entry point, and removed the old root `agent/`, `cli/`, `config/`,
  `core/`, and `ui/` packages without compatibility shims. Runtime behavior and
  public function names are unchanged; `squid_core/` remains reusable and has
  no import dependency on `code_squid/`. Updated architecture, generated file
  tree, production/test imports, monkeypatch targets, and package-boundary
  coverage. Focused application settings/paths/setup/CLI/session/Skill/UI suite:
  271 passed. Full suite: 724 passed (the 723-test baseline plus one new final
  layout boundary test). Production compileall and a fresh 69-module import
  walk passed; stale root-package imports are absent, all five old package
  directories are gone, the Core dependency check passed, and both diff checks
  passed. No live model inference was run. Finalize behavior, CodingAgent
  specialization, display decomposition, resource packaging, providers, and
  dynamic loader branding remain intentionally deferred.
- 2026-09-02: Removed the remaining top-level `storage/` package by moving
  traceback-only diagnostic logging and generic cross-location session
  registration/discovery into `squid_core/storage/`. The Core APIs now receive
  explicit log, registry, and sessions-directory paths; `core/app_paths.py`
  remains the sole owner of Code Squid's `.code-squid` layout and
  `CODE_SQUID_SESSION_INDEXES` override. Cross-workspace newest-first listing,
  stale-root tolerance, malformed-line skipping, duplicate suppression, and
  CLI latest/show/resume behavior are unchanged. No compatibility shims were
  added. Focused storage/session-index/error-log/CLI session suite: 119 passed.
  Full suite: 723 passed. Production compileall and a fresh 67-module import
  walk passed; stale top-level storage imports and forbidden Core path,
  environment, app-path, CLI, and UI dependencies are absent. Both diff checks
  passed. No live model inference was run. Broader application-shell and CLI/UI
  ownership cleanup remains intentionally deferred.
- 2026-09-02: Completed Squid Core refactor Patch 6B by moving atomic JSON
  writes, per-session persistence, latest-only undo mechanics, and generic
  session-directory inspection into `squid_core/storage/` with no compatibility
  shims. `SessionStore.create(...)` and `UndoStore.create/open(...)` now accept
  explicit storage directories; optional workspace metadata is supplied
  explicitly. Session creation no longer writes Code Squid's global registry.
  Code Squid's `core.app_paths` and application runner now own
  `<repo>/.code-squid/sessions`, `<repo>/.code-squid/undo`, and explicit
  best-effort registration, while top-level `storage/session_index.py` retains
  `CODE_SQUID_SESSION_INDEXES` and cross-workspace policy. Existing session
  metadata/JSONL semantics, IDs, diagnostics, replay, statuses, CLI discovery,
  resume/show/latest behavior, and latest-only undo behavior were preserved.
  Focused storage/session/undo/spawner/runner/CLI/boundary suite: 219 passed.
  Full suite: 721 passed. Production compileall and a fresh 69-module import
  walk passed; stale top-level generic storage imports and forbidden Core path,
  environment, app-path, CLI, and UI dependencies are absent. Both diff checks
  passed. No live model inference was run. Provider/config ownership, Skills/
  Mods packaging, CLI architecture, and final application-package relocation
  remain intentionally deferred.
- 2026-09-02: Moved the provider contract, OpenAI-compatible transport, native
  Ollama transport, and their small settings-only construction helper into
  `squid_core/providers/`; removed the old top-level provider source package
  without compatibility shims. Added `squid_core/settings.py` for effective
  provider, runtime, approval, streaming, tool-step, and compaction semantics.
  Code Squid's `config/settings.py` continues to own
  `.code-squid/settings.json`, product defaults, saved provider/model selection,
  persistence, and optional `CODE_SQUID_*` overrides, and now explicitly
  translates those application settings before `core.runner` calls the generic
  spawner. Generic generation now requires explicit Core settings or a supplied
  `ModelAdapter`; supplied adapters and providers retain their construction
  bypasses. Removed terminal debug output and the implicit `lm-studio` API-key
  fallback from reusable OpenAI-compatible transport. Focused
  provider/settings/spawner/generation/application-runner/boundary suite: 194
  passed. Full suite: 711 passed. Production compileall and a fresh 67-module
  import walk passed; stale old-provider imports and forbidden Core imports are
  absent, and both diff checks passed. No live inference was run. Deferred: LM
  Studio native `/api/v1/*`, explicit LM Studio model
  load/unload/download support, future Squid Models provider/runtime integration,
  and storage ownership cleanup.
- 2026-09-01: Completed Patch 5C by renaming `squid_core/runner.py` to
  `squid_core/spawner.py`, reflecting that the module spawns and constructs a
  fully wired generic runtime. The `AgentRun`, `AgentLoop`, `build_agent_run`,
  `build_agent_loop`, and `run_agent_task` API names are unchanged, and no
  compatibility shim was added. Cleaned stale Code Squid ownership wording in
  reusable Mod and Skill descriptions and a ModelAdapter boundary comment.
  Runtime behavior and construction semantics are unchanged. Focused
  spawner/runner/boundary suite: 55 passed. Full suite: 703 passed (the 702-test
  baseline plus one old-module-absence boundary test). Production compilation
  and a fresh 69-module import walk passed. Lightweight test-adapter smoke
  covered Code Squid application construction, generic spawner construction,
  and direct `AgentLoop` construction. Stale current imports are absent and
  both diff checks passed. No live model inference was run.
- 2026-09-01: Completed Squid Core refactor Patch 5B by organizing the existing
  reusable runtime into the six intentionally capped subsystem packages:
  `agent/`, `compaction/`, `mods/`, `tools/`, `hooks/`, and `safety/`. Moved Mod
  metadata/resolution, Tool execution/results/user metadata/built-ins, Hook
  lifecycle/loading, and preflight/approval/workspace boundaries under their
  canonical packages; removed the old repository-root Tool source package and
  updated production and tests directly with no compatibility wrappers. No
  runtime behavior changes were intended. Focused subsystem/boundary suite: 240
  passed. Full suite: 702 passed. Compileall and a fresh 69-module production
  import walk passed; stale old subsystem imports are absent and both diff
  checks passed. Manual verification covered normal Code Squid construction,
  architecture-review Skill resolution, Session/default Tool registry creation,
  canonical `chat-agent` Mod discovery/resolution, selected-Mod construction,
  generic construction, and a real local Ollama `gemma3:4b` no-tool run returning
  `PATCH5B_OLLAMA_OK`. Remaining flat-file ownership, including
  `context_status.py`, stays deferred to the remaining ownership audit.
- 2026-09-01: Completed Squid Core refactor Patch 5A by physically moving the
  reusable runtime modules from `core/` into `squid_core/` and updating current
  production, test, CLI, tool, provider, and documentation imports to their
  canonical locations. `Compactor` now lives inside the existing compaction
  package and is exposed from `squid_core.compaction`. Resource loaders accept
  explicit application homes/roots and no longer import Code Squid's home
  policy. Only application-owned `core/app_paths.py` and `core/runner.py` remain
  for the later application-package cleanup. Deleted the obsolete Squid Bell
  installer and its two tests. Patch 4 Mod discovery, precedence, protected
  tools, ordered Tool equality, lazy Tool loading, and selected-Hook loading are
  unchanged. Focused runtime/boundary suite: 243 passed. Full suite: 698 passed
  (697 baseline - 2 deleted Squid Bell tests + 3 boundary tests). Compileall and
  63-module import checks passed; stale reusable `core.*` imports and current
  Squid Bell references are absent; both diff checks passed. Manual verification
  covered normal and selected-Mod Code Squid construction, architecture-review
  Skill resolution, Session/default Tool registry creation, canonical Mod
  discovery/resolution, and a real no-tool Ollama `gemma3:4b` run returning
  `PATCH5A_OLLAMA_OK`.
- 2026-09-01: Completed Squid Core refactor Patch 4 by deleting the legacy
  Extension runtime, storage/state helpers, CLI commands, and Extension-specific
  tests rather than wrapping them. Added the canonical Core Mod system at
  `<app-home>/mods/<mod-name>/mod.yaml`, using Desktop's current one-Skill
  metadata fields and ordered `mod.yaml tools`/Skill `allowed-tools` contract.
  The host supplies the application home and selects the Mod; Core discovers,
  parses, validates, and resolves it into `ResolvedMod` metadata, Skill, lazy
  executable Tools, and loaded selected Hooks. Standalone `skills/`, `tools/`,
  and `hooks/` remain supported. Mod-local resources win over same-named loose
  user resources; protected built-in Tools win loose collisions and reject
  Mod-local replacement packages. Metadata discovery/validation imports
  neither Tool nor Hook source. `core.runner` now accepts `mod_name` plus
  `app_home` and supplies resolved components to the unchanged Mod-agnostic
  `squid_core.runner`. Before changes, local CLI startup and a fake-adapter
  architecture-review run constructed a session and completed. After changes,
  canonical Mod discovery/resolution and a fake-adapter selected-Mod run did
  the same; a real localhost Ollama `gemma3:270m` attempt failed to produce an
  accepted final, while the installed `gemma3:4b` completed the no-tool Mod
  smoke with `PATCH4_SMOKE_OK`. Focused Mod/Skill/Tool/Hook/runner suite: 117
  passed. Full suite: 697 passed. Compile/import checks and `git diff --check`
  passed. Desktop parser/call-site migration and the physical `core/` to
  `squid_core/` package migration remain deferred.
- 2026-09-01: Simplified the Patch 3 generic construction API before treating
  it as permanent. Removed factory arguments for provider, ModelAdapter,
  Compactor, ToolExecutor, ToolResults, ApprovalPolicy, ActionPreflight,
  HookRunner, and AgentLoop construction. Callers now either pass replacement
  collaborator objects or construct `AgentLoop` directly. Session and undo
  store factories remain because Core must create the session store first and
  pass its session ID into delayed undo-store construction. UI neutrality,
  direct/pre-created stores, provider/adapter bypass behavior, and the normal
  Code Squid application path are unchanged. Focused runner suite: 42 passed.
  Full suite: 751 passed. `git diff --check` passed.
- 2026-09-01: Completed Squid Core refactor Patch 3 by separating the
  batteries-included Code Squid application builder in `core/runner.py` from
  UI-neutral generic construction in `squid_core/runner.py`. The generic seam
  defaults to `squid_core.agent.Agent` and can selectively accept an Agent,
  provider, ModelAdapter, Compactor, ToolExecutor, ToolResults, ApprovalPolicy,
  ActionPreflight, HookRunner, display, approval prompter, Session,
  SessionStore, UndoStore, or storage factories. Supplied adapters bypass
  provider construction, supplied executors bypass default executor/undo
  construction, and store factories retain session-first/session-id ordering.
  TerminalDisplay construction, Code Squid prompt defaults, Skill/tool
  resolution, active-extension hooks, and run-context policy remain in the
  application layer. Existing Code Squid helpers, prompt/runtime behavior,
  provider selection, approvals, compaction, transcripts, hooks, storage, and
  direct `AgentLoop(...)` construction are intentionally preserved. Focused
  verification: 124 passed. Full suite: 751 passed. `git diff --check` passed.
  Patch 4 still owns broader physical package migration,
  Extension/Mod naming work, and Desktop import/packaging migration.
- 2026-09-01: Completed Squid Core refactor Patch 2 after the Patch 1
  Agent/prompt split. `AgentLoop` now delegates workspace-boundary and guarded
  `run_command` decisions to a small action-preflight collaborator, while its
  orchestration order remains hook, preflight, approval, execution, and result.
  The generic compaction prompt moved to `squid_core/compaction/prompts.py`, so
  Core compaction no longer imports Code Squid application prompts. Workspace
  safety, guarded commands, approval/denial and yolo behavior, hook and
  cancellation ordering, transcripts, and compaction trigger/chunk/retention
  behavior were intentionally preserved. Focused suite: 122 passed. Full
  suite: 741 passed. Broader physical package moves, Mods/Extensions
  unification, runner customization, and Desktop migration remain deferred to
  later patches.
- 2026-09-01: Established the generic Squid Core Agent and prompt ownership
  boundary. `squid_core.agent.Agent` now owns generic agent state, raw initial
  and follow-up message construction, tool exposure, reply validation,
  completion rules, reason-specific corrections, and repeated-invalid failure
  messages. Core also owns protected response protocol, narration guidance,
  examples, Skill/environment insertion, and prompt assembly. Code Squid keeps
  its explicit non-replaceable coding baseline and replaceable application
  defaults in `agent/prompts.py`; runners inject those defaults into Core.
  `agent.coding.CodingAgent` remains a compatibility alias. Runtime behavior is
  unchanged: tasks and follow-ups stay raw authored user messages, tool turns
  accept exactly one action even with blank narration, and non-empty no-tool
  replies are final. Full suite: 734 passed.
- 2026-08-30: Added an optional request-scoped streaming trace callback for
  diagnostic callers. OpenAI-compatible and native Ollama providers report the
  exact generation payload, raw chunks, exposed reasoning/thinking fields,
  response/finish metadata, and first/total timing before normal response
  assembly. Callers that omit the callback retain the existing generation path.
- 2026-08-22: Made session transcripts canonical for user-authored tasks.
  Initial and follow-up text now persist as raw `role=user` messages, while
  task/follow-up prompt guidance and invalid-reply corrections are assembled
  only for model requests. Resumed runs retain prior canonical context and the
  existing continuation guidance without saving control prompts as user turns.
- 2026-08-09: Added append-only `model_reply` and linked `reply_rejection`
  diagnostics to each session JSONL. Core now preserves provider-exposed raw
  tool arguments, content, reasoning/thinking, finish reason, usage, provider,
  model, and response IDs before validation, while diagnostic entries remain
  excluded from canonical conversation replay. Streaming provider adapters
  retain exposed finish/reasoning metadata as well.
- 2026-08-04: Added an explicit resolved-component seam to fresh run
  construction. Hosts that already resolved a Skill and executable tool
  registry can pass `resolved_skill` and `resolved_tools` together, bypassing
  discovery while Core continues to own run construction and execution. The
  seam is package-agnostic and adds no Core knowledge of Mods.
- 2026-08-04: Added optional `session_store_factory` and
  `undo_store_factory` inputs to fresh run construction and the convenience
  runner. Core still creates repository-local stores by default, while hosts
  can independently provide alternate persistence without replacing imported
  globals or exposing host storage layouts to Core.
- 2026-08-04: Added public metadata-to-runtime seams for package-aware hosts.
  `build_user_tool_registry_from_metadata(...)` builds Core's standard lazy
  executable entries from an explicit `UserTool` mapping, while
  `load_hook_infos(...)` instantiates an explicit `HookInfo` list. Desktop owns
  Mod-local/shared precedence because it owns package selection; Core continues
  to own safe tool execution, result normalization, source import, and hook
  factory behavior. Existing standalone discovery APIs and CLI behavior remain
  intact. Tests verify the explicit paths execute and that metadata-only
  discovery/registry construction does not import source.
- 2026-06-27: Skill prompts now omit default coding-agent tool guidance unless a skill explicitly provides its own `TOOL_USAGE_GUIDANCE` override.
- 2026-07-06: Added core extension discovery/state/validation. Extensions stay inactive until selected through `active_extension` state; runtime skill/tool/hook wiring is not included in this patch.
- 2026-07-06: Active extension skills/tools now participate in discovery. Extension tools are only active through selected skills that explicitly allow them; no-skill runs still use built-ins only.
- 2026-07-06: Active extension hooks now load while an extension is active and deactivate when the extension is inactive or invalid. Loose user hooks continue to work independently through the existing user-hook opt-in path.
- 2026-07-06: Added CLI extension management commands for listing, checking,
  activating, deactivating, and validating discovered user extensions.

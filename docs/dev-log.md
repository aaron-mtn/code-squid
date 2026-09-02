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

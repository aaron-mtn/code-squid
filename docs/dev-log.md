- 2026-09-17: Added the protected original system and user messages to the
  compaction summarizer request as separately labeled authoritative reference
  context. They remain verbatim outside the generated summary; selected older
  history, the preserved recent tail, and the authoritative runtime-facts
  cutoff are unchanged. Added regressions for concrete original requirements,
  pre-cutoff user instructions, post-cutoff exclusion, verbatim retention, and
  the existing provider/no-provider paths. Focused compaction/context tests
  passed 43 tests, and the broader loop/runner/spawner/storage/adapter/boundary
  suite passed 184 tests. The full suite passed 1,278 tests with the same 29
  unrelated existing prompt-copy, repeated-read-guidance-copy, and Windows TTY
  expectation failures recorded by preceding patches. Production and test
  compilation, direct imports, and `git diff --check` passed; no live model
  inference was run.
- 2026-09-17: Scoped authoritative compaction facts to the exact canonical
  history represented by each summary. Core now passes the flattened preserved
  message tail to its optional application context provider, generates the
  returned text once, and supplies that identical text both to the summarizer
  as authoritative host/runtime facts and after the generated summary as the
  deterministic backstop. Code Squid validates that the tail exactly matches
  the canonical session-message suffix and fails closed on mismatch, then
  derives facts from the remaining prefix without cumulative state. The facts
  now include mechanical success/failure counts for the four built-in Tools and
  explicit careful absence statements for known direct mutation and
  verification. Focused compaction/context/session/runner/spawner verification
  passed 94 tests; the full suite passed 1,275 tests with the same 29 unrelated
  existing prompt-copy, repeated-read-guidance-copy, and Windows TTY expectation
  failures recorded by preceding patches. Production and test compilation,
  direct imports, and `git diff --check` passed; no live model inference was run.
- 2026-09-17: Added a small optional Core compaction-context callback that
  appends deterministic application text only after a model-written summary.
  Missing, empty, invalid, or failing callbacks preserve summary-only
  compaction. Code Squid now supplies an application-owned provider that reads
  the full canonical session message history at compaction time and carries
  forward only the latest known successful direct mutation, latest explicit
  verification and its relationship to later known direct mutations, and the
  latest concrete unresolved Tool failure. Core has no Code Squid Tool
  semantics, no planner state was added, and the provider makes no filesystem,
  behavioral-correctness, completion, or command-side-effect claims. The
  provider omits successful command output and carries short failure output
  verbatim; long failure output is bounded mechanically to raw head and tail
  portions without error parsing. The generic summarizer guidance now makes
  recency, stale verification,
  unresolved failures, and intended-versus-performed changes explicit.
  Focused output-context verification passed 9 tests, and the broader
  compaction/context/runner/architecture-boundary suite passed 66 tests.
  The final full suite completed with 1,269 passing tests and the same 29
  unrelated existing prompt-copy, repeated-read-guidance-copy, and Windows TTY
  expectation failures recorded by preceding patches. Production and test
  compilation, direct
  imports, and `git diff --check` passed; no live model inference was run.
- 2026-09-17: Made Core's existing `run_command.verification` boolean required
  in both the model-facing schema and built-in executor signature. Code Squid's
  non-replaceable baseline policy now explains purpose-based classification,
  representative verification and non-verification commands, and that omitted
  values are invalid. Normal model-adapter validation rejects omissions, while
  canonical command results and `PostVerificationNudge` behavior remain
  unchanged. Focused Tool, adapter, executor, prompt, and post-verification
  coverage passed 123 tests. The full suite passed 1,255 tests with the same 29
  unrelated existing prompt-copy, repeated-read-guidance-copy, and Windows TTY
  expectation failures recorded by preceding patches. Production and test
  compilation plus `git diff --check` passed; no live model inference was run.
- 2026-09-16: Simplified built-in Tool results at the existing request-only
  model-rendering seam. Canonical transcript JSON and runtime result
  dictionaries remain unchanged for Hooks, storage, replay, trimming, and
  coverage tracking. Model requests now receive compact textual observations:
  `read_file` emits ordinary source beneath exact per-region line headers and
  explicit gap markers (including partial/suppressed repeated reads), commands
  use a small output block, patch failures retain recovery identifiers and
  current candidate text, and successful writes are status plus path. Unknown
  tools remain JSON. Added focused formatter, trimming/coverage, provider
  pairing, and `model-view.jsonl` assertions. Verification: 242 focused and
  broader agent-loop, Hook, compaction, built-in Tool, executor, spawner, and
  model-view tests passed. The full suite passed 1,252 tests with the same 29
  unrelated existing prompt-copy, repeated-read-guidance-copy, and Windows TTY
  expectation failures recorded by preceding patches. Production/test
  compilation and `git diff --check` passed; no live model inference was run.
- 2026-09-16: Added always-on per-session `model-view.jsonl` request capture
  beside `session.jsonl`. Refactored the initial loop-level implementation so
  `ModelAdapter` exposes a generic request observer and invokes it from one
  shared finalized-request transport boundary immediately before every real
  provider attempt. The Core spawner wires that observer to the session store;
  `AgentLoop` and `Compactor` contain no model-view-specific persistence or
  observer plumbing. This captures ordinary, streaming, retry, compaction, and
  direct prepared-request calls without reconstructing requests, while keeping
  persistence failures non-fatal and storage knowledge out of the adapter.
  Also made every disjoint `read_file` result render an explicit omitted-line
  marker without changing
  returned range selection or metadata, and taught old-result trimming not to
  count marker lines as source coverage. Compaction requests use the same
  shared adapter seam and repeated-read result shaping preserves separators
  between remaining disjoint regions. Verification: 171 focused model-adapter,
  model-view, agent-loop, compaction, session-store, and Core-spawner tests
  passed. The full suite passed 1,244 tests with 31 unrelated existing
  prompt-copy, repeated-read-guidance-copy, runner-guidance-copy, and Windows
  TTY expectation failures. Production and test compilation plus
  `git diff --check` passed; no live model inference was run.
- 2026-09-16: Made model-request failures diagnosable and conservatively
  retryable without changing the agent/tool loop. `ModelAdapter` now retains
  precise, credential-redacted provider exception details and classifies
  timeout, connection, rate-limit, provider 5xx, stream, malformed-response,
  authentication, configuration, and unknown failures. `AgentLoop` retries
  only transient `ModelRequestError` failures from one unchanged rendered
  message snapshot, records failed/scheduled/started attempt lifecycle in the
  main session JSONL, and reports retry count on eventual success. Application
  and Core runtime settings expose bounded retry-count and backoff values,
  defaulting to 2 retries and 250 ms. Verification: 266 focused
  adapter/agent-loop/settings/spawner tests passed; 243 broader
  runtime/provider/logging tests passed; the full suite passed 1,258 tests with
  the same nine unrelated baseline prompt/terminal failures recorded by
  preceding patches. Compilation and `git diff --check` passed.
- 2026-09-16: Added Core's optional `TooManyReadsNudge` to recognize successful
  `read_file` accumulation without a successful `apply_patch` or `write_file`.
  The advisory Hook nudges at three reads, escalates at five and later reads,
  treats commands and failed Tools as neutral, preserves its behavioral count
  through compaction, resets at run start, and never changes read output. Code
  Squid now wires it independently beside the existing built-in Hooks and can
  disable it with `runtime.too_many_reads_enabled` without affecting them.
  Focused tests cover thresholds, non-consecutive reads, mutation and failure
  semantics, compaction, run reset, unmodified output, threshold validation,
  default wiring, and settings-based disabling. Verification: 263 focused and
  broader Hook/agent-loop tests passed; the full suite passed 1,242 tests with
  the same nine unrelated baseline failures documented by preceding patches:
  eight stale prompt-copy expectations and one Windows TTY path-rendering
  assertion. All Python modules compiled and `git diff --check` passed. No live
  model inference ran, and no follow-up is intentionally deferred.

- 2026-09-16: Simplified Core's public `read_file` contract so every targeted
  read uses a single `ranges` representation. Removed top-level `start_line`
  and `end_line` from the schema and executor, capped requests at eight ranges,
  and applied the existing normalized merged line budget uniformly to one- and
  multi-region reads. Updated prompt guidance, repeated-read request metadata,
  tests, README, and architecture documentation. Verification: 91 focused
  read-tool and repeated-read tests passed; 180 broader trimming, compaction,
  executor, agent-loop, and prompt-guidance tests passed with five known stale
  prompt-copy checks excluded. The full suite passed 1,222 tests with the same
  nine unrelated baseline failures documented by preceding patches: eight
  stale prompt-copy expectations and one Windows TTY path-rendering assertion.
  Core, application, and test modules compiled, the read-tool import/schema
  smoke check passed, and `git diff --check` passed. No live model inference
  ran, and no follow-up is intentionally deferred.

- 2026-09-16: Added a generic optional reasoning-token budget to Core provider
  settings and Code Squid model settings, including strict non-negative-integer
  validation and the `CODE_SQUID_REASONING_TOKEN_BUDGET` override/unset behavior.
  Built-in provider construction now forwards both normalized reasoning values.
  OpenRouter sends positive budgets through its separate
  `reasoning.max_tokens` field; because its current API documents budget and
  effort as alternatives, an explicit budget wins. Zero remains valid in Core
  but is not sent without documented provider support. The existing request-
  local no-reasoning override remains authoritative, and unsupported adapters
  do not approximate a reasoning budget with total output limits. Model request
  lifecycle events now include the effective normalized values when configured.
  Verification: 267 focused settings/provider/generation/spawner/agent-loop
  tests passed. The full suite passed 1,221 tests with the same nine unrelated
  baseline failures documented by preceding patches: eight stale prompt-copy
  expectations and one Windows TTY path-rendering assertion. All Python modules
  compiled, the public settings/provider import smoke check passed, and
  `git diff --check` passed. A credentialed OpenRouter smoke test against
  `deepseek/deepseek-v4-flash-0731` used reasoning mode `low` and a 4,000-token
  reasoning budget; it returned normal assistant code successfully with 36
  input, 301 output, and 337 total tokens. The short request did not exhaust the
  budget, and OpenRouter's returned usage did not separate reasoning tokens, so
  cutoff-at-budget behavior was not directly observed.

- 2026-09-15: Added optional same-file multi-range reads to Core's existing
  `read_file` tool. A `ranges` request uses the legacy inclusive line and
  minimum-context semantics for each region, sorts and merges overlapping or
  adjacent effective ranges, and rejects combined coverage above the existing
  `default_max_lines` budget. Results reuse `returned_line_ranges`, so
  RepeatedReadNudge's novel-only shaping, mutation invalidation, compaction
  reset, and trim-aware per-result provenance continue through the existing
  machinery. Whole-file and single-range branches remain unchanged. Updated
  the model-facing schema, prompt guidance, README, and architecture reference.
  Verification: 228 focused read-tool, repeated-read, trimming, compaction,
  executor, and runtime Hook tests passed. The full suite passed 1,192 tests
  with the same nine unrelated baseline failures documented by preceding
  patches: eight stale prompt-copy expectations and one Windows TTY
  path-rendering assertion. Core, application, and test modules compiled, the
  read-tool import/schema smoke check passed, and `git diff --check` passed. No
  live model inference ran, and no follow-up is intentionally deferred.

- 2026-09-15: Changed `RepeatedReadNudge` from ratio-based binary masking to
  exact novel-range shaping. Successful partially redundant reads now return
  only source lines not already visible and unchanged, including multiple
  fragments and truncated head/tail results, with accurate returned-range and
  character metadata plus a compact omission message. Fully new reads remain
  unchanged; fully covered reads retain the existing `already_covered` mask.
  Partial reads advance the persistent per-file strike while recording only
  source actually left visible, so later reads and `read_result_trimmed`
  continue to reflect model-visible coverage. Unsafe content-to-range mappings
  conservatively preserve the original result. The obsolete 70% overlap
  constant and public export were removed. Mutation invalidation, stale-range
  refresh, compaction, and post-verification behavior were not redesigned.
  Verification: 42 focused repeated-read tests and 163 broader Hook/runtime
  tests passed. The full suite passed 1,181 tests with the same nine unrelated
  baseline failures documented by preceding patches: eight stale prompt-copy
  expectations and one Windows TTY path-rendering assertion. Core,
  application, and test modules compiled, the public import smoke test passed,
  and `git diff --check` passed. No live model inference ran, and no follow-up
  is intentionally deferred.

- 2026-09-15: Made `RepeatedReadNudge` keep each file's redundant-read strikes
  across later useful reads and after stronger escalation. Counts now remain at
  the escalated level until existing evidence-invalidation seams clear them,
  including successful mutation, relevant result trimming, compaction, and a
  new run; files remain independent. Partial-overlap trimming and novel-only
  read results remain intentionally deferred. Verification: 54 focused
  repeated-read/trimming tests and 299 broader Hook/runtime tests passed. The
  full suite passed 1,175 tests with the same nine unrelated baseline failures
  documented by preceding patches: eight stale prompt-copy expectations and one
  Windows TTY path-rendering assertion. Changed modules compiled, and
  `git diff --check` passed. No live model inference ran.

- 2026-09-15: Strengthened `PostVerificationNudge` around a deliberately small
  state model: current verification plus a count of subsequent successful Tool
  actions. The default threshold is now two; reads, searches, commands, other
  successful non-mutation activity, and repeated verification all advance the
  count regardless of verification command text. Successful `apply_patch` or
  `write_file` and failed explicit verification invalidate the current receipt
  and reset the count. Command-signature tracking was removed. The Hook remains
  advisory and retains its non-stacking behavior with `RepeatedReadNudge`.
  Verification: 103 focused post-verification/wiring/agent-loop tests passed.
  The full suite passed 1,174 tests with the same nine unrelated baseline
  failures documented by the preceding patch: eight stale prompt-copy
  expectations and one Windows TTY path-rendering assertion. Core, application,
  and test modules compiled, and `git diff --check` passed. No live model
  inference ran, and no follow-up is intentionally deferred.

- 2026-09-15: Made `PostVerificationNudge` self-contained and removed the
  standalone `VerificationState` Hook. The nudge now privately owns current
  verification, normalized successful-command signatures, duplicate detection,
  and its no-progress streak. `RepeatedReadNudge` no longer accepts or consults
  verification state and always emits its normal reread guidance. Reads masked
  as already covered still advance the post-verification streak without stacking
  finalization guidance on the same result. Application wiring and exports now
  expose only the two independent policy Hooks. Verification: 57 focused
  post-verification/repeated-read/wiring tests and 199 broader Hook/runtime
  tests passed. The full suite passed 1,169 tests with the same nine unrelated
  baseline failures documented by preceding patches: eight stale prompt-copy
  expectations and one Windows TTY path-rendering assertion. Changed modules
  compiled, the public-import/wiring smoke test passed, and `git diff --check`
  passed. No live model inference ran, and no follow-up is intentionally
  deferred.

- 2026-09-14: Made `RepeatedReadNudge` coverage match source that remains in
  the effective model request. Request-only tool-result trimming now maps its
  retained character head/tail back to complete `read_file` source lines and
  notifies Hooks through a narrow `read_result_trimmed` seam. The repeated-read
  Hook keeps bounded per-tool-call provenance, retracts fully or partially
  trimmed results without losing overlapping visible reads, and preserves
  original-to-current line mappings across patches. Metadata-only trimmed
  results no longer suppress recovery reads; a successful recovery read
  restores coverage normally. Canonical session/history rendering remains
  unchanged, as do no-trimming behavior, mutation invalidation, compaction,
  and shell-command handling. Verification: 53 focused trimming/repeated-read
  tests and 271 broader Hook/loop/compaction/Tool tests passed. The full suite
  passed 1,171 tests with the same nine unrelated baseline failures documented
  by preceding patches: eight stale prompt-copy expectations and one Windows
  TTY path-rendering assertion. Core, application, and test compilation plus
  `git diff --check` passed. No live model inference ran, and no follow-up is
  intentionally deferred.

- 2026-09-14: Added a small post-verification no-progress nudge. Core's run-local
  `VerificationState` now tracks current verification, normalized successful
  command signatures for the current implementation, and a shared observation
  streak. New successful verification commands reset the streak, duplicate
  successful commands advance it, failed verification supplies actionable new
  information and clears it, and successful structured edits invalidate all
  prior verification facts. A separate `PostVerificationNudge`, wired after the
  existing repeated-read Hook, counts supported post-verification reads and
  duplicate checks and emits non-blocking finalization guidance after three
  actions. It deliberately does not parse arbitrary shell commands. Added normal
  coding guidance and a prompt-policy regression requiring obsolete replaced
  implementations to be removed unless concretely retained. Verification: 61
  focused hook/state/repeated-read/wiring/prompt/mod tests passed. The full suite
  passed 1,164 tests with the nine previously documented unrelated failures
  (eight stale prompt-copy expectations and one Windows TTY path-rendering
  assertion). Core, application, and changed-test compilation plus
  `git diff --check` passed.

- 2026-09-14: Fixed the startup Workspace submenu's transient-state crash.
  Workspace rendering, movement, and activation now use the recent-path tuple
  as their authoritative collection, invalid activation indexes are ignored,
  and an empty recent list remains safely open. Main-row activation also
  prepares submenu-specific state before publishing the new mode, preventing a
  render callback from pairing Workspace labels with stale provider/model
  options. Added focused regressions for submenu transitions, mismatched stale
  option counts, empty discovery, and out-of-range activation. Verification:
  40 focused startup-menu tests passed; 347 broader console/UI tests passed
  with the existing unrelated Windows TTY path-rendering assertion failure.
  Changed modules compiled and `git diff --check` passed.

- 2026-09-14: Added explicit verification intent to Core's `run_command` schema
  and result metadata, defaulting to false without inspecting command text.
  Added a separate run-local `VerificationState` Hook that becomes true only
  after a successful explicitly marked verification command and resets after a
  successful `apply_patch` or `write_file`. Code Squid now shares that state
  with the existing `RepeatedReadNudge`, which uses finalization-aware wording
  for its normal redundant-read guidance when verification is current; it does
  not block reads or infer completion. Existing read coverage, mutation
  invalidation, escalation, and compaction behavior remain unchanged. Added
  focused Tool schema/result, state-transition, application-wiring, and guidance
  regressions. Verification: 101 focused Tool/state/repeated-read/wiring/mod
  tests passed; 338 broader relevant tests passed with five unrelated stale
  prompt-copy failures; the full suite passed 1,150 tests with the nine unrelated
  baseline failures (eight stale prompt-copy expectations and one Windows TTY
  path-rendering assertion). Core and application compilation, Hook/tool import
  smoke checks, and `git diff --check` passed.

- 2026-09-12: Made successful context compaction a reset boundary for Core's
  `RepeatedReadNudge`. `AgentLoop` now dispatches a narrow Hook seam only for
  the existing authoritative `compaction_applied` event, after the in-memory
  transcript rebuild and compaction-event persistence. The Hook clears all
  tracked files' coverage, patch-stale ranges, and per-file redundant-read
  counters, so the first post-compaction read returns fresh source and an
  immediate repeat is suppressed normally. Compaction checks, starts,
  requests, failures, and otherwise unapplied attempts leave state intact.
  Added focused state/sequence regressions, Hook seam coverage, and AgentLoop
  lifecycle integration coverage, and synchronized the repeated-read test's
  stale guidance copy with the already-existing production text without
  changing that prompt. Verification: 32 focused repeated-read tests and 219
  broader Hook/runtime/compaction/Tool tests passed; the full suite passed
  1,139 tests with the same nine unrelated baseline failures recorded by the
  preceding patches (eight stale prompt-copy expectations and one Windows TTY
  path-rendering assertion). Changed modules and tests compiled, the Core Hook
  import smoke passed, and `git diff --check` passed. No compaction policy,
  thresholds, production prompts, Tool schemas, mutation invalidation, or
  repeated-read escalation behavior changed. No live model inference ran, and
  no concrete follow-up is intentionally deferred.

- 2026-09-12: Corrected `RepeatedReadNudge` mutation invalidation so a
  successful `apply_patch` makes its changed lines readable on the next
  intersecting `read_file`, even when unchanged surrounding lines keep the
  verification window above the normal 70% overlap threshold. Patch handling
  still trims or splits old coverage and shifts post-edit coverage by the line
  delta, while a separate bounded stale-span marker forces only the first read
  returning changed lines through and is cleared for the lines that read made
  fresh. Successful `write_file` clears both coverage and stale markers for its
  target; file identities remain isolated. Added regressions for real patch and
  read integration, immediate repeat masking, partial-range preservation,
  line-count shifts, whole-file writes, cross-file isolation, and retained the
  existing truncated head/tail coverage test. Verification: 30 focused
  repeated-read tests and 156 broader Hook/runtime/Tool tests passed; changed
  modules and tests compiled, and `git diff --check` passed. The full suite
  passed 1,135 tests and retained the same nine unrelated baseline failures
  recorded by the preceding patch: eight stale prompt-copy expectations and
  one Windows TTY path-rendering assertion. No live model inference ran. No
  concrete follow-up is intentionally deferred.

- 2026-09-12: Changed Core's existing `RepeatedReadNudge` so the first
  substantially overlapping unchanged `read_file` reread at the configured
  threshold is masked immediately instead of returning duplicate source. The
  small successful `already_covered` result preserves path and range metadata,
  identifies the still-current prior result, and is paired with action-oriented
  guidance to reuse context and make a focused edit when clear. A further
  qualifying reread retains the stronger correction and resets the per-file
  streak. Existing overlap thresholds, coverage tracking, truncated-range
  handling, mutation invalidation/adjustment, per-file isolation, and reset
  rules remain unchanged; `read_file` itself was not changed. Verification:
  focused repeated-read tests passed 26 tests; broader Hook, runtime-wiring, and
  agent-loop tests passed 111 tests. The full suite passed 1,131 tests and
  retained the same nine unrelated baseline failures recorded by preceding
  patches: eight stale prompt-copy expectations and one Windows TTY
  path-rendering assertion. Changed modules and tests compiled, the Core Hook
  import smoke passed, and `git diff --check` passed. No live model inference
  ran, and no follow-up work is intentionally deferred.

- 2026-09-11: Made reconstructed compaction summaries explicitly synthetic and
  non-authoritative. Compaction still protects the initial system and verbatim
  first user messages, but now inserts its model-generated summary as an
  `assistant` message headed `# Compacted Working Context` with a model-visible
  warning that real user messages are authoritative and the lossy summary cannot
  add, replace, or override their requirements. Strengthened the generic
  summarizer prompt against inventing or reinterpreting requested behavior.
  Triggering, chunk selection, recent-tail retention, tool-call/result integrity,
  lifecycle diagnostics, exact-summary logging, metadata, and failure handling
  are unchanged. Verification: 21 focused compaction tests and 144 related
  adapter/provider/agent-loop tests passed; production/test compilation, import
  smoke, and `git diff --check` passed. The full suite passed 1,130 tests and
  retained the same nine unrelated baseline failures recorded by preceding
  patches: eight stale prompt-copy expectations and one Windows TTY path-rendering
  assertion. No live model inference ran. Preserving later real user messages
  beyond the existing recent-tail policy remains intentionally deferred.

- 2026-09-11: Escalated Core's existing `RepeatedReadNudge` in two stages. The
  first substantially redundant unchanged `read_file` still returns its normal
  contents with the existing transient guidance; the next qualifying read in
  the same per-file streak now uses the `tool_result` transformation seam to
  return a small successful `already_covered` result without duplicate source
  text, then resets that streak. Non-redundant reads and successful mutations
  reset pending escalation as before, failed reads do not advance it, and all
  existing range coverage, truncated head/tail, patch adjustment, write
  invalidation, and per-file isolation rules remain unchanged. Verification:
  focused repeated-read and Hook suites passed 62 tests. The full suite passed
  1,129 tests and retained the same nine unrelated baseline failures already
  recorded by preceding patches: eight stale prompt-copy expectations and one
  Windows TTY path-rendering assertion. Production/test compilation and
  `git diff --check` passed; no live model inference ran. No follow-up work is
  intentionally deferred.

- 2026-09-11: Updated Code Squid's canonical read guidance to prefer whole-file
  reads when useful and substantial coherent regions for larger files, while
  discouraging incremental adjacent ranges and post-patch rereads used only as
  confirmation. Added Core `ReadFileSettings` defaults of 1,000 maximum lines
  for whole-file reads and a 150-line minimum ranged-read window. Small valid
  ranges now expand around the requested area and shift at file boundaries;
  larger ranges, full-file truncation, and past-EOF reads retain their prior
  behavior. Results report the effective expanded line bounds, preserving
  `RepeatedReadNudge` coverage semantics. Focused read, prompt, repeated-read,
  settings, and runtime-wiring verification passed 182 tests. The full suite
  passed 1,122 tests and retained the same nine unrelated baseline failures
  already recorded by preceding patches: eight stale prompt-copy expectations
  and one Windows TTY path-rendering assertion. Production and test compilation
  plus `git diff --check` passed; no live model inference ran. No follow-up work
  is intentionally deferred.

- 2026-09-10: Audited the normal Code Squid Hook path and confirmed that the
  application builder already appended `RepeatedReadNudge` and
  `RepeatedFailureNudge` before passing its `HookRunner` into `AgentLoop`; no
  production wiring fix was needed. Added compact `hooks_configured` and
  per-handler `hook_execution` records to the existing persisted runtime-event
  pipeline. Outcomes distinguish no effect, an effect category, and errors
  without copying Hook-returned text, Tool output, prompt context, or exception
  details. Added generic coverage for every lifecycle seam and Hook errors plus
  Code Squid builder regressions proving that unchanged `read_file` ranges with
  70% overlap fire the repeated-read guidance and 69% overlap does not, while
  both leave events in the normal session JSONL. `run_command` file inspection
  remains outside repeated-read tracking because it has no structured returned
  line metadata. Focused Hook, wiring, persistence, and loop coverage passed 149
  tests. The full suite passed 1,109 tests and retained the same nine unrelated
  baseline failures already recorded by preceding patches: eight stale
  prompt-copy expectations and one Windows TTY path-rendering assertion.
  Production/test compilation and `git diff --check` passed; no live model
  inference ran.

- 2026-09-10: Added a minimal normalized provider reasoning setting with
  `off`, `low`, `medium`, and `high` values and a default of `null`. Code Squid
  application settings now pass the value through Core's existing
  `ProviderSettings` and provider-construction seam. At the concrete
  OpenRouter request boundary, `off` maps to reasoning effort `none` and the
  other values map directly; unset values and every provider without a known
  mapping retain their prior request shape. No reasoning policy, budgets,
  model registry, capability detection, prompt changes, or GUI controls were
  added. Focused settings/provider tests passed 154 tests. The full suite
  passed 1,105 tests and retained the same nine failures recorded by the prior
  patch: eight stale prompt-copy expectations and one Windows TTY path-rendering
  assertion. Production/test compilation and `git diff --check` passed; no live
  model inference ran.

- 2026-09-10: Tightened `RepeatedReadNudge` so its default threshold advises on
  the first read with at least 70% prior coverage while retaining configurable
  thresholds, including one. Successful `apply_patch` results now use their
  before/after line metadata to remove only changed coverage and shift known
  later ranges by the line-count delta; `write_file` still clears the whole
  file, and failed mutations leave coverage untouched. Added focused coverage
  for overlap boundaries, truncated reads, mutation outcomes, forward/backward
  shifts, split ranges, changed-line invalidation, threshold behavior, and run
  reset. The focused Hook and wiring tests passed 23 tests. The full suite
  passed 1,080 tests and retained nine failures in untouched areas: eight stale
  prompt-copy expectations and one Windows TTY path-rendering assertion.
  Production/test compilation and `git diff --check` passed; no live model
  inference ran.

- 2026-09-10: Replaced the narrow small-range `RedundantReadNudge` behavior
  with Core's `RepeatedReadNudge`. It now compares actual successful
  `read_file` returned ranges by normalized absolute path, treats at least 70%
  prior coverage as redundant, preserves disjoint `returned_line_ranges` for
  truncated full-file reads, and advises through the existing transient
  `tool_result` `additional_context` seam on the second redundant reread. A
  successful `apply_patch` or `write_file` invalidates that file's run-local
  coverage and streak; failures do not, emission resets the streak, and
  `before_run` clears all tracking. Focused Hook and default-wiring tests passed
  17 tests. The full suite passed 1,074 tests and retained nine failures in
  untouched areas: eight stale prompt-copy expectations and one Windows TTY
  path-rendering assertion. Production/test compilation and `git diff --check`
  passed; no live model inference ran.

- 2026-09-10: Added a small durable runtime lifecycle around ordinary model
  turns and run termination. `AgentLoop` now emits and persists compact
  `model_request_started`, `model_request_finished`, and
  `model_request_failed` records without prompt/message contents, including
  readily available adapter identity, request size estimates, duration, and
  bounded error details. Requested cancellation and boundary interruptions now
  leave `run_interrupted`; unexpected exceptions and existing failed outcomes
  leave `run_failed` with a known runtime stage before session status changes.
  All records use the existing linked session JSONL path, remain outside model
  transcript replay, and preserve original exceptions and host control flow.
  Focused loop/storage/Hook/CLI verification passed 181 tests. The full suite passed
  1,075 tests with nine unrelated baseline failures in prompt-copy and Windows
  TTY path assertions. No
  live model inference ran; no follow-up work is intentionally deferred.

- 2026-09-10: Changed transcript compaction selection from a fixed
  `keep_recent_turns` split to deterministic oldest-first token-weight
  selection. Compaction now targets 80% of eligible chunk tokens by default,
  preserves at least two newest chunks, excludes the protected system/original
  task prefix from the fraction, and retains indivisible Tool-call/result
  chunks. Added explicit fraction and recent-chunk settings, richer lifecycle
  diagnostics, and repeated-summary coverage. Older `keep_recent_turns` JSON is
  ignored and must be renamed when a customized retention value is desired.
  Focused compaction/settings/status/loop/persistence verification passed 230
  tests. The full suite passed 1,071 tests and retained the same nine unrelated
  baseline failures (eight prompt-text expectations and one Windows TTY path
  assertion); compilation and diff checks passed.

- 2026-09-10: Added a centralized request-only boundary for trimming old Tool
  results before ordinary model turns. Complete Tool results still flow through
  normal transcript and append-only session persistence; `AgentLoop` now asks
  `tool_result_trimming.py` for a model-visible copy immediately before calling
  the adapter. Core's frozen `ToolResultTrimmingSettings` exposes direct knobs
  for the recent full-result count and old read, command, failed-patch, and
  write payload limits. Trimming is deterministic, preserves Tool-call/result
  IDs and operational metadata, leaves unknown Tools unchanged, and uses small
  omission markers at zero limits. No built-in Tool, canonical event,
  compaction behavior, semantic invalidation, or presets changed. Focused
  rendering/settings/spawner/loop verification passed 98 tests. The full suite
  passed 1,051 tests and retained nine failures in untouched areas: eight stale
  prompt-copy expectations and one Windows TTY path-rendering assertion.
  Production/test compilation passed; no live model inference ran.

- 2026-09-09: Added deterministic `run_command` failure diagnostics and
  transient recovery after command flailing. Failed command executions now
  retain output while exposing a conservative `failure_class` plus shell and
  platform facts; timeout, recognizable PowerShell parser/missing-command
  diagnostics, selected path/permission signals, generic process failures, and
  launch failures remain mechanically distinct. Core's existing
  `RepeatedFailureNudge` now keeps a separate run-local count across different
  failed command strings, ignores unrelated Tools, resets on command success,
  and uses the existing one-request-only context path at three failures. Code
  Squid continues to own the recovery wording. No polling, background process,
  output-handle, retry, command rewrite, or general trimming behavior was
  added. Focused Tool/Hook/loop/wiring verification passed 77 tests. The full
  suite passed 1,040 tests and retained nine failures in untouched areas: eight
  stale prompt-copy expectations and one Windows TTY path-rendering assertion.
  Production/test compilation and `git diff --check` passed. No live model
  inference ran.

- 2026-09-09: Surfaced actual context compaction in normal CLI output as the
  indented, dim `🌀 Compacting context...` notification. `AgentLoop` now
  forwards the existing persisted `compaction_started` event through its
  observer seam, so ordinary threshold checks remain silent. Neutral
  previous-session and compaction notices share the same notification rendering
  helper; assistant, tool, warning, compaction, and persistence semantics are
  otherwise unchanged. Ten focused renderer/loop/compaction tests passed, as
  did compilation and `git diff --check`. The full suite passed 1,034 tests with
  seven pre-existing failures in untouched prompt-copy expectations and Windows
  TTY debug path rendering.

- 2026-09-09: Added first-class compaction observability to canonical session
  JSONL. Each enabled check now records its token estimate and trigger decision;
  actual compactions record start/request identity and size, optional normalized
  reasoning, the exact returned summary before mutation, optional usage/finish
  metadata, and final before/after counts. Failures record the active prepare,
  model-request, response-parse, session-rebuild, or persistence stage without
  swallowing the original exception. `ModelAdapter.complete_text()` now exposes
  normalized reasoning and finish reason in addition to its existing content
  and usage fields, and `SessionStore.append_compaction_event()` owns the linked
  lifecycle-event persistence seam. Compaction thresholds, prompts, retention,
  summary semantics, and reconstruction behavior are unchanged. Focused
  compaction/session/adapter/loop verification passed 135 tests, and the
  broader related Core subset passed 112 tests. The full suite reached 1,032
  passes with six failures in untouched prompt-copy and Windows TTY display
  areas outside this patch. Core compilation and
  `git diff --check` passed.

- 2026-09-09: Refined `apply_patch` argument precedence so a known stored
  `match_id` remains authoritative, while an empty or unknown string ID is
  ignored when complete normal patch arguments are present. Incomplete calls
  with unusable IDs retain `patch_candidate_unavailable`; exact matching,
  candidate revalidation, path conflicts, invalidation, diagnostics, and undo
  behavior are unchanged. Focused executor tests, affected-module compilation,
  and `git diff --check` passed.

- 2026-09-09: Added the thin interactive `/compact-at <tokens>` command over
  the existing application compaction setting. Plain integers and exact `k`
  shorthand, including decimals such as `28.5k`, normalize to a positive
  integer `compaction.trigger_input_tokens`; invalid input prints concise
  guidance without writing settings. No model context-limit discovery or
  automatic compaction behavior changed. The focused runtime-command suite
  passed 34 tests; settings/help checks passed 56 tests; affected-module
  compilation and `git diff --check` also passed.

- 2026-09-09: Made `apply_patch` candidate recovery tolerate redundant normal
  fields whenever `match_id` is present. Stored candidate text and replacement
  remain authoritative, a redundant path must identify the same target, and
  exact offset revalidation and candidate invalidation are unchanged. Switched
  the schema alternatives from `oneOf` to `anyOf` so compatible providers can
  emit the tolerated form. Focused Tool, executor, and adapter verification
  passed 90 tests; affected-module compilation and `git diff --check` also
  passed.

- 2026-09-09: Moved all `apply_patch` argument declarations into the Tool
  schema's top-level `properties`, leaving `oneOf` responsible only for the
  normal and candidate-selection required-field alternatives. This preserves
  runtime and recovery behavior while making the definition acceptable to LM
  Studio and stricter OpenAI-compatible providers. Confirmed the existing
  `ModelAdapter` required-variant extraction against this layout with focused
  schema and adapter validation tests: 58 tests passed. Compilation of the
  affected modules and tests and `git diff --check` also passed.

- 2026-09-09: Extended `apply_patch` diagnostic recovery with short-lived,
  selectable candidate IDs. Duplicate exact matches expose one ID per reported
  occurrence, and the existing above-threshold closest line window exposes one
  ID without changing its matcher or threshold. A path-less selection call
  retrieves the original request from run-local `ToolExecutor` memory,
  revalidates the stored exact candidate text at its original character
  offset, and applies the original replacement; it never fuzzy-mutates or
  searches for a substitute. Successful mutation invalidates candidates only
  for that target file, and a fresh executor/run starts empty. Updated the Tool
  schema, shallow model-action validation for alternative required argument
  forms, application guidance, undo snapshot integration, and focused
  regressions. Focused Tool, executor, adapter, schema, and prompt verification
  passed 88 tests. The full suite passed 1,014 tests and retained five
  pre-existing failures: four stale prompt-policy phrase assertions and one
  Windows TTY path-fragment assertion. Production/test compilation, affected
  import smoke checks, and `git diff --check` passed. No live model inference
  ran.

- 2026-09-09: Added Core's conservative `RedundantReadNudge` and enabled it in
  Code Squid's default Hook runner alongside `RepeatedFailureNudge`. The Hook
  retains bounded run-local actual line coverage from successful `read_file`
  results, invalidates only reliably identified successful `write_file` and
  `apply_patch` targets, and emits one-turn `additional_context` only after two
  consecutive small covered rereads of the same unchanged file. It does not
  block or rewrite Tools/results, and the generic runner/loop seams required no
  feature-specific changes. Focused Hook, runner-wiring, and Mod coverage passed
  63 tests. The full suite passed 995 tests and retained five pre-existing
  failures: four stale prompt-policy phrase assertions and one Windows TTY
  path-fragment assertion. Production/test compilation and `git diff --check`
  passed. No live model inference ran.

- 2026-09-09: Consolidated all lifecycle Hook return values into the frozen
  `HookResponse` dataclass while retaining event-specific input contexts and
  the existing runner/loop ownership boundary. `before_model_turn` now uses the
  same response contract as every other seam; Tool-result replacements are
  explicit through `updated_tool_output`; and ordered `additional_context`
  guidance uses the loop's existing one-request-only runtime-message path
  without entering canonical or persisted transcript history. Migrated the
  repeated-failure nudge to emit guidance directly from `tool_result`, removed
  its pending cross-event bridge and unused title, and retained `source` only
  because hosts use it as Hook configuration metadata. Added focused coverage
  for every aggregation/chaining/blocking seam, explicit result replacement,
  nudge reset behavior, and transient-versus-persisted loop behavior. Focused
  Hook, agent-loop, runner-wiring, and Mod coverage passed 121 tests. Full-suite
  verification passed 983 tests and retained five pre-existing failures: four
  stale prompt-policy phrase assertions and one Windows TTY path-fragment
  assertion. Production/test compilation and `git diff --check` passed. No
  live model inference ran.

- 2026-09-08: Changed full-file `read_file` truncation from the shared
  12,000-character helper to a dedicated 1,000-line limit. Files through the
  limit are returned unchanged; larger files return 500 head and 500 tail lines
  plus exact `returned_line_ranges` and guidance to inspect omitted content with
  `start_line` / `end_line`. Ranged reads remain untruncated, existing response
  fields remain available, and `run_command` retains shared character-based
  truncation. Also strengthened Code Squid's generic verification prompt to
  compare behavior with the user's request instead of treating syntax or build
  checks as behavioral proof. All 15 focused behavior tests passed. The full
  suite passed 980 tests and retained five pre-existing failures: four stale
  prompt-policy phrase assertions and one Windows TTY path-fragment assertion.
  Compilation/import checks and `git diff --check` passed. No live model
  inference ran.

- 2026-09-08: Added a conservative runtime no-progress nudge. Squid Core now
  provides a small Hook that recognizes three consecutive failed Tool actions
  only when Tool name, complete JSON arguments, and scalar error category are
  identical. Success or any material fingerprint/category change resets the
  streak; injection also resets it, requiring a fresh threshold before another
  nudge. Code Squid owns and wires the short recovery wording, delivered as
  transient `before_model_turn` context without persisting it or changing,
  blocking, or retrying Tool calls. Added focused detector, Hook-loop, and
  application-wiring regressions. Focused Hook, runner-wiring, and Mod tests
  passed (49 tests); compilation of `squid_core`, `code_squid`, and `tests`,
  plus `git diff --check`, passed. The full suite passed 976 tests and retained
  five pre-existing failures: four stale prompt-policy phrase assertions and
  one Windows TTY path-fragment assertion. No live model inference ran.

- 2026-09-08: Updated Code Squid's application-owned coding prompt to recover
  directly from `apply_patch` diagnostics. Non-unique matches now steer the
  model toward returned locations and context, while missing matches steer it
  toward exact closest-match content; both paths re-read only when diagnostics
  are insufficient and require a meaningfully corrected exact `old_text`.
  Added concise baseline guidance to act on exact corrective Tool information
  and abandon repeated no-progress approaches, plus Tool discipline against
  shell editing workarounds when shell behavior is not genuinely required.
  Mutation semantics, runtime repetition handling, the one-Tool turn contract,
  finalization, and generic Squid Core policy remain unchanged. Three focused
  prompt regressions passed. The full suite passed 967 tests with the same four
  pre-existing prompt-policy assertion failures and one pre-existing Windows
  TTY path-fragment failure documented by preceding work. Production prompt
  compilation, affected imports, and `git diff --check` passed. No live model
  inference ran.

- 2026-09-08: Moved provider, model, safety, streaming, compaction, and display
  preferences from workspace-local ownership to the Code Squid application
  home (`~/.code-squid/settings.json`, or `<CODE_SQUID_HOME>/settings.json`).
  `code_squid.app_paths` remains the canonical path-policy owner, while
  `squid_core` continues to receive only effective runtime settings. When the
  global file is absent, settings loading adopts the current workspace's
  legacy `.code-squid/settings.json` best-effort without deleting it; an
  existing global file is authoritative and workspaces are never merged.
  Provider-scoped persistence and environment-only override precedence remain
  unchanged. Workspace rebuilds now explicitly retain application settings
  while clearing workspace-owned active-session state and rerooting session,
  undo, display, and discovery objects. Added path, migration, restart,
  workspace-switch, and slash-command write-target regressions. Focused
  settings/provider/workspace/runtime/startup coverage: 218 passed. Full suite:
  964 passed, with the same four pre-existing prompt-policy assertion failures
  and one pre-existing Windows TTY path-fragment failure documented by the
  preceding provider work. Production compilation, affected imports, and
  `git diff --check` passed. No live model inference ran.

- 2026-09-08: Scoped persisted connection settings by provider. The selected
  provider and exact model ID remain under `model`, while explicitly saved URL,
  key, and key-environment fields now live in a sparse `providers.<id>` mapping.
  Switching through slash commands or the startup picker restores that
  provider's saved connection without overwriting any other provider; absent
  fields still use `ProviderProfile` defaults. Legacy flat model connection
  fields load as the saved provider's values without an eager disk rewrite and
  migrate naturally on the next provider selection or connection edit.
  Environment precedence, model selection, disconnected-provider selection,
  readiness, discovery, inference enforcement, and the Core boundary remain
  unchanged. Added settings, CLI, and startup regressions. Focused verification:
  129 passed. Full suite: 961 passed, with the same four pre-existing prompt-
  policy assertion failures and one pre-existing Windows TTY path-fragment
  failure documented by the preceding provider work. Production compilation,
  affected imports, and `git diff --check` passed. No live model inference ran.

- 2026-09-08: Separated provider selection from provider readiness. The shared
  `select_provider` operation now persists the requested provider and applies
  its defaults before probing/reporting readiness, allowing both `/provider
  use` and the startup picker to select a disconnected provider for subsequent
  URL or key configuration. Readiness and inference credential enforcement
  remain unchanged, and model discovery remains advisory during selection.
  Added regressions for disconnected slash-command and startup selection,
  follow-up URL configuration/status, preserved connected behavior, and
  unusable inference configuration. Focused provider/runtime/startup coverage
  passed 147 tests. The full suite passed 955 tests with the four pre-existing
  prompt-policy assertion failures and one pre-existing Windows TTY path-
  fragment failure documented by the preceding provider work. Production
  compilation, affected imports, and `git diff --check` passed. No live model
  inference ran.

- 2026-09-08: Improved built-in Tool reliability without changing mutation or
  runtime policy. The four built-in schemas now describe only mechanical
  purpose and constraints; narration guidance remains in Agent prompts.
  `apply_patch` still requires exactly one UTF-8 text match and never
  fuzzy-edits, but missing matches can now report one conservative same-sized
  closest line window and duplicate matches report at most three bounded
  contexts with exact line ranges. Successful patches report affected line
  ranges and retain `chars_before` / `chars_after` for compatibility.
  ToolExecutor undo ownership, AgentLoop behavior, and approval semantics are
  unchanged. Focused built-in Tool, apply-patch, ToolExecutor/undo, and Tool
  result verification passed 45 tests. The full suite passed 952 tests with
  the four pre-existing prompt-policy assertion failures and one pre-existing
  Windows TTY path-fragment failure documented by the preceding setup work.
  Tool-package compilation, affected import smoke checks, and
  `git diff --check` passed.

- 2026-09-08: Separated model discovery capability from inference readiness.
  OpenRouter model discovery now uses its public unauthenticated `GET /models`
  catalog, including in the startup Model menu when no API key is configured.
  OpenRouter remains `not connected` without a key, and normal inference
  construction plus direct inference use continue to reject keyless
  configuration. Shared discovery no longer calls `is_ready()` first; each
  provider's `list_models()` now determines whether its catalog is reachable.
  Added regressions for request headers, keyless readiness, startup display,
  and inference credential enforcement. Focused provider/startup/runtime/Core
  verification passed 119 tests. The full suite passed 942 tests with the four
  pre-existing prompt-policy assertion failures and one pre-existing Windows
  TTY path-fragment failure documented below. Production compilation, affected
  imports, and `git diff --check` passed. No live model inference ran.

- 2026-09-08: Fixed startup Provider selection corrupting the live
  prompt-toolkit scene. The startup menu now applies the shared provider result
  and suppresses its optional informational explanation because the menu has no
  renderer-owned message surface; `/provider use` still prints that explanation
  outside startup rendering. Audited every startup selection branch and found
  no other direct stdout writes. Added regression coverage for both explanation
  outcomes, retained focus/navigation, provider/model state, and the unchanged
  slash-command output behavior. Focused verification: 57 passed. Full suite:
  939 passed, with the same four prompt-policy assertion failures and one
  Windows TTY path-fragment failure already documented by the preceding setup
  pass. Compilation, affected imports, and `git diff --check` passed.

- 2026-09-08: Implemented the Provider + Model setup pass. Added
  `code_squid/provider_setup.py` as the non-UI application seam for five
  friendly provider identities, connection defaults, readiness/discovery
  orchestration, and shared provider/model mutations used by startup and slash
  commands. Core retains inference transport ownership: LM Studio, Squid
  Models, OpenRouter, and generic OpenAI Compatible use chat completions;
  Ollama remains native. Setup probes use LM Studio `/api/v1/models`, Squid
  Models `/health` plus `/v1/models`, Ollama `/api/tags`, and authenticated
  OpenRouter/generic `/models`. Startup menus now show friendly names and only
  `ready`/`not connected`, discover real IDs in a seven-row viewport, preserve
  settings on failure, and persist exact model selections. Added the complete
  generic `/provider` family, safe key handling, env-override diagnostics, and
  two-ID Squid Models inference regression coverage. Focused verification: 230
  passed. Full suite: 938 passed, 5 failed: the four pre-existing prompt-policy
  assertion failures and one pre-existing Windows TTY path-fragment failure.
  Compilation, import smoke checks, and `git diff --check` passed. Desktop was
  audited, but migration is deferred: its settings import precedes the optional
  Core bridge, and its managed local lifecycle still embeds fixed-model
  translation, making a safe move span bootstrap, packaging, UI option shapes,
  and lifecycle tests. The shared module is UI-neutral and is the intended
  migration target.

- 2026-09-07: Increased the shared startup submenu viewport to seven visible
  entries. Workspace now shows seven recent paths, and Session shows pinned
  `New session` plus six saved sessions before scrolling. Fixed heading,
  option-start, and footer rows, keyboard behavior, panel dimensions, and
  discovery limits are unchanged. Focused startup-menu/UI verification passed
  71 tests; compilation and `git diff --check` also passed.

- 2026-09-07: Unified the six selectable startup submenus around one fixed
  panel layout. Provider, Model, Safety, Mod, Workspace, and `Sessions for this
  workspace` now share a centered top heading, an upper-left option anchor, a
  bounded non-recentering viewport, and a fixed centered
  `↑↓   Enter select   Esc back` footer. Workspace disambiguation and
  truncation, Session title/age fitting, existing scrolling behavior, keyboard
  actions, panel dimensions, and startup lifecycle remain unchanged. The
  startup-menu suite passed 29 tests. Broader startup/UI verification passed
  238 tests with the previously documented unrelated Windows TTY path-fragment
  assertion failure in `test_terminal.py`. Compilation, affected imports, and
  `git diff --check` passed. No live model inference ran.

- 2026-09-07: Simplified workspace selection by making the startup Workspace
  submenu recent-only and removing `Choose folder...` plus its boxed path
  prompt. Added `/workspace` status and `/workspace <path>` switching with
  quoted-space and `~` support, existing-directory validation, and recent-list
  persistence. Command parsing returns a switch target to the outer prompt
  loop; both command and startup selections use the same workspace-runtime
  reconstruction seam, which reloads settings/display/menu/discovery state and
  clears the active session on a real root change. `/cwd` remains compatible.
  Focused workspace/CLI/startup/main verification passed 108 tests. Broader
  console verification passed 310 tests with one unrelated TTY path-fragment
  assertion failure in `test_terminal.py`. The full suite passed 918 tests with
  that same unrelated failure plus the four pre-existing prompt-policy
  assertion failures in `test_coding_agent.py` and `test_core_agent.py` already
  documented below. Production compilation, affected imports, and
  `git diff --check` passed. No live model inference ran.

- 2026-09-07: Made the startup Workspace row interactive using the existing
  fixed startup panel and single-Application handoff lifecycle. The submenu
  shows a scrolling five-row view over up to ten recent absolute paths plus
  `Choose folder...`; basename collisions gain a compact parent hint. Recent
  paths persist newest-first as a deduplicated JSON list at the configured
  Code Squid home's `recent-workspaces.json`. Folder input uses the ordinary
  prompt after startup terminal ownership is released, expands `~`, resolves
  the path, and quietly keeps the current root on invalid input. Valid
  selection returns a distinct startup sentinel to `prompt_loop.py`, which
  reconstructs workspace settings, display/header, menu, and discovery state
  around the new root and clears any active session on a real root change.
  Core globals and storage formats are unchanged. Focused startup/workspace,
  prompt-input, app-path, interactive-session, and package-boundary
  verification: 95 passed; broader console verification: 141 passed. The full
  suite passed 917 tests and retained four unrelated prompt-policy assertion
  failures already documented below. Compilation, affected imports, and
  `git diff --check` passed. No live model inference ran.

- 2026-09-07: Polished saved-session startup handoff without adding another
  renderer or fade. Saved-session selection now conditionally removes its
  unused empty composer from the existing StartupApplication, then the CLI
  joins that renderer's natural binary-rain fade before printing the previous-
  session notice or opening PromptSession. The established force-and-join seam
  remains unchanged for ordinary writers that need immediate terminal
  ownership. Focused startup/menu/runtime coverage passed (66 tests); the
  broader console/UI suite passed (363 tests). The full suite reached 911
  passed with the same four unrelated prompt-policy assertion failures in
  `test_coding_agent.py` and `test_core_agent.py` recorded below. Production
  compilation, affected imports, and `git diff --check` passed. No live model
  inference ran.

- 2026-09-07: Moved the saved-session notice from the next task-submission
  boundary to the startup Session picker's activation boundary. A successful
  saved-session selection now returns a distinct result from the existing
  temporary startup Application; the CLI retires and joins that renderer,
  prints the one-time notice, and opens the ordinary composer before the user
  submits another task. `StartupMenu` still owns selection state only, and
  session resolution, transcript loading, and follow-up construction are
  unchanged. Restyled the notice as one fully dim, normally detail-indented
  line, with a local 40-character title limit that preserves the compact age
  and optional cheap metadata message count. `New session`, launch-time resume,
  and later follow-ups remain silent. Focused startup/menu/input/runtime/display
  coverage passed (236 tests). The full suite reached 910 passed with the same
  four unrelated prompt-policy assertion failures in `test_coding_agent.py`
  and `test_core_agent.py` recorded by the preceding Session-picker work.
  Production compilation, affected imports, and `git diff --check` passed. No
  live model inference ran.

- 2026-09-07: Added one quiet CLI status notice for a saved session explicitly
  selected through the startup Session picker. After the startup scene retires,
  the display prints two neutral dim lines with the shared normalized title and
  compact age, then consumes the selected metadata so subsequent follow-ups do
  not repeat it. `New session` and sessions active before picker interaction
  remain silent. The notice reuses the already-read workspace metadata record;
  current persisted metadata has no message count, so normal output omits it
  and no transcript is opened or scanned. A count is rendered only when an
  existing metadata record already supplies a valid `message_count`. Session
  resolution, transcript loading, and follow-up construction are unchanged.
  Focused startup/session/terminal coverage passed (210 tests), and the broader
  relevant CLI suite passed (296 tests). The full suite reached 908 passed with
  the same four unrelated prompt-policy assertion failures in
  `test_coding_agent.py` and `test_core_agent.py` recorded by the preceding
  Session-picker work. Production compilation, affected imports, and
  `git diff --check` passed. No live model inference ran.

- 2026-09-07: Normalized saved task whitespace at the startup menu's shared
  session-title seam so multiline tasks remain one-line presentation data in
  both the recent-session submenu and the main Session row. Runs of whitespace,
  including newlines and tabs, now collapse to one space before truncation;
  empty results still use `Untitled session`. Panel geometry, scrolling,
  timestamp alignment, and prompt_toolkit lifecycle behavior are unchanged.
  Added focused coverage for normalization, truncation, age visibility and
  alignment, fixed panel height, and unchanged single-line titles. The focused
  startup-menu suite passed (21 tests); related CLI runtime, prompt-input,
  terminal, and session UI suites passed (213 tests). Compilation, an affected
  import smoke check, and `git diff --check` passed. No live model inference
  ran.

- 2026-09-07: Added a Session row and recent-session picker to the existing
  fixed startup panel and its sole temporary prompt_toolkit Application. The
  submenu keeps `New session` first, shows five of the newest 20 workspace
  sessions at once, scrolls with the existing arrow-key state, truncates task
  titles ahead of a stable compact age column, commits with Enter, and backs
  out without mutation with Esc. Discovery reuses Core's presentation-neutral
  `list_sessions` index through CLI-owned `discover_recent_sessions`; selection
  reuses the `/resume` path's `resolve_session_id`; transcript loading and
  resumed-run construction remain exclusively in the existing follow-up
  runner. Main-menu focus, panel geometry, rain, composer, mouse behavior, and
  persistence formats are unchanged. Focused startup/menu/session/CLI/header/
  composer/display coverage passed (344 tests). The full suite reached 903
  passed with four unrelated prompt-policy assertion failures in
  `test_coding_agent.py` and `test_core_agent.py`; this patch changes no prompt
  or agent-policy files. Production compilation, affected imports, and
  `git diff --check` passed. No live model inference ran.

- 2026-09-07: Improved the existing CLI `tool_preparing` pulse without changing
  Core, providers, events, narration rendering, or completed Tool presentation.
  `TerminalSpinner.start()` now accepts an optional active label and repaints
  its already-owned line when that label changes; its four pulse frames and
  0.17-second interval remain unchanged. The CLI maps `read_file` to
  `Reading...`, `write_file` to `Writing...`, `apply_patch` to `Patching...`,
  and `run_command` to `Running...`, with `Using tool...` for custom or unknown
  tools. Ordinary work remains `Thinking...`, existing Tool/run boundaries
  still stop the pulse, and debug mode retains its static diagnostics. Focused
  console/UI tests passed (213), the full suite passed (901), production
  compilation passed, and `git diff --check` passed. No live model inference
  ran.

- 2026-09-06: Updated the CLI for Core's narration-phase transition. A live
  streamed narration panel now exposes one narrow `retain_live_frame()`
  lifecycle operation: `tool_preparing` uses it to synchronously stop the
  prompt_toolkit Application while preserving its visible frame as scrollback,
  then immediately starts the existing Thinking pulse. The authoritative
  narration callback consumes retained state without reprinting text or
  stopping/restarting Thinking; `tool_started` still stops the pulse. Static,
  debug, redirected-output, rejection, finalization, failure, cancellation,
  and ordinary commit behavior remain on their existing paths. Focused
  console/UI tests passed (202), the full suite passed (874), production
  compilation and import smoke checks passed, and `git diff --check` passed.
  No live model inference ran.

- 2026-09-06: Added an explicit semantic `phase` to Core assistant-text
  events: `assistant_message_started`, `assistant_delta`, and
  `assistant_message` now carry `narration`, while `final_message` carries
  `final`. This is an additive observer-protocol change only; the existing
  model call, event families, payload fields, and `tool_preparing` ordering and
  behavior remain unchanged. The focused agent-loop suite passed (69), the full
  suite passed (872), production compilation and a fresh 82-module import walk
  passed, and `git diff --check` passed. No live model inference ran.

- 2026-09-06: Corrected the presentation regressions in the thinking-pulse
  patch without changing its four frames or 0.17-second interval. Normal
  thinking is terminal-neutral again; Mod accents remain limited to narration
  and report squid markers, with the existing dim neutral panel borders left
  unchanged. Removed the CLI's `_tool_preparing_pending` state and stopped
  presenting `tool_preparing` as a pulse: providers emit that parse-time event
  before the authoritative `assistant_message` and `tool_started`, so deferring
  it until narration committed caused the observed last-moment flash. Added
  coverage for the final static and prompt_toolkit output paths, proving every
  emitted U+1F991 remains directly followed by U+FE0E and the glyph accent is
  immediately reset before neutral narration/report text. Saved-session
  headings now reuse the canonical text-presentation constant instead of
  embedding color-emoji literals. Focused presentation/event coverage passed
  (256), the full suite passed (872), production compilation and a fresh
  31-module import walk passed, and `git diff --check` passed. No Core or
  renderer changes were made, and no live model inference ran.

- 2026-09-06: Replaced the normal thinking squid/Braille spinner with one
  four-frame `\u00b7`/`\u2022`/`\u25cf`/`\u2022` `Thinking...` pulse. The existing
  spinner thread and terminal lifecycle remain unchanged, while the complete
  pulse line now resolves and applies the current Mod accent with an immediate
  ANSI reset; debug thinking is static plain text. The CLI's already-wired
  `tool_preparing` event now restarts the same pulse after streamed narration
  settles, using one deferred display flag when provider event order announces
  the Tool before the authoritative assistant message. Tool, visible-output,
  rejection, failure, cancellation, interruption, and finalization boundaries
  clear the pending/running pulse. Narration and report retain the canonical
  U+1F991 U+FE0E squid marker and live accent resolution. No Core, Tool/error
  icon, startup, composer, approval, or streaming-renderer change was made.
  Focused spinner/narration/display coverage passed (181), focused runtime
  event/provider coverage passed (132), and the full suite passed (869).
  Production `code_squid` compilation and a fresh 31-module import walk passed,
  as did `git diff --check`. Brightness modulation and the broader Tool/error
  icon cleanup remain intentionally deferred; no live model inference ran.

- 2026-09-05: Let the existing startup-rain drops continue falling during the
  global fade. Fade advancement now uses a non-resetting movement path, so no
  replacement drops enter after submit and off-screen drops are not recycled;
  the final step still clears the entire remaining population atomically. The
  style progression and startup Application lifecycle are unchanged. Focused
  rain/startup/composer/display/narration coverage passed (216), and the full
  suite passed (858). Production compileall and a fresh 82-module import walk
  passed, as did `git diff --check`. No live model inference was run.

- 2026-09-05: Corrected the startup-rain fade's visual model without changing
  its non-blocking Application lifecycle. Fade frames now keep every existing
  drop frozen and apply one global prompt_toolkit intensity step to all rain;
  the last faint frame retains the complete rain geometry and the next frame
  clears it atomically. Title, startup panel, and submitted composer styling
  remain fixed. Focused rain/startup/composer coverage passed (197), focused
  narration/startup coverage passed (41), and the full suite passed (856).
  Production compileall and a fresh 82-module import walk passed, as did
  `git diff --check`. No live model inference was run.

- 2026-09-05: Added a short non-blocking startup-rain exit fade without
  restoring post-submit rain continuation. Enter now freezes and makes the
  composer read-only, returns its task immediately, and lets the one existing
  nonfullscreen prompt_toolkit Application remove its existing drops across
  eight frames (a nominal 350 ms: one immediate frame plus seven 50 ms refresh
  intervals). The clean frame retains the title, startup panel, and submitted
  composer with zero rain cells, then exits into normal scrollback. A shared
  CLI ownership seam forces that clean render and synchronously joins the
  startup renderer before early narration, Tool/debug output, approvals,
  failures, interruptions, direct commands, or cleanup can write. No Core,
  alternate-screen, stdout-interception, custom ANSI repaint, or second
  startup-renderer change was made. Focused startup/rain/composer/narration/
  display tests passed (214), with the submit lifecycle also passing three
  consecutive focused runs. The full suite passed (856). Production compileall
  and a fresh 84-module import walk passed, and `git diff --check` passed. No
  live model inference was run.

- 2026-09-05: Simplified the final CLI completion panel's file summary from the
  always-present `Session files` Read/Written split to an optional, glyph-free
  `Changed files` section listing only paths recorded in `files_written`. Runs
  without written files now show only the existing report content. Removed the
  obsolete folder-glyph constant and its special display-width correction;
  streaming narration and panel styling are unchanged. Focused TerminalDisplay
  coverage passed (143); broader CLI/UI coverage passed (154); and the full
  suite passed (849). Production compilation and an 82-module fresh import walk
  passed, and `git diff --check` passed. No live model inference was run.

- 2026-09-05: Replaced streamed narration's Code Squid-owned ANSI row clearing
  and cursor movement with a temporary nonfullscreen prompt_toolkit
  `Application` and `FormattedTextControl`. The renderer starts only on the
  first visible delta, reads each layout from the real terminal `Output`,
  hides its cursor, invalidates coherently as content grows or the viewport
  changes, and uses a private pipe rather than consuming terminal input.
  Accepted narration exits with its authoritative final frame retained in
  ordinary scrollback; rejection, final report, interruption, failure, and
  loop cleanup erase the provisional frame and synchronously release renderer
  ownership before static or Tool output proceeds. The existing Core events,
  fresh/resumed `on_event` wiring, persistence, spinner handoff, and debug and
  redirected static fallbacks are unchanged. Focused narration/composer/
  startup/terminal coverage passed (207); broader CLI/UI coverage passed
  (307); and the full suite passed (849). Production compilation and an
  82-module fresh import walk passed, the obsolete raw repaint constants are
  absent, and `git diff --check` passed. A real PTY utility was not available
  in this Windows environment, so target-terminal resize/flashing confirmation
  remains manual; no live model inference was run.

- 2026-09-05: Added CLI-owned streamed assistant narration using Core's
  existing event callback without changing Core, providers, or persistence.
  `session_runner.py` now passes the display event handler into fresh and
  resumed runs. A small `StreamingNarration` renderer opens without drawing,
  appends deltas into one TTY panel, repaints only the rows it owns, and settles
  authoritative `assistant_message` text in place. Rejected and final replies,
  failures, cancellation completion, and KeyboardInterrupt presentation erase
  provisional rows and clear state; final text continues through the existing
  report path. Spinner ownership ends before the first visible delta, while
  debug and redirected output retain their prior static behavior. Focused
  CLI/UI/Core-event coverage passed (284), and the full suite passed (845).
  Compilation, import smoke, `git diff --check`, and a real PTY smoke covering
  growth, wrapping, settlement, following Tool output, and interruption passed.
  Interactive resize and provider-backed rejection/final streaming remain for
  manual confirmation in the target terminal; no live model inference ran.

- 2026-09-05: Repaired boxed composer growth after Windows Terminal resize
  testing exposed corruption from a startup Output adapter that reported a
  canvas taller than the real terminal, disabled CPR, and overrode physical
  rows below the cursor. Startup now passes prompt_toolkit the real Output
  unchanged. A shared `composer_layout.py` policy still grows startup and
  follow-up composers from 2 through 14 visible content rows using
  prompt_toolkit's cell-aware preferred-height calculation, but each caller
  supplies a separate cap derived from its real viewport. Startup subtracts
  its currently visible scene, separator, and two frame rows; constrained
  terminals clip the decorative scene from the bottom to retain the ordinary
  two-row content minimum. BufferControl owns internal scrolling and retains
  the complete input. PageUp/PageDown use prompt_toolkit page navigation,
  Ctrl+Up/Ctrl+Down use its half-page navigation, Ctrl+Home/Ctrl+End keep the
  standard buffer-boundary behavior, and input windows use one-row top/bottom
  scroll offsets. No assistant/run renderer or rain-during-run behavior
  changed. Focused prompt/input, startup-menu, binary-header, and terminal
  tests passed (190); selected interactive `/new`/startup lifecycle tests
  passed (3). Targeted Python compilation, import smoke, and
  `git diff --check` passed. Pipe-input/rendered-screen coverage exercised
  short and long input, both height caps, fast navigation, resize shrink and
  recovery, deletion, submission, Ctrl+C, and complete Buffer retention. A
  real Windows PTY smoke was not available because this environment has no
  winpty, pywinpty, or pexpect package; Windows Terminal resize behavior still
  requires manual confirmation.

- 2026-09-04: Replaced the startup's competing prompt_toolkit/ANSI-renderer
  architecture with one temporary nonfullscreen `StartupApplication`. The old
  split ownership let `BinaryRainHeader` move the physical cursor while
  PromptSession retained a different logical screen, which caused wrapping and
  shrink instability, frozen rain, stale borders, and `Window too small...`
  replacing large input. StartupApplication now owns rain, title, menu panel,
  and one multiline BufferControl until Enter or Ctrl+C exits it completely;
  ordinary run output and follow-up prompts remain print/scrollback based.
  BinaryRainHeader is now an I/O-free rain state/composition model. Removed its
  animator thread, anchored cursor writes, reanchor and live-size logic, prompt
  row/height/column state, redraw callback, and the production dependency on
  `renderer._last_screen`; removed the corresponding geometry publication from
  `prompt_input.py`. The Application refresh interval advances rain through the
  same renderer during typing, wrapping, scrolling, paste, and menu navigation.
  Its bounded input Window scrolls while retaining the complete Buffer, and
  constrained layouts contract rather than invoking prompt_toolkit's fallback.
  `/new` constructs a fresh Application and resets drop state. Focused startup,
  input, menu, display, CLI, and boundary tests: 261 passed; full suite: 828
  passed. Python compilation, a 67-module production import smoke, and
  `git diff --check` passed. A real 80x40 ConPTY smoke sampled 12 distinct rain
  frames, exercised menu navigation, slow typing, natural wrapping, a large
  bracketed paste, heavy deletion, CSI-u Shift+Enter/Alt+Enter, clean Ctrl+C,
  post-submit print output via `/help`, and a fresh `/new` scene. It never showed
  `Window too small...`. The ConPTY harness was temporary and no model inference
  ran. A visible Windows Terminal remains the final manual visual authority.

- 2026-09-04: Fixed the startup rain/boxed-composer rendering seam. Confirmed
  that prompt_toolkit's `run_in_terminal` contract erased, reset, and fully
  repainted the framed prompt for every rain frame, causing idle flashing; live
  frames now run directly on the PromptSession event loop and restore the
  renderer-owned cursor without prompt teardown. After each completed prompt
  render, the input seam publishes prompt_toolkit's actual cursor row and the
  visible bottom-border height to `BinaryRainHeader`. Cursor-relative redraw
  offsets update on wrapping/newlines/deletion and are also the sole live-fit
  bound: rows below the current cursor are never traversed by the writer. This
  prevents ordinary 27-30-row terminal viewports from falsely invalidating the
  only animation callback.
  The first shrink implementation's self-referential exact-height outer split
  and explicit spacer were removed after real-terminal testing showed that they
  separated the BufferControl's allocation from the visible frame, reducing
  input to a one-cell viewport and placing its cursor outside the box. The
  composer is again one natural fixed-width split. Only its middle input row is
  capped from the normal PromptSession input container's own preferred height;
  that container keeps its full 58-cell interior width while retained cleanup
  rows stay below the bottom border and the visible frame still shrinks. Menu key actions now
  explicitly wake that same worker for immediate shared-panel repaint. Windows
  Terminal's legacy and CSI-u Shift+Enter (modifier 2) and Alt+Enter (modifier
  3) encodings normalize to the multiline Ctrl+J binding. The single rain
  worker remains active during composer growth and menu use; no fallback,
  transcript renderer, pinned region, or stdout interception was added.
  Focused prompt/header/menu/terminal/runtime-command/help tests: 285 passed;
  full suite: 853 passed. Production compilation, an 81-module import walk,
  and `git diff --check` passed. A forced-ANSI 80x40 ConPTY startup emitted 392
  distinct live frames while exercising immediate menu repaint, wrapped input,
  both CSI-u modified-Enter sequences, shrinkage, focus return, and clean
  cancellation. The harness does not advertise ANSI support without forcing
  that capability, and it is not a visible Windows Terminal window, so final
  Windows Terminal visual confirmation remains manual. The completed-screen
  read is the only remaining private prompt_toolkit dependency; the prior
  custom attribute on `session.app` was removed. No model inference was run.

- 2026-09-04: Added a transient boxed task composer without changing terminal
  ownership. The existing non-fullscreen `PromptSession` now renders normal
  task input in a dynamically tall rounded frame using the same canonical
  61-cell width as narration and completion panels, two-cell left padding, a
  one-cell right gutter, cell-aware prompt_toolkit wrapping, and continuation
  alignment beneath the `› ` marker. Menu focus substitutes equal-width spaces
  for the marker, preserving input position. Approval input remains unboxed.
  Updated startup viewport/redraw geometry for the framed prompt while keeping
  its one animator and ordinary scrollback lifecycle. Fixed the completion
  edge defect at `🗂️ Session files` by reconciling that exact variation-selector
  sequence with the target terminal's one-cell rendering during ANSI/OSC-aware
  panel measurement. Added rendered-screen composer geometry and styled,
  hyperlinked completion-panel regressions. Focused console tests: 259 passed;
  full suite: 842 passed. Production compilation/import checks and
  `git diff --check` passed. A real xterm PTY smoke verified startup, fixed and
  growing composer geometry, long wrapping, Alt+Enter, menu marker hide/restore,
  submitted/cancelled composer scrollback, `/exit` cleanup, and aligned styled
  Report/Session files output with a wide path and OSC hyperlink. No model
  inference was run.

- 2026-09-04: Replaced divider-heavy normal-run presentation with fixed-width
  static panels while preserving ordinary print-based scrollback and the
  existing prompt-toolkit composer lifecycle. One canonical 61-column width
  now governs every narration panel and the shared Report/Session files
  completion panel; narration, report text, and long file labels wrap within
  that geometry. Tool results, approvals, warnings, and failure/interruption
  statuses remain outside panels. Removed standalone run, report, and file
  dividers, including the direct-final duplicate structure. Borders use the
  same dim/default treatment everywhere, while the text-presentation squid
  alone retains the live Mod accent and immediate foreground reset. Focused
  terminal/composer/spinner tests: 155 passed; full suite: 837 passed.
  Production compilation/import checks and `git diff --check` passed. A real
  PTY smoke verified the unchanged startup scene, plain composer, `/new`,
  `/exit`, and clean terminal teardown; no live model inference or
  terminal-ownership refactor was performed.

- 2026-09-04: Completed the small normal-CLI presentation cleanup. Thinking,
  narration, report, and spinner markers now use the squid's text-presentation
  sequence (`U+1F991 U+FE0E`), allowing the existing semantic Mod accent ANSI
  foreground to remain visible instead of being overridden by a color-emoji
  font; the reset still occurs immediately after the glyph. Restored the plain
  61-character run-start divider with normal vertical spacing and routed it,
  the report divider, and the Session files divider through one dim/default
  styling helper. No label, curve, success line, composer change, or terminal
  lifecycle change was added. Focused terminal/spinner tests: 144 passed; full
  suite: 832 passed. Production compilation/import checks and
  `git diff --check` passed. A real PTY smoke covered startup rendering, menu
  focus entry/Escape, clean `/exit`, the exact run/thinking/narration/report
  and Session files output paths, and a live purple-to-red accent change
  without model inference.

- 2026-09-04: Applied a focused normal-CLI visual polish without changing
  terminal ownership. The existing single `BinaryRainHeader` scene now owns
  five rain rows below its menu panel while still ending before the ordinary
  prompt rows. The composer and startup menu remain terminal-native; a live
  prompt fragment hides `›` whenever the main menu or a submenu owns focus and
  restores it on return. Code Squid presentation now maps semantic Mod accent
  names through the exact product palette and applies the current selection
  only to visible squid glyphs in thinking, narration, and report lines, with
  an immediate ANSI reset. Run-start chrome and the successful `Done!` line
  were removed; failed/interrupted statuses, neutral report dividers, reports,
  and session files remain. No persistent composer, managed viewport, stdout
  interception, or second animation worker was introduced. Focused console
  tests: 245 passed. Full suite: 821 passed. Production compilation/import
  checks and `git diff --check` passed. A real PTY startup plus Up, Esc, and
  `/exit` smoke completed with the taller scene and clean terminal teardown;
  no model inference was run.

- 2026-09-04: Polished the keyboard startup surface after manual testing while
  preserving the existing main-menu panel. Composer Up now always enters on
  Workspace after either menu boundary; submenu titles, marker-aware option
  columns, and footers center as coherent blocks; and the menu Escape binding
  is eager so prompt-toolkit does not wait on a possible Alt sequence. Removed
  the visible divider and its physical geometry row, leaving three rain rows
  beneath the panel. Made the startup scene explicitly session-scoped:
  submitting the first prompt retires its sole worker and later prompts are
  composer-only, while `/new` starts one fresh scene with current runtime and
  specialization state. Focused startup/menu/input/display/CLI tests: 245
  passed. Full suite: 813 passed. Production compilation/import checks and
  `git diff --check` passed. Interactive visual smoke was intentionally left
  for a human-controlled terminal.

- 2026-09-04: Made the composed startup panel keyboard-interactive without
  turning the CLI into a fullscreen TUI. Up from an empty prompt focuses a
  remembered main-menu row; arrows navigate, Enter replaces the same fixed
  panel rectangle with Provider, Model, Safety, Mod, or read-only Workspace
  content, and Esc backs out. Prompt text keeps normal multiline arrow
  behavior. Provider/model/safety persistence and Mod/Skill exclusion now have
  small shared operations used by slash commands and the menu. Provider and
  Mod options use their canonical discovery sources. Model discovery consults
  only the selected provider adapter's optional capability and otherwise shows
  the `/model <name>` fallback; it runs on submenu entry, never during rain
  rendering. The existing header worker renders all menu states, pauses around
  activation/discovery, and resumes without creating another worker. Added
  focused deterministic menu/input/rendering/persistence coverage and updated
  `/help`. No mouse handling, workspace mutation, composer redesign, or model
  inference was added. Focused console/menu tests: 91 passed. Full suite: 807
  passed. Production compilation/import checks and `git diff --check` passed.
  A real PTY launch preserved the initial scene and completed an Up, Down,
  Enter, Esc, Esc, `/exit` keyboard sequence with clean process teardown.
- 2026-09-04: Polished the composed startup scene without compacting its menu.
  The title/panel gap is now an explicit two-row layout constant, while the
  five-item panel retains all six intentional blank interior rows. Initial rain
  heads are distributed through the composed rain height so the first frame is
  visibly populated above, beside, and below the panel; later drops still reset
  above the scene with independently varied speeds and sparse trails. When the
  complete scene, separator, prompt identity, and input row fit, startup first
  reserves that exact draw region and returns the cursor to its top, preserving
  ordinary scrollback while preventing the scene from scrolling itself out of
  view. Too-short terminals keep the safe sequential static fallback. Focused
  header/banner/terminal tests: 151 passed. Full suite: 796 passed. Production
  compilation and import checks plus `git diff --check` passed. An 80x30
  interactive PTY launch confirmed that the title, complete panel, lower rain
  region, divider, identity, and composer remain in the initial viewport and
  that `/exit` is clean. Deterministic first-frame rendering confirmed populated
  rain in every allowed region. No model inference was run.
- 2026-09-04: Replaced the separate binary header and loose startup metadata
  with one composed startup scene. A small `header_layout.py` module now owns
  the title, centered compact panel, rain exclusion rectangle, three rows of
  rain below the panel, safe width, and final divider geometry. The animator
  renders rain only in layout-approved cells, then composes the fixed title,
  panel, and DIM divider as one frame. The panel contains Provider, Model,
  Safety, Mod, and concise Workspace state; a directly selected standalone
  Skill adds one optional row, and interactive Mod/Skill changes update later
  re-anchored scenes. Composer behavior and startup-row interaction remain
  unchanged. Focused console/header/banner/main/runtime-command tests: 217
  passed. Full suite: 790 passed. Production compilation and import checks plus
  `git diff --check` passed. An interactive PTY launch confirmed the centered
  title and panel, concise workspace, divider/prompt ordering, stable-size
  redraw, and clean `/exit`; deterministic composition also confirmed rain on
  both sides of and below the fully reserved panel rectangle. No model
  inference was run.
- 2026-09-04: Made live binary-header redraws resize-safe. The animator now
  invalidates and freezes its relative prompt anchor when either terminal
  dimension changes, rechecks size immediately before cursor movement, and
  waits for the next clean prompt boundary to rebuild and resume. Too-small
  terminals remain paused, recovery reuses the existing worker, and teardown
  remains idempotent. Live offsets now use the startup panel's rendered
  physical height so blank spacing and wrapped workspace paths are accounted
  for. The dim startup divider follows the header's safe current-width-minus-one
  rule, and blank lines separate Provider, Model, Safety, optional Skill, and
  Workspace details. Focused header/terminal/main/runtime-command suite: 209
  passed. Full suite: 782 passed. Production compilation/import checks and
  `git diff --check` passed. An interactive launch confirmed the full-width
  dim divider, spaced startup fields, usable `/help`, prompt return, and clean
  `/exit`; physical resize smoke remains deferred because this execution
  channel does not provide a user-driven resizable terminal. No model
  inference was run.
- 2026-09-03: Extended the binary-rain header from a bounded startup animation
  to a single lifecycle-owned idle animator. `TerminalDisplay` now starts,
  pauses, and stops it at presentation boundaries; prompt input sends frames
  through prompt_toolkit's `run_in_terminal` seam with synchronous
  backpressure, and shutdown joins the worker and restores the cursor. Added
  event-based coverage for idempotent start,
  pause/resume state retention, non-TTY behavior, worker teardown, prompt-safe
  resume/pause ordering, output transition pausing, prompt re-anchoring, and
  exit cleanup. Re-anchoring the same preserved state before later prompts
  prevents relative redraws from ever targeting intervening command output.
  Focused header/prompt/terminal/CLI suite: 207 passed. Full suite: 775
  passed. Production packages compiled, affected imports loaded, and
  `git diff --check` passed. Normal and forced-ANSI PTY smokes covered static
  fallback, live typing, `/help`, prompt return, `/exit`, and cursor cleanup;
  no model inference was run.
- 2026-09-03: Wired the bounded binary-rain header into normal interactive CLI
  startup as the sole startup identity. Removed the old ASCII logo, subtitle,
  bordered startup card, and startup controls reminder; retained provider,
  model, safety, workspace, and active Skill details as plain lines beneath a
  dim divider. The prompt identity is now `@code-squid`, and `/help` owns an
  explicit Input section with Enter, Alt+Enter, and Ctrl+C guidance. Focused
  console/startup/help suite: 185 passed. Full suite: 768 passed. Production
  packages compiled, affected imports loaded, and `git diff --check` passed.
  A manual PTY launch confirmed the fallback title, plain readable startup
  details, dim divider, cleaned prompt identity, help guidance, usable prompt,
  and cursor restoration; that PTY did not offer animation support, while the
  forced-ANSI header tests cover the bounded animated path. No model inference
  was run, and no follow-up work is intentionally deferred.
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

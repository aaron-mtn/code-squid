# Provider extraction moves

The earlier staged changes are preserved. Source moved to newly initialized
sibling Git repositories, without commits or remote publication. Git history
remains in the original Code Squid repository.

- `squid_core/**` -> `../squid-core/squid_core/**` (contents preserved).
- `squid_providers/**` -> `../squid-providers/squid_providers/**`.
- Provider-local pyproject -> `../squid-providers/pyproject.toml`.
- Original Core pyproject -> `../squid-core/pyproject.toml`; app metadata now lives
  at Code Squid's root.
- `code_squid/provider_settings.py` -> provider-owned `settings.py`, using generic
  config instead of an application timeout field.
- Catalog/construction/profile/replay code -> provider-owned `catalog.py`.
- No source copies or compatibility re-exports remain in Code Squid.

## Core test ownership

- `test_action_preflight.py`
- `test_agent_loop.py`
- `test_approval.py`
- `test_atomic_json.py`
- `test_boundaries.py`
- `test_compaction.py`
- `test_container_safety.py`
- `test_context_status.py`
- `test_core_agent.py`
- `test_core_settings.py`
- `test_core_spawner.py`
- `test_core_storage_index.py`
- `test_docx_read_support.py`
- `test_epub_read_support.py`
- `test_error_log.py`
- `test_events.py`
- `test_file_readers.py`
- `test_generation.py`
- `test_hook_loader.py`
- `test_hooks.py`
- `test_image_read_support.py`
- `test_model_adapter.py`
- `test_model_transcript.py`
- `test_mods.py`
- `test_pdf_read_support.py`
- `test_platform_context.py`
- `test_session_store.py`
- `test_skills.py`
- `test_spreadsheet_read_support.py`
- `test_token_estimate.py`
- `test_tool_executor.py`
- `test_tool_result_trimming.py`
- `test_tool_results.py`
- `test_tools.py`
- `test_undo_store.py`
- `test_user_tools.py`
- `test_workspace_boundary.py`

## Application behavioral hook test ownership

The later hook extraction moved `test_no_progress_nudge.py`,
`test_too_many_reads_nudge.py`, and `test_post_verification_nudge.py` to Code
Squid, along with behavioral loop integration tests. Core retains generic hook
and lifecycle tests.

## Provider test ownership

- `test_boundaries.py`
- `test_catalog.py`
- `test_image_integration.py`
- `test_ollama_provider.py`
- `test_openai_compatible_provider.py`
- `test_provider_cancellation.py`
- `test_provider_settings.py`
- `test_vision.py`

Mixed spawner, agent, Mod, PDF and image tests were split. Core tests import no
application or transport code; Providers owns image-to-wire integration; product
prompt, persistence, compaction context and orchestration tests remain with Code
Squid. Old path-absence tests were retired in favor of import/source guards.

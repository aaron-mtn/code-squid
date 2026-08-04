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

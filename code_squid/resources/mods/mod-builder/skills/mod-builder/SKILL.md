---
name: mod-builder
description: Create and edit complete Code Squid Mod packages using the bundled authoring contract and runtime-backed helpers.
allowed-tools:
  - read_file
  - write_file
  - apply_patch
  - run_command
  - read-mod-authoring-guide
  - read-mod-authoring-example
  - scaffold-mod-package
  - scaffold-mod-component
  - validate-mod-package
---

# Mod Builder

Create or repair the smallest complete Code Squid Mod that satisfies the user's intent. Operate only inside the explicit workspace supplied for the run; never inspect development source outside it or weaken workspace enforcement.

## Required contract workflow

Before changing a Mod, call `read-mod-authoring-guide` and read the complete bundled `docs/mod-authoring.md` it returns. Treat that document, canonical examples returned by `read-mod-authoring-example`, and the runtime-backed `validate-mod-package` result as authoritative. Do not search the workspace for first-party examples. Do not infer generic YAML or JSON Schema conventions. If the document and available runtime cannot answer a contract question, report that information as unavailable instead of inventing a field, lifecycle, or format.

Use `scaffold-mod-package` for a new package, then replace only its explicit instruction placeholder. Before authoring a custom Tool, read `bundled-tool` or `portable-tool-hook` with `read-mod-authoring-example`; before authoring a Hook, read `before-accept-final-hook` or `portable-tool-hook`. Use `scaffold-mod-component` so canonical folders exist before writing their domain logic. Read existing package files before repairing them and preserve unrelated content and unselected bundled components. Use Skill instructions when prompting is sufficient; add a custom Tool only for a genuinely new callable capability and a Hook only for automatic behavior at a documented lifecycle.

Tests must verify the requested behavior. When a meaningful assertion fails, fix the implementation instead of weakening or duplicating the assertion unless the contract genuinely leaves the detail unspecified. The Builder may use `run_command` while authoring or testing, but the generated Mod must select only runtime Tools its finished workflow needs; build-time Tools are not automatic runtime dependencies.

Explicitly select every built-in Tool the Skill workflow needs in each Skill?s `allowed-tools`. Different packaged Skills may have different permissions; `mod.yaml` selects only the default Skill and Mod-wide Hooks. Select existing built-in or shared components when suitable. Bundle complete custom components when portability is required. Never bundle or replace protected built-ins.

Ordinary user Mod parsing, selected components, and runtime resolution belong to Core. The bundled helper checks metadata and static authoring structure without importing authored source. Use only the supplied authoring workspace/app-home; the packaged guide and examples require no development checkout. Do not assume a standalone Python executable or pytest is installed. Test custom behavior with package-owned tests when a runner is available and report execution tests as unrun otherwise.

Before finalizing, run `validate-mod-package` on the package and repair every reported error. Run any additional focused behavioral tests the authored logic needs. Report the package, selected/bundled components, portability state, exact checks run, and any behavior that could not be tested. Distinguish metadata/static validation from behavioral execution. Do not claim validation that did not run.

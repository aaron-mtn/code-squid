# Code Squid

A small local-first coding agent for repository work.

READ • PATCH • TEST • REPEAT  
SMALL AGENT. BIG TENTACLES.

Code Squid is a command-line application that reads files, makes edits, and runs
commands through model tool calls in a selected local workspace. It shows tool
activity and assistant responses, saves sessions, and lets you continue work
with follow-up tasks. The project aims to stay small and inspectable.

## Status and features

v0.1.0 is the first public release: an experimental personal project, with a
terminal interface and no stability guarantee yet. Model quality and tool-use
support matter. LM Studio is the default local provider; native Ollama support
is experimental. Outside contributions may not be reviewed promptly while the
project's direction settles. Forks and feedback are welcome.

- Sequential execution of valid single- or multi-tool replies
- File reads, exact text patches, whole-file writes, and shell commands
- Saved transcripts, session listing/resume, and latest-run file undo
- Approval modes, provider/model settings, and automatic transcript compaction
- A keyboard startup menu and multiline task composer
- User-installed Mods and Skills for task specialization
- Optional document, spreadsheet, PDF, and vision-enabled image reads

## Installation

Requires Python 3.11+, Git, and a tool-capable model served locally or through a
supported cloud provider. Code Squid, **Squid Core**, and **Squid Providers** are
separate distributions. Core owns the reusable runtime, tools, storage, and
contracts; Providers owns model transports, discovery, and connection defaults;
Code Squid owns coding policy, settings, and the console interface.

Install all three from their public GitHub repositories into one environment.
Do not assume `squid-core` or `squid-providers` is available on PyPI. Replace
`<owner>` below with each dependency repository's actual GitHub owner; those URLs
have not yet been established in this checkout. The commands use the default
branches; use matching release refs when all three v0.1.0 refs are available.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install "squid-core @ git+https://github.com/<owner>/squid-core.git" "squid-providers @ git+https://github.com/<owner>/squid-providers.git" "code-squid @ git+https://github.com/aarons360-stack/code-squid.git"
```

On macOS/Linux, activate with `source .venv/bin/activate` instead. The same pip
command then applies. Passing all three sources together supplies the pinned
`0.1.0` Core and Providers dependencies without fetching them from PyPI. Other
runtime dependencies are installed normally by pip.

For document and image readers, replace the Core requirement in that command
with `"squid-core[documents] @ git+https://github.com/<owner>/squid-core.git"`.
The extra installs the format libraries; it is not required for ordinary text
reads, edits, or commands. Image input additionally requires a vision-capable
model and a supported transport.

## Quick start

Start LM Studio's local server and load a tool-capable model. Its default endpoint
is `http://127.0.0.1:1234/v1`. Then select your workspace:

```bash
code-squid --cwd /path/to/repository
```

Choose the loaded model in the startup menu or enter `/model <exact-model-id>`.
The configured default model name is `qwen3.5-9b`; it must match a model your
server actually serves. Enter a task such as:

```text
Read the failing test and relevant implementation. Fix the bug with the smallest correct change. Run verification before finalizing.
```

`Enter` sends; `Alt+Enter` or `Ctrl+J` inserts a newline. `Shift+Enter` also works
when the terminal sends a supported modified-Enter sequence. `Ctrl+C` cancels
input or interrupts a run. Up from an empty startup composer focuses the menu;
Up/Down moves, Enter selects, and Esc returns. Use `/help` for current controls.

## Providers and configuration

| Provider ID | Connection |
| --- | --- |
| `lm_studio` | Local OpenAI-compatible chat completions; default `http://127.0.0.1:1234/v1` |
| `squid_models` | An already-running Squid Models service; default `http://127.0.0.1:8080/v1` |
| `ollama` | Native Ollama chat; default `http://127.0.0.1:11434`; experimental |
| `openrouter` | Cloud chat completions at `https://openrouter.ai/api/v1`; API key required |
| `openai_compatible` | Other compatible servers; default `http://127.0.0.1:8000/v1` |

Code Squid connects to services; it does not download models or manage server
processes. Compatibility varies by server and model.

Settings live at `~/.code-squid/settings.json`, or
`<CODE_SQUID_HOME>/settings.json` when `CODE_SQUID_HOME` is set. Missing settings
use defaults. A minimal configuration is:

```json
{
  "model": {"provider": "lm_studio", "name": "your-loaded-model-id"},
  "providers": {
    "lm_studio": {"base_url": "http://127.0.0.1:1234/v1", "api_key": "lm-studio"},
    "openrouter": {"api_key_env": "OPENROUTER_API_KEY"}
  },
  "runtime": {"approval_mode": "guarded", "max_tool_steps": null}
}
```

This example selects balanced safety. The actual default is `approval_mode=never`
(yolo), with no tool-step limit. Provider entries store sparse connection
overrides; missing fields inherit provider defaults. `api_key_env` names an
environment variable containing a key. `CODE_SQUID_API_KEY` overrides both that
variable and a saved key. A legacy workspace settings file is adopted on first
use if no application-wide settings file exists.

Common environment overrides: `CODE_SQUID_PROVIDER`, `CODE_SQUID_MODEL`,
`CODE_SQUID_BASE_URL`, `CODE_SQUID_API_KEY`, `CODE_SQUID_TEMPERATURE`, and
`CODE_SQUID_DEBUG`. `CODE_SQUID_TRACE=1` enables debug output and an end-of-run
transcript dump. `CODE_SQUID_STREAM_ASSISTANT_TEXT` controls live assistant text.
Optional `model.reasoning_mode` (`off`, `low`, `medium`, `high`) and
`model.reasoning_token_budget` are translated for OpenRouter; a positive budget
takes precedence over the mode. They also have `CODE_SQUID_REASONING_MODE` and
`CODE_SQUID_REASONING_TOKEN_BUDGET` overrides. `/reasoning show` controls display,
not the model's reasoning budget.

## Commands

The installed `code-squid` command and `python main.py` from a source checkout
use the same entry point.

```bash
code-squid --help
code-squid --cwd /path/to/repository
code-squid --skill <name>
code-squid safety balanced
code-squid skill
code-squid sessions
code-squid show latest
code-squid resume latest
code-squid undo
```

`show` and `resume` also accept a session ID. Workspace commands operate on the
current directory unless `--cwd` selects another workspace.

At the interactive prompt:

| Command | Action |
| --- | --- |
| `/help`, `/exit`, `/new` | Show help, exit, or start a new session boundary |
| `/provider`, `/provider use <id>`, `/provider status` | Inspect/select a provider and inspect effective setup |
| `/provider key <value>`, `/provider url <value>` | Save connection overrides for the selected provider |
| `/model <exact-id>` | Select a model |
| `/safety [strict\|balanced\|yolo]` | Inspect/change approval mode |
| `/reasoning [show\|hide]` | Inspect/change reasoning display |
| `/compact-at <tokens>` | Set automatic compaction threshold, e.g. `30k` |
| `/mod [name\|none]`, `/skill [name\|none]` | Inspect/select specialization |
| `/sessions`, `/show [current\|latest\|<id>]`, `/resume <id-or-latest>` | Inspect or continue saved work |
| `/undo` | Restore the latest-run file snapshots |
| `/workspace [path]`, `/cwd` | Inspect/switch workspace or show its root |

## Mods and Skills

Mods are the primary interactive specialization path. Install a Mod package
under `~/.code-squid/mods/<name>/` (or the configured application home), with a
`mod.yaml` manifest and packaged `skills/<skill-id>/SKILL.md` files. A Mod
combines identity, a default Skill, and optional custom Tools and Hooks. Its
active Skill's `allowed-tools` determines tool access; the manifest does not
grant tools. `/mod <name>` selects its default Skill, and `/skill <name>` switches
within that Mod. `/skill none` resets the Mod default; `/mod none` clears it.

Standalone Skills live under `~/.code-squid/skills/<name>/SKILL.md`. They supply
instructions and can restrict or select tools. Use `/skill <name>` without an
active Mod, or launch with `--skill <name>`. Code Squid ships no bundled Mods or
Skills. Custom Tools and Hooks execute local Python code; install only resources
you trust. See the architecture reference for the resource contracts.

## Tools and safety

The default model-facing tools are:

- `read_file(path, ranges=None, pages=None, sheet=None, rows=None)` — bounded
  UTF-8 text reads; optional format readers for DOCX, EPUB, XLSX, ODS, PDF,
  PNG, JPEG, and WebP. Text ranges, PDF page ranges, and sheet/row selection are
  format-specific. PDF reads extract text and lazily render selected pages;
  they do not perform OCR. Image reads require declared vision support,
  through LM Studio, native Ollama, or OpenRouter models whose catalog declares
  image input; unsupported or unknown capabilities fail closed.
- `apply_patch(path, old_text, new_text)` — exact replacement in an existing
  UTF-8 file, with revalidated candidate selection through `match_id` after a
  diagnostic. This is not a unified-diff tool.
- `write_file(path, content)` — create or replace a UTF-8 file.
- `run_command(command, verification)` — shell execution in the workspace with
  a timeout and bounded output. The required boolean records whether the model
  considers the command a verification step.

File tools require absolute paths. Valid multi-tool replies execute sequentially
in response order and stop at the first unsuccessful action. Dependent calls
should be made in a later model turn.

`strict` (`always`) asks before every tool; `balanced` (`guarded`) allows file
actions within the workspace and asks for untrusted commands or actions carrying
workspace/Hook approval reasons; `yolo` (`never`, the default) runs without
approval prompts. Balanced mode can remember command identities you approve.
Press Enter to approve, or enter a comment to reject and steer the model.

Approval gates are not a hardened sandbox. Commands and custom code run with
your user's permissions and can affect real files or external services.

## Sessions, undo, and compaction

Workspace sessions live in `.code-squid/sessions/<session-id>/`, with transcript
and event records in `session.jsonl` and session assets alongside them. Listing,
showing, and resuming sessions support review and follow-up work.

Undo is latest-run only: starting a run or resuming creates a fresh buffer.
`write_file` and `apply_patch` snapshot each target's pre-change state. Undo
restores those files or removes newly created files. Shell commands and custom
Tools are not automatically undo-protected. Undo is not a substitute for Git.

Automatic compaction defaults to 25,000 estimated input tokens, summarizes about
80% of eligible older history, and preserves at least the newest two chunks.
The system message and original task remain protected. `/compact-at` changes the
threshold. Estimates are approximate, and summaries can lose detail.

## Local state and privacy

Workspace `.code-squid/` holds sessions, assets, undo snapshots, and diagnostic
logs. The application home holds settings, resources, a session-index registry,
and recent workspace paths. These may contain prompts, file contents, command
output, local paths, and credentials saved in settings. Keep workspace state
ignored in your own repositories and review state before sharing it.

Local-first describes workspace/state ownership: selected providers receive the
model transcript and tool results, including file content and supported images.
Cloud providers therefore send this data off your machine; local providers use
the configured local service. Trace output can expose the same sensitive data.

## Known limitations

- Experimental terminal UX; no GUI or multi-agent orchestration.
- No built-in browser or structured search tool; use shell commands for search.
- Stdin task input is not implemented; tasks begin at the interactive prompt.
- Provider/model compatibility and tool-call reliability vary.
- Format reads do not preserve full document layout or edit those formats;
  spreadsheets are not recalculated, and PDF OCR is not provided.
- Approval is not containment; command side effects are not covered by undo.
- Compaction uses approximate token counts and lossy summaries.

## Development and testing

For editable development, clone the three repositories side by side as
`code-squid/`, `squid-core/`, and `squid-providers/`. The sibling layout is a
convenience for `requirements.txt`, not an installed runtime requirement.
From the Code Squid checkout, in an activated virtual environment:

```bash
python -m pip install -r requirements.txt pytest build
python -m pip install -e "../squid-core[documents]"
python -m pytest tests
python -m build
code-squid --help
```

The documents extra is needed for reader tests. Run Core and Providers suites
separately (`python -m pytest ../squid-core/tests` and
`python -m pytest ../squid-providers/tests`); they can share test module names.
No live model inference is needed for the Code Squid suite.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for ownership, runtime flow, and
public seams. See [docs/IMPLEMENTATION_NOTES.md](docs/IMPLEMENTATION_NOTES.md)
for subsystem mechanics, storage layouts, and maintenance details.

## License

Code Squid is licensed under the [MIT License](LICENSE), copyright Aaron Slater.
Squid Core, Squid Providers, and third-party dependencies have their own licenses.

# Code Squid

Code Squid is a local-first coding agent that works directly with projects on
your computer.

It can read and edit files, run commands and tests, and work with both local and
cloud models. It is designed to stay small, understandable, and easy to
customize.

Skills can change its instructions and available tools. Mods can bundle Skills,
custom tools, and hooks together for different kinds of work.

Code Squid is built on Squid Core, with its model integrations provided by
Squid Providers.

## Features

- Local and cloud model support
- File reads, targeted patches, whole-file writes, and shell commands
- Sequential single- and multi-tool execution
- Saved sessions with resume and follow-up work
- Latest-run file undo
- Approval modes for tool actions
- Automatic context compaction for longer sessions
- Easy customization with custom Skills, Mods, hooks, and tools
- Optional document, spreadsheet, PDF, and image reads
- A keyboard-driven terminal interface

## Installation

Requires Python 3.11+, Git, and a tool-capable model served locally or through a
supported cloud provider. Code Squid, **Squid Core**, and **Squid Providers** are
separate distributions. Core owns the reusable runtime, tools, storage, and
contracts; Providers owns model transports, discovery, and connection defaults;
Code Squid owns coding policy, settings, and the console interface.

Install all three from their public GitHub repositories into one environment.
Do not assume `squid-core` or `squid-providers` is available on PyPI. The commands
use the default branches; use matching release refs when all three v0.1.0 refs
are available.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install "squid-core @ git+https://github.com/aaron-mtn/squid-core.git" "squid-providers @ git+https://github.com/aaron-mtn/squid-providers.git" "code-squid @ git+https://github.com/aaron-mtn/code-squid.git"
```

On macOS/Linux, activate with `source .venv/bin/activate` instead. The same pip
command then applies. Passing all three sources together supplies the pinned
`0.1.0` Core and Providers dependencies without fetching them from PyPI. Other
runtime dependencies are installed normally by pip.

For document and image readers, replace the Core requirement in that command
with `"squid-core[documents] @ git+https://github.com/aaron-mtn/squid-core.git"`.
The extra installs the format libraries; it is not required for ordinary text
reads, edits, or commands. Image input additionally requires a vision-capable
model and a supported transport.

## Quick start

Start a local model server such as LM Studio or Ollama with a model that supports tool calling.

Open a terminal and start Code Squid:

```powershell
code-squid
```

Select your provider and model from the startup menu.

To choose the folder Code Squid will work in, use `/workspace` followed by the path:

```text
/workspace C:\path\to\project
```

Once you've used a workspace, it will also appear in the recent workspaces list in the startup menu.

Then enter a coding task, for example:

```text
Build a little JavaScript endless runner where I ride a skateboard, jump over obstacles, and try to get the highest score. Make it a web app and launch it in my browser when it's ready.
```

Use `/help` to see the available commands and keyboard controls.

## Providers and configuration

Code Squid supports local and cloud models through Squid Providers.

| Provider | Default endpoint |
| --- | --- |
| LM Studio | `http://127.0.0.1:1234/v1` |
| Ollama | `http://127.0.0.1:11434` |
| OpenRouter | `https://openrouter.ai/api/v1` |
| OpenAI-compatible servers | `http://127.0.0.1:8000/v1` |

You can select a provider and model from the startup menu or change them
using `/provider` and `/model` inside Code Squid.

Code Squid connects to existing model servers and APIs. It does not download
models or manage model servers.

Settings are saved in `~/.code-squid/settings.json`. You can configure providers
through Code Squid's commands or edit the settings file directly.

OpenRouter requires an API key. Local providers generally don't, unless your
server requires authentication.

Support for tool calling, vision, reasoning, and other features depends on the
model and provider.

For additional configuration details, see
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Commands

After installation, start Code Squid with:

```powershell
code-squid
```

You can also run it directly from the source repository:

```powershell
python main.py
```

Some useful commands inside Code Squid:

| Command | Purpose |
| --- | --- |
| `/workspace <path>` | Switch to a different workspace |
| `/provider` | View and select model providers |
| `/model <name>` | Select a model |
| `/mod` | View and select Mods |
| `/skill` | View and select Skills |
| `/safety` | View or change tool approval settings |
| `/sessions` | List saved sessions |
| `/resume latest` | Continue the most recent session |
| `/undo` | Undo file changes from the latest run |
| `/new` | Start a new session |

Use `/help` inside Code Squid for the full command list and keyboard controls.

## Mods and Skills

Code Squid can be customized with Skills, Mods, custom tools, and hooks.

**Skills** change how Code Squid works for a particular kind of task. They can replace or extend specific sections of the system prompt and control which tools are available to the agent. By default, the agent uses Code Squid's normal tools. A Skill can specify an `allowed-tools` list to restrict which built-in and custom tools are available.

**Mods** package Skills, custom tools, hooks, and metadata together. A Mod can contain multiple Skills, each with its own instructions and tool permissions. Mods can also define an accent color that changes the appearance of the terminal interface.

### Mod Builder

Code Squid includes **Mod Builder**, a built-in Mod that helps you create and edit Skills, custom tools, hooks, and complete Mod packages by describing what you want.

For example:

```text
Create a Dungeon Master Mod that runs a text-based fantasy adventure,
with a custom tool for dice rolls, combat, character stats, and saved games.
```

Mod Builder can generate the required files, create custom Python tools and hooks, and validate the completed package.

### Using Mods and Skills

Use `/mod` to see available Mods and `/mod <name>` to activate one. Use `/skill` to see available Skills and `/skill <name>` to select a Skill within the active Mod.

To start Mod Builder:

```text
/mod mod-builder
```

User-installed Mods live in `~/.code-squid/mods/`, and standalone Skills live in `~/.code-squid/skills/`. Built-in Mod Builder ships with Code Squid.

Custom tools and hooks can execute local Python code, so only install Mods from sources you trust.

## Tools and safety

Code Squid comes with four built-in tools:

| Tool | Purpose |
| --- | --- |
| `read_file` | Read code, text files, and supported documents and images |
| `write_file` | Create or replace files |
| `apply_patch` | Make targeted changes to existing files |
| `run_command` | Run shell commands and tests |

Custom tools can also be added through Skills and Mods.

### Approval modes

Code Squid has three approval modes that control when it asks permission before executing tools:

- **Strict:** Ask for approval before every tool action.
- **Balanced:** Allow file reads, writes, and patches within the workspace. Shell commands require approval, with an option to remember allowed command types, such as `git` or `ls`.
- **Yolo (default):** Run tools without asking for approval.

You can view or change the approval mode using `/safety`.

Code Squid runs commands with your user's permissions. Approval modes are not a security sandbox, so review what the agent is doing, especially when using Yolo mode.

## Sessions, undo, and compaction

Code Squid saves your sessions so you can review previous work, resume unfinished tasks, and continue conversations across multiple sessions. It automatically creates a `.code-squid/sessions/` directory in your workspace to store them.

Use `/sessions` to browse saved sessions and `/resume` to continue one.

Code Squid can also undo file changes made during the latest run using `/undo`. This covers changes made through `write_file` and `apply_patch`, but not shell commands or custom tools. Undo is not a replacement for Git.

For longer conversations, Code Squid uses **context compaction** to summarize older messages and make room for new ones. This helps the agent continue working without exceeding the model's context limit, although some details may be lost during summarization.

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

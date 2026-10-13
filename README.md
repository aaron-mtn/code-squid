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

Code Squid requires Python 3.11+, Git, and a tool-capable model served locally or through a supported cloud provider.

Create a virtual environment and install Code Squid from GitHub:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install "git+https://github.com/aaron-mtn/code-squid.git@v0.1.0"
```

On Linux, activate the virtual environment with `source .venv/bin/activate` instead.

Squid Core and Squid Providers are installed automatically from PyPI as dependencies.

For optional document, spreadsheet, PDF, and image reading support, install:

```powershell
python -m pip install "squid-core[documents]==0.1.0"
```

The additional libraries are not required for ordinary text files, code editing, or shell commands. Image reading also requires a vision-capable model and supported provider.

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

**Skills** change how Code Squid works for a particular kind of task. They can replace or extend specific sections of the system prompt and control which tools are available to the agent. Standalone Skills use Code Squid's default tools unless they specify an `allowed-tools` list. Listing specific tools restricts which built-in and custom tools are available, while an explicit empty list (`allowed-tools: []`) disables all tools. Skills packaged inside Mods must specify their allowed tools.

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

Code Squid saves sessions locally under `~/.code-squid/workspaces/`, outside your project directories. Each workspace has its own saved sessions, latest-run undo buffer, and diagnostic logs.

Use `/sessions` to browse saved sessions and `/resume` to continue one.

Sessions are associated with the workspace's location. Moving or renaming a workspace means its previous sessions will not automatically appear under the new path.

Code Squid can also undo file changes made during the latest run using `/undo`. This covers changes made through `write_file` and `apply_patch`, but not shell commands or custom tools. Undo is not a replacement for Git.

For longer conversations, Code Squid uses **context compaction** to summarize older messages and make room for new ones. This helps the agent continue working without exceeding the model's context limit, although some details may be lost during summarization.

## Local state and privacy

Code Squid stores its settings, Mods, Skills, and session data locally in `~/.code-squid/`. Session histories, undo snapshots, and logs are organized by workspace and stored outside your project directories.

These files may contain conversation history, source code, command output, and other sensitive information. Keep your Code Squid application directory private, especially when backing up or sharing files.

Code Squid supports both local and cloud models. When using a local model server, requests are sent to that server. When using a cloud provider, prompts and relevant project information are sent to that provider for processing.

Code Squid does not require an account, although cloud providers may require API keys and have their own data handling policies.

## Known limitations

- Code Squid currently provides a terminal interface. A separate desktop application is in development.
- Code Squid does not include a built-in web browser or web search tool.
- Model compatibility and tool-calling reliability vary by provider and model. Smaller local models may require additional guidance.
- Document and image reading requires optional dependencies and compatible models. These tools extract content but do not provide full document editing or layout preservation.
- Undo only covers changes made through Code Squid's built-in file-editing tools, not shell commands or custom tools.
- Context compaction summarizes older conversations, so some details may be lost during longer sessions.

## Development and testing

Code Squid is open source and built across three repositories: Code Squid, Squid Core, and Squid Providers.

To work on the source code, clone all three repositories into the same parent directory:

```text
projects/
├── code-squid/
├── squid-core/
└── squid-providers/
```

From the Code Squid directory, create a Python virtual environment:

```bash
python -m venv .venv
```

Activate it on Windows (PowerShell):

```powershell
.venv\Scripts\Activate.ps1
```

Or on Linux:

```bash
source .venv/bin/activate
```

Install the three projects in editable mode, along with the development dependencies:

```bash
python -m pip install -e "../squid-core[documents]"
python -m pip install -e ../squid-providers
python -m pip install -e .
python -m pip install pytest build
```

Run the tests with:

```bash
python -m pytest tests
```

You can also run Code Squid directly from the source repository:

```bash
python main.py
```

For more technical details, see [Architecture](docs/ARCHITECTURE.md) and [Implementation Notes](docs/IMPLEMENTATION_NOTES.md).

## License

Code Squid is licensed under the [MIT License](LICENSE), copyright Aaron Slater.
Squid Core, Squid Providers, and third-party dependencies have their own licenses.

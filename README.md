# Code Squid

A small local-first coding agent for repository work.

READ • PATCH • TEST • REPEAT  
SMALL AGENT. BIG TENTACLES.

## What it is

Code Squid is a command-line coding agent that can read files, write files, and
run commands while working in a local repository. It works through model tool
calls, shows a visible transcript of what is happening, and persists sessions so
work can be shown, resumed, or reviewed later.

It supports resume, latest-only undo, safety modes, transcript compaction, and
a small set of local tools. The project is intended to stay small and
inspectable.

## What it is not

Code Squid is not a general agent framework, a hardened sandbox, a multi-agent
system, or a polished TUI/GUI.

Safety modes are not containment. Code Squid can run local shell commands and
can read or write real files as the current user.

## Current status

This repository is at an MVP checkpoint. It is public, but still a personal
experimental project while the architecture and direction settle.

LM Studio, or another OpenAI-compatible local server, is the recommended default
provider path. The native Ollama provider exists and is experimental.
OpenRouter is supported, but can be noisier than local OpenAI-compatible
servers.

OpenRouter may return multiple tool calls even when `parallel_tool_calls=false`
is sent. Code Squid rejects those replies and retries with a correction message.

## Features

- Strict one-tool-at-a-time coding loop
- Visible narration plus terminal tool-event display
- Local tools: `apply_patch`, `read_file`, `write_file`, and `run_command`
- Sessions saved under `.code-squid/sessions`
- Session listing, transcript display, and resume
- Latest-only undo for `write_file`
- Safety levels: `strict`, `balanced`, or `yolo`
- Settings file with environment variable overrides
- Provider support: `openai_compatible`, `openrouter`, and `ollama`
- Transcript compaction
- Output truncation and ranged reads
- Final summary contract

## Install

Clone the repository, create a virtual environment, and install the Python
requirements:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## Quick start with LM Studio

Start the LM Studio local server and load a tool-capable model. By default,
Code Squid expects an OpenAI-compatible server at:

```text
http://127.0.0.1:1234/v1
```

Then run:

```bash
python main.py
```

Enter a task when prompted. For example:

```text
Work in /absolute/path/to/repo. Start by reading the failing test and relevant implementation. Fix the bug with the smallest correct change. Run verification before finalizing.
```

The task prompt supports multiline input:

- `Enter` sends the task.
- `Alt+Enter` inserts a newline.
- `Ctrl+J` inserts a newline.
- `Ctrl+C` cancels before the run starts or interrupts an active run.

Stdin task input is not implemented yet; start tasks from the interactive
prompt.

## Configuration

Code Squid reads local settings from:

```text
.code-squid/settings.json
```

Missing settings are allowed. A practical LM Studio-oriented configuration looks
like this:

```json
{
  "model": {
    "provider": "openai_compatible",
    "base_url": "http://127.0.0.1:1234/v1",
    "api_key": "lm-studio",
    "name": "qwen3.5-9b",
    "temperature": 0
  },
  "runtime": {
    "approval_mode": "never",
    "max_tool_steps": null
  },
  "display": {
    "debug": false
  },
  "compaction": {
    "enabled": true,
    "trigger_input_tokens": 48000,
    "keep_recent_turns": 8
  }
}
```

`model.api_key_env` can name an environment variable that contains the API key.
`CODE_SQUID_API_KEY` overrides both `model.api_key_env` and `model.api_key`.

Supported environment overrides:

- `CODE_SQUID_BASE_URL`
- `CODE_SQUID_API_KEY`
- `CODE_SQUID_MODEL`
- `CODE_SQUID_PROVIDER`
- `CODE_SQUID_TEMPERATURE`
- `CODE_SQUID_DEBUG`

`CODE_SQUID_TRACE=1` enables debug output and prints the full transcript at the
end of a run.

## Providers

### LM Studio / Generic OpenAI-Compatible

Use this for LM Studio or another local OpenAI-compatible chat completions
server:

```json
{
  "model": {
    "provider": "openai_compatible",
    "base_url": "http://127.0.0.1:1234/v1",
    "api_key": "lm-studio",
    "name": "qwen3.5-9b"
  }
}
```

### OpenRouter

Set `provider` to `openrouter`, use the OpenRouter base URL, and provide an API
key through `model.api_key`, `model.api_key_env`, or `CODE_SQUID_API_KEY`.

```json
{
  "model": {
    "provider": "openrouter",
    "base_url": "https://openrouter.ai/api/v1",
    "api_key_env": "OPENROUTER_API_KEY",
    "name": "your-model-name"
  }
}
```

Known issue: OpenRouter may emit multiple tool calls in one reply. Code Squid
rejects those replies and retries.

### Ollama Native

Set `provider` to `ollama` to use the native Ollama provider:

```json
{
  "model": {
    "provider": "ollama",
    "base_url": "http://127.0.0.1:11434",
    "name": "your-tool-capable-model"
  }
}
```

The native Ollama provider is experimental and works best with tool-capable
models.

## Commands

```bash
python main.py
python main.py --cwd <path>
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

`python main.py` starts a new interactive task.

`python main.py sessions` lists saved sessions.

`python main.py show latest` shows the newest saved session.

`python main.py show <session_id>` shows a specific saved session.

`python main.py resume latest` resumes the newest saved session and asks for a
follow-up task.

`python main.py resume <session_id>` resumes a specific saved session and asks
for a follow-up task.

`python main.py undo` restores the latest undo buffer.

`python main.py safety` prints the current safety mode.

`python main.py safety strict`, `safety balanced`, and `safety yolo` select the
friendly safety level backed by `runtime.approval_mode`.

Mods are the primary interactive specialization path: use `/mod`, `/mod
<name>`, or `/mod none`. Standalone Skills remain the direct/advanced path:
use `/skill`, `/skill <name>`, or `/skill none` interactively, `python main.py
skill` to list them, and `--skill <name>` to start with one selected.

At the task prompt, enter `/help` to print the current prompt keybindings and
command summary.

## Tools and safety

Code Squid exposes four local tools to the model:

- `apply_patch(patch)`
- `read_file(path, start_line=None, end_line=None)`
- `write_file(path, content)`
- `run_command(command)`

`read_file` and `write_file` require absolute paths. Paths outside the selected
workspace root require approval in strict mode and are allowed without prompts
in yolo mode.

`run_command` runs a shell command from the current/configured repo root by
default. It uses the local shell, has a timeout, and can mutate files or perform
other local side effects.

Code Squid is a trusted local tool, not a hardened sandbox. Review tasks and
model/provider behavior with that in mind.

## Safety modes

The user-facing safety names map to the internal approval setting:

- `strict` means `approval_mode=always`
- `balanced` means `approval_mode=guarded`
- `yolo` means `approval_mode=never`

`never` is trusted local mode. Tools run without prompting.

`guarded` allows low-risk workspace actions without prompting and asks for
approval when an action falls outside those rules. `always` asks before every
tool execution. Press Enter to approve the proposed
tool action. Type a comment to reject the action and steer the model; the
denial is returned to the model as a normal failed tool result before your
comment is added as the next user instruction.

Approval mode is an interaction gate before tool execution, not a sandbox or
containment boundary.

## Local state and privacy

Code Squid stores local runtime state under:

```text
.code-squid/
```

That directory may contain settings, sessions, logs, undo snapshots,
transcripts, prompts, file contents, command output, local paths, and other
repo-specific data. It is ignored by this repository and should stay ignored.
Do not publish, upload, or share `.code-squid/` without reviewing it first.

## Sessions and undo

Sessions are stored in:

```text
.code-squid/sessions
```

Each session records transcript and event entries in `session.jsonl`. The
session commands are useful for show/resume/report-style workflows: list saved
sessions, inspect a transcript, or continue a previous run with a follow-up
task.

Undo is latest-only. Starting a new run or resume creates a fresh undo buffer.
Before `write_file` changes a file, Code Squid snapshots the previous state for
undo. `run_command` is not undo-protected and can mutate files directly.

## Compaction

Compaction is enabled by default. Before model calls, Code Squid estimates the
current transcript size. When it gets large, older context is summarized while
recent turns are kept verbatim.

Compaction uses rough token estimates. It is transcript management, not
workspace memory.

## Known limitations

- Local trusted tool execution can affect real files.
- Approval mode is not a sandbox.
- `run_command` can mutate files and is not undo-protected.
- Tool access is small by design: no plugin system, browser tool, patch tool,
  or structured search tool.
- OpenRouter can be noisier than local OpenAI-compatible providers.
- The native Ollama provider is experimental.
- Model quality matters, especially for tool use and final summaries.
- There is no GUI/TUI yet.
- Compaction does not use an exact tokenizer yet.
- Stdin task input is not implemented yet.

## Contributing

Code Squid is public, but outside contributions are not actively accepted yet
while the architecture and direction are still settling. Issues and pull
requests may not be reviewed promptly.

Forks and feedback are welcome.

## License

No `LICENSE` file is included yet. Until one is added, do not assume Code Squid
is licensed for reuse or redistribution.

## Architecture reference

For the deeper technical reference, see
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

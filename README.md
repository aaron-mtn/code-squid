# Code Squid

A small local-first coding agent for repository work.

READ • PATCH • TEST • REPEAT  
SMALL AGENT. BIG TENTACLES.

## What it is

Code Squid is a command-line coding agent that can read files, write files, and
run commands in a local repository. It works through model tool calls, keeps a
visible transcript of what is happening, and persists sessions so work can be
shown or resumed later.

It supports resume, latest-only undo, approval mode, transcript compaction, and
a small set of local tools. The project is intended to stay small and
inspectable.

## What it is not

Code Squid is not a general agent framework, a hardened sandbox, a multi-agent
system, or a polished TUI/GUI.

## Current status

This repository is at an MVP checkpoint.

LM Studio, or another OpenAI-compatible local server, is the recommended default
provider path. The native Ollama provider exists and is experimental.
OpenRouter is supported, but can be noisier than local OpenAI-compatible
servers.

OpenRouter may return multiple tool calls even when `parallel_tool_calls=false`
is sent. Code Squid rejects those replies and retries with a correction message.

## Features

- Strict one-tool-at-a-time coding loop
- Visible narration plus terminal tool-event display
- Local tools: `read_file`, `write_file`, and `run_command`
- Sessions saved under `.code-squid/sessions`
- Show and list saved sessions
- Resume the latest session or a specific session
- Latest-only undo
- Approval mode: `never` or `always`
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

The interactive task prompt currently reads one input line. For long tasks,
paste the task as one line for now. Multiline task input and stdin task input
are not implemented yet; if you paste multiple lines into a normal shell, extra
lines may be interpreted by the shell after Code Squid exits.

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
python main.py sessions
python main.py show latest
python main.py show <session_id>
python main.py resume latest
python main.py resume <session_id>
python main.py undo
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

## Approval mode

`never` is trusted local mode. Tools run without prompting.

`always` asks before every tool execution. If a tool call is denied, the denial
is returned to the model as a normal failed tool result.

Approval mode is not a sandbox. It is an interaction gate before tool execution.

## Sessions and undo

Sessions are stored in:

```text
.code-squid/sessions
```

Each session records transcript and event entries in `session.jsonl`. Resume
loads the saved messages, appends a follow-up user message, and continues the
same saved session.

Undo restores the latest undo buffer only. Before `write_file` changes a file,
Code Squid snapshots the previous state for undo. `run_command` is not
undo-protected and can mutate files directly.

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
- OpenRouter can be noisier than local OpenAI-compatible providers.
- Model quality matters, especially for tool use and final summaries.
- There is no GUI/TUI yet.
- There is no plugin system.
- Compaction does not use an exact tokenizer yet.
- Multiline task input and stdin task input are not implemented yet.

## Architecture reference

For the deeper technical reference, see
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

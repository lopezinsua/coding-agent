# coding-agent

CLI agent that finds failing tests, fixes the code and opens a PR — agentic loop with tool use built from scratch, no frameworks.

## What it does

Given a GitHub repo or a local path, the agent runs this cycle autonomously:

1. Clones/reads the repo
2. Detects language and structure
3. Runs existing tests → identifies failures
4. Analyses the relevant code with an LLM
5. Applies a fix (minimum change)
6. Re-runs tests → verifies they pass
7. Opens a PR with the fix

## Install

```bash
git clone https://github.com/lopezinsua/coding-agent
cd coding-agent
pip install -r requirements.txt
cp .env.example .env   # add your API key
```

## Setup

Get a free Groq API key at [console.groq.com](https://console.groq.com) and add it to `.env`:

```
LLM_PROVIDER=groq
GROQ_API_KEY=gsk_...
```

To open real PRs, also add a GitHub token:

```
GITHUB_TOKEN=ghp_...
GITHUB_USERNAME=your-username
```

Supported providers: `groq` (free), `ollama` (local), `anthropic`, `openai`.

## Usage

```bash
# Fix a GitHub repo and open a PR
python src/agent.py --repo https://github.com/user/repo

# Fix a local repo (no cloning)
python src/agent.py --local /path/to/repo

# Dry run — prints the PR instead of opening it
python src/agent.py --repo https://github.com/user/repo --dry-run
```

## Try the demo

```bash
python src/agent.py --local examples/demo_repo --dry-run
```

`examples/demo_repo` contains a Python module with a bug (`add()` returns `a - b`) and pytest tests that catch it. The agent finds the bug, fixes it, verifies all tests pass and prints the PR it would open.

## How it works

The agent exposes 5 tools to the LLM:

| Tool | What it does |
|------|-------------|
| `read_file` | Read a file from the repo |
| `list_files` | List a directory |
| `run_command` | Run shell commands (pytest, linters) |
| `write_file` | Write a fix to a file |
| `open_pr` | Commit, push a branch and open a PR |

The agentic loop calls the LLM, executes whatever tools it requests, feeds results back, and repeats until the model stops or the tests pass. No LangChain, no AutoGen — tool use implemented from scratch with the provider's API.

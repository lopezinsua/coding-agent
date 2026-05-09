#!/usr/bin/env python3
import argparse
import json
import os
import sys
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(__file__))

from tools import TOOLS, execute_tool
from github_client import GitHubClient
from prompts import SYSTEM_PROMPT

load_dotenv()

MAX_ITERATIONS = 30

# Provider configs for OpenAI-compatible APIs
_OPENAI_PROVIDERS = {
    "groq":   ("https://api.groq.com/openai/v1",  "GROQ_API_KEY",   "llama-3.3-70b-versatile"),
    "ollama": ("http://localhost:11434/v1",         None,             "qwen2.5-coder:7b"),
    "openai": ("https://api.openai.com/v1",         "OPENAI_API_KEY", "gpt-4o-mini"),
}


# ── Anthropic loop ────────────────────────────────────────────────────────────

def _loop_anthropic(client, repo_path, github_client, dry_run):
    messages = [{"role": "user", "content": f"Fix the failing tests in: {repo_path}"}]

    for iteration in range(MAX_ITERATIONS):
        response = client.messages.create(
            model=os.getenv("LLM_MODEL", "claude-sonnet-4-6"),
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        print(f"[iter {iteration + 1}] stop_reason={response.stop_reason}")
        for block in response.content:
            if hasattr(block, "text") and block.text:
                print(f"\nAgent: {block.text}\n")

        if response.stop_reason == "end_turn":
            print("Agent finished.")
            return

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    print(f"  >> {block.name}({block.input})")
                    result = execute_tool(block.name, block.input, repo_path, github_client, dry_run)
                    print(f"  << {result[:300]}{'...' if len(result) > 300 else ''}\n")
                    tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": result})

            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})

    print(f"Reached max iterations ({MAX_ITERATIONS}).")


# ── OpenAI-compatible loop (Groq, Ollama, OpenAI) ────────────────────────────

def _loop_openai_compatible(client, repo_path, github_client, dry_run):
    oai_tools = [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],
            },
        }
        for t in TOOLS
    ]

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Fix the failing tests in: {repo_path}"},
    ]

    for iteration in range(MAX_ITERATIONS):
        response = client.chat.completions.create(
            model=os.getenv("LLM_MODEL", "qwen/qwen3-32b"),
            max_tokens=4096,
            tools=oai_tools,
            messages=messages,
        )

        choice = response.choices[0]
        msg = choice.message
        finish = choice.finish_reason

        print(f"[iter {iteration + 1}] finish_reason={finish}")
        if msg.content:
            print(f"\nAgent: {msg.content}\n")

        if finish == "stop" or not msg.tool_calls:
            print("Agent finished.")
            return

        # Add assistant turn with tool calls
        messages.append({
            "role": "assistant",
            "content": msg.content,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in msg.tool_calls
            ],
        })

        # Execute each tool and add individual tool result messages
        for tc in msg.tool_calls:
            inputs = json.loads(tc.function.arguments)
            print(f"  >> {tc.function.name}({inputs})")
            result = execute_tool(tc.function.name, inputs, repo_path, github_client, dry_run)
            print(f"  << {result[:300]}{'...' if len(result) > 300 else ''}\n")
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})

    print(f"Reached max iterations ({MAX_ITERATIONS}).")


# ── Entry point ───────────────────────────────────────────────────────────────

def run_agent(repo_url=None, local_path=None, dry_run=False):
    provider = os.getenv("LLM_PROVIDER", "anthropic").lower()

    github_client = None
    repo_path = None

    if repo_url:
        print(f"Cloning {repo_url} ...")
        github_client = GitHubClient()
        repo_path = github_client.clone_repo(repo_url)
        print(f"Cloned to: {repo_path}\n")
    elif local_path:
        repo_path = os.path.abspath(local_path)
        print(f"Using local repo: {repo_path}\n")
        if not dry_run:
            try:
                github_client = GitHubClient()
            except KeyError:
                print("Warning: GITHUB_TOKEN not set — PR creation will be skipped.\n")
    else:
        print("Error: provide --repo <url> or --local <path>")
        sys.exit(1)

    print(f"Provider: {provider}\n")
    print("Agent starting...\n")

    if provider == "anthropic":
        import anthropic
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        _loop_anthropic(client, repo_path, github_client, dry_run)

    elif provider == "groq":
        from groq import Groq
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            print("Error: GROQ_API_KEY not set in .env")
            sys.exit(1)
        client = Groq(api_key=api_key)
        _loop_openai_compatible(client, repo_path, github_client, dry_run)

    elif provider in _OPENAI_PROVIDERS:
        from openai import OpenAI
        base_url, key_env, _ = _OPENAI_PROVIDERS[provider]
        api_key = os.getenv(key_env) if key_env else "ollama"
        if not api_key:
            print(f"Error: {key_env} not set in .env")
            sys.exit(1)
        client = OpenAI(base_url=base_url, api_key=api_key)
        _loop_openai_compatible(client, repo_path, github_client, dry_run)

    else:
        print(f"Error: unknown LLM_PROVIDER '{provider}'. Choose: anthropic, groq, ollama, openai")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Autonomous coding agent — finds failing tests, fixes code, opens a PR."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--repo", metavar="URL", help="GitHub repo URL to clone and fix")
    group.add_argument("--local", metavar="PATH", help="Local repo path (no cloning)")
    parser.add_argument("--dry-run", action="store_true", help="Skip opening a real PR")
    args = parser.parse_args()
    run_agent(repo_url=args.repo, local_path=args.local, dry_run=args.dry_run)


if __name__ == "__main__":
    main()

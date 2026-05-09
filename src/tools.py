import subprocess
from pathlib import Path

TOOLS = [
    {
        "name": "read_file",
        "description": "Read the contents of a file in the repository.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path to the file"}
            },
            "required": ["path"],
        },
    },
    {
        "name": "list_files",
        "description": "List files in a directory of the repository.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory to list ('' = root)"}
            },
            "required": ["path"],
        },
    },
    {
        "name": "run_command",
        "description": "Run a shell command in the repository directory (tests, linters, etc.).",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Command to execute"},
                "timeout": {"type": "integer", "description": "Timeout in seconds", "default": 30},
            },
            "required": ["command"],
        },
    },
    {
        "name": "write_file",
        "description": "Write or overwrite a file in the repository with the given content.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "open_pr",
        "description": "Open a Pull Request on GitHub with the current changes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "body": {"type": "string"},
                "branch": {"type": "string", "description": "Name of the branch to create"},
            },
            "required": ["title", "body", "branch"],
        },
    },
]


_BLOCKED_COMMANDS = {
    "rm", "del", "rmdir", "format", "mkfs", "dd",
    "shutdown", "reboot", "halt", "curl", "wget", "nc", "netcat",
}

def _safe_path(repo_path: str, file_path: str) -> Path:
    base = Path(repo_path).resolve()
    target = (base / file_path).resolve()
    # relative_to() raises ValueError if target is not under base,
    # correctly handling boundary cases like /foo/bar vs /foo/bar2
    try:
        target.relative_to(base)
    except ValueError:
        raise ValueError(f"Path traversal attempt blocked: {file_path}")
    return target


def read_file(path: str, repo_path: str) -> str:
    full_path = _safe_path(repo_path, path)
    if not full_path.exists():
        return f"Error: file not found: {path}"
    if not full_path.is_file():
        return f"Error: not a file: {path}"
    return full_path.read_text(encoding="utf-8")


def list_files(path: str, repo_path: str) -> str:
    if path:
        full_path = _safe_path(repo_path, path)
    else:
        full_path = Path(repo_path).resolve()
    if not full_path.exists():
        return f"Error: directory not found: {path}"
    entries = sorted(full_path.iterdir(), key=lambda p: (p.is_file(), p.name))
    lines = []
    for entry in entries:
        rel = entry.relative_to(repo_path)
        tag = "F" if entry.is_file() else "D"
        lines.append(f"[{tag}] {rel}")
    return "\n".join(lines) if lines else "(empty directory)"


def run_command(command: str, repo_path: str, timeout: int = 30) -> str:
    first_token = command.strip().split()[0].lower().lstrip("./")
    if first_token in _BLOCKED_COMMANDS:
        return f"Error: command '{first_token}' is blocked for safety."
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = result.stdout + result.stderr
        return output if output.strip() else f"(exit code {result.returncode}, no output)"
    except subprocess.TimeoutExpired:
        return f"Error: command timed out after {timeout}s"


def write_file(path: str, content: str, repo_path: str) -> str:
    full_path = _safe_path(repo_path, path)
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(content, encoding="utf-8")
    return f"Written: {path}"


def execute_tool(
    name: str,
    inputs: dict,
    repo_path: str,
    github_client=None,
    dry_run: bool = False,
) -> str:
    try:
        if name == "read_file":
            return read_file(inputs["path"], repo_path)
        elif name == "list_files":
            return list_files(inputs.get("path", ""), repo_path)
        elif name == "run_command":
            return run_command(inputs["command"], repo_path, inputs.get("timeout", 30))
        elif name == "write_file":
            return write_file(inputs["path"], inputs["content"], repo_path)
        elif name == "open_pr":
            if dry_run:
                return (
                    f"[DRY RUN] Would open PR: '{inputs['title']}' "
                    f"on branch '{inputs['branch']}'\n\n{inputs['body']}"
                )
            if github_client is None:
                return "Error: GitHub client unavailable. Use --repo to clone from GitHub, or set GITHUB_TOKEN."
            url = github_client.open_pr(
                repo_path=repo_path,
                title=inputs["title"],
                body=inputs["body"],
                branch=inputs["branch"],
            )
            return f"PR opened: {url}"
        else:
            return f"Error: unknown tool '{name}'"
    except Exception as exc:
        return f"Error in {name}: {exc}"

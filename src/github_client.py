import os
import re
import tempfile
from github import Github
from git import Repo
from dotenv import load_dotenv

load_dotenv()


def _extract_repo_full_name(url: str) -> str:
    """Extract 'owner/repo' from a GitHub HTTPS or SSH URL."""
    url = re.sub(r"\.git$", "", url.rstrip("/"))
    match = re.search(r"github\.com[:/](.+/.+)$", url)
    if not match:
        raise ValueError(f"Cannot parse GitHub repo from URL: {url}")
    return match.group(1)


def _inject_credentials(url: str, token: str, username: str) -> str:
    """Embed token into an HTTPS GitHub URL for authenticated push/clone."""
    if not re.match(r"https://github\.com/", url):
        raise ValueError(f"Only github.com HTTPS URLs are supported, got: {url!r}")
    return re.sub(r"https://", f"https://{username}:{token}@", url, count=1)


class GitHubClient:
    def __init__(self):
        self.token = os.environ["GITHUB_TOKEN"]
        self.username = os.environ.get("GITHUB_USERNAME", "coding-agent")
        self.gh = Github(self.token)

    def clone_repo(self, url: str) -> str:
        """Clone a GitHub repo into a temp directory. Returns the local path."""
        repo_name = re.sub(r"\.git$", "", url.rstrip("/").split("/")[-1])
        dest = tempfile.mkdtemp(prefix=f"{repo_name}_")
        auth_url = _inject_credentials(url, self.token, self.username)
        Repo.clone_from(auth_url, dest)
        return dest

    def open_pr(self, repo_path: str, title: str, body: str, branch: str) -> str:
        if not re.match(r"^[a-zA-Z0-9._\-/]+$", branch):
            raise ValueError(f"Invalid branch name: {branch!r}")
        repo = Repo(repo_path)
        remote_url = repo.remotes.origin.url
        full_name = _extract_repo_full_name(remote_url)

        # Set git identity for the commit
        with repo.config_writer() as cfg:
            cfg.set_value("user", "name", self.username)
            cfg.set_value("user", "email", f"{self.username}@users.noreply.github.com")

        # Create and switch to the fix branch
        repo.git.checkout("-b", branch)

        # Stage all modifications and untracked files
        repo.git.add("-A")

        if not repo.git.status("--short"):
            raise RuntimeError("No changes to commit — the tests may already pass.")

        repo.index.commit(f"fix: {title}")

        # Push using authenticated URL so credentials are not stored in .git/config
        auth_url = _inject_credentials(remote_url, self.token, self.username)
        repo.git.push("--set-upstream", auth_url, branch)

        # Open the PR via GitHub API
        gh_repo = self.gh.get_repo(full_name)
        pr = gh_repo.create_pull(
            title=title,
            body=body,
            head=branch,
            base=gh_repo.default_branch,
        )
        return pr.html_url

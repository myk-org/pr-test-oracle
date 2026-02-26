"""GitHub operations: fetch PR data and post comments via gh CLI."""

import asyncio
import json
import os
import subprocess

from simple_logger.logger import get_logger

from pr_test_oracle.models import PRInfo

logger = get_logger(name=__name__, level=os.environ.get("LOG_LEVEL", "INFO"))


class GitHubClient:
    """Client for GitHub operations using the gh CLI."""

    def __init__(self, token: str | None = None) -> None:
        """Initialize with optional GitHub token.

        If token is provided, it's set as GH_TOKEN env var for gh CLI.
        Otherwise, gh CLI uses its own auth.
        """
        self._env = os.environ.copy()
        if token:
            self._env["GH_TOKEN"] = token

    async def get_pr_diff(self, pr_info: PRInfo) -> str:
        """Fetch the full diff for a PR.

        Uses: gh pr diff {pr_number} --repo {owner}/{repo}

        Returns the diff as a string.
        Raises RuntimeError on failure.
        """
        cmd = [
            "gh",
            "pr",
            "diff",
            str(pr_info.pr_number),
            "--repo",
            f"{pr_info.owner}/{pr_info.repo}",
        ]
        return await self._run_gh(cmd, f"fetch diff for PR #{pr_info.pr_number}")

    async def get_pr_files(self, pr_info: PRInfo) -> list[str]:
        """Get list of changed file paths in a PR.

        Uses: gh pr diff {pr_number} --repo {owner}/{repo} --name-only

        Returns list of file paths.
        """
        cmd = [
            "gh",
            "pr",
            "diff",
            str(pr_info.pr_number),
            "--repo",
            f"{pr_info.owner}/{pr_info.repo}",
            "--name-only",
        ]
        output = await self._run_gh(cmd, f"list files for PR #{pr_info.pr_number}")
        return [f.strip() for f in output.strip().splitlines() if f.strip()]

    async def get_pr_details(self, pr_info: PRInfo) -> dict:
        """Get PR metadata (title, body, base branch, head branch, etc.).

        Uses: gh pr view {pr_number} --repo {owner}/{repo}
        --json title,body,baseRefName,headRefName,url

        Returns parsed JSON dict.
        """
        cmd = [
            "gh",
            "pr",
            "view",
            str(pr_info.pr_number),
            "--repo",
            f"{pr_info.owner}/{pr_info.repo}",
            "--json",
            "title,body,baseRefName,headRefName,url",
        ]
        output = await self._run_gh(cmd, f"view PR #{pr_info.pr_number}")
        return json.loads(output)

    async def post_comment(self, pr_info: PRInfo, body: str) -> str | None:
        """Post a comment on a PR.

        Uses: gh pr comment {pr_number} --repo {owner}/{repo} --body {body}

        Returns the comment URL if available, None otherwise.
        """
        cmd = [
            "gh",
            "pr",
            "comment",
            str(pr_info.pr_number),
            "--repo",
            f"{pr_info.owner}/{pr_info.repo}",
            "--body",
            body,
        ]
        logger.info(
            "Posting comment on PR #%d in %s/%s",
            pr_info.pr_number,
            pr_info.owner,
            pr_info.repo,
        )
        output = await self._run_gh(cmd, f"post comment on PR #{pr_info.pr_number}")
        # gh pr comment prints the comment URL on success
        url = output.strip()
        return url if url.startswith("https://") else None

    async def clone_repo(self, owner: str, repo: str, target_path: str, *, depth: int = 1) -> None:
        """Shallow clone a repository.

        Uses: gh repo clone {owner}/{repo} {target_path} -- --depth {depth}
        """
        cmd = [
            "gh",
            "repo",
            "clone",
            f"{owner}/{repo}",
            target_path,
            "--",
            f"--depth={depth}",
        ]
        await self._run_gh(cmd, f"clone {owner}/{repo}")
        logger.info("Cloned %s/%s to %s", owner, repo, target_path)

    async def _run_gh(self, cmd: list[str], description: str) -> str:
        """Run a gh CLI command and return stdout.

        Args:
            cmd: Command and arguments.
            description: Human-readable description for logging/errors.

        Returns:
            stdout output from the command.

        Raises:
            RuntimeError: If the command fails.
        """
        logger.debug("Running: %s", " ".join(cmd))
        try:
            result = await asyncio.to_thread(
                subprocess.run,
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
                env=self._env,
            )
        except subprocess.TimeoutExpired as exc:
            msg = f"gh CLI timed out: {description}"
            raise RuntimeError(msg) from exc

        if result.returncode != 0:
            error_detail = result.stderr or result.stdout or "unknown error"
            msg = f"gh CLI failed to {description}: {error_detail}"
            raise RuntimeError(msg)

        return result.stdout

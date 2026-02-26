"""Tests for GitHub client module."""

from unittest.mock import MagicMock, patch

import pytest

from pr_test_oracle.github_client import GitHubClient
from pr_test_oracle.models import PRInfo


@pytest.fixture
def gh_client() -> GitHubClient:
    """Create a GitHubClient without token."""
    return GitHubClient()


@pytest.fixture
def gh_client_with_token() -> GitHubClient:
    """Create a GitHubClient with token."""
    return GitHubClient(token="test-token")


@pytest.fixture
def pr_info() -> PRInfo:
    """Create a sample PRInfo."""
    return PRInfo(
        owner="owner", repo="repo", pr_number=42, url="https://github.com/owner/repo/pull/42"
    )


class TestGitHubClientInit:
    """Tests for GitHubClient initialization."""

    def test_init_without_token(self, gh_client: GitHubClient) -> None:
        assert "GH_TOKEN" not in gh_client._env or gh_client._env.get("GH_TOKEN") is None

    def test_init_with_token(self, gh_client_with_token: GitHubClient) -> None:
        assert gh_client_with_token._env["GH_TOKEN"] == "test-token"


class TestGetPrDiff:
    """Tests for get_pr_diff."""

    async def test_returns_diff(self, gh_client: GitHubClient, pr_info: PRInfo) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "diff --git a/file.py b/file.py\n+new line"
        mock_result.stderr = ""

        with patch("pr_test_oracle.github_client.asyncio.to_thread", return_value=mock_result):
            diff = await gh_client.get_pr_diff(pr_info)
        assert "diff --git" in diff

    async def test_failure_raises(self, gh_client: GitHubClient, pr_info: PRInfo) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "Not found"

        with (
            patch("pr_test_oracle.github_client.asyncio.to_thread", return_value=mock_result),
            pytest.raises(RuntimeError, match="Not found"),
        ):
            await gh_client.get_pr_diff(pr_info)


class TestGetPrFiles:
    """Tests for get_pr_files."""

    async def test_returns_file_list(self, gh_client: GitHubClient, pr_info: PRInfo) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "src/auth.py\nsrc/config.py\ntests/test_auth.py\n"
        mock_result.stderr = ""

        with patch("pr_test_oracle.github_client.asyncio.to_thread", return_value=mock_result):
            files = await gh_client.get_pr_files(pr_info)
        assert files == ["src/auth.py", "src/config.py", "tests/test_auth.py"]

    async def test_handles_empty_output(self, gh_client: GitHubClient, pr_info: PRInfo) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "\n"
        mock_result.stderr = ""

        with patch("pr_test_oracle.github_client.asyncio.to_thread", return_value=mock_result):
            files = await gh_client.get_pr_files(pr_info)
        assert files == []


class TestPostComment:
    """Tests for post_comment."""

    async def test_returns_url(self, gh_client: GitHubClient, pr_info: PRInfo) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "https://github.com/owner/repo/pull/42#issuecomment-123\n"
        mock_result.stderr = ""

        with patch("pr_test_oracle.github_client.asyncio.to_thread", return_value=mock_result):
            url = await gh_client.post_comment(pr_info, "test comment")
        assert url == "https://github.com/owner/repo/pull/42#issuecomment-123"

    async def test_returns_none_for_non_url(self, gh_client: GitHubClient, pr_info: PRInfo) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Comment posted\n"
        mock_result.stderr = ""

        with patch("pr_test_oracle.github_client.asyncio.to_thread", return_value=mock_result):
            url = await gh_client.post_comment(pr_info, "test comment")
        assert url is None


class TestCloneRepo:
    """Tests for clone_repo."""

    async def test_clone_success(self, gh_client: GitHubClient) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""

        with patch("pr_test_oracle.github_client.asyncio.to_thread", return_value=mock_result):
            await gh_client.clone_repo("owner", "repo", "/tmp/target")

    async def test_clone_failure(self, gh_client: GitHubClient) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 128
        mock_result.stdout = ""
        mock_result.stderr = "fatal: repository not found"

        with (
            patch("pr_test_oracle.github_client.asyncio.to_thread", return_value=mock_result),
            pytest.raises(RuntimeError, match="repository not found"),
        ):
            await gh_client.clone_repo("owner", "repo", "/tmp/target")


class TestRunGhTimeout:
    """Tests for _run_gh timeout handling."""

    async def test_timeout_raises(self, gh_client: GitHubClient) -> None:
        import subprocess

        with (
            patch(
                "pr_test_oracle.github_client.asyncio.to_thread",
                side_effect=subprocess.TimeoutExpired(cmd="gh", timeout=120),
            ),
            pytest.raises(RuntimeError, match="timed out"),
        ):
            await gh_client._run_gh(["gh", "test"], "test operation")

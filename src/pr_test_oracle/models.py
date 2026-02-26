"""Pydantic request/response models for the PR Test Oracle API."""

import re
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator


class PRInfo(BaseModel):
    """Parsed PR information extracted from PR URL."""

    owner: str
    repo: str
    pr_number: int
    url: str


class AnalyzeRequest(BaseModel):
    """Request payload for /analyze endpoint."""

    pr_url: str = Field(description="GitHub PR URL (e.g., https://github.com/owner/repo/pull/123)")
    repo_path: str | None = Field(default=None, description="Optional local path to the repository")
    repo_url: str | None = Field(
        default=None, description="Repository URL for cloning if repo_path not provided"
    )
    ai_provider: Literal["claude", "gemini", "cursor"] | None = Field(
        default=None, description="AI provider (overrides env var)"
    )
    ai_model: str | None = Field(default=None, description="AI model (overrides env var)")

    @field_validator("ai_model")
    @classmethod
    def validate_ai_model(cls, v: str | None) -> str | None:
        """Validate ai_model contains only safe characters."""
        if v is None:
            return v
        if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9._:/-]*$", v):
            msg = (
                "ai_model must start with an alphanumeric character and contain only "
                "alphanumeric characters, dots, hyphens, underscores, colons, and slashes"
            )
            raise ValueError(msg)
        return v

    ai_cli_timeout: Annotated[int, Field(gt=0)] | None = Field(
        default=None, description="AI CLI timeout in minutes"
    )
    github_token: str | None = Field(
        default=None,
        description="GitHub token (overrides env var)",
        json_schema_extra={"format": "password"},
    )
    test_patterns: list[str] | None = Field(
        default=None, description="Glob patterns for test files"
    )
    post_comment: bool | None = Field(default=None, description="Whether to post PR comment")

    @field_validator("pr_url")
    @classmethod
    def validate_pr_url(cls, v: str) -> str:
        """Validate that pr_url matches the expected GitHub PR URL pattern."""
        pattern = r"^https://github\.com/[\w.\-]+/[\w.\-]+/pull/\d+$"
        if not re.match(pattern, v):
            msg = (
                f"Invalid GitHub PR URL: '{v}'. "
                "Expected format: https://github.com/owner/repo/pull/123"
            )
            raise ValueError(msg)
        return v

    def parse_pr_info(self) -> PRInfo:
        """Extract owner, repo, and PR number from the validated pr_url."""
        parts = self.pr_url.rstrip("/").split("/")
        return PRInfo(
            owner=parts[-4],
            repo=parts[-3],
            pr_number=int(parts[-1]),
            url=self.pr_url,
        )


class TestRecommendation(BaseModel):
    """A single test recommendation."""

    test_file: str = Field(description="Path to the test file")
    test_name: str | None = Field(
        default=None, description="Specific test name/class if applicable"
    )
    reason: str = Field(description="Why this test should run")
    priority: Literal["critical", "standard"] = Field(description="Test priority")
    confidence: Literal["high", "medium", "low"] = Field(description="Confidence level")


class AnalyzeResponse(BaseModel):
    """Response from /analyze endpoint."""

    pr_url: str = Field(description="The analyzed PR URL")
    ai_provider: str = Field(default="", description="AI provider used")
    ai_model: str = Field(default="", description="AI model used")
    recommendations: list[TestRecommendation] = Field(
        default_factory=list, description="Test recommendations"
    )
    summary: str = Field(default="", description="Human-readable summary")
    comment_posted: bool = Field(default=False, description="Whether a PR comment was posted")
    comment_url: str | None = Field(default=None, description="URL of the posted comment")


class TestMapping(BaseModel):
    """Mapping of a changed source file to candidate test files."""

    source_file: str = Field(description="Changed source file path")
    candidate_tests: list[str] = Field(default_factory=list, description="Related test file paths")
    mapping_reason: str = Field(default="", description="How the mapping was determined")

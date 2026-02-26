"""Core orchestration: fetch PR → map tests → call AI → format result."""

import json
import os
import re
import shutil
import tempfile
from pathlib import Path

from pydantic import SecretStr
from simple_logger.logger import get_logger

from pr_test_oracle.ai_client import VALID_AI_PROVIDERS, call_ai_cli
from pr_test_oracle.config import Settings
from pr_test_oracle.github_client import GitHubClient
from pr_test_oracle.models import (
    AnalyzeRequest,
    AnalyzeResponse,
    TestMapping,
    TestRecommendation,
)
from pr_test_oracle.test_mapper import TestMapper

logger = get_logger(name=__name__, level=os.environ.get("LOG_LEVEL", "INFO"))


def _resolve_ai_config(body: AnalyzeRequest, settings: Settings) -> tuple[str, str]:
    """Resolve AI provider and model from request or settings.

    Request values take precedence over settings/env vars.

    Returns:
        Tuple of (ai_provider, ai_model).

    Raises:
        ValueError: If provider or model is not configured.
    """
    provider = body.ai_provider or settings.ai_provider or ""
    model = body.ai_model or settings.ai_model or ""
    if not provider:
        msg = (
            "No AI provider configured. Set AI_PROVIDER env var or pass "
            f"ai_provider in request body. Valid providers: {', '.join(sorted(VALID_AI_PROVIDERS))}"
        )
        raise ValueError(msg)
    if not model:
        msg = "No AI model configured. Set AI_MODEL env var or pass ai_model in request body."
        raise ValueError(msg)
    return provider, model


def _merge_settings(body: AnalyzeRequest, settings: Settings) -> Settings:
    """Create a copy of settings with per-request overrides applied.

    Request values take precedence over environment variable defaults.
    Only non-None request values are applied as overrides.
    """
    overrides: dict = {}

    direct_fields = [
        "ai_provider",
        "ai_model",
        "ai_cli_timeout",
        "test_patterns",
        "post_comment",
    ]
    for field in direct_fields:
        value = getattr(body, field, None)
        if value is not None:
            overrides[field] = value

    # SecretStr field needs wrapping
    if body.github_token is not None:
        overrides["github_token"] = SecretStr(body.github_token)

    if overrides:
        merged_data = settings.model_dump(mode="python") | overrides
        # model_dump(mode="python") keeps SecretStr objects as-is,
        # but model_validate would double-wrap them. Extract raw values first.
        if "github_token" not in overrides and merged_data.get("github_token") is not None:
            token = merged_data["github_token"]
            if isinstance(token, SecretStr):
                merged_data["github_token"] = token.get_secret_value()
        return Settings.model_validate(merged_data)
    return settings


def _build_ai_prompt(
    pr_diff: str,
    test_mappings: list[TestMapping],
    test_contents: dict[str, str],
) -> str:
    """Build the AI prompt for test recommendation analysis.

    Includes PR diff, pre-computed test mappings, and test file contents.
    """
    parts: list[str] = []

    parts.append(
        "You are an expert test engineer. Analyze this PR diff and recommend "
        "which tests should run to verify the changes.\n"
    )

    parts.append("## PR Diff\n")
    parts.append(pr_diff)
    parts.append("\n")

    parts.append("## Pre-computed Test Mappings\n")
    parts.append(
        "Static analysis has identified these potential test file matches for the changed files:\n"
    )
    for mapping in test_mappings:
        parts.append(f"\n### {mapping.source_file}")
        parts.append(f"Mapping reason: {mapping.mapping_reason}")
        if mapping.candidate_tests:
            parts.extend(f"  - {test}" for test in mapping.candidate_tests)
        else:
            parts.append("  (no direct mapping found)")
    parts.append("\n")

    if test_contents:
        parts.append("## Test File Contents\n")
        parts.append(
            "Here are the contents of candidate test files so you can understand what they test:\n"
        )
        for path, content in test_contents.items():
            parts.append(f"\n### {path}\n```python\n{content}\n```\n")

    parts.append("## Instructions\n")
    parts.append(
        """Analyze the PR changes and return your recommendations as a JSON array.

For each recommended test, provide:
- test_file: path to the test file
- test_name: specific test class/function if applicable (null if the whole file should run)
- reason: why this test should run (be specific about the connection to the PR changes)
- priority: "critical" (directly tests changed code) or "standard" (regression safety)
- confidence: "high", "medium", or "low"

Your response must be ONLY a valid JSON array. No text before or after. No markdown code blocks.

Example:
[
  {
    "test_file": "tests/test_auth.py",
    "test_name": "TestAuth::test_login_flow",
    "reason": "Changed auth middleware directly affects login flow",
    "priority": "critical",
    "confidence": "high"
  }
]
"""
    )

    return "\n".join(parts)


def _parse_ai_response(raw_text: str) -> list[TestRecommendation]:
    """Parse AI CLI JSON response into TestRecommendation list.

    Handles common AI response quirks: markdown code blocks, surrounding text.
    """
    text = raw_text.strip()

    # Try parsing directly
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return [TestRecommendation(**item) for item in data]
    except (json.JSONDecodeError, TypeError, KeyError, ValueError):
        pass

    # Try extracting from markdown code block
    blocks = re.findall(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    for block in blocks:
        stripped_block = block.strip()
        try:
            data = json.loads(stripped_block)
            if isinstance(data, list):
                return [TestRecommendation(**item) for item in data]
        except (json.JSONDecodeError, TypeError, KeyError, ValueError):
            continue

    # Try finding JSON array by bracket matching
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        try:
            data = json.loads(text[start : end + 1])
            if isinstance(data, list):
                return [TestRecommendation(**item) for item in data]
        except (json.JSONDecodeError, TypeError, KeyError, ValueError):
            pass

    logger.warning("Failed to parse AI response as JSON array, returning empty recommendations")
    return []


def _format_pr_comment(
    recommendations: list[TestRecommendation],
    ai_provider: str,
    ai_model: str,
) -> str:
    """Format test recommendations as a PR comment in markdown."""
    parts: list[str] = []

    parts.append("## Test Recommendations\n")
    parts.append("Based on analysis of the PR changes, here are the recommended tests to run:\n")

    critical = [r for r in recommendations if r.priority == "critical"]
    standard = [r for r in recommendations if r.priority == "standard"]

    if critical:
        parts.append("### Critical (directly affected)")
        parts.append("| Test | Reason | Confidence |")
        parts.append("|------|--------|------------|")
        for rec in critical:
            test_name = f"`{rec.test_file}"
            if rec.test_name:
                test_name += f"::{rec.test_name}"
            test_name += "`"
            parts.append(f"| {test_name} | {rec.reason} | {rec.confidence.capitalize()} |")
        parts.append("")

    if standard:
        parts.append("### Standard (regression safety)")
        parts.append("| Test | Reason | Confidence |")
        parts.append("|------|--------|------------|")
        for rec in standard:
            test_name = f"`{rec.test_file}"
            if rec.test_name:
                test_name += f"::{rec.test_name}"
            test_name += "`"
            parts.append(f"| {test_name} | {rec.reason} | {rec.confidence.capitalize()} |")
        parts.append("")

    if not recommendations:
        parts.append("No specific test recommendations identified.\n")

    # Summary
    parts.append("### Summary")
    total = len(recommendations)
    parts.append(
        f"- **{total} tests** recommended ({len(critical)} critical, {len(standard)} standard)"
    )
    parts.append(f"- AI Provider: {ai_provider.capitalize()} ({ai_model})")

    return "\n".join(parts)


async def analyze_pr(
    body: AnalyzeRequest,
    settings: Settings,
) -> AnalyzeResponse:
    """Analyze a PR and return test recommendations.

    This is the main orchestration function:
    1. Parse PR URL to extract owner/repo/number
    2. Fetch PR diff and changed files from GitHub
    3. Map changed files to candidate test files (static analysis)
    4. Send PR diff + test mapping + test contents to AI
    5. Parse AI response into structured recommendations
    6. Optionally post comment on PR
    7. Return response

    Args:
        body: The analyze request.
        settings: Application settings (already merged with request overrides).

    Returns:
        AnalyzeResponse with recommendations and metadata.
    """
    # Resolve AI config
    ai_provider, ai_model = _resolve_ai_config(body, settings)

    # Parse PR info
    pr_info = body.parse_pr_info()
    logger.info("Analyzing PR #%d in %s/%s", pr_info.pr_number, pr_info.owner, pr_info.repo)

    # Create GitHub client
    github_token = body.github_token or settings.github_token.get_secret_value()

    gh_client = GitHubClient(token=github_token)

    # Fetch PR data (diff and files in parallel would be nice, but diff contains file info)
    pr_diff = await gh_client.get_pr_diff(pr_info)
    changed_files = await gh_client.get_pr_files(pr_info)

    logger.info("PR has %d changed files", len(changed_files))

    # Determine repo path for test mapping
    repo_path = body.repo_path
    cleanup_repo = False

    try:
        if not repo_path:
            # Clone the repo to a temp directory
            repo_path = tempfile.mkdtemp(prefix="pr-test-oracle-")
            cleanup_repo = True
            await gh_client.clone_repo(pr_info.owner, pr_info.repo, repo_path)

        # Map changed files to test files
        test_patterns = body.test_patterns or settings.test_patterns
        mapper = TestMapper(repo_path, test_patterns)
        test_mappings = mapper.map_changed_files(changed_files)

        # Collect all candidate test files
        all_candidates: set[str] = set()
        for mapping in test_mappings:
            all_candidates.update(mapping.candidate_tests)

        # Read test file contents for AI context
        test_contents = mapper.get_test_file_contents(sorted(all_candidates))

        # Build AI prompt
        prompt = _build_ai_prompt(pr_diff, test_mappings, test_contents)

        # Call AI
        ai_cli_timeout = body.ai_cli_timeout or settings.ai_cli_timeout
        success, output = await call_ai_cli(
            prompt=prompt,
            cwd=Path(repo_path),
            ai_provider=ai_provider,
            ai_model=ai_model,
            ai_cli_timeout=ai_cli_timeout,
        )

        if not success:
            logger.error("AI CLI call failed: %s", output)
            return AnalyzeResponse(
                pr_url=body.pr_url,
                ai_provider=ai_provider,
                ai_model=ai_model,
                summary=f"AI analysis failed: {output}",
            )

        # Parse AI response
        recommendations = _parse_ai_response(output)

        critical_count = sum(1 for r in recommendations if r.priority == "critical")
        standard_count = sum(1 for r in recommendations if r.priority == "standard")

        logger.info(
            "AI recommended %d tests (%d critical, %d standard)",
            len(recommendations),
            critical_count,
            standard_count,
        )

        # Build summary
        summary = (
            f"{len(recommendations)} tests recommended "
            f"({critical_count} critical, {standard_count} standard)"
        )

        # Post PR comment if enabled
        should_post = body.post_comment if body.post_comment is not None else settings.post_comment
        comment_posted = False
        comment_url = None

        if should_post and recommendations:
            comment_body = _format_pr_comment(recommendations, ai_provider, ai_model)
            try:
                comment_url = await gh_client.post_comment(pr_info, comment_body)
                comment_posted = True
                logger.info("Posted PR comment: %s", comment_url)
            except RuntimeError:
                logger.exception("Failed to post PR comment")

        return AnalyzeResponse(
            pr_url=body.pr_url,
            ai_provider=ai_provider,
            ai_model=ai_model,
            recommendations=recommendations,
            summary=summary,
            comment_posted=comment_posted,
            comment_url=comment_url,
        )

    finally:
        if cleanup_repo and repo_path:
            shutil.rmtree(repo_path, ignore_errors=True)
            logger.debug("Cleaned up temporary repo at %s", repo_path)

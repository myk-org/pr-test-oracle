# PR Test Oracle

AI-powered service that analyzes GitHub pull requests and recommends which tests to run.

PR Test Oracle is a FastAPI service that takes a GitHub PR URL, fetches the diff, maps changed files to test files using static analysis, then sends the context to an AI provider for intelligent test recommendations. Results are returned as structured JSON and optionally posted as a PR comment. The entire flow is synchronous and stateless -- no database, no async job tracking, no background workers.

## Architecture

```
POST /analyze
     |
     v
Parse PR URL (owner/repo/number)
     |
     v
Fetch PR diff and changed files (gh CLI)
     |
     v
Clone repo (if no local path provided)
     |
     v
Static analysis: map changed files to candidate test files
     |
     v
Build prompt: diff + test mappings + test file contents
     |
     v
Call AI CLI (claude / gemini / cursor)
     |
     v
Parse AI JSON response into structured recommendations
     |
     v
Post PR comment (optional, via gh CLI)
     |
     v
Return AnalyzeResponse JSON
```

Each request is fully self-contained. The service clones the repository to a temporary directory when no local path is provided, and cleans it up after the request completes.

## Quick Start

### Prerequisites

- Python 3.12 or later
- [uv](https://docs.astral.sh/uv/) package manager
- [GitHub CLI (gh)](https://cli.github.com/) installed and authenticated
- At least one AI CLI installed: `claude`, `gemini`, or `agent` (Cursor)

### Install

```bash
uv sync --extra dev
```

### Run

```bash
uv run pr-test-oracle
```

The server starts on `http://0.0.0.0:8000`. Set `DEBUG=true` to enable auto-reload during development.

### Test it

```bash
curl -X POST http://localhost:8000/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "pr_url": "https://github.com/owner/repo/pull/123",
    "ai_provider": "claude",
    "ai_model": "sonnet"
  }'
```

## API Reference

### POST /analyze

Analyze a PR and return test recommendations.

#### Request Payload

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `pr_url` | string | Yes | GitHub PR URL (e.g., `https://github.com/owner/repo/pull/123`) |
| `repo_path` | string | No | Local path to the repository. If omitted, the repo is cloned to a temp directory. |
| `repo_url` | string | No | Repository URL for cloning if `repo_path` is not provided. |
| `ai_provider` | string | No | AI provider: `"claude"`, `"gemini"`, or `"cursor"`. Overrides the `AI_PROVIDER` env var. |
| `ai_model` | string | No | AI model name (e.g., `"sonnet"`, `"gemini-2.5-pro"`). Overrides the `AI_MODEL` env var. |
| `ai_cli_timeout` | integer | No | AI CLI timeout in minutes (must be > 0). Overrides the `AI_CLI_TIMEOUT` env var. |
| `github_token` | string | No | GitHub token for API access. Overrides the `GITHUB_TOKEN` env var. |
| `test_patterns` | list[string] | No | Glob patterns for test file discovery (e.g., `["tests/**/*.py"]`). Overrides the `TEST_PATTERNS` env var. |
| `post_comment` | boolean | No | Whether to post a PR comment with recommendations. Overrides the `POST_COMMENT` env var. |

#### Response Payload

| Field | Type | Description |
|-------|------|-------------|
| `pr_url` | string | The analyzed PR URL |
| `ai_provider` | string | AI provider that was used |
| `ai_model` | string | AI model that was used |
| `recommendations` | list | Array of test recommendation objects |
| `recommendations[].test_file` | string | Path to the test file |
| `recommendations[].test_name` | string or null | Specific test class/function, or null if the whole file should run |
| `recommendations[].reason` | string | Why this test should run |
| `recommendations[].priority` | string | `"critical"` (directly tests changed code) or `"standard"` (regression safety) |
| `recommendations[].confidence` | string | `"high"`, `"medium"`, or `"low"` |
| `summary` | string | Human-readable summary (e.g., `"5 tests recommended (2 critical, 3 standard)"`) |
| `comment_posted` | boolean | Whether a PR comment was posted |
| `comment_url` | string or null | URL of the posted comment, if applicable |

#### Example curl Command

```bash
curl -X POST http://localhost:8000/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "pr_url": "https://github.com/myorg/myrepo/pull/42",
    "ai_provider": "claude",
    "ai_model": "sonnet",
    "post_comment": true,
    "test_patterns": ["tests/**/*.py"]
  }'
```

#### Example Response

```json
{
  "pr_url": "https://github.com/myorg/myrepo/pull/42",
  "ai_provider": "claude",
  "ai_model": "sonnet",
  "recommendations": [
    {
      "test_file": "tests/test_auth.py",
      "test_name": "TestAuth::test_login_flow",
      "reason": "Changed auth middleware directly affects login flow",
      "priority": "critical",
      "confidence": "high"
    },
    {
      "test_file": "tests/test_utils.py",
      "test_name": null,
      "reason": "Utility functions used by modified module",
      "priority": "standard",
      "confidence": "medium"
    }
  ],
  "summary": "2 tests recommended (1 critical, 1 standard)",
  "comment_posted": true,
  "comment_url": "https://github.com/myorg/myrepo/pull/42#issuecomment-123456"
}
```

### GET /health

Simple health check endpoint.

```bash
curl http://localhost:8000/health
```

Response:

```json
{"status": "healthy"}
```

## Configuration

All settings are loaded from environment variables (or a `.env` file). Every environment variable can also be overridden per-request in the JSON payload.

| Variable | Description | Default | Request Override Field |
|----------|-------------|---------|----------------------|
| `GITHUB_TOKEN` | GitHub token for `gh` CLI authentication | None (uses `gh` CLI's own auth) | `github_token` |
| `AI_PROVIDER` | AI provider to use (`claude`, `gemini`, `cursor`) | None (required) | `ai_provider` |
| `AI_MODEL` | AI model name | None (required) | `ai_model` |
| `AI_CLI_TIMEOUT` | AI CLI timeout in minutes | `10` | `ai_cli_timeout` |
| `TEST_PATTERNS` | JSON array of glob patterns for test files | `["tests/**/*.py", "test_*.py"]` | `test_patterns` |
| `POST_COMMENT` | Post recommendations as a PR comment | `true` | `post_comment` |
| `PROMPT_FILE` | Path to a custom prompt file | `/app/PROMPT.md` | -- |
| `LOG_LEVEL` | Logging level | `INFO` | -- |
| `DEBUG` | Enable uvicorn auto-reload | `false` | -- |

Request payload values always take precedence over environment variable defaults. This per-request override design allows a single service instance to handle requests with different providers, models, and tokens.

## AI Providers

PR Test Oracle integrates with AI providers through their CLI tools rather than SDK libraries. This keeps the Python dependency footprint minimal and delegates authentication entirely to each CLI.

| Provider | CLI Binary | Command Pattern | Auth Method |
|----------|-----------|-----------------|-------------|
| `claude` | `claude` | `claude --model <model> --dangerously-skip-permissions -p` | Claude CLI manages its own auth |
| `gemini` | `gemini` | `gemini --model <model> --yolo` | Gemini CLI manages its own auth |
| `cursor` | `agent` | `agent --force --model <model> --print --workspace <path>` | Cursor Agent CLI manages its own auth |

The prompt is sent via stdin to the AI CLI process. The AI response (expected to be a JSON array) is captured from stdout. If the CLI returns a non-zero exit code, the error is captured from stderr.

The timeout for AI CLI calls is configurable via `AI_CLI_TIMEOUT` (in minutes, default 10). A maximum of 10 concurrent AI calls is enforced.

## GitHub Action Usage

PR Test Oracle ships as a composite GitHub Action. It sends a request to a running PR Test Oracle service instance.

### Action Inputs

| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `oracle_url` | Yes | -- | URL of the PR Test Oracle service |
| `ai_provider` | No | `claude` | AI provider to use |
| `ai_model` | No | -- | AI model to use |
| `test_patterns` | No | -- | JSON array of test file glob patterns |
| `post_comment` | No | `true` | Whether to post a PR comment |
| `github_token` | No | `${{ github.token }}` | GitHub token for API access |

### Example Workflow

```yaml
name: PR Test Oracle
on:
  pull_request:
    types: [opened, synchronize]

jobs:
  analyze:
    runs-on: ubuntu-latest
    steps:
      - uses: myk-org/pr-test-oracle@main
        with:
          oracle_url: https://your-oracle-instance.example.com
          ai_provider: claude
          ai_model: sonnet
```

The action constructs a JSON payload from the inputs, sends it to the `/analyze` endpoint, and logs both the request and response. It fails the step if the service returns an HTTP 400 or higher status code.

## PR Comment Format

When `post_comment` is enabled and the AI returns recommendations, the service posts a markdown comment on the PR. The comment is organized by priority level with a summary at the bottom.

Example comment:

```markdown
## Test Recommendations

Based on analysis of the PR changes, here are the recommended tests to run:

### Critical (directly affected)
| Test | Reason | Confidence |
|------|--------|------------|
| `tests/test_auth.py::TestAuth::test_login_flow` | Changed auth middleware directly affects login flow | High |
| `tests/test_auth.py::TestAuth::test_token_refresh` | Token refresh logic modified | High |

### Standard (regression safety)
| Test | Reason | Confidence |
|------|--------|------------|
| `tests/test_utils.py` | Utility functions used by modified module | Medium |
| `tests/test_api.py::TestAPI::test_error_handling` | Error handling path may be affected | Low |

### Summary
- **4 tests** recommended (2 critical, 2 standard)
- AI Provider: Claude (sonnet)
```

## Test Mapping

Before sending context to the AI, PR Test Oracle performs static analysis to map changed source files to candidate test files. This narrows the search space and gives the AI concrete starting points.

The mapper uses these strategies in order:

1. **Naming convention** -- A changed file `auth.py` maps to `test_auth.py` or `auth_test.py` in any test directory.

2. **Module name matching** -- If the source file stem (e.g., `github_client`) appears anywhere in a test file name (e.g., `test_github_client.py`), it is considered a candidate.

3. **Directory structure mapping** -- Parallel directory structures are recognized. For example, `src/pr_test_oracle/analyzer.py` maps to `tests/test_analyzer.py` after stripping the `src/` and package name prefixes.

4. **Config file detection** -- Changes to project config files (`pyproject.toml`, `setup.py`, `setup.cfg`, `tox.ini`, `pytest.ini`, `conftest.py`, `.env`, `requirements.txt`, `requirements-dev.txt`, `Makefile`) are flagged as affecting all tests.

5. **Non-Python files** -- Files without a `.py` extension that are not config files produce no static mapping. They are included in the AI prompt with a note that the AI should determine relevant tests from the diff context.

Test files named `__init__.py` and `conftest.py` are excluded from discovery results.

## Docker

### Build

```bash
docker build -t pr-test-oracle .
```

### Run

```bash
docker run -p 8000:8000 \
  -e AI_PROVIDER=claude \
  -e AI_MODEL=sonnet \
  pr-test-oracle
```

The Docker image includes all three AI CLIs (Claude, Gemini, Cursor) and the GitHub CLI pre-installed. Pass additional environment variables as needed (e.g., `GITHUB_TOKEN`).

### OpenShift Compatibility

The container is designed for OpenShift environments where containers run as an arbitrary UID with GID 0. The image uses a non-root `appuser` account, and all necessary directories have group-writable permissions. The `HOME` environment variable is explicitly set to ensure CLI tools work correctly even when the UID has no entry in `/etc/passwd`.

## Development

### Install development dependencies

```bash
uv sync --extra dev
```

### Run tests

```bash
uv run pytest tests/ -v
```

### Lint

```bash
uv run ruff check src/ tests/
```

### Format

```bash
uv run ruff format src/ tests/
```

### Type checking

```bash
uv run mypy src/
```

## Project Structure

```
pr-test-oracle/
  action.yml                          # GitHub Action definition (composite)
  Dockerfile                          # Multi-stage build with AI CLIs
  pyproject.toml                      # Project metadata and tool configuration
  uv.lock                            # Locked dependencies
  README.md
  src/
    pr_test_oracle/
      __init__.py
      main.py                        # FastAPI app, /analyze and /health endpoints
      config.py                      # Settings from environment variables (pydantic-settings)
      models.py                      # Request/response Pydantic models
      analyzer.py                    # Core orchestration: diff -> map -> AI -> result
      ai_client.py                   # AI CLI subprocess integration (claude/gemini/cursor)
      github_client.py               # GitHub operations via gh CLI
      test_mapper.py                 # Static analysis: source files -> candidate test files
  tests/
    __init__.py
    conftest.py
    test_ai_client.py
    test_analyzer.py
    test_github_client.py
    test_main.py
    test_models.py
    test_test_mapper.py
```

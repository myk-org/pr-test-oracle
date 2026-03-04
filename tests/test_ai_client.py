"""Tests verifying ai_client re-exports from ai-cli-runner."""

from pr_test_oracle.ai_client import (
    PROVIDER_CONFIG,
    PROVIDERS,
    VALID_AI_PROVIDERS,
    ProviderConfig,
    call_ai_cli,
    check_ai_cli_available,
    get_ai_cli_timeout,
    run_parallel_with_limit,
)


class TestReExports:
    """Verify all re-exports are available and correct types."""

    def test_valid_providers_exist(self) -> None:
        assert "claude" in VALID_AI_PROVIDERS
        assert "gemini" in VALID_AI_PROVIDERS
        assert "cursor" in VALID_AI_PROVIDERS

    def test_providers_dict(self) -> None:
        assert isinstance(PROVIDERS, dict)
        assert len(PROVIDERS) >= 3

    def test_provider_config_alias(self) -> None:
        assert PROVIDER_CONFIG is PROVIDERS

    def test_provider_config_type(self) -> None:
        config = PROVIDERS["claude"]
        assert isinstance(config, ProviderConfig)
        assert config.binary == "claude"

    def test_call_ai_cli_is_callable(self) -> None:
        assert callable(call_ai_cli)

    def test_check_ai_cli_available_is_callable(self) -> None:
        assert callable(check_ai_cli_available)

    def test_get_ai_cli_timeout_returns_int(self) -> None:
        result = get_ai_cli_timeout()
        assert isinstance(result, int)
        assert result > 0

    def test_run_parallel_with_limit_is_callable(self) -> None:
        assert callable(run_parallel_with_limit)

    async def test_unknown_provider(self) -> None:
        success, output = await call_ai_cli(
            prompt="test", ai_provider="unknown", ai_model="model"
        )
        assert success is False
        assert "Unknown" in output or "unknown" in output.lower()

    async def test_missing_model(self) -> None:
        success, output = await call_ai_cli(
            prompt="test", ai_provider="claude", ai_model=""
        )
        assert success is False
        assert "model" in output.lower()

    async def test_parallel_execution(self) -> None:
        async def coro(x: int) -> int:
            return x * 2

        results = await run_parallel_with_limit([coro(1), coro(2), coro(3)])
        assert results == [2, 4, 6]

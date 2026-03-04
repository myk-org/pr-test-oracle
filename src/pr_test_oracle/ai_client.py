"""AI CLI integration — re-exports from ai-cli-runner package."""

from ai_cli_runner import (
    PROVIDERS,
    VALID_AI_PROVIDERS,
    ProviderConfig,
    call_ai_cli,
    check_ai_cli_available,
    get_ai_cli_timeout,
    run_parallel_with_limit,
)

# Re-export PROVIDER_CONFIG as alias for backward compatibility
PROVIDER_CONFIG = PROVIDERS

__all__ = [
    "PROVIDER_CONFIG",
    "PROVIDERS",
    "ProviderConfig",
    "VALID_AI_PROVIDERS",
    "call_ai_cli",
    "check_ai_cli_available",
    "get_ai_cli_timeout",
    "run_parallel_with_limit",
]

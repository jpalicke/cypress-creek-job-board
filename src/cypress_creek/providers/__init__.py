# ABOUTME: The provider layer: one interface every model backend implements, plus typed errors.
# ABOUTME: get_provider builds one from settings. The Ollama adapter registers itself here.
from cypress_creek.providers.base import (
    Capabilities,
    CostPerMtok,
    Provider,
    StructuredResult,
    Usage,
)
from cypress_creek.providers.budget import Budget, BudgetedProvider, BudgetTracker
from cypress_creek.providers.errors import (
    BudgetExceeded,
    ContextTruncated,
    ProviderError,
    ProviderUnavailable,
    RateLimited,
    Refusal,
    SchemaViolation,
)
from cypress_creek.providers.factory import (
    REGISTRY,
    ProviderRegistry,
    UnknownProvider,
    get_provider,
)
from cypress_creek.providers.ollama import OllamaProvider
from cypress_creek.providers.retry import RetryPolicy, call_with_retry

__all__ = [
    "REGISTRY",
    "Budget",
    "BudgetExceeded",
    "BudgetTracker",
    "BudgetedProvider",
    "Capabilities",
    "ContextTruncated",
    "CostPerMtok",
    "OllamaProvider",
    "Provider",
    "ProviderError",
    "ProviderRegistry",
    "ProviderUnavailable",
    "RateLimited",
    "Refusal",
    "RetryPolicy",
    "SchemaViolation",
    "StructuredResult",
    "UnknownProvider",
    "Usage",
    "call_with_retry",
    "get_provider",
]

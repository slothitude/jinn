"""Central provider/model registry with quota tracking and fallback chains."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass


@dataclass
class ProviderProfile:
    """Configuration for a single LLM provider."""
    name: str
    base_url: str
    api_key_env: str           # e.g. "LLM_API_KEY"
    models: list[str]          # available model IDs
    rate_limit: int            # requests per window (0 = unlimited)
    rate_window_secs: int      # window duration in seconds (0 = unlimited)
    priority: int              # lower = preferred


# Default profiles — rate limits overrideable via env vars:
#   <PROVIDER>_RATE_LIMIT (e.g. ZHIPU_RATE_LIMIT=400)
#   <PROVIDER>_RATE_WINDOW (e.g. ZHIPU_RATE_WINDOW=18000)
#   <PROVIDER>_PRIORITY (e.g. ZHIPU_PRIORITY=0)
DEFAULT_PROFILES: list[ProviderProfile] = [
    ProviderProfile(
        name="zhipu",
        base_url="",  # resolved from LLM_BASE_URL env or provider.py
        api_key_env="LLM_API_KEY",
        models=["glm-5.1", "glm-5", "glm-5-turbo", "glm-4.7", "glm-4.6", "glm-4.5", "glm-4.5-air"],
        rate_limit=400,
        rate_window_secs=18000,       # 5 hours
        priority=0,                   # preferred for planning
    ),
    ProviderProfile(
        name="nvidia",
        base_url="https://integrate.api.nvidia.com/v1",
        api_key_env="NVIDIA_API_KEY",
        models=["nvidia/llama-3.1-nemotron-70b-instruct", "meta/llama-3.1-405b-instruct"],
        rate_limit=0,                 # unlimited (free tier)
        rate_window_secs=0,
        priority=1,
    ),
]


class ResourceManager:
    """Tracks quotas, builds fallback chains per agent tier."""

    def __init__(self) -> None:
        self.providers: dict[str, ProviderProfile] = {}
        self._usage: dict[str, list[float]] = {}       # provider -> [timestamps]
        self._fallback_chains: dict[str, list[tuple[str, str]]] = {}

    @classmethod
    def from_defaults(cls) -> ResourceManager:
        """Create a ResourceManager pre-loaded with all default provider profiles.

        Rate limits, windows, and priorities are overridable via env vars:
            <PROVIDER>_RATE_LIMIT  — int, requests per window
            <PROVIDER>_RATE_WINDOW — int, seconds
            <PROVIDER>_PRIORITY    — int, lower = preferred
        """
        rm = cls()
        for profile in DEFAULT_PROFILES:
            p = _apply_env_overrides(profile)
            rm.register_provider(p)
        return rm

    def register_provider(self, profile: ProviderProfile) -> None:
        self.providers[profile.name] = profile
        self._usage.setdefault(profile.name, [])
        self._rebuild_chains()

    def _rebuild_chains(self) -> None:
        """Build fallback chains for each tier based on provider priority + models."""
        sorted_providers = sorted(self.providers.values(), key=lambda p: p.priority)

        # Planning tier (ORCHESTRATOR, SUPERVISOR) — follow priority order
        planning_chain: list[tuple[str, str]] = []
        for p in sorted_providers:
            for model in p.models:
                planning_chain.append((p.name, model))

        # Worker tier — prefer nvidia first (higher priority index),
        # then planning-tier providers
        worker_chain: list[tuple[str, str]] = []
        for p in reversed(sorted_providers):
            for model in p.models:
                worker_chain.append((p.name, model))

        self._fallback_chains = {
            "ORCHESTRATOR": planning_chain,
            "SUPERVISOR": planning_chain,
            "ULTRAPLAN": planning_chain,
            "KAIROS": planning_chain,
            "BUDDY": worker_chain,
            "WORKER": worker_chain,
        }

    def get_fallback_chain(self, tier: str) -> list[tuple[str, str]]:
        return self._fallback_chains.get(tier.upper(), [])

    def check_quota(self, provider: str) -> bool:
        """Return True if provider has headroom for another request."""
        profile = self.providers.get(provider)
        if profile is None:
            return False
        if profile.rate_limit == 0:
            return True  # unlimited
        self._prune(provider, profile.rate_window_secs)
        return len(self._usage.get(provider, [])) < profile.rate_limit

    def record_usage(self, provider: str) -> None:
        self._usage.setdefault(provider, []).append(time.monotonic())

    def get_next_available(self, tier: str) -> tuple[str, str] | None:
        """Return the first (provider, model) in the fallback chain with quota."""
        chain = self.get_fallback_chain(tier)
        for provider, model in chain:
            if self.check_quota(provider):
                return provider, model
        # If all exhausted, return the first anyway (best effort)
        return chain[0] if chain else None

    def get_quota_status(self) -> dict[str, dict]:
        """Return quota info for all providers (for dashboard/debugging)."""
        status = {}
        for name, profile in self.providers.items():
            self._prune(name, profile.rate_window_secs)
            used = len(self._usage.get(name, []))
            status[name] = {
                "used": used,
                "limit": profile.rate_limit,
                "remaining": profile.rate_limit - used if profile.rate_limit > 0 else -1,
                "window_secs": profile.rate_window_secs,
            }
        return status

    def _prune(self, provider: str, window_secs: int) -> None:
        if window_secs <= 0:
            return
        now = time.monotonic()
        cutoff = now - window_secs
        timestamps = self._usage.get(provider, [])
        self._usage[provider] = [t for t in timestamps if t > cutoff]


def _apply_env_overrides(profile: ProviderProfile) -> ProviderProfile:
    """Allow env vars to override rate_limit, rate_window_secs, priority."""
    prefix = profile.name.upper()
    rate_limit = os.getenv(f"{prefix}_RATE_LIMIT")
    rate_window = os.getenv(f"{prefix}_RATE_WINDOW")
    priority = os.getenv(f"{prefix}_PRIORITY")

    return ProviderProfile(
        name=profile.name,
        base_url=profile.base_url,
        api_key_env=profile.api_key_env,
        models=profile.models,
        rate_limit=int(rate_limit) if rate_limit else profile.rate_limit,
        rate_window_secs=int(rate_window) if rate_window else profile.rate_window_secs,
        priority=int(priority) if priority else profile.priority,
    )

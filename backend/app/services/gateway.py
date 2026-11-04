"""Agent Gateway: the one path from a deployed agent to a model.

For every prompt the gateway:

1. redacts PII (the same guardrail the flow executor uses),
2. screens the prompt with the default Model Armor template (prompt injection, jailbreak),
3. picks the cheapest Gemini model that can handle the prompt's complexity,
4. calls that model and returns the text.

Prompt text is never logged. Only the model name and complexity are.
"""

import asyncio
import logging
import re
from dataclasses import dataclass
from enum import IntEnum
from functools import lru_cache
from typing import Protocol

from app.config import Settings, get_settings
from app.services.guardrails import redact_pii

logger = logging.getLogger(__name__)


class Complexity(IntEnum):
    SIMPLE = 0
    STANDARD = 1
    COMPLEX = 2


@dataclass(frozen=True)
class ModelTier:
    name: str
    handles: Complexity  # the hardest prompt this model is chosen for


# Cheapest first. The order follows relative list price. Re-check current prices before
# relying on the cost ordering; the routing only needs the order to be right.
MODEL_CATALOG: tuple[ModelTier, ...] = (
    ModelTier("gemini-2.5-flash-lite", Complexity.SIMPLE),
    ModelTier("gemini-2.5-flash", Complexity.STANDARD),
    ModelTier("gemini-2.5-pro", Complexity.COMPLEX),
)

COMPLEX_HINTS = re.compile(
    r"\b(analy[sz]e|compare|step by step|prove|debug|write (?:the )?code|plan|trade-?offs?)\b",
    re.IGNORECASE,
)
STANDARD_LENGTH = 300
COMPLEX_LENGTH = 1500


def classify(prompt: str) -> Complexity:
    if len(prompt) > COMPLEX_LENGTH or COMPLEX_HINTS.search(prompt):
        return Complexity.COMPLEX
    if len(prompt) > STANDARD_LENGTH:
        return Complexity.STANDARD
    return Complexity.SIMPLE


def choose_model(complexity: Complexity) -> ModelTier:
    for tier in MODEL_CATALOG:
        if complexity <= tier.handles:
            return tier
    return MODEL_CATALOG[-1]


class GuardrailBlocked(Exception):
    """The prompt matched a Model Armor filter. The model is never called."""


class GatewayUnavailable(Exception):
    """Screening is required but no Model Armor template is configured."""


@dataclass(frozen=True)
class ScreenVerdict:
    allowed: bool
    reason: str = ""


class PromptScreener(Protocol):
    async def screen(self, prompt: str, template: str) -> ScreenVerdict: ...


class ModelArmorScreener:
    """Model Armor ``sanitizeUserPrompt`` on the regional endpoint named in the template."""

    def __init__(self) -> None:
        from google.auth import default as google_auth_default
        from google.auth.transport.requests import AuthorizedSession

        credentials, _ = google_auth_default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        self._session = AuthorizedSession(credentials)

    def _screen_sync(self, prompt: str, template: str) -> ScreenVerdict:
        location = re.search(r"/locations/([^/]+)/", template)
        if location is None:
            raise GatewayUnavailable("Model Armor template name has no location")
        url = (
            f"https://modelarmor.{location.group(1)}.rep.googleapis.com/v1/"
            f"{template}:sanitizeUserPrompt"
        )
        response = self._session.post(url, json={"userPromptData": {"text": prompt}}, timeout=15)
        response.raise_for_status()
        result = response.json().get("sanitizationResult", {})
        if result.get("filterMatchState") == "MATCH_FOUND":
            return ScreenVerdict(False, "matched a Model Armor filter")
        return ScreenVerdict(True)

    async def screen(self, prompt: str, template: str) -> ScreenVerdict:
        return await asyncio.to_thread(self._screen_sync, prompt, template)


class ModelBackend(Protocol):
    async def generate(self, model: str, prompt: str, system_prompt: str) -> str: ...


class MockModelBackend:
    async def generate(self, model: str, prompt: str, system_prompt: str) -> str:
        return f"[mock-llm {model}] {prompt.strip()[:300]}"


class GenAIModelBackend:
    def __init__(self, client, max_tokens: int) -> None:
        self._client = client
        self._max_tokens = max_tokens

    async def generate(self, model: str, prompt: str, system_prompt: str) -> str:
        from google.genai import types

        config = types.GenerateContentConfig(
            max_output_tokens=self._max_tokens,
            system_instruction=system_prompt or None,
        )
        response = await self._client.aio.models.generate_content(
            model=model, contents=prompt, config=config
        )
        return response.text or ""


@dataclass(frozen=True)
class GatewayReply:
    text: str
    model: str
    complexity: Complexity
    screened: bool


class AgentGateway:
    def __init__(
        self,
        backend: ModelBackend,
        screener: PromptScreener | None,
        template: str,
        redact_pii_enabled: bool,
    ) -> None:
        self._backend = backend
        self._screener = screener
        self._template = template
        self._redact = redact_pii_enabled

    async def handle(
        self, prompt: str, system_prompt: str, require_screening: bool
    ) -> GatewayReply:
        if self._redact:
            prompt = redact_pii(prompt)

        screened = False
        if self._template and self._screener is not None:
            verdict = await self._screener.screen(prompt, self._template)
            if not verdict.allowed:
                logger.warning("Gateway blocked a prompt: %s", verdict.reason)
                raise GuardrailBlocked(verdict.reason)
            screened = True
        elif require_screening:
            raise GatewayUnavailable("No Model Armor template is configured")

        complexity = classify(prompt)
        tier = choose_model(complexity)
        logger.info("Gateway routed a prompt to %s (complexity=%s)", tier.name, complexity.name)
        text = await self._backend.generate(tier.name, prompt, system_prompt)
        return GatewayReply(text=text, model=tier.name, complexity=complexity, screened=screened)


def build_gateway(settings: Settings) -> AgentGateway:
    if settings.llm_provider == "mock":
        backend: ModelBackend = MockModelBackend()
        screener: PromptScreener | None = None
    else:
        from app.services.llm import _build_genai_client

        backend = GenAIModelBackend(
            _build_genai_client(settings), max_tokens=settings.llm_max_output_tokens
        )
        screener = ModelArmorScreener() if settings.model_armor_template else None
    return AgentGateway(
        backend=backend,
        screener=screener,
        template=settings.model_armor_template,
        redact_pii_enabled=settings.pii_redaction_enabled,
    )


@lru_cache
def get_gateway() -> AgentGateway:
    return build_gateway(get_settings())

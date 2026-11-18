"""Pick an adapter. Two are enough.

The OpenAI-compatible one covers OpenAI, Codex, Ollama, LM Studio and vLLM,
because they all speak the same wire format - a local model is a base_url
pointing at host.docker.internal. So the choice is Anthropic native or that.

Both build their prompt from insights/prompts/extract_insights.md, which is the
single source of truth an agent on the host reads too. There is no second copy
of the instructions in this package, and there must never be.
"""
from functools import lru_cache
from pathlib import Path

from django.conf import settings

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "extract_insights.md"


@lru_cache(maxsize=1)
def prompt_text():
    return PROMPT_PATH.read_text(encoding="utf-8")


def get_extractor():
    from insights.extractors.anthropic_api import AnthropicExtractor
    from insights.extractors.openai_compatible import OpenAICompatibleExtractor

    provider = (settings.LLM_PROVIDER or "").strip().lower()
    if provider == "anthropic":
        return AnthropicExtractor()
    if provider in {"openai_compatible", "openai", "codex", "ollama", "local"}:
        return OpenAICompatibleExtractor()
    raise ValueError(
        f"LLM_PROVIDER={provider!r} is not one of 'anthropic' or 'openai_compatible'."
    )

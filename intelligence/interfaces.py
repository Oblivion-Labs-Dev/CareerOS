"""Public contract for the intelligence service.

LLM orchestration, the story/experience corpus, gap analysis and AI-powered
career signals. Other services import ONLY from this module.
"""

from typing import Any, Protocol


class IIntelligenceService(Protocol):
    async def generate_answer(self, question: str, context: dict[str, Any] | None = None) -> dict: ...
    def load_story_corpus(self) -> list[dict[str, Any]]: ...

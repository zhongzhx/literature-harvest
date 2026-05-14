"""LLM-based relevance scorer for harvested papers.

Uses the Anthropic API to score each paper's relevance to the user's
query/topic on a 0–100 scale, based on title and abstract.

Requires the ``ANTHROPIC_API_KEY`` environment variable to be set.
"""

from __future__ import annotations

import os
import re
import time
from typing import Any, Optional

from literature_harvest.status import METADATA_ONLY

_SCORING_PROMPT = """You are a research relevance evaluator. Rate how relevant the following paper is to the user's research topic.

User's topic: {query}

Paper title: {title}
Paper abstract: {abstract}

Consider:
- Does the paper directly study the same topic/subject?
- Does it use related methods, models, or approaches?
- Is it in a closely related field or discipline?
- Would a researcher working on "{query}" find this paper useful?

Respond with ONLY a single integer between 0 and 100, where:
- 0 = completely unrelated
- 25 = tangentially related
- 50 = somewhat relevant (related field or methods)
- 75 = clearly relevant
- 100 = directly about the topic
"""


class LLMScorer:
    """Score paper relevance using the Anthropic API.

    Usage::

        scorer = LLMScorer(api_key="sk-...")
        result = scorer.score(
            title="...", abstract="...", query="RAW264.7 inflammation"
        )
        # -> {"score": 85, "raw_response": "85"}
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "claude-sonnet-4-20250514",
        max_retries: int = 2,
        delay: float = 0.5,
    ) -> None:
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.model = model
        self.max_retries = max_retries
        self.delay = delay

        if not self.api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY is not set. "
                "Set it via environment variable or pass api_key= to LLMScorer."
            )

        try:
            import anthropic
        except ImportError:
            raise ImportError(
                "The 'anthropic' package is required for LLM scoring.\n"
                "Install it with: pip install anthropic"
            ) from None

        self._client = anthropic.Anthropic(api_key=self.api_key)

    def score(
        self,
        title: str,
        abstract: str,
        query: str,
    ) -> dict[str, Any]:
        """Score a single paper's relevance.

        Returns:
            ``{"score": int, "raw_response": str, "error": None | str}``
        """
        prompt = _SCORING_PROMPT.format(
            query=query,
            title=title[:500],
            abstract=(abstract or "")[:2000],
        )

        for attempt in range(1 + self.max_retries):
            try:
                raw = self._call_api(prompt)
                score = self._parse_score(raw)
                return {"score": score, "raw_response": raw.strip(), "error": None}
            except Exception as exc:
                if attempt < self.max_retries:
                    time.sleep(self.delay)
                    continue
                return {"score": 0, "raw_response": "", "error": str(exc)}

    def score_batch(
        self,
        papers: list[dict[str, Any]],
        query: str,
        batch_size: int = 10,
    ) -> list[dict[str, Any]]:
        """Score a list of papers and return them sorted by score descending.

        Each paper dict should have at minimum ``title`` and optionally
        ``abstract``, ``doi``, ``authors``, ``journal``, ``year``.

        Returns the same dicts with ``relevance_score`` and
        ``abstract_summary`` keys added, sorted by score descending.
        """
        results: list[dict[str, Any]] = []
        for i, paper in enumerate(papers):
            title = str(paper.get("title", "") or "")
            abstract = str(paper.get("abstract", "") or "")[:2000]
            result = self.score(title, abstract, query)
            paper["relevance_score"] = result["score"]
            paper["abstract_summary"] = abstract[:300] + "..." if len(abstract) > 300 else abstract
            paper["scoring_error"] = result["error"]
            results.append(paper)
            if (i + 1) % batch_size == 0:
                print(f"  Scored {i + 1}/{len(papers)} papers...")

        results.sort(key=lambda p: p.get("relevance_score", 0), reverse=True)
        return results

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _call_api(self, prompt: str) -> str:
        """Call the Anthropic API and return the raw response text."""
        message = self._client.messages.create(
            model=self.model,
            max_tokens=64,
            temperature=0.0,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text if message.content else ""

    @staticmethod
    def _parse_score(raw: str) -> int:
        """Extract an integer score from the LLM response."""
        cleaned = raw.strip()
        # Guard: if the response is suspiciously long, it's likely an error
        if len(cleaned) > 20:
            # Try to extract a score from the first token only
            first_token = cleaned.split()[0] if cleaned.split() else cleaned
            try:
                val = int(first_token)
                if 0 <= val <= 100:
                    return val
            except ValueError:
                pass
            return 0
        # Try direct integer parse for clean responses
        try:
            val = int(cleaned)
            if 0 <= val <= 100:
                return val
        except ValueError:
            pass
        # Fall back to regex
        numbers = re.findall(r"\b(\d{1,3})\b", cleaned)
        for num in numbers:
            val = int(num)
            if 0 <= val <= 100:
                return val
        return 0


# ------------------------------------------------------------------
# Convenience: score without instantiating (uses env var)
# ------------------------------------------------------------------


def score_relevance(
    title: str,
    abstract: str,
    query: str,
) -> int:
    """One-shot relevance score, reading API key from environment."""
    scorer = LLMScorer()
    result = scorer.score(title, abstract, query)
    return result["score"]

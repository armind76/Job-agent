"""Classify a job posting into a priority tier using Claude."""
import json
import re
from dataclasses import dataclass
from typing import Optional

from config.job_targets import (
    EXCLUSION_KEYWORDS,
    TIER1_KEYWORDS,
    TIER2_KEYWORDS,
    TIER3_KEYWORDS,
    TIER4_KEYWORDS,
)
from job_agent.ai.client import AIClient
from job_agent.db.models import Job


@dataclass
class ClassificationResult:
    tier: int            # 1–4 (1 = highest priority)
    score: float         # 0.0–1.0 within tier
    reason: str
    skip: bool = False   # True if job should be excluded


_SYSTEM = """You are a job classification assistant for an experienced C++ systems software engineer in New York City.
Your task: classify a job posting into one of 4 priority tiers based on relevance.

Tier definitions:
1 = C++ systems / low-latency / HFT / trading systems / kernel (HIGHEST priority)
2 = Low-level infrastructure / embedded / compilers / distributed systems / Rust
3 = Graphics / GPU / simulation / HPC / rendering
4 = General SWE / backend / Go / Java / Python (LOWEST priority, still relevant)

Return a JSON object with exactly these keys:
{
  "tier": <1|2|3|4>,
  "score": <float 0.0-1.0, finer-grained ranking within the tier>,
  "reason": "<1-2 sentence explanation>",
  "skip": <true if job is clearly irrelevant or matches exclusion criteria, false otherwise>
}

Return ONLY the JSON object, no markdown, no extra text."""


def _keyword_prescreen(title: str, description: str) -> Optional[ClassificationResult]:
    """Fast keyword-based pre-screening to avoid unnecessary Claude calls."""
    text = f"{title} {description}".lower()

    # Hard exclusion
    for kw in EXCLUSION_KEYWORDS:
        if kw in text:
            return ClassificationResult(
                tier=4, score=0.0,
                reason=f"Excluded: matched exclusion keyword '{kw}'",
                skip=True,
            )

    # Check tiers by keyword presence (heuristic, Claude refines this)
    tier1_hits = sum(1 for kw in TIER1_KEYWORDS if kw in text)
    tier2_hits = sum(1 for kw in TIER2_KEYWORDS if kw in text)
    tier3_hits = sum(1 for kw in TIER3_KEYWORDS if kw in text)

    # If clearly tier 1 by keywords, still let Claude confirm score/reason
    # Only skip Claude for obvious exclusions
    return None


def classify_job(job: Job, client: AIClient) -> ClassificationResult:
    """Classify a job posting. Returns ClassificationResult."""
    # Quick pre-screen
    prescan = _keyword_prescreen(job.title, job.description or "")
    if prescan and prescan.skip:
        return prescan

    desc_snippet = (job.description or "")[:3000]
    prompt = f"""Job Title: {job.title}
Company: {job.company}
Location: {job.location or 'Not specified'}
Source: {job.source}

Job Description:
{desc_snippet}

Classify this job posting per the instructions."""

    try:
        response = client.complete(prompt, system=_SYSTEM, max_tokens=256)
        # Extract JSON even if there's surrounding text
        match = re.search(r'\{[^{}]+\}', response, re.DOTALL)
        if match:
            data = json.loads(match.group())
        else:
            data = json.loads(response)

        return ClassificationResult(
            tier=int(data.get("tier", 4)),
            score=float(data.get("score", 0.5)),
            reason=str(data.get("reason", "")),
            skip=bool(data.get("skip", False)),
        )
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        # Fallback: keyword-based tier
        text = f"{job.title} {job.description or ''}".lower()
        if any(kw in text for kw in TIER1_KEYWORDS):
            return ClassificationResult(tier=1, score=0.5, reason="Keyword match (fallback)")
        if any(kw in text for kw in TIER2_KEYWORDS):
            return ClassificationResult(tier=2, score=0.5, reason="Keyword match (fallback)")
        if any(kw in text for kw in TIER3_KEYWORDS):
            return ClassificationResult(tier=3, score=0.5, reason="Keyword match (fallback)")
        return ClassificationResult(tier=4, score=0.3, reason=f"Classification failed: {e}")

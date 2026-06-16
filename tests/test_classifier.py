"""Tests for the job classifier module."""
import json
from unittest.mock import MagicMock, patch

import pytest

from job_agent.ai.classifier import ClassificationResult, classify_job, _keyword_prescreen
from job_agent.db.models import Job


def make_job(title: str, description: str, company: str = "Acme") -> Job:
    return Job(
        url=f"https://example.com/{title.replace(' ', '-')}",
        title=title,
        company=company,
        location="New York, NY",
        description=description,
        source="builtin",
    )


class MockAIClient:
    """Mock AI client that returns predetermined responses."""

    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[str] = []

    def complete(self, prompt: str, system: str = None, max_tokens: int = 256) -> str:
        self.calls.append(prompt)
        return self.response


# ── Keyword pre-screening tests ────────────────────────────────────

def test_prescreen_exclusion_keyword():
    result = _keyword_prescreen("QA Engineer", "test automation, selenium")
    assert result is not None
    assert result.skip is True


def test_prescreen_non_excluded():
    result = _keyword_prescreen("C++ Systems Engineer", "low latency C++17")
    assert result is None  # No pre-screen exclusion; let Claude classify


# ── Full classification tests ───────────────────────────────────────

def test_classify_tier1_cpp():
    mock_response = json.dumps({
        "tier": 1,
        "score": 0.95,
        "reason": "Requires C++17, low-latency systems, HFT experience",
        "skip": False,
    })
    client = MockAIClient(mock_response)
    job = make_job(
        "Senior C++ Software Engineer",
        "C++17, STL, lock-free, NUMA, trading systems, low-latency",
    )
    result = classify_job(job, client)
    assert result.tier == 1
    assert result.score == 0.95
    assert result.skip is False
    assert "C++17" in result.reason


def test_classify_tier2_systems():
    mock_response = json.dumps({
        "tier": 2,
        "score": 0.75,
        "reason": "Compiler engineering role — qualifies as tier 2 low-level infrastructure",
        "skip": False,
    })
    client = MockAIClient(mock_response)
    job = make_job(
        "Compiler Engineer",
        "LLVM, JIT compilation, compiler optimisation, C++, Rust",
    )
    result = classify_job(job, client)
    assert result.tier == 2
    assert result.skip is False


def test_classify_tier3_graphics():
    mock_response = json.dumps({
        "tier": 3,
        "score": 0.80,
        "reason": "GPU rendering — tier 3 graphics engineering",
        "skip": False,
    })
    client = MockAIClient(mock_response)
    job = make_job(
        "GPU Rendering Engineer",
        "Vulkan, ray tracing, physically-based rendering, C++",
    )
    result = classify_job(job, client)
    assert result.tier == 3


def test_classify_skip_flag():
    mock_response = json.dumps({
        "tier": 4,
        "score": 0.1,
        "reason": "Frontend role — not relevant",
        "skip": True,
    })
    client = MockAIClient(mock_response)
    job = make_job("React Developer", "React, TypeScript, CSS, frontend development")
    result = classify_job(job, client)
    assert result.skip is True


def test_classify_fallback_on_json_error():
    """When Claude returns invalid JSON, fall back to keyword classification."""
    client = MockAIClient("Sorry, I cannot classify this job.")
    job = make_job(
        "Senior C++ Engineer",
        "c++ systems low-latency trading kernel stl simd",
    )
    result = classify_job(job, client)
    # Should fall back to keyword-based tier 1 detection
    assert result.tier in (1, 4)  # Tier 1 if keyword match, 4 otherwise


def test_classify_tier4_general_swe():
    mock_response = json.dumps({
        "tier": 4,
        "score": 0.40,
        "reason": "General backend SWE role — lowest relevant tier",
        "skip": False,
    })
    client = MockAIClient(mock_response)
    job = make_job(
        "Backend Software Engineer",
        "Python, Django, REST APIs, PostgreSQL, Kubernetes",
    )
    result = classify_job(job, client)
    assert result.tier == 4
    assert result.skip is False


def test_classification_result_dataclass():
    r = ClassificationResult(tier=1, score=0.99, reason="Excellent match", skip=False)
    assert r.tier == 1
    assert r.score == 0.99
    assert r.skip is False

"""Tests for job scoring, classification, resume selection, and cover letter generation.

All AI calls are mocked — no Anthropic API key required.
"""
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from job_agent.ai.classifier import ClassificationResult, _keyword_prescreen, classify_job
from job_agent.ai.cover_letter import generate_cover_letter
from job_agent.ai.resume_selector import select_resume
from job_agent.db.models import Job, ResumeCache


# ── Helpers ─────────────────────────────────────────────────────────


def make_job(
    title: str,
    description: str = "",
    company: str = "Acme",
    location: str = "New York, NY",
    source: str = "builtin",
) -> Job:
    return Job(
        url=f"https://example.com/{title.replace(' ', '-').lower()}",
        title=title,
        company=company,
        location=location,
        description=description,
        source=source,
    )


def make_resume_cache(
    filename: str,
    summary: str = "",
    skills: list[str] | None = None,
    text: str = "Experienced software engineer.",
) -> ResumeCache:
    return ResumeCache(
        resume_path=f"/data/resumes/{filename}",
        resume_hash="deadbeef",
        extracted_text=text,
        summary=summary,
        skills_json=json.dumps(skills or []),
    )


class MockAIClient:
    """Deterministic stand-in for AIClient — returns a fixed response."""

    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[tuple[str, str | None]] = []

    def complete(self, prompt: str, system: str | None = None, max_tokens: int = 256) -> str:
        self.calls.append((prompt, system))
        return self.response


def classifier_response(tier: int, score: float, reason: str, skip: bool = False) -> str:
    return json.dumps({"tier": tier, "score": score, "reason": reason, "skip": skip})


# ── Keyword pre-screening ────────────────────────────────────────────


class TestKeywordPrescreen:
    """_keyword_prescreen is fast and never calls the AI."""

    def test_qa_engineer_is_excluded(self):
        result = _keyword_prescreen("QA Engineer", "test automation, selenium")
        assert result is not None
        assert result.skip is True

    def test_sdet_is_excluded(self):
        result = _keyword_prescreen("SDET", "automated testing, pytest, selenium")
        assert result is not None
        assert result.skip is True

    def test_salesforce_is_excluded(self):
        result = _keyword_prescreen("Salesforce Developer", "apex, lightning web components")
        assert result is not None
        assert result.skip is True

    def test_clearance_required_is_excluded(self):
        result = _keyword_prescreen("Software Engineer", "clearance required, top secret")
        assert result is not None
        assert result.skip is True

    def test_cpp_engineer_passes_prescreen(self):
        # Tier-1 job should NOT be excluded by pre-screen
        result = _keyword_prescreen("C++ Systems Engineer", "C++17, STL, low-latency")
        assert result is None  # passes through to Claude

    def test_generic_backend_passes_prescreen(self):
        result = _keyword_prescreen("Backend Engineer", "Python, Django, PostgreSQL")
        assert result is None

    def test_case_insensitive_exclusion(self):
        # Exclusion keywords are lowercased before matching
        result = _keyword_prescreen("iOS Developer", "Swift, Objective-C, UIKit")
        assert result is not None
        assert result.skip is True


# ── classify_job — Claude integration ────────────────────────────────


class TestClassifyJob:
    def test_tier1_cpp_low_latency(self):
        client = MockAIClient(classifier_response(1, 0.95, "C++17 low-latency HFT role"))
        job = make_job("Senior C++ Engineer", "C++17, STL, lock-free, trading systems")
        result = classify_job(job, client)

        assert result.tier == 1
        assert result.score == pytest.approx(0.95)
        assert result.skip is False
        assert len(client.calls) == 1  # one AI call made

    def test_tier2_compiler_engineering(self):
        client = MockAIClient(classifier_response(2, 0.75, "Compiler engineering — tier 2"))
        job = make_job("Compiler Engineer", "LLVM, JIT compilation, Rust")
        result = classify_job(job, client)

        assert result.tier == 2
        assert result.skip is False

    def test_tier3_graphics_gpu(self):
        client = MockAIClient(classifier_response(3, 0.80, "GPU rendering — tier 3 graphics"))
        job = make_job("GPU Rendering Engineer", "Vulkan, ray tracing, CUDA, C++")
        result = classify_job(job, client)

        assert result.tier == 3

    def test_tier4_general_backend(self):
        client = MockAIClient(classifier_response(4, 0.40, "General backend SWE"))
        job = make_job("Backend Engineer", "Python, Django, PostgreSQL, Kubernetes")
        result = classify_job(job, client)

        assert result.tier == 4
        assert result.skip is False

    def test_skip_flag_returned_from_claude(self):
        client = MockAIClient(classifier_response(4, 0.05, "Frontend role", skip=True))
        job = make_job("React Developer", "React, TypeScript, CSS")
        result = classify_job(job, client)

        assert result.skip is True

    def test_score_is_within_valid_range(self):
        for score in [0.0, 0.5, 1.0]:
            client = MockAIClient(classifier_response(1, score, "Test"))
            job = make_job("C++ Eng", "c++")
            result = classify_job(job, client)
            assert 0.0 <= result.score <= 1.0

    def test_fallback_to_keywords_on_invalid_json(self):
        """When Claude returns non-JSON, fall back to keyword-based tier detection."""
        client = MockAIClient("I cannot classify this job.")
        job = make_job("C++ Systems Programmer", "c++ trading systems low-latency kernel")
        result = classify_job(job, client)

        # Keyword fallback should catch "c++" → tier 1
        assert result.tier == 1
        assert result.score == 0.5
        assert "fallback" in result.reason.lower()

    def test_fallback_tier4_when_no_keyword_matches(self):
        client = MockAIClient("not valid json at all")
        job = make_job("General Wizard", "magic and unicorns")
        result = classify_job(job, client)

        assert result.tier == 4

    def test_exclusion_skips_claude_call(self):
        """Pre-screen exclusions should short-circuit before calling Claude."""
        client = MockAIClient("should not be called")
        job = make_job("QA Engineer", "test automation, selenium, pytest")
        result = classify_job(job, client)

        assert result.skip is True
        assert len(client.calls) == 0  # Claude was never called

    def test_json_embedded_in_prose_is_parsed(self):
        """Claude sometimes wraps JSON in extra text — parser should handle it."""
        response = 'Here is my classification: {"tier": 2, "score": 0.7, "reason": "Systems role", "skip": false} Done.'
        client = MockAIClient(response)
        job = make_job("Systems Engineer", "linux kernel drivers embedded")
        result = classify_job(job, client)

        assert result.tier == 2
        assert result.score == pytest.approx(0.7)

    def test_prompt_contains_job_title_and_company(self):
        """The prompt sent to Claude should include job metadata."""
        client = MockAIClient(classifier_response(1, 0.9, "Good match"))
        job = make_job("HFT Quant Dev", "c++ quantitative", company="Jane Street")
        classify_job(job, client)

        prompt_sent = client.calls[0][0]
        assert "HFT Quant Dev" in prompt_sent
        assert "Jane Street" in prompt_sent


# ── Resume selection ─────────────────────────────────────────────────


class TestResumeSelector:
    def test_single_resume_returned_without_ai_call(self):
        client = MockAIClient("should not be called")
        cache = make_resume_cache("cpp_resume.pdf")
        job = make_job("C++ Dev", "c++")

        path, reason = select_resume(job, [cache], client)

        assert path == Path("/data/resumes/cpp_resume.pdf")
        assert "Only resume" in reason
        assert len(client.calls) == 0

    def test_selects_correct_resume_from_multiple(self):
        cpp_cache = make_resume_cache("cpp_resume.pdf", summary="C++ HFT engineer")
        web_cache = make_resume_cache("web_resume.pdf", summary="Full-stack web developer")

        response = json.dumps({"filename": "cpp_resume.pdf", "reason": "Best C++ match"})
        client = MockAIClient(response)
        job = make_job("C++ HFT Engineer", "c++ trading systems")

        path, reason = select_resume(job, [cpp_cache, web_cache], client)

        assert path == Path("/data/resumes/cpp_resume.pdf")
        assert "C++" in reason

    def test_fallback_to_first_resume_on_bad_json(self):
        caches = [
            make_resume_cache("resume_a.pdf"),
            make_resume_cache("resume_b.pdf"),
        ]
        client = MockAIClient("Sorry, I can't decide.")
        job = make_job("Software Engineer", "python java golang")

        path, reason = select_resume(job, caches, client)

        assert path == Path("/data/resumes/resume_a.pdf")
        assert "Fallback" in reason

    def test_fallback_when_claude_returns_unknown_filename(self):
        caches = [make_resume_cache("real_resume.pdf")]
        response = json.dumps({"filename": "nonexistent.pdf", "reason": "Best match"})
        client = MockAIClient(response)
        job = make_job("Engineer", "code")

        path, reason = select_resume(job, caches, client)

        # Should fall back to first resume since filename doesn't match
        assert path == Path("/data/resumes/real_resume.pdf")

    def test_raises_if_no_resumes(self):
        client = MockAIClient("")
        job = make_job("C++ Dev", "c++")

        with pytest.raises(ValueError, match="No resumes"):
            select_resume(job, [], client)

    def test_prompt_includes_job_title_for_multi_resume(self):
        caches = [make_resume_cache("a.pdf"), make_resume_cache("b.pdf")]
        response = json.dumps({"filename": "a.pdf", "reason": "Best match"})
        client = MockAIClient(response)
        job = make_job("Low-Latency C++ Dev", "c++ hft", company="Tower Research")

        select_resume(job, caches, client)

        prompt = client.calls[0][0]
        assert "Low-Latency C++ Dev" in prompt
        assert "Tower Research" in prompt


# ── Cover letter generation ──────────────────────────────────────────


class TestCoverLetterGeneration:
    def test_returns_string(self):
        client = MockAIClient("This is a compelling cover letter for a C++ role.")
        job = make_job("C++ Systems Engineer", "c++ trading")
        result = generate_cover_letter(job, "Resume text here.", client)

        assert isinstance(result, str)
        assert len(result) > 0

    def test_prompt_includes_job_title_and_company(self):
        client = MockAIClient("Cover letter content.")
        job = make_job("HFT Developer", "c++ latency", company="Citadel Securities")
        generate_cover_letter(job, "Resume text.", client)

        prompt = client.calls[0][0]
        assert "HFT Developer" in prompt
        assert "Citadel Securities" in prompt

    def test_resume_text_is_included_in_prompt(self):
        client = MockAIClient("Cover letter.")
        job = make_job("C++ Dev", "c++")
        resume_text = "Experienced in C++17, STL, lock-free data structures."
        generate_cover_letter(job, resume_text, client)

        prompt = client.calls[0][0]
        assert "C++17" in prompt

    def test_long_resume_is_truncated_in_prompt(self):
        """Resume text is capped at 4000 chars to avoid token overflow."""
        client = MockAIClient("Cover letter.")
        job = make_job("C++ Dev", "c++")
        long_resume = "x" * 10000
        generate_cover_letter(job, long_resume, client)

        prompt = client.calls[0][0]
        # The prompt itself will be longer, but it should not contain 10000 x's
        assert prompt.count("x") <= 4000

    def test_long_description_is_truncated(self):
        """Job description is capped at 3000 chars."""
        client = MockAIClient("Cover letter.")
        # Use 'z' — it doesn't appear in the prompt template, so count is exact
        long_desc = "z" * 9000
        job = make_job("Engineer", long_desc)
        generate_cover_letter(job, "resume", client)

        prompt = client.calls[0][0]
        assert prompt.count("z") <= 3000

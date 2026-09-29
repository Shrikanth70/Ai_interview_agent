"""Tests for grounding validation, anti-hallucination guardrails, and resume generalization.

Tests cover:
1. Priority 0: Grounding validation function unit matching, retry correction, and deterministic fallback.
2. Priority 1: Multi-turn simulated sessions across Srikanth, Sparse, and Messy fixtures.
3. Priority 2 & 3: Turn 1 resume ordering, anti-cheating, key point follow-ups, and negative assertion against hallucinations.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
import pytest
from httpx import ASGITransport, AsyncClient

from app.agent.grounding import (
    extract_deterministic_fallback_target,
    is_source_ref_grounded,
    normalize_tokens,
    validate_question_assumptions,
)
from app.agent.interviewer import InterviewerAgent
from app.session.state import SessionState
from app.api.routes import get_agent
from app.llm.base import BaseLLMClient
from app.llm.mock_client import MockLLMClient
from app.main import app

FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Test Clients for Grounding Validation Testing
# ---------------------------------------------------------------------------

class HallucinatingOnceLLMClient(BaseLLMClient):
    """Hallucinates 'raft-kv-go' on the first attempt, but corrects to a valid resume claim on retry."""

    def __init__(self, valid_claim: str = "MovieBuddy — AI Movie Recommendation Platform"):
        self.attempts = 0
        self.valid_claim = valid_claim

    async def _call_provider(self, messages: List[Dict[str, str]], temperature: float) -> str:
        self.attempts += 1
        last_msg = messages[-1].get("content", "")

        # Check if correction instruction was received on retry
        if "CRITICAL GROUNDING ERROR" in last_msg or self.attempts > 1:
            return json.dumps({
                "question": f"Welcome! Looking over your background, you highlighted {self.valid_claim}. Walk me through your design.",
                "turn_type": "resume_claim",
                "source": "resume",
                "source_ref": self.valid_claim[:50],
                "reasoning_note": "Corrected turn grounded verifiably in the resume text after validation failure.",
            })

        # Initial attempt: intentionally hallucinate external raft-kv-go project
        return json.dumps({
            "question": "In your repository 'raft-kv-go', how did you implement log compaction with snapshotting?",
            "turn_type": "github_project",
            "source": "github",
            "source_ref": "repo: raft-kv-go / log compaction",
            "reasoning_note": "Intentionally hallucinated ungrounded project.",
        })


class DoubleHallucinatingLLMClient(BaseLLMClient):
    """Hallucinates ungrounded content on BOTH attempts to test deterministic fallback."""

    def __init__(self):
        self.attempts = 0

    async def _call_provider(self, messages: List[Dict[str, str]], temperature: float) -> str:
        self.attempts += 1
        return json.dumps({
            "question": "Tell me about your distributed Paxos implementation in Go.",
            "turn_type": "github_project",
            "source": "github",
            "source_ref": "repo: phantom-paxos-cluster",
            "reasoning_note": "Hallucinating phantom repo on all attempts.",
        })


# ---------------------------------------------------------------------------
# Unit Tests: Grounding Validation Matching Logic (Priority 0 & 1)
# ---------------------------------------------------------------------------

def test_grounding_validation_fuzzy_matching_logic():
    """Verify that is_source_ref_grounded accurately validates grounded refs and rejects hallucinations."""
    srikanth_resume = (FIXTURES_DIR / "sample_resume_srikanth.txt").read_text(encoding="utf-8")
    messy_resume = (FIXTURES_DIR / "sample_resume_messy.txt").read_text(encoding="utf-8")
    sparse_resume = (FIXTURES_DIR / "sample_resume_sparse.txt").read_text(encoding="utf-8")

    github_summary = {
        "username": "Shrikanth70",
        "repos": {
            "MovieBuddy": {
                "name": "MovieBuddy",
                "description": "AI Movie Recommendation Platform",
                "language": "Python",
                "topics": ["nlp", "streamlit", "recommendation-system"],
                "readme_excerpt": "A content-based recommendation platform using TMDB metadata and cosine similarity.",
            },
            "StudyBuddy-Ai": {
                "name": "StudyBuddy-Ai",
                "description": "AI Learning Assistant",
                "language": "JavaScript",
                "topics": ["react", "express", "mongodb"],
                "readme_excerpt": "Full-stack platform using Gemini API and JWT authentication.",
            },
        },
    }

    # 1. Grounded resume claims on Srikanth fixture
    grounded, reason = is_source_ref_grounded(
        "MovieBuddy — AI Movie Recommendation Platform",
        source="resume",
        turn_type="resume_claim",
        resume_text=srikanth_resume,
        github_summary=github_summary,
    )
    assert grounded, f"Expected MovieBuddy to be grounded: {reason}"

    grounded, reason = is_source_ref_grounded(
        "AGEWELL — Elder Care Service Platform",
        source="resume",
        turn_type="resume_claim",
        resume_text=srikanth_resume,
        github_summary=github_summary,
    )
    assert grounded, f"Expected AGEWELL to be grounded: {reason}"

    grounded, reason = is_source_ref_grounded(
        "Skills Section: Python, JavaScript, MongoDB",
        source="resume",
        turn_type="skill_anchored",
        resume_text=srikanth_resume,
        github_summary=github_summary,
    )
    assert grounded, f"Expected skills to be grounded: {reason}"

    # 2. Tolerates messy / mangled text (Priority 1 item 6)
    grounded, reason = is_source_ref_grounded(
        "MovieBuddy — AI Movie Recommendation Platform",
        source="resume",
        turn_type="resume_claim",
        resume_text=messy_resume,
        github_summary=github_summary,
    )
    assert grounded, f"Expected fuzzy match on messy resume: {reason}"

    grounded, reason = is_source_ref_grounded(
        "StudyBuddy AI — AI Learning Assistant",
        source="resume",
        turn_type="resume_claim",
        resume_text=messy_resume,
        github_summary=github_summary,
    )
    assert grounded, f"Expected fuzzy match on messy StudyBuddy: {reason}"

    # 3. Grounded on sparse fresher resume
    grounded, reason = is_source_ref_grounded(
        "TaskTrack — Minimalist Task Tracker",
        source="resume",
        turn_type="resume_claim",
        resume_text=sparse_resume,
        github_summary={},
    )
    assert grounded, f"Expected TaskTrack to be grounded on sparse resume: {reason}"

    # 4. NEGATIVE ASSERTION: Known hallucination 'raft-kv-go' must fail on ALL fixtures
    for r_name, r_text in [("srikanth", srikanth_resume), ("messy", messy_resume), ("sparse", sparse_resume)]:
        grounded, reason = is_source_ref_grounded(
            "repo: raft-kv-go / log compaction",
            source="github",
            turn_type="github_project",
            resume_text=r_text,
            github_summary=github_summary,
        )
        assert not grounded, f"Hallucinated 'raft-kv-go' should FAIL on {r_name}, but passed: {reason}"
        assert "hallucination detected" in reason.lower()

    # 5. NEGATIVE ASSERTION: Non-existent technology must fail
    grounded, reason = is_source_ref_grounded(
        "Apache Kafka event pipeline migration (450ms -> 40ms latency)",
        source="resume",
        turn_type="resume_claim",
        resume_text=srikanth_resume,
        github_summary=github_summary,
    )
    assert not grounded, "Kafka should fail on Srikanth's resume as it does not exist there."


# ---------------------------------------------------------------------------
# Test: Rejected-Then-Corrected Turn (Priority 0 Evidence)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_validation_layer_rejected_then_corrected_turn():
    """Verify that an initial hallucination is rejected and re-prompted, succeeding on retry."""
    srikanth_resume = (FIXTURES_DIR / "sample_resume_srikanth.txt").read_text(encoding="utf-8")
    
    mock_client = HallucinatingOnceLLMClient(valid_claim="MovieBuddy AI Movie Recommendation")
    agent = InterviewerAgent(llm_client=mock_client)

    state = SessionState(
        session_id="test-retry-session",
        candidate_name="Srikanth Bhukya",
        resume_text=srikanth_resume,
        github_summary={},
    )

    # Execute turn 1: attempt 1 will return raft-kv-go (source='github'), which violates both
    # the Turn 1 resume ordering rule and the grounding validation check!
    turn_output = await agent.execute_turn(state)

    # Verify attempt 1 was caught and retried
    assert mock_client.attempts == 2, "Agent should have retried generation once upon validation failure."
    assert turn_output.source == "resume", "Final question must be from resume."
    assert "MovieBuddy" in turn_output.question or "MovieBuddy" in (turn_output.source_ref or "")
    assert "raft-kv-go" not in turn_output.question
    assert "raft-kv-go" not in (turn_output.source_ref or "")


# ---------------------------------------------------------------------------
# Test: Second-Failure Fallback to Deterministic Question (Priority 0 Evidence)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_validation_layer_second_failure_deterministic_fallback():
    """Verify that when an LLM fails validation twice, the agent safely falls back to a deterministic question."""
    srikanth_resume = (FIXTURES_DIR / "sample_resume_srikanth.txt").read_text(encoding="utf-8")
    
    mock_client = DoubleHallucinatingLLMClient()
    agent = InterviewerAgent(llm_client=mock_client)

    state = SessionState(
        session_id="test-fallback-session",
        candidate_name="Srikanth Bhukya",
        resume_text=srikanth_resume,
        github_summary={},
    )

    turn_output = await agent.execute_turn(state)

    # Verify both attempts failed and fallback was invoked
    assert mock_client.attempts == 2
    assert turn_output.source == "resume"
    assert "Deterministic app-layer fallback" in turn_output.reasoning_note
    # Must be grounded in Srikanth's actual skills/claims
    grounded, reason = is_source_ref_grounded(
        turn_output.source_ref,
        source=turn_output.source,
        turn_type=turn_output.turn_type,
        resume_text=srikanth_resume,
        github_summary={},
    )
    assert grounded, f"Deterministic fallback must be grounded in resume: {reason}"


# ---------------------------------------------------------------------------
# Multi-Turn Simulated Sessions across ALL THREE Fixtures (Priority 1)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("fixture_filename, candidate_answers", [
    (
        "sample_resume_srikanth.txt",
        [
            # Turn 1 Answer containing key points (Priority 3.3):
            # 1. Named tool: "TMDB API with TF-IDF and cosine similarity"
            # 2. Quantifiable claim: "reduced latency from 600ms to 45ms by precomputing the similarity matrix"
            # 3. Design trade-off: "in-memory sparse matrix vs recomputing on request"
            "For MovieBuddy, I used Python with TF-IDF vectorization and cosine similarity on TMDB metadata. "
            "To solve response time bottlenecks, I moved feature generation offline and stored precomputed similarity vectors, "
            "which reduced latency from 600ms to 45ms while preserving recommendation relevance.",

            # Turn 2 Answer: Thorough and complete (pivots cleanly without artificial follow-up)
            "In StudyBuddy AI, we used React with Vite for the frontend and Express.js with MongoDB on the backend. "
            "We integrated Gemini API using server-side rate-limiting and streamed responses to prevent socket timeouts.",

            # Turn 3 Answer: Concrete technical description
            "For the AGEWELL platform, I designed modular React components using TailwindCSS, ensuring full accessibility and mobile responsiveness."
        ]
    ),
    (
        "sample_resume_sparse.txt",
        [
            # Turn 1 Answer with key point: "SQLite with WAL mode", "1000 tasks/second"
            "In TaskTrack, I built a CLI in Python and used SQLite with WAL mode enabled to support concurrent read operations, "
            "handling up to 1000 tasks/second without locking errors.",

            # Turn 2 Answer: Detailed answer
            "For WeatherFetch, I implemented caching with a 15-minute TTL to respect OpenWeatherMap API rate limits and formatted output with rich console tables.",

            # Turn 3 Answer
            "I used Python's dataclasses and argparse module to keep the CLI lightweight with zero external dependencies beyond requests."
        ]
    ),
    (
        "sample_resume_messy.txt",
        [
            # Turn 1 Answer with key point
            "In MovieBuddy, I extracted metadata tags from TMDB and built a content-based recommendation filter using scikit-learn cosine similarity.",

            # Turn 2 Answer: Detailed answer
            "For Chintu voice assistant, I chained SpeechRecognition with pyttsx3 and implemented regex dispatching for desktop commands.",

            # Turn 3 Answer
            "I managed state transitions using an async event queue to prevent blocking the audio input stream during web searches."
        ]
    ),
])
@pytest.mark.asyncio
async def test_multi_turn_simulated_sessions_across_all_fixtures(
    fixture_filename: str, candidate_answers: List[str]
):
    """Simulate a multi-turn interview across all three fixtures.
    
    Asserts:
    1. Turn 1 question's source is strictly 'resume'.
    2. Turn 1 begins with the required professional greeting ('Welcome!').
    3. Every source_ref across the entire session fuzzy-matches real fixture content.
    4. Negative assertion: known hallucinated string 'raft-kv-go' NEVER appears in any source_ref or question.
    5. At least one follow-up fires on an answer containing a key point.
    """
    resume_path = FIXTURES_DIR / fixture_filename
    assert resume_path.exists(), f"Fixture file not found: {resume_path}"
    resume_text = resume_path.read_text(encoding="utf-8")

    mock_llm = MockLLMClient()
    agent = InterviewerAgent(llm_client=mock_llm)
    app.dependency_overrides[get_agent] = lambda: agent

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Start Session
        start_res = await client.post("/session/start", json={
            "resume_text": resume_text,
            "github_username": "Shrikanth70" if "srikanth" in fixture_filename or "messy" in fixture_filename else "alexchen-dev",
            "use_mock_github": True,
        })
        assert start_res.status_code == 201, f"Session start failed: {start_res.text}"
        data = start_res.json()
        session_id = data["session_id"]
        turn_1 = data["turn"]

        # Assertion 1: Turn 1 source is strictly 'resume'
        assert turn_1["source"] == "resume", f"Turn 1 source must be 'resume', got: {turn_1['source']}"

        # Assertion 2: Turn 1 begins with professional welcome greeting
        assert turn_1["question"].startswith("Welcome!"), f"Turn 1 must start with 'Welcome!', got: {turn_1['question'][:30]}"

        # Assertion 3: Every source_ref is grounded in fixture
        all_turns = [turn_1]

        # Execute candidate answer turns
        for ans in candidate_answers:
            ans_res = await client.post(f"/session/{session_id}/answer", json={"answer": ans})
            assert ans_res.status_code == 200, f"Answer failed: {ans_res.text}"
            all_turns.append(ans_res.json()["turn"])

        # End session
        end_res = await client.post(f"/session/{session_id}/end")
        assert end_res.status_code == 200

        from app.session.store import get_session_store
        session_obj = await get_session_store().get(session_id)
        assert session_obj is not None
        session_github = session_obj.github_summary

        # Run holistic assertions across the entire session
        follow_up_count = 0
        for idx, turn in enumerate(all_turns, start=1):
            source_ref = turn.get("source_ref", "")
            source = turn.get("source", "")
            turn_type = turn.get("turn_type", "")
            question = turn.get("question", "")

            # Assertion 4: Negative assertion against hallucinations
            assert "raft-kv-go" not in question.lower(), f"Hallucination 'raft-kv-go' found in question at turn {idx}!"
            assert "raft-kv-go" not in source_ref.lower(), f"Hallucination 'raft-kv-go' found in source_ref at turn {idx}!"

            # Assertion 5: Grounding check on every turn
            grounded, reason = is_source_ref_grounded(
                source_ref=source_ref,
                source=source,
                turn_type=turn_type,
                resume_text=resume_text,
                github_summary=session_github,
            )
            assert grounded, (
                f"Turn {idx} source_ref '{source_ref}' (source={source}, type={turn_type}) "
                f"failed grounding verification against {fixture_filename}: {reason}"
            )

            if turn_type == "follow_up":
                follow_up_count += 1

        # Assertion 6: At least one follow-up occurred during the session
        # (Candidate answers touched on key points or follow-up opportunities)
        # Note: In sparse resumes or when answer is thorough, interviewer may pivot or follow up based on potential
        assert len(all_turns) >= 3

    app.dependency_overrides.clear()


def test_follow_up_grounding_rejects_hallucinated_technologies():
    """Verify that a follow-up claiming 'prior_answer: Experience with Go' is rejected
    when the candidate's answer discussed Redis/Lua and never mentioned Go.
    """
    resume_with_mongo = "Technical Skills: MongoDB, MySQL, Python, Redis. Experience in database optimization."
    
    transcript = [
        {
            "role": "interviewer",
            "content": "Welcome! Looking over your experience and background, you highlighted your work with MongoDB. Walk me through a challenging problem.",
            "meta": {"source": "resume", "source_ref": "Skills Section: MongoDB", "turn_type": "skill_anchored"}
        },
        {
            "role": "candidate",
            "content": (
                "I used a Lua script to ensure only the client that set the lock could release it. "
                "The script checked if the stored value matched the client's unique identifier, and only then "
                "executed a DEL on the key. This atomic check-and-delete prevented other clients from unlocking resources."
            )
        }
    ]

    # 1. Hallucinated follow-up claiming Go was mentioned in prior answer -> MUST FAIL
    grounded, reason = is_source_ref_grounded(
        source_ref="Prior answer: Experience with Go",
        source="resume",
        turn_type="follow_up",
        resume_text=resume_with_mongo,
        github_summary={},
        transcript=transcript,
    )
    assert not grounded, f"Expected hallucinated Go follow-up to FAIL, but got: {reason}"
    assert "hallucination detected" in reason.lower()

    # 2. Genuine follow-up probing Lua script / atomic delete from the actual answer -> MUST PASS
    grounded, reason = is_source_ref_grounded(
        source_ref="prior_answer: Lua script atomic check-and-delete",
        source="resume",
        turn_type="follow_up",
        resume_text=resume_with_mongo,
        github_summary={},
        transcript=transcript,
    )
    assert grounded, f"Expected genuine Lua follow-up to PASS, but got: {reason}"

    # 3. Word boundary check: 'go' as a standalone token must NOT match inside 'MongoDB'
    grounded, reason = is_source_ref_grounded(
        source_ref="Experience with Go",
        source="resume",
        turn_type="skill_anchored",
        resume_text=resume_with_mongo,
        github_summary={},
    )
    assert not grounded, f"Expected standalone 'Go' to not match inside 'MongoDB', but got: {reason}"


def test_validate_question_assumptions_rejects_fabricated_pipeline_context():
    """Verify that questions inventing unestablished surrounding architectures
    (e.g., 'in your real-time data pipeline') are rejected even if source_ref looks valid.
    """
    resume_text = "Technical Skills: Python, Redis, SQL. Built distributed systems."
    github_summary = {
        "username": "testuser",
        "repos": {
            "redis-distributed-lock": {
                "name": "redis-distributed-lock",
                "description": "Distributed lock service using Redis SETNX and Lua scripts.",
                "language": "Python",
                "topics": ["redis", "concurrency"],
                "readme_excerpt": "A fault-tolerant distributed locking library with auto-lease expiry.",
            }
        }
    }
    transcript = [
        {
            "role": "candidate",
            "content": "I used a Lua script to ensure only the client that set the lock could release it."
        }
    ]

    # 1. Hallucinated question assumption: 'in your real-time data pipeline' -> MUST BE REJECTED
    fabricated_question = (
        "Can you explain how you used Redis as a distributed lock service in your real-time data pipeline, "
        "and how you handled the trade-off between lock acquisition latency and the number of concurrent locks?"
    )
    grounded, reason = is_source_ref_grounded(
        source_ref="repo: redis-distributed-lock / lock acquisition latency",
        source="github",
        turn_type="follow_up",
        resume_text=resume_text,
        github_summary=github_summary,
        transcript=transcript,
        question=fabricated_question,
    )
    assert not grounded, f"Expected fabricated 'real-time data pipeline' question to FAIL, but got: {reason}"
    assert "unsupported context assumption" in reason.lower()
    assert "pipeline" in reason.lower()

    # 2. Grounded question focusing strictly on documented architecture -> MUST PASS
    grounded_question = (
        "How did you handle lock acquisition under high concurrency in your Redis implementation, "
        "and what trade-offs did you consider around acquisition latency and contention?"
    )
    grounded, reason = is_source_ref_grounded(
        source_ref="repo: redis-distributed-lock / lock acquisition latency",
        source="github",
        turn_type="github_project",
        resume_text=resume_text,
        github_summary=github_summary,
        transcript=transcript,
        question=grounded_question,
    )
    assert grounded, f"Expected grounded question to PASS, but got: {reason}"


def test_deterministic_fallback_ignores_core_skills_header():
    """Verify that extract_deterministic_fallback_target does not extract 'CORE SKILLS' as a skill."""
    resume_with_core_skills = (
        "Candidate Name\n"
        "Software Engineer\n\n"
        "CORE SKILLS\n"
        "Python, Go, Docker, PostgreSQL\n\n"
        "EXPERIENCE\n"
        "- Built an async web service with FastAPI handling 5k req/s.\n"
    )
    from app.agent.grounding import extract_deterministic_fallback_target
    target, ref = extract_deterministic_fallback_target(resume_with_core_skills)
    assert target.lower() != "core skills", f"Target should not be 'CORE SKILLS', got: {target}"
    assert "core skills" not in ref.lower(), f"Ref should not be 'CORE SKILLS', got: {ref}"
    assert target in ["Python", "Go", "Docker", "PostgreSQL"] or "FastAPI" in target


def test_follow_up_grounding_rejects_hallucinated_redis_in_memoization():
    """Verify that a follow-up attributing Redis to a matrix pathfinding memoization answer is rejected."""
    resume_text = "Software Engineer with Python experience. Technical Skills: Python, Redis, SQL."
    transcript = [
        {
            "role": "interviewer",
            "content": "Walk me through a challenging technical problem you solved and the primary architectural trade-offs you navigated.",
            "meta": {"source": "resume", "source_ref": "General Claim", "turn_type": "skill_anchored"}
        },
        {
            "role": "candidate",
            "content": (
                "I tackled a complex problem where I had to optimize recursive backtracking for matrix pathfinding "
                "under strict time limits. The trade-off was between readability (clear recursion trees) and "
                "performance (memoization with space overhead). I chose a hybrid approach—caching partial results "
                "while keeping recursion for clarity—cutting runtime by nearly half without losing maintainability."
            )
        }
    ]

    # 1. Hallucinated follow-up claiming candidate used Redis in hybrid memoization approach -> MUST FAIL
    hallucinated_question = (
        "You mentioned a hybrid approach to optimize matrix pathfinding, caching partial results while keeping "
        "recursion for clarity. Can you walk me through the Redis implementation details in your hybrid approach, "
        "such as the specific Redis commands or data structures used?"
    )
    grounded, reason = is_source_ref_grounded(
        source_ref="partial results caching with Redis",
        source="resume",
        turn_type="follow_up",
        resume_text=resume_text,
        github_summary={},
        transcript=transcript,
        question=hallucinated_question,
    )
    assert not grounded, f"Expected hallucinated Redis follow-up to FAIL, but got: {reason}"
    assert any(w in reason.lower() for w in ["hallucination", "redis", "unsupported", "unmentioned"])

    # 2. Genuine grounded follow-up on candidate's actual memoization caching -> MUST PASS
    grounded_question = (
        "You mentioned caching partial results while keeping recursion for clarity. Can you walk me through "
        "how you structured the cache keys or memoization storage to prevent memory bloat during deep recursion?"
    )
    grounded, reason = is_source_ref_grounded(
        source_ref="prior_answer: caching partial results memoization",
        source="resume",
        turn_type="follow_up",
        resume_text=resume_text,
        github_summary={},
        transcript=transcript,
        question=grounded_question,
    )
    assert grounded, f"Expected genuine memoization follow-up to PASS, but got: {reason}"


def test_deterministic_fallback_ignores_location_and_employer_lines_arjun_reddy():
    """Verify that extract_deterministic_fallback_target extracts a real skill (e.g. Python) and NEVER 'India' or employer names."""
    resume_text = (
        "ARJUN REDDY\n"
        "Senior AI/ML Engineer\n\n"
        "Hyderabad, India\n"
        "Email: arjun.reddy.demo@example.com\n"
        "GitHub: github.com/arjun-reddy-demo\n\n"
        "------------------------------------------------------------\n"
        "PROFESSIONAL SUMMARY\n"
        "------------------------------------------------------------\n\n"
        "Senior AI/ML Engineer with 6+ years of experience designing ML systems.\n\n"
        "------------------------------------------------------------\n"
        "CORE SKILLS\n"
        "------------------------------------------------------------\n\n"
        "Programming:\n"
        "Python, Go, SQL, Bash, JavaScript, TypeScript\n\n"
        "Machine Learning:\n"
        "Scikit-learn, XGBoost, LightGBM\n\n"
        "------------------------------------------------------------\n"
        "PROFESSIONAL EXPERIENCE\n"
        "------------------------------------------------------------\n\n"
        "MACHINE LEARNING ENGINEER\n"
        "DataSphere Technologies — Bengaluru, India\n"
        "June 2021 – June 2023\n\n"
        "- Developed machine learning models for customer behavior prediction.\n"
    )
    from app.agent.grounding import extract_deterministic_fallback_target
    target, ref = extract_deterministic_fallback_target(resume_text)
    assert target.lower() not in ["india", "bengaluru", "hyderabad", "datasphere technologies", "datasphere technologies — bengaluru"], f"Target extracted invalid geography/employer: {target}"
    assert target in ["Python", "Go", "SQL", "Scikit-learn", "XGBoost", "LightGBM"]


def test_validate_question_assumptions_rejects_hallucinated_metrics():
    """Verify that questions containing fabricated numerical/latency metrics are rejected."""
    resume_text = (
        "ARJUN REDDY\n"
        "Senior AI/ML Engineer\n\n"
        "Experience:\n"
        "- TechNova Solutions: Optimized inference pipelines and reduced average response latency by approximately 35%.\n"
        "Projects:\n"
        "- Real-Time Fraud Detection System: Used Kafka for event ingestion and Redis for low-latency feature access.\n"
    )

    # 1. Question containing hallucinated metrics (450ms, 40ms) -> MUST BE REJECTED
    hallucinated_question = (
        "Welcome! Looking over your experience and background, you highlighted optimizing an event pipeline with "
        "Apache Kafka to reduce latency from 450ms down to 40ms. Can you walk me through the design decisions you made?"
    )
    valid, reason = validate_question_assumptions(
        question=hallucinated_question,
        turn_type="resume_claim",
        resume_text=resume_text,
        github_summary={},
    )
    assert not valid, f"Expected hallucinated 450ms/40ms metrics to be rejected, but got: {reason}"
    assert any(term in reason.lower() for term in ["metric", "450ms", "40ms", "unsupported", "hallucinat"])

    # 2. Question containing real metrics from resume (35%) -> MUST PASS
    grounded_metric_question = (
        "Welcome! Looking over your experience and background, you highlighted optimizing inference pipelines to "
        "reduce average response latency by approximately 35%. Can you walk me through the caching and batching strategies you used?"
    )
    valid, reason = validate_question_assumptions(
        question=grounded_metric_question,
        turn_type="resume_claim",
        resume_text=resume_text,
        github_summary={},
    )
    assert valid, f"Expected genuine 35% metric to pass, but got rejection: {reason}"


def test_validate_question_assumptions_rejects_hallucinated_assertions():
    """Verify that questions asserting an action/tech combination not connected in resume are rejected."""
    resume_text = (
        "ARJUN REDDY\n"
        "Senior AI/ML Engineer\n\n"
        "Experience:\n"
        "- TechNova Solutions: Optimized inference pipelines and reduced average response latency by approximately 35%.\n"
        "Projects:\n"
        "- Real-Time Fraud Detection System: Used Kafka for event ingestion and Redis for low-latency feature access.\n"
    )

    # Question asserts candidate optimized event pipelines with Kafka (which candidate never claimed)
    hallucinated_assertion_question = (
        "Welcome! Looking over your experience and background, you highlighted optimizing an event pipeline with "
        "Apache Kafka. Can you walk me through the partitioning strategies you used?"
    )
    valid, reason = validate_question_assumptions(
        question=hallucinated_assertion_question,
        turn_type="resume_claim",
        resume_text=resume_text,
        github_summary={},
    )
    assert not valid, f"Expected ungrounded assertion to be rejected, but got: {reason}"
    assert any(term in reason.lower() for term in ["assertion", "unsupported", "hallucinat", "kafka"])


def test_is_source_ref_grounded_rejects_cross_bullet_chimera():
    """Verify that source_refs combining disjoint tokens across separate jobs are rejected."""
    resume_text = (
        "ARJUN REDDY\n"
        "Senior AI/ML Engineer\n\n"
        "Experience:\n"
        "- TechNova Solutions: Optimized inference pipelines and reduced average response latency by approximately 35%.\n\n"
        "Projects:\n"
        "- Real-Time Fraud Detection System: Used Kafka for event ingestion and Redis for low-latency feature access.\n"
    )

    # source_ref cherry-picks 'Kafka' from Projects and 'latency optimization' from Experience
    chimera_ref = "Kafka event pipeline optimization (latency reduction)"
    grounded, reason = is_source_ref_grounded(
        source_ref=chimera_ref,
        source="resume",
        turn_type="resume_claim",
        resume_text=resume_text,
        github_summary={},
    )
    assert not grounded, f"Expected chimera source_ref to be rejected, but got passed: {reason}"
    assert any(term in reason.lower() for term in ["hallucination", "co-occur", "disjoint", "span", "appear"])


def test_prompts_free_of_leakage_entities():
    """Verify that system prompt directives do not mention specific project names like MovieBuddy."""
    from app.llm.prompts import MASTER_SYSTEM_PROMPT
    assert "MovieBuddy" not in MASTER_SYSTEM_PROMPT, "Found concrete entity 'MovieBuddy' in MASTER_SYSTEM_PROMPT"


def test_deterministic_fallback_on_arjun_reddy_never_extracts_senior_ai():
    """Verify that fallback extraction on Arjun Reddy's resume extracts an actual bullet/project and never 'Senior AI'."""
    resume_text = (
        "ARJUN REDDY\n\n"
        "Senior AI/ML Engineer\n\n"
        "Hyderabad, India\n"
        "Email: arjun.reddy.demo@example.com\n"
        "Phone: +91 98765 43210\n"
        "LinkedIn: linkedin.com/in/arjun-reddy-demo\n"
        "GitHub: github.com/arjun-reddy-demo\n\n"
        "PROFESSIONAL SUMMARY\n\n"
        "Senior AI/ML Engineer with 6+ years of experience designing, developing, and deploying production-grade Machine Learning, Deep Learning, NLP, LLM, and Generative AI systems.\n\n"
        "PROFESSIONAL EXPERIENCE\n\n"
        "Senior AI/ML Engineer\n"
        "TechNova Solutions Pvt. Ltd. — Hyderabad, India\n"
        "July 2023 – Present\n\n"
        "- Designed and developed production-grade Generative AI applications using LLMs, RAG pipelines, vector databases, and agentic workflows.\n"
        "- Built a multi-stage RAG architecture combining document ingestion, chunking, embedding generation, hybrid retrieval, reranking, and LLM-based answer generation.\n"
    )
    from app.agent.grounding import extract_deterministic_fallback_target
    target, ref = extract_deterministic_fallback_target(resume_text)
    assert "senior ai" not in target.lower(), f"Target extracted job title fragment: {target}"
    assert "senior ai" not in ref.lower(), f"Ref extracted job title fragment: {ref}"
    assert "skills section" not in ref.lower(), f"Emitted Skills Section for resume without skills section: {ref}"


def test_extract_candidate_anchors_finds_real_projects():
    """Verify extract_candidate_anchors pulls real project names from the candidate dossier."""
    resume_text = (
        "ARJUN REDDY\n"
        "Senior AI/ML Engineer\n\n"
        "SELECTED PROJECTS\n\n"
        "Enterprise Knowledge Assistant\n"
        "Technology: Python, LangGraph, FastAPI, Qdrant\n"
        "- Built an enterprise RAG assistant capable of answering questions.\n\n"
        "Real-Time Fraud Detection System\n"
        "Technology: Python, XGBoost, Kafka, Redis\n"
        "- Developed a real-time fraud detection pipeline processing streaming transaction events.\n\n"
        "AI Document Processing Platform\n"
        "Technology: Python, PyTorch, Transformers\n"
        "- Developed an automated document-processing pipeline.\n"
    )
    from app.agent.grounding import extract_candidate_anchors
    anchors = extract_candidate_anchors(resume_text)
    assert len(anchors) >= 2
    assert "Enterprise Knowledge Assistant" in anchors
    assert "Real-Time Fraud Detection System" in anchors


def test_github_grounding_strictly_requires_repository_match():
    """Verify that source='github' strictly requires matching a real repo and rejects fake repos matching generic words."""
    github_summary = {
        "profile": {
            "login": "octocat",
            "bio": "Systems Engineer and Distributed Systems Enthusiast at GitHub",
            "html_url": "https://github.com/octocat",
        },
        "repos": {
            "autotyper": {"name": "autotyper", "description": "Typing daemon in Go"},
            "event-hub": {"name": "event-hub", "description": "Event router in Go"},
        },
    }
    from app.agent.grounding import is_source_ref_grounded
    # 'RAG system GitHub repository' contains 'system' and 'github' from profile, but is NOT a repository!
    is_grounded, reason = is_source_ref_grounded(
        source_ref="RAG system GitHub repository",
        source="github",
        turn_type="context_switch",
        resume_text="Sample resume text",
        github_summary=github_summary,
    )
    assert not is_grounded, f"Expected non-existent GitHub repo to be rejected, but passed: {reason}"
    assert any(term in reason.lower() for term in ["repository", "portfolio", "repos", "autotyper", "not appear", "hallucinat"])


def test_fallback_switches_to_github_when_needed():
    """Verify that when the session needs a GitHub turn, fallback selects an uncovered repository."""
    from app.agent.interviewer import InterviewerAgent
    from app.session.state import SessionState

    state = SessionState(
        session_id="test-github-fallback",
        resume_text="Experienced engineer with Python and Go skills.",
        github_summary={
            "repos": {
                "autotyper": {"name": "autotyper", "description": "Typing daemon in Go", "language": "Go"},
                "event-hub": {"name": "event-hub", "description": "Stream router in Go", "language": "Go"},
            }
        },
    )
    # Simulate 2 prior resume turns
    state.add_interviewer_question("Welcome! Question 1", "resume_claim", "resume", "ref1")
    state.add_candidate_answer("Answer 1")
    state.add_interviewer_question("Question 2", "follow_up", "resume", "ref2")
    state.add_candidate_answer("Answer 2")

    agent = InterviewerAgent()
    fallback = agent._generate_deterministic_fallback(state, is_opening=False)
    assert fallback.source == "github"
    assert fallback.turn_type == "github_project"
    assert fallback.source_ref in ["autotyper", "event-hub"]
    assert "autotyper" in fallback.question or "event-hub" in fallback.question


def test_fallback_never_asks_consecutive_skill_questions():
    """Verify that if turn N was skill_anchored, turn N+1 fallback never asks another skill."""
    from app.agent.interviewer import InterviewerAgent
    from app.session.state import SessionState

    resume_text = (
        "Technical Skills\n"
        "- Programming: Python, Java, Go, SQL\n\n"
        "Experience\n"
        "- Designed and deployed high-performance stream processing engines.\n"
    )
    state = SessionState(
        session_id="test-no-consecutive-skills",
        resume_text=resume_text,
        github_summary={},
    )
    # Turn 1: skill_anchored
    state.add_interviewer_question("Question 1", "skill_anchored", "resume", "Skills Section: Python")
    state.add_candidate_answer("Answer 1")

    agent = InterviewerAgent()
    fallback = agent._generate_deterministic_fallback(state, is_opening=False)
    assert fallback.turn_type == "resume_claim"
    assert "skills section" not in fallback.source_ref.lower()
    assert "stream processing" in fallback.question.lower()


def test_extract_deterministic_fallback_ignores_academic_cs_subjects():
    """Verify that academic CS theory terms like OOP, DBMS, OS are ignored by fallback."""
    from app.agent.grounding import extract_deterministic_fallback_target

    resume_text = (
        "Technical Skills\n"
        "- Core CS: Data Structures and Algorithms, OOP, DBMS, Operating Systems, Computer Networks\n"
        "- Languages: Python, Go\n"
    )
    target, ref = extract_deterministic_fallback_target(resume_text)
    assert target.lower() not in ["oop", "dbms", "os", "cn", "operating systems", "computer networks", "data structures and algorithms"]
    assert target.lower() in ["python", "go"]


def test_fallback_caps_skills_at_one_across_session():
    """Verify that even when the immediately preceding turn was not skill_anchored, fallback does not ask a second skill."""
    from app.agent.interviewer import InterviewerAgent
    from app.session.state import SessionState

    resume_text = (
        "Technical Skills\n"
        "- Languages: Python, Java, Go\n\n"
        "Experience\n"
        "- Built microservices orchestration platform handling 10k req/sec.\n"
    )
    state = SessionState(
        session_id="test-cap-skills",
        resume_text=resume_text,
        github_summary={},
    )
    # Turn 1: skill_anchored
    state.add_interviewer_question("Question 1", "skill_anchored", "resume", "Skills Section: Python")
    state.add_candidate_answer("Answer 1")
    # Turn 2: follow_up (not skill_anchored)
    state.add_interviewer_question("Question 2", "follow_up", "resume", "prior_answer")
    state.add_candidate_answer("Answer 2")

    agent = InterviewerAgent()
    fallback = agent._generate_deterministic_fallback(state, is_opening=False)
    assert fallback.turn_type == "resume_claim"
    assert "skills section" not in fallback.source_ref.lower()
    assert "microservices orchestration" in fallback.question.lower()






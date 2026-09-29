import json
import pytest
from app.agent.interviewer import InterviewerAgent, InterviewerTurnOutput
from app.agent.grounding import is_source_ref_grounded, extract_deterministic_fallback_target
from app.session.state import SessionState
from app.llm.base import BaseLLMClient
from app.llm.mock_client import MockLLMClient

SENIOR_RESUME_WITHOUT_SKILLS = """
Jane Doe
Staff Infrastructure Engineer
Email: jane.doe@example.com | GitHub: janedoe

PROFESSIONAL EXPERIENCE

Principal Systems Architect | Nexus Cloud Systems | 2021 - Present
- Designed and delivered a multi-region distributed consensus layer using Raft and Go, sustaining 45,000 TPS at 99.999% availability.
- Overcame RocksDB write amplification and SST compaction stalls by implementing custom tiered compaction strategies, cutting p99 tail latency from 85ms to 12ms.
- Mentored 14 senior engineers across distributed storage and platform reliability squads.

Senior Staff Software Engineer | DataStream Corp | 2017 - 2021
- Architected real-time stream processing platform leveraging Apache Flink and Kafka, ingesting 2.5 billion daily telemetry events.
- Mitigated partition skew and consumer rebalance storms across 120 broker clusters through key hashing and cooperative sticky assignors.
- Re-architected schema evolution registry with Protocol Buffers, eliminating backward-incompatible deployment outages.

Senior Software Engineer | CoreLogic Systems | 2013 - 2017
- Built high-concurrency microservices in C++ and Python handling distributed transaction coordination across relational databases.
- Tuned Linux kernel TCP buffer configurations and epoll event loops to eliminate socket buffer drops under heavy burst traffic.
"""


class CannedLLMClient(BaseLLMClient):
    """Simple test LLM client returning predetermined JSON response."""

    def __init__(self, canned_json: str):
        self.canned_json = canned_json

    async def _call_provider(self, messages, temperature: float = 0.4) -> str:
        return self.canned_json


def test_deterministic_fallback_on_skill_less_resume():
    """Verify fallback extracts experience bullets when no skills section header exists."""
    target, ref = extract_deterministic_fallback_target(SENIOR_RESUME_WITHOUT_SKILLS)
    assert target is not None
    assert len(target) > 10
    # Must NOT be the fallback generic text
    assert target != "software engineering experience"
    # Grounding check must succeed
    is_grounded, reason = is_source_ref_grounded(
        source_ref=ref,
        source="resume",
        turn_type="resume_claim",
        resume_text=SENIOR_RESUME_WITHOUT_SKILLS,
        github_summary={},
    )
    assert is_grounded, f"Fallback reference '{ref}' failed grounding: {reason}"


def test_fallback_question_architectural_framing():
    """Verify fallback question is phrased with architectural depth for senior engineers."""
    state = SessionState(
        session_id="test-senior-fallback",
        resume_text=SENIOR_RESUME_WITHOUT_SKILLS,
        github_summary={},
    )
    agent = InterviewerAgent(llm_client=MockLLMClient())
    turn_output = agent._generate_deterministic_fallback(state, is_opening=False)

    assert "trade-offs" in turn_output.question.lower() or "architecture" in turn_output.question.lower()
    assert "skills section" not in turn_output.question.lower()


@pytest.mark.asyncio
async def test_skill_anchored_turn_anti_hallucination():
    """Verify skill_anchored turn output does not hallucinate 'skills section' on skill-less resumes."""
    mock_response = (
        '{\n'
        '  "question": "In your work at Nexus Cloud Systems, you utilized RocksDB and Raft. At 45,000 TPS, what SST compaction bottlenecks did you encounter, and what alternative state engines did you evaluate?",\n'
        '  "turn_type": "skill_anchored",\n'
        '  "source": "resume",\n'
        '  "source_ref": "RocksDB / Raft consensus layer (Nexus Cloud Systems)",\n'
        '  "reasoning_note": "Probing embedded storage engine trade-offs from senior work experience."\n'
        '}'
    )
    canned_client = CannedLLMClient(mock_response)
    agent = InterviewerAgent(llm_client=canned_client)

    state = SessionState(
        session_id="test-senior-session",
        resume_text=SENIOR_RESUME_WITHOUT_SKILLS,
        github_summary={"repos": {"raft-kv": {"description": "Distributed key-value store"}}},
    )
    # Add opening turn to transcript so this is Turn 2
    state.add_interviewer_question(
        question="Welcome! Tell me about your consensus layer.",
        turn_type="resume_claim",
        source="resume",
        source_ref="Nexus Cloud Systems Raft consensus",
        reasoning_note="Opening turn",
    )

    output = await agent.execute_turn(state, candidate_answer="We encountered severe write stalls under sustained burst traffic.")
    assert "skills section" not in output.question.lower()
    assert "technical skills section" not in output.question.lower()
    assert output.turn_type == "skill_anchored"

    is_grounded, reason = is_source_ref_grounded(
        source_ref=output.source_ref,
        source=output.source,
        turn_type=output.turn_type,
        resume_text=state.resume_text,
        github_summary=state.github_summary,
        transcript=state.transcript,
        question=output.question,
    )
    assert is_grounded, f"Grounded check failed: {reason}"


@pytest.mark.asyncio
async def test_opening_turn_on_skill_less_senior_resume():
    """Verify Turn 1 opening question succeeds and grounds against work experience."""
    mock_llm = MockLLMClient()
    agent = InterviewerAgent(llm_client=mock_llm)

    state = SessionState(
        session_id="test-senior-opening",
        resume_text=SENIOR_RESUME_WITHOUT_SKILLS,
        github_summary={"repos": {"raft-kv": {"description": "Distributed key-value store"}}},
    )

    turn_1 = await agent.execute_turn(state)
    assert turn_1.source == "resume"
    assert turn_1.question.startswith("Welcome!")
    assert "skills section" not in turn_1.question.lower()

    is_grounded, reason = is_source_ref_grounded(
        source_ref=turn_1.source_ref,
        source=turn_1.source,
        turn_type=turn_1.turn_type,
        resume_text=state.resume_text,
        github_summary=state.github_summary,
        question=turn_1.question,
    )
    assert is_grounded, f"Turn 1 reference '{turn_1.source_ref}' failed grounding: {reason}"

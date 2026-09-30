import pytest
from app.api.models import (
    StartSessionRequest,
    StartSessionResponse,
    SubmitAnswerRequest,
    SubmitAnswerResponse,
    OrchestrationResponse,
)
from app.agent.interviewer import InterviewerTurnOutput


def test_start_session_request_with_theme_and_jd():
    req = StartSessionRequest(
        resume_text="Senior Backend Engineer with Python and Redis expertise.",
        github_username="octocat",
        use_mock_github=True,
        starting_theme="JD",
        jd_scenarios=[{"scenario_id": "stream_ingestion", "title": "Telemetry Streaming"}],
    )
    assert req.starting_theme == "JD"
    assert len(req.jd_scenarios) == 1
    assert req.jd_scenarios[0]["scenario_id"] == "stream_ingestion"


def test_submit_answer_request_with_jev_signal():
    req = SubmitAnswerRequest(
        answer="We used two-tier Redis caching with local LRU.",
        jev_signal="SWITCH_CONTEXT",
    )
    assert req.answer == "We used two-tier Redis caching with local LRU."
    assert req.jev_signal == "SWITCH_CONTEXT"


def test_orchestration_response_serialization():
    orch = OrchestrationResponse(
        active_theme="PROFILE",
        active_context_id="github:distributed-cache",
        current_rubric_dimension="methodology_depth",
        is_bridge_turn=False,
        minutes_remaining=23.5,
        elapsed_minutes=1.5,
        is_closing_time=False,
        sub_memories=[
            {
                "context_id": "github:distributed-cache",
                "theme": "PROFILE",
                "status": "in_progress",
                "current_dimension": "methodology_depth",
            }
        ],
        globally_covered_topics=["caching"],
    )
    assert orch.active_theme == "PROFILE"
    assert orch.minutes_remaining == 23.5

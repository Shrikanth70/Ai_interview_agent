import pytest
from app.agent.interviewer import InterviewerAgent
from app.llm.client import MockLLMClient
from app.session.state import SessionState


@pytest.mark.asyncio
async def test_e2e_multi_turn_hierarchical_interview_simulation():
    """Simulates a complete multi-turn interview verifying theme switching, bridge questions,

    sub-memory isolation, and closing cutoff.
    """
    mock_llm = MockLLMClient()
    agent = InterviewerAgent(llm_client=mock_llm)

    state = SessionState(
        session_id="e2e-hierarchical-session-1",
        resume_text=(
            "Arjun Reddy\n"
            "Backend Engineer specializing in Python, Redis, and high-concurrency systems.\n"
            "Experience:\n"
            "- Designed distributed caching layer with custom TTL and eviction policies.\n"
            "- Built async telemetry pipeline reducing p99 latency by 35%.\n"
        ),
        github_summary={
            "repos": {
                "distributed-cache": {
                    "description": "High-throughput in-memory caching daemon with TTL",
                    "language": "Python",
                },
                "fast-analytics": {
                    "description": "Ring-buffer analytics streaming worker",
                    "language": "Go",
                },
            }
        },
    )

    # Turn 1: Opening turn in PROFILE theme
    t1 = await agent.execute_turn(state, starting_theme="PROFILE")
    assert t1.question
    assert state.turn_count == 1
    assert state.orchestration.active_theme == "PROFILE"
    assert "github:distributed-cache" in state.sub_memories

    # Turn 2: Follow-up within distributed-cache (JEV says FOLLOW_UP)
    t2 = await agent.execute_turn(
        state=state,
        candidate_answer="We implemented a two-tier eviction wheel with mutex locks.",
        jev_signal="FOLLOW_UP",
    )
    assert t2.question
    assert state.turn_count == 2
    assert state.orchestration.active_theme == "PROFILE"

    # Turn 3: Context Switch to JD theme (JEV says SWITCH_CONTEXT -> Bridge Question)
    t3 = await agent.execute_turn(
        state=state,
        candidate_answer="That allowed concurrent reads while background workers evicted expired keys.",
        jev_signal="SWITCH_CONTEXT",
    )
    assert t3.question
    assert state.turn_count == 3
    assert state.orchestration.active_theme == "JD"
    assert any(k.startswith("jd:") for k in state.sub_memories.keys())

    # Turn 4: Follow-up within JD theme (JEV says FOLLOW_UP)
    t4 = await agent.execute_turn(
        state=state,
        candidate_answer="I would handle the message burst using an in-memory ring buffer with backpressure.",
        jev_signal="FOLLOW_UP",
    )
    assert t4.question
    assert state.turn_count == 4
    assert state.orchestration.active_theme == "JD"

    # Turn 5: Switch context back to PROFILE (JEV says SWITCH_CONTEXT)
    t5 = await agent.execute_turn(
        state=state,
        candidate_answer="Backpressure signals upstream producers to throttle when the queue reaches 80% capacity.",
        jev_signal="SWITCH_CONTEXT",
    )
    assert t5.question
    assert state.turn_count == 5
    assert state.orchestration.active_theme == "PROFILE"

    # Verify sub-memory isolation
    profile_subs = [s for s in state.sub_memories.values() if s.theme == "PROFILE"]
    jd_subs = [s for s in state.sub_memories.values() if s.theme == "JD"]
    assert len(profile_subs) >= 1
    assert len(jd_subs) >= 1

    # Verify sliding dialogue window is bounded
    assert len(state.recent_dialogue_window) <= 6

    # Turn 6: Trigger budget cutoff near max turns
    state.turn_count = 11
    t_close = await agent.execute_turn(
        state=state,
        candidate_answer="That summarizes my approach to concurrency and buffer safety.",
    )
    assert t_close.turn_type == "closing"
    assert state.status == "completed"
    assert "concludes our interview" in t_close.question.lower() or "wrap up" in t_close.question.lower()

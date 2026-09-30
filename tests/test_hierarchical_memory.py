from datetime import datetime, timezone
import pytest
from app.session.state import (
    ContextSubMemory,
    SessionBudget,
    SessionState,
    TurnRecord,
)

def test_context_sub_memory_lifecycle():
    sub = ContextSubMemory(
        context_id="github:distributed-cache",
        theme="PROFILE",
        source_ref="distributed-cache",
        source_slice={"description": "In-memory cache daemon", "language": "Python"},
        pending_dimensions=["clarity_of_framing", "methodology_depth", "feasibility"],
    )
    assert sub.context_id == "github:distributed-cache"
    assert sub.theme == "PROFILE"
    assert len(sub.pending_dimensions) == 3
    assert len(sub.probed_dimensions) == 0

    # Advance dimension
    sub.record_turn(
        role="interviewer",
        content="Walk me through the core problem of distributed-cache.",
        rubric_dimension="clarity_of_framing",
    )
    assert len(sub.turns) == 1
    assert "clarity_of_framing" in sub.probed_dimensions
    assert sub.pending_dimensions == ["methodology_depth", "feasibility"]

def test_session_state_hierarchical_integration():
    state = SessionState(
        session_id="test-session-123",
        resume_text="Senior Engineer with Redis and Python experience.",
        github_summary={"repos": {"distributed-cache": {"description": "A cache"}}},
    )
    assert state.budget.max_duration_seconds == 1500
    assert state.budget.max_turns == 12
    assert state.orchestration.active_theme in ["PROFILE", "JD"]
    assert isinstance(state.sub_memories, dict)

    # Adding a candidate answer updates both transcript and recent dialogue window
    state.add_candidate_answer("We used mutex locks with a TTL wheel.")
    assert len(state.transcript) == 1
    assert len(state.recent_dialogue_window) == 1
    assert state.recent_dialogue_window[-1].content == "We used mutex locks with a TTL wheel."

    # Verify sliding window caps at max 3 pairs (6 turns)
    for i in range(10):
        state.add_candidate_answer(f"Answer {i}")
    assert len(state.recent_dialogue_window) <= 6

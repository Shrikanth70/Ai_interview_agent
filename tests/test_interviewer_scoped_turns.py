import pytest
from app.agent.interviewer import InterviewerAgent
from app.llm.client import MockLLMClient
from app.session.state import SessionState


@pytest.mark.asyncio
async def test_turn_1_initializes_random_theme_and_sub_memory():
    mock_llm = MockLLMClient()
    agent = InterviewerAgent(llm_client=mock_llm)
    state = SessionState(
        session_id="test-hierarchical-turn1",
        resume_text="Experienced engineer with Redis caching and FastAPI systems.",
        github_summary={"repos": {"cache-service": {"description": "A cache service"}}},
    )
    turn = await agent.execute_turn(state)
    assert turn.question
    assert state.orchestration.active_context_id is not None
    assert len(state.sub_memories) == 1
    assert state.orchestration.active_theme in ["PROFILE", "JD"]


@pytest.mark.asyncio
async def test_jev_signal_follow_up_advances_dimension():
    mock_llm = MockLLMClient()
    agent = InterviewerAgent(llm_client=mock_llm)
    state = SessionState(
        session_id="test-jev-followup",
        resume_text="Redis engineer with caching systems.",
        github_summary={"repos": {"cache-service": {"description": "Cache"}}},
    )
    # Turn 1
    await agent.execute_turn(state)
    active_id = state.orchestration.active_context_id

    # Candidate answers, JEV says FOLLOW_UP
    turn2 = await agent.execute_turn(
        state=state,
        candidate_answer="We used mutex locks with a TTL wheel.",
        jev_signal="FOLLOW_UP",
    )
    assert turn2.question
    assert state.orchestration.active_context_id == active_id


@pytest.mark.asyncio
async def test_jev_signal_switch_context_triggers_bridge():
    mock_llm = MockLLMClient()
    agent = InterviewerAgent(llm_client=mock_llm)
    state = SessionState(
        session_id="test-jev-switch",
        resume_text="Redis engineer",
        github_summary={"repos": {"cache-service": {"description": "Cache"}}},
    )
    # Turn 1 (starts in PROFILE)
    await agent.execute_turn(state, starting_theme="PROFILE")
    first_context = state.orchestration.active_context_id

    # Candidate answers, JEV says SWITCH_CONTEXT
    turn2 = await agent.execute_turn(
        state=state,
        candidate_answer="That is how we structured eviction.",
        jev_signal="SWITCH_CONTEXT",
    )
    assert turn2.question
    # Active context must have switched to JD
    assert state.orchestration.active_theme == "JD"
    assert state.orchestration.active_context_id != first_context


@pytest.mark.asyncio
async def test_budget_cutoff_forces_closing_turn():
    mock_llm = MockLLMClient()
    agent = InterviewerAgent(llm_client=mock_llm)
    state = SessionState(
        session_id="test-budget-cutoff",
        resume_text="Redis engineer",
        github_summary={"repos": {"cache-service": {"description": "Cache"}}},
    )
    # Simulate turn count near max
    state.turn_count = 11
    turn = await agent.execute_turn(
        state=state,
        candidate_answer="Final wrapup point.",
    )
    assert turn.turn_type == "closing"
    assert state.status == "completed"

import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status

from app.agent.interviewer import InterviewerAgent
from app.config import settings
from app.api.models import (
    EndSessionResponse,
    OrchestrationResponse,
    SessionSummary,
    StartSessionRequest,
    StartSessionResponse,
    SubmitAnswerRequest,
    SubmitAnswerResponse,
    TranscriptResponse,
)
from app.ingestion.github_loader import fetch_github_profile
from app.ingestion.resume_loader import load_resume
from app.session.state import SessionState
from app.session.store import SessionStore, get_session_store

router = APIRouter(prefix="/session", tags=["Interview Session"])


def get_agent() -> InterviewerAgent:
    """Dependency helper providing the InterviewerAgent instance."""
    return InterviewerAgent()


def _build_orchestration_response(
    state: SessionState, is_bridge: bool = False
) -> OrchestrationResponse:
    """Extracts live hierarchical memory, budget, and theme tracking for API responses."""
    active_sub = (
        state.sub_memories.get(state.orchestration.active_context_id)
        if state.orchestration.active_context_id
        else None
    )
    current_dim = (
        active_sub.pending_dimensions[0]
        if active_sub and active_sub.pending_dimensions
        else None
    )
    sub_summaries = []
    for sm in state.sub_memories.values():
        status_val = "completed" if not sm.pending_dimensions else "in_progress"
        sub_summaries.append({
            "context_id": sm.context_id,
            "theme": sm.theme,
            "source_ref": sm.source_ref,
            "status": status_val,
            "completed_dimensions": list(sm.probed_dimensions),
            "pending_dimensions": list(sm.pending_dimensions),
            "turn_count": len(sm.turns),
        })
    return OrchestrationResponse(
        active_theme=state.orchestration.active_theme,
        active_context_id=state.orchestration.active_context_id or "",
        current_rubric_dimension=current_dim,
        is_bridge_turn=is_bridge,
        minutes_remaining=round(state.budget.minutes_remaining, 2),
        elapsed_minutes=round(state.budget.elapsed_minutes, 2),
        is_closing_time=state.budget.is_closing_time,
        sub_memories=sub_summaries,
        globally_covered_topics=list(state.globally_covered_topics),
    )


@router.post(
    "/start",
    response_model=StartSessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Start a new interview session",
)
async def start_session(
    payload: StartSessionRequest,
    store: SessionStore = Depends(get_session_store),
    agent: InterviewerAgent = Depends(get_agent),
) -> StartSessionResponse:
    """Ingests resume & GitHub profile, initializes session state, and emits opening question."""
    # 1. Ingest Resume
    resume_source = payload.resume_text or payload.resume_file_path
    if not resume_source or not resume_source.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either 'resume_text' or 'resume_file_path' must be provided.",
        )

    try:
        parsed_resume = load_resume(resume_source)
        clean_resume_text = parsed_resume["full_text"]
    except Exception as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to process resume: {err}",
        )

    # 2. Ingest GitHub profile (with mock support & resilient fallback)
    try:
        github_data = await fetch_github_profile(
            payload.github_username, use_mock=payload.use_mock_github
        )
    except Exception as net_err:
        # Fallback to mock profile so candidate interview is not blocked
        from app.ingestion.github_loader import get_mock_portfolio
        github_data = get_mock_portfolio(payload.github_username)

    # 3. Initialize SessionState
    chosen_provider = payload.llm_provider or settings.LLM_PROVIDER
    if chosen_provider == "mock":
        chosen_model = payload.model_name or "mock-interview-agent"
    elif chosen_provider == "ollama":
        chosen_model = payload.model_name or settings.OLLAMA_MODEL
    else:
        chosen_model = payload.model_name or settings.OPENROUTER_MODEL

    session_id = str(uuid.uuid4())
    state = SessionState(
        session_id=session_id,
        resume_text=clean_resume_text,
        github_summary=github_data,
        llm_provider=chosen_provider,
        model_name=chosen_model,
    )

    # Seed custom JD scenarios or text if provided
    if payload.jd_scenarios:
        state.jd_scenarios = payload.jd_scenarios
    if payload.jd_text:
        state.jd_text = payload.jd_text

    # 4. Generate Opening Turn with requested starting theme
    try:
        turn_output = await agent.execute_turn(
            state,
            candidate_answer=None,
            starting_theme=payload.starting_theme,
        )
    except Exception as llm_err:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to generate opening question from LLM: {llm_err}",
        )

    # 5. Persist State
    await store.save(state)

    return StartSessionResponse(
        session_id=session_id,
        status=state.status,
        turn_index=state.turn_count,
        turn=turn_output,
        orchestration=_build_orchestration_response(state, is_bridge=False),
    )


@router.post(
    "/{session_id}/answer",
    response_model=SubmitAnswerResponse,
    summary="Submit candidate answer and get next turn",
)
async def submit_answer(
    session_id: str,
    payload: SubmitAnswerRequest,
    store: SessionStore = Depends(get_session_store),
    agent: InterviewerAgent = Depends(get_agent),
) -> SubmitAnswerResponse:
    """Appends candidate answer to transcript and evaluates next interviewer question or pivot."""
    state = await store.get(session_id)
    if not state:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session '{session_id}' was not found.",
        )

    if state.status == "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Session '{session_id}' is already completed. No more answers can be submitted.",
        )

    clean_answer = payload.answer.strip()
    if not clean_answer:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Candidate answer cannot be empty or whitespace only.",
        )

    try:
        turn_output = await agent.execute_turn(
            state,
            candidate_answer=clean_answer,
            jev_signal=payload.jev_signal,
        )
    except Exception as llm_err:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to generate next interviewer turn: {llm_err}",
        )

    is_bridge = (
        turn_output.turn_type == "context_switch"
        or state.orchestration.theme_switch_pending
    )

    await store.save(state)

    return SubmitAnswerResponse(
        session_id=session_id,
        status=state.status,
        turn_index=state.turn_count,
        turn=turn_output,
        orchestration=_build_orchestration_response(state, is_bridge=is_bridge),
    )


@router.get(
    "/{session_id}/transcript",
    response_model=TranscriptResponse,
    summary="Get complete interview transcript and covered references",
)
async def get_transcript(
    session_id: str,
    store: SessionStore = Depends(get_session_store),
) -> TranscriptResponse:
    """Fetches full conversation history and tracked source references."""
    state = await store.get(session_id)
    if not state:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session '{session_id}' was not found.",
        )

    return TranscriptResponse(
        session_id=state.session_id,
        status=state.status,
        turn_count=state.turn_count,
        created_at=state.created_at,
        updated_at=state.updated_at,
        covered_refs=state.covered_refs,
        transcript=state.transcript,
    )


@router.post(
    "/{session_id}/end",
    response_model=EndSessionResponse,
    summary="Conclude the interview session",
)
async def end_session(
    session_id: str,
    store: SessionStore = Depends(get_session_store),
) -> EndSessionResponse:
    """Transitions session status to completed and returns topic summary."""
    state = await store.get(session_id)
    if not state:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session '{session_id}' was not found.",
        )

    state.status = "completed"
    await store.save(state)

    # Compute analytical metrics
    resume_q = sum(
        1 for t in state.transcript
        if t.role == "interviewer" and t.meta and t.meta.source == "resume"
    )
    github_q = sum(
        1 for t in state.transcript
        if t.role == "interviewer" and t.meta and t.meta.source == "github"
    )
    skill_q = sum(
        1 for t in state.transcript
        if t.role == "interviewer" and t.meta and t.meta.turn_type == "skill_anchored"
    )
    follow_ups = sum(
        1 for t in state.transcript
        if t.role == "interviewer" and t.meta and t.meta.turn_type == "follow_up"
    )
    switches = sum(
        1 for t in state.transcript
        if t.role == "interviewer" and t.meta and t.meta.turn_type == "context_switch"
    )
    topics = [ref.ref for ref in state.covered_refs]

    return EndSessionResponse(
        session_id=state.session_id,
        status=state.status,
        total_turns=state.turn_count,
        summary=SessionSummary(
            resume_questions_count=resume_q,
            github_questions_count=github_q,
            skill_anchored_count=skill_q,
            follow_up_count=follow_ups,
            context_switch_count=switches,
            covered_topics=topics,
        ),
        closing_message="The interview session has been formally completed. All transcripts and metadata are preserved.",
    )

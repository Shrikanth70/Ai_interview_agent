import pytest
from app.agent.theme_fetcher import ThemeMemoryFetchTool
from app.session.state import SessionState

def test_fetch_initial_slice_random_or_specified():
    fetcher = ThemeMemoryFetchTool()
    resume_text = "Senior Python Developer with Redis and FastAPI expertise."
    github_summary = {
        "repos": {
            "distributed-cache": {
                "description": "High-concurrency cache daemon",
                "language": "Python",
            }
        }
    }

    # Profile slice fetch
    sub_mem = fetcher.initialize_context(
        theme="PROFILE",
        resume_text=resume_text,
        github_summary=github_summary,
    )
    assert sub_mem.theme == "PROFILE"
    assert sub_mem.context_id.startswith("github:") or sub_mem.context_id.startswith("resume:")
    assert "clarity_of_framing" in sub_mem.pending_dimensions

    # JD slice fetch
    jd_sub = fetcher.initialize_context(
        theme="JD",
        resume_text=resume_text,
        github_summary=github_summary,
        jd_scenarios=[{"scenario_id": "ingestion_buffer", "title": "Real-time Stream Ingestion"}],
    )
    assert jd_sub.theme == "JD"
    assert jd_sub.context_id == "jd:ingestion_buffer"

def test_fetch_bridge_slice():
    fetcher = ThemeMemoryFetchTool()
    state = SessionState(
        session_id="test-session-bridge",
        resume_text="Engineer",
        github_summary={"repos": {"repo-a": {"description": "Repo A"}}},
    )
    # Setup active sub-memory
    active_sub = fetcher.initialize_context("PROFILE", state.resume_text, state.github_summary)
    state.sub_memories[active_sub.context_id] = active_sub
    state.orchestration.active_context_id = active_sub.context_id
    state.orchestration.active_theme = "PROFILE"

    bridge_payload = fetcher.fetch_bridge_context(
        state=state,
        target_theme="JD",
        jd_scenarios=[{"scenario_id": "stream_worker", "title": "Stream Worker"}],
    )
    assert "anchor_slice" in bridge_payload
    assert "target_slice" in bridge_payload
    assert bridge_payload["target_theme"] == "JD"

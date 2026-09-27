import pytest
from app.session.state import SessionState
from app.session.store import InMemorySessionStore


@pytest.mark.asyncio
async def test_session_store_lifecycle(tmp_path):
    store = InMemorySessionStore(persist_dir=tmp_path)
    state = SessionState(
        session_id="test-session-123",
        resume_text="Sample resume content",
        github_summary={"repos": {"demo-repo": {"language": "Python"}}},
    )

    # Save
    await store.save(state)

    # Retrieve
    retrieved = await store.get("test-session-123")
    assert retrieved is not None
    assert retrieved.session_id == "test-session-123"
    assert retrieved.resume_text == "Sample resume content"

    # Add turns
    retrieved.add_interviewer_question(
        question="Tell me about your Python project.",
        turn_type="github_project",
        source="github",
        source_ref="demo-repo",
        reasoning_note="Opening question on GitHub project",
    )
    retrieved.add_candidate_answer("I built a custom web scraper with asyncio.")
    await store.save(retrieved)

    # Reload and verify disk persistence
    fresh_store = InMemorySessionStore(persist_dir=tmp_path)
    reloaded = await fresh_store.get("test-session-123")
    assert reloaded is not None
    assert len(reloaded.transcript) == 2
    assert len(reloaded.covered_refs) == 1
    assert reloaded.covered_refs[0].ref == "demo-repo"

    # Delete
    deleted = await store.delete("test-session-123")
    assert deleted is True
    assert await store.get("test-session-123") is None

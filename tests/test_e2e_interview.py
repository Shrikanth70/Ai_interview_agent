import os
import pytest
from httpx import ASGITransport, AsyncClient

from app.agent.interviewer import InterviewerAgent, InterviewerTurnOutput
from app.api.routes import get_agent
from app.main import app
from app.session.state import SessionState


class MockRealisticLLMClient:
    """Mock LLM client producing deterministic, realistic interview turns for testing."""

    def __init__(self):
        self.call_count = 0

    async def generate_turn(self, messages, temperature=0.4, max_retries=3):
        self.call_count += 1
        if self.call_count == 1:
            # Turn 1: Opening specific resume claim
            return {
                "question": (
                    "Welcome! Looking at your experience at Acme Cloud, you noted a 45% reduction in "
                    "end-to-end event latency on your Kafka pipeline. Walk me through the exact bottlenecks "
                    "in the legacy setup and your partitioning design."
                ),
                "turn_type": "resume_claim",
                "source": "resume",
                "source_ref": "Acme Cloud Infrastructure: Kafka 45% event latency reduction",
                "reasoning_note": "Starting with an impactful metrics-grounded claim from recent experience.",
            }
        elif self.call_count == 2:
            # Turn 2: Follow-up grounded in candidate's actual answer
            return {
                "question": (
                    "You mentioned switching from synchronous database writes to an in-memory ring buffer. "
                    "How did your consumer pool prevent out-of-memory errors when downstream processing stalled?"
                ),
                "turn_type": "follow_up",
                "source": "resume",
                "source_ref": "prior_answer: in-memory ring buffer memory backpressure",
                "reasoning_note": "Challenging the memory bounds and failure modes of their claimed ring buffer.",
            }
        elif self.call_count == 3:
            # Turn 3: Context switch to GitHub repository
            return {
                "question": (
                    "That clarifies the consumer backpressure design. Pivoting to your GitHub portfolio: "
                    "in your 'Spoon-Knife' repository, how did you structure the workflow documentation for fork synchronization?"
                ),
                "turn_type": "context_switch",
                "source": "github",
                "source_ref": "repo: Spoon-Knife / README fork guidelines",
                "reasoning_note": "Switching context to candidate's public GitHub portfolio after 2 resume turns.",
            }
        else:
            return {
                "question": "Thank you for walking through your experience and open-source work. That concludes our interview.",
                "turn_type": "closing",
                "source": "resume",
                "source_ref": "session_completion",
                "reasoning_note": "Closing interview.",
            }


@pytest.mark.asyncio
async def test_e2e_interview_session_flow():
    """End-to-end multi-turn interview test verifying all 4 endpoints, grounding, follow-ups, and context switches."""
    mock_client = MockRealisticLLMClient()
    mock_agent = InterviewerAgent(llm_client=mock_client)

    app.dependency_overrides[get_agent] = lambda: mock_agent

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Start Session (Turn 1)
        start_payload = {
            "github_username": "octocat",
            "resume_file_path": "sample_resume.txt",
        }
        res_start = await client.post("/session/start", json=start_payload)
        assert res_start.status_code == 201
        data_start = res_start.json()

        session_id = data_start["session_id"]
        assert session_id is not None
        assert data_start["status"] == "active"
        assert data_start["turn_index"] == 1

        turn_1 = data_start["turn"]
        assert turn_1["turn_type"] == "resume_claim"
        assert turn_1["source"] == "resume"
        # Non-generic assertion: specific claim referenced
        assert "45%" in turn_1["source_ref"] or "Kafka" in turn_1["source_ref"]
        assert len(turn_1["source_ref"]) > 10
        assert turn_1["reasoning_note"] is not None

        # 2. Candidate Submits Answer -> Generates Turn 2 (Follow-up)
        answer_1_payload = {
            "answer": "We removed synchronous MySQL writes from the worker threads and buffered events in a ring buffer with 10k capacity."
        }
        res_turn_2 = await client.post(f"/session/{session_id}/answer", json=answer_1_payload)
        assert res_turn_2.status_code == 200
        data_turn_2 = res_turn_2.json()
        assert data_turn_2["turn_index"] == 2
        turn_2 = data_turn_2["turn"]
        # Follow-up assertion: at least one follow-up occurs
        assert turn_2["turn_type"] == "follow_up"
        assert "prior_answer" in turn_2["source_ref"]
        assert "ring buffer" in turn_2["question"].lower()

        # 3. Candidate Submits Answer -> Generates Turn 3 (Context Switch to GitHub)
        answer_2_payload = {
            "answer": "We implemented exponential backoff and paused the Kafka consumer partition if buffer utilization crossed 85%."
        }
        res_turn_3 = await client.post(f"/session/{session_id}/answer", json=answer_2_payload)
        assert res_turn_3.status_code == 200
        data_turn_3 = res_turn_3.json()
        assert data_turn_3["turn_index"] == 3
        turn_3 = data_turn_3["turn"]
        # Context switch assertion: at least one context switch occurs
        assert turn_3["turn_type"] == "context_switch"
        assert turn_3["source"] == "github"
        assert "repo:" in turn_3["source_ref"]

        # 4. Get Transcript
        res_transcript = await client.get(f"/session/{session_id}/transcript")
        assert res_transcript.status_code == 200
        transcript_data = res_transcript.json()

        assert transcript_data["session_id"] == session_id
        assert transcript_data["turn_count"] == 3
        assert len(transcript_data["covered_refs"]) >= 3
        assert len(transcript_data["transcript"]) == 5  # Q1, A1, Q2, A2, Q3

        # Verify sources covered
        covered_sources = {r["source"] for r in transcript_data["covered_refs"]}
        assert "resume" in covered_sources
        assert "github" in covered_sources

        # 5. End Session
        res_end = await client.post(f"/session/{session_id}/end")
        assert res_end.status_code == 200
        end_data = res_end.json()
        assert end_data["status"] == "completed"
        assert end_data["summary"]["resume_questions_count"] == 2
        assert end_data["summary"]["github_questions_count"] == 1
        assert end_data["summary"]["follow_up_count"] == 1
        assert end_data["summary"]["context_switch_count"] == 1

        # 6. Verify subsequent answer attempt fails on completed session (409 Conflict)
        res_after_end = await client.post(
            f"/session/{session_id}/answer",
            json={"answer": "Trying to answer after close"},
        )
        assert res_after_end.status_code == 409

    # Clean up dependency override
    app.dependency_overrides.clear()

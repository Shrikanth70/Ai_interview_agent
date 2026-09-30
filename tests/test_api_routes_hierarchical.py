import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.mark.asyncio
async def test_start_session_route_with_jd_and_theme():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "resume_text": "Experienced Python Engineer building high-throughput message brokers.",
            "github_username": "octocat",
            "use_mock_github": True,
            "llm_provider": "mock",
            "starting_theme": "JD",
            "jd_scenarios": [
                {
                    "scenario_id": "stream_worker",
                    "title": "Stream Worker High Throughput",
                    "problem_statement": "Telemetry pipeline must scale to 50k msgs/sec.",
                }
            ],
        }
        resp = await client.post("/session/start", json=payload)
        assert resp.status_code == 201
        data = resp.json()
        assert data["session_id"]
        assert "orchestration" in data
        assert data["orchestration"] is not None
        assert data["orchestration"]["active_theme"] == "JD"
        assert data["orchestration"]["active_context_id"] == "jd:stream_worker"
        assert data["turn"]["turn_type"] == "role_scenario"
        assert data["turn"]["source"] == "jd"
        assert data["turn"]["source_ref"] == "Stream Worker High Throughput"

        session_id = data["session_id"]

        # Turn 2: Submit answer with SWITCH_CONTEXT -> Bridge to PROFILE
        ans_payload = {
            "answer": "We implemented a zero-copy ring buffer with shared memory.",
            "jev_signal": "SWITCH_CONTEXT",
        }
        ans_resp = await client.post(f"/session/{session_id}/answer", json=ans_payload)
        assert ans_resp.status_code == 200
        ans_data = ans_resp.json()
        assert ans_data["orchestration"] is not None
        assert ans_data["orchestration"]["active_theme"] == "PROFILE"
        assert ans_data["orchestration"]["is_bridge_turn"] is True

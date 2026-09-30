# Streamlit UI & REST API Hierarchical 2-Theme Engine Integration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the 3-tier hierarchical memory model and 2-theme engine (`PROFILE` vs `JD`) into the FastAPI REST API contracts and modernize `streamlit_app.py` with JD scenarios, 25-minute budget timer, JEV evaluator simulation controls (`FOLLOW_UP` vs `SWITCH_CONTEXT`), and live sub-memory inspection.

**Architecture:** Extend Pydantic v2 schemas in `app/api/models.py` to accept starting themes, custom JD scenarios, and JEV signals while returning orchestration metadata. Update `app/api/routes.py` to pass these parameters to `InterviewerAgent.execute_turn()`. Overhaul `streamlit_app.py` to provide a modern, interactive dashboard visualizing the 2-theme engine, bridge questions, and hierarchical memory state.

**Tech Stack:** Python 3.10+, FastAPI, Pydantic v2, Streamlit, httpx, pytest.

---

### Task 1: API Schemas Enhancement (`app/api/models.py`)

**Files:**
- Modify: `app/api/models.py`
- Test: `tests/test_api_models_hierarchical.py`

- [ ] **Step 1: Write the failing unit tests for API schemas**

Create `tests/test_api_models_hierarchical.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_api_models_hierarchical.py -v`
Expected: FAIL (cannot import `OrchestrationResponse` or unexpected keyword arguments)

- [ ] **Step 3: Update `app/api/models.py`**

In `app/api/models.py`:
1. Add `starting_theme: Optional[Literal["PROFILE", "JD"]] = Field(default=None, description="Initial theme override (PROFILE or JD). If None, randomized 50/50.")`
2. Add `jd_text: Optional[str] = Field(default=None, description="Optional raw text of the target role Job Description.")`
3. Add `jd_scenarios: Optional[List[Dict[str, Any]]] = Field(default=None, description="Optional pre-structured JD technical scenarios.")`
4. Add `jev_signal: Optional[Literal["FOLLOW_UP", "SWITCH_CONTEXT"]] = Field(default=None, description="External evaluator signal driving next question strategy.")` to `SubmitAnswerRequest`.
5. Add `OrchestrationResponse` model.
6. Add `orchestration: Optional[OrchestrationResponse] = Field(default=None)` to `StartSessionResponse` and `SubmitAnswerResponse`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_api_models_hierarchical.py -v`
Expected: PASS

- [ ] **Step 5: Commit (check auto_commit)**

Check `.agent/config.yml` for `auto_commit` setting.
If `auto_commit: false`: skip commit and staging. Print: "Skipping commit (auto_commit: false)."

---

### Task 2: API Route Orchestration (`app/api/routes.py`)

**Files:**
- Modify: `app/api/routes.py`
- Test: `tests/test_api_routes_hierarchical.py`

- [ ] **Step 1: Write the failing integration test**

Create `tests/test_api_routes_hierarchical.py`:
```python
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
        assert data["orchestration"]["active_theme"] == "JD"
        assert data["orchestration"]["active_context_id"] == "jd:stream_worker"

        session_id = data["session_id"]

        # Turn 2: Submit answer with SWITCH_CONTEXT
        ans_payload = {
            "answer": "We implemented a zero-copy ring buffer with shared memory.",
            "jev_signal": "SWITCH_CONTEXT",
        }
        ans_resp = await client.post(f"/session/{session_id}/answer", json=ans_payload)
        assert ans_resp.status_code == 200
        ans_data = ans_resp.json()
        assert ans_data["orchestration"]["active_theme"] == "PROFILE"
        assert ans_data["orchestration"]["is_bridge_turn"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_api_routes_hierarchical.py -v`
Expected: FAIL (`orchestration` missing from response or theme not honored)

- [ ] **Step 3: Update `app/api/routes.py`**

In `app/api/routes.py`:
1. Define helper `_build_orchestration_response(state: SessionState, is_bridge: bool = False) -> OrchestrationResponse` to construct `OrchestrationResponse` extracting `active_theme`, `active_context_id`, current dimension, `minutes_remaining`, `elapsed_minutes`, `is_closing_time`, and sub-memories summaries.
2. In `start_session`:
   - If `payload.jd_scenarios` is passed, store it into `state.source_memory["jd_scenarios"] = payload.jd_scenarios`.
   - If `payload.jd_text` is passed, parse/wrap it and store in `state.source_memory["jd_text"] = payload.jd_text`.
   - Pass `starting_theme=payload.starting_theme` to `agent.execute_turn(state, starting_theme=payload.starting_theme)`.
   - Attach `orchestration=_build_orchestration_response(state)` to `StartSessionResponse`.
3. In `submit_answer`:
   - Pass `jev_signal=payload.jev_signal` to `agent.execute_turn(state, candidate_answer=clean_answer, jev_signal=payload.jev_signal)`.
   - Check if the turn was a bridge question (`state.orchestration.theme_switch_pending` or `turn_output.turn_type == "context_switch"`).
   - Attach `orchestration=_build_orchestration_response(state, is_bridge=...)` to `SubmitAnswerResponse`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_api_routes_hierarchical.py -v`
Expected: PASS

- [ ] **Step 5: Commit (check auto_commit)**

Check `.agent/config.yml` for `auto_commit` setting.
If `auto_commit: false`: skip commit and staging. Print: "Skipping commit (auto_commit: false)."

---

### Task 3: Streamlit Frontend Redesign (`streamlit_app.py`)

**Files:**
- Modify: `streamlit_app.py`

- [ ] **Step 1: Implement Enterprise JD Scenarios & Starting Theme Controls in Setup Form**

In `streamlit_app.py`:
- Add Job Description setup section with pre-loaded default scenarios (`DEFAULT_JD_SCENARIOS`) or custom JD input option.
- Add Starting Theme Selector: `Auto (50/50 Random per spec)`, `Theme 1: Candidate Profile`, `Theme 2: Job Description Scenario`.
- Pass `starting_theme`, `jd_scenarios`, and `jd_text` into `/session/start` request payload.

- [ ] **Step 2: Implement Live Session Budget Card & Theme Indicator**

In `streamlit_app.py`:
- Add top dashboard header showing:
  - ⏱️ Session Budget: 25-Minute Limit countdown (`X min remaining`), elapsed time, and turn progress bar (`Turn N / 12`).
  - 🎯 Theme Pill: `💜 Theme 1: Candidate Profile` vs `🎯 Theme 2: Job Description Scenario`.
  - 📈 Rubric Ladder Tracker: `1. Clarity of Framing` ➔ `2. Methodology Depth` ➔ `3. Trade-off Analysis`.
  - 🌉 Bridge Transition Banner when `is_bridge_turn` is true.

- [ ] **Step 3: Implement Hybrid JEV Submission Buttons**

In `streamlit_app.py`:
- Replace single answer button with 3 action buttons:
  - `💬 Submit Answer (Auto-Evaluate)` (sends `jev_signal=None`)
  - `🔍 Submit & Force Follow-Up (Probe Rubric Depth)` (sends `jev_signal="FOLLOW_UP"`)
  - `🌉 Submit & Force Context Switch (Trigger Bridge Question)` (sends `jev_signal="SWITCH_CONTEXT"`)

- [ ] **Step 4: Add Hierarchical Memory Inspector Drawer**

In `streamlit_app.py`:
- Add sidebar/expander tab "🧠 Hierarchical Sub-Memory Tree" rendering active sub-memory, completed/pending rubric dimensions, and globally covered topics.

- [ ] **Step 5: Verify Streamlit App Syntax & Health**

Run: `python -m py_compile streamlit_app.py`
Expected: Exits 0 with no syntax errors.

---

### Task 4: Full Suite Regression Verification

**Files:**
- Test: All tests in `tests/`

- [ ] **Step 1: Run complete pytest suite**

Run: `pytest tests/ -v`
Expected: All 56+ tests PASS (100% success).

- [ ] **Step 2: Commit (check auto_commit)**

Check `.agent/config.yml` for `auto_commit` setting.
If `auto_commit: false`: skip commit and staging. Print: "Skipping commit (auto_commit: false)."

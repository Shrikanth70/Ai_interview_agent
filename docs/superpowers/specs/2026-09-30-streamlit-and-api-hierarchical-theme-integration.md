# Design Specification: Streamlit UI & REST API Hierarchical 2-Theme Engine Integration

**Date**: 2026-09-30  
**Status**: Proposed  
**Branch**: `main`  
**Dependencies**: `app/agent/interviewer.py`, `app/agent/theme_fetcher.py`, `app/session/state.py`

---

## 1. Problem Statement & Motivation

While the core interviewer engine (`interviewer.py`), deterministic fetcher (`theme_fetcher.py`), and state machine (`state.py`) were upgraded to the 3-tier hierarchical memory model and 2-theme engine (`PROFILE` vs `JD`), the **REST API contracts (`models.py`, `routes.py`)** and the **Streamlit Web UI (`streamlit_app.py`)** still reflected the legacy single-theme version.

Specifically:
1. `streamlit_app.py` only collected Resume and GitHub inputs, with no Job Description (JD) input or scenario selection.
2. The UI had no visibility into or control over the **JEV Evaluator Signal** (`FOLLOW_UP` vs `SWITCH_CONTEXT`), causing turns to execute without explicit signal testing.
3. The UI did not display the **25-Minute Session Budget Countdown** or **Rubric Depth Ladder**.
4. The REST API did not accept `starting_theme` or `jev_signal`, and did not return active orchestration state in turn responses.

---

## 2. Proposed Architecture & Enhancements

### 2.1 REST API Model Enhancements (`app/api/models.py`)

1. **`StartSessionRequest`**:
   - `starting_theme: Optional[Literal["PROFILE", "JD"]] = None`
   - `jd_scenarios: Optional[List[Dict[str, Any]]] = None`
   - `jd_text: Optional[str] = None`
2. **`SubmitAnswerRequest`**:
   - `jev_signal: Optional[Literal["FOLLOW_UP", "SWITCH_CONTEXT"]] = None`
3. **`OrchestrationResponse`**:
   - `active_theme: Literal["PROFILE", "JD"]`
   - `active_context_id: str`
   - `current_rubric_dimension: Optional[str]`
   - `is_bridge_turn: bool`
   - `minutes_remaining: float`
   - `elapsed_minutes: float`
   - `is_closing_time: bool`
   - `sub_memories: List[Dict[str, Any]]`
   - `globally_covered_topics: List[str]`
4. **`StartSessionResponse` & `SubmitAnswerResponse`**:
   - Include `orchestration: Optional[OrchestrationResponse] = None` alongside `turn`.

---

### 2.2 Route Orchestration Updates (`app/api/routes.py`)

1. **`POST /session/start`**:
   - Ingests JD text / scenarios if provided; falls back to default JD scenarios.
   - Saves JD data into `state.source_memory["jd_scenarios"]`.
   - Passes `starting_theme=payload.starting_theme` to `agent.execute_turn(state, ...)`.
   - Formats `OrchestrationResponse` from `state` and returns in response.
2. **`POST /session/{id}/answer`**:
   - Passes `jev_signal=payload.jev_signal` to `agent.execute_turn(state, ...)`.
   - Formats `OrchestrationResponse` from updated `state`.

---

### 2.3 Streamlit Frontend Redesign (`streamlit_app.py`)

1. **Setup & Ingestion Panel**:
   - **Candidate Profile**: Resume upload / sample selector + GitHub handle/mock.
   - **Job Description (JD)**:
     - Select from pre-loaded enterprise scenarios (*High-Throughput Stream Ingestion*, *Low-Latency Distributed Caching*, *Microservice Event Bus*) or enter custom JD role requirements.
   - **Starting Theme Selector**: Auto (Randomized 50/50 per spec) vs Explicit `PROFILE` vs `JD`.
2. **Live Interview Dashboard**:
   - **Session Budget Header**: Real-time 25-minute timer countdown, elapsed time, and turn progress (e.g. Turn 3/12).
   - **Active Theme & Rubric Bar**:
     - Theme pill: `💜 Theme 1: Candidate Profile` or `🎯 Theme 2: Job Description Scenario`.
     - Sub-memory anchor target (e.g., `github:distributed-cache` or `jd:high_throughput_ingestion`).
     - Rubric ladder progress: `1. Clarity of Framing` ➔ `2. Methodology Depth` ➔ `3. Trade-off Analysis`.
   - **Bridge Question Alert**: High-contrast banner highlighting when a turn is a bridge question transitioning across themes.
3. **Hybrid JEV Evaluator Submission Controls**:
   - Default primary button: `💬 Submit Answer (Auto-Evaluate)`
   - Override button 1: `🔍 Submit & Force Follow-Up (Probe Deeper)`
   - Override button 2: `🌉 Submit & Force Context Switch (Trigger Bridge Question)`
4. **Hierarchical Memory Inspector (Sidebar / Expander)**:
   - Live tree view of all `ContextSubMemory` instances.
   - Sliding 2-3 turn dialogue window preview.
   - Globally covered anti-duplication topic registry.

---

## 3. Success & Verification Criteria

1. `POST /session/start` accepts custom JD and `starting_theme` and returns turn + orchestration metadata.
2. `POST /session/{id}/answer` accepts `jev_signal="SWITCH_CONTEXT"` and produces a verified bridge question and theme pivot.
3. Streamlit UI launches and visually exposes the 2-theme engine, budget timer, bridge badges, and JEV buttons.
4. All unit tests (`pytest tests/`) pass with 100% success.

# Design Specification: First-Class `role_scenario` Turn Type for Theme: JD

**Date**: 2026-09-30  
**Status**: Approved  
**Target Files**: `app/session/state.py`, `app/agent/interviewer.py`, `app/api/models.py`, `streamlit_app.py`  

---

## 1. Problem Statement
When an interview session was initialized with **Theme: JD**, the opening question was being mislabeled with `turn_type="resume_claim"`. This occurred because:
1. `_generate_deterministic_fallback` in `interviewer.py` had `turn_type="theme_switch" if not is_opening else "resume_claim"`, forcing `resume_claim` on Turn 1 regardless of theme.
2. `_build_conversation_messages` in `interviewer.py` had a single Turn 1 prompt contract requiring the model to ask about a candidate's resume claim, lacking the branch for Case B (`Theme: JD`).

---

## 2. Proposed Architecture & Changes

### 2.1 Turn Type Schema Updates
1. In `app/session/state.py`, `app/agent/interviewer.py`, and `app/api/models.py`:
   - Add `"role_scenario"` to `turn_type: Literal[...]`.
   - In `normalize_turn_type`, support `"role_scenario"` and alias `"jd_scenario"` -> `"role_scenario"`.

### 2.2 Dual-Branch Opening Prompt Contract
In `_build_conversation_messages` of `app/agent/interviewer.py`:
- If `state.orchestration.active_theme == "PROFILE"`:
  - Keep Case A: Welcome greeting probing a real project or claim from resume/GitHub.
  - `turn_type = "resume_claim"` or `"github_project"`.
- If `state.orchestration.active_theme == "JD"`:
  - Implement Case B: Welcome greeting introducing the active role scenario from `active_sub.source_slice`.
  - Pattern: *"Welcome! In this role, we frequently design systems tackling '{title}': {problem_statement}. Walk me through how you would architect a solution from scratch and what primary trade-offs you would design around."*
  - `turn_type = "role_scenario"`, `source = "jd"`, `source_ref = active_sub.source_ref`.

### 2.3 Deterministic Fallback Alignment
In `_generate_deterministic_fallback`:
- If `active_theme == "JD"`:
  - If `is_opening`: `turn_type = "role_scenario"`.
  - If `state.orchestration.theme_switch_pending`: `turn_type = "theme_switch"`.
  - Else: `turn_type = "follow_up"`.

### 2.4 Streamlit UI Rendering
- Ensure `role_scenario` renders with badge `badge-jd`.

---

## 3. Success Criteria
1. Initializing a session with `starting_theme="JD"` emits `turn_type="role_scenario"` and `source="jd"`.
2. Initializing with `starting_theme="PROFILE"` emits `turn_type="resume_claim"` (or `"github_project"`).
3. All 58 existing unit & integration tests in `pytest tests/` pass.

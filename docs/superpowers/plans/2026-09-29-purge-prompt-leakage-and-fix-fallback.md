# Purge Prompt Leakage & Fix Fallback Parser Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate entity prompt leakage (e.g. "MovieBuddy"), dynamically anchor Turn 1 prompts to verified candidate topics, and fix inverted logic in the deterministic fallback parser to prevent "Senior AI" hallucinations.

**Architecture:** 
1. Sanitize system prompt and few-shot calibration examples in `app/llm/prompts.py` to remove any concrete project names that small models (Llama 3.2 3B) copy.
2. In `app/agent/interviewer.py`, dynamically extract 2-4 candidate-grounded anchor topics from the uploaded resume and pass them as explicit options in the Turn 1 directive.
3. In `app/agent/grounding.py`, rewrite `extract_deterministic_fallback_target` with an explicit `SKILLS_SECTION_WHITELIST`, atomic slash handling, and seniority/title blacklisting, falling back to genuine experience bullets.

**Tech Stack:** Python 3.10+, FastAPI, Pydantic v2, pytest.

---

### Task 1: Purge All Concrete Entities from System Directives

**Files to modify:**
- `app/llm/prompts.py`
- `tests/test_grounding.py`

- [ ] **Step 1.1**: Write a test in `tests/test_grounding.py` verifying that `MASTER_SYSTEM_PROMPT` contains zero occurrences of "MovieBuddy" and only structural placeholders.
- [ ] **Step 1.2**: Update line 26 in `app/llm/prompts.py` to replace `"MovieBuddy"` with `<project_name>`.
- [ ] **Step 1.3**: Run `pytest tests/test_grounding.py -k test_prompts_free_of_leakage_entities` to confirm the test passes.

---

### Task 2: Fix `extract_deterministic_fallback_target` Parser

**Files to modify:**
- `app/agent/grounding.py`
- `tests/test_grounding.py`

- [ ] **Step 2.1**: Write unit tests in `tests/test_grounding.py`:
  - `test_deterministic_fallback_on_arjun_reddy_never_extracts_senior_ai`: Verifies that on Arjun Reddy's resume without a skills section, the fallback extracts a real experience/project bullet, and NEVER `"Senior AI"` or `"Skills Section: Senior AI"`.
- [ ] **Step 2.2**: Run the test to confirm it fails on current code.
- [ ] **Step 2.3**: In `app/agent/grounding.py`:
  - Define `SKILLS_SECTION_WHITELIST = {"skills", "core skills", "technical skills", "technologies", "core competencies", "tools & technologies", "technical competencies", "skills & tools"}`.
  - Only look for skills in sections where `clean_lower in SKILLS_SECTION_WHITELIST`.
  - In sub-line splitting, split on `r"[,|•;]"` instead of `r"[,|•;/]"`.
  - Add seniority, job title, and role words to `NON_SKILL_BLACKLIST`:
    `{"senior", "junior", "lead", "principal", "staff", "intern", "associate", "manager", "director", "vp", "head", "engineer", "developer", "architect", "specialist", "analyst", "consultant", "scientist", "researcher", "officer"}`.
  - When no skills section is found, fall back directly to an experience or project bullet with `target = clean_line`, `ref = clean_line[:65]`.
- [ ] **Step 2.4**: Run `pytest tests/test_grounding.py -k test_deterministic_fallback` and confirm tests pass.

---

### Task 3: Dynamic Candidate Anchoring for Turn 1

**Files to modify:**
- `app/agent/grounding.py` (add `extract_candidate_anchors(resume_text)`)
- `app/agent/interviewer.py` (inject anchors into Turn 1 instruction)
- `tests/test_grounding.py`

- [ ] **Step 3.1**: Implement `extract_candidate_anchors(resume_text: str) -> List[str]` in `app/agent/grounding.py`:
  - Identifies project titles (e.g. lines after "SELECTED PROJECTS" or lines matching project headers) or top role accomplishments.
  - Returns 2-4 clean, concise anchor strings (e.g. `["Enterprise Knowledge Assistant", "Real-Time Fraud Detection System", "AI Document Processing Platform"]`).
- [ ] **Step 3.2**: In `app/agent/interviewer.py`, update Turn 1 instruction builder:
  - Call `extract_candidate_anchors(state.resume_text)`.
  - Inject anchor suggestions into the prompt:
    `"VERIFIED CANDIDATE ANCHOR TOPICS FROM RESUME (Focus your opening question on one of these): ..."`
- [ ] **Step 3.3**: Write unit test verifying that `extract_candidate_anchors` correctly extracts project titles from Arjun Reddy's resume and messy resumes.
- [ ] **Step 3.4**: Run pytest to verify all tests pass.

---

### Task 4: End-to-End Verification & Live Simulation

- [ ] **Step 4.1**: Run `pytest -v` across the complete test suite (all 35+ tests).
- [ ] **Step 4.2**: Run live simulation script with Ollama `llama3.2:latest` on `sessions/75df8b1b-aa23-4aed-835e-2a06254f012a.json` to verify that Turn 1 generates a grounded question on Attempt 1 without falling back.

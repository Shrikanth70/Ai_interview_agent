# Multi-Layer Deterministic Anti-Hallucination Guardrail Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a 4-layer deterministic defense in the AI Interview Agent backend to permanently prevent prompt few-shot leakage, metric hallucinations (e.g. "450ms down to 40ms"), and cross-bullet claim amalgamations.

**Architecture:** 
1. Sanitized structural few-shot examples in `app/llm/prompts.py` replacing concrete tech with abstract structural templates.
2. Numeric & metric claim verifier in `app/agent/grounding.py` rejecting any ungrounded numbers or units in questions.
3. Interviewer assertion clause grounding (`you highlighted/optimized [X]`) in `validate_question_assumptions`.
4. Co-occurrence chunk-level grounding in `is_source_ref_grounded` preventing cross-section chimera references.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, Pytest, Regex.

---

### Task 1: Layer 1 - Sanitize Few-Shot Examples in `app/llm/prompts.py`

**Files:**
- Modify: `app/llm/prompts.py:69-102`
- Modify: `app/agent/interviewer.py:220-230`
- Test: `tests/test_refinements.py`

- [ ] **Step 1: Update few-shot examples to structural templates**
In `app/llm/prompts.py`, rewrite `FEW_SHOT_EXAMPLES` to eliminate concrete domain technologies and metrics (`Kafka`, `450ms -> 40ms`, `RocksDB/Raft at 45,000 TPS`), replacing them with abstract placeholders (e.g. `<ProjectName>`, `<ArchitectureComponent>`, `<TargetMetric>`) and clean technical question patterns. Also update `interviewer.py` instructions to reinforce that few-shot values are abstract markers.

- [ ] **Step 2: Run existing tests to verify prompt assembly remains valid**
Run: `pytest tests/test_refinements.py -v`
Expected: PASS

---

### Task 2: Layer 2 - Strict Metric & Numeric Claim Verifier in `app/agent/grounding.py`

**Files:**
- Modify: `app/agent/grounding.py:100-180`
- Test: `tests/test_grounding.py`

- [ ] **Step 1: Write failing unit test for metric hallucination rejection**
In `tests/test_grounding.py`, add `test_validate_question_assumptions_rejects_hallucinated_metrics()`:
- Test that a question containing `"reduce latency from 450ms down to 40ms"` against Arjun Reddy's resume is REJECTED with reason `"hallucinated metric detected"`.
- Test that a question containing `"reduced average response latency by approximately 35%"` (which is genuinely in Arjun Reddy's resume) PASSES.

- [ ] **Step 2: Run test to verify it fails (RED)**
Run: `pytest -k test_validate_question_assumptions_rejects_hallucinated_metrics -v`
Expected: FAIL

- [ ] **Step 3: Implement metric extraction and verification**
In `app/agent/grounding.py`:
- Add `extract_numerical_metrics(text: str) -> List[str]` identifying latency/rate/percent units (`ms`, `s`, `tps`, `qps`, `%`, `x`) and significant standalone numbers (`\b\d{2,}\b`).
- In `validate_question_assumptions()`, verify every extracted metric from `question` appears in `established_corpus`.

- [ ] **Step 4: Run test to verify it passes (GREEN)**
Run: `pytest -k test_validate_question_assumptions_rejects_hallucinated_metrics -v`
Expected: PASS

---

### Task 3: Layer 3 & 4 - Assertion Clause and Co-Occurrence Grounding

**Files:**
- Modify: `app/agent/grounding.py:115-380`
- Test: `tests/test_grounding.py`

- [ ] **Step 1: Write failing unit tests for assertion clause and co-occurrence rejection**
In `tests/test_grounding.py`:
- Add `test_validate_question_assumptions_rejects_hallucinated_assertion()` testing that `"Welcome! Looking over your experience and background, you highlighted optimizing an event pipeline with Apache Kafka to reduce latency..."` is rejected because Arjun Reddy never claimed event pipeline latency optimization for Kafka.
- Add `test_is_source_ref_grounded_rejects_cross_bullet_chimera()` testing that `source_ref="Kafka event pipeline optimization (latency reduction)"` is rejected because `Kafka` and `latency reduction` reside in different jobs.

- [ ] **Step 2: Run tests to verify they fail (RED)**
Run: `pytest -k "test_validate_question_assumptions_rejects_hallucinated_assertion or test_is_source_ref_grounded_rejects_cross_bullet_chimera" -v`
Expected: FAIL

- [ ] **Step 3: Implement assertion clause extraction and bullet chunk co-occurrence**
In `app/agent/grounding.py`:
- In `validate_question_assumptions()`, add regex for `you (highlighted|noted|stated|mentioned|described|built|designed|implemented|optimized|developed|created) <phrase>` and check whether the core verb-subject combination exists in the dossier.
- In `is_source_ref_grounded()`, break `target_text` into bullet/paragraph chunks. If `source_ref` contains >= 3 substantive tokens, require that at least 2 key tokens co-occur within the same chunk.

- [ ] **Step 4: Run tests to verify they pass (GREEN)**
Run: `pytest -k "test_validate_question_assumptions_rejects_hallucinated_assertion or test_is_source_ref_grounded_rejects_cross_bullet_chimera" -v`
Expected: PASS

---

### Task 4: Full Suite Verification & Regression Check

**Files:**
- Test: `tests/`

- [ ] **Step 1: Run full pytest suite across all test files**
Run: `pytest`
Expected: All 35+ tests pass with zero regressions.

- [ ] **Step 2: Verify Arjun Reddy full turn simulation**
Run an end-to-end test with Arjun Reddy's resume ensuring opening question is 100% grounded in real claims without any Kafka latency or few-shot leakage.

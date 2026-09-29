# Design Specification: Handling Complex Senior Resumes Without a Dedicated Skills Section

**Date:** 2026-09-29  
**Status:** Approved  
**Topic:** Adaptive Skill Anchoring & Senior Architectural Probing for Resumes Lacking an Explicit Skills Section  

---

## 1. Executive Summary & Problem Statement

In real-world technical hiring, senior and staff engineers frequently submit resumes that lack a dedicated "Technical Skills" or "Keywords" section. Instead, their technologies, architectural patterns, and competencies are woven directly into detailed work experience bullets (e.g., *"Architected distributed event settlement service in Go and RocksDB processing 15,000 TPS with 99.99% availability"*).

### Vulnerabilities in the Current Implementation
1. **Few-Shot Template Bias & Hallucination**:
   Calibration Example 4 in [app/llm/prompts.py](file:///c:/Users/Bhukya%20Shrikanth/OneDrive/Desktop/Interview-agent/app/llm/prompts.py) uses the template:
   `"You have 'eBPF / Kernel Tracing' listed in your technical skills section. Where have you actually applied eBPF in practice..."`
   When an experienced candidate has no skills section, the LLM is at risk of mimicking this exact phrasing, hallucinating that a skills section exists and violating our strict grounding mandate.
2. **Superficial Questioning Risk**:
   Without explicit seniority guidelines, the LLM may default to basic syntax trivia or fixate exclusively on the most recent job, rather than probing multi-year architectural trade-offs, scaling limits, and failure modes across the candidate's career.
3. **Implicit Skill Grounding Alignment**:
   When the agent probes an implicit skill extracted from an experience bullet, `source_ref` must follow clean conventions (e.g., `"RocksDB / Raft state engine (Acme Corp)"`) that seamlessly pass code-level grounding verification in [app/agent/grounding.py](file:///c:/Users/Bhukya%20Shrikanth/OneDrive/Desktop/Interview-agent/app/agent/grounding.py).

---

## 2. Architectural Principles & Constraints

- **Strict Adherence to Core Philosophy (NO RAG, NO Vector DB)**:
  All reasoning continues to happen over the full candidate dossier kept in the LLM context window. The resume text is ingested in full by [app/ingestion/resume_loader.py](file:///c:/Users/Bhukya%20Shrikanth/OneDrive/Desktop/Interview-agent/app/ingestion/resume_loader.py) and stored in `SessionState.resume_text`. Zero experience text is discarded.
- **Zero Ingestion Latency / Cost Overhead**:
  No pre-flight LLM calls or complex regex dictionaries are introduced. The enhancement is achieved through rigorous prompt calibration, negative constraints, and grounding verification.
- **Traceability & Grounding**:
  Every question remains strictly verifiable against `resume_text` or `github_summary` with explicit `source_ref` and `reasoning_note`.

---

## 3. Detailed Component Changes

### 3.1 Prompt Refinement in `app/llm/prompts.py`

#### A. Senior & Complex Resume Mandate in `MASTER_SYSTEM_PROMPT`
Add an explicit directive governing complex and senior candidate dossiers:
- **Seniority & Architectural Depth**: When interviewing senior candidates with extensive career histories, questions must probe **architectural & production trade-offs**:
  1. System scalability limits and concurrency/bottleneck challenges.
  2. Failure modes, data consistency trade-offs, and disaster recovery strategies.
  3. Alternatives evaluated (why tool/architecture X was chosen over Y).
  4. Operational decisions under production constraints.
- **Career Breadth Coverage**: The agent should probe impactful achievements across their full career timeline rather than fixating solely on the most recent position.

#### B. Adaptive Skill-Anchored Inquiry (`turn_type='skill_anchored'`)
Update the rules governing `skill_anchored` turns:
- If a dedicated skills section exists, anchor to explicit skills.
- If **no dedicated skills section exists**, the agent must extract underlying technologies and system components directly from experience bullets.
- **Negative Hallucination Constraint**: Under no circumstances may the agent use phrases such as *"in your skills section"*, *"you listed under technical skills"*, or *"from your skills list"* if the resume does not have an explicit skills section.
- **Phrasing Convention**: Anchor the inquiry directly to the project or role:
  *Example*: *"Looking at your work on the settlement engine at Acme Corp, you leveraged RocksDB and Raft. At 15k TPS, what state compaction or write amplification bottlenecks did you encounter, and what alternative storage engines did you evaluate?"*

#### C. Calibration Few-Shot Example Update
Update Example 4 in `FEW_SHOT_EXAMPLES` to illustrate probing an embedded technology from a complex experience bullet focused on architectural trade-offs:
```json
{
  "question": "In your work architecting the real-time settlement engine at Acme Corp, you utilized RocksDB and Raft. At 15,000 TPS, what write amplification or compaction bottlenecks did you encounter, and what alternative state engines did you evaluate?",
  "turn_type": "skill_anchored",
  "source": "resume",
  "source_ref": "RocksDB / Raft state engine (Acme Corp)",
  "reasoning_note": "Extracting an embedded technical skill from experience achievements to probe production scaling trade-offs and alternative evaluations."
}
```

### 3.2 Fallback Phrasing in `app/agent/interviewer.py`

In `_generate_deterministic_fallback()`:
Update the fallback question template for `skill_anchored` turns to maintain the same senior architectural tone:
```python
question = (
    f"Turning to your experience with {target}: walk me through the system architecture where you applied it "
    f"and the primary operational or scaling trade-offs you navigated."
)
```

### 3.3 Grounding Validation in `app/agent/grounding.py`

- Ensure that `extract_deterministic_fallback_target()` cleanly utilizes Priority 2 (experience bullets) when Priority 1 (skills section) yields no matches.
- Confirm `is_source_ref_grounded()` correctly handles references citing company/role along with the embedded technology (e.g., `RocksDB / Raft state engine (Acme Corp)` matches tokens `["rocksdb", "raft", "state", "engine", "acme", "corp"]` in `resume_text`).

---

## 4. Testing & Verification Plan

### Automated Test Cases (`tests/test_senior_skill_less_resume.py` or updates to `tests/test_interviewer.py`)
1. **Fixture**: Create a realistic senior engineer resume containing only work experience bullets (architectures, scale numbers, distributed systems, technologies) and NO skills section headers.
2. **Turn 1 Grounding Test**: Verify that the opening turn successfully extracts a grounded technical claim from work experience and formats a professional welcome greeting without errors.
3. **Skill-Anchored Anti-Hallucination Test**: Execute a turn with `turn_type='skill_anchored'` on this resume:
   - Assert `"skills section"` not in `turn_output.question.lower()`.
   - Assert `"technical skills"` not in `turn_output.question.lower()`.
   - Assert `turn_output.source_ref` is verified as grounded against `resume_text`.
4. **Fallback Test**: Invoke `_generate_deterministic_fallback` on the skill-less resume and assert that it produces a valid question grounded in an experience bullet.
5. **Existing Regression Suite**: Run `pytest tests/` to verify that all existing tests continue to pass.

---

## 5. Scope Boundary

- No changes to frontend (none exists).
- No new database, embeddings, or vector stores.
- No changes to API routes or contract schemas (`InterviewerTurnOutput` schema remains untouched).

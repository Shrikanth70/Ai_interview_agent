# Design Specification: Purge Prompt Leakage & Fix Deterministic Fallback Parser

## 1. Overview & Problem Statement

In live interviews with smaller local models (e.g. Ollama `llama3.2:latest`, 3.2B parameters) evaluating resumes without explicit `CORE SKILLS` sections (such as Arjun Reddy's resume), Turn 1 degenerated into:
> *"Welcome! Looking over your experience and background, you highlighted your work with Senior AI. Walk me through a challenging technical problem you solved involving Senior AI and the primary architectural trade-offs you navigated."*
> **Metadata**: `Turn Intent: skill_anchored`, `Grounded Reference: Skills Section: Senior AI`, `Internal Reasoning: Deterministic app-layer fallback generated after LLM grounding validation failed twice.`

### Root Cause Analysis
1. **System Prompt Leakage**: In [`app/llm/prompts.py`](file:///c:/Users/Bhukya%20Shrikanth/OneDrive/Desktop/Interview-agent/app/llm/prompts.py), the prompt explicitly mentioned: `"If you ask about 'MovieBuddy', 'source_ref' MUST be 'MovieBuddy'"`. Llama 3.2 latched onto this entity and generated a question about "MovieBuddy" on Turn 1 Attempt 1.
2. **Calibration Example Leakage**: On retry with an anti-hallucination correction directive, Llama 3.2 copied `TelemetryRouter` from the calibration example.
3. **Anti-Hallucination Guardrail Validation**: The new deterministic guardrail in [`app/agent/grounding.py`](file:///c:/Users/Bhukya%20Shrikanth/OneDrive/Desktop/Interview-agent/app/agent/grounding.py) successfully rejected both "MovieBuddy" and "TelemetryRouter".
4. **Fallback Parser Inversion**: Because Attempt 1 and 2 failed, `_generate_deterministic_fallback` was invoked. In [`app/agent/grounding.py:616`](file:///c:/Users/Bhukya%20Shrikanth/OneDrive/Desktop/Interview-agent/app/agent/grounding.py#L616), `clean_lower in SECTION_HEADER_BLACKLIST` was used to identify skills sections. Non-skill sections like `PROFESSIONAL EXPERIENCE` were treated as skills sections. The parser then split `Senior AI/ML Engineer` on `/`, producing `"Senior AI"`, which was returned as `target = "Senior AI"`, `ref = "Skills Section: Senior AI"`.

---

## 2. Proposed Architecture & Fixes

### Component 1: Purge All Concrete Entities from System Directives
- **File**: `app/llm/prompts.py`
- Remove all mentions of `"MovieBuddy"` from `MASTER_SYSTEM_PROMPT`. Replace with abstract placeholder `<project_name>`.
- In `FEW_SHOT_EXAMPLES`, use abstract naming (`[Candidate Project A]`, etc.) or generic system descriptors to prevent smaller models from copying literal entity names.

### Component 2: Dynamic Candidate Anchoring for Turn 1
- **File**: `app/agent/interviewer.py`
- When constructing Turn 1 instructions, dynamically extract 2-4 candidate-grounded anchor topics directly from `state.resume_text` (e.g. named projects, key roles, or concrete technologies mentioned in experience).
- Inject an explicit prompt directive for Turn 1:
  ```
  VERIFIED CANDIDATE ANCHOR TOPICS FROM RESUME (You MUST select one of these for Turn 1):
  - {anchor_1}
  - {anchor_2}
  - {anchor_3}
  ```
- This gives smaller models (3B-8B) a clear, grounded set of choices on Attempt 1, avoiding hallucination and template copying.

### Component 3: Rewrite `extract_deterministic_fallback_target`
- **File**: `app/agent/grounding.py`
- **Disentangle Whitelist vs Blacklist**:
  - `SKILLS_SECTION_WHITELIST = {"skills", "core skills", "technical skills", "technologies", "core competencies", "tools & technologies", "technical competencies"}`
  - Only inspect lines under a section if `clean_lower in SKILLS_SECTION_WHITELIST`.
- **Preserve Slashes**:
  - Split candidate skill tokens on `r"[,|•;]"` instead of `r"[,|•;/]"`. Never split technical compound titles like `AI/ML` or `CI/CD` across slashes.
- **Job Title, Role & Seniority Blacklist**:
  - Add to `NON_SKILL_BLACKLIST`:
    `senior`, `lead`, `staff`, `principal`, `junior`, `intern`, `associate`, `manager`, `director`, `vp`, `head`, `engineer`, `developer`, `architect`, `specialist`, `analyst`, `consultant`, `scientist`, `researcher`, `officer`.
- **Bullet-First Fallback for Skill-Less Resumes**:
  - If no section matches `SKILLS_SECTION_WHITELIST`, extract the first substantial experience or project bullet point:
    `target = bullet_text`, `ref = bullet_text[:65]`, `turn_type = "resume_claim"`.
  - NEVER emit `ref = "Skills Section: ..."` if the resume does not contain a verified skills section!

---

## 3. Verification Plan

1. **Unit Tests (`tests/test_grounding.py`)**:
   - `test_deterministic_fallback_on_arjun_reddy_never_extracts_senior_ai`: Ensure `extract_deterministic_fallback_target` on Arjun Reddy's resume returns a real bullet or technology (e.g. RAG, LangGraph, or TechNova bullet) and NEVER "Senior AI".
   - `test_prompts_free_of_leakage_entities`: Ensure `MASTER_SYSTEM_PROMPT` contains zero occurrences of "MovieBuddy".
2. **Turn 1 Live Simulation**:
   - Run `InterviewerAgent().execute_turn(state)` with `llama3.2:latest` on Arjun Reddy's session and verify Turn 1 succeeds on Attempt 1 with a genuine resume topic.
3. **Full Test Suite**:
   - Run `pytest -v` across all 35+ tests and ensure 100% pass rate.

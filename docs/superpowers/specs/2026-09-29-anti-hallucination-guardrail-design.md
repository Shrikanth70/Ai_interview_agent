# Design Specification: Multi-Layer Deterministic Anti-Hallucination Guardrail

**Date:** 2026-09-29  
**Status:** Proposed / Review  
**Target Modules:** `app/llm/prompts.py`, `app/agent/grounding.py`, `tests/test_grounding.py`

---

## 1. Executive Summary & Problem Statement

In local and open-source LLM environments (e.g. Ollama with Llama-3 / Mistral), the AI Interview Agent occasionally generates fabricated assertions such as:
> *"Welcome! Looking over your experience and background, you highlighted optimizing an event pipeline with Apache Kafka to reduce latency from 450ms down to 40ms. Can you walk me through the design decisions you made on partitioning and replication strategies to achieve this significant performance improvement?"*

This hallucination slipped past the validation layer because of three architectural gaps:
1. **Few-Shot Prompt Contamination**: `FEW_SHOT_EXAMPLES` in `app/llm/prompts.py` contained hardcoded technical stories with specific numbers (`Apache Kafka`, `450ms -> 40ms`, `partitioning and replication strategies`). Small LLMs memorized and re-emitted these exact tokens whenever a candidate's resume shared even a single keyword (e.g. `Kafka`).
2. **Missing Numeric & Metric Validation**: The grounding layer only validated bag-of-words tokens from `source_ref`. It never extracted numbers, units, or percentages from the actual `question` text (`450ms`, `40ms`) to verify their presence in the candidate dossier.
3. **Cross-Section Token Amalgamation**: `is_source_ref_grounded()` computed token overlap across the entire resume text globally. A synthetic reference combining words from different sections (e.g., `Kafka` from Project 2 + `latency optimization` from Job 1) scored an 83% match ratio despite being a cross-bullet Frankenstein claim.
4. **Unchecked Interviewer Assertions**: `validate_question_assumptions()` only checked patterns like `in your <phrase>` or `for your <phrase>`, completely ignoring conversational assertions such as `you highlighted <phrase>`, `you achieved <phrase>`, or `you optimized <phrase>`.

---

## 2. Architectural Design: The 4 Layers of Defense

```mermaid
flowchart TD
    subgraph Prompting Layer
        P1["Prompt Assembly"] --> P2["Sanitized Few-Shot Examples (Generic Structural Placeholders)"]
    end
    
    subgraph Validation Layer
        LLM["LLM Turn Output"] --> V1{"Layer 1: Metric & Number Verifier"}
        V1 -->|Contains fabricated metric (e.g. 450ms)| REJECT["Validation Failure -> Retry / Fallback"]
        V1 -->|All metrics verified| V2{"Layer 2: Assertion Clause Verifier"}
        V2 -->|Asserts ungrounded claim ('you highlighted X')| REJECT
        V2 -->|Assertions grounded| V3{"Layer 3: Co-occurrence / Bullet Grounding"}
        V3 -->|source_ref tokens span separate bullets| REJECT
        V3 -->|Tokens co-occur in same context| PASS["Validated Output -> Candidate"]
    end
```

### Layer 1: Sanitized Few-Shot Calibration Examples (`app/llm/prompts.py`)
- **Objective**: Prevent the LLM from copying domain technologies, company names, or metrics out of calibration examples.
- **Implementation**:
  - Replace specific technologies and metrics (`Kafka`, `450ms -> 40ms`, `RocksDB/Raft at 45,000 TPS`) with domain-neutral structural templates using distinct, non-colliding entity markers (e.g., `<ProjectName>`, `<ArchitectureComponent>`, `<TargetMetric>`, or explicit structural skeletons).
  - Add explicit negative calibration directives informing the model that few-shot values are non-existent templates.

### Layer 2: Metric & Numeric Claim Verifier (`app/agent/grounding.py`)
- **Objective**: Ensure that any numerical metric, measurement, or percentage spoken in the question is verifiably present in the candidate's dossier.
- **Regex Detection**:
  - Detect units and numbers: `\b\d+(?:\.\d+)?\s*(?:ms|s|sec|seconds|tps|qps|rps|req\/s|%|percent|x|fold|k|m|gb|mb|tb)\b` and standalone numbers `\b\d{2,}\b`.
  - Exclude conversational turn references (e.g., "turn 1", "turn 2") and common generic words.
- **Verification Rule**:
  - Every extracted metric (e.g. `450ms`, `40ms`, `35%`) MUST appear in `resume_text` or `github_summary` (case-insensitive, normalized).
  - If a metric appears in the question but is absent from the candidate's dossier, immediately fail grounding with:
    `"hallucinated metric detected: question claimed '{metric}' which does not appear anywhere in candidate dossier"`.

### Layer 3: Co-Occurrence / Bullet-Level Grounding for `source_ref` (`app/agent/grounding.py`)
- **Objective**: Prevent Frankenstein references constructed by cherry-picking isolated words from different jobs and projects.
- **Verification Rule**:
  - When `source_ref` has >= 3 substantive keywords, require that at least 2 key substantive tokens co-occur within the **same paragraph, bullet point, or project block** (bounded by 250 characters or line boundaries), rather than matching across disjoint sections of the resume.

### Layer 4: Interviewer Assertion Clause Grounding (`app/agent/grounding.py`)
- **Objective**: Catch claims embedded in framing phrases like *"you highlighted [X]"*, *"you mentioned [X]"*, *"you achieved [X]"*, *"you designed [X]"*.
- **Patterns**:
  - `\b(?:you\s+(?:highlighted|noted|stated|mentioned|described|built|designed|implemented|optimized|developed|created))\s+([a-zA-Z0-9_\-\.\'\" ]{4,70}?)(?:\.|\?|,|\bto\b|\bby\b|\bwhere\b|\busing\b|\band\b)`
- **Verification Rule**:
  - Extract substantive keywords from the asserted clause.
  - Verify that the asserted technology or action exists in the candidate's dossier within the context of the referenced project or experience.

---

## 3. Data Flow & Turn Lifecycle

1. **Generation**:
   - `InterviewerAgent.execute_turn()` builds messages using sanitized few-shot examples.
   - LLM generates response JSON.
2. **Validation**:
   - `is_source_ref_grounded()` invokes:
     1. `validate_question_assumptions(question, ...)`:
        - Checks for fabricated metrics (`validate_numerical_metrics`).
        - Checks for unsupported assumptions (`in your <phrase>`).
        - Checks for unsupported assertions (`you highlighted <phrase>`).
     2. `validate_source_ref_grounding(source_ref, ...)`:
        - Direct match.
        - Co-occurrence verification against bullet chunks.
3. **Recovery**:
   - If validation fails, `interviewer.py` retries up to 2 times with targeted feedback explaining the exact failed metric or assertion.
   - If both retries fail, invokes `extract_deterministic_fallback_target()`, which extracts a guaranteed real skill/bullet and formats a verified question.

---

## 4. Verification & Testing Strategy

1. **Unit Test: Metric Hallucination Rejection**:
   - Assert that a question asserting `450ms down to 40ms` against Arjun Reddy's resume fails validation with `reason` citing the missing metric.
   - Assert that a question asserting `35% response latency reduction` (which is in Arjun Reddy's resume) passes metric validation.
2. **Unit Test: Cross-Bullet Amalgamation Rejection**:
   - Assert that combining `Kafka` with `latency optimization` from separate jobs fails co-occurrence validation.
3. **Unit Test: Assertion Clause Verification**:
   - Assert that `"you highlighted optimizing an event pipeline with Apache Kafka"` fails if the event pipeline optimization claim is not attached to Kafka in the resume.
4. **End-to-End Regression**:
   - Run `pytest` across all 32 existing tests to guarantee zero regressions.

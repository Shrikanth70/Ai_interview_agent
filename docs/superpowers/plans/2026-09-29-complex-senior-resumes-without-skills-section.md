# Handling Complex Senior Resumes Without a Skills Section Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enhance the interview agent to effectively interview experienced candidates whose resumes lack a dedicated skills section, eliminating template hallucination and focusing inquiries on senior architectural trade-offs.

**Architecture:** Operates via in-context reasoning over the full candidate dossier (NO RAG) with refined LLM system instructions, adaptive skill anchoring from experience bullets, an updated few-shot calibration example, and two-tier code-level grounding verification.

**Tech Stack:** Python 3.10+, FastAPI, Pydantic v2, Pytest, OpenRouter/Mock LLM Client.

---

### Task 1: Create Test Fixture and Comprehensive Test Suite for Skill-Less Senior Resumes

**Files:**
- Create: `tests/test_senior_skill_less_resume.py`

- [ ] **Step 1: Write tests for senior skill-less resume handling**

```python
import pytest
from app.agent.interviewer import InterviewerAgent, InterviewerTurnOutput
from app.agent.grounding import is_source_ref_grounded, extract_deterministic_fallback_target
from app.session.state import SessionState, TranscriptTurn, TurnMeta
from app.llm.client import MockLLMClient

SENIOR_RESUME_WITHOUT_SKILLS = """
Jane Doe
Staff Infrastructure Engineer
Email: jane.doe@example.com | GitHub: janedoe

PROFESSIONAL EXPERIENCE

Principal Systems Architect | Nexus Cloud Systems | 2021 - Present
- Designed and delivered a multi-region distributed consensus layer using Raft and Go, sustaining 45,000 TPS at 99.999% availability.
- Overcame RocksDB write amplification and SST compaction stalls by implementing custom tiered compaction strategies, cutting p99 tail latency from 85ms to 12ms.
- Mentored 14 senior engineers across distributed storage and platform reliability squads.

Senior Staff Software Engineer | DataStream Corp | 2017 - 2021
- Architected real-time stream processing platform leveraging Apache Flink and Kafka, ingesting 2.5 billion daily telemetry events.
- Mitigated partition skew and consumer rebalance storms across 120 broker clusters through key hashing and cooperative sticky assignors.
- Re-architected schema evolution registry with Protocol Buffers, eliminating backward-incompatible deployment outages.

Senior Software Engineer | CoreLogic Systems | 2013 - 2017
- Built high-concurrency microservices in C++ and Python handling distributed transaction coordination across relational databases.
- Tuned Linux kernel TCP buffer configurations and epoll event loops to eliminate socket buffer drops under heavy burst traffic.
"""

def test_deterministic_fallback_on_skill_less_resume():
    """Verify fallback extracts experience bullets when no skills section header exists."""
    target, ref = extract_deterministic_fallback_target(SENIOR_RESUME_WITHOUT_SKILLS)
    assert target is not None
    assert len(target) > 10
    # Must NOT be the fallback generic text
    assert target != "software engineering experience"
    # Grounding check must succeed
    is_grounded, reason = is_source_ref_grounded(
        source_ref=ref,
        source="resume",
        turn_type="resume_claim",
        resume_text=SENIOR_RESUME_WITHOUT_SKILLS,
        github_summary={},
    )
    assert is_grounded, f"Fallback reference '{ref}' failed grounding: {reason}"

def test_fallback_question_architectural_framing():
    """Verify fallback question is phrased with architectural depth for senior engineers."""
    state = SessionState(
        session_id="test-senior-fallback",
        resume_text=SENIOR_RESUME_WITHOUT_SKILLS,
        github_summary={},
    )
    agent = InterviewerAgent(llm_client=MockLLMClient())
    turn_output = agent._generate_deterministic_fallback(state, is_opening=False)
    
    assert "trade-offs" in turn_output.question.lower() or "architecture" in turn_output.question.lower()
    assert "skills section" not in turn_output.question.lower()

@pytest.mark.asyncio
async def test_skill_anchored_turn_anti_hallucination():
    """Verify skill_anchored turn output does not hallucinate 'skills section' on skill-less resumes."""
    mock_response = (
        '{\n'
        '  "question": "In your work at Nexus Cloud Systems, you utilized RocksDB and Raft. At 45,000 TPS, what SST compaction bottlenecks did you encounter, and what alternative state engines did you evaluate?",\n'
        '  "turn_type": "skill_anchored",\n'
        '  "source": "resume",\n'
        '  "source_ref": "RocksDB / Raft consensus layer (Nexus Cloud Systems)",\n'
        '  "reasoning_note": "Probing embedded storage engine trade-offs from senior work experience."\n'
        '}'
    )
    mock_client = MockLLMClient(canned_responses=[mock_response])
    agent = InterviewerAgent(llm_client=mock_client)
    
    state = SessionState(
        session_id="test-senior-session",
        resume_text=SENIOR_RESUME_WITHOUT_SKILLS,
        github_summary={"repos": {"raft-kv": {"description": "Distributed key-value store"}}},
    )
    # Add opening turn to transcript so this is Turn 2
    state.record_interviewer_turn(InterviewerTurnOutput(
        question="Welcome! Tell me about your consensus layer.",
        turn_type="resume_claim",
        source="resume",
        source_ref="Nexus Cloud Systems Raft consensus",
        reasoning_note="Opening turn",
    ))
    
    output = await agent.execute_turn(state, candidate_answer="We encountered severe write stalls under sustained burst traffic.")
    assert "skills section" not in output.question.lower()
    assert "technical skills section" not in output.question.lower()
    assert output.turn_type == "skill_anchored"
    
    is_grounded, reason = is_source_ref_grounded(
        source_ref=output.source_ref,
        source=output.source,
        turn_type=output.turn_type,
        resume_text=state.resume_text,
        github_summary=state.github_summary,
        transcript=state.transcript,
        question=output.question,
    )
    assert is_grounded, f"Grounded check failed: {reason}"
```

- [ ] **Step 2: Run test to verify it passes or flags fallback template difference**

Run: `pytest tests/test_senior_skill_less_resume.py -v`
Expected: `test_fallback_question_architectural_framing` may fail if the fallback question doesn't yet contain the updated architectural trade-off wording.

- [ ] **Step 3: Commit (if auto_commit enabled)**

Check `.agent/config.yml` for `auto_commit` setting.
If `auto_commit: true`:
```bash
git add tests/test_senior_skill_less_resume.py
git commit -m "test: add senior skill-less resume grounding and anti-hallucination tests"
```
If `auto_commit: false`: skip commit and staging. Print: "Skipping commit (auto_commit: false)."

---

### Task 2: Refine Fallback Question Generation in `app/agent/interviewer.py`

**Files:**
- Modify: `app/agent/interviewer.py:128-140`
- Test: `tests/test_senior_skill_less_resume.py`

- [ ] **Step 1: Update `_generate_deterministic_fallback` in `app/agent/interviewer.py`**

In [app/agent/interviewer.py](file:///c:/Users/Bhukya%20Shrikanth/OneDrive/Desktop/Interview-agent/app/agent/interviewer.py), replace lines 133-139 with:
```python
        else:
            question = (
                f"Turning to your experience with {target}: walk me through the system architecture where you applied it "
                f"and the primary operational or scaling trade-offs you navigated."
            )
            turn_type = "skill_anchored" if len(target.split()) <= 4 else "resume_claim"
```

- [ ] **Step 2: Run tests to verify fallback question passes**

Run: `pytest tests/test_senior_skill_less_resume.py -k test_fallback_question_architectural_framing -v`
Expected: PASS

- [ ] **Step 3: Commit (if auto_commit enabled)**

Check `.agent/config.yml` for `auto_commit` setting.
If `auto_commit: true`:
```bash
git add app/agent/interviewer.py
git commit -m "refactor: update fallback question to probe system architecture and trade-offs"
```
If `auto_commit: false`: skip commit and staging. Print: "Skipping commit (auto_commit: false)."

---

### Task 3: Update System Prompt & Few-Shot Calibration in `app/llm/prompts.py`

**Files:**
- Modify: `app/llm/prompts.py:28-36, 90-98`
- Test: `tests/test_senior_skill_less_resume.py`

- [ ] **Step 1: Update `MASTER_SYSTEM_PROMPT` in `app/llm/prompts.py`**

Add senior resume guidelines and adaptive skill anchoring directives to `MASTER_SYSTEM_PROMPT`:
Under `ORDERING & GROUNDING RULES:`, add:
```python
- EXPERIENCED RESUMES & EMBEDDED SKILLS: When evaluating senior/experienced candidates with rich work histories:
  1. If the resume has NO explicit skills section, extract technical competencies, storage engines, protocols, and architectural patterns directly from their work experience bullets.
  2. STRICT NEGATIVE CONSTRAINT: NEVER say "in your skills section", "listed under skills", or "from your technical skills" if the resume lacks a dedicated skills section. Anchor inquiries directly to the project or role where the technology was applied.
  3. SENIORITY & ARCHITECTURAL FOCUS: Focus questions on high-impact architectural and production trade-offs: scaling bottlenecks, failure modes, concurrency/data consistency trade-offs, and alternative designs evaluated. Probe across their full career timeline rather than fixating solely on their most recent role.
```

- [ ] **Step 2: Update Example 4 in `FEW_SHOT_EXAMPLES` in `app/llm/prompts.py`**

Replace Example 4 with an adaptive skill-anchored inquiry demonstrating embedded skill probing without hallucinating a skills section:
```python
    """Turn 4: Adaptive Skill-Anchored Question (Grounded in Work Experience)
{
  "question": "In your work architecting the consensus and storage layer at Acme, you utilized RocksDB and Raft. At 45,000 TPS, what SST compaction or write amplification bottlenecks did you encounter, and what alternative state engines did you evaluate?",
  "turn_type": "skill_anchored",
  "source": "resume",
  "source_ref": "RocksDB / Raft consensus layer (Acme)",
  "reasoning_note": "Extracting an embedded technical skill from experience achievements to probe production scaling trade-offs and alternative evaluations."
}""",
```

- [ ] **Step 3: Run the new test suite**

Run: `pytest tests/test_senior_skill_less_resume.py -v`
Expected: PASS (all 3 tests pass)

- [ ] **Step 4: Commit (if auto_commit enabled)**

Check `.agent/config.yml` for `auto_commit` setting.
If `auto_commit: true`:
```bash
git add app/llm/prompts.py
git commit -m "feat: add senior resume directives and adaptive skill-anchored calibration"
```
If `auto_commit: false`: skip commit and staging. Print: "Skipping commit (auto_commit: false)."

---

### Task 4: Full Regression Verification

**Files:**
- Test: All tests in `tests/`

- [ ] **Step 1: Run the full test suite**

Run: `pytest -v`
Expected: All 25 tests pass with 0 failures.

- [ ] **Step 2: Commit (if auto_commit enabled)**

Check `.agent/config.yml` for `auto_commit` setting.
If `auto_commit: true`:
```bash
git commit --allow-empty -m "chore: verify full test suite passes with senior resume enhancements"
```
If `auto_commit: false`: skip commit and staging. Print: "Skipping commit (auto_commit: false)."

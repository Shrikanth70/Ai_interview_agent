# Break Fallback Deadlock & Strict GitHub Grounding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Break the infinite fallback deadlock loop where Turns 3-6 continuously emitted skills, inject explicit GitHub repository whitelists into context switch nudges, and enforce strict repo matching for `source="github"`.

**Architecture:**
1. Update `calculate_source_nudge` in `app/llm/prompts.py` to accept `github_summary` and list verified repository names in the prompt directive.
2. In `app/agent/grounding.py`, make `source == "github"` validation strictly require an actual repository name from `github_summary["repos"]`, preventing profile text fallthrough.
3. In `app/agent/interviewer.py`, upgrade `_generate_deterministic_fallback` to support GitHub repositories when source rotation mandates a GitHub turn, and prevent consecutive `skill_anchored` fallback questions.

**Tech Stack:** Python 3.10+, FastAPI, Pydantic v2, pytest.

---

### Task 1: Strict GitHub Grounding & Test

**Files to modify:**
- `app/agent/grounding.py`
- `tests/test_grounding.py`

- [ ] **Step 1.1**: Write a failing unit test `test_github_grounding_strictly_requires_repository_match` in `tests/test_grounding.py`:
  - Provide a `github_summary` with repositories `["autotyper", "event-hub"]`.
  - Pass `source="github"`, `source_ref="RAG system GitHub repository"`.
  - Expect `is_source_ref_grounded` to return `False` and an explicit error stating that "RAG system GitHub repository" is not in the candidate's repository list.
- [ ] **Step 1.2**: In `app/agent/grounding.py` (lines 498-504):
  - When `source == "github"`, verify `source_ref` against `repo_names`.
  - If no repository in `repo_names` matches, return `False` immediately without falling through to generic text token matching.
- [ ] **Step 1.3**: Run `pytest tests/test_grounding.py -k test_github_grounding_strictly_requires_repository_match` and confirm it passes.

---

### Task 2: Explicit Repository Whitelist in GitHub Nudges

**Files to modify:**
- `app/llm/prompts.py`
- `app/agent/interviewer.py`
- `tests/test_refinements.py`

- [ ] **Step 2.1**: Update `calculate_source_nudge` signature in `app/llm/prompts.py` to:
  `calculate_source_nudge(transcript, max_consecutive=3, has_github=True, github_summary=None)`
- [ ] **Step 2.2**: When `has_github and github_turns_count == 0 and len(interviewer_turns) >= 2`:
  - Extract repo names and languages from `github_summary.get("repos", {})`.
  - Format them as a clear list in the `MANDATORY GITHUB EXPLORATION MANDATE`.
  - Add explicit negative constraint: `DO NOT target resume projects under source='github' unless they match one of the exact names above.`
- [ ] **Step 2.3**: Update `app/agent/interviewer.py:214` to pass `state.github_summary` to `calculate_source_nudge`.
- [ ] **Step 2.4**: Add a unit test verifying that the GitHub nudge contains the exact repository names.

---

### Task 3: Dual-Source & Anti-Repetition Fallback in `interviewer.py`

**Files to modify:**
- `app/agent/interviewer.py`
- `tests/test_grounding.py`

- [ ] **Step 3.1**: Write a unit test `test_fallback_switches_to_github_when_needed` in `tests/test_grounding.py`:
  - Set up a session with 2 resume turns and 0 GitHub turns, with repositories in `github_summary`.
  - Call `agent._generate_deterministic_fallback(state, is_opening=False)`.
  - Assert that `output.source == "github"` and `output.source_ref` is one of the candidate's GitHub repositories.
- [ ] **Step 3.2**: In `_generate_deterministic_fallback` in `app/agent/interviewer.py`:
  - Check if `has_github` and `github_turns_count == 0` and `len(interviewer_turns) >= 2`:
    - Pick an uncovered repository from `state.github_summary["repos"]`.
    - Generate a question probing its architecture or concurrency:
      `"Turning to your open-source work on GitHub: in your '{repo_name}' repository ({desc}), walk me through the system architecture you built and the primary operational or scaling trade-offs you navigated."`
    - Set `source="github"`, `turn_type="github_project"`, `source_ref=repo_name`.
  - If selecting from resume:
    - If `last_turn_type == "skill_anchored"`, force selection of an experience/project bullet (`turn_type="resume_claim"`) instead of a skill.
- [ ] **Step 3.3**: Run `pytest tests/test_grounding.py -k test_fallback_switches_to_github_when_needed` and confirm it passes.

---

### Task 4: Full Suite & Live Simulation

- [ ] **Step 4.1**: Run `pytest` across all 38+ tests.
- [ ] **Step 4.2**: Run simulation of Turn 3 and Turn 4 with Ollama on `c1add18f-ee34-422c-8b6e-ba5e0182907a` to confirm Turn 3 smoothly pivots to a verified GitHub repo (`autotyper` or `event-hub`) and breaks the deadlock.

# Design Specification: Break Fallback Deadlock & Strict GitHub Grounding

## 1. Overview & Problem Statement

In multi-turn interview sessions (specifically reproduced in session `c1add18f-ee34-422c-8b6e-ba5e0182907a`), the interview system became trapped in an **infinite fallback deadlock loop** from Turn 3 through Turn 6:
- Turn 3: Deterministic fallback on `Python` (`Skills Section: Python`)
- Turn 4: Deterministic fallback on `Java` (`Skills Section: Java`)
- Turn 5: Deterministic fallback on `JavaScript` (`Skills Section: JavaScript`)
- Turn 6: Deterministic fallback on `SQL` (`Skills Section: SQL`)

### Root Causes
1. **Ambiguous GitHub Mandate**: On Turn 3, `calculate_source_nudge` commanded a GitHub pivot, but did not list the actual repositories. When the candidate's resume tagged its own projects with `[GitHub]` (e.g. `RAG Document QA Chatbot [GitHub]`), the model attempted to ask about `RAG Document QA Chatbot` as a GitHub repository.
2. **GitHub-Blind Fallback Mechanism**: When validation failed twice, `_generate_deterministic_fallback` only searched `state.resume_text` and set `source="resume"`. Because the fallback never touched GitHub, `github_turns_count` remained 0, causing `calculate_source_nudge` to issue the exact same mandatory GitHub pivot on every subsequent turn.
3. **No Anti-Repetition in Fallback**: The fallback lacked turn-type memory. Having asked a `skill_anchored` question on Turn 3, it asked three more `skill_anchored` questions in direct succession (Turn 4, 5, 6).
4. **Fuzzy Token Leakage for GitHub Sources**: In [`app/agent/grounding.py`](file:///c:/Users/Bhukya%20Shrikanth/OneDrive/Desktop/Interview-agent/app/agent/grounding.py), turns with `source="github"` that failed repository name matching fell through to generic bag-of-words token matching against the entire profile text, allowing non-existent repositories (e.g., `"RAG system GitHub repository"`) to pass validation if words like `"system"` and `"github"` appeared in the candidate's bio or URL.

---

## 2. Proposed Architecture & Fixes

### Component 1: Explicit Repository Whitelist in GitHub Nudges
- **File**: `app/llm/prompts.py`
- Update `calculate_source_nudge(transcript, max_consecutive=3, has_github=True, github_summary=None)` to accept `github_summary`.
- When emitting `MANDATORY GITHUB EXPLORATION MANDATE`, extract all repository names and languages from `github_summary["repos"]` and format them as an explicit, bulleted list:
  ```
  VERIFIED GITHUB REPOSITORIES (You MUST choose one from this exact list):
  - autotyper (Go)
  - event-hub (Go)
  - distributed-cache (Go)
  STRICT CONSTRAINT: DO NOT invent repository names or target resume projects under source='github' unless they match one of the exact names above.
  ```

### Component 2: Dual-Source Fallback with GitHub Support
- **File**: `app/agent/interviewer.py`
- Enhance `_generate_deterministic_fallback(state, is_opening)`:
  1. Inspect conversation history: if `has_github` is true and `github_turns_count == 0` and `len(interviewer_turns) >= 2`:
     - Select the highest-starred or first uncovered repository from `state.github_summary["repos"]`.
     - Emit a grounded GitHub question:
       ```
       "Turning to your open-source work on GitHub: in your '{repo_name}' repository ({description}), walk me through the system architecture you built and the primary operational or scaling trade-offs you navigated."
       ```
     - Set `source="github"`, `turn_type="github_project"`, `source_ref=repo_name`.
     - This increments `github_turns_count`, satisfies source rotation, and breaks the deadlock.
  2. If selecting from the resume:
     - Check `last_turn_type`. If the previous turn was `skill_anchored`, fallback MUST pick an uncovered experience or project bullet point (`turn_type="resume_claim"`), NEVER two skill questions in a row.

### Component 3: Strict Grounding for `source="github"`
- **File**: `app/agent/grounding.py`
- In `is_source_ref_grounded`:
  - When `source == "github"`, verify that `source_ref` directly matches a real repository name in `github_summary.get("repos", {})` (case-insensitive exact or substring match).
  - Do NOT fall through to generic profile blob token matching. If the reference is not an actual repository from the candidate's GitHub profile, reject it immediately:
    ```
    f"hallucination detected: '{source_ref}' does not match any public repository in candidate's GitHub portfolio ({list(repos.keys())})"
    ```

---

## 3. Verification & Testing

1. **Unit Tests**:
   - `test_github_grounding_rejects_unlisted_repo_despite_profile_words`: Verify that `"RAG system GitHub repository"` is strictly rejected when `source="github"`.
   - `test_fallback_switches_to_github_when_needed`: Verify that `_generate_deterministic_fallback` generates a GitHub repository question when `github_turns_count == 0` after 2 resume turns.
   - `test_fallback_never_asks_consecutive_skill_questions`: Verify that if turn N was `skill_anchored`, fallback on turn N+1 emits a `resume_claim` or `github_project`.
2. **End-to-End Simulation**:
   - Re-run `c1add18f-ee34-422c-8b6e-ba5e0182907a` Turns 3 and 4 with Ollama (`llama3.2:latest`) and verify:
     - Turn 3 cleanly switches to a real GitHub repo from the whitelist.
     - No infinite loop or repetitive skill fallback occurs.
3. **Full Suite**:
   - Run `pytest -v` across all test files.

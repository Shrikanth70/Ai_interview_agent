# Interviewer Hierarchical Memory & Theme Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the interview agent to use a 3-tier hierarchical memory (Static Source, Global Session, and Context Sub-Memories), random Turn 1 theme selection (`PROFILE` vs `JD`), external JEV signal processing (`FOLLOW_UP` vs `SWITCH_CONTEXT`), seamless bridge question transitions, and a 25-minute session budget guardrail.

**Architecture:**
- `app/session/state.py`: Define `ContextSubMemory`, `TurnRecord`, `SessionBudget`, and `OrchestrationState`, refactoring `SessionState` to store isolated sub-memories and a sliding 2–3 turn dialogue window while maintaining backward compatibility with the existing `transcript` and `covered_refs`.
- `app/agent/theme_fetcher.py`: Implement the deterministic `ThemeMemoryFetchTool` to extract scoped context slices (Profile repo/claim vs JD problem scenario) and target rubric dimensions without LLM tool-calling overhead.
- `app/llm/prompts.py`: Add `format_scoped_turn_prompt` and `format_bridge_turn_prompt` to construct compact prompts (~800–1,200 tokens) using only active slices and short-term dialogue.
- `app/agent/interviewer.py`: Update `InterviewerAgent.execute_turn` to accept optional `jev_signal`, handle random Turn 1 theme selection, advance rubric dimensions on follow-ups, synthesize bridge questions on context switches, and enforce the 25-minute closing cutoff.
- `tests/`: Comprehensive test suite verifying scoped prompt assembly, sub-memory isolation, bridge questions, JEV signals, and budget cutoffs.

**Tech Stack:** Python 3.10+, FastAPI, Pydantic v2, pytest, pytest-asyncio.

---

## File Structure

- **Modify**: `app/session/state.py` (Add hierarchical models: `TurnRecord`, `ContextSubMemory`, `SessionBudget`, `OrchestrationState`, and extend `SessionState`).
- **Create**: `app/agent/theme_fetcher.py` (Deterministic scoped context retriever for Profile and JD themes).
- **Modify**: `app/llm/prompts.py` (Add scoped prompt builders and bridge instructions).
- **Modify**: `app/agent/interviewer.py` (Integrate scoped assembly, JEV signal processing, bridge generation, and session timer).
- **Create**: `tests/test_hierarchical_memory.py` (Unit tests for sub-memory models, budget tracking, and state operations).
- **Create**: `tests/test_theme_fetcher.py` (Unit tests for single-context and composite bridge slice retrieval).
- **Create**: `tests/test_interviewer_scoped_turns.py` (Integration tests for JEV signals, bridge transitions, and 25-minute budget cutoff).

---

### Task 1: Hierarchical Memory Data Models in `app/session/state.py`

**Files:**
- Modify: `app/session/state.py`
- Create: `tests/test_hierarchical_memory.py`

- [ ] **Step 1: Write the failing test for hierarchical state models**

Create `tests/test_hierarchical_memory.py`:
```python
from datetime import datetime, timezone
import pytest
from app.session.state import (
    ContextSubMemory,
    InterviewSessionState,
    SessionBudget,
    SessionState,
    TurnRecord,
)

def test_context_sub_memory_lifecycle():
    sub = ContextSubMemory(
        context_id="github:distributed-cache",
        theme="PROFILE",
        source_ref="distributed-cache",
        source_slice={"description": "In-memory cache daemon", "language": "Python"},
        pending_dimensions=["clarity_of_framing", "methodology_depth", "feasibility"],
    )
    assert sub.context_id == "github:distributed-cache"
    assert sub.theme == "PROFILE"
    assert len(sub.pending_dimensions) == 3
    assert len(sub.probed_dimensions) == 0

    # Advance dimension
    sub.record_turn(
        role="interviewer",
        content="Walk me through the core problem of distributed-cache.",
        rubric_dimension="clarity_of_framing",
    )
    assert len(sub.turns) == 1
    assert "clarity_of_framing" in sub.probed_dimensions
    assert sub.pending_dimensions == ["methodology_depth", "feasibility"]

def test_session_state_hierarchical_integration():
    state = SessionState(
        session_id="test-session-123",
        resume_text="Senior Engineer with Redis and Python experience.",
        github_summary={"repos": {"distributed-cache": {"description": "A cache"}}},
    )
    assert state.budget.max_duration_seconds == 1500
    assert state.budget.max_turns == 12
    assert state.active_theme in ["PROFILE", "JD"]
    assert isinstance(state.sub_memories, dict)

    # Adding a candidate answer updates both transcript and recent dialogue window
    state.add_candidate_answer("We used mutex locks with a TTL wheel.")
    assert len(state.transcript) == 1
    assert len(state.recent_dialogue_window) == 1
    assert state.recent_dialogue_window[-1].content == "We used mutex locks with a TTL wheel."

    # Verify sliding window caps at max 3 pairs (6 turns)
    for i in range(10):
        state.add_candidate_answer(f"Answer {i}")
    assert len(state.recent_dialogue_window) <= 6
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_hierarchical_memory.py -v`
Expected: FAIL with `ImportError: cannot import name 'ContextSubMemory' from 'app.session.state'`

- [ ] **Step 3: Implement hierarchical models in `app/session/state.py`**

In `app/session/state.py`, add `TurnRecord`, `ContextSubMemory`, `SessionBudget`, `OrchestrationState`, and extend `SessionState`:
```python
class TurnRecord(BaseModel):
    """A single dialogue turn stored in sub-memory or the short-term sliding window."""
    turn_index: int
    role: Literal["interviewer", "candidate"]
    content: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    theme: Optional[Literal["PROFILE", "JD"]] = None
    context_id: Optional[str] = None
    rubric_dimension: Optional[str] = None

class ContextSubMemory(BaseModel):
    """Domain-scoped memory tracking depth on a single project, resume claim, or JD scenario."""
    context_id: str
    theme: Literal["PROFILE", "JD"]
    source_ref: str
    source_slice: Dict[str, Any] = Field(default_factory=dict)
    probed_dimensions: List[str] = Field(default_factory=list)
    pending_dimensions: List[str] = Field(
        default_factory=lambda: ["clarity_of_framing", "methodology_depth", "feasibility"]
    )
    turns: List[TurnRecord] = Field(default_factory=list)
    extracted_takeaways: Dict[str, str] = Field(default_factory=dict)

    def record_turn(
        self,
        role: Literal["interviewer", "candidate"],
        content: str,
        rubric_dimension: Optional[str] = None,
    ) -> TurnRecord:
        turn = TurnRecord(
            turn_index=len(self.turns) + 1,
            role=role,
            content=content.strip(),
            theme=self.theme,
            context_id=self.context_id,
            rubric_dimension=rubric_dimension,
        )
        self.turns.append(turn)
        if rubric_dimension:
            if rubric_dimension in self.pending_dimensions:
                self.pending_dimensions.remove(rubric_dimension)
            if rubric_dimension not in self.probed_dimensions:
                self.probed_dimensions.append(rubric_dimension)
        return turn

class SessionBudget(BaseModel):
    """Timer and turn limit guardrails for the 25-minute interview."""
    max_duration_seconds: int = 1500  # 25 minutes
    max_turns: int = 12
    start_time: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def elapsed_seconds(self) -> float:
        return (datetime.now(timezone.utc) - self.start_time).total_seconds()

    @property
    def is_closing_time(self) -> bool:
        return self.elapsed_seconds >= 1320  # 22 minutes cutoff

class OrchestrationState(BaseModel):
    """Global coordination state for theme and context transitions."""
    active_theme: Literal["PROFILE", "JD"] = "PROFILE"
    active_context_id: Optional[str] = None
    turns_in_active_context: int = 0
    last_jev_signal: Optional[Literal["FOLLOW_UP", "SWITCH_CONTEXT"]] = None
    theme_switch_pending: bool = False
```

Update `SessionState` to add:
```python
    budget: SessionBudget = Field(default_factory=SessionBudget)
    orchestration: OrchestrationState = Field(default_factory=OrchestrationState)
    sub_memories: Dict[str, ContextSubMemory] = Field(default_factory=dict)
    recent_dialogue_window: List[TurnRecord] = Field(default_factory=list)
    globally_covered_topics: List[str] = Field(default_factory=list)
```
Update `add_candidate_answer` and `add_interviewer_question` to update `recent_dialogue_window` (keeping max 6 items) and active `ContextSubMemory`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_hierarchical_memory.py -v`
Expected: PASS

- [ ] **Step 5: Run existing test suite to ensure zero regression**

Run: `pytest tests/ -v`
Expected: All 44 tests pass.

- [ ] **Step 6: Commit (if auto_commit enabled)**

Check `.agent/config.yml` for `auto_commit` setting.
If `auto_commit: false`: skip commit and staging. Print: "Skipping commit (auto_commit: false)."

---

### Task 2: Implement `ThemeMemoryFetchTool` in `app/agent/theme_fetcher.py`

**Files:**
- Create: `app/agent/theme_fetcher.py`
- Create: `tests/test_theme_fetcher.py`

- [ ] **Step 1: Write the failing test for `ThemeMemoryFetchTool`**

Create `tests/test_theme_fetcher.py`:
```python
import pytest
from app.agent.theme_fetcher import ThemeMemoryFetchTool
from app.session.state import SessionState

def test_fetch_initial_slice_random_or_specified():
    fetcher = ThemeMemoryFetchTool()
    resume_text = "Senior Python Developer with Redis and FastAPI expertise."
    github_summary = {
        "repos": {
            "distributed-cache": {
                "description": "High-concurrency cache daemon",
                "language": "Python",
            }
        }
    }

    # Profile slice fetch
    sub_mem = fetcher.initialize_context(
        theme="PROFILE",
        resume_text=resume_text,
        github_summary=github_summary,
    )
    assert sub_mem.theme == "PROFILE"
    assert sub_mem.context_id.startswith("github:") or sub_mem.context_id.startswith("resume:")
    assert "clarity_of_framing" in sub_mem.pending_dimensions

    # JD slice fetch
    jd_sub = fetcher.initialize_context(
        theme="JD",
        resume_text=resume_text,
        github_summary=github_summary,
        jd_scenarios=[{"scenario_id": "ingestion_buffer", "title": "Real-time Stream Ingestion"}],
    )
    assert jd_sub.theme == "JD"
    assert jd_sub.context_id == "jd:ingestion_buffer"

def test_fetch_bridge_slice():
    fetcher = ThemeMemoryFetchTool()
    state = SessionState(
        session_id="test-session-bridge",
        resume_text="Engineer",
        github_summary={"repos": {"repo-a": {"description": "Repo A"}}},
    )
    # Setup active sub-memory
    active_sub = fetcher.initialize_context("PROFILE", state.resume_text, state.github_summary)
    state.sub_memories[active_sub.context_id] = active_sub
    state.orchestration.active_context_id = active_sub.context_id
    state.orchestration.active_theme = "PROFILE"

    bridge_payload = fetcher.fetch_bridge_context(
        state=state,
        target_theme="JD",
        jd_scenarios=[{"scenario_id": "stream_worker", "title": "Stream Worker"}],
    )
    assert "anchor_slice" in bridge_payload
    assert "target_slice" in bridge_payload
    assert bridge_payload["target_theme"] == "JD"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_theme_fetcher.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.agent.theme_fetcher'`

- [ ] **Step 3: Implement `ThemeMemoryFetchTool` in `app/agent/theme_fetcher.py`**

Create `app/agent/theme_fetcher.py`:
```python
import random
from typing import Any, Dict, List, Literal, Optional, Tuple
from app.session.state import ContextSubMemory, SessionState

DEFAULT_JD_SCENARIOS = [
    {
        "scenario_id": "high_throughput_ingestion",
        "title": "High-Throughput Stream Ingestion",
        "problem_statement": "In this role, we handle massive traffic surges where real-time telemetry must be buffered without dropping data or exhausting memory.",
        "key_trade_offs": ["memory bounds vs. message loss", "synchronous vs. asynchronous commit"],
    },
    {
        "scenario_id": "distributed_caching_and_stampedes",
        "title": "Low-Latency Distributed Caching",
        "problem_statement": "Our backend experiences concurrent cache miss stampedes during flash sales, causing database CPU spikes.",
        "key_trade_offs": ["probabilistic expiration vs. mutex locking", "eventual vs. strong consistency"],
    },
]

class ThemeMemoryFetchTool:
    """Deterministic, zero-latency context selector for Profile and JD themes."""

    def initialize_context(
        self,
        theme: Literal["PROFILE", "JD"],
        resume_text: str,
        github_summary: Dict[str, Any],
        jd_scenarios: Optional[List[Dict[str, Any]]] = None,
        preferred_repo: Optional[str] = None,
    ) -> ContextSubMemory:
        """Initializes a new isolated ContextSubMemory for either PROFILE or JD."""
        if theme == "PROFILE":
            repos = github_summary.get("repos", {}) if isinstance(github_summary, dict) else {}
            if repos:
                repo_name = preferred_repo if preferred_repo in repos else list(repos.keys())[0]
                repo_data = repos[repo_name]
                return ContextSubMemory(
                    context_id=f"github:{repo_name}",
                    theme="PROFILE",
                    source_ref=repo_name,
                    source_slice={
                        "type": "github_repository",
                        "repo_name": repo_name,
                        "description": repo_data.get("description", ""),
                        "language": repo_data.get("language", ""),
                    },
                    pending_dimensions=["clarity_of_framing", "methodology_depth", "feasibility"],
                )
            else:
                return ContextSubMemory(
                    context_id="resume:primary_experience",
                    theme="PROFILE",
                    source_ref="Resume Experience",
                    source_slice={"type": "resume_summary", "text_excerpt": resume_text[:600]},
                    pending_dimensions=["clarity_of_framing", "methodology_depth", "feasibility"],
                )
        else:
            scenarios = jd_scenarios or DEFAULT_JD_SCENARIOS
            chosen = scenarios[0]
            return ContextSubMemory(
                context_id=f"jd:{chosen['scenario_id']}",
                theme="JD",
                source_ref=chosen["title"],
                source_slice=chosen,
                pending_dimensions=["clarity_of_framing", "methodology_depth", "feasibility"],
            )

    def fetch_follow_up_context(self, state: SessionState) -> Dict[str, Any]:
        """Pulls the active sub-memory slice, next rubric dimension, and sliding window."""
        active_id = state.orchestration.active_context_id
        sub = state.sub_memories.get(active_id) if active_id else None
        next_dim = sub.pending_dimensions[0] if sub and sub.pending_dimensions else "methodology_depth"
        return {
            "context_id": active_id,
            "theme": state.orchestration.active_theme,
            "source_slice": sub.source_slice if sub else {},
            "source_ref": sub.source_ref if sub else "General",
            "next_dimension": next_dim,
            "recent_turns": state.recent_dialogue_window[-4:],
            "anti_duplication": state.globally_covered_topics,
        }

    def fetch_bridge_context(
        self,
        state: SessionState,
        target_theme: Literal["PROFILE", "JD"],
        jd_scenarios: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Constructs a composite anchor + target context for seamless bridge transitions."""
        active_id = state.orchestration.active_context_id
        active_sub = state.sub_memories.get(active_id)
        anchor_slice = active_sub.source_slice if active_sub else {}
        target_sub = self.initialize_context(
            theme=target_theme,
            resume_text=state.resume_text,
            github_summary=state.github_summary,
            jd_scenarios=jd_scenarios,
        )
        return {
            "anchor_context_id": active_id,
            "anchor_slice": anchor_slice,
            "anchor_source_ref": active_sub.source_ref if active_sub else "Previous Project",
            "target_context": target_sub,
            "target_theme": target_theme,
            "target_slice": target_sub.source_slice,
            "recent_turns": state.recent_dialogue_window[-4:],
            "anti_duplication": state.globally_covered_topics,
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_theme_fetcher.py -v`
Expected: PASS

- [ ] **Step 5: Commit (if auto_commit enabled)**

Check `.agent/config.yml` for `auto_commit`. If false, skip commit.

---

### Task 3: Scoped Prompt Builders in `app/llm/prompts.py`

**Files:**
- Modify: `app/llm/prompts.py`
- Create: `tests/test_scoped_prompts.py`

- [ ] **Step 1: Write the failing test for scoped prompt formatting**

Create `tests/test_scoped_prompts.py`:
```python
from app.llm.prompts import format_scoped_turn_prompt, format_bridge_turn_prompt

def test_format_scoped_turn_prompt():
    prompt = format_scoped_turn_prompt(
        theme="PROFILE",
        source_ref="distributed-cache",
        source_slice={"description": "Cache daemon"},
        next_dimension="methodology_depth",
        anti_duplication=["Redis TTL"],
    )
    assert "THEME: PROFILE" in prompt
    assert "distributed-cache" in prompt
    assert "methodology_depth" in prompt
    assert "Redis TTL" in prompt

def test_format_bridge_turn_prompt():
    prompt = format_bridge_turn_prompt(
        anchor_ref="distributed-cache",
        anchor_slice={"description": "Cache daemon"},
        target_theme="JD",
        target_ref="High-Throughput Stream Ingestion",
        target_slice={"problem_statement": "Handle surges"},
    )
    assert "BRIDGE TRANSITION MANDATE" in prompt
    assert "distributed-cache" in prompt
    assert "High-Throughput Stream Ingestion" in prompt
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_scoped_prompts.py -v`
Expected: FAIL with `ImportError: cannot import name 'format_scoped_turn_prompt' from 'app.llm.prompts'`

- [ ] **Step 3: Implement scoped prompt formatters in `app/llm/prompts.py`**

Add functions `format_scoped_turn_prompt` and `format_bridge_turn_prompt` to `app/llm/prompts.py`:
```python
def format_scoped_turn_prompt(
    theme: str,
    source_ref: str,
    source_slice: Dict[str, Any],
    next_dimension: str,
    anti_duplication: List[str],
) -> str:
    """Builds a compact (~800 token) instruction focusing strictly on active slice and next dimension."""
    antidup_block = ""
    if anti_duplication:
        antidup_block = f"\nOFF-LIMITS TOPICS (Already covered, do not re-probe): {', '.join(anti_duplication)}\n"

    return (
        f"--- ACTIVE CONTEXT ---\n"
        f"THEME: {theme}\n"
        f"TARGET FOCUS: {source_ref}\n"
        f"SOURCE DETAILS: {source_slice}\n"
        f"TARGET RUBRIC DIMENSION: {next_dimension}\n"
        f"{antidup_block}\n"
        f"INSTRUCTION: Ask a specific, hands-on technical question evaluating the candidate's '{next_dimension}'. "
        f"Probe their concrete decisions, architecture, and trade-offs. Avoid generic definitions."
    )

def format_bridge_turn_prompt(
    anchor_ref: str,
    anchor_slice: Dict[str, Any],
    target_theme: str,
    target_ref: str,
    target_slice: Dict[str, Any],
) -> str:
    """Builds instructions for constructing a smooth bridge question connecting past work to new scenario."""
    return (
        f"--- BRIDGE TRANSITION MANDATE ---\n"
        f"PREVIOUS CONTEXT: {anchor_ref} ({anchor_slice})\n"
        f"UPCOMING THEME: {target_theme} - {target_ref}\n"
        f"UPCOMING SCENARIO: {target_slice}\n\n"
        f"INSTRUCTION: Seamlessly bridge the conversation. Verbally connect the candidate's approach or decisions "
        f"in '{anchor_ref}' to the upcoming scenario in '{target_ref}'. Ask how their experience in the former "
        f"informs their architecture or trade-offs in the latter."
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_scoped_prompts.py -v`
Expected: PASS

- [ ] **Step 5: Commit (if auto_commit enabled)**

Check `.agent/config.yml` for `auto_commit`. If false, skip commit.

---

### Task 4: Interviewer Scoped Turn Execution & JEV Integration in `app/agent/interviewer.py`

**Files:**
- Modify: `app/agent/interviewer.py`
- Create: `tests/test_interviewer_scoped_turns.py`

- [ ] **Step 1: Write integration tests for scoped turn execution, JEV signal, and 25-minute closing cutoff**

Create `tests/test_interviewer_scoped_turns.py`:
```python
import pytest
from app.agent.interviewer import InterviewerAgent
from app.llm.client import MockLLMClient
from app.session.state import SessionState

@pytest.mark.asyncio
async def test_turn_1_initializes_random_theme_and_sub_memory():
    mock_llm = MockLLMClient()
    agent = InterviewerAgent(llm_client=mock_llm)
    state = SessionState(
        session_id="test-hierarchical-turn1",
        resume_text="Experienced engineer with Redis caching and FastAPI systems.",
        github_summary={"repos": {"cache-service": {"description": "A cache service"}}},
    )
    turn = await agent.execute_turn(state)
    assert turn.question
    assert state.orchestration.active_context_id is not None
    assert len(state.sub_memories) == 1
    assert state.orchestration.active_theme in ["PROFILE", "JD"]

@pytest.mark.asyncio
async def test_jev_signal_follow_up_advances_dimension():
    mock_llm = MockLLMClient()
    agent = InterviewerAgent(llm_client=mock_llm)
    state = SessionState(
        session_id="test-jev-followup",
        resume_text="Redis engineer",
        github_summary={"repos": {"cache-service": {"description": "Cache"}}},
    )
    # Turn 1
    await agent.execute_turn(state)
    active_id = state.orchestration.active_context_id
    sub = state.sub_memories[active_id]

    # Candidate answers, JEV says FOLLOW_UP
    turn2 = await agent.execute_turn(
        state=state,
        candidate_answer="We used mutex locks with a TTL wheel.",
        jev_signal="FOLLOW_UP",
    )
    assert turn2.question
    assert state.orchestration.active_context_id == active_id

@pytest.mark.asyncio
async def test_jev_signal_switch_context_triggers_bridge():
    mock_llm = MockLLMClient()
    agent = InterviewerAgent(llm_client=mock_llm)
    state = SessionState(
        session_id="test-jev-switch",
        resume_text="Redis engineer",
        github_summary={"repos": {"cache-service": {"description": "Cache"}}},
    )
    # Turn 1 (starts in PROFILE)
    await agent.execute_turn(state, starting_theme="PROFILE")
    first_context = state.orchestration.active_context_id

    # Candidate answers, JEV says SWITCH_CONTEXT
    turn2 = await agent.execute_turn(
        state=state,
        candidate_answer="That is how we structured eviction.",
        jev_signal="SWITCH_CONTEXT",
    )
    assert turn2.question
    # Active context must have switched to JD
    assert state.orchestration.active_theme == "JD"
    assert state.orchestration.active_context_id != first_context

@pytest.mark.asyncio
async def test_budget_cutoff_forces_closing_turn():
    mock_llm = MockLLMClient()
    agent = InterviewerAgent(llm_client=mock_llm)
    state = SessionState(
        session_id="test-budget-cutoff",
        resume_text="Redis engineer",
        github_summary={"repos": {"cache-service": {"description": "Cache"}}},
    )
    # Simulate turn count near max
    state.turn_count = 11
    turn = await agent.execute_turn(
        state=state,
        candidate_answer="Final wrapup point.",
    )
    assert turn.turn_type == "closing"
    assert state.status == "completed"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_interviewer_scoped_turns.py -v`
Expected: FAIL (method arguments `starting_theme`, `jev_signal` not supported, sub-memories not updated).

- [ ] **Step 3: Update `InterviewerAgent.execute_turn` in `app/agent/interviewer.py`**

1. Import `ThemeMemoryFetchTool` and new prompt formatters.
2. In `execute_turn(self, state: SessionState, candidate_answer: Optional[str] = None, jev_signal: Optional[str] = None, starting_theme: Optional[str] = None)`:
   - Check budget: if `state.budget.is_closing_time` or `state.turn_count >= state.budget.max_turns - 1`, set `is_closing = True`.
   - On Turn 1: if no active context, randomly select theme (`starting_theme` or `random.choice(["PROFILE", "JD"])`), initialize sub-memory via `ThemeMemoryFetchTool`.
   - On subsequent turns:
     - Process candidate answer into active sub-memory and sliding window.
     - Evaluate `jev_signal`:
       - If `"FOLLOW_UP"`: pull active context slice and next rubric dimension.
       - If `"SWITCH_CONTEXT"`: pull bridge context, transition theme pointer, construct bridge prompt.
   - Run LLM with scoped prompt + sliding window.
   - Run Grounding validation layer against active slice and transcript.
   - Record turn in active sub-memory, session transcript, and sliding window.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_interviewer_scoped_turns.py -v`
Expected: PASS

- [ ] **Step 5: Run complete test suite**

Run: `pytest tests/ -v`
Expected: All tests pass (both legacy test suite and new hierarchical memory tests).

- [ ] **Step 6: Commit (if auto_commit enabled)**

Check `.agent/config.yml` for `auto_commit`. If false, skip commit.

---

### Task 5: End-to-End System Verification & Coverage Check

**Files:**
- Test: `tests/test_e2e_hierarchical_interview.py`

- [ ] **Step 1: Write multi-turn E2E simulation test**

Create `tests/test_e2e_hierarchical_interview.py`:
Simulate a complete 8-turn interview session:
- Turn 1: Opening question on Profile.
- Turns 2–3: Follow-up on cache architecture (`FOLLOW_UP`).
- Turn 4: Bridge to JD scenario (`SWITCH_CONTEXT`).
- Turns 5–6: Follow-up on stream ingestion scenario (`FOLLOW_UP`).
- Turn 7: Bridge to second project or resume (`SWITCH_CONTEXT`).
- Turn 8: Closing turn triggered by budget cutoff.
Verify:
- Token efficiency (prompt messages contain only active slice and sliding window).
- No cross-project hallucinations.
- Sub-memories isolate project details correctly.

- [ ] **Step 2: Run E2E test**

Run: `pytest tests/test_e2e_hierarchical_interview.py -v`
Expected: PASS

- [ ] **Step 3: Run full regression test suite**

Run: `pytest -v`
Expected: 100% pass across all test modules.

# Agent Design Specification: Conversational State Machine & Memory Model

## 1. Executive Summary

The **Interviewer Agent** is an autonomous, stateful conversational agent that conducts deep, technical candidate interviews. Instead of chunking documents into vector databases (RAG) and generating disconnected questions, the agent retains the full textual representation of the candidate's resume and public GitHub portfolio directly in context.

The agent's intelligence is governed by:
1. A 5-state Conversational State Machine (`INIT` → `SELECT_FOCUS` → `ASK` → `LISTEN` → `DECIDE_NEXT`).
2. A transparent, inspectable memory model (`session_state`).
3. Dynamic, non-deterministic context switching between resume claims and GitHub project implementations.
4. A strict per-turn structured output schema.

---

## 2. Conversational State Machine

```
   ┌────────────────────────────────────────────────────────┐
   │                         INIT                           │
   │  - Ingest raw resume text & GitHub portfolio summary   │
   │  - Initialize SessionState & CoveredRef registry       │
   └───────────────────────────┬────────────────────────────┘
                               │
                               ▼
   ┌────────────────────────────────────────────────────────┐
   │                     SELECT_FOCUS                       │
   │  - Read covered_refs & past transcript turns           │
   │  - Choose focus target:                                │
   │    * Uncovered resume bullet/claim                     │
   │    * Uncovered GitHub repository/architecture          │
   │    * Skill-anchored probe on claimed skill/keyword     │
   │    * Source-agnostic follow-up probe on last answer    │
   └───────────────────────────┬────────────────────────────┘
                               │
                               ▼
   ┌────────────────────────────────────────────────────────┐
   │                         ASK                            │
   │  - Formulate highly specific question                  │
   │  - Emit structured JSON payload                        │
   │  - Log turn into transcript and append to covered_refs │
   │  - Send question to candidate                          │
   └───────────────────────────┬────────────────────────────┘
                               │
                               ▼ (Candidate submits answer)
   ┌────────────────────────────────────────────────────────┐
   │                        LISTEN                          │
   │  - Ingest verbatim candidate response                  │
   │  - Record candidate turn into transcript               │
   └───────────────────────────┬────────────────────────────┘
                               │
                               ▼
   ┌────────────────────────────────────────────────────────┐
   │                     DECIDE_NEXT                        │
   │  - Evaluate depth, clarity & evidence of last response │
   │  - Follow-up availability is independent of source:    │
   │    dig deeper on GitHub, resume, or skill answers      │
   │  - Answer-driven pivots (no fixed rhythm or cadence):  │
   │    * Vague/shallow answer -> Follow-up probe           │
   │    * Complete answer -> Pivot to different claim/repo  │
   │    * Shared skill/tech name-dropped -> Bridge/pivot    │
   │    * Unannounced switch -> Unpredictable human cadence │
   │  - Soft guardrails: avoid >2 consecutive 1-turn pivots │
   │    and never stay on one source for entire session     │
   │  - Check session turn limits (Closing triggered?)      │
   └───────────────────────────┬────────────────────────────┘
                               │
                               └─────────► loops back to SELECT_FOCUS
```

### Detailed State Specifications

#### State 1: `INIT`
- **Trigger**: `POST /session/start` invoked with resume content and `github_username` or `github_url`.
- **Actions**:
  1. Parse resume text and extract logical sections (experience, projects, skills) without assuming fixed headers.
  2. Query GitHub REST API for public repositories, languages, topics, and README excerpts.
  3. Instantiate a new `SessionState` with empty transcript and `covered_refs`.
  4. Automatically transition to `SELECT_FOCUS` to generate the opening question.
  5. **Ordering Rule (Hard Code Constraint)**: `INIT` always leads to a first question sourced strictly from the resume (`source: "resume"`, either a skill, project bullet, or experience bullet). GitHub-sourced questions are only permissible from turn 2 onward.

#### State 2: `SELECT_FOCUS`
- **Actions**:
  1. Determine the target for the next turn:
     - **Opening turn (Turn 1)**: Must be grounded in the candidate's resume (claim, project, or skill). Opens with a polite welcome note.
     - **Follow-up turn (Turn 2+)**: Symmetrically identify technical ambiguities, trade-offs, or numbers mentioned in candidate's latest response (equally applicable to GitHub, resume, or skill probes based on "key point" criteria).
     - **Skill-anchored turn**: Pick a core skill/keyword from the resume's skills section and challenge the candidate to prove where they've applied it across either resume or GitHub repos.
     - **Context switch turn**: Execute an answer-driven or exploratory pivot across sources (resume ↔ GitHub), either bridging common tech or switching cleanly without forced connections.
  2. Enforce freshness: cross-reference candidates against `covered_refs` to guarantee no duplicate questions on previously explored items.
  3. **Sparse Resume Handling**: For fresher/sparse resumes with limited bullets, the agent leans more heavily on GitHub repos and skill-anchored inquiries or moves toward early closing, preventing hallucinations.

#### State 3: `ASK` & Code-Level Grounding Validation Layer
- **Actions**:
  1. Construct the LLM completion prompt including system rules, few-shot examples, candidate dossier, transcript history, and app-layer nudges.
  2. Call configured LLM client (OpenRouter, Ollama, or Mock) with structured output handling.
  3. **Code-Level Grounding Validation (Anti-Hallucination Guard)**:
     - Extract `source_ref` and `source` from the structured output.
     - **Ordering Verification**: If Turn 1 and `source != "resume"`, reject immediately.
     - **Fuzzy Matching**: Match `source_ref` against the entire raw `resume_text` (if `source == "resume"`) or `github_summary` blob (if `source == "github"`). Matching uses normalized substring/keyword overlap and token sequence matching (tolerant of PDF extraction noise and varied layouts, without hardcoded section headers).
     - **On Validation Failure (Turn Rejected)**:
       - Do not surface the question to the candidate.
       - Log the validation failure with question text, claimed `source_ref`, and reason.
       - Retry LLM generation once with an explicit correction message:
         *"Your previous question referenced '<source_ref>', which does not appear in the provided resume or GitHub data. Generate a new question using ONLY content verifiably present in the source material below."*
     - **On Second Validation Failure**:
       - Do not call the LLM a third time.
       - Fall back to a deterministic, app-layer grounded question (e.g. selecting an extracted skill or bullet from the candidate's actual resume: *"Tell me about your experience with <skill> and where you applied it."*).
  4. Append validated interviewer turn to `transcript` with metadata.
  5. Add `{source, source_ref}` to `covered_refs`.
  6. Return verified question response to client.

#### State 4: `LISTEN`
- **Trigger**: `POST /session/{id}/answer` received with candidate response.
- **Actions**:
  1. Validate session status is `active`.
  2. Reject empty or whitespace-only answers.
  3. Append candidate message to `transcript`:
     ```json
     {"role": "candidate", "content": "..."}
     ```
  4. Transition to `DECIDE_NEXT`.

#### State 5: `DECIDE_NEXT`
- **Actions**:
  1. Reason over the candidate's last answer in conjunction with the interview history:
     - **Symmetrical Follow-Ups**: Follow-up availability is independent of source — do not special-case resume vs github when choosing whether to dig deeper. If the candidate just answered a GitHub question, probe their implementation choices, trade-offs, or stated numbers just as vigorously as a resume answer.
     - **Did the candidate give a vague or evasive answer?** → **Action**: Follow up to challenge the specifics (source-agnostic).
     - **Did the candidate give a crisp, comprehensive technical answer?** → **Action**: Natural pivot point; shift to another project, skill anchor, or cross-switch source.
     - **Did the candidate name-drop a skill/tech appearing in the other source?** → **Action**: Bridge across sources naturally.
     - **Has the topic been adequately explored?** → **Action**: Pivot without requiring a fixed turn count.
     - **Has the session reached the configured limit (e.g., turn 14/15)?** → **Action**: Transition `turn_type` to `closing`.

---

## 3. Memory Model (`session_state`)

The memory model is lightweight, zero-dependency, and human-inspectable. No vector database or hidden embeddings are used.

### Schema Definition (Pydantic / Dataclass)

```python
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class TurnMeta(BaseModel):
    source: Optional[Literal["resume", "github"]] = None
    source_ref: Optional[str] = None
    turn_type: Literal[
        "resume_claim",
        "github_project",
        "skill_anchored",
        "follow_up",
        "context_switch",
        "closing",
    ]
    reasoning_note: Optional[str] = None


class TranscriptTurn(BaseModel):
    role: Literal["interviewer", "candidate"]
    content: str
    turn_index: int
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    meta: Optional[TurnMeta] = None


class CoveredRef(BaseModel):
    source: Literal["resume", "github"]
    ref: str
    turn_index: int
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class SessionState(BaseModel):
    session_id: str
    status: Literal["active", "completed"] = "active"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    # Full source documents
    resume_text: str
    github_summary: Dict[str, Any]  # {repo_name: {description, readme_excerpt, language, topics, stars}}

    # Memory trackers
    covered_refs: List[CoveredRef] = Field(default_factory=list)
    transcript: List[TranscriptTurn] = Field(default_factory=list)

    # Runtime telemetry
    turn_count: int = 0
```

### Invariants Maintained by the Store:
1. `transcript` maintains strict chronological alternation: `[interviewer, candidate, interviewer, candidate, ...]`.
2. Every interviewer turn must have populated `meta` fields.
3. Every non-closing interviewer turn must register a `CoveredRef` in `covered_refs`.
4. `resume_text` and `github_summary` are immutable after session initialization.

---

## 4. Context Switching & Anti-Cheating Logic

The primary goal of the agent's turn sequencing is to **stop cheating and verify authentic technical competence**. A critical weakness of AI interview bots is predictable, mechanical cadence:
- Alternating `resume -> github -> resume -> github`
- Or rigid paired rhythms like `resume + follow-up -> github + follow-up -> skill + follow-up`

When candidates perceive a predictable pattern, they anticipate questions, pre-generate answers using external LLMs, or prepare responses in batches per source. The agent completely eliminates this vulnerability.

### Core Anti-Cheating Principles:

1. **Random, Non-Linear Questioning**:
   - Human technical interviewers do not follow robotic paired sequences.
   - The agent can jump dynamically: `resume -> resume -> github -> skill -> resume -> github`.
   - It may explore 2 different resume claims back-to-back without following up, or jump cold from a resume answer straight into a public GitHub repository.

2. **Follow-Ups Are Gated Strictly on Answer Potential — Never Automatic**:
   - **Do NOT follow up by default**: A follow-up is NOT a mandatory step after every new question.
   - **If the candidate gives a thorough, comprehensive answer**: The answer demonstrates technical competence. Asking an unnecessary follow-up wastes time and creates a predictable rhythm. The agent acknowledges the depth and **immediately pivots** to a different claim, repository, or skill anchor to test if depth holds across their entire profile.
   - **If the candidate gives a vague, evasive, shallow, or buzzword-heavy answer**: The agent triggers a targeted `follow_up` to press on concrete code internals, race conditions, memory bottlenecks, or failure modes.
   - **Symmetrical Follow-Up Capability**: Follow-ups are equally available for resume claims, GitHub repositories, and skill anchors, but always gated on answer quality.

3. **Answer-Driven Pivots & Skill Anchors**:
   - **Cross-Source Skill Bridging**: When an answer references technology also used in their GitHub repos, bridge across organically.
   - **Skill-Anchored Challenge (`skill_anchored`)**: Probe a claimed skill from their resume's skills section out of the blue, challenging them to prove where and how they implemented it in practice.
   - **Soft Guardrails**: Avoid spending the entire interview on one source, and avoid continuous whiplash (flipping sources on every single turn for more than 2 turns in a row).

---

## 5. Structured Per-Turn Output Contract

Every LLM generation for an interviewer turn must conform to the following schema:

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "InterviewerTurnOutput",
  "type": "object",
  "properties": {
    "question": {
      "type": "string",
      "description": "The exact question spoken to the candidate. Realistic, conversational, non-generic, and directly grounded in source material."
    },
    "turn_type": {
      "type": "string",
      "enum": [
        "resume_claim",
        "github_project",
        "skill_anchored",
        "follow_up",
        "context_switch",
        "closing"
      ],
      "description": "Classification of the turn's intent."
    },
    "source": {
      "type": "string",
      "enum": ["resume", "github"],
      "description": "Primary knowledge source grounding this question."
    },
    "source_ref": {
      "type": "string",
      "description": "Human-readable pointer to the exact bullet point, metric, or repo/code artifact being questioned."
    },
    "reasoning_note": {
      "type": "string",
      "description": "Internal 1-line justification explaining why this question, follow-up, or pivot was chosen (for inspection, not shown to candidate)."
    }
  },
  "required": ["question", "turn_type", "source", "source_ref", "reasoning_note"]
}
```

### Turn Type Taxonomy

| `turn_type` | When to Use | Example `source_ref` | Example `question` |
|---|---|---|---|
| `resume_claim` | Introducing a new topic from the candidate's resume experience/projects. | `"45% execution speed improvement at Acme Corp"` | *"On your resume, you noted a 45% increase in execution speed for the data pipeline at Acme. Walk me through the bottlenecks you diagnosed and your specific optimizations."* |
| `github_project` | Introducing a new topic from the candidate's GitHub repos. | `"repo: autotyper / README concurrency section"` | *"I took a look at your autotyper repo on GitHub. In the README, you mentioned handling keystroke delays with Goroutines. How did you handle synchronization and backpressure?"* |
| `skill_anchored` | Probing a keyword from skills section to prove real-world application across sources. | `"Skills: Kafka (proof across resume/repos)"` | *"You have Kafka listed in your core skills. Walk me through where you have actually deployed or operated Kafka clusters — either in your production roles or in one of your personal repositories."* |
| `follow_up` | Probing deeper into candidate's immediate prior answer (works symmetrically on GitHub, resume, or skill turns). | `"prior_answer: Redis buffer trade-off"` | *"You mentioned relying on an in-memory Redis buffer to absorb those traffic spikes. What would happen if Redis experienced a failover during high write throughput?"* |
| `context_switch` | Intentionally pivoting across sources (resume ↔ GitHub), answer-driven or unannounced. | `"repo: distributed-cache (pivot from Acme resume)"` | *"That clarifies the pipeline work. Shifting gears to your GitHub projects: in your distributed-cache repo, you implemented consistent hashing. What made you choose that over rendezvous hashing?"* |
| `closing` | Concluding the interview session gracefully. | `"session_completion"` | *"Thank you for walking me through both your production experience and personal repositories. That covers everything I wanted to dive into today. Do you have any questions for me?"* |

---

## 6. Failure Modes & Edge Case Handling

1. **Candidate provides a one-word or non-responsive answer**:
   - The agent detects low information density and asks a polite but firm clarifying follow-up demanding technical specifics.
2. **Candidate answers with "I don't remember" or "I wasn't involved in that"**:
   - The agent notes the response in `reasoning_note` and pivots to a different claim or project rather than getting stuck.
3. **Candidate claims contradict GitHub README or Resume details**:
   - The agent can politely point out the discrepancy: *"Earlier you mentioned X, but your repository's architecture diagram describes Y. How did that evolve?"*
4. **LLM outputs malformed JSON or markdown codeblocks**:
   - The client strips markdown wrappers (` ```json ... ``` `) and uses a fallback regex extractor before retrying with an explicit JSON-repair instruction.
5. **Model attempts to ask ungrounded or hallucinated question**:
   - Captured deterministically by the Code-Level Grounding Validation layer via fuzzy matching against the raw candidate dossier. Retried once with explicit correction prompt. If validation fails twice, replaced by a deterministic fallback question.
6. **Sparse or fresher resume (limited projects/experience)**:
   - When a resume lacks deep project history, the agent avoids hallucinating details to fill turns; it leans heavily on public GitHub repositories and skill-anchored inquiries or transitions toward early closing.
7. **Messy PDF text extraction (jumbled tables, missing headers)**:
   - Raw text is ingested without fragile structural assumptions. The grounding validation layer matches keywords and sub-phrases across the entire raw document blob rather than relying on brittle section headers.


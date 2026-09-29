# Technical Design Specification: AI Interview Agent Architecture & End-to-End Lifecycle

**Date:** 2026-09-28  
**Author:** AI Pair Programmer & System Architect  
**Status:** Approved by User  
**Target Path:** `docs/superpowers/specs/2026-09-28-interview-agent-working-and-lifecycle-design.md`

---

## 1. Executive Summary & Problem Statement

Existing AI-based interview bots routinely suffer from two fundamental design flaws:
1. **RAG-Induced Fragmentation**: By chopping resumes into 300-word chunks and retrieving them via embedding similarity, RAG bots lose the holistic candidate narrative. They cannot detect career progressions, multi-project architectures, or subtle contradictions across work history. Consequently, their questions regress to generic templates (*"Tell me about a time you used Redis"*).
2. **Fixed-Script Linear Quiz Flow**: Conventional interview tools follow rigid questionnaire trees or alternate rigidly (*1 resume question, 1 GitHub question*). They do not listen to the candidate's actual answers, fail to probe vague claims, and cannot perform spontaneous, human-like context pivots.

The **AI Interview Agent** solves this by maintaining the candidate's entire source context (un-chunked resume text and synthesized GitHub portfolio summaries) directly within modern LLM context windows. It runs an autonomous, 5-state conversational state machine backed by a two-tier code-level grounding validation layer to deliver realistic, rigorous, and fully auditable technical interviews.

---

## 2. Core Architectural Principles & Invariants

### 2.1 NO-RAG / Full Context Window Reasoning
* **No Vector Databases or Chunking**: The architecture strictly forbids Chroma, Pinecone, FAISS, or chunked embedding retrieval.
* **Context Budget**: A cleaned technical resume occupies ~800–2,000 tokens. A summarized GitHub repository portfolio (top 5–10 repos, README excerpts, primary languages, commit activity) occupies ~2,000–4,000 tokens. Modern frontier models (128k+ token context windows) process this data in working memory effortlessly, enabling holistic reasoning across the entire candidate profile.

### 2.2 Strict Non-Generic Questioning & Full Traceability
* Every question emitted must directly probe a concrete metric, architecture decision, or implementation detail.
* Every turn produces structured metadata:
  - `source`: `"resume"` or `"github"`
  - `source_ref`: Concrete pointer to the exact bullet point, metric, or repo name
  - `turn_type`: `"opening"`, `"follow_up"`, `"context_switch"`, `"skill_anchored"`, or `"closing"`
  - `reasoning_note`: Internal rationale explaining why the question or pivot was chosen (for inspection and auditing).

### 2.3 Scope Boundaries (Phase 1 Backend Engine)
* **Backend Only**: Exposed exclusively through typed FastAPI REST endpoints or CLI scripts. No frontend UI in this phase.
* **No Authentication / Multi-Tenancy**: Single-candidate interview testing keyed by `session_id`.
* **In-Memory Session Store**: Fast dictionary storage with thread safety and optional JSON serialization for auditability. No SQL database or ORM dependencies.
* **No Candidate Scoring/Grading**: This phase is focused 100% on the interview conversation dynamics.

---

## 3. Subsystem Architecture & Code Execution Flow

The system comprises five decoupled subsystems running inside FastAPI:

```
                            ┌───────────────────────────────┐
                            │    Client (cURL/CLI/Suite)    │
                            └───────────────┬───────────────┘
                                            │ HTTP REST
                                            ▼
                            ┌───────────────────────────────┐
                            │  FastAPI API (app/api/routes) │
                            └───────┬───────────────┬───────┘
                                    │               │
                 ┌──────────────────┘               └──────────────────┐
                 ▼                                                     ▼
   ┌───────────────────────────┐                         ┌───────────────────────────┐
   │    Ingestion Subsystem    │                         │      Session & State      │
   ├───────────────────────────┤                         ├───────────────────────────┤
   │ - resume_loader.py        │                         │ - state.py (SessionState) │
   │   (Text/PDF clean & slice)│                         │ - store.py (Memory/JSON)  │
   │ - github_loader.py        │                         │ - covered_refs tracker    │
   │   (httpx REST API & repos)│                         │ - transcript history      │
   └─────────────┬─────────────┘                         └─────────────┬─────────────┘
                 │                                                     │
                 └───────────────────────┬─────────────────────────────┘
                                         ▼
                          ┌─────────────────────────────┐
                          │      Core Agent Engine      │
                          │   (app/agent/interviewer)   │
                          ├─────────────────────────────┤
                          │ - 5-State Conversational FSM│
                          │ - GroundingValidator        │
                          │   (app/agent/grounding.py)  │
                          └──────────────┬──────────────┘
                                         │
                                         ▼
                          ┌─────────────────────────────┐
                          │          LLM Layer          │
                          ├─────────────────────────────┤
                          │ - prompts.py (System/Shots) │
                          │ - client.py (LLMClient)     │
                          │   (OpenRouter/Ollama/Mock)  │
                          └─────────────────────────────┘
```

### 3.1 Ingestion Subsystem (`app/ingestion/`)
* **`resume_loader.py`**:
  - Ingests raw text, Markdown, or PDF binary uploads (extracting text via `pdfplumber` or `pypdf`).
  - Cleans whitespace, strips boilerplate headers, and classifies content into logical sections (`experience`, `projects`, `skills`, `education`) without assuming rigid template headings.
* **`github_loader.py`**:
  - Asynchronously queries GitHub's REST API (`https://api.github.com/users/{username}/repos`) using `httpx.AsyncClient`.
  - Filters out external forks unless requested; ranks repos by stars and recency.
  - Summarizes top README excerpts (capped at ~1,000–1,500 words), primary languages, topics, star counts, and last commit dates.

### 3.2 Session & State Management (`app/session/`)
* **`state.py` (`SessionState`)**:
  - Pydantic v2 data model maintaining:
    - `session_id: str`: Unique session UUID.
    - `resume_text: str`: Raw cleaned resume text.
    - `github_summary: dict[str, Any]`: Structured repo summaries and README excerpts.
    - `covered_refs: list[CoveredRef]`: History of claimed bullets/repos already probed to eliminate repetition.
    - `transcript: list[Turn]`: Verbatim candidate and interviewer turn history.
    - `current_state: str`: Active state in the FSM.
    - `turn_count: int`: Current turn index.
* **`store.py` (`InMemorySessionStore`)**:
  - Thread-safe dictionary store keyed by `session_id`.
  - Automatically dumps session transcripts and states to `sessions/{session_id}.json` upon conclusion.

### 3.3 Core Agent Engine (`app/agent/`)
* **`interviewer.py` (`InterviewerEngine`)**:
  - Coordinates conversational transitions across the 5 FSM states.
  - Assembles prompt context: candidate dossier, covered references, verbatim transcript history, and dynamic app-layer nudges.
  - Calls `LLMClient`, passes output through `GroundingValidator`, logs turns immutably, and updates state.
* **`grounding.py` (`GroundingValidator`)**:
  - Two-tier anti-hallucination verification engine validating generated questions against established facts.

### 3.4 LLM & Inference Layer (`app/llm/`)
* **`client.py` (`LLMClient`)**:
  - Abstract interface with implementations: `OpenRouterClient` (Claude 3.5 Sonnet, GPT-4o), `OllamaClient` (local Llama 3.1/3.2), and `MockLLMClient` (deterministic offline testing).
  - Robust JSON extraction, regex repair fallback, and automatic retry on malformed outputs.
* **`prompts.py`**:
  - System prompts defining the senior technical peer interviewer persona, strict non-generic questioning rules, few-shot demonstration anchors, and structured JSON output specifications.

### 3.5 API Layer (`app/api/`)
* **`routes.py`**:
  - `POST /session/start`: Ingests resume + GitHub username, initializes state, returns Turn 1 opening question.
  - `POST /session/{id}/answer`: Receives candidate answer, evaluates response depth, executes next probe or context switch.
  - `GET /session/{id}/transcript`: Returns full transcript with all metadata and covered references.
  - `POST /session/{id}/end`: Gracefully terminates the session and returns an analytical summary of topics covered.
* **`models.py`**: Strict Pydantic v2 request/response schemas.

---

## 4. Conversational State Machine (FSM) Lifecycle

The interview progresses through 5 well-defined states:

```
┌────────────────────────────────────────────────────────┐
│                         INIT                           │
│  - Ingest resume & GitHub profile data                 │
│  - Initialize SessionState & CoveredRef registry       │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────┐
│                     SELECT_FOCUS                       │
│  - Evaluate covered_refs & past transcript turns       │
│  - Choose focus target:                                │
│    * Uncovered resume bullet/claim (Turn 1 constraint) │
│    * Symmetrical follow-up probe on last answer        │
│    * Uncovered GitHub repository / architecture        │
│    * Skill-anchored probe on claimed skill/keyword     │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────┐
│                         ASK                            │
│  - Assemble context prompt & invoke LLM                │
│  - Two-Tier Grounding Validation                       │
│  - Log turn into transcript & append covered_ref       │
│  - Send question payload to candidate                  │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼ (Candidate submits answer)
┌────────────────────────────────────────────────────────┐
│                        LISTEN                          │
│  - Receive verbatim candidate answer                   │
│  - Append candidate turn to transcript                 │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────┐
│                     DECIDE_NEXT                        │
│  - Evaluate depth, technical rigor, and clarity        │
│  - Determine next move (no fixed alternating pattern): │
│    * Vague / shallow answer ──► Follow-up probe        │
│    * Complete / deep answer ──► Dynamic context switch │
│    * Shared technology name-dropped ──► Bridge pivot   │
│  - Soft guardrails: warn if >3 consecutive same source │
│  - Check turn limits (Closing required?)               │
└───────────────────────────┬────────────────────────────┘
                            │
                            └─────────► loops back to SELECT_FOCUS
```

### State Behavior Rules
1. **Turn 1 Hard Constraint**: The opening turn (`turn_number == 1`) MUST be grounded strictly in the candidate's resume (`source: "resume"`), targeting an experience bullet, project, or concrete metric, accompanied by a polite opening welcome. GitHub questions are only permissible from Turn 2 onward.
2. **Freshness & Deduplication**: Every proposed topic is checked against `session_state.covered_refs`. If a bullet or repository was previously probed, the agent must pick an uncovered reference.
3. **Sparse Resume Handling**: If a candidate provides a minimal or student resume with few bullet points, the agent smoothly transitions to GitHub repositories and skill-anchored probes rather than hallucinating experience bullets.
4. **App-Layer Nudging**: The orchestrator injects soft nudges into the prompt:
   - If 3+ consecutive turns probe the resume: *"You have asked 3 consecutive resume questions. Look for a natural pivot to their GitHub repositories on this turn."*
   - If turns reach `max_turns`: *"This is the final turn. Formulate a polite closing question or concluding remark."*

---

## 5. Two-Tier Code-Level Grounding Validation Layer

To eliminate LLM hallucinations and fabricated claims, generated outputs pass through `app/agent/grounding.py` before emission:

```
                 Generated LLM JSON Payload
                             │
                             ▼
 ┌────────────────────────────────────────────────────────┐
 │ Tier 1: Question-Level Assumption Validation           │
 │ (validate_question_assumptions)                        │
 ├────────────────────────────────────────────────────────┤
 │ - Regex scans for contextual clauses:                  │
 │   "in your <phrase>", "for your <system>",             │
 │   "during your <pipeline>"                             │
 │ - Extracts substantive nouns (excluding stopwords)     │
 │ - Checks each noun against the Established Fact Corpus │
 │   (Resume + GitHub READMEs + Candidate Answers)        │
 └───────────────────────────┬────────────────────────────┘
                             │ PASS
                             ▼
 ┌────────────────────────────────────────────────────────┐
 │ Tier 2: Source Reference Verification                  │
 │ (is_source_ref_grounded)                               │
 ├────────────────────────────────────────────────────────┤
 │ - Verifies that metadata tag `source_ref` actually      │
 │   exists in the claimed source                         │
 │ - If source="github", checks repo name / topics        │
 │ - If source="resume", checks token overlap (>0.75      │
 │   difflib similarity) against resume bullet points     │
 └───────────────────────────┬────────────────────────────┘
                             │ PASS
                             ▼
              Question Approved & Emitted
        (If FAIL: Trigger LLM Retry with Grounding Error)
```

### Grounding Failure Handling
When a generated question violates either check (e.g. LLM invents a *"real-time Kafka pipeline"* when the candidate only listed a Redis script):
1. The validator returns `(False, error_reason)`.
2. `interviewer.py` intercepts the error and re-prompts the LLM with an explicit correction directive containing `error_reason`.
3. If retries fail, the system falls back to a deterministic, safely grounded probe drawn directly from an uncovered bullet in `covered_refs`.

---

## 6. Concrete Candidate Lifecycle Case Study

### Candidate Profile: Alex Rivers
* **Role**: Staff Distributed Systems Engineer
* **Resume Content**:
  - Acme Cloud: Led high-throughput Kafka streaming pipeline (100k events/sec).
  - Acme Cloud: Decreased end-to-end event latency by 45% (from 450ms down to 40ms) using custom partitioning logic and ring buffer consumers.
  - Acme Cloud: Designed distributed rate limiter (1.2M requests/min) with Redis cluster and token bucket algorithm.
* **GitHub Repositories**:
  - `raft-kv-go`: Distributed consensus key-value store implementing Raft in Go with log compaction and snapshotting.
  - `SIMD-Vector-Index`: Vector similarity search engine in C++20 with AVX2.

---

### Step-by-Step Turn Trace

#### Turn 1: Initialization & Resume-Grounded Opening
* **HTTP Action**: `POST /session/start` with resume text and GitHub username `alexrivers`.
* **State Transition**: `INIT` → `SELECT_FOCUS` → `ASK`.
* **Interviewer Emitted Question**:
  ```json
  {
    "turn_number": 1,
    "question": "Welcome Alex! Looking at your work at Acme Cloud, you noted reducing end-to-end event latency by 45% down to 40ms using custom partitioning and ring buffer consumers. Walk me through the bottleneck in the previous consumer architecture and how the ring buffer solved it.",
    "turn_type": "opening",
    "source": "resume",
    "source_ref": "Decreased end-to-end event latency by 45% (from 450ms down to 40ms) using custom partitioning logic and ring buffer consumers",
    "reasoning_note": "Opening probe grounded in concrete performance metric from most recent lead role."
  }
  ```
* **State Mutation**: `covered_refs` adds the latency reduction bullet; `turn_count = 1`.

#### Turn 2: Candidate Answer & Symmetrical Technical Follow-Up
* **Candidate Submits Answer**:
  > *"The original pipeline performed synchronous database inserts inside the consumer polling loop, which caused Kafka partition pauses. We replaced it with an in-memory LMAX Disruptor-style ring buffer where worker goroutines asynchronously drain batches and flush them to Cassandra."*
* **State Transition**: `LISTEN` → `DECIDE_NEXT` → `SELECT_FOCUS` → `ASK`.
* **Decision Rationale**: Candidate introduced asynchronous worker goroutines and bulk Cassandra writes. This introduces critical backpressure and data-loss failure modes.
* **Interviewer Emitted Question**:
  ```json
  {
    "turn_number": 2,
    "question": "When Cassandra write latency spikes and worker goroutines fall behind incoming 100k events/sec bursts, what backpressure strategy prevents that in-memory ring buffer from exhausting memory or dropping uncommitted offsets?",
    "turn_type": "follow_up",
    "source": "resume",
    "source_ref": "Architected high-throughput Kafka streaming pipeline processing 100k events/sec",
    "reasoning_note": "Candidate introduced asynchronous Cassandra batching; probing backpressure boundary conditions."
  }
  ```
* **State Mutation**: `covered_refs` tracks Kafka throughput bullet; `turn_count = 2`.

#### Turn 3: Answer-Driven Dynamic Context Switch to GitHub
* **Candidate Submits Answer**:
  > *"We configured a threshold watermark at 80% ring capacity. When exceeded, the consumer group coordinator pauses partition fetching via consumer.Pause() until the buffer drains below 40%, ensuring zero data loss and strictly bounded heap memory."*
* **State Transition**: `LISTEN` → `DECIDE_NEXT` → `SELECT_FOCUS` → `ASK`.
* **Decision Rationale**: The candidate gave a complete, precise answer. Having spent two consecutive turns on resume stream processing, the agent executes an answer-driven context switch to the candidate's GitHub portfolio.
* **Interviewer Emitted Question**:
  ```json
  {
    "turn_number": 3,
    "question": "That handles consumer backpressure cleanly. Pivoting over to your public GitHub profile, in your 'raft-kv-go' repository, you implemented Raft consensus from scratch. In your log compaction implementation, how do you handle incoming AppendEntries RPCs while an asynchronous snapshot is actively streaming to disk?",
    "turn_type": "context_switch",
    "source": "github",
    "source_ref": "raft-kv-go",
    "reasoning_note": "Pivoting from resume stream processing to GitHub consensus project log compaction details."
  }
  ```
* **State Mutation**: `covered_refs` tracks `raft-kv-go`; `turn_count = 3`.

#### Turn 4: GitHub Follow-Up / Core Skill Probe
* Probes Raft log index truncation race conditions or bridges to C++ SIMD vector search.

#### Turn 5: Session Termination & Auditability
* **HTTP Action**: `POST /session/{id}/end`.
* Session state transitions to `CLOSED`. Transcript is written to `sessions/{id}.json`.
* Summary report reflects:
  - Total Turns: 5
  - Resume References Probed: 2
  - GitHub Repositories Probed: 1
  - Follow-up Depth: 2 deep technical probes
  - Duplicate Questions: 0

---

## 7. Verification & Testing Matrix

The codebase enforces reliability through comprehensive automated tests in `tests/`:

| Test Suite | Target Module | Verification Objective |
|---|---|---|
| `test_resume_loader.py` | `app/ingestion/resume_loader.py` | Validates text and PDF ingestion, sectioning, and whitespace cleaning. |
| `test_github_loader.py` | `app/ingestion/github_loader.py` | Validates async GitHub REST queries, fork filtering, and README truncation. |
| `test_grounding.py` | `app/agent/grounding.py` | Tests Tier 1 assumption validation (catches fabricated context) and Tier 2 source ref verification. |
| `test_state_machine.py` | `app/agent/interviewer.py` | Validates Turn 1 resume constraint, dynamic context switching, and covered_refs tracking. |
| `test_api_routes.py` | `app/api/routes.py` | Validates FastAPI request/response contracts, 400/404/422 status codes, and transcript outputs. |

---

## 8. Summary of Non-Goals & Future Phases

| Dimension | Phase 1 (Current Engine) | Future Phase |
|---|---|---|
| **Interface** | FastAPI REST Endpoints / CLI | Web UI (React/Next.js) |
| **Authentication** | Tokenless Session IDs | Multi-Tenant JWT / OAuth |
| **Persistence** | In-Memory + JSON Dump | PostgreSQL / Supabase |
| **Evaluation** | Conversational Interaction | Candidate Rubric & Scoring Engine |
| **Media** | Pure Text In / Text Out | Live Real-Time Speech (WebRTC/TTS) |

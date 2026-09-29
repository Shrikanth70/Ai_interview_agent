# Architecture Specification: AI Interview Agent

## 1. System Overview

The **AI Interview Agent** is a backend service providing a stateful, conversational technical interviewer. Unlike RAG-based interview bots that retrieve isolated resume snippets to ask generic questions, this system keeps full source context (un-chunked resume text and parsed GitHub repository summaries) directly within the LLM context window.

The agent reasons across both sources, conducts follow-up probes based on the candidate's actual answers, and dynamically switches context between resume claims and GitHub project implementations.

```
                              ┌────────────────────────────────────────┐
                              │            Client / Consumer           │
                              │       (curl / Postman / Test Suite)    │
                              └───────────────────┬────────────────────┘
                                                  │ HTTP REST
                                                  ▼
                              ┌────────────────────────────────────────┐
                              │          FastAPI App Entrypoint        │
                              │           (app/main.py, routes)        │
                              └───────────────────┬────────────────────┘
                                                  │
                 ┌────────────────────────────────┴───────────────────────────────┐
                 │                                                                │
                 ▼                                                                ▼
   ┌───────────────────────────┐                                    ┌───────────────────────────┐
   │    Ingestion Subsystem    │                                    │      Session & State      │
   ├───────────────────────────┤                                    ├───────────────────────────┤
   │ - resume_loader.py        │                                    │ - SessionState model      │
   │   (txt, md, pdf parsing)  │                                    │ - InMemory / JSON Store   │
   │ - github_loader.py        │                                    │ - covered_refs tracker    │
   │   (repos, READMEs, langs) │                                    │ - transcript history      │
   └─────────────┬─────────────┘                                    └─────────────┬─────────────┘
                 │                                                                │
                 │ Ingested Sources (Resume + GitHub)                             │ State & History
                 └───────────────────────────────┬────────────────────────────────┘
                                                 │
                                                 ▼
                                  ┌─────────────────────────────┐
                                  │      Agent Core Engine      │
                                  │   (app/agent/interviewer.py)│
                                  ├─────────────────────────────┤
                                  │ - Conversational FSM        │
                                  │ - Symmetrical Follow-Ups    │
                                  │ - Answer-Driven Pivots      │
                                  │ - Skill-Anchored Inquiries  │
                                  └──────────────┬──────────────┘
                                                 │
                                                 ▼
                                  ┌─────────────────────────────┐
                                  │         LLM Layer           │
                                  ├─────────────────────────────┤
                                  │ - prompts.py (system/shots) │
                                  │ - client.py (LLMClient)     │
                                  │   (OpenRouter & Ollama)     │
                                  │ - Robust JSON Repair/Retry  │
                                  └──────────────┬──────────────┘
                                                 │
                        ┌────────────────────────┴────────────────────────┐
                        │ HTTPS                                           │ HTTP
                        ▼                                                 ▼
         ┌─────────────────────────────┐                   ┌─────────────────────────────┐
         │      OpenRouter API         │                   │      Ollama Local API       │
         │ (Claude 3.5 Sonnet / GPT-4o)│                   │   (llama3.1 / llama3.2)     │
         └─────────────────────────────┘                   └─────────────────────────────┘
```

---

## 2. Directory Layout

The application strictly follows this structure:

```
interview-agent/
├── app/
│   ├── __init__.py
│   ├── main.py                     # FastAPI application factory & lifespan
│   ├── config.py                   # Pydantic BaseSettings for env vars
│   ├── agent/
│   │   ├── __init__.py
│   │   └── interviewer.py          # State machine, prompt assembler, turn execution
│   ├── api/
│   │   ├── __init__.py
│   │   ├── models.py               # Pydantic request/response schemas
│   │   └── routes.py               # /session/start, /answer, /transcript, /end
│   ├── ingestion/
│   │   ├── __init__.py
│   │   ├── resume_loader.py        # Text & PDF extraction, cleaning, sectioning
│   │   └── github_loader.py        # Public repo & README extraction via GitHub API
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── client.py               # Unified LLMClient abstraction & JSON repair/retry engine
│   │   ├── openrouter_client.py    # OpenRouter compatibility export
│   │   ├── ollama_client.py        # Ollama local client implementation
│   │   └── prompts.py              # System prompt, few-shots, context builders
│   └── session/
│       ├── __init__.py
│       ├── state.py                # SessionState, Turn, CoveredRef models
│       └── store.py                # Thread-safe in-memory session repository
├── docs/
│   ├── ARCHITECTURE.md             # This document
│   ├── AGENT_DESIGN.md             # Conversational state machine & memory model
│   ├── PROMPTING_GUIDE.md          # System prompts, few-shot examples, reasoning rules
│   ├── API_CONTRACT.md             # HTTP endpoints, schemas, error formats
│   └── SETUP.md                    # Environment setup, execution, curl testing
├── tests/
│   ├── __init__.py
│   ├── test_ingestion.py           # Unit tests for resume and GitHub loaders
│   ├── test_session_store.py       # Unit tests for session persistence
│   └── test_e2e_interview.py       # Multi-turn interview E2E integration test
├── .env.example
├── .gitignore
├── AGENTS.md                       # Standing instructions for agentic pair programmers
├── requirements.txt
└── README.md
```

---

## 3. Module Responsibilities

### 3.1 `app.config`
- Loads environment configurations using `pydantic-settings`.
- Key settings: `LLM_PROVIDER` (`openrouter` | `ollama`, default `openrouter`), `OPENROUTER_API_KEY`, `OPENROUTER_MODEL` (default: `anthropic/claude-3.5-sonnet`), `OPENROUTER_BASE_URL`, `OLLAMA_BASE_URL` (default: `http://localhost:11434`), `OLLAMA_MODEL` (default: `llama3.1`), `GITHUB_TOKEN` (optional for higher rate limits), `MAX_SESSION_TURNS` (default: 15), `LOG_LEVEL`.

### 3.2 `app.ingestion`
- **`resume_loader.py`**:
  - Ingests plain text (`.txt`, `.md`) or binary PDF documents (`pdfplumber` / `pypdf`).
  - Cleans excess whitespace and normalizes headers.
  - Generates a lightweight section outline (experience, projects, skills, education) while preserving the full text for LLM context.
  - Can be executed directly via CLI (`python -m app.ingestion.resume_loader path/to/resume.pdf`) for validation.
- **`github_loader.py`**:
  - Ingests public repositories for a given GitHub username or parsed from a GitHub profile URL using `httpx` (async).
  - Fetches top repositories sorted by update date/stars (excluding forks by default unless primary).
  - For each repo, extracts metadata (name, description, stars, primary language, topics) and fetches the top ~1000 words of the `README.md`.
  - Can be executed directly via CLI (`python -m app.ingestion.github_loader <username>`).

### 3.3 `app.session`
- **`state.py`**:
  - Pure Pydantic / dataclass definitions representing:
    - `SessionState`: unique `session_id`, `created_at`, `status` (`active`, `completed`), `resume_text`, `github_summary`, `covered_refs`, `transcript`, `llm_provider`, `model_name`.
    - `TranscriptTurn`: role (`interviewer`, `candidate`), `content`, `turn_index`, `meta` (`source`, `source_ref`, `turn_type`, `reasoning_note`).
    - `CoveredRef`: source (`resume`, `github`), reference descriptor, turn number.
- **`store.py`**:
  - `SessionStore` protocol and an `InMemorySessionStore` implementation.
  - Provides thread-safe async access (`get`, `save`, `list`, `delete`).
  - Supports optional serialization to a local `./sessions/` directory for debugging.

### 3.4 `app.llm`
- **`client.py` & provider clients**:
  - Provider-agnostic interface (`LLMClient`) supporting both OpenRouter (cloud) and Ollama (local) chat completion backends.
  - Enforces identical structured output contract across providers: `{question, turn_type, source, source_ref, reasoning_note}`.
  - Shared JSON-repair/retry fallback: strips markdown fences, attempts outermost brace recovery, and retries once with stricter "return ONLY valid JSON" instructions when parsing local model outputs.
- **`prompts.py`**:
  - Houses the system prompt template, behavioral constraints, and few-shot calibration examples.
  - Dynamic prompt assembly: candidate dossier, conversation history, covered references, and soft guidance nudges (anti-whiplash and anti-monologue).

### 3.5 `app.agent`
- **`interviewer.py`**:
  - The central coordinator that executes the conversational state machine:
    1. Checks session turn count and covered topics.
    2. Enforces **Turn 1 Resume Ordering Rule**: Opening question is strictly sourced from resume claims or skills (`source: "resume"`).
    3. Builds the context window with the system prompt, dossier, transcripts, and soft nudges.
    4. Manages symmetrical follow-ups: evaluates last answer depth based on "key point" criteria regardless of whether last turn was resume, GitHub, or skill-anchored.
    5. Avoids mechanical checklist hopping by encouraging deep 1-2 turn probing on candidate trade-offs.
    6. Calls configured LLM provider via `LLMClient`.
    7. Executes two-tier grounding validation via `grounding.py`.
    8. Appends verified turns to `session_state.transcript` and registers explored items in `covered_refs`.
- **`grounding.py`**:
  - Code-level anti-hallucination verification engine:
    1. **Question Assumption Validation (`validate_question_assumptions`)**: Scans `question` text for contextual claims (e.g. `in your <pipeline/system>`) and verifies them against established dossier facts and prior answers, rejecting fabricated architectures.
    2. **Source Reference Validation (`is_source_ref_grounded`)**:
       - Word-boundary token checking (`is_token_in_text`) with lookaround assertions `(?<![a-zA-Z0-9_])tok(?![a-zA-Z0-9_])` preventing substring false positives (e.g., `"go"` matching inside `"mongodb"` or `"algorithms"`).
       - Strict follow-up transcript isolation: when `turn_type == "follow_up"` or `source_ref` starts with `prior_answer:`, requires keywords to be present in what the candidate actually stated in prior answers.
       - Fuzzy and sequence matching for multi-token source references across raw documents.
    3. **Deterministic Fallback Generator (`extract_deterministic_fallback_target`)**: When LLM grounding fails twice, extracts a guaranteed-grounded skill or bullet from raw resume text while respecting `covered_refs`.

### 3.6 `app.api`
- **`models.py`**:
  - Request/response schemas for `/session/start`, `/session/{id}/answer`, `/session/{id}/transcript`, `/session/{id}/end`.
- **`routes.py`**:
  - HTTP handlers translating REST requests into agent operations, mapping validation errors to clean HTTP error statuses.
- **`main.py`**:
  - FastAPI app initialization, CORS middleware, error handlers, and lifecycle hooks.

---

## 4. End-to-End Data Flow

### 4.1 Session Initialization Flow (`POST /session/start`)
```
Client
  │  POST /session/start {resume_text/file, github_username | github_url, llm_provider?}
  ▼
FastAPI Route (routes.py)
  │
  ├── 1. Ingestion:
  │      - resume_loader.load_resume(input) -> clean resume_text
  │      - github_loader.fetch_profile(username_or_parsed_url) -> github_summary dict
  │
  ├── 2. Session Creation:
  │      - Create SessionState(session_id=uuid4(), resume_text, github_summary, provider, model)
  │
  ├── 3. Agent First Turn (interviewer.py):
  │      - Assemble initial prompt (State = INIT -> SELECT_FOCUS -> ASK)
  │      - Enforce Ordering Rule: source must be "resume"
  │      - Call LLMClient (OpenRouter or Ollama)
  │      - Two-Tier Validation (grounding.py):
  │        * Tier 1: validate_question_assumptions (no fabricated context)
  │        * Tier 2: is_source_ref_grounded with word-boundary lookarounds
  │        * If ungrounded -> Retry once with correction prompt
  │        * If 2nd failure -> Deterministic fallback question
  │      - Append turn to transcript; record source_ref in covered_refs
  │      - session_store.save(state)
  │
  ▼
Client receives:
  { session_id, turn_index: 1, question, source: "resume", source_ref, turn_type }
```

### 4.2 Candidate Answer Flow (`POST /session/{id}/answer`)
```
Client
  │  POST /session/{id}/answer { answer: "We used Redis streams..." }
  ▼
FastAPI Route (routes.py)
  │
  ├── 1. Fetch SessionState from store
  │      - Reject if status != "active" or not found
  │
  ├── 2. Append candidate answer to state.transcript (State = LISTEN)
  │
  ├── 3. Agent Next Turn (interviewer.py) (State = DECIDE_NEXT -> SELECT_FOCUS -> ASK):
  │      - Evaluate turn count & covered_refs distribution
  │      - If consecutive turns on same source >= 3, inject soft pivot nudge
  │      - If turn_count >= MAX_SESSION_TURNS - 1, nudge towards wrap-up / closing
  │      - Call OpenRouterClient with full transcript + source dossier
  │      - Parse structured output
  │      - Append interviewer question to state.transcript
  │      - Record in covered_refs
  │      - session_store.save(state)
  │
  ▼
Client receives:
  { turn_index, question, source, source_ref, turn_type, reasoning_note }
```

### 4.3 Transcript & Status Inspection (`GET /session/{id}/transcript`)
Returns the complete verbatim record of all interviewer questions, candidate answers, and the metadata tracking every source reference investigated.

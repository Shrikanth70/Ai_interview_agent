# 01. System Architecture & Module Linkages

[← Back to Wiki Index](file:///c:/Users/Bhukya%20Shrikanth/OneDrive/Desktop/Interview-agent/wiki/INDEX.md)

---

## 🏛️ Architecture Overview

The **AI Interview Agent** backend is structured as an autonomous, state-machine driven conversational service. It conducts technical interviews grounded in a candidate's resume, public GitHub portfolio, and job criteria without vector databases or chunked RAG.

### Architectural Philosophy
1. **Context Window Reasoning**: The candidate's full profile and JD scenarios comfortably fit in modern LLM context windows. We use Python dictionary scoping rather than semantic embeddings.
2. **Deterministic Scoped Assembly**: Instead of passing all data on every turn, the agent pulls only the active project or scenario, reducing prompt size from ~5,000+ tokens to ~800–1,200 tokens.
3. **Decoupled Evaluator Handshake**: Depth decisions (`FOLLOW_UP` vs. `SWITCH_CONTEXT`) are consumed from an external evaluation module (`jev`), keeping the interviewer lean and focused on conversational excellence.

---

## 📦 Module Dependency & Call Graph

```mermaid
flowchart TD
    MAIN["app/main.py<br/>(FastAPI Application Entry)"] --> ROUTES["app/api/routes.py<br/>(REST Endpoints: /start, /answer)"]
    MAIN --> CONFIG["app/config.py<br/>(Pydantic Settings & Env Vars)"]
    
    ROUTES --> INGEST_RES["app/ingestion/resume_loader.py<br/>(Resume Ingestion & Cleanup)"]
    ROUTES --> INGEST_GH["app/ingestion/github_loader.py<br/>(GitHub API Scraper)"]
    ROUTES --> STORE["app/session/store.py<br/>(InMemorySessionStore)"]
    
    STORE --> STATE["app/session/state.py<br/>(SessionState, ContextSubMemory, SessionBudget)"]
    
    ROUTES --> AGENT["app/agent/interviewer.py<br/>(InterviewerAgent State Machine)"]
    
    AGENT --> FETCHER["app/agent/theme_fetcher.py<br/>(ThemeMemoryFetchTool)"]
    AGENT --> PROMPTS["app/llm/prompts.py<br/>(Prompt Builder & Calibration Shots)"]
    AGENT --> LLM["app/llm/client.py<br/>(OpenRouter / Ollama / Mock Client)"]
    AGENT --> GROUND["app/agent/grounding.py<br/>(2-Tier Anti-Hallucination Guard)"]

    GROUND -.->|"Validates Assumptions"| STATE
    FETCHER -.->|"Pulls Active Slice"| STATE
```

---

## 📂 Codebase Directory Topology

| Directory | Core Responsibility | Key Files |
| :--- | :--- | :--- |
| [`app/api/`](file:///c:/Users/Bhukya%20Shrikanth/OneDrive/Desktop/Interview-agent/app/api) | FastAPI route handlers, Pydantic request/response schemas, error handling | [`routes.py`](file:///c:/Users/Bhukya%20Shrikanth/OneDrive/Desktop/Interview-agent/app/api/routes.py), [`schemas.py`](file:///c:/Users/Bhukya%20Shrikanth/OneDrive/Desktop/Interview-agent/app/api/schemas.py) |
| [`app/session/`](file:///c:/Users/Bhukya%20Shrikanth/OneDrive/Desktop/Interview-agent/app/session) | Stateful interview representations: 3-tier memory model, budget timers, in-memory registry | [`state.py`](file:///c:/Users/Bhukya%20Shrikanth/OneDrive/Desktop/Interview-agent/app/session/state.py), [`store.py`](file:///c:/Users/Bhukya%20Shrikanth/OneDrive/Desktop/Interview-agent/app/session/store.py) |
| [`app/agent/`](file:///c:/Users/Bhukya%20Shrikanth/OneDrive/Desktop/Interview-agent/app/agent) | Core state machine coordinator, theme memory routing, and code-level grounding layer | [`interviewer.py`](file:///c:/Users/Bhukya%20Shrikanth/OneDrive/Desktop/Interview-agent/app/agent/interviewer.py), [`theme_fetcher.py`](file:///c:/Users/Bhukya%20Shrikanth/OneDrive/Desktop/Interview-agent/app/agent/theme_fetcher.py), [`grounding.py`](file:///c:/Users/Bhukya%20Shrikanth/OneDrive/Desktop/Interview-agent/app/agent/grounding.py) |
| [`app/llm/`](file:///c:/Users/Bhukya%20Shrikanth/OneDrive/Desktop/Interview-agent/app/llm) | Outbound LLM HTTP clients, system prompts, few-shot calibration, and bridge formatters | [`client.py`](file:///c:/Users/Bhukya%20Shrikanth/OneDrive/Desktop/Interview-agent/app/llm/client.py), [`prompts.py`](file:///c:/Users/Bhukya%20Shrikanth/OneDrive/Desktop/Interview-agent/app/llm/prompts.py) |
| [`app/ingestion/`](file:///c:/Users/Bhukya%20Shrikanth/OneDrive/Desktop/Interview-agent/app/ingestion) | Parsing raw resume text/PDF and pulling GitHub public repositories via REST API | [`resume_loader.py`](file:///c:/Users/Bhukya%20Shrikanth/OneDrive/Desktop/Interview-agent/app/ingestion/resume_loader.py), [`github_loader.py`](file:///c:/Users/Bhukya%20Shrikanth/OneDrive/Desktop/Interview-agent/app/ingestion/github_loader.py) |
| [`tests/`](file:///c:/Users/Bhukya%20Shrikanth/OneDrive/Desktop/Interview-agent/tests) | Unit, integration, grounding, and E2E simulation test suites | [`test_e2e_hierarchical_interview.py`](file:///c:/Users/Bhukya%20Shrikanth/OneDrive/Desktop/Interview-agent/tests/test_e2e_hierarchical_interview.py) |

---

## 🔄 End-to-End Data Flow

```mermaid
sequenceDiagram
    autonumber
    actor Client
    participant Routes as app/api/routes.py
    participant Ingestion as Ingestion Loaders
    participant Store as app/session/store.py
    participant State as app/session/state.py
    participant Agent as app/agent/interviewer.py
    participant Fetcher as app/agent/theme_fetcher.py
    participant LLM as app/llm/client.py
    participant Grounding as app/agent/grounding.py

    Note over Client,Routes: Step 1: Initialize Interview
    Client->>Routes: POST /session/start (Resume + GitHub URL)
    Routes->>Ingestion: Parse Resume & Fetch GitHub Repos
    Ingestion-->>Routes: Cleaned Text & Repo Summaries
    Routes->>Store: Create SessionState
    Store->>State: Initialize State & SessionBudget (25m)
    Routes->>Agent: execute_turn(state, starting_theme=None)
    Agent->>Fetcher: initialize_context(random: PROFILE or JD)
    Fetcher-->>Agent: Sub-Memory & First Slice
    Agent->>LLM: generate_turn(scoped_prompt)
    LLM-->>Agent: Draft Question JSON
    Agent->>Grounding: is_source_ref_grounded() + validate_assumptions()
    Grounding-->>Agent: Approved Turn
    Agent->>State: Record Turn & update SubMemory
    Agent-->>Routes: Turn Output JSON
    Routes-->>Client: 200 OK (Opening Question)

    Note over Client,Routes: Step 2: Answer & Follow-up Cycle
    Client->>Routes: POST /session/{id}/answer (Candidate Answer)
    Routes->>Store: Get SessionState
    Routes->>Agent: execute_turn(state, answer, jev_signal)
    Agent->>State: add_candidate_answer(answer) -> update sliding window
    alt JEV Signal == FOLLOW_UP
        Agent->>Fetcher: fetch_follow_up_context(state)
        Fetcher-->>Agent: Active Slice + Next Rubric Dimension
    else JEV Signal == SWITCH_CONTEXT
        Agent->>Fetcher: fetch_bridge_context(state, target_theme)
        Fetcher-->>Agent: Composite Anchor + Target Scenario
    end
    Agent->>LLM: generate_turn(scoped_messages)
    LLM-->>Agent: Next Question Draft
    Agent->>Grounding: Validate Grounding against source/transcript
    Grounding-->>Agent: Validated Question
    Agent->>State: Record Turn & advance dimension
    Agent-->>Routes: Question Output
    Routes-->>Client: 200 OK (Next Question)
```

---

[Next: 02. Memory & State Graph →](file:///c:/Users/Bhukya%20Shrikanth/OneDrive/Desktop/Interview-agent/wiki/02_MEMORY_AND_STATE_GRAPH.md)

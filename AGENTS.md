# Standing Instructions for AI Coding Agents (AGENTS.md)

## 1. Project Mission & Identity

You are working on the **AI Interview Agent** backend. The goal of this system is to conduct realistic, rigorous, non-generic technical interviews grounded directly in a candidate's resume and public GitHub profile, powered by the OpenRouter API.

---

## 2. Core Architectural Philosophy: NO RAG, NO VECTOR DB

- **Strict Constraint**: Do **NOT** introduce embeddings, vector databases (Chroma, Pinecone, FAISS, etc.), or chunked retrieval.
- **Context Window Reasoning**: The candidate's full resume text and summarized GitHub repositories fit comfortably in modern LLM context windows (a few thousand tokens). The agent reasons across the full source context simultaneously.
- **Traceability**: Every question emitted MUST be tagged with its source (`resume` or `github`), a specific `source_ref` describing the exact claim or repo being probed, and a `reasoning_note`.

---

## 3. Scope Boundaries: What NOT To Do

1. **NO Frontend**: Do not build React, Vue, HTML/CSS, or any graphical user interface. Interaction is solely through FastAPI REST endpoints or CLI scripts.
2. **NO Authentication / User Accounts**: No JWTs, passwords, multi-tenant databases, or login routes in this phase.
3. **NO Database Engine**: Use the in-memory session store (with optional flat JSON dump for inspectability). No PostgreSQL, SQLite, or ORM dependencies.
4. **NO Scoring / Grading Engine**: This phase is exclusively about generating the **interview conversation** itself, not scoring or deciding hire/no-hire.

---

## 4. Coding Conventions & Stack

- **Language & Framework**: Python 3.10+ with FastAPI.
- **Type Annotations**: Strict typing everywhere. Use `typing` / built-in generics (`str`, `dict[str, Any]`, `list[str]`, `Optional`, `Literal`).
- **Data Validation & Schemas**: Use **Pydantic v2** (`BaseModel`, `Field`) for all API requests/responses, internal session state, and LLM structured outputs.
- **HTTP Client**: Use `httpx` (async) for outbound calls (OpenRouter API and GitHub API).
- **Error Handling**: Raise explicit `HTTPException` with meaningful error messages for 400, 404, 409, and 502 status codes.
- **Docstrings & Clean Code**: Every public function and class must have clear docstrings explaining arguments and invariants.

---

## 5. Where to Look First

Before modifying or extending any part of the codebase, consult the canonical documentation in `/docs`:
- **State Machine, Memory & Context Switching**: Read [docs/AGENT_DESIGN.md](file:///c:/Users/Bhukya%20Shrikanth/OneDrive/Desktop/Interview-agent/docs/AGENT_DESIGN.md)
- **Folder Layout & Module Boundaries**: Read [docs/ARCHITECTURE.md](file:///c:/Users/Bhukya%20Shrikanth/OneDrive/Desktop/Interview-agent/docs/ARCHITECTURE.md)
- **System Prompts & Few-Shot Anchors**: Read [docs/PROMPTING_GUIDE.md](file:///c:/Users/Bhukya%20Shrikanth/OneDrive/Desktop/Interview-agent/docs/PROMPTING_GUIDE.md)
- **API Request/Response Schemas**: Read [docs/API_CONTRACT.md](file:///c:/Users/Bhukya%20Shrikanth/OneDrive/Desktop/Interview-agent/docs/API_CONTRACT.md)
- **Local Setup & Testing**: Read [docs/SETUP.md](file:///c:/Users/Bhukya%20Shrikanth/OneDrive/Desktop/Interview-agent/docs/SETUP.md)

---

## 6. Testing Requirements

- Ingestion loaders (`resume_loader.py` and `github_loader.py`) must be runnable standalone (`python -m ...`) and emit valid JSON.
- Unit and integration tests in `tests/` must verify:
  1. Questions are non-generic and contain verifiable `source_ref`.
  2. Follow-ups probe the candidate's actual prior answers.
  3. Dynamic context switching (resume ↔ GitHub) occurs at non-fixed intervals.
  4. Covered references are properly tracked and never duplicated.

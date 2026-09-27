# AI Technical Interview Agent (Resume + GitHub Aware)

An autonomous, stateful backend service that conducts deep, realistic technical interviews. Grounded directly in a candidate's resume and public GitHub profile, powered by the OpenRouter API.

Unlike traditional RAG systems that chunk text into embeddings and retrieve disconnected snippets to ask generic questions, this system keeps the full source documents in context, tracks conversational depth, asks probing follow-ups, and performs natural context switches.

---

## Key Features

- **Grounded in Full Source Context**: No RAG or vector database. The entire cleaned resume and summarized GitHub repositories (languages, stars, topics, README excerpts) are maintained in the LLM's context.
- **Strictly Non-Generic Questions**: Every question probes an exact metric, architecture, or codebase detail.
- **Conversational State Machine**: Implements `INIT` → `SELECT_FOCUS` → `ASK` → `LISTEN` → `DECIDE_NEXT`.
- **Dynamic Context Switching**: Non-fixed cadence between resume claims and GitHub project implementations.
- **Multi-Turn Memory & Auditability**: Tracks covered references (`covered_refs`) and provides full transcripts with reasoning notes on every turn.
- **FastAPI Backend**: Clean, typed REST endpoints with Pydantic v2 schemas and validation.

---

## Documentation

Full architectural specifications and guides are located in `/docs`:

1. [Architecture & Folder Structure](docs/ARCHITECTURE.md)
2. [Conversational State Machine & Memory Model](docs/AGENT_DESIGN.md)
3. [Prompting Guide & Few-Shot Calibration](docs/PROMPTING_GUIDE.md)
4. [API Contract & Schema Specification](docs/API_CONTRACT.md)
5. [Local Setup & cURL Walkthrough](docs/SETUP.md)
6. [Coding Agent Instructions](AGENTS.md)

---

## Quickstart

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure Environment
```bash
cp .env.example .env
# Edit .env and supply your OPENROUTER_API_KEY
```

### 3. Run FastAPI Server
```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000 --http h11 --reload
```
Interactive API docs are available at `http://127.0.0.1:8000/docs`.

### 4. Run Streamlit Test Frontend
```bash
streamlit run streamlit_app.py
```
Interactive test UI opens at `http://localhost:8501`.

### 5. Run Test Suite
```bash
pytest -v
```

---

## API Endpoints

- `POST /session/start` — Ingest resume & GitHub profile, start session, emit opening question.
- `POST /session/{id}/answer` — Submit candidate answer, receive next question or follow-up.
- `GET /session/{id}/transcript` — Retrieve full conversation transcript and covered references.
- `POST /session/{id}/end` — Conclude interview session and view analytical summary.

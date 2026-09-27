# Local Setup & End-to-End Testing Guide

## 1. Prerequisites

- **Python 3.10+** (Python 3.11 or 3.12 recommended)
- **LLM Provider** (choose either or both):
  - **OpenRouter (Cloud)**: API key from [openrouter.ai](https://openrouter.ai/keys)
  - **Ollama (Local)**: Installed and running locally from [ollama.ai](https://ollama.ai) (e.g. `llama3.1` or `llama3.2`)
- **Optional**: GitHub Personal Access Token (for higher rate limits against GitHub API: 5,000 req/hr vs 60 unauthenticated)

---

## 2. Environment Variables

Create a `.env` file in the project root by copying `.env.example`:

```bash
cp .env.example .env
```

| Variable | Required | Default | Description |
|---|---|---|---|
| `LLM_PROVIDER` | No | `openrouter` | Default LLM provider: `openrouter` (cloud) or `ollama` (local) |
| `OPENROUTER_API_KEY` | If using OpenRouter | `None` | Your OpenRouter secret key (`sk-or-v1-...`) |
| `OPENROUTER_MODEL` | No | `anthropic/claude-3.5-sonnet` | Model on OpenRouter (e.g. `anthropic/claude-3.5-sonnet`, `openai/gpt-4o`) |
| `OPENROUTER_BASE_URL` | No | `https://openrouter.ai/api/v1` | OpenRouter API base URL |
| `OLLAMA_BASE_URL` | No | `http://localhost:11434` | Ollama service base URL |
| `OLLAMA_MODEL` | No | `llama3.1` | Local model name (e.g. `llama3.1`, `llama3.2:latest`, `mistral`) |
| `GITHUB_TOKEN` | No | `None` | Optional GitHub PAT for authenticated requests |
| `MAX_SESSION_TURNS` | No | `15` | Turn limit before triggering graceful session closure |
| `LOG_LEVEL` | No | `INFO` | Application log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |

---

## 3. Ollama Setup (Local LLM Path)

If you prefer to run locally with zero API costs:

```bash
# 1. Start Ollama daemon (if not already running as a background service)
ollama serve

# 2. Pull a structured-output capable model (e.g., Llama 3.1 or Llama 3.2)
ollama pull llama3.1

# 3. In your .env, set:
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.1
```

The system automatically cleans markdown fences and runs a repair retry if a local model's structured JSON output requires formatting adjustments.

---

## 4. Installation & Running

### 4.1 Create Virtual Environment & Install Dependencies

```bash
# Create virtual environment
python -m venv venv

# Activate on Linux/macOS:
source venv/bin/activate

# Or activate on Windows (PowerShell):
.\venv\Scripts\Activate.ps1

# Install requirements
pip install -r requirements.txt
```

### 4.2 Run FastAPI Server

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000 --http h11 --reload
```

Server interactive Swagger documentation is available at:
- **Interactive UI**: `http://127.0.0.1:8000/docs`
- **ReDoc**: `http://127.0.0.1:8000/redoc`

### 4.3 Run Streamlit Test Frontend

In a separate terminal:
```bash
streamlit run streamlit_app.py
```
This launches the interactive test UI in your browser at `http://localhost:8501`.

---

## 5. Standalone Ingestion Testing

Both the resume loader and GitHub loader can be tested independently without starting the web server.

### 5.1 Testing Resume Ingestion
```bash
# Test with a text file:
python -m app.ingestion.resume_loader path/to/sample_resume.txt

# Test with a PDF file:
python -m app.ingestion.resume_loader path/to/sample_resume.pdf
```
This prints the cleaned extracted text and identified section breakdown as JSON.

### 5.2 Testing GitHub Profile Ingestion
```bash
# Test fetching a public profile by username:
python -m app.ingestion.github_loader octocat
```
This outputs a structured JSON summary of public repositories, languages, stars, and README excerpts.

---

## 6. End-to-End Testing via cURL

### Step 1: Start a New Session (`POST /session/start`)

#### Option A: Using `github_username` (OpenRouter Cloud)
```bash
curl -X POST http://127.0.0.1:8000/session/start \
  -H "Content-Type: application/json" \
  -d '{
    "github_username": "octocat",
    "resume_text": "Alex Rivers\nSenior Distributed Systems Engineer\nAcme Corp (2022-Present)\n- Architected high-throughput Kafka streaming pipeline processing 100k events/sec with 99.99% uptime.\n- Decreased end-to-end event latency by 45% (from 450ms to 40ms) using custom partitioning logic.\nProjects:\n- raft-kv: Built a distributed key-value store implementing the Raft consensus algorithm from scratch in Go."
  }'
```

#### Option B: Using `github_url` (Ollama Local)
```bash
curl -X POST http://127.0.0.1:8000/session/start \
  -H "Content-Type: application/json" \
  -d '{
    "github_url": "https://github.com/octocat",
    "resume_file_path": "sample_resume.txt",
    "llm_provider": "ollama",
    "model_name": "llama3.1"
  }'
```

**Save the returned `session_id`** from the response (e.g., `d3b07384-d113-4632-9c9e-1f744e4b5239`).

---

### Step 2: Submit an Answer & Receive Follow-Up (`POST /session/{id}/answer`)

```bash
curl -X POST http://127.0.0.1:8000/session/d3b07384-d113-4632-9c9e-1f744e4b5239/answer \
  -H "Content-Type: application/json" \
  -d '{
    "answer": "The 45% latency drop was achieved by removing synchronous MySQL writes from the hot path. We partitioned events into 12 Kafka topics keyed by customer_id and used in-memory ring buffers in our Go worker pool."
  }'
```

The response will contain the interviewer's next turn (e.g., challenging the in-memory ring buffer sizing, memory limits, or consumer backpressure). Follow-ups work symmetrically whether the prior turn was on Resume, GitHub, or a Skill anchor.

---

### Step 3: Check Live Interview Transcript (`GET /session/{id}/transcript`)

```bash
curl -X GET http://127.0.0.1:8000/session/d3b07384-d113-4632-9c9e-1f744e4b5239/transcript
```

Returns:
- Full conversation history with roles (`interviewer` and `candidate`).
- Metadata for each interviewer question (`turn_type`, `source`, `source_ref`, `reasoning_note`).
- `covered_refs` list showing all topics touched so far.

---

### Step 4: Conclude Interview (`POST /session/{id}/end`)

```bash
curl -X POST http://127.0.0.1:8000/session/d3b07384-d113-4632-9c9e-1f744e4b5239/end
```

Returns:
- Session status changed to `completed`.
- Analytical breakdown of resume questions, GitHub questions, skill-anchored questions, follow-ups, and context switches.

---

## 7. Known Limitations & Scope

1. **Non-English & Mixed-Language Resumes**:
   - The ingestion subsystem processes UTF-8 raw text without crashing or corrupting character streams.
   - However, system prompts, few-shot anchors, and regex heuristic extractors are calibrated primarily for English technical resumes.
   - Non-English text is passed verbatim to the LLM; while multilingual LLMs may conduct parts of the interview in the detected language, English resumes provide optimal grounding and validation accuracy.

2. **Sparse or Fresher Resumes**:
   - For candidates with minimal resume text (e.g. only 1-2 school projects and no work experience), the interviewer avoids hallucinating corporate achievements. It will emphasize public GitHub repositories and skill-anchored challenges, or conclude the session within fewer turns.

3. **No Database Engine (In-Memory Scope)**:
   - Sessions are held in-memory (with optional flat JSON persistence). Restarting the process resets in-memory session states unless dumps are reloaded.


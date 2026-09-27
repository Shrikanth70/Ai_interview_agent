

## 1. Project Structure

This is a monorepo for a candidate-assessment platform.

- `frontend`: Next.js 16.2.2 App Router application using React 19, TypeScript, Tailwind CSS, Base UI, and Vitest.
- `backend`: FastAPI application using Pydantic, Supabase, JWT authentication, LangChain, and background grading workers.
  - `routers/`: HTTP API endpoints
  - `services/`: GitHub ingestion, grading, reports, profile processing, retrieval
  - `agent/`: LangChain agent, tools, sandboxing, chat orchestration
  - `db`: Pydantic models, tenant scoping, database helpers
  - `tests/`: Backend tests
- `proxy`: OpenAI-compatible OpenRouter proxy with JWT validation, usage metering, transcript capture, streaming, and provider resilience.
- `cohort-similarity`: Standalone repository/text similarity pipeline with tokenization and embeddings.
- `source-adapters`: Bulk source-data ingestion utilities.
- `assessments`: Assessment JSON definitions and data packs.
- `problems`: Problem and rubric configurations.
- `cohort-persona-configs`: Persona-specific assessment configuration.
- `grading-integration-configs`: Grading integration configuration.
- `report-dimension-configs`: Report scoring/dimension configuration.
- `tech-pre-grading-configs`: Technical pre-assessment grading configuration.
- `templates`: Candidate starter repositories and assessment templates.
- `supabase`, `migrations`: Database migration and Supabase-related files.
- `docs`, `specs`, `openwiki`: Documentation, specifications, and generated repository evidence.
- `deploy`, `.github`: Deployment scripts and CI/CD workflows.
- `tools`: Auxiliary tools, including a usage dashboard.
- `e2e`: Repository-level end-to-end assets.

The primary runtime architecture is:

```text
Next.js frontend
        |
        v
FastAPI backend
        |
        +-- Supabase/Postgres and Storage
        +-- OpenRouter through LangChain/OpenAI-compatible APIs
        +-- GitHub REST API and optional git clone
        +-- Background grading and report-generation workers
```

## 2. Resume-Related Logic

### Resume-specific processing

A dedicated resume parser, resume generator, or resume optimizer is **not present**.

There is no resume-specific schema, interface, extraction prompt, or resume output format.

### Generic document/file handling

The codebase does support generic uploaded-file and document workflows:

- `tools.py`
  - Reads and summarizes CSV files.
  - Generates or edits Markdown, text, and HTML documents through LLM calls.
  - Uses sandboxed generated Python for CSV transformations.
- `grading_artefacts.py`
  - Extracts text from PDFs using `pdfplumber`.
  - Reads the first eight pages.
  - Returns capped text, up to approximately 500,000 characters.
- `pdfplumber` is declared in the backend dependencies.
- No `python-docx`-based resume parser or resume document generator was found in production source.

### Data schema

No resume data model exists. The closest related structures are general session uploads and assessment data:

- `models.py`: `UploadedFileOut`, `SessionState`, and other API models.
- `memory_store.py`: in-memory upload/session representations.

## 3. GitHub API Usage

GitHub integration is present and substantial.

### Profile and repository metadata

`platform_fetcher.py` uses `httpx.AsyncClient` against:

- `https://api.github.com/users/{login}`
- `https://api.github.com/users/{login}/repos`

It returns normalized data including:

- Login and display name
- Bio
- Public repository count
- Follower count
- Recent repositories
- Repository descriptions
- Stars
- Primary language

Authentication uses a bearer token from `GITHUB_TOKEN`, `GITHUB_PAT`, or configured settings.

### Repository contents

`repo_reader.py` supports:

- GitHub URL parsing
- Branch extraction from `/tree/{branch}` and `/blob/{branch}` URLs
- Repository metadata
- Contents/tree/blob retrieval
- README retrieval
- Commit-log retrieval
- Base64 decoding of GitHub file contents
- Source-file filtering
- `.env`, binary, generated-file, and vendored-directory exclusion

It uses bounded retry with exponential backoff for transient `httpx` failures.

### Clone-based access

`repo_access.py` provides:

- Clone-first repository access
- Sparse checkout
- REST fallback when cloning fails
- Per-grade caching
- Concurrency limits
- Clone timeouts
- Cleanup of temporary worktrees

No specialized GitHub SDK was found. The implementation primarily uses `httpx` and the git command-line tool.

## 4. LLM API Integration Patterns

### Provider and SDK

The main provider is OpenRouter through its OpenAI-compatible API.

The main chat agent uses:

- LangChain
- LangGraph-style `create_agent`
- `langchain-openai.ChatOpenAI`

See `executor.py`.

OpenRouter is configured through:

- `OPENROUTER_API_KEY`
- `OPENROUTER_BASE_URL`
- Configured model names
- Temperature and token limits

### Chat calls

The assessment chat path is:

```text
POST /sessions/{session_id}/chat
        |
        v
backend/routers/chat.py
        |
        v
backend/agent/chat_runner.py
        |
        v
LangChain agent / ChatOpenAI
        |
        v
SSE events
```

`chat_runner.py` emits structured events for:

- Text tokens
- Tool execution started/completed
- Generated files
- Errors
- Completion

The system prompt is assembled from assessment context, enabled skills/tools, uploaded files, and persisted conversation information.

### Streaming

Streaming is used for interactive chat:

- Backend returns `text/event-stream` using FastAPI `StreamingResponse`.
- Frontend consumes the response with a `ReadableStream`.
- Events are encoded as `data: {...}\n\n`.

Relevant files:

- `chat.py`
- `chat_runner.py`
- `sse.ts`

The proxy also forwards upstream OpenRouter streaming responses and includes handling for stalled or incomplete streams.

### Non-streaming calls

Several services use direct, non-streaming OpenRouter calls through `httpx`, including:

- Code-generation calls in `tools.py`
- Grading nodes
- Report generation
- Transcript summarization
- Cohort insights

These calls generally use a `messages` array with optional `system` and `user` messages.

### Conversation and memory

Conversation state is persisted through the `DataStore` abstraction:

- `deps.py`: store interface/dependency
- `supabase_store.py`: production persistence
- `memory_store.py`: test/local persistence

Session state includes `chat_history`, prompt counts, uploaded files, and completed client turns.

The frontend sends a `client_turn_id`, allowing retries to be deduplicated. `ChatPanel.tsx` preserves messages locally while streaming and retries failed turns with the same identifier.

Langfuse callbacks are supported through `callbacks.py`.

## 5. Backend/API Layer Conventions

The API framework is FastAPI.

### Endpoint structure

Typical endpoints:

- Use `APIRouter`
- Define async handlers
- Accept Pydantic request models
- Return Pydantic response models where applicable
- Obtain persistence through `Depends(get_store)`
- Raise `HTTPException` with explicit status codes and details
- Keep blocking work off the event loop with `asyncio.to_thread`

Example files:

- `auth.py`
- `chat.py`
- `sessions.py`

### Request and response schemas

Schemas are centralized in `models.py`, using Pydantic types such as:

- `LoginRequest`
- `LoginResponse`
- `SessionState`
- `ChatRequest`
- `UploadedFileOut`
- Assessment and dashboard response models

### Authentication

Authentication uses:

- JWTs signed with an application secret
- HTTP-only `access_token` cookies
- Optional bearer-token extraction
- bcrypt password verification
- Public-route allowlisting
- Role and tenant checks

Relevant files:

- `auth.py`
- `auth_utils.py`
- `deps.py`

Tenant context is applied per request. Admin and organization access are enforced through dependencies and role helpers.

## 6. Frontend Patterns

### Stack

The frontend uses:

- Next.js 16.2.2
- React 19
- TypeScript
- App Router
- Tailwind CSS
- Base UI
- `lucide-react`
- `react-markdown`
- Vitest and React Testing Library
- Playwright for E2E tests

### State management

No Redux, Zustand, or other global state library was found.

State is handled through:

- Component-level `useState`
- `useEffect`
- `useRef`
- `useCallback`
- `useSyncExternalStore` for the persisted workspace splitter state
- Local storage for session-specific UI layout preferences

API contracts and fetch helpers are centralized in `api.ts`.

### Chat UI

The main chat interface is `ChatPanel.tsx`.

It supports:

- Local message state
- Persisted initial chat history
- Streaming token accumulation
- Tool activity groups
- Generated-file events
- Abort/cancellation through `AbortController`
- Retry of failed turns
- Prompt-cap enforcement
- Scroll pinning
- Markdown rendering

The surrounding assessment workspace is implemented in [`frontend/app/workspace/[sessionId]/page.tsx`](frontend/app/workspace/[sessionId]/page.tsx).

## 7. Environment and Configuration

Secrets are environment-driven and are not intended to be committed.

The repository contains:

- Root `.env.example`
- A root `.env` file in the current workspace
- Backend Pydantic settings
- Separate proxy settings

Backend configuration is defined in `config.py` using `pydantic-settings`. It loads the repository-root `.env` and optionally `backend/.env`.

Important configuration categories include:

- `SUPABASE_URL`
- `SUPABASE_SERVICE_KEY`
- `JWT_SECRET`
- `OPENROUTER_API_KEY`
- `OPENROUTER_BASE_URL`
- Agent, grader, and embedding model names
- GitHub token settings
- CORS origins
- Langfuse credentials
- Repository clone limits and timeouts
- Grading concurrency and retry settings

The proxy has its own validation in `config.py`, including required proxy JWT and OpenRouter settings.

Frontend configuration uses public, non-secret values such as:

- `NEXT_PUBLIC_API_URL`
- Supabase public URL/anonymous key where applicable

Secrets are not placed in `NEXT_PUBLIC_*` variables.

## 8. Reusable Utilities

### Text extraction

- PDF text extraction with `pdfplumber` in `grading_artefacts.py`
- Plain text, Markdown, CSV, JSON, XML, and other text-like content decoding in the same module
- Repository text filtering and normalization in `repo_reader.py`
- Source-code token normalization in `tokenize_norm.py`

### Chunking and retrieval

- `RecursiveCharacterTextSplitter` is used for code/document chunking.
- `retrieval.py` implements:
  - Tokenization
  - BM25 retrieval
  - Regex retrieval
  - Reciprocal-rank fusion
  - Retrieval budgets and traces

### Embeddings

- `embeddings.py` uses LangChain `OpenAIEmbeddings` against the OpenRouter-compatible endpoint.
- Inputs are truncated and batched.
- The backend has embedding model fallback and cooldown behavior.

### Retry and resilience

Existing retry patterns include:

- GitHub REST transient retries in `repo_reader.py`
- Grading invocation retries in the grading nodes
- Artifact-fetch retries in `grading_artefacts.py`
- Exponential backoff for background grading
- OpenRouter proxy stream-stall retries and provider cooldowns in `main.py` and `upstream.py`

### Rate limiting and concurrency

There is no general-purpose inbound API rate limiter.

There are targeted controls:

- LeetCode concurrency semaphore in `platform_fetcher.py`
- Embedding cooldown registry
- Repository clone concurrency limits
- Grading concurrency limits
- Proxy/provider cooldowns

### PDF/DOCX

- PDF text extraction is present.
- A dedicated resume PDF parser is not present.
- A dedicated DOCX resume parser or generator is not present.
- Generic document generation/editing exists, but it is not resume-aware.
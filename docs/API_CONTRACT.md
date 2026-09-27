# API Contract Specification

## 1. Overview

The AI Interview Agent exposes a RESTful HTTP API over JSON. All endpoints are hosted under the FastAPI backend server.

### Base URL
```
http://127.0.0.1:8000
```

### Common Headers
- `Content-Type: application/json`
- `Accept: application/json`

---

## 2. Endpoints Summary

| Method | Path | Summary | Description |
|---|---|---|---|
| `POST` | `/session/start` | Start Interview | Ingests resume & GitHub profile, initializes state, and generates the opening question. |
| `POST` | `/session/{session_id}/answer` | Submit Answer | Submits candidate's answer and generates the next interviewer turn (follow-up or pivot). |
| `GET` | `/session/{session_id}/transcript` | Get Transcript | Returns full conversation transcript, covered references, and telemetry. |
| `POST` | `/session/{session_id}/end` | End Interview | Concludes the interview session, records completion timestamp, and returns a summary. |

---

## 3. Endpoint Details

### 3.1 `POST /session/start`

Initiates a new interview session. Ingests the candidate's resume and GitHub profile (via username or full URL), establishes the memory state, and triggers the first interviewer question.

#### Request Body
```json
{
  "resume_text": "Experienced software engineer with 5 years in distributed systems at Uber...",
  "github_username": "octocat",
  "github_url": null,
  "resume_file_path": null,
  "llm_provider": "openrouter",
  "model_name": "anthropic/claude-3.5-sonnet"
}
```
*Notes on input fields:*
- **Resume**: Either `resume_text` or a server-accessible `resume_file_path` (e.g. `.txt`, `.md`, or `.pdf`) must be provided.
- **GitHub**: Exactly one of `github_username` (e.g. `"octocat"`) OR `github_url` (e.g. `"https://github.com/octocat"`) must be provided. Trailing slashes are supported.
- **LLM Provider** (optional): `"openrouter"` (cloud) or `"ollama"` (local). Defaults to server environment configuration.

#### Response Body (`201 Created`)
```json
{
  "session_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "status": "active",
  "turn_index": 1,
  "turn": {
    "question": "Welcome! Looking over your experience at Uber, you mention architecting a Kafka partition router that reduced delivery latency by 40%. Walk me through how you chose your partitioning key and dealt with hotspot skew.",
    "turn_type": "resume_claim",
    "source": "resume",
    "source_ref": "Uber: Kafka partition router (40% latency reduction)",
    "reasoning_note": "Starting with an impactful metrics-grounded claim from their most recent role."
  }
}
```

#### Error Responses
- `400 Bad Request` (Missing Resume):
  ```json
  {
    "detail": "Either 'resume_text' or 'resume_file_path' must be provided."
  }
  ```
- `400 Bad Request` (Invalid GitHub input — both or neither provided):
  ```json
  {
    "detail": "Exactly one of 'github_username' or 'github_url' must be provided."
  }
  ```
- `400 Bad Request` (Invalid GitHub URL domain or structure):
  ```json
  {
    "detail": "Invalid GitHub URL: must be a valid github.com profile URL (e.g., https://github.com/username)."
  }
  ```
- `404 Not Found` (GitHub User not found):
  ```json
  {
    "detail": "GitHub user 'unknown_user_9999' was not found or has no public repositories."
  }
  ```
- `502 Bad Gateway` (Upstream LLM or GitHub error):
  ```json
  {
    "detail": "Failed to connect to LLM provider (openrouter): Connection timeout."
  }
  ```

---

### 3.2 `POST /session/{session_id}/answer`

Receives the candidate's answer for the current turn, appends it to the transcript, evaluates context switching or follow-up logic, and returns the interviewer's subsequent turn.

#### Path Parameters
- `session_id` (string, UUID): The unique session identifier returned by `/session/start`.

#### Request Body
```json
{
  "answer": "We keyed by tenant_id, but for our top 5 enterprise customers who generated 60% of all events, we hashed tenant_id plus a random modulus (0..3) across 4 dedicated partitions."
}
```

#### Response Body (`200 OK`)
```json
{
  "session_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "status": "active",
  "turn_index": 2,
  "turn": {
    "question": "Fanning out a single tenant across 4 partitions means total ordering is lost for those tenant events. How did your downstream consumers handle state mutations that arrived out of order?",
    "turn_type": "follow_up",
    "source": "resume",
    "source_ref": "prior_answer: tenant-partition fanning out and out-of-order handling",
    "reasoning_note": "Candidate answered the skew question; now challenging the consistency trade-off caused by their partition fanning."
  }
}
```

#### Error Responses
- `400 Bad Request` (Empty or whitespace-only answer):
  ```json
  {
    "detail": "Candidate answer cannot be empty or whitespace only."
  }
  ```
- `404 Not Found` (Session ID not found):
  ```json
  {
    "detail": "Session '9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d' was not found."
  }
  ```
- `409 Conflict` (Session already ended):
  ```json
  {
    "detail": "Session '9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d' is already completed. No more answers can be submitted."
  }
  ```

---

### 3.3 `GET /session/{session_id}/transcript`

Fetches the complete audit log of the interview, including all candidate answers, interviewer questions, metadata tags, and the list of covered references.

#### Path Parameters
- `session_id` (string, UUID): The unique session identifier.

#### Response Body (`200 OK`)
```json
{
  "session_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "status": "active",
  "turn_count": 2,
  "created_at": "2026-09-27T15:30:00Z",
  "updated_at": "2026-09-27T15:32:15Z",
  "covered_refs": [
    {
      "source": "resume",
      "ref": "Uber: Kafka partition router (40% latency reduction)",
      "turn_index": 1,
      "timestamp": "2026-09-27T15:30:05Z"
    },
    {
      "source": "resume",
      "ref": "prior_answer: tenant-partition fanning out and out-of-order handling",
      "turn_index": 2,
      "timestamp": "2026-09-27T15:32:15Z"
    }
  ],
  "transcript": [
    {
      "role": "interviewer",
      "content": "Welcome! Looking over your experience at Uber, you mention architecting a Kafka partition router...",
      "turn_index": 1,
      "timestamp": "2026-09-27T15:30:05Z",
      "meta": {
        "source": "resume",
        "source_ref": "Uber: Kafka partition router (40% latency reduction)",
        "turn_type": "resume_claim",
        "reasoning_note": "Starting with an impactful metrics-grounded claim from their most recent role."
      }
    },
    {
      "role": "candidate",
      "content": "We keyed by tenant_id, but for our top 5 enterprise customers...",
      "turn_index": 1,
      "timestamp": "2026-09-27T15:31:00Z",
      "meta": null
    },
    {
      "role": "interviewer",
      "content": "Fanning out a single tenant across 4 partitions means total ordering is lost...",
      "turn_index": 2,
      "timestamp": "2026-09-27T15:32:15Z",
      "meta": {
        "source": "resume",
        "source_ref": "prior_answer: tenant-partition fanning out and out-of-order handling",
        "turn_type": "follow_up",
        "reasoning_note": "Candidate answered the skew question; now challenging consistency trade-offs."
      }
    }
  ]
}
```

#### Error Responses
- `404 Not Found`: Session does not exist.

---

### 3.4 `POST /session/{session_id}/end`

Explicitly ends the interview session. Transitions state to `completed`, prevents further answer submissions, and returns an analytical summary of topics covered.

#### Path Parameters
- `session_id` (string, UUID): The unique session identifier.

#### Response Body (`200 OK`)
```json
{
  "session_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "status": "completed",
  "total_turns": 6,
  "summary": {
    "resume_questions_count": 4,
    "github_questions_count": 2,
    "skill_anchored_count": 1,
    "follow_up_count": 3,
    "context_switch_count": 2,
    "covered_topics": [
      "Uber: Kafka partition router",
      "prior_answer: tenant-partition fanning out",
      "repo: autotyper / README concurrency",
      "prior_answer: Go channels backpressure",
      "Resume Projects: VectorIndex C++20 SIMD HNSW"
    ]
  },
  "closing_message": "The interview session has been formally completed. All transcripts and metadata are preserved."
}
```

#### Error Responses
- `404 Not Found`: Session does not exist.

---

## 4. Example cURL Invocations

### 4.1 Start Session with `github_username`
```bash
curl -X POST http://127.0.0.1:8000/session/start \
  -H "Content-Type: application/json" \
  -d '{
    "github_username": "octocat",
    "resume_text": "Alex Rivers\nSenior Infrastructure Engineer\n- Architected Kafka streaming pipeline cutting latency from 450ms to 40ms\n- Designed automated PostgreSQL failover controller",
    "llm_provider": "openrouter"
  }'
```

### 4.2 Start Session with `github_url`
```bash
curl -X POST http://127.0.0.1:8000/session/start \
  -H "Content-Type: application/json" \
  -d '{
    "github_url": "https://github.com/octocat/",
    "resume_file_path": "sample_resume.txt",
    "llm_provider": "ollama",
    "model_name": "llama3.1"
  }'
```

### 4.3 Submit Answer
```bash
curl -X POST http://127.0.0.1:8000/session/<SESSION_ID>/answer \
  -H "Content-Type: application/json" \
  -d '{
    "answer": "We configured 12 Kafka partitions keyed by tenant_id and decoupled consumption via an in-memory ring buffer."
  }'
```

### 4.4 Get Transcript & Audit
```bash
curl -X GET http://127.0.0.1:8000/session/<SESSION_ID>/transcript
```

### 4.5 End Session
```bash
curl -X POST http://127.0.0.1:8000/session/<SESSION_ID>/end
```


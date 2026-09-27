# PRD: AI Interview Agent (Resume + GitHub Aware)

**Status:** Draft v1
**Scope:** Backend only. No frontend/UI in this phase (chat/API testing only, e.g. via Postman/curl/CLI).

---

## 1. Problem Statement

Existing "AI interviewer" tools are either RAG-style Q&A bots (retrieve a resume chunk → generate a generic question) or fixed-script quizzes. Neither feels like a real interview. A real interviewer:

- Picks a specific claim from your resume ("45% increase in execution speed") and asks you to defend it.
- Follows up based on *what you actually said*, not a pre-written follow-up bank.
- Switches from resume-context to GitHub-context and back, unpredictably — the way a real panel jumps between "walk me through this project" and "tell me about this bullet point on your CV."
- Remembers earlier answers in the same session and can call back to them ("Earlier you said X — does that conflict with Y?").

## 2. Goals

1. Ingest a candidate's **resume** (text/PDF-extracted) and **GitHub profile data** (repos, READMEs, languages, commit patterns) as two distinct, taggable knowledge sources.
2. Use an LLM (via **OpenRouter API**) as the "interviewer persona" — not a retrieval-then-answer pipeline, but a stateful conversational agent that reasons over both sources.
3. Generate **specific, claim-grounded questions**, not generic ones ("Tell me about a challenge you faced" ❌ vs. "You mentioned a 45% speed improvement — walk me through your approach" ✅).
4. Support **multi-turn memory**: follow-ups must reference the candidate's actual prior answer, not a fixed follow-up template.
5. Support **context switching**: the agent should be able to move between resume-sourced and GitHub-sourced questions non-linearly, similar to how a human interviewer bounces around.
6. Keep the question-selection logic **non-deterministic in pattern** (not "1 resume Q, 1 github Q, repeat") but deterministic in **traceability** (we can always answer: "why was this question asked, from which source, referencing which prior turn").

## 3. Non-Goals (this phase)

- No frontend/chat UI — interaction happens via API calls (e.g. Postman, curl, or a minimal CLI script) or a simple test harness.
- No auth/user accounts — single-session, single-candidate use for now.
- No audio/video/voice — text in, text out.
- No scoring/evaluation/hiring-decision logic — this phase is about the *interview conversation itself*, not candidate scoring.
- No persistent database across sessions (in-memory or flat-file session state is fine for v1).

## 4. Users

- Primary: Shrikanth, testing/demoing the agent directly via API calls.
- Secondary (future): a candidate being interviewed, via some future frontend.

## 5. Inputs

### 5.1 Resume
- Format: plain text or PDF-extracted text (reuse existing resume-parsing logic if already present in your other projects — see the codebase-scan step before building).
- No fixed schema required — the agent should work off raw resume text, but a lightweight structuring pass (sections: experience, projects, skills, education) improves question targeting.

### 5.2 GitHub Profile
- Input: a GitHub username or profile URL.
- Fetched via GitHub REST API (public, unauthenticated is fine for public repos; support optional PAT for higher rate limits).
- Data to pull per repo: name, description, README content (top ~1000 words), primary language, topics/tags, last-updated date.
- No need for commit-level analysis in v1 — repo + README is enough surface area for realistic questions.

## 6. Core Agent Design

### 6.1 Why not RAG
RAG retrieves the "most relevant chunk" per question — but a real interviewer doesn't retrieve, they **remember and reason**. So instead of a retrieve-then-ask loop, the agent holds the **full resume text + full GitHub summary** directly in its context window (both are small enough — a few thousand tokens combined) alongside a running conversation transcript. Every generation call sees:

1. The full source material (resume + GitHub summary), tagged by origin.
2. The full conversation so far (candidate's actual answers, verbatim).
3. A system prompt instructing it to behave as an interviewer, not a Q&A bot.

This removes the need for embeddings/vector search entirely for this scale of data.

### 6.2 Conversation State Machine

```
┌─────────────┐
│   INIT      │  Load resume + GitHub data, build source registry
└──────┬──────┘
       ▼
┌─────────────┐
│ SELECT_FOCUS│  Agent decides: resume-claim / github-project / follow-up
└──────┬──────┘
       ▼
┌─────────────┐
│ ASK         │  Emit question, tag with {source, source_ref, turn_type}
└──────┬──────┘
       ▼
┌─────────────┐
│ LISTEN      │  Receive candidate's answer, append to transcript
└──────┬──────┘
       ▼
┌─────────────┐
│ DECIDE_NEXT │  Agent decides: follow-up on this answer OR switch context
└──────┬──────┘
       └──────► back to SELECT_FOCUS
```

`DECIDE_NEXT` is the crux of the "not a fixed pattern" requirement — it's not a coin flip or round-robin, it's a **model decision**, prompted to weigh:
- Was the last answer vague/high-level? → follow up, dig into specifics.
- Was the last answer complete and specific? → good moment to switch source (resume ↔ GitHub).
- Has this source region already been covered? → avoid re-asking, pick an uncovered claim/project.

### 6.3 Memory Model

Keep it simple and inspectable — no need for a vector store:

```python
session_state = {
    "resume_text": str,
    "github_summary": dict,  # {repo_name: {description, readme_excerpt, language, topics}}
    "covered_refs": [        # tracks what's been asked about, to avoid repetition
        {"source": "resume", "ref": "45% speed improvement bullet", "turn": 2},
        {"source": "github", "ref": "autotyper", "turn": 4},
    ],
    "transcript": [
        {"role": "interviewer", "content": "...", "meta": {"source": "resume", "type": "opening"}},
        {"role": "candidate", "content": "..."},
        {"role": "interviewer", "content": "...", "meta": {"source": "resume", "type": "follow_up"}},
        {"role": "candidate", "content": "..."},
        {"role": "interviewer", "content": "...", "meta": {"source": "github", "type": "context_switch", "ref": "autotyper"}},
        ...
    ]
}
```

The full `transcript` + `covered_refs` + both source texts are passed to the LLM on every turn. `covered_refs` is maintained by having the model tag each question it emits with structured metadata (see 6.5), so the app layer can track it without a second "extraction" LLM call.

### 6.4 Context Switching Logic

"Context switching" here = switching **source region** (resume vs. GitHub), not conceptual topic. Implementation approach:

- The system prompt explicitly instructs: *"You may ask a follow-up on the current topic, OR pivot to a different source (resume vs GitHub) at any point. Do not follow a fixed alternating pattern. Let the pivot feel natural — e.g. after a strong answer, or when a topic is exhausted."*
- The model's response is asked to include structured metadata (see below) so the app can enforce guardrails (e.g., don't switch on literally every single turn — that would feel erratic too; and don't stay on one source for the entire session).
- A light app-layer nudge (not a hard rule) can bias the model: if `covered_refs` shows 4+ consecutive turns from the same source, add a soft instruction line: "Consider pivoting to the other source soon."

### 6.5 Structured Output Per Turn

Every interviewer turn should be generated as structured output so the app can log/track state without extra parsing calls:

```json
{
  "question": "You mentioned a 45% increase in execution speed — could you walk me through your approach?",
  "turn_type": "resume_claim | github_project | follow_up | context_switch | closing",
  "source": "resume | github",
  "source_ref": "short human-readable pointer to what's being referenced",
  "reasoning_note": "1-line internal note on why this question/pivot was chosen (not shown to candidate)"
}
```
`reasoning_note` is for your own debugging/tuning, not shown to the candidate.

### 6.6 Prompting Strategy

- **System prompt** defines persona ("You are a senior technical interviewer conducting a live interview..."), rules against genericness, rules for follow-up behavior, and the structured output contract.
- **Few-shot examples** in the system prompt showing the exact style from your brief (specific-claim question → follow-up → context-switched GitHub question → resume question again) to anchor tone and unpredictability.
- Explicitly instruct: *"Never ask a question that could apply to any candidate. Every question must reference a specific detail from the resume or GitHub content provided."*
- Explicitly instruct: *"Vary session structure — do not follow a fixed number of follow-ups before switching."*

## 7. Technical Architecture (Backend Only)

```
interview-agent/
├── app/
│   ├── main.py                 # FastAPI app entrypoint
│   ├── config.py               # env/config loading (OPENROUTER_API_KEY, model name, etc.)
│   ├── llm/
│   │   ├── openrouter_client.py    # thin wrapper around OpenRouter chat completions
│   │   └── prompts.py              # system prompt + few-shot templates
│   ├── ingestion/
│   │   ├── resume_loader.py        # load/clean resume text (txt or PDF)
│   │   └── github_loader.py        # fetch repos + READMEs via GitHub REST API
│   ├── session/
│   │   ├── state.py                # session_state dataclass/model (see 6.3)
│   │   └── store.py                # in-memory or flat-file session persistence
│   ├── agent/
│   │   └── interviewer.py          # core turn logic: build context, call LLM, parse structured output, update state
│   └── api/
│       └── routes.py               # POST /session/start, POST /session/{id}/answer, GET /session/{id}/transcript
├── tests/
├── .env.example
├── requirements.txt
└── README.md
```

### 7.1 Tech Stack
- **Language/Framework:** Python + FastAPI (matches existing stack/comfort).
- **LLM Provider:** OpenRouter API (model configurable via env var, e.g. `openai/gpt-4o`, `anthropic/claude-sonnet-4.6`, etc. — pick one strong at structured JSON output).
- **PDF parsing (if resume is PDF):** reuse existing resume-parsing utility if the codebase scan turns one up; otherwise `pdfplumber` or `pypdf`.
- **GitHub data:** `requests` against `api.github.com` (no SDK needed for this scope).
- **Session state:** in-memory dict for v1 (single-process); flat JSON file per session for persistence across restarts if needed.
- **Structured output:** enforce via JSON-mode / response schema if the chosen OpenRouter model supports it; otherwise strict prompt instruction + a JSON-repair fallback.

### 7.2 API Endpoints (v1)

| Endpoint | Method | Purpose |
|---|---|---|
| `/session/start` | POST | Accepts resume text/file + GitHub username, initializes session, returns first question |
| `/session/{id}/answer` | POST | Accepts candidate's answer text, returns next interviewer turn (question + metadata) |
| `/session/{id}/transcript` | GET | Returns full transcript + covered_refs, for debugging/inspection |
| `/session/{id}/end` | POST | Ends session, optionally returns a summary of topics covered |

## 8. Success Criteria (v1)

- Given a real resume + GitHub profile, the agent can run a 10–15 turn conversation that:
  - Asks at least 3 resume-claim questions and 3 GitHub-project questions.
  - Produces at least 2 genuine follow-ups that clearly reference the candidate's prior answer (not templated).
  - Switches source context at least 3 times, at non-fixed intervals.
  - Never repeats the same source_ref twice (no re-asking about the same bullet/project unless explicitly a callback follow-up).
- Every question is specific enough that it couldn't be asked of a different candidate's resume/GitHub unchanged.

## 9. Open Questions / Decisions Needed

1. Which OpenRouter model to default to (affects JSON-mode reliability and cost) — need a quick eval pass across 2–3 candidates.
2. How long should a session run before a "closing" turn is forced (fixed max turns, e.g. 15–20, vs. model-decided)?
3. Should `covered_refs` be model-reported only, or should the app layer also do a cheap keyword-overlap check as a safety net against accidental repeats?
4. PDF resume support in v1, or text-only for now (faster to ship)?

## 10. Milestones

1. **M1** — Ingestion: resume loader + GitHub loader working standalone, output inspectable as JSON.
2. **M2** — Single-turn question generation: given full context, generate one well-grounded, specific question with structured metadata.
3. **M3** — Full state machine: multi-turn loop with follow-up/switch decision logic, session state tracked and inspectable via `/transcript`.
4. **M4** — Tuning pass: few-shot prompt refinement against real resume/GitHub pairs until output matches the "realistic interviewer" bar in Section 8.
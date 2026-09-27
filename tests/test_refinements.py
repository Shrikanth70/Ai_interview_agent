"""Tests verifying Changes 1-4: context-switching, symmetrical follow-ups, github_url input, and LLM provider / JSON repair."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.agent.interviewer import InterviewerAgent, InterviewerTurnOutput
from app.api.models import StartSessionRequest, parse_github_username_from_url
from app.api.routes import get_agent
from app.llm.base import BaseLLMClient, extract_and_parse_json
from app.llm.client import LLMClient
from app.main import app


def test_github_url_parsing():
    """Verify parsing github usernames from diverse valid URL formats and rejecting invalid ones."""
    assert parse_github_username_from_url("https://github.com/shrikanth-dev") == "shrikanth-dev"
    assert parse_github_username_from_url("https://github.com/shrikanth-dev/") == "shrikanth-dev"
    assert parse_github_username_from_url("http://github.com/octocat") == "octocat"
    assert parse_github_username_from_url("https://www.github.com/torvalds/") == "torvalds"
    assert parse_github_username_from_url("github.com/octocat") == "octocat"

    # Reject non-github.com URLs
    with pytest.raises(ValueError, match="must be a valid github.com profile URL"):
        parse_github_username_from_url("https://gitlab.com/shrikanth-dev")

    with pytest.raises(ValueError, match="must be a valid github.com profile URL"):
        parse_github_username_from_url("https://example.com/user")

    # Reject URLs without a username
    with pytest.raises(ValueError, match="expected profile path"):
        parse_github_username_from_url("https://github.com/")


def test_start_session_request_validation():
    """Verify StartSessionRequest mutual exclusivity for github_username and github_url."""
    # Valid with username only
    req1 = StartSessionRequest(
        github_username="octocat",
        resume_text="Senior engineer with Python and distributed systems expertise.",
    )
    assert req1.github_username == "octocat"

    # Valid with URL only (automatically parsed into github_username)
    req2 = StartSessionRequest(
        github_url="https://github.com/octocat/",
        resume_text="Senior engineer with Python and distributed systems expertise.",
    )
    assert req2.github_username == "octocat"

    # Invalid: both provided
    with pytest.raises(ValueError, match="Exactly one of 'github_username' or 'github_url'"):
        StartSessionRequest(
            github_username="octocat",
            github_url="https://github.com/octocat",
            resume_text="Experience...",
        )

    # Invalid: neither provided
    with pytest.raises(ValueError, match="Exactly one of 'github_username' or 'github_url'"):
        StartSessionRequest(
            resume_text="Experience...",
        )

    # Invalid: no resume provided
    with pytest.raises(ValueError, match="Either 'resume_text' or 'resume_file_path'"):
        StartSessionRequest(
            github_username="octocat",
        )


def test_extract_and_parse_json():
    """Verify JSON extraction handles fences, extra text, and raw JSON."""
    # Clean JSON
    assert extract_and_parse_json('{"key": "value"}') == {"key": "value"}

    # Markdown fences
    fenced = '```json\n{"question": "How did you scale Kafka?", "turn_type": "resume_claim"}\n```'
    parsed = extract_and_parse_json(fenced)
    assert parsed["question"] == "How did you scale Kafka?"

    # Markdown fences without 'json' tag
    fenced2 = '```\n{"question": "Explain Raft log compaction", "turn_type": "github_project"}\n```'
    parsed2 = extract_and_parse_json(fenced2)
    assert parsed2["turn_type"] == "github_project"

    # Conversational text surrounding JSON
    surrounded = 'Here is the turn payload:\n{"question": "Explain eBPF", "turn_type": "skill_anchored"}\nHope this helps!'
    parsed3 = extract_and_parse_json(surrounded)
    assert parsed3["turn_type"] == "skill_anchored"


@pytest.mark.asyncio
async def test_llm_base_repair_retry():
    """Verify that BaseLLMClient retries once with a stricter instruction if the first response is invalid JSON."""
    call_log = []

    class MockFailingThenSuccessClient(BaseLLMClient):
        async def _call_provider(self, messages, temperature):
            call_log.append(messages)
            if len(call_log) == 1:
                # First attempt returns invalid text
                return "I think you should ask: How does Raft consensus work?"
            # Second attempt (after repair instruction) returns valid JSON
            return '{"question": "How does Raft work?", "turn_type": "github_project", "source": "github", "source_ref": "repo: raft", "reasoning_note": "probed"}'

    client = MockFailingThenSuccessClient()
    result = await client.generate_turn([{"role": "user", "content": "Generate question"}])
    assert result["question"] == "How does Raft work?"
    assert len(call_log) == 2
    # Verify the second call received the repair instruction
    assert "CRITICAL: Your previous response was not valid JSON" in call_log[1][-1]["content"]


class MockSymmetricalAndSkillLLMClient:
    """Mock client providing symmetrical follow-ups on GitHub and skill-anchored questions."""

    def __init__(self):
        self.turns = [
            # Turn 1: Opening Resume Claim (Required by Priority 0 Ordering Rule)
            {
                "question": "Welcome! Looking over your experience at Acme Cloud, you noted reducing latency by 45% on your Kafka pipeline. Walk me through the bottlenecks you diagnosed.",
                "turn_type": "resume_claim",
                "source": "resume",
                "source_ref": "Acme Cloud Infrastructure: Kafka 45% event latency reduction",
                "reasoning_note": "Starting with a verified resume claim.",
            },
            # Turn 2: Context Switch to candidate's GitHub Project
            {
                "question": "In your 'autotyper' repository, you used Goroutines to emit key events. How did you coordinate timing?",
                "turn_type": "context_switch",
                "source": "github",
                "source_ref": "repo: autotyper / Goroutine timer coordination",
                "reasoning_note": "Switching to open-source systems project.",
            },
            # Turn 3: Symmetrical follow-up on that GitHub answer!
            {
                "question": "You mentioned channel select loops with time.After. Did you profile timer leak issues in older Go runtimes?",
                "turn_type": "follow_up",
                "source": "github",
                "source_ref": "prior_answer: time.After channel leak in select loop",
                "reasoning_note": "Symmetrically digging deeper into their GitHub implementation specifics.",
            },
            # Turn 4: Skill-anchored question
            {
                "question": "You listed 'Kubernetes' in your skills section. Walk me through where you have designed or managed k8s clusters in practice.",
                "turn_type": "skill_anchored",
                "source": "resume",
                "source_ref": "Skills Section: Kubernetes",
                "reasoning_note": "Testing skill veracity across both sources.",
            },
            # Turn 5: Closing
            {
                "question": "Thank you for walking through your experience and repos today.",
                "turn_type": "closing",
                "source": "resume",
                "source_ref": "session_completion",
                "reasoning_note": "Wrap up.",
            },
        ]
        self.call_idx = 0

    async def generate_turn(self, messages, temperature=0.4, max_retries=3):
        turn = self.turns[min(self.call_idx, len(self.turns) - 1)]
        self.call_idx += 1
        return turn


@pytest.mark.asyncio
async def test_e2e_github_url_and_symmetrical_follow_up():
    """Verify session start with github_url, Turn 1 resume ordering, symmetrical follow-up on GitHub, and skill_anchored turn."""
    mock_client = MockSymmetricalAndSkillLLMClient()
    mock_agent = InterviewerAgent(llm_client=mock_client)

    app.dependency_overrides[get_agent] = lambda: mock_agent

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Start Session with github_url (Option B)
        start_payload = {
            "github_url": "https://github.com/octocat/",
            "resume_file_path": "sample_resume.txt",
            "use_mock_github": True,
        }
        res_start = await client.post("/session/start", json=start_payload)
        assert res_start.status_code == 201
        data_start = res_start.json()

        session_id = data_start["session_id"]
        # Ordering Rule: Turn 1 is ALWAYS from resume
        assert data_start["turn"]["turn_type"] == "resume_claim"
        assert data_start["turn"]["source"] == "resume"

        # 2. Candidate Answer on resume -> Turn 2 pivots to GitHub
        res_turn_2 = await client.post(
            f"/session/{session_id}/answer",
            json={"answer": "We removed synchronous DB queries and batched events in memory."},
        )
        assert res_turn_2.status_code == 200
        turn_2 = res_turn_2.json()["turn"]
        assert turn_2["turn_type"] == "context_switch"
        assert turn_2["source"] == "github"

        # 3. Candidate Answer on GitHub project -> Turn 3 is symmetrical follow-up on GitHub!
        res_turn_3 = await client.post(
            f"/session/{session_id}/answer",
            json={"answer": "I used time.After in a select statement inside each worker goroutine."},
        )
        assert res_turn_3.status_code == 200
        turn_3 = res_turn_3.json()["turn"]
        assert turn_3["turn_type"] == "follow_up"
        assert turn_3["source"] == "github"
        assert "prior_answer" in turn_3["source_ref"]

        # 4. Answer follow-up -> Turn 4 is skill_anchored
        res_turn_4 = await client.post(
            f"/session/{session_id}/answer",
            json={"answer": "We avoided leaks by resetting a persistent time.NewTimer instead."},
        )
        assert res_turn_4.status_code == 200
        turn_4 = res_turn_4.json()["turn"]
        assert turn_4["turn_type"] == "skill_anchored"
        assert "Skills Section" in turn_4["source_ref"]

        # 5. Check End Session summary
        res_end = await client.post(f"/session/{session_id}/end")
        assert res_end.status_code == 200
        end_data = res_end.json()
        assert end_data["summary"]["skill_anchored_count"] == 1
        assert end_data["summary"]["github_questions_count"] == 2
        assert end_data["summary"]["follow_up_count"] == 1

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_anti_cheating_conditional_follow_up_flow():
    """Verify that MockLLMClient does NOT follow up on thorough answers (jumps dynamically),
    and strictly triggers follow_up when an answer is shallow/vague to stop cheating.
    """
    from app.llm.mock_client import MockLLMClient
    from app.api.routes import get_agent

    mock_llm = MockLLMClient()
    agent = InterviewerAgent(llm_client=mock_llm)
    app.dependency_overrides[get_agent] = lambda: agent

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Start interview
        start_payload = {
            "resume_text": "Experienced Systems Engineer with Kafka event pipeline optimization (reduced latency from 450ms to 40ms) and eBPF kernel tracing skills.",
            "github_username": "mock-tester",
            "use_mock_github": True,
        }
        res_start = await client.post("/session/start", json=start_payload)
        assert res_start.status_code == 201
        session_id = res_start.json()["session_id"]
        turn_1 = res_start.json()["turn"]
        assert turn_1["turn_type"] == "resume_claim"
        assert "Kafka" in turn_1["question"]

        # 1. Candidate gives a THOROUGH, IN-DEPTH answer (> 18 words, detailed)
        thorough_answer = (
            "We profiled the synchronous MySQL inserts and identified severe thread pool contention. "
            "We introduced 12 Kafka partitions keyed by tenant_id with snappy compression, "
            "decoupled ingestion via an in-memory ring buffer, and achieved 40ms P99 latency."
        )
        res_turn_2 = await client.post(
            f"/session/{session_id}/answer",
            json={"answer": thorough_answer},
        )
        assert res_turn_2.status_code == 200
        turn_2 = res_turn_2.json()["turn"]
        # MUST NOT BE FOLLOW_UP! Should jump straight to GitHub (anti-cheating, no paired rhythm)
        assert turn_2["turn_type"] != "follow_up"
        assert turn_2["source"] == "github"
        assert "autotyper" in turn_2["question"]

        # 2. Candidate gives a VAGUE, SHALLOW answer (< 18 words, buzzwordy)
        shallow_answer = "I just used standard stuff with goroutines and best practices."
        res_turn_3 = await client.post(
            f"/session/{session_id}/answer",
            json={"answer": shallow_answer},
        )
        assert res_turn_3.status_code == 200
        turn_3 = res_turn_3.json()["turn"]
        # MUST BE FOLLOW_UP because answer lacked potential / technical depth!
        assert turn_3["turn_type"] == "follow_up"
        assert turn_3["source"] == "github"
        assert "prior_answer" in turn_3["source_ref"]

        # 3. Candidate answers follow-up thoroughly
        thorough_followup_answer = (
            "To avoid leaking timers in tight select loops, we replaced time.After with a reusable time.NewTimer, "
            "properly draining the channel when stopping before reset, verified with pprof heap allocations under 10k events/sec."
        )
        res_turn_4 = await client.post(
            f"/session/{session_id}/answer",
            json={"answer": thorough_followup_answer},
        )
        assert res_turn_4.status_code == 200
        turn_4 = res_turn_4.json()["turn"]
        # Prior was resolved thoroughly, so NO follow up! Jumps dynamically to an unprobed repo or skill!
        assert turn_4["turn_type"] != "follow_up"
        assert turn_4["turn_type"] in ("skill_anchored", "context_switch", "resume_claim")

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_real_uploaded_resume_opening_greeting():
    """Verify that any real uploaded resume begins with the mandatory welcome greeting
    highlighting a concrete claim or skill directly from that candidate's actual resume."""
    from app.llm.mock_client import MockLLMClient
    from app.api.routes import get_agent

    mock_llm = MockLLMClient()
    agent = InterviewerAgent(llm_client=mock_llm)
    app.dependency_overrides[get_agent] = lambda: agent

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Real resume with concrete project & NLP claim (MovieBuddy)
        real_resume_text = (
            "Bhukya Srikanth\n"
            "Software Developer\n\n"
            "PROJECTS\n"
            "MovieBuddy — AI Movie Recommendation Platform\n"
            "- Developed a content-based movie recommendation system using Python and NLP techniques "
            "trained on the TMDB dataset to generate personalized movie suggestions.\n"
            "- Built an interactive Streamlit web application integrating TMDB and OMDb APIs.\n\n"
            "TECHNICAL SKILLS\n"
            "Programming Languages: Python, JavaScript, SQL\n"
            "Frameworks: Streamlit, FastAPI, REST APIs"
        )
        start_payload = {
            "resume_text": real_resume_text,
            "github_username": "Shrikanth70",
            "use_mock_github": True,
        }
        res_start = await client.post("/session/start", json=start_payload)
        assert res_start.status_code == 201
        data = res_start.json()
        turn_1 = data["turn"]

        # MUST start with the welcome note
        assert turn_1["question"].startswith("Welcome! Looking over your experience and background, you highlighted")
        # MUST highlight the real claim/skill from the uploaded resume, NOT Kafka!
        assert "Kafka" not in turn_1["question"]
        assert "movie recommendation" in turn_1["question"].lower() or "nlp" in turn_1["question"].lower()
        assert turn_1["source"] == "resume"
        assert turn_1["turn_type"] == "resume_claim"
        assert len(turn_1["source_ref"]) > 5

        # 2. Real resume with only technical skills listed
        skills_resume_text = (
            "Jane Smith\n"
            "Cloud Infrastructure Engineer\n\n"
            "TECHNICAL SKILLS\n"
            "Core Technologies: FastAPI, PostgreSQL, Docker, Redis\n"
        )
        start_skills_payload = {
            "resume_text": skills_resume_text,
            "github_username": "janesmith",
            "use_mock_github": True,
        }
        res_skills = await client.post("/session/start", json=start_skills_payload)
        assert res_skills.status_code == 201
        skills_data = res_skills.json()
        skills_turn_1 = skills_data["turn"]

        # MUST start with the welcome note
        assert skills_turn_1["question"].startswith("Welcome! Looking over your experience and background, you highlighted")
        assert "Kafka" not in skills_turn_1["question"]
        assert "fastapi" in skills_turn_1["question"].lower() or "postgresql" in skills_turn_1["question"].lower()
        assert skills_turn_1["source"] == "resume"
        assert skills_turn_1["turn_type"] in ("skill_anchored", "resume_claim")

    app.dependency_overrides.clear()



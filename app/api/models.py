from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from urllib.parse import urlparse
from pydantic import BaseModel, Field, model_validator

from app.agent.interviewer import InterviewerTurnOutput
from app.session.state import CoveredRef, TranscriptTurn


def parse_github_username_from_url(url_str: str) -> str:
    """Extracts and validates the GitHub username from a profile URL.
    
    Accepts:
    - https://github.com/shrikanth-dev
    - https://github.com/shrikanth-dev/
    - http://github.com/shrikanth-dev
    - github.com/shrikanth-dev
    - https://www.github.com/shrikanth-dev/
    
    Rejects non-github.com URLs and malformed paths.
    """
    raw = url_str.strip()
    if not raw.startswith(("http://", "https://")):
        raw = "https://" + raw

    parsed = urlparse(raw)
    domain = parsed.netloc.lower()
    if domain.startswith("www."):
        domain = domain[4:]

    if domain != "github.com":
        raise ValueError(
            f"Invalid GitHub URL '{url_str}': must be a valid github.com profile URL."
        )

    path_segments = [p for p in parsed.path.strip("/").split("/") if p]
    if len(path_segments) != 1:
        raise ValueError(
            f"Invalid GitHub URL '{url_str}': expected profile path in format 'github.com/<username>'."
        )

    return path_segments[0]


class StartSessionRequest(BaseModel):
    """Request payload to initialize an interview session."""

    resume_text: Optional[str] = Field(
        default=None,
        description="Raw resume text string.",
    )
    resume_file_path: Optional[str] = Field(
        default=None,
        description="Path to local resume document (.txt, .md, or .pdf).",
    )
    github_username: Optional[str] = Field(
        default=None,
        description="Public GitHub username or profile handle.",
        examples=["octocat"],
    )
    github_url: Optional[str] = Field(
        default=None,
        description="Full public GitHub profile URL.",
        examples=["https://github.com/octocat"],
    )
    use_mock_github: bool = Field(
        default=False,
        description="Whether to use offline mock GitHub portfolio for fast demonstration/testing.",
    )
    llm_provider: Optional[Literal["openrouter", "ollama", "mock"]] = Field(
        default=None,
        description="LLM provider: 'ollama' (local), 'openrouter' (cloud), or 'mock' (offline demo). Defaults to settings.",
    )
    model_name: Optional[str] = Field(
        default=None,
        description="Model name override (e.g. 'llama3.1' or 'anthropic/claude-3.5-sonnet').",
    )
    starting_theme: Optional[Literal["PROFILE", "JD"]] = Field(
        default=None,
        description="Initial theme override ('PROFILE' or 'JD'). If None, randomized 50/50.",
    )
    jd_text: Optional[str] = Field(
        default=None,
        description="Optional raw text of the target role Job Description.",
    )
    jd_scenarios: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="Optional pre-structured JD technical scenarios.",
    )

    @model_validator(mode="after")
    def validate_inputs(self) -> "StartSessionRequest":
        """Ensures valid resume input and mutually exclusive GitHub username / URL."""
        has_text = bool(self.resume_text and self.resume_text.strip())
        has_file = bool(self.resume_file_path and self.resume_file_path.strip())
        if not has_text and not has_file:
            raise ValueError("Either 'resume_text' or 'resume_file_path' must be provided.")

        has_username = bool(self.github_username and self.github_username.strip())
        has_url = bool(self.github_url and self.github_url.strip())

        if has_username == has_url:
            raise ValueError(
                "Exactly one of 'github_username' or 'github_url' must be provided."
            )

        if has_url:
            self.github_username = parse_github_username_from_url(self.github_url)

        return self


class OrchestrationResponse(BaseModel):
    """Real-time metadata describing the 2-theme engine, budget, and memory hierarchy."""

    active_theme: Literal["PROFILE", "JD"] = "PROFILE"
    active_context_id: str = ""
    current_rubric_dimension: Optional[str] = None
    is_bridge_turn: bool = False
    minutes_remaining: float = 25.0
    elapsed_minutes: float = 0.0
    is_closing_time: bool = False
    sub_memories: List[Dict[str, Any]] = Field(default_factory=list)
    globally_covered_topics: List[str] = Field(default_factory=list)


class StartSessionResponse(BaseModel):
    """Response returned upon successful session creation."""

    session_id: str
    status: Literal["active", "completed"] = "active"
    turn_index: int
    turn: InterviewerTurnOutput
    orchestration: Optional[OrchestrationResponse] = None


class SubmitAnswerRequest(BaseModel):
    """Request payload containing the candidate's answer for the current turn."""

    answer: str = Field(
        ...,
        min_length=1,
        description="Verbatim text of the candidate's answer.",
    )
    jev_signal: Optional[Literal["FOLLOW_UP", "SWITCH_CONTEXT"]] = Field(
        default=None,
        description="External evaluator signal driving next question strategy (FOLLOW_UP or SWITCH_CONTEXT).",
    )


class SubmitAnswerResponse(BaseModel):
    """Response returned after processing a candidate's answer."""

    session_id: str
    status: Literal["active", "completed"]
    turn_index: int
    turn: InterviewerTurnOutput
    orchestration: Optional[OrchestrationResponse] = None


class TranscriptResponse(BaseModel):
    """Complete audit record of the interview session."""

    session_id: str
    status: Literal["active", "completed"]
    turn_count: int
    created_at: datetime
    updated_at: datetime
    covered_refs: List[CoveredRef]
    transcript: List[TranscriptTurn]


class SessionSummary(BaseModel):
    """Analytical summary of covered topics and questioning patterns."""

    resume_questions_count: int
    github_questions_count: int
    skill_anchored_count: int = 0
    follow_up_count: int
    context_switch_count: int
    covered_topics: List[str]


class EndSessionResponse(BaseModel):
    """Response returned upon formal session conclusion."""

    session_id: str
    status: Literal["completed"]
    total_turns: int
    summary: SessionSummary
    closing_message: str

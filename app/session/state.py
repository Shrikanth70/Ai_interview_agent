from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, field_validator


class TurnMeta(BaseModel):
    """Metadata describing the origin, intent, and reasoning behind an interviewer turn."""

    source: Optional[Literal["resume", "github"]] = None
    source_ref: Optional[str] = None
    turn_type: Literal[
        "resume_claim",
        "github_project",
        "skill_anchored",
        "follow_up",
        "context_switch",
        "closing",
    ] = "resume_claim"
    reasoning_note: Optional[str] = None

    @field_validator("turn_type", mode="before")
    @classmethod
    def normalize_turn_type(cls, v: Any) -> str:
        if not isinstance(v, str):
            return "resume_claim"
        cleaned = v.strip().lower().replace("-", "_").replace(" ", "_")
        mapping = {
            "resume": "resume_claim",
            "resume_claim": "resume_claim",
            "resume_project": "resume_claim",
            "project": "resume_claim",
            "claim": "resume_claim",
            "github": "github_project",
            "github_project": "github_project",
            "github_repo": "github_project",
            "repo": "github_project",
            "repository": "github_project",
            "skill": "skill_anchored",
            "skills": "skill_anchored",
            "skill_anchored": "skill_anchored",
            "skill_anchor": "skill_anchored",
            "followup": "follow_up",
            "follow_up": "follow_up",
            "switch": "context_switch",
            "context_switch": "context_switch",
            "closing": "closing",
            "close": "closing",
            "conclude": "closing",
            "conclusion": "closing",
        }
        return mapping.get(cleaned, "resume_claim")

    @field_validator("source", mode="before")
    @classmethod
    def normalize_source(cls, v: Any) -> Optional[str]:
        if not v or not isinstance(v, str):
            return "resume"
        cleaned = v.strip().lower()
        if "github" in cleaned:
            return "github"
        if "resume" in cleaned:
            return "resume"
        return "resume"


class TranscriptTurn(BaseModel):
    """A single turn in the interview transcript (either candidate or interviewer)."""

    role: Literal["interviewer", "candidate"]
    content: str
    turn_index: int
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    meta: Optional[TurnMeta] = None


class CoveredRef(BaseModel):
    """A record of a specific resume claim or GitHub repository that has been explored."""

    source: Literal["resume", "github"]
    ref: str
    turn_index: int
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SessionState(BaseModel):
    """Complete, stateful representation of an active or concluded interview session."""

    session_id: str
    status: Literal["active", "completed"] = "active"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Full source documents kept directly in context
    resume_text: str
    github_summary: Dict[str, Any]

    # Memory state
    covered_refs: List[CoveredRef] = Field(default_factory=list)
    transcript: List[TranscriptTurn] = Field(default_factory=list)
    turn_count: int = 0

    # Provider and model tracking
    llm_provider: Optional[Literal["openrouter", "ollama", "mock"]] = None
    model_name: Optional[str] = None

    def add_candidate_answer(self, answer_text: str) -> TranscriptTurn:
        """Appends candidate's answer to the transcript."""
        turn = TranscriptTurn(
            role="candidate",
            content=answer_text.strip(),
            turn_index=self.turn_count,
            timestamp=datetime.now(timezone.utc),
            meta=None,
        )
        self.transcript.append(turn)
        self.updated_at = datetime.now(timezone.utc)
        return turn

    def add_interviewer_question(
        self,
        question: str,
        turn_type: Literal[
            "resume_claim",
            "github_project",
            "skill_anchored",
            "follow_up",
            "context_switch",
            "closing",
        ],
        source: Optional[Literal["resume", "github"]] = None,
        source_ref: Optional[str] = None,
        reasoning_note: Optional[str] = None,
    ) -> TranscriptTurn:
        """Appends interviewer's question to the transcript and registers the covered reference."""
        self.turn_count += 1
        meta = TurnMeta(
            source=source,
            source_ref=source_ref,
            turn_type=turn_type,
            reasoning_note=reasoning_note,
        )
        turn = TranscriptTurn(
            role="interviewer",
            content=question.strip(),
            turn_index=self.turn_count,
            timestamp=datetime.now(timezone.utc),
            meta=meta,
        )
        self.transcript.append(turn)

        # Register covered reference if valid source and ref
        if source and source_ref and turn_type != "closing":
            self.covered_refs.append(
                CoveredRef(
                    source=source,
                    ref=source_ref,
                    turn_index=self.turn_count,
                    timestamp=datetime.now(timezone.utc),
                )
            )

        if turn_type == "closing":
            self.status = "completed"

        self.updated_at = datetime.now(timezone.utc)
        return turn

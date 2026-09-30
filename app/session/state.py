from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, field_validator


class TurnMeta(BaseModel):
    """Metadata describing the origin, intent, and reasoning behind an interviewer turn."""

    source: Optional[Literal["resume", "github", "jd"]] = None
    source_ref: Optional[str] = None
    turn_type: Literal[
        "resume_claim",
        "github_project",
        "skill_anchored",
        "role_scenario",
        "follow_up",
        "context_switch",
        "theme_switch",
        "closing",
    ] = "resume_claim"
    theme: Optional[Literal["PROFILE", "JD"]] = None
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
            "role_scenario": "role_scenario",
            "jd_scenario": "role_scenario",
            "scenario": "role_scenario",
            "followup": "follow_up",
            "follow_up": "follow_up",
            "switch": "theme_switch",
            "theme_switch": "theme_switch",
            "bridge": "theme_switch",
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
        if "jd" in cleaned:
            return "jd"
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

    source: Literal["resume", "github", "jd"]
    ref: str
    turn_index: int
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class TurnRecord(BaseModel):
    """A single dialogue turn stored in sub-memory or the short-term sliding window."""

    turn_index: int
    role: Literal["interviewer", "candidate"]
    content: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    theme: Optional[Literal["PROFILE", "JD"]] = None
    context_id: Optional[str] = None
    rubric_dimension: Optional[str] = None


class ContextSubMemory(BaseModel):
    """Domain-scoped memory tracking depth on a single project, resume claim, or JD scenario."""

    context_id: str
    theme: Literal["PROFILE", "JD"]
    source_ref: str
    source_slice: Dict[str, Any] = Field(default_factory=dict)
    probed_dimensions: List[str] = Field(default_factory=list)
    pending_dimensions: List[str] = Field(
        default_factory=lambda: ["clarity_of_framing", "methodology_depth", "feasibility"]
    )
    turns: List[TurnRecord] = Field(default_factory=list)
    extracted_takeaways: Dict[str, str] = Field(default_factory=dict)

    def record_turn(
        self,
        role: Literal["interviewer", "candidate"],
        content: str,
        rubric_dimension: Optional[str] = None,
    ) -> TurnRecord:
        turn = TurnRecord(
            turn_index=len(self.turns) + 1,
            role=role,
            content=content.strip(),
            theme=self.theme,
            context_id=self.context_id,
            rubric_dimension=rubric_dimension,
        )
        self.turns.append(turn)
        if rubric_dimension:
            if rubric_dimension in self.pending_dimensions:
                self.pending_dimensions.remove(rubric_dimension)
            if rubric_dimension not in self.probed_dimensions:
                self.probed_dimensions.append(rubric_dimension)
        return turn


class SessionBudget(BaseModel):
    """Timer and turn limit guardrails for the 25-minute interview."""

    max_duration_seconds: int = 1500  # 25 minutes
    max_turns: int = 12
    start_time: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def elapsed_seconds(self) -> float:
        return (datetime.now(timezone.utc) - self.start_time).total_seconds()

    @property
    def elapsed_minutes(self) -> float:
        return self.elapsed_seconds / 60.0

    @property
    def minutes_remaining(self) -> float:
        return max(0.0, (self.max_duration_seconds - self.elapsed_seconds) / 60.0)

    @property
    def is_closing_time(self) -> bool:
        return self.elapsed_seconds >= 1320  # 22 minutes cutoff


class OrchestrationState(BaseModel):
    """Global coordination state for theme and context transitions."""

    active_theme: Literal["PROFILE", "JD"] = "PROFILE"
    active_context_id: Optional[str] = None
    turns_in_active_context: int = 0
    last_jev_signal: Optional[Literal["FOLLOW_UP", "SWITCH_CONTEXT"]] = None
    theme_switch_pending: bool = False


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

    # Hierarchical memory and orchestration
    budget: SessionBudget = Field(default_factory=SessionBudget)
    orchestration: OrchestrationState = Field(default_factory=OrchestrationState)
    sub_memories: Dict[str, ContextSubMemory] = Field(default_factory=dict)
    recent_dialogue_window: List[TurnRecord] = Field(default_factory=list)
    globally_covered_topics: List[str] = Field(default_factory=list)
    jd_scenarios: Optional[List[Dict[str, Any]]] = None
    jd_text: Optional[str] = None

    # Provider and model tracking
    llm_provider: Optional[Literal["openrouter", "ollama", "mock"]] = None
    model_name: Optional[str] = None

    def add_candidate_answer(self, answer_text: str) -> TranscriptTurn:
        """Appends candidate's answer to the transcript and updates hierarchical memory."""
        cleaned = answer_text.strip()
        turn = TranscriptTurn(
            role="candidate",
            content=cleaned,
            turn_index=self.turn_count,
            timestamp=datetime.now(timezone.utc),
            meta=None,
        )
        self.transcript.append(turn)

        # Update sliding window (max 6 items = 3 Q/A pairs)
        record = TurnRecord(
            turn_index=self.turn_count,
            role="candidate",
            content=cleaned,
            theme=self.orchestration.active_theme,
            context_id=self.orchestration.active_context_id,
        )
        self.recent_dialogue_window.append(record)
        if len(self.recent_dialogue_window) > 6:
            self.recent_dialogue_window = self.recent_dialogue_window[-6:]

        # Update active sub-memory if present
        active_id = self.orchestration.active_context_id
        if active_id and active_id in self.sub_memories:
            self.sub_memories[active_id].record_turn(role="candidate", content=cleaned)
            self.orchestration.turns_in_active_context += 1

        self.updated_at = datetime.now(timezone.utc)
        return turn

    def add_interviewer_question(
        self,
        question: str,
        turn_type: Literal[
            "resume_claim",
            "github_project",
            "skill_anchored",
            "role_scenario",
            "follow_up",
            "context_switch",
            "theme_switch",
            "closing",
        ],
        source: Optional[Literal["resume", "github", "jd"]] = None,
        source_ref: Optional[str] = None,
        reasoning_note: Optional[str] = None,
        rubric_dimension: Optional[str] = None,
        theme: Optional[Literal["PROFILE", "JD"]] = None,
    ) -> TranscriptTurn:
        """Appends interviewer's question to transcript and updates hierarchical memory."""
        self.turn_count += 1
        cleaned_question = question.strip()
        assigned_theme = theme or self.orchestration.active_theme
        meta = TurnMeta(
            source=source,
            source_ref=source_ref,
            turn_type=turn_type,
            reasoning_note=reasoning_note,
            theme=assigned_theme,
        )
        turn = TranscriptTurn(
            role="interviewer",
            content=cleaned_question,
            turn_index=self.turn_count,
            timestamp=datetime.now(timezone.utc),
            meta=meta,
        )
        self.transcript.append(turn)

        # Update sliding window
        record = TurnRecord(
            turn_index=self.turn_count,
            role="interviewer",
            content=cleaned_question,
            theme=self.orchestration.active_theme,
            context_id=self.orchestration.active_context_id,
            rubric_dimension=rubric_dimension,
        )
        self.recent_dialogue_window.append(record)
        if len(self.recent_dialogue_window) > 6:
            self.recent_dialogue_window = self.recent_dialogue_window[-6:]

        # Update active sub-memory if present
        active_id = self.orchestration.active_context_id
        if active_id and active_id in self.sub_memories:
            self.sub_memories[active_id].record_turn(
                role="interviewer",
                content=cleaned_question,
                rubric_dimension=rubric_dimension,
            )

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
            if source_ref not in self.globally_covered_topics:
                self.globally_covered_topics.append(source_ref)

        if turn_type == "closing":
            self.status = "completed"

        self.updated_at = datetime.now(timezone.utc)
        return turn

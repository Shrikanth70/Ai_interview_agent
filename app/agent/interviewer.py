import logging
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, field_validator

from app.agent.grounding import (
    extract_deterministic_fallback_target,
    is_source_ref_grounded,
)
from app.config import settings
from app.llm.client import LLMClient
from app.llm.prompts import (
    FEW_SHOT_EXAMPLES,
    MASTER_SYSTEM_PROMPT,
    calculate_source_nudge,
    format_covered_refs,
    format_dossier,
)
from app.session.state import SessionState

logger = logging.getLogger(__name__)


class InterviewerTurnOutput(BaseModel):
    """Structured response model generated on every interviewer turn."""

    question: str = Field(
        ...,
        description="The exact conversational question to ask the candidate.",
    )
    turn_type: Literal[
        "resume_claim",
        "github_project",
        "skill_anchored",
        "follow_up",
        "context_switch",
        "closing",
    ] = Field(
        ...,
        description="Intent of the turn.",
    )
    source: Optional[Literal["resume", "github"]] = Field(
        default="resume",
        description="Knowledge source grounding this question.",
    )
    source_ref: Optional[str] = Field(
        default="General Claim",
        description="Specific pointer to the claim, metric, or repository component.",
    )
    reasoning_note: Optional[str] = Field(
        default="",
        description="Internal rationale for this question or pivot choice.",
    )

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

    @field_validator("source_ref", mode="before")
    @classmethod
    def normalize_source_ref(cls, v: Any) -> str:
        if not v or not isinstance(v, str):
            return "General Claim"
        return str(v).strip()

    @field_validator("reasoning_note", mode="before")
    @classmethod
    def normalize_reasoning_note(cls, v: Any) -> str:
        if not v or not isinstance(v, str):
            return ""
        return str(v).strip()


class InterviewerAgent:
    """Core state machine coordinator that manages conversation turns, context assembly, and LLM calls."""

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self._custom_llm_client = llm_client

    def _generate_deterministic_fallback(
        self, state: SessionState, is_opening: bool
    ) -> InterviewerTurnOutput:
        """Generates a deterministic, verifiably grounded fallback question from the resume."""
        target, ref = extract_deterministic_fallback_target(
            state.resume_text,
            covered_refs=state.covered_refs,
        )
        if is_opening:
            question = (
                f"Welcome! Looking over your experience and background, you highlighted your work with {target}. "
                f"Walk me through a challenging technical problem you solved involving {target} and the primary architectural trade-offs you navigated."
            )
            turn_type = "resume_claim" if len(target.split()) > 4 else "skill_anchored"
        else:
            question = (
                f"Turning to another aspect of your background: can you tell me about your experience with {target} "
                f"and walk me through a concrete system where you applied it?"
            )
            turn_type = "skill_anchored" if len(target.split()) <= 4 else "resume_claim"

        return InterviewerTurnOutput(
            question=question,
            turn_type=turn_type,
            source="resume",
            source_ref=ref,
            reasoning_note="Deterministic app-layer fallback generated after LLM grounding validation failed twice.",
        )

    def _build_conversation_messages(
        self, state: SessionState
    ) -> List[Dict[str, str]]:
        """Assembles the complete OpenAI-compatible prompt payload."""
        messages: List[Dict[str, str]] = []

        # 1. System Prompt
        system_content = [MASTER_SYSTEM_PROMPT]
        if FEW_SHOT_EXAMPLES:
            system_content.append("\n--- FEW-SHOT EXAMPLES (For Calibration) ---")
            for idx, shot in enumerate(FEW_SHOT_EXAMPLES, 1):
                system_content.append(f"Example {idx}:\n{shot}")
        messages.append({"role": "system", "content": "\n".join(system_content)})

        # 2. Candidate Dossier (Full Source Material)
        dossier_text = format_dossier(state.resume_text, state.github_summary)
        covered_text = format_covered_refs(
            [ref.model_dump() for ref in state.covered_refs]
        )

        dossier_message = (
            f"{dossier_text}\n\n"
            f"--- [PREVIOUSLY COVERED REFERENCES (DO NOT REPEAT)] ---\n"
            f"{covered_text}\n"
        )
        messages.append({"role": "user", "content": dossier_message})

        # 3. Conversation History
        # We present prior turns as conversational dialogue
        if state.transcript:
            for turn in state.transcript:
                if turn.role == "interviewer":
                    as_json = {
                        "question": turn.content,
                        "turn_type": turn.meta.turn_type if turn.meta else "resume_claim",
                        "source": turn.meta.source if turn.meta else "resume",
                        "source_ref": turn.meta.source_ref if turn.meta else "general",
                        "reasoning_note": turn.meta.reasoning_note if turn.meta else "",
                    }
                    messages.append({
                        "role": "assistant",
                        "content": str(as_json),
                    })
                elif turn.role == "candidate":
                    messages.append({
                        "role": "user",
                        "content": f"[Candidate Answer]: {turn.content}",
                    })

        # 4. Final Instruction for the upcoming turn
        instructions = []
        is_closing = state.turn_count >= settings.MAX_SESSION_TURNS - 1
        if is_closing:
            instructions.append(
                "MANDATE: The interview session has reached its maximum allocated turns. "
                "Conclude the interview gracefully with a closing turn (turn_type='closing'). "
                "Thank the candidate for discussing their background and invite any questions."
            )
        else:
            # Check source nudge
            transcript_dict = [t.model_dump() for t in state.transcript]
            nudge = calculate_source_nudge(transcript_dict, max_consecutive=3)
            if nudge:
                instructions.append(nudge)

            if not state.transcript:
                instructions.append(
                    "You are generating the OPENING question (Turn 1).\n"
                    "MANDATORY OPENING GREETING CONTRACT:\n"
                    "Start the interview with a polite, professional welcome note that frames the technical inquiry around one real skill, project, or claim found in their uploaded resume.\n"
                    "Required pattern: 'Welcome! Looking over your experience and background, you highlighted [insert one real project, skill, or achievement directly from their uploaded resume]. [Walk me through / Can you walk me through (concrete technical inquiry probing that project or skill)]?'\n"
                    "GROUNDING MANDATE: The project, skill, or metric referenced MUST come 100% from the uploaded document in the CANDIDATE DOSSIER above. Never use made-up or template examples.\n"
                    "ORDERING MANDATE: Turn 1 MUST have source='resume'. Do not ask about GitHub projects on Turn 1.\n"
                    "1-TO-1 CONSISTENCY: 'source_ref' MUST match the EXACT project or claim targeted in your question.\n"
                    "DOMAIN RELEVANCE: Ask only about technical concepts that genuinely belong to the targeted project."
                )
            else:
                instructions.append(
                    "DECIDE_NEXT ANTI-CHEATING & UNPREDICTABLE QUESTIONING MANDATE:\n"
                    "1. STOP CHEATING & ELIMINATE REPEATING PATTERNS: Never follow a predictable formula like "
                    "'resume + follow-up -> github + follow-up -> skill + follow-up'. Candidates anticipate this cadence. "
                    "Questioning must be random, non-linear, and varied across sources and projects.\n"
                    "2. FOLLOW-UPS CONDITIONAL ON ANSWER POTENTIAL ONLY: Never automatically ask a follow-up after every question. "
                    "Evaluate the candidate's last response:\n"
                    "   - IF THOROUGH & SUBSTANTIATED: DO NOT follow up! Acknowledge briefly and immediately pivot to an entirely "
                    "different claim, GitHub repo, or skill anchor to test if depth holds across their entire profile.\n"
                    "   - IF VAGUE, SHALLOW, EVASIVE, OR TEXTBOOK BUZZWORDS: ONLY THEN use turn_type='follow_up' to drill into "
                    "concrete architecture, trade-offs, code internals, or failure modes.\n"
                    "3. SYMMETRICAL APPLICATION: Follow-ups are equally available for resume claims, GitHub repositories, and skill "
                    "anchors, but strictly triggered by answer quality rather than source type.\n"
                    "4. RANDOM JUMPS & SKILL ANCHORS: You may jump from resume directly to GitHub with no follow-up, ask two consecutive "
                    "resume questions on distinct projects, or suddenly probe a skill claim (turn_type='skill_anchored') out of the blue."
                )

        instructions.append(
            "STRICT GROUNDING & 1-TO-1 ALIGNMENT CONTRACT:\n"
            "- Ground your question 100% in the real text of the CANDIDATE DOSSIER above.\n"
            "- The 'source_ref' MUST be identical to the project or claim asked in 'question'. Never cite one project in source_ref while asking about another!\n"
            "- Ask only about technologies that belong to the targeted project.\n"
            "- Produce ONLY valid JSON with keys: question, turn_type, source, source_ref, reasoning_note."
        )

        messages.append({
            "role": "user",
            "content": "\n\n".join(instructions),
        })

        return messages

    async def execute_turn(
        self, state: SessionState, candidate_answer: Optional[str] = None
    ) -> InterviewerTurnOutput:
        """Executes a single conversational cycle in the state machine with code-level grounding validation."""
        if state.status == "completed":
            raise ValueError(
                f"Session '{state.session_id}' is already completed. Cannot generate new turns."
            )

        # State: LISTEN (Ingest candidate's answer if provided)
        if candidate_answer is not None:
            clean_answer = candidate_answer.strip()
            if not clean_answer:
                raise ValueError("Candidate answer cannot be empty or whitespace only.")
            state.add_candidate_answer(clean_answer)

        # State: SELECT_FOCUS & ASK (Build context, query LLM, validate output)
        messages = self._build_conversation_messages(state)

        # Resolve LLM client (custom or per-session provider/model)
        client = self._custom_llm_client or LLMClient(
            provider=state.llm_provider,
            model=state.model_name,
        )

        # Generate turn from configured LLM
        raw_response = await client.generate_turn(messages)
        turn_output = InterviewerTurnOutput.model_validate(raw_response)

        # Code-Level Grounding Validation Layer
        is_opening = not state.transcript

        # Ordering Rule: Turn 1 must always be sourced from the resume
        ordering_violated = is_opening and turn_output.source != "resume"

        grounded, reason = is_source_ref_grounded(
            source_ref=turn_output.source_ref or "",
            source=turn_output.source or "resume",
            turn_type=turn_output.turn_type,
            resume_text=state.resume_text,
            github_summary=state.github_summary,
            transcript=state.transcript,
        )

        if ordering_violated or not grounded:
            fail_reason = "Turn 1 source must be 'resume'" if ordering_violated else reason
            logger.warning(
                "Grounding validation FAILED on turn %s (attempt 1). Reason: %s. Question: '%s' | source_ref: '%s'. Retrying once with explicit correction...",
                state.turn_count + 1,
                fail_reason,
                turn_output.question,
                turn_output.source_ref,
            )

            # Retry once with explicit correction message
            correction_instruction = (
                f"CRITICAL GROUNDING ERROR: Your previous question referenced '{turn_output.source_ref}', "
                f"which was rejected because: {fail_reason}. "
                "You must generate a new question using ONLY content verifiably present in the source material above. "
                + ("REMINDER: The opening turn (Turn 1) MUST be sourced from the resume." if is_opening else "")
            )
            retry_messages = list(messages) + [
                {"role": "user", "content": correction_instruction}
            ]

            try:
                retry_raw = await client.generate_turn(retry_messages)
                retry_turn = InterviewerTurnOutput.model_validate(retry_raw)

                retry_ordering_violated = is_opening and retry_turn.source != "resume"
                retry_grounded, retry_reason = is_source_ref_grounded(
                    source_ref=retry_turn.source_ref or "",
                    source=retry_turn.source or "resume",
                    turn_type=retry_turn.turn_type,
                    resume_text=state.resume_text,
                    github_summary=state.github_summary,
                    transcript=state.transcript,
                )

                if not retry_ordering_violated and retry_grounded:
                    logger.info(
                        "Grounding validation SUCCEEDED on retry for turn %s. Question: '%s' | source_ref: '%s'",
                        state.turn_count + 1,
                        retry_turn.question,
                        retry_turn.source_ref,
                    )
                    turn_output = retry_turn
                else:
                    retry_fail_reason = "Turn 1 source must be 'resume'" if retry_ordering_violated else retry_reason
                    logger.error(
                        "Grounding validation FAILED on retry (attempt 2) for turn %s. Reason: %s. Falling back to deterministic app-layer question.",
                        state.turn_count + 1,
                        retry_fail_reason,
                    )
                    turn_output = self._generate_deterministic_fallback(state, is_opening)
            except Exception as err:
                logger.error("Error during grounding retry generation: %s. Falling back to deterministic question.", err)
                turn_output = self._generate_deterministic_fallback(state, is_opening)

        # State: Record validated turn in state machine transcript and covered_refs
        state.add_interviewer_question(
            question=turn_output.question,
            turn_type=turn_output.turn_type,
            source=turn_output.source,
            source_ref=turn_output.source_ref,
            reasoning_note=turn_output.reasoning_note,
        )

        return turn_output


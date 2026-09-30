import asyncio
import logging
import random
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, field_validator

from app.agent.grounding import (
    extract_candidate_anchors,
    extract_deterministic_fallback_target,
    is_source_ref_grounded,
)
from app.agent.theme_fetcher import ThemeMemoryFetchTool
from app.config import settings
from app.llm.client import LLMClient
from app.llm.prompts import (
    FEW_SHOT_EXAMPLES,
    MASTER_SYSTEM_PROMPT,
    calculate_source_nudge,
    format_bridge_turn_prompt,
    format_covered_refs,
    format_dossier,
    format_scoped_turn_prompt,
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
        "role_scenario",
        "follow_up",
        "context_switch",
        "theme_switch",
        "closing",
    ] = Field(
        ...,
        description="Intent of the turn.",
    )
    theme: Optional[Literal["PROFILE", "JD"]] = Field(
        default=None,
        description="Active theme of the question (PROFILE or JD).",
    )
    source: Optional[Literal["resume", "github", "jd"]] = Field(
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
        self.theme_fetcher = ThemeMemoryFetchTool()

    def _generate_deterministic_fallback(
        self, state: SessionState, is_opening: bool
    ) -> InterviewerTurnOutput:
        """Generates a deterministic, verifiably grounded fallback question from GitHub or resume."""
        interviewer_turns = [
            t for t in state.transcript if t.role == "interviewer" and t.meta
        ]
        sources = [
            t.meta.source for t in interviewer_turns if t.meta and t.meta.source
        ]
        turn_types = [
            t.meta.turn_type for t in interviewer_turns if t.meta and t.meta.turn_type
        ]
        last_turn_type = turn_types[-1] if turn_types else ""
        github_turns_count = sum(1 for s in sources if s == "github")
        skill_turns_count = sum(1 for tt in turn_types if tt == "skill_anchored")

        has_github_repos = bool(
            state.github_summary
            and isinstance(state.github_summary, dict)
            and state.github_summary.get("repos")
        )

        # 0. JD Theme Fallback
        if state.orchestration.active_theme == "JD" and state.orchestration.active_context_id:
            active_sub = state.sub_memories.get(state.orchestration.active_context_id)
            if active_sub and active_sub.source_slice:
                title = active_sub.source_slice.get("title", active_sub.source_ref)
                prob = active_sub.source_slice.get("problem_statement", "")
                if is_opening:
                    question = (
                        f"Welcome! In this role, we frequently design systems tackling '{title}'. "
                        f"{prob} Walk me through how you would architect a solution from scratch and what primary trade-offs you would design around."
                    )
                else:
                    question = (
                        f"Turning to our role scenario '{title}': {prob} "
                        f"Walk me through your methodology for designing this system and how you mitigate failure modes."
                    )
                return InterviewerTurnOutput(
                    question=question,
                    turn_type="role_scenario" if is_opening else ("theme_switch" if state.orchestration.theme_switch_pending else "follow_up"),
                    source="jd",
                    source_ref=active_sub.source_ref,
                    reasoning_note="Deterministic app-layer fallback generated for JD role scenario.",
                    theme="JD",
                )

        # 1. If GitHub repositories exist and have never been explored after 2+ turns, fall back to GitHub
        if not is_opening and has_github_repos and github_turns_count == 0 and len(interviewer_turns) >= 2:
            covered_github_refs = {
                c.ref.lower().strip() for c in state.covered_refs if c.source == "github"
            }
            repos_dict = state.github_summary.get("repos", {})
            available_repo = None
            for repo_name, repo_data in repos_dict.items():
                if repo_name.lower().strip() not in covered_github_refs:
                    available_repo = (repo_name, repo_data)
                    break

            if available_repo:
                repo_name, repo_data = available_repo
                description = repo_data.get("description", "") if isinstance(repo_data, dict) else ""
                language = repo_data.get("language", "") if isinstance(repo_data, dict) else ""
                context_clause = f" involving {language}" if language else ""

                if description:
                    question = (
                        f"Looking at your public GitHub repositories, I noticed your project '{repo_name}', "
                        f"described as '{description}'. Walk me through the core system architecture{context_clause} "
                        f"and the primary concurrency or design trade-offs you navigated."
                    )
                else:
                    question = (
                        f"Looking at your public GitHub repositories, I noticed your project '{repo_name}'. "
                        f"Walk me through the core system architecture{context_clause} "
                        f"and the primary concurrency or design trade-offs you navigated."
                    )

                return InterviewerTurnOutput(
                    question=question,
                    turn_type="github_project",
                    source="github",
                    source_ref=repo_name,
                    reasoning_note="Deterministic app-layer fallback generated after LLM grounding validation failed twice.",
                )

        # 2. Resume Fallback (Ensure no consecutive skill questions, and maximum 1 skill question per session)
        force_bullet = (last_turn_type == "skill_anchored" or skill_turns_count >= 1)
        target, ref = extract_deterministic_fallback_target(
            state.resume_text,
            covered_refs=state.covered_refs,
            force_bullet=force_bullet,
        )
        is_skill = ref.startswith("Skills Section:")

        if is_opening:
            if not is_skill:
                lower_first = target[:1].lower() + target[1:] if not target.isupper() else target
                question = (
                    f"Welcome! Looking over your experience and background, you highlighted that you {lower_first}. "
                    f"Walk me through the system architecture you built and the primary technical trade-offs you navigated."
                )
                turn_type = "resume_claim"
            else:
                question = (
                    f"Welcome! Looking over your experience and background, you highlighted your work with {target}. "
                    f"Walk me through a challenging technical problem you solved involving {target} and the primary architectural trade-offs you navigated."
                )
                turn_type = "skill_anchored"
        else:
            if not is_skill:
                lower_first = target[:1].lower() + target[1:] if not target.isupper() else target
                question = (
                    f"Turning to your work where you {lower_first}: walk me through the system architecture "
                    f"and the primary operational or scaling trade-offs you navigated."
                )
                turn_type = "resume_claim"
            else:
                question = (
                    f"Turning to your experience with {target}: walk me through the system architecture where you applied it "
                    f"and the primary operational or scaling trade-offs you navigated."
                )
                turn_type = "skill_anchored"

        return InterviewerTurnOutput(
            question=question,
            turn_type=turn_type,
            source="resume",
            source_ref=ref,
            reasoning_note="Deterministic app-layer fallback generated after LLM grounding validation failed twice.",
        )

    def _build_conversation_messages(
        self,
        state: SessionState,
        bridge_data: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, str]]:
        """Assembles the complete OpenAI-compatible prompt payload."""
        messages: List[Dict[str, str]] = []

        # 1. System Prompt
        system_content = [MASTER_SYSTEM_PROMPT]
        if FEW_SHOT_EXAMPLES:
            system_content.append("\n--- FEW-SHOT EXAMPLES (For Calibration) ---")
            shot_limit = 1 if state.llm_provider == "ollama" else 2
            for idx, shot in enumerate(FEW_SHOT_EXAMPLES[:shot_limit], 1):
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
        is_closing = (
            state.budget.is_closing_time
            or state.turn_count >= state.budget.max_turns - 1
            or state.turn_count >= settings.MAX_SESSION_TURNS - 1
        )
        if is_closing:
            instructions.append(
                "MANDATE: The interview session has reached its maximum allocated turns. "
                "Conclude the interview gracefully with a closing turn (turn_type='closing'). "
                "Thank the candidate for discussing their background and invite any questions."
            )
        else:
            # Check source nudge
            has_github_repos = bool(
                state.github_summary
                and isinstance(state.github_summary, dict)
                and state.github_summary.get("repos")
            )
            transcript_dict = [t.model_dump() for t in state.transcript]
            nudge = calculate_source_nudge(
                transcript_dict,
                max_consecutive=3,
                has_github=has_github_repos,
                github_summary=state.github_summary,
            )
            if nudge and not bridge_data:
                instructions.append(nudge)

            if bridge_data:
                target_ctx = bridge_data.get("target_context")
                target_ref = (
                    getattr(target_ctx, "source_ref", "Upcoming Scenario")
                    if target_ctx
                    else "Upcoming Scenario"
                )
                target_theme = bridge_data.get("target_theme", "JD")
                instructions.append(
                    format_bridge_turn_prompt(
                        anchor_ref=bridge_data.get("anchor_source_ref", "Previous Project"),
                        anchor_slice=bridge_data.get("anchor_slice", {}),
                        target_theme=target_theme,
                        target_ref=target_ref,
                        target_slice=bridge_data.get("target_slice", {}),
                    )
                    + f"\nCRITICAL THEME SWITCH MANDATE: Set turn_type='theme_switch'. Set source='{target_theme.lower() if target_theme == 'JD' else 'resume'}'. Set source_ref='{target_ref}'."
                )
            elif state.orchestration.active_context_id:
                active_sub = state.sub_memories.get(state.orchestration.active_context_id)
                if active_sub:
                    next_dim = (
                        active_sub.pending_dimensions[0]
                        if active_sub.pending_dimensions
                        else "methodology_depth"
                    )
                    instructions.append(
                        format_scoped_turn_prompt(
                            theme=active_sub.theme,
                            source_ref=active_sub.source_ref,
                            source_slice=active_sub.source_slice,
                            next_dimension=next_dim,
                            anti_duplication=state.globally_covered_topics,
                        )
                    )

            if not state.transcript:
                if state.orchestration.active_theme == "JD":
                    active_sub = state.sub_memories.get(state.orchestration.active_context_id)
                    scenario_title = active_sub.source_slice.get("title", active_sub.source_ref) if active_sub and active_sub.source_slice else "Role System Design Scenario"
                    scenario_problem = active_sub.source_slice.get("problem_statement", "") if active_sub and active_sub.source_slice else ""
                    instructions.append(
                        "You are generating the OPENING question (Turn 1) for THEME: JD.\n"
                        "MANDATORY OPENING GREETING CONTRACT (ROLE SCENARIO):\n"
                        "Start the interview with a polite, professional welcome note framing the technical challenge around the role scenario.\n"
                        f"Target Scenario: '{scenario_title}'\n"
                        f"Problem Statement: {scenario_problem}\n"
                        "Required pattern: 'Welcome! In this role, we frequently design systems tackling [Scenario Title]: [Problem Statement]. Walk me through how you would architect a solution from scratch and what primary trade-offs you would design around.'\n"
                        f"MANDATORY SCHEMA: Set turn_type='role_scenario', source='jd', source_ref='{scenario_title}'."
                    )
                else:
                    anchors = extract_candidate_anchors(state.resume_text)
                    anchor_hint = ""
                    if anchors:
                        formatted_anchors = "\n".join(f"  - {a}" for a in anchors)
                        anchor_hint = (
                            f"VERIFIED CANDIDATE ANCHOR TOPICS FROM RESUME (Focus your opening question on one of these):\n"
                            f"{formatted_anchors}\n\n"
                        )

                    instructions.append(
                        "You are generating the OPENING question (Turn 1) for THEME: PROFILE.\n"
                        "MANDATORY OPENING GREETING CONTRACT:\n"
                        "Start the interview with a polite, professional welcome note that frames the technical inquiry around one real skill, project, or claim found in their uploaded resume or public GitHub profile.\n"
                        "Required pattern: 'Welcome! Looking over your experience and background, you highlighted [insert one real project, skill, or achievement directly from their uploaded resume or public repository]. [Walk me through / Can you walk me through (concrete technical inquiry probing that project or skill)]?'\n\n"
                        f"{anchor_hint}"
                        "GROUNDING MANDATE: The project, skill, company, or metric referenced MUST come 100% verbatim from the uploaded document in the CANDIDATE DOSSIER above. Never invent metrics or copy entities from the calibration examples.\n"
                        "DO NOT COPY CALIBRATION EXAMPLES: Under no circumstances should you cite TelemetryRouter, PostgreSQL WAL, or any entity from the calibration examples unless it appears verbatim in the candidate's uploaded resume!\n"
                        "1-TO-1 CONSISTENCY: 'source_ref' MUST match the EXACT project or claim targeted in your question.\n"
                        "DOMAIN RELEVANCE: Ask only about technical concepts that genuinely belong to the targeted project."
                    )
            else:
                instructions.append(
                    "DECIDE_NEXT QUESTIONING MANDATE:\n"
                    "1. THEMATIC DEEP-DIVE: Drill down into the active sub-memory along the rubric dimensions (clarity of framing -> methodology/wiring -> trade-offs & edge cases).\n"
                    "2. FOLLOW-UP DECISION (DRIVEN BY KEY POINTS): Never follow up mechanically, but DO ask a follow-up (turn_type='follow_up') when the candidate's last answer presents a concrete key point:\n"
                    "   - A named technology, framework, algorithm, or library explicitly mentioned in their answer that has not been deeply probed.\n"
                    "   - A quantifiable metric or scale claim (e.g. 'improved accuracy by 25%', 'reduced latency to 40ms', '20+ concurrent users').\n"
                    "   - An architectural trade-off or design decision mentioned without deep justification.\n"
                    "   - An evasive, vague, or textbook recitation that lacks hands-on code specifics.\n"
                    "   In any of these cases, use turn_type='follow_up' to probe that exact detail.\n"
                    "   STRICT FOLLOW-UP MANDATE: You must NEVER invent or attribute technologies to the candidate that they did not explicitly mention! If the candidate discussed Redis and Lua scripts, follow up on Redis or Lua; NEVER claim they mentioned Go, Goroutines, or other technologies not in their text.\n"
                    "3. PROGRESSION DISCIPLINE: Stay anchored in the active theme context until a theme switch is initiated."
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
        self,
        state: SessionState,
        candidate_answer: Optional[str] = None,
        jev_signal: Optional[Literal["FOLLOW_UP", "SWITCH_CONTEXT"]] = None,
        starting_theme: Optional[Literal["PROFILE", "JD"]] = None,
    ) -> InterviewerTurnOutput:
        """Executes a single conversational cycle in the state machine with code-level grounding validation."""
        if state.status == "completed":
            raise ValueError(
                f"Session '{state.session_id}' is already completed. Cannot generate new turns."
            )

        # Budget & Turn Limit Guardrail (25-minute limit)
        is_closing = (
            state.budget.is_closing_time
            or state.turn_count >= state.budget.max_turns - 1
            or state.turn_count >= settings.MAX_SESSION_TURNS - 1
        )

        if is_closing:
            closing_question = (
                "Thank you so much for sharing your technical background, architectural decisions, "
                "and problem-solving trade-offs with me today. That concludes our interview! "
                "Do you have any questions for me before we wrap up?"
            )
            turn_output = InterviewerTurnOutput(
                question=closing_question,
                turn_type="closing",
                source="resume",
                source_ref="Closing",
                reasoning_note="Session budget or turn limit reached. Concluding interview gracefully.",
            )
            state.add_interviewer_question(
                question=turn_output.question,
                turn_type="closing",
                source="resume",
                source_ref="Closing",
                reasoning_note=turn_output.reasoning_note,
            )
            return turn_output

        # Context Initialization on Turn 1
        is_opening = not state.transcript
        if is_opening and not state.orchestration.active_context_id:
            chosen_theme = starting_theme or "PROFILE"
            sub = self.theme_fetcher.initialize_context(
                theme=chosen_theme,
                resume_text=state.resume_text,
                github_summary=state.github_summary,
                jd_scenarios=state.jd_scenarios,
            )
            state.sub_memories[sub.context_id] = sub
            state.orchestration.active_theme = chosen_theme
            state.orchestration.active_context_id = sub.context_id

        # State: LISTEN (Ingest candidate's answer if provided)
        if candidate_answer is not None:
            clean_answer = candidate_answer.strip()
            if not clean_answer:
                raise ValueError("Candidate answer cannot be empty or whitespace only.")
            state.add_candidate_answer(clean_answer)

        # Process JEV signal if provided or evaluate automatically
        effective_signal = jev_signal
        if effective_signal is None and not is_opening and not is_closing:
            # Auto JEV evaluation: after 2 turns in active context, trigger a theme switch (PROFILE <-> JD)
            if state.orchestration.turns_in_active_context >= 2:
                effective_signal = "SWITCH_CONTEXT"
            else:
                effective_signal = "FOLLOW_UP"

        bridge_data = None
        if effective_signal:
            state.orchestration.last_jev_signal = effective_signal
            if effective_signal == "SWITCH_CONTEXT":
                target_theme = "JD" if state.orchestration.active_theme == "PROFILE" else "PROFILE"
                bridge_data = self.theme_fetcher.fetch_bridge_context(
                    state,
                    target_theme=target_theme,
                    jd_scenarios=state.jd_scenarios,
                )
                target_sub = bridge_data["target_context"]
                state.sub_memories[target_sub.context_id] = target_sub
                state.orchestration.active_theme = target_theme
                state.orchestration.active_context_id = target_sub.context_id
                state.orchestration.theme_switch_pending = True
                state.orchestration.turns_in_active_context = 0

        # State: SELECT_FOCUS & ASK (Build context, query LLM, validate output)
        messages = self._build_conversation_messages(state, bridge_data=bridge_data)

        # Resolve LLM client (custom or per-session provider/model)
        client = self._custom_llm_client or LLMClient(
            provider=state.llm_provider,
            model=state.model_name,
        )

        # Generate turn from configured LLM with timeout guardrail
        call_timeout = 20.0 if state.llm_provider == "ollama" else 25.0
        try:
            raw_response = await asyncio.wait_for(client.generate_turn(messages), timeout=call_timeout)
            turn_output = InterviewerTurnOutput.model_validate(raw_response)
        except Exception as llm_err:
            logger.warning(
                "LLM call failed or timed out (%s). Falling back to deterministic grounded question.",
                llm_err,
            )
            fallback_turn = self._generate_deterministic_fallback(state, is_opening=is_opening)
            state.add_interviewer_question(
                question=fallback_turn.question,
                turn_type=fallback_turn.turn_type,
                source=fallback_turn.source,
                source_ref=fallback_turn.source_ref,
                reasoning_note=fallback_turn.reasoning_note,
            )
            return fallback_turn

        # Code-Level Grounding Validation Layer
        ordering_violated = (
            is_opening
            and state.orchestration.active_theme == "PROFILE"
            and turn_output.source not in ["resume", "github"]
        ) or (
            is_opening
            and state.orchestration.active_theme == "JD"
            and turn_output.source != "jd"
        )

        grounded, reason = is_source_ref_grounded(
            source_ref=turn_output.source_ref or "",
            source=turn_output.source or "resume",
            turn_type=turn_output.turn_type,
            resume_text=state.resume_text,
            github_summary=state.github_summary,
            transcript=state.transcript,
            question=turn_output.question,
        )

        if ordering_violated or not grounded:
            fail_reason = "Turn 1 source must be 'resume' or 'github'" if ordering_violated else reason
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
                + ("REMINDER: The opening turn (Turn 1) MUST be sourced from the resume or a public github repo." if is_opening else "")
            )
            # If the rejected turn targeted GitHub or failed on a repository reference, provide the exact valid repository list
            if (turn_output.source == "github" or "github" in str(fail_reason).lower()) and state.github_summary.get("repos"):
                valid_repos = list(state.github_summary["repos"].keys())
                correction_instruction += (
                    f"\nSTRICT GITHUB CONSTRAINT: The candidate's ONLY public repositories are: {valid_repos}. "
                    f"If asking about GitHub (source='github'), 'source_ref' MUST match one of these exact repository names: {valid_repos}. "
                    f"DO NOT invent repository names like '<tech>-scripts' or use generic technology names like 'Redis' as the repository name."
                )
            retry_messages = list(messages) + [
                {"role": "user", "content": correction_instruction}
            ]

            retry_timeout = 10.0 if state.llm_provider == "ollama" else 15.0
            try:
                retry_raw = await asyncio.wait_for(client.generate_turn(retry_messages), timeout=retry_timeout)
                retry_turn = InterviewerTurnOutput.model_validate(retry_raw)

                retry_ordering_violated = (
                    is_opening
                    and state.orchestration.active_theme == "PROFILE"
                    and retry_turn.source not in ["resume", "github"]
                ) or (
                    is_opening
                    and state.orchestration.active_theme == "JD"
                    and retry_turn.source != "jd"
                )
                retry_grounded, retry_reason = is_source_ref_grounded(
                    source_ref=retry_turn.source_ref or "",
                    source=retry_turn.source or "resume",
                    turn_type=retry_turn.turn_type,
                    resume_text=state.resume_text,
                    github_summary=state.github_summary,
                    transcript=state.transcript,
                    question=retry_turn.question,
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
                    retry_fail_reason = "Turn 1 source must be 'resume' or 'github'" if retry_ordering_violated else retry_reason
                    logger.error(
                        "Grounding validation FAILED on retry (attempt 2) for turn %s. Reason: %s. Falling back to deterministic app-layer question.",
                        state.turn_count + 1,
                        retry_fail_reason,
                    )
                    turn_output = self._generate_deterministic_fallback(state, is_opening)
            except Exception as err:
                logger.error("Error during grounding retry generation: %s. Falling back to deterministic question.", err)
                turn_output = self._generate_deterministic_fallback(state, is_opening)

        # State: Record validated turn in state machine transcript and sub-memory
        if bridge_data and turn_output.turn_type in ("resume_claim", "github_project"):
            turn_output.turn_type = "theme_switch"

        turn_output.theme = state.orchestration.active_theme

        active_sub_id = state.orchestration.active_context_id
        target_dim = None
        if active_sub_id and active_sub_id in state.sub_memories:
            active_sub = state.sub_memories[active_sub_id]
            if active_sub.pending_dimensions:
                target_dim = active_sub.pending_dimensions[0]

        state.add_interviewer_question(
            question=turn_output.question,
            turn_type=turn_output.turn_type,
            source=turn_output.source,
            source_ref=turn_output.source_ref,
            reasoning_note=turn_output.reasoning_note,
            rubric_dimension=target_dim,
            theme=state.orchestration.active_theme,
        )

        return turn_output



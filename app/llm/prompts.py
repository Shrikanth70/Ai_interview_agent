"""Prompts and prompt assembly for the Interviewer Agent."""

import json
from typing import Any, Dict, List, Optional


MASTER_SYSTEM_PROMPT = """You are an expert technical interviewer conducting an in-depth, rigorous, and realistic technical interview for an engineering candidate.

CRITICAL ANTI-HALLUCINATION MANDATE (NON-NEGOTIABLE):
- You must NEVER reference a skill, project, technology, company, or claim that is not verbatim (or a very close paraphrase of) something present in the `resume_text` or `github_summary` provided in this context.
- You have NO knowledge of the candidate beyond what is given to you in this conversation.
- If you cannot find a valid resume/github detail to ask about, ask a simpler question anchored to whatever IS present, rather than inventing one.
- DO NOT invent projects, tools, metrics, or company names from external training knowledge!

You have access to the candidate's complete background from two distinct knowledge sources:
1. RESUME: Their official professional resume containing career history, accomplishments, skills, and claimed metrics.
2. GITHUB PORTFOLIO: Their public repositories, project descriptions, README excerpts, and primary programming languages.

ORDERING & GROUNDING RULES:
- TURN 1 OPENING MANDATE: The first question (Turn 1) MUST ALWAYS be sourced from the candidate's resume (turn_type='resume_claim' or 'skill_anchored', source='resume'). GitHub questions may only appear from Turn 2 onward.
- OPENING GREETING: Begin Turn 1 with a professional, polite welcome note:
  "Welcome! Looking over your experience and background, you highlighted [insert one real project, skill, or achievement directly from their uploaded resume]. [In-depth technical inquiry probing the architecture, bottlenecks, or trade-offs of that claim or skill]?"
  For all subsequent turns (Turn 2 onwards), transition naturally and do NOT repeat the welcome note.
- 1-TO-1 ALIGNMENT: The 'source_ref' MUST match the EXACT project or claim targeted in your 'question'. If you ask about "MovieBuddy", 'source_ref' MUST be "MovieBuddy". It is a critical error if 'question' and 'source_ref' reference different projects!
- DOMAIN RELEVANCE: Ask ONLY about technical concepts that genuinely belong to the targeted project.
- SPARSE RESUMES & FRESHERS: If a candidate's resume has limited experience or projects (e.g. a fresher with 1-2 projects, no formal work section), you must NEVER run out of resume material and hallucinate projects to fill turns. Instead, lean more heavily on GitHub content and skill-anchored questions (turn_type='skill_anchored'), or gracefully move toward closing the session early.
- NO FORCED CONNECTIONS: If a candidate's resume has no technical overlap with their GitHub repos, you must NOT fabricate a false connection. Switching with no stated narrative link is completely natural and encouraged.

YOUR CORE MISSION & ANTI-CHEATING MANDATE:
- Our primary objective is to STOP CHEATING and thoroughly verify hands-on technical competence.
- Candidates cheat or rely on AI generation when an interview has a predictable rhythm (such as: question -> follow-up -> question -> follow-up). You MUST eliminate any perceptible pattern.
- Questioning should be NON-LINEAR and RANDOM: jump dynamically across resume claims, GitHub repositories, and claimed skills. You can ask two resume claims in a row, jump straight from resume to GitHub with NO follow-up, or probe a skill anchor out of the blue.

FOLLOW-UPS ARE DRIVEN BY ANSWER KEY POINTS:
- Never follow up automatically, but DO ask a follow-up (turn_type='follow_up') whenever the candidate's response presents a key point worth probing:
  1. A named technology, framework, or tool mentioned that has not been deeply explored (e.g. LangGraph, FAISS, Socket.IO, Redis, Goroutines, WebSockets).
  2. A quantifiable claim or metric (e.g. 'improved by 25%', 'reduced latency to 40ms', '20+ concurrent users').
  3. An architectural trade-off or design decision mentioned without deep justification.
  4. A vague, evasive, or textbook answer that lacks hands-on code specifics.
- Symmetrical: Follow-ups apply equally after a resume question, a GitHub project question, or a skill-anchored question.
- Avoid over-drilling: Ask at most 1 or 2 follow-ups on the same project before pivoting to a new topic or the other source.
- When an answer has addressed all trade-offs and leaves no remaining key points, pivot immediately across sources (resume <-> github).

SOFT GUARDRAILS:
- Do not switch sources on every single turn for more than 2 consecutive turns (avoid whiplash), and never remain on one source for the entire interview session.
- If the candidate has public GitHub repositories, you MUST explore them during the interview session (do not stay on the resume alone).
- Never repeat a topic or claim that has already been explored in covered_refs.
- When the interview approaches its conclusion or turn limit, transition gracefully to a closing turn.

JSON OUTPUT CONTRACT:
You must respond with ONLY a single valid JSON object with the following exact keys:
{
  "question": "The question string spoken to the candidate. Be direct, natural, and technical. Avoid excessive praise, meta-commentary, or empty filler.",
  "turn_type": "resume_claim" | "github_project" | "skill_anchored" | "follow_up" | "context_switch" | "closing",
  "source": "resume" | "github",
  "source_ref": "Short, human-readable pointer to the specific claim, metric, skill, or repo being discussed. MUST match the question subject.",
  "reasoning_note": "A concise internal note explaining why you chose this question, pivot, or follow-up based on candidate answer potential (not shown to candidate)."
}
"""

FEW_SHOT_EXAMPLES: List[str] = [
    """Turn 1: Opening Turn (Grounded in a Specific Resume Claim with Welcome Greeting)
{
  "question": "Welcome! Looking over your experience and background, you highlighted optimizing an event pipeline with Apache Kafka to reduce latency from 450ms down to 40ms. Walk me through the bottlenecks you diagnosed in the old architecture and how you designed your partitioning strategy.",
  "turn_type": "resume_claim",
  "source": "resume",
  "source_ref": "Kafka event pipeline migration (450ms -> 40ms latency)",
  "reasoning_note": "Welcoming candidate and opening with a high-impact, metrics-grounded technical achievement from recent experience."
}""",
    """Turn 2: Answer-Driven Follow-Up (When Answer Lacks Depth or Sizing Specifics)
{
  "question": "You mentioned partitioning by tenant_id, but how did you handle large enterprise tenants that produce 100x the volume of standard tenants to prevent partition skew and hot spots?",
  "turn_type": "follow_up",
  "source": "resume",
  "source_ref": "prior_answer: Kafka partition key by tenant_id and hotspot mitigation",
  "reasoning_note": "Candidate gave a high-level answer; challenging the data skew failure mode of their chosen partition key."
}""",
    """Turn 3: Symmetrical Follow-Up on GitHub
{
  "question": "In Go, copy-on-write with raw pointers can lead to race conditions or unexpected memory bloat if the garbage collector gets overwhelmed during high write loads. How did you verify safety and benchmark GC pause times during snapshotting?",
  "turn_type": "follow_up",
  "source": "github",
  "source_ref": "prior_answer: Go pointer copy-on-write safety and GC pause times",
  "reasoning_note": "Symmetrically digging deeper on a GitHub answer: challenging the memory safety and GC implications of their described Go implementation."
}""",
    """Turn 4: Skill-Anchored Question
{
  "question": "You have 'eBPF / Kernel Tracing' listed in your technical skills section. Where have you actually applied eBPF in practice — was that in production diagnosing network bottlenecks, or in an experimental repository? Walk me through a concrete program you wrote or loaded.",
  "turn_type": "skill_anchored",
  "source": "resume",
  "source_ref": "Skills Section: eBPF / Kernel Tracing application challenge",
  "reasoning_note": "Testing veracity of a high-level skill claim; breaking binary source rhythm by challenging candidate to prove where the skill was applied across either source."
}""",
]


def format_dossier(resume_text: str, github_summary: Dict[str, Any]) -> str:
    """Formats the candidate's resume and GitHub portfolio into a clear, tagged dossier."""
    parts = [
        "================================================================================",
        "CANDIDATE DOSSIER: RESUME & GITHUB PORTFOLIO",
        "================================================================================",
        "",
        "--- [SOURCE 1: RESUME TEXT & SKILLS] ---",
        resume_text.strip(),
        "",
        "--- [SOURCE 2: GITHUB PROFILE & REPOSITORIES] ---",
    ]

    repos = github_summary.get("repos", {})
    if not repos:
        parts.append("No public repositories found or provided.")
    else:
        for name, repo_data in repos.items():
            parts.append(f"\nRepository: {name}")
            if repo_data.get("description"):
                parts.append(f"  Description: {repo_data['description']}")
            parts.append(f"  Primary Language: {repo_data.get('language', 'Unknown')}")
            parts.append(f"  Stars: {repo_data.get('stars', 0)}")
            topics = repo_data.get("topics", [])
            if topics:
                parts.append(f"  Topics: {', '.join(topics)}")
            readme = repo_data.get("readme_excerpt", "").strip()
            if readme:
                parts.append(f"  README excerpt:\n    {readme[:1200]}")

    parts.append("\n================================================================================")
    return "\n".join(parts)


def format_covered_refs(covered_refs: List[Dict[str, Any]]) -> str:
    """Formats the list of already covered references to prevent duplicate questions."""
    if not covered_refs:
        return "None yet (opening turn)."
    lines = []
    for ref in covered_refs:
        lines.append(f"- [Turn {ref.get('turn_index')}: {ref.get('source')}] {ref.get('ref')}")
    return "\n".join(lines)


def calculate_source_nudge(
    transcript: List[Dict[str, Any]],
    max_consecutive: int = 3,
    has_github: bool = True,
) -> Optional[str]:
    """Generates boundary guidance to ensure multi-source coverage and prevent monologues."""
    interviewer_turns = [
        t for t in transcript if t.get("role") == "interviewer" and t.get("meta")
    ]
    if not interviewer_turns:
        return None

    sources = [
        t["meta"].get("source") for t in interviewer_turns if t["meta"].get("source")
    ]
    turn_types = [
        t["meta"].get("turn_type") for t in interviewer_turns if t["meta"].get("turn_type")
    ]

    last_turn_type = turn_types[-1] if turn_types else ""
    github_turns_count = sum(1 for s in sources if s == "github")

    # If the candidate has GitHub repositories and we have reached turn 3+ with ZERO GitHub turns, mandate a GitHub pivot!
    if has_github and github_turns_count == 0 and len(interviewer_turns) >= 2:
        return (
            "MANDATORY GITHUB EXPLORATION MANDATE:\n"
            "You have spent multiple turns on the resume and have NOT yet asked about the candidate's GitHub portfolio. "
            "To verify public code and avoid a resume-only interview, your NEXT question MUST target one of the candidate's public repositories "
            "from [SOURCE 2: GITHUB PROFILE & REPOSITORIES] above.\n"
            "Requirements:\n"
            "- Set source='github'\n"
            "- Set turn_type='context_switch' or 'github_project'\n"
            "- Explicitly name the repository and inquire into its architecture, concurrency, or data structures."
        )

    # If the previous turn was already skill_anchored, do not repeat skill_anchored immediately
    if last_turn_type == "skill_anchored":
        return (
            "DIVERSITY MANDATE: You just asked a skill-anchored inquiry. Do NOT ask another skill-anchored question back-to-back. "
            "Either follow up on the candidate's response (turn_type='follow_up') or pivot to a concrete project or repository (turn_type='context_switch')."
        )

    # Anti-monologue: if stuck on a single source for >= max_consecutive turns
    if len(sources) >= max_consecutive:
        recent_sources = sources[-max_consecutive:]
        if len(set(recent_sources)) == 1:
            current_source = recent_sources[0]
            alt_source = "github" if current_source == "resume" and has_github else "resume"
            return (
                f"SOURCE ROTATION MANDATE: The last {max_consecutive} questions have all been sourced from {current_source}. "
                f"You MUST now pivot to an uncovered item from {alt_source} to test breadth across their background. "
                f"Set source='{alt_source}' and turn_type='context_switch'."
            )

    return None

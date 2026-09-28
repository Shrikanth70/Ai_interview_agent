"""Code-level grounding validation and anti-hallucination verification."""

import difflib
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

STOPWORDS = {
    "a", "an", "the", "and", "or", "in", "on", "at", "to", "for", "with",
    "from", "by", "of", "about", "your", "my", "our", "their", "this", "that",
    "using", "used", "via", "into", "over", "under", "through", "across",
    "section", "claim", "project", "repo", "repository", "experience", "skills",
    "prior_answer", "prior", "answer", "work", "technical", "engineering",
    "welcome", "general", "overview"
}


def normalize_tokens(text: str) -> List[str]:
    """Tokenizes text into clean lowercase alphanumeric words, filtering out common stopwords."""
    if not text:
        return []
    words = re.findall(r"[a-zA-Z0-9_\-\+\#\.]+", text.lower())
    cleaned = []
    for w in words:
        clean_w = w.strip(".-_")
        if clean_w and clean_w not in STOPWORDS and len(clean_w) > 1:
            cleaned.append(clean_w)
    return cleaned


def is_token_in_text(tok: str, text: str) -> bool:
    """Checks whether a token exists in text as a distinct word or identifier (case-insensitive).
    Prevents false positive substring matches (e.g. 'go' matching inside 'mongodb' or 'algorithm').
    """
    if not tok or not text:
        return False
    tok_clean = tok.strip().lower()
    text_clean = text.lower()

    pattern_parts = []
    if re.match(r"^\w", tok_clean):
        pattern_parts.append(r"(?<![a-zA-Z0-9_])")
    pattern_parts.append(re.escape(tok_clean))
    if re.match(r".*\w$", tok_clean):
        pattern_parts.append(r"(?![a-zA-Z0-9_])")
    else:
        pattern_parts.append(r"(?:\s|[.,;!?\'\"\)\]\n]|\Z)")

    pattern = "".join(pattern_parts)
    if re.search(pattern, text_clean):
        return True
    if len(tok_clean) >= 5 and tok_clean in text_clean:
        return True
    return False


def extract_github_blob(github_summary: Dict[str, Any]) -> str:
    """Consolidates all text from the candidate's GitHub summary into a single searchable blob."""
    parts: List[str] = []
    if not github_summary:
        return ""

    if isinstance(github_summary, dict):
        if "username" in github_summary:
            parts.append(str(github_summary["username"]))
        repos = github_summary.get("repos", {})
        if isinstance(repos, dict):
            for name, repo_data in repos.items():
                parts.append(str(name))
                if isinstance(repo_data, dict):
                    parts.append(repo_data.get("description", ""))
                    parts.append(repo_data.get("language", ""))
                    topics = repo_data.get("topics", [])
                    if isinstance(topics, list):
                        parts.extend(topics)
                    readme = repo_data.get("readme_excerpt", "")
                    if readme:
                        parts.append(readme[:2500])

    return "\n".join(parts)


def validate_question_assumptions(
    question: str,
    turn_type: str,
    resume_text: str,
    github_summary: Dict[str, Any],
    transcript: Optional[List[Any]] = None,
) -> Tuple[bool, str]:
    """Scans the generated question for ungrounded architectural or domain assumptions.

    Catches fabricated surrounding context like 'in your real-time data pipeline'
    when neither the resume, the GitHub project, nor candidate answers mention such a pipeline.
    """
    if not question:
        return True, "question text is empty"

    if turn_type == "closing":
        return True, "closing turn requires no assumption check"

    # Build reference text corpus of established facts
    candidate_answers = []
    if transcript:
        candidate_answers = [
            t.content if hasattr(t, "content") else t.get("content", "")
            for t in transcript
            if (hasattr(t, "role") and t.role == "candidate") or (isinstance(t, dict) and t.get("role") == "candidate")
        ]
    answers_blob = " ".join(candidate_answers)
    established_corpus = f"{resume_text} {extract_github_blob(github_summary)} {answers_blob}".lower()

    # Pattern: 'in your <phrase>' or 'for your <phrase>' or 'within your <phrase>'
    assumption_patterns = [
        r"\b(?:in|for|within|during)\s+your\s+([a-zA-Z0-9_\-\.\'\" ]{3,60}?)(?:,|\.|\?|\band\b|\bwhere\b|\bwhen\b|\bhow\b|\bwith\b|\bto\b|\bwhich\b)",
        r"\b(?:part of your)\s+([a-zA-Z0-9_\-\.\'\" ]{3,60}?)(?:,|\.|\?|\band\b)",
    ]

    GENERIC_CONTEXT_WORDS = {
        "experience", "project", "projects", "work", "background", "implementation",
        "system", "systems", "solution", "solutions", "architecture", "code", "application",
        "service", "services", "career", "role", "team", "previous", "recent", "time",
        "repository", "repo", "repos", "engineering"
    }

    for pat in assumption_patterns:
        matches = re.finditer(pat, question, flags=re.IGNORECASE)
        for m in matches:
            phrase = m.group(1).strip()
            tokens = normalize_tokens(phrase)
            substantive = [t for t in tokens if t not in GENERIC_CONTEXT_WORDS and len(t) > 2]

            # If the phrase introduces specific architectural/domain claims (e.g. 'real-time data pipeline')
            # verify that at least one substantive token is established in the corpus
            if substantive:
                matched = [tok for tok in substantive if is_token_in_text(tok, established_corpus)]
                if not matched:
                    return False, (
                        f"unsupported context assumption: question assumed '{phrase}' (keywords {substantive}), "
                        f"which was never established in the candidate's resume, GitHub projects, or prior answers"
                    )

    return True, "question assumptions verified"


def is_source_ref_grounded(
    source_ref: str,
    source: str,
    turn_type: str,
    resume_text: str,
    github_summary: Dict[str, Any],
    transcript: Optional[List[Any]] = None,
    question: Optional[str] = None,
) -> Tuple[bool, str]:
    """Fuzzy-matches source_ref and question assumptions against the candidate's raw dossier to detect hallucinations.

    Returns:
        (is_grounded: bool, reason: str)
    """
    if question:
        valid_q, q_reason = validate_question_assumptions(
            question=question,
            turn_type=turn_type,
            resume_text=resume_text,
            github_summary=github_summary,
            transcript=transcript,
        )
        if not valid_q:
            return False, q_reason

    if not source_ref or not source_ref.strip():
        return False, "source_ref is empty"

    clean_ref = source_ref.strip()

    # 1. Closing turns are self-contained session conclusions
    if turn_type == "closing" or clean_ref.lower() in ("session_completion", "session completion", "closing"):
        return True, "closing turn reference is valid"

    # 2. Follow-up turns referencing candidate's prior answer
    if turn_type == "follow_up" or clean_ref.lower().startswith("prior_answer") or clean_ref.lower().startswith("prior answer"):
        # Check against transcript history
        if transcript:
            prior_candidate_texts = [
                t.content if hasattr(t, "content") else t.get("content", "")
                for t in transcript
                if (hasattr(t, "role") and t.role == "candidate") or (isinstance(t, dict) and t.get("role") == "candidate")
            ]
            if not prior_candidate_texts:
                return False, "follow-up reference generated but transcript contains no prior candidate answers"

            candidate_corpus = " ".join(prior_candidate_texts)

            # Clean off prefix like 'prior_answer:' or 'prior answer:'
            followup_subject = re.sub(r"^prior[_ ]answer:?\s*", "", clean_ref, flags=re.IGNORECASE).strip()
            followup_subject = followup_subject.strip("'\"`()[]")
            ref_tokens = normalize_tokens(followup_subject)
            if not ref_tokens:
                ref_tokens = [w.lower() for w in re.findall(r"\w+", followup_subject) if len(w) > 2]

            if not ref_tokens:
                return True, "follow_up reference contains standard anchor"

            # Check if any substantive keyword from the follow-up exists in candidate's answers as a whole word
            matched_in_answers = [tok for tok in ref_tokens if is_token_in_text(tok, candidate_corpus)]

            # Also check if it matches the current topic/project being discussed in the last interviewer turn
            last_interviewer_turn = next(
                (t for t in reversed(transcript) if (hasattr(t, "role") and t.role == "interviewer") or (isinstance(t, dict) and t.get("role") == "interviewer")),
                None
            )
            interviewer_context = ""
            if last_interviewer_turn:
                content = last_interviewer_turn.content if hasattr(last_interviewer_turn, "content") else last_interviewer_turn.get("content", "")
                meta_ref = ""
                if hasattr(last_interviewer_turn, "meta") and last_interviewer_turn.meta:
                    meta_ref = getattr(last_interviewer_turn.meta, "source_ref", "")
                elif isinstance(last_interviewer_turn, dict) and "meta" in last_interviewer_turn:
                    meta_ref = last_interviewer_turn["meta"].get("source_ref", "")
                interviewer_context = f"{content} {meta_ref}"

            matched_in_context = [tok for tok in ref_tokens if is_token_in_text(tok, interviewer_context)]

            if matched_in_answers or matched_in_context:
                matched_all = list(set(matched_in_answers + matched_in_context))
                return True, f"follow_up verified against conversation context (matched: {matched_all[:3]})"

            return False, (
                f"hallucination detected: follow-up topic '{followup_subject}' (keywords {ref_tokens}) "
                f"was never mentioned in candidate's answer or the preceding discussion"
            )
        return True, "follow_up reference accepted"

    # 3. Determine target text corpus based on source
    if source == "resume":
        target_text = (resume_text or "").lower()
        source_label = "resume"
    elif source == "github":
        target_text = extract_github_blob(github_summary).lower()
        source_label = "github_summary"
    else:
        # Fall back to combined dossier
        target_text = ((resume_text or "") + " " + extract_github_blob(github_summary)).lower()
        source_label = "combined_dossier"

    if not target_text.strip():
        return False, f"target source text for {source_label} is completely empty"

    # 4. Remove standard schema prefixes from source_ref for matching
    cleaned_ref_subject = re.sub(
        r"^(repo:|repository:|skills section:|skills:|project:|experience:|claim:)\s*",
        "",
        clean_ref,
        flags=re.IGNORECASE,
    ).strip()

    # Strip surrounding quotes and brackets
    cleaned_ref_subject = cleaned_ref_subject.strip("'\"`()[]")
    lower_subject = cleaned_ref_subject.lower()

    # Direct substring match
    if len(lower_subject) >= 3 and lower_subject in target_text:
        return True, f"exact substring match found in {source_label}"

    # Extract substantive tokens
    tokens = normalize_tokens(cleaned_ref_subject)
    if not tokens:
        # If no tokens left after stopwords, fall back to raw words
        tokens = [w.lower() for w in re.findall(r"\w+", cleaned_ref_subject) if len(w) > 2]

    if not tokens:
        return False, f"source_ref '{source_ref}' has no substantive keywords"

    # Check token presence in target text with whole-word boundary
    matched_tokens = []
    missing_tokens = []
    for tok in tokens:
        if is_token_in_text(tok, target_text):
            matched_tokens.append(tok)
        else:
            # Check SequenceMatcher against words in target
            matches = [w for w in target_text.split() if difflib.SequenceMatcher(None, tok, w).ratio() >= 0.85]
            if matches:
                matched_tokens.append(tok)
            else:
                missing_tokens.append(tok)

    match_ratio = len(matched_tokens) / len(tokens)

    # For single-token references (e.g. "Kafka", "Docker", "MovieBuddy"), require exact match
    if len(tokens) == 1:
        if matched_tokens:
            return True, f"single-token reference '{tokens[0]}' verified in {source_label}"
        return False, f"token '{tokens[0]}' does not appear anywhere in {source_label}"

    # For GitHub repository turns, if the repository name is verifiably in github_summary repos
    if source == "github" or "repo:" in clean_ref.lower():
        repos = github_summary.get("repos", {}) if isinstance(github_summary, dict) else {}
        repo_names = [r.lower() for r in repos.keys()]
        if any(r in lower_subject for r in repo_names if len(r) >= 3):
            return True, f"github repository name verified in {source_label}"

    # For two-token references, require at least 1 match and match_ratio >= 0.5
    if len(tokens) == 2:
        if match_ratio >= 0.5 and len(matched_tokens) >= 1:
            return True, f"fuzzy match verified ({len(matched_tokens)}/2 tokens present in {source_label})"
        return False, f"insufficient token overlap for two-token reference '{source_ref}'"

    # For multi-token references (>= 3 tokens), require at least 60% overlap
    if match_ratio >= 0.6:
        return True, f"fuzzy match verified ({len(matched_tokens)}/{len(tokens)} tokens present in {source_label})"

    return False, (
        f"hallucination detected: keywords {missing_tokens} from source_ref '{source_ref}' "
        f"do not appear in the candidate's {source_label}"
    )


def extract_deterministic_fallback_target(resume_text: str, covered_refs: Optional[List[Any]] = None) -> Tuple[str, str]:
    """Extracts a real skill or project bullet from the raw resume to form a guaranteed grounded question."""
    covered_lower = []
    if covered_refs:
        for r in covered_refs:
            ref_str = r.get("ref", "") if isinstance(r, dict) else getattr(r, "ref", "")
            covered_lower.append(str(ref_str).lower())

    SECTION_HEADER_BLACKLIST = {
        "technical skills", "skills", "technologies", "core competencies",
        "tools", "programming languages", "languages", "frameworks",
        "databases", "experience", "work history", "education", "projects",
        "leadership", "activities", "certifications", "summary"
    }

    lines = [line.strip() for line in resume_text.splitlines() if line.strip()]

    # Priority 1: Look for skills line
    for line in lines:
        lower = line.lower()
        if any(k in lower for k in ["skills", "technologies", "competencies", "tools"]):
            clean = re.sub(r"^[-*•\d\.\)]\s*", "", line).strip()
            if ":" in clean:
                clean = clean.split(":", 1)[1].strip()
            elif clean.lower() in SECTION_HEADER_BLACKLIST:
                continue
            skills = [s.strip() for s in re.split(r"[,|•;/]", clean) if s.strip()]
            for s in skills:
                if s.lower() in SECTION_HEADER_BLACKLIST or len(s.split()) > 4:
                    continue
                if len(s) > 1 and len(s) < 30 and not any(s.lower() in cov for cov in covered_lower):
                    return s, f"Skills Section: {s}"

    # Priority 2: Look for experience or project bullet
    for line in lines:
        clean_line = re.sub(r"^[-*•–\d\.\)]\s*", "", line).strip()
        if clean_line.lower() in SECTION_HEADER_BLACKLIST:
            continue
        if line.startswith(("-", "*", "•", "–")) and len(line) > 20:
            clean = re.sub(r"^[-*•–\d\.\)]\s*", "", line).strip()
            # Check if not covered
            if not any(clean[:30].lower() in cov for cov in covered_lower):
                return clean, clean[:65]

    # Priority 3: Any substantial line
    for line in lines:
        if 20 < len(line) < 120 and not any(h in line.lower() for h in ["email", "phone", "github", "linkedin", "address"]):
            return line, line[:60]

    return "software engineering experience", "General Experience Claim"

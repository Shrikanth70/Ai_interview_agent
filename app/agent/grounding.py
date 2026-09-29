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


def extract_semantic_chunks(text: str) -> List[str]:
    """Extracts cohesive bullet items, standalone section lines, and role/project blocks to test claim co-occurrence."""
    chunks = []
    # 1. Segment text into sections by section headers (e.g. 'Experience:', 'projects:'), markdown headers, or paragraph breaks
    sections = re.split(
        r"\n(?=[a-z0-9\s\-]{3,40}:)|\n(?=[a-z\s]{4,}(?:\n|$))|\n\s*\n|(?:\-{3,})|(?:\={3,})",
        text,
        flags=re.IGNORECASE,
    )
    for sec in sections:
        clean_sec = re.sub(r"\s+", " ", sec).strip().lower()
        if len(clean_sec) >= 30 and clean_sec not in chunks:
            chunks.append(clean_sec)

        # 2. Extract bullets within this section
        bullet_items = re.findall(
            r"(?:^|\n)\s*[-*•\d\.\)]\s*([^\n]+(?:\n(?!\s*[-*•\d\.\)]\s*)[^\n]+)*)",
            sec,
        )
        for item in bullet_items:
            clean = re.sub(r"\s+", " ", item).strip().lower()
            if len(clean) >= 15 and clean not in chunks:
                chunks.append(clean)

        # 3. Standalone non-bullet lines within this section (e.g. project headers, degrees)
        for line in sec.splitlines():
            clean = line.strip().lower()
            clean = re.sub(r"^[-*•\d\.\)]\s*", "", clean).strip()
            if len(clean) >= 15 and clean not in chunks:
                chunks.append(clean)

    return chunks


def extract_numerical_metrics(text: str) -> List[str]:
    """Extracts numerical claims, metric values, latency, throughput, and percentages from text."""
    metrics: List[str] = []
    # 1. Numbers with units: 450ms, 40ms, 35%, 100x, 45,000 tps, 5k req/s, 10gb
    unit_pattern = re.compile(
        r"\b(\d+(?:[,\.]\d+)?\s*(?:ms|sec|seconds|s|tps|qps|rps|req/s|reqs/sec|%|percent|x|fold|k|m|gb|mb|tb))\b",
        re.IGNORECASE,
    )
    for m in unit_pattern.finditer(text):
        token = m.group(1).strip().lower()
        metrics.append(token)

    # 2. Latency / quantitative ranges: from X to Y, from X down to Y, by X
    range_pattern = re.compile(
        r"\b(?:from|down to|up to|reduced to|by)\s+(\d+(?:[,\.]\d+)?\s*(?:ms|sec|s|%|tps|x)?)\b",
        re.IGNORECASE,
    )
    for m in range_pattern.finditer(text):
        val = m.group(1).strip().lower()
        if re.search(r"\d", val):
            metrics.append(val)

    # Deduplicate while preserving order
    seen = set()
    deduped = []
    for m in metrics:
        norm = re.sub(r"\s+", "", m).lower()
        if norm not in seen:
            seen.add(norm)
            deduped.append(m)
    return deduped


def is_metric_in_corpus(metric: str, corpus: str) -> bool:
    """Verifies whether an extracted metric or number appears legitimately in the candidate's corpus."""
    corpus_lower = corpus.lower()
    clean_metric = metric.lower().strip()
    no_space_metric = re.sub(r"\s+", "", clean_metric)
    if clean_metric in corpus_lower or no_space_metric in corpus_lower:
        return True

    # Extract number part
    num_match = re.search(r"\d+(?:[,\.]\d+)?", clean_metric)
    if not num_match:
        return False
    num_str = num_match.group(0).replace(",", "")

    # Ignore trivial single-digit narrative numbers or turn numbers (e.g., "1", "2")
    if len(num_str) == 1 and clean_metric in ["1", "2", "3"]:
        return True

    # Check if number appears with unit or percent in corpus (e.g. 35% vs 35 percent)
    if "%" in clean_metric and f"{num_str} percent" in corpus_lower:
        return True

    # Check exact word boundary for the number itself if metric had a unit
    pattern = rf"\b{re.escape(num_str)}\b"
    if re.search(pattern, corpus_lower):
        return True

    return False


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

    # 1. Metric and Numerical Claim Verification
    extracted_metrics = extract_numerical_metrics(question)
    for met in extracted_metrics:
        if not is_metric_in_corpus(met, established_corpus):
            return False, (
                f"hallucinated metric detected: question claimed '{met}' "
                f"which does not appear anywhere in candidate dossier or conversation context"
            )

    # Pattern: 'in your <phrase>' or 'for your <phrase>' or 'within your <phrase>'
    assumption_patterns = [
        r"\b(?:in|for|within|during)\s+your\s+([a-zA-Z0-9_\-\.\'\" ]{3,60}?)(?:,|\.|\?|\band\b|\bwhere\b|\bwhen\b|\bhow\b|\bwith\b|\bto\b|\bwhich\b)",
        r"\b(?:part of your)\s+([a-zA-Z0-9_\-\.\'\" ]{3,60}?)(?:,|\.|\?|\band\b)",
        r"\b(?:the|your)\s+([a-zA-Z0-9_\-\+\#\.]+)\s+(?:implementation|details|commands|data structures|setup|config|configuration|pipeline|cluster|service|architecture)\s+(?:in|for|of|during|within)\s+your\s+([a-zA-Z0-9_\-\.\'\" ]{3,60}?)(?:,|\.|\?|\band\b|\bwhere\b|\bwhen\b|\bhow\b|\bwhich\b)?",
    ]

    GENERIC_CONTEXT_WORDS = {
        "experience", "project", "projects", "work", "background", "implementation",
        "system", "systems", "solution", "solutions", "architecture", "code", "application",
        "service", "services", "career", "role", "team", "previous", "recent", "time",
        "repository", "repo", "repos", "engineering",
        "reducing", "reduced", "increasing", "increased", "improving", "improved",
        "optimizing", "optimized", "achieving", "achieved", "handling", "handled",
        "using", "used", "working", "worked", "strategy", "strategies", "approach",
        "bottlenecks", "challenges"
    }

    for pat in assumption_patterns:
        matches = re.finditer(pat, question, flags=re.IGNORECASE)
        for m in matches:
            groups = m.groups()
            if len(groups) == 2 and groups[1]:
                # Matches: the <tech> implementation in your <phrase>
                tech_token = groups[0].strip()
                phrase = groups[1].strip()
                if turn_type == "follow_up":
                    # In a follow-up, any specific technology claimed to be in candidate's solution must be stated in their answers
                    interviewer_context = ""
                    if transcript:
                        last_interviewer_turn = next(
                            (t for t in reversed(transcript) if (hasattr(t, "role") and t.role == "interviewer") or (isinstance(t, dict) and t.get("role") == "interviewer")),
                            None
                        )
                        if last_interviewer_turn:
                            content = last_interviewer_turn.content if hasattr(last_interviewer_turn, "content") else last_interviewer_turn.get("content", "")
                            meta_ref = ""
                            if hasattr(last_interviewer_turn, "meta") and last_interviewer_turn.meta:
                                meta_ref = getattr(last_interviewer_turn.meta, "source_ref", "")
                            elif isinstance(last_interviewer_turn, dict) and "meta" in last_interviewer_turn:
                                meta_ref = last_interviewer_turn["meta"].get("source_ref", "")
                            interviewer_context = f"{content} {meta_ref}".lower()

                    if not is_token_in_text(tech_token, answers_blob) and not is_token_in_text(tech_token, interviewer_context):
                        return False, (
                            f"unsupported context assumption: follow-up question assumed candidate used '{tech_token}' "
                            f"in their '{phrase}', but '{tech_token}' was never mentioned in candidate's answers or discussion"
                        )
                continue

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

    # 3. Assertion Clause Verification: catches 'you highlighted/noted/stated/mentioned/claimed <phrase>'
    # This checks that opening resume claims don't fabricate candidate achievements.
    # For follow-ups, prior answers are checked separately via the transcript.
    if turn_type != "follow_up":
        assertion_patterns = [
            r"\b(?:you\s+(?:highlighted|noted|stated|mentioned|claimed|described))\s+([a-zA-Z0-9_\-\.\'\"\% ]{4,80}?)(?:\.|\?|,|\bwhere\b|\bwhen\b|\bhow\b)",
        ]
        chunks = extract_semantic_chunks(established_corpus)
        for pat in assertion_patterns:
            matches = re.finditer(pat, question, flags=re.IGNORECASE)
            for m in matches:
                phrase = m.group(1).strip()
                tokens = normalize_tokens(phrase)
                substantive = [t for t in tokens if t not in GENERIC_CONTEXT_WORDS and len(t) > 2]
                if len(substantive) >= 2:
                    max_chunk_matches = max(
                        (sum(1 for tok in substantive if is_token_in_text(tok, c)) for c in chunks),
                        default=0,
                    )
                    if max_chunk_matches < len(substantive) * 0.6:
                        return False, (
                            f"unsupported assertion detected: question asserted '{phrase}' (keywords {substantive}), "
                            f"which does not co-occur as a unified claim in candidate's resume or background "
                            f"(max chunk overlap: {max_chunk_matches}/{len(substantive)})"
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
            established_tokens = set(matched_in_answers + matched_in_context)

            if not established_tokens:
                return False, (
                    f"hallucination detected: follow-up topic '{followup_subject}' (keywords {ref_tokens}) "
                    f"was never mentioned in candidate's answer or the preceding discussion"
                )

            # Anti-hallucination cross-check: detect if the follow-up introduced a distinct technology/entity
            # from the resume or GitHub dossier that was never mentioned in candidate's answers or current discussion
            dossier_text = f"{resume_text} {extract_github_blob(github_summary)}"
            GENERIC_WORDS = {
                "handling", "mitigation", "strategy", "strategies", "approach", "approaches",
                "implementation", "implementations", "details", "tradeoff", "tradeoffs",
                "design", "designs", "choice", "choices", "performance", "optimization",
                "optimizations", "overhead", "safety", "failure", "failures", "bottleneck",
                "bottlenecks", "scaling", "latency", "throughput", "reliability",
                "architecture", "architectures", "challenge", "challenges", "decision",
                "decisions", "solution", "solutions", "method", "methods", "technique",
                "techniques", "mechanism", "mechanisms", "process", "pattern", "patterns",
                "system", "systems", "code", "logic", "flow", "structure", "structures",
                "data", "partial", "results", "hybrid", "experience", "problem", "problems",
                "testing", "verification", "benchmark", "benchmarking", "usage", "setup",
                "key", "keys", "value", "values", "storage", "caching", "memoization", "specifics",
                "channel", "channels", "loop", "loops", "leak", "leaks", "thread", "threads",
                "buffer", "buffers", "pool", "pools", "lock", "locks", "mutex", "mutexes",
                "queue", "queues", "event", "events", "stack", "tree", "trees", "table", "tables",
                "timer", "timers", "pointer", "pointers", "routine", "routines", "goroutine", "goroutines"
            }

            unmentioned_dossier_tokens = []
            for tok in ref_tokens:
                if tok not in established_tokens and tok not in GENERIC_WORDS:
                    # If this token exists as a distinct entity in the resume or github dossier
                    if is_token_in_text(tok, dossier_text):
                        unmentioned_dossier_tokens.append(tok)

            if unmentioned_dossier_tokens:
                return False, (
                    f"hallucination detected: follow-up topic '{followup_subject}' attributes unmentioned "
                    f"technology/entity {unmentioned_dossier_tokens} from dossier to candidate's answer"
                )

            return True, f"follow_up verified against conversation context (matched: {list(established_tokens)[:3]})"
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

    # 5. Strict verification for GitHub repository turns
    if source == "github" or "repo:" in clean_ref.lower():
        repos = github_summary.get("repos", {}) if isinstance(github_summary, dict) else {}
        repo_names = [r.lower() for r in repos.keys()]
        matched_repo = next((r for r in repo_names if r in lower_subject and len(r) >= 3), None)
        if matched_repo:
            return True, f"github repository '{matched_repo}' verified in {source_label}"

        # If repo name is not directly cited, check if substantive tokens co-occur in a single repository
        repo_chunks = [
            f"{name} {rdata.get('description', '')} {rdata.get('readme_excerpt', '')}".lower()
            for name, rdata in repos.items()
            if isinstance(rdata, dict)
        ]
        substantive = [
            t for t in tokens
            if t not in {"github", "repo", "repository", "project", "code", "system", "systems"}
            and len(t) > 2
        ]
        if substantive and repo_chunks:
            best_chunk_matches = max(
                (sum(1 for tok in substantive if is_token_in_text(tok, chunk)) for chunk in repo_chunks),
                default=0,
            )
            if best_chunk_matches >= len(substantive) * 0.7:
                return True, f"github repository topic verified in {source_label}"

        return False, (
            f"hallucination detected: github turn reference '{source_ref}' does not match "
            f"any public repository in candidate's portfolio: {list(repos.keys())}"
        )

    # For two-token references, require at least 1 match and match_ratio >= 0.5
    if len(tokens) == 2:
        if match_ratio >= 0.5 and len(matched_tokens) >= 1:
            return True, f"fuzzy match verified ({len(matched_tokens)}/2 tokens present in {source_label})"
        return False, f"insufficient token overlap for two-token reference '{source_ref}'"

    # For multi-token references (>= 3 tokens), require at least 60% overlap
    if match_ratio >= 0.6:
        # If reference has >= 4 tokens, verify that at least 60% of them co-occur
        # within a single cohesive bullet or paragraph chunk in target_text
        if len(tokens) >= 4:
            target_chunks = extract_semantic_chunks(target_text)
            max_chunk_matches = max(
                (sum(1 for tok in tokens if is_token_in_text(tok, c)) for c in target_chunks),
                default=0,
            )
            if max_chunk_matches < len(tokens) * 0.6:
                return False, (
                    f"hallucination detected: tokens from source_ref '{source_ref}' are disjoint and span "
                    f"separate sections of the {source_label} (max local co-occurrence: {max_chunk_matches}/{len(tokens)})"
                )

        return True, f"fuzzy match verified ({len(matched_tokens)}/{len(tokens)} tokens present in {source_label})"

    return False, (
        f"hallucination detected: keywords {missing_tokens} from source_ref '{source_ref}' "
        f"do not appear in the candidate's {source_label}"
    )


def extract_deterministic_fallback_target(
    resume_text: str,
    covered_refs: Optional[List[Any]] = None,
    force_bullet: bool = False,
) -> Tuple[str, str]:
    """Extracts a real skill or project bullet from the raw resume to form a guaranteed grounded question."""
    covered_lower = []
    if covered_refs:
        for r in covered_refs:
            ref_str = r.get("ref", "") if isinstance(r, dict) else getattr(r, "ref", "")
            covered_lower.append(str(ref_str).lower())

    SKILLS_SECTION_WHITELIST = {
        "technical skills", "skills", "technologies", "core competencies",
        "core skills", "key skills", "primary skills", "relevant skills",
        "professional skills", "technical competencies", "skills & tools",
        "tools & technologies", "tools and technologies", "programming languages",
    }

    SECTION_HEADER_BLACKLIST = {
        "experience", "work history", "professional experience", "employment",
        "education", "projects", "selected projects", "academic projects", "personal projects",
        "leadership", "activities", "certifications", "summary", "professional summary",
        "profile", "about me", "objective", "career objective", "additional information",
        "achievements", "interests", "awards"
    } | SKILLS_SECTION_WHITELIST

    NON_SKILL_BLACKLIST = {
        # Countries & tech regions/cities
        "india", "usa", "uk", "united states", "canada", "germany", "australia",
        "singapore", "bengaluru", "bangalore", "hyderabad", "mumbai", "pune",
        "delhi", "noida", "gurugram", "chennai", "kolkata", "san francisco",
        "new york", "london", "seattle", "austin", "boston", "chicago",
        # Human spoken languages
        "english", "telugu", "hindi", "spanish", "french", "mandarin",
        "japanese", "korean", "tamil", "kannada", "marathi", "bengali",
        # Degrees & education terms
        "b.tech", "btech", "m.tech", "mtech", "b.e.", "be", "m.e.", "me",
        "b.s.", "bs", "m.s.", "ms", "ph.d", "phd", "bachelor", "bachelors",
        "master", "masters", "degree", "university", "institute", "college",
        "cgpa", "gpa", "percentage",
        # Employment, company & status terms
        "present", "current", "months", "years", "full-time", "full time",
        "part-time", "intern", "internship", "contract", "freelance",
        "pvt ltd", "pvt. ltd.", "ltd", "inc", "inc.", "llc", "corp", "corporation",
        "solutions", "technologies", "services", "consulting",
        # Job titles, seniority levels & professions
        "senior", "junior", "lead", "principal", "staff", "associate",
        "manager", "director", "vp", "head", "engineer", "developer",
        "architect", "specialist", "analyst", "consultant", "scientist", "researcher",
        "officer", "administrator", "coordinator", "senior ai", "senior ml", "ai engineer",
        "ml engineer", "ai/ml engineer", "machine learning engineer", "software engineer",
        # Academic CS subjects & theory topics (not practical technologies or frameworks)
        "oop", "object oriented programming", "object-oriented programming",
        "dbms", "database management system", "database management systems",
        "os", "operating system", "operating systems",
        "cn", "computer network", "computer networks",
        "dsa", "data structures", "algorithms", "data structures and algorithms",
        "data structures & algorithms", "software engineering", "computer science",
    } | SECTION_HEADER_BLACKLIST

    def is_divider_line(text: str) -> bool:
        cleaned = re.sub(r"[\s\-\=\_\*\#]", "", text)
        return len(cleaned) == 0 and len(text.strip()) >= 3

    def is_employer_or_location_line(text: str) -> bool:
        lower_text = text.lower()
        if any(term in lower_text for term in ["pvt. ltd", "pvt ltd", "inc.", "llc", "solutions pvt"]):
            return True
        if re.search(r"\b(20\d\d|19\d\d)\s*[–—\-]\s*(20\d\d|19\d\d|present)\b", lower_text):
            return True
        if any(marker in lower_text for marker in ["— bengaluru", "– bengaluru", "— hyderabad", "– hyderabad", "— india", "– india"]):
            return True
        return False

    def is_valid_candidate_skill(s: str) -> bool:
        s_clean = s.strip(":-_•* ").strip()
        s_lower = s_clean.lower()
        if not s_clean:
            return False
        if s_lower in NON_SKILL_BLACKLIST:
            return False
        if s_lower.endswith("skills") or s_lower.endswith("technologies"):
            return False
        if len(s_clean.split()) > 4:
            return False
        if not (1 < len(s_clean) < 30):
            return False
        if any(s_lower in cov for cov in covered_lower):
            return False
        return True

    # Preprocess lines ignoring divider lines
    lines = [line.strip() for line in resume_text.splitlines() if line.strip() and not is_divider_line(line)]

    # Priority 1: Look ONLY within explicit skills sections (unless force_bullet is requested)
    if not force_bullet:
        for i, line in enumerate(lines):
            clean = re.sub(r"^[-*•\d\.\)]\s*", "", line).strip()
            clean_lower = clean.lower().rstrip(":")

            if clean_lower in SKILLS_SECTION_WHITELIST:
                # Look ahead up to 10 lines in this section for skills
                for j in range(i + 1, min(i + 12, len(lines))):
                    sub_line = lines[j]
                    sub_clean = re.sub(r"^[-*•\d\.\)]\s*", "", sub_line).strip()
                    sub_lower = sub_clean.lower().rstrip(":")
                    # Stop if we hit another major section header
                    if sub_lower in SECTION_HEADER_BLACKLIST and not any(sub_lower.startswith(k) for k in ["programming", "languages", "frameworks", "tools", "databases", "machine learning", "deep learning", "cloud", "backend", "generative ai", "nlp", "vector", "mlops"]):
                        break
                    if is_employer_or_location_line(sub_line):
                        break
                    # Handle sub-category line like "Programming: Python, Go, SQL" or standalone "Python, Go"
                    candidate_content = sub_clean.split(":", 1)[1].strip() if ":" in sub_clean else sub_clean
                    tokens = [t.strip() for t in re.split(r"[,|•;]", candidate_content) if t.strip()]
                    for tok in tokens:
                        if is_valid_candidate_skill(tok):
                            return tok, f"Skills Section: {tok}"

            # If line contains explicit skills section phrasing
            if any(k in clean_lower for k in ["core skills", "technical skills", "skills & tools", "programming languages"]):
                if is_employer_or_location_line(clean):
                    continue
                content = clean.split(":", 1)[1].strip() if ":" in clean else clean
                tokens = [t.strip() for t in re.split(r"[,|•;]", content) if t.strip()]
                for tok in tokens:
                    if is_valid_candidate_skill(tok):
                        return tok, f"Skills Section: {tok}"

    # Priority 2: Look for experience or project bullet
    in_skills_section = False
    for line in lines:
        if is_employer_or_location_line(line):
            continue
        clean_line = re.sub(r"^[-*•–\d\.\)]\s*", "", line).strip()
        clean_lower = clean_line.lower().rstrip(":")

        if clean_lower in SKILLS_SECTION_WHITELIST:
            in_skills_section = True
            continue
        if clean_lower in SECTION_HEADER_BLACKLIST and clean_lower not in SKILLS_SECTION_WHITELIST:
            in_skills_section = False
            continue

        if in_skills_section:
            continue

        if any(clean_lower.startswith(prefix) for prefix in [
            "programming:", "programming languages:", "languages:", "frameworks:",
            "tools:", "databases:", "libraries:", "platforms:", "technologies:",
            "core competencies:", "technical skills:", "skills:"
        ]):
            continue

        if clean_line.lower().rstrip(":") in SECTION_HEADER_BLACKLIST:
            continue
        if line.startswith(("-", "*", "•", "–")) and len(line) > 20:
            if not any(clean_line[:30].lower() in cov for cov in covered_lower):
                return clean_line, clean_line[:65]

    # Priority 3: Any substantial line
    in_skills_section = False
    for line in lines:
        if is_employer_or_location_line(line):
            continue
        clean_line = re.sub(r"^[-*•–\d\.\)]\s*", "", line).strip()
        clean_lower = clean_line.lower().rstrip(":")

        if clean_lower in SKILLS_SECTION_WHITELIST:
            in_skills_section = True
            continue
        if clean_lower in SECTION_HEADER_BLACKLIST and clean_lower not in SKILLS_SECTION_WHITELIST:
            in_skills_section = False
            continue

        if in_skills_section:
            continue

        if any(clean_lower.startswith(prefix) for prefix in [
            "programming:", "programming languages:", "languages:", "frameworks:",
            "tools:", "databases:", "libraries:", "platforms:", "technologies:",
            "core competencies:", "technical skills:", "skills:"
        ]):
            continue

        if 20 < len(line) < 120 and not any(h in line.lower() for h in ["email", "phone", "github", "linkedin", "address"]):
            if not any(clean_line[:30].lower() in cov for cov in covered_lower):
                return line, line[:60]

    return "software engineering experience", "General Experience Claim"


def extract_candidate_anchors(resume_text: str) -> List[str]:
    """Extracts 2-4 verified project names or key technical achievements from the resume for Turn 1 anchoring."""
    if not resume_text:
        return []
    anchors: List[str] = []
    lines = [l.strip() for l in resume_text.splitlines() if l.strip()]

    # 1. Look for Projects section
    in_projects = False
    for line in lines:
        clean_lower = line.lower().rstrip(":")
        if clean_lower in ["selected projects", "projects", "technical projects", "key projects", "academic projects"]:
            in_projects = True
            continue
        if in_projects and clean_lower in ["education", "certifications", "achievements", "experience", "work history", "professional experience"]:
            break
        if in_projects:
            if not line.startswith(("-", "*", "•", "–")) and not line.lower().startswith("technology:") and not re.search(r"\b20\d\d\b", line):
                if 3 < len(line) < 60 and clean_lower not in ["overview", "details", "description"]:
                    if line not in anchors:
                        anchors.append(line)
                        if len(anchors) >= 4:
                            return anchors

    # 2. If fewer than 2 anchors, extract key experience bullets
    if len(anchors) < 2:
        for line in lines:
            if line.startswith(("-", "*", "•", "–")) and len(line) > 25:
                clean_bullet = re.sub(r"^[-*•–\d\.\)]\s*", "", line).strip()
                clause = re.split(r"[,;]|\busing\b|\bwith\b|\bby\b", clean_bullet)[0].strip()
                if 15 < len(clause) < 70 and clause not in anchors:
                    anchors.append(clause)
                    if len(anchors) >= 3:
                        break

    return anchors[:4]


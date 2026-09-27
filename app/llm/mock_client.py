"""Mock LLM client producing realistic, anti-cheating, dynamic interview turns for offline testing and demos."""

import json
import re
from typing import Any, Dict, List, Optional

from app.llm.base import BaseLLMClient


class MockLLMClient(BaseLLMClient):
    """Generates realistic structured interview turns grounded strictly in the candidate's actual dossier.
    
    Implements anti-cheating, random non-linear questioning, answer-potential gated follow-ups,
    and dynamically extracts the candidate's real GitHub repositories from the provided dossier.
    """

    def __init__(self):
        self._turn_index = 0

    def _extract_last_candidate_answer(self, messages: List[Dict[str, str]]) -> Optional[str]:
        """Extracts the candidate's last answer from the message history."""
        for msg in reversed(messages):
            content = msg.get("content", "")
            if msg.get("role") == "user" and "[Candidate Answer]:" in content:
                parts = content.split("[Candidate Answer]:", 1)
                if len(parts) > 1:
                    return parts[1].strip()
        return None

    def _is_vague_or_shallow(self, answer: Optional[str]) -> bool:
        """Determines if the answer lacks technical depth and warrants a follow-up."""
        if not answer:
            return True
        words = answer.strip().split()
        if len(words) < 18:
            return True
        
        lower = answer.lower()
        evasive_patterns = [
            "standard stuff",
            "best practices",
            "i don't recall",
            "used a library",
            "just followed",
            "not really sure",
            "standard way",
            "normal architecture",
        ]
        if any(p in lower for p in evasive_patterns):
            return True
            
        return False

    def _extract_resume_elements_from_dossier(self, messages: List[Dict[str, str]]) -> Dict[str, Any]:
        """Extracts candidate claims, projects, and skills from the uploaded resume in the dossier."""
        resume_content = ""
        for msg in messages:
            content = msg.get("content", "")
            if "--- [SOURCE 1: RESUME TEXT & SKILLS] ---" in content:
                match = re.search(
                    r"--- \[SOURCE 1: RESUME TEXT & SKILLS\] ---\s*(.*?)\s*(?=--- \[SOURCE 2:|\n={10,}|\Z)",
                    content,
                    re.DOTALL,
                )
                if match:
                    resume_content = match.group(1).strip()
                    break

        if not resume_content:
            return {"is_sample_kafka": False, "raw_text": "", "projects": [], "claims": [], "skills": []}

        # Check for known sample resume claim to maintain 100% test compatibility
        lower_full = resume_content.lower()
        is_sample_kafka = "kafka" in lower_full and (
            "450ms" in lower_full or "40ms" in lower_full or "45%" in lower_full or "pipeline" in lower_full
        )

        lines = [line.strip() for line in resume_content.splitlines() if line.strip()]

        projects: List[Dict[str, str]] = []
        claims: List[Dict[str, str]] = []
        skills: List[str] = []

        current_section = "general"
        for line in lines:
            lower_line = line.lower()
            if any(h in lower_line for h in ["technical skills", "skills", "technologies", "core competencies"]):
                current_section = "skills"
                if ":" in line:
                    parts = line.split(":", 1)[1]
                    for item in re.split(r"[,|•;]", parts):
                        s = item.strip()
                        if s and len(s) < 35 and not s.lower().startswith("languages"):
                            skills.append(s)
                continue
            elif any(h in lower_line for h in ["experience", "work history", "employment", "internship"]):
                current_section = "experience"
                continue
            elif any(h in lower_line for h in ["projects", "key projects", "personal projects"]):
                current_section = "projects"
                continue
            elif any(h in lower_line for h in ["education", "academic"]):
                current_section = "education"
                continue

            if current_section == "skills":
                clean_line = re.sub(r"^[-*•\d\.\)]\s*", "", line)
                if ":" in clean_line:
                    clean_line = clean_line.split(":", 1)[1]
                for item in re.split(r"[,|•;]", clean_line):
                    s = item.strip()
                    if s and len(s) < 35 and len(s.split()) <= 4:
                        skills.append(s)
            elif current_section in ("experience", "projects", "general"):
                clean_line = re.sub(r"^[-*•\d\.\)]\s*", "", line).strip()
                if "—" in clean_line or " - " in clean_line:
                    p_name = re.split(r"[—\-]", clean_line)[0].strip()
                    if len(p_name.split()) <= 4 and len(p_name) < 40 and not p_name.isupper():
                        projects.append({"title": p_name, "raw": clean_line})

                action_verbs = [
                    "architected", "developed", "built", "implemented", "designed",
                    "optimized", "migrated", "engineered", "created", "reduced",
                    "decreased", "scaled", "spearheaded", "led", "rebuilt"
                ]
                if line.startswith(("-", "*", "•", "–")) or any(v in lower_line for v in action_verbs):
                    if len(clean_line) > 15:
                        claims.append({"raw": clean_line, "section": current_section})

        return {
            "is_sample_kafka": is_sample_kafka,
            "raw_text": resume_content,
            "projects": projects,
            "claims": claims,
            "skills": skills,
        }

    def _generate_opening_question(self, resume_info: Dict[str, Any]) -> Dict[str, Any]:
        """Generates a Turn 1 opening question starting with the welcome note and citing a real claim/skill."""
        if resume_info.get("is_sample_kafka"):
            return {
                "question": (
                    "Welcome! Looking over your experience and background, you highlighted optimizing an event pipeline "
                    "with Apache Kafka to reduce latency from 450ms down to 40ms. Walk me through the bottlenecks you "
                    "diagnosed in the old architecture and how you designed your partitioning strategy."
                ),
                "turn_type": "resume_claim",
                "source": "resume",
                "source_ref": "Kafka event pipeline migration (450ms -> 40ms latency)",
                "reasoning_note": "Welcoming candidate and opening with a high-impact, metrics-grounded technical achievement from recent experience.",
            }

        claims = resume_info.get("claims", [])
        projects = resume_info.get("projects", [])
        skills = resume_info.get("skills", [])

        # Priority 1: A concrete claim/bullet from resume
        if claims:
            chosen_claim = claims[0]["raw"]
            clean_claim = re.sub(r"^[-*•\d\.\)]\s*", "", chosen_claim).strip()

            words = clean_claim.split()
            first_word = words[0].lower() if words else ""
            conjugations = {
                "developed": "developing",
                "built": "building",
                "architected": "architecting",
                "designed": "designing",
                "implemented": "implementing",
                "optimized": "optimizing",
                "engineered": "engineering",
                "created": "creating",
                "migrated": "migrating",
                "led": "leading",
                "spearheaded": "spearheading",
                "scaled": "scaling",
                "reduced": "reducing",
                "decreased": "decreasing",
                "rebuilt": "rebuilding",
            }
            if first_word in conjugations:
                highlight_phrase = conjugations[first_word] + " " + " ".join(words[1:])
            else:
                highlight_phrase = clean_claim[0].lower() + clean_claim[1:] if clean_claim else "your technical background"

            if len(highlight_phrase) > 150:
                shortened = highlight_phrase[:150]
                if " using " in shortened:
                    highlight_phrase = shortened.rsplit(" using ", 1)[0]
                elif " to " in shortened:
                    highlight_phrase = shortened.rsplit(" to ", 1)[0]
                elif "," in shortened:
                    highlight_phrase = shortened.rsplit(",", 1)[0]
                else:
                    highlight_phrase = shortened.rsplit(" ", 1)[0]

            highlight_phrase = highlight_phrase.rstrip(".,;: ")

            lower_claim = clean_claim.lower()
            if any(k in lower_claim for k in ["nlp", "recommendation", "similarity", "model", "ml", "ai"]):
                inquiry = "Walk me through how you calculated similarity metrics, diagnosed computational bottlenecks, and optimized inference or response latency."
            elif any(k in lower_claim for k in ["api", "backend", "full-stack", "full stack", "microservice", "endpoints", "express", "fastapi"]):
                inquiry = "Walk me through the system architecture, how you handled external dependencies and latency, and the primary trade-offs you navigated."
            elif any(k in lower_claim for k in ["latency", "throughput", "pipeline", "streaming", "scale"]):
                inquiry = "Walk me through the bottlenecks you diagnosed in the legacy workflow and how you structured your throughput and data flow."
            else:
                inquiry = "Walk me through the bottlenecks you diagnosed during implementation and the key architectural trade-offs you navigated."

            ref_snippet = clean_claim[:65].strip()
            if len(clean_claim) > 65:
                ref_snippet += "..."

            return {
                "question": f"Welcome! Looking over your experience and background, you highlighted {highlight_phrase}. {inquiry}",
                "turn_type": "resume_claim",
                "source": "resume",
                "source_ref": ref_snippet,
                "reasoning_note": "Welcoming candidate and opening with a concrete technical claim from their uploaded resume.",
            }

        # Priority 2: A project title
        if projects:
            p_title = projects[0]["title"]
            return {
                "question": (
                    f"Welcome! Looking over your experience and background, you highlighted developing {p_title}. "
                    f"Walk me through the core architecture of this platform, the technical trade-offs you faced during development, "
                    f"and how you diagnosed and resolved its toughest bottlenecks."
                ),
                "turn_type": "resume_claim",
                "source": "resume",
                "source_ref": f"Project: {p_title}",
                "reasoning_note": f"Welcoming candidate and opening with project '{p_title}' from their uploaded resume.",
            }

        # Priority 3: Highlighted skills
        if skills:
            top_skills = ", ".join(skills[:2]) if len(skills) >= 2 else skills[0]
            return {
                "question": (
                    f"Welcome! Looking over your experience and background, you highlighted your expertise with {top_skills}. "
                    f"Walk me through a complex technical system where you applied these technologies and the biggest architectural "
                    f"bottlenecks you had to diagnose and overcome."
                ),
                "turn_type": "skill_anchored",
                "source": "resume",
                "source_ref": f"Skills Section: {top_skills}",
                "reasoning_note": f"Welcoming candidate and probing listed technical skill '{top_skills}' from uploaded resume.",
            }

        # Fallback
        return {
            "question": (
                "Welcome! Looking over your experience and background, you highlighted your engineering achievements. "
                "Walk me through the most technically demanding system you have architected, the bottlenecks you diagnosed, "
                "and how you resolved them under real-world constraints."
            ),
            "turn_type": "resume_claim",
            "source": "resume",
            "source_ref": "Engineering Experience Overview",
            "reasoning_note": "Welcoming candidate and inviting a deep dive into their most challenging architectural achievement.",
        }

    def _extract_repositories_from_dossier(self, messages: List[Dict[str, str]]) -> Dict[str, Dict[str, str]]:
        """Parses real repositories present in the candidate's dossier."""
        repos = {}
        for msg in messages:
            content = msg.get("content", "")
            if "--- [SOURCE 2: GITHUB PROFILE & REPOSITORIES] ---" in content:
                repo_matches = re.finditer(
                    r"Repository:\s*([^\n\r]+)(.*?)(?=\nRepository:|\n={10,}|\Z)",
                    content,
                    re.DOTALL
                )
                for m in repo_matches:
                    name = m.group(1).strip()
                    block = m.group(2)
                    lang_m = re.search(r"Primary Language:\s*([^\n\r]+)", block)
                    desc_m = re.search(r"Description:\s*([^\n\r]+)", block)
                    lang = lang_m.group(1).strip() if lang_m else "Python"
                    desc = desc_m.group(1).strip() if desc_m else ""
                    repos[name] = {"name": name, "language": lang, "description": desc}
        return repos

    def _get_covered_topics(self, messages: List[Dict[str, str]]) -> List[str]:
        """Identifies topics already covered in prior assistant turns."""
        covered = []
        for msg in messages:
            if msg.get("role") == "assistant":
                content = msg.get("content", "").lower()
                covered.append(content)
        return covered

    def _get_last_turn_meta(self, messages: List[Dict[str, str]]) -> Dict[str, Any]:
        """Extracts metadata from the most recent interviewer turn."""
        for msg in reversed(messages):
            if msg.get("role") == "assistant":
                content = msg.get("content", "")
                try:
                    data = json.loads(content)
                    return data
                except Exception:
                    meta = {}
                    if "'turn_type':" in content or '"turn_type":' in content:
                        match = re.search(r'["\']turn_type["\']:\s*["\']([^"\']+)["\']', content)
                        if match:
                            meta["turn_type"] = match.group(1)
                    if "'source':" in content or '"source":' in content:
                        match = re.search(r'["\']source["\']:\s*["\']([^"\']+)["\']', content)
                        if match:
                            meta["source"] = match.group(1)
                    if "'source_ref':" in content or '"source_ref":' in content:
                        match = re.search(r'["\']source_ref["\']:\s*["\']([^"\']+)["\']', content)
                        if match:
                            meta["source_ref"] = match.group(1)
                    return meta
        return {}

    async def _call_provider(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
    ) -> str:
        # Check closing mandate
        last_msg = messages[-1].get("content", "") if messages else ""
        if "turn_type='closing'" in last_msg or "maximum allocated turns" in last_msg:
            payload = {
                "question": (
                    "Thank you for walking me through your background, engineering projects, and technical skills. "
                    "That covers the core technical areas I wanted to explore today. Do you have any questions for me about the team or systems?"
                ),
                "turn_type": "closing",
                "source": "resume",
                "source_ref": "session_completion",
                "reasoning_note": "Interview session conclusion reached after comprehensive multi-source exploration.",
            }
            return json.dumps(payload)

        assistant_turns = sum(1 for m in messages if m.get("role") == "assistant")
        turn_num = assistant_turns + 1

        # Extract actual repositories and resume elements from candidate dossier
        candidate_repos = self._extract_repositories_from_dossier(messages)
        resume_info = self._extract_resume_elements_from_dossier(messages)
        covered_texts = self._get_covered_topics(messages)

        # Helper to check if a repo has already been asked about
        def is_repo_covered(r_name: str) -> bool:
            return any(r_name.lower() in t for t in covered_texts)

        uncovered_repos = [r for r in candidate_repos.values() if not is_repo_covered(r["name"])]

        # Turn 1: Opening question (Grounded in Resume claim with welcoming greeting)
        if turn_num == 1:
            payload = self._generate_opening_question(resume_info)
            return json.dumps(payload)

        # Subsequent turns: inspect answer quality and potential
        last_answer = self._extract_last_candidate_answer(messages)
        is_shallow = self._is_vague_or_shallow(last_answer)
        last_meta = self._get_last_turn_meta(messages)
        last_turn_type = last_meta.get("turn_type", "")
        last_ref = last_meta.get("source_ref", "")

        # Anti-cheating rule: Follow-up ONLY if shallow/vague, AND avoid consecutive follow-ups
        if is_shallow and last_turn_type != "follow_up":
            # If the last question was on a GitHub repository, probe that specific repo!
            if "repo:" in last_ref.lower():
                match = re.search(r'repo:\s*([^\s/]+)', last_ref, re.IGNORECASE)
                repo_name = match.group(1) if match else "your repository"
                payload = {
                    "question": (
                        f"In your '{repo_name}' implementation, can you be more specific about the concrete data pipeline, "
                        f"how you structured error handling, and the exact trade-offs you encountered under production constraints?"
                    ),
                    "turn_type": "follow_up",
                    "source": "github",
                    "source_ref": f"prior_answer: {repo_name} implementation specifics & trade-offs",
                    "reasoning_note": f"Candidate gave a vague answer on {repo_name}; drilling down into implementation specifics.",
                }
            elif "kafka" in last_ref.lower():
                payload = {
                    "question": (
                        "Your explanation on the pipeline was quite high-level. Specifically, what serialization protocol "
                        "(e.g. Avro, Protobuf, JSON) did you deploy, how did you size partition buffer memory, and how did your "
                        "consumer groups recover from rebalances without message duplication?"
                    ),
                    "turn_type": "follow_up",
                    "source": "resume",
                    "source_ref": "prior_answer: Kafka buffer sizing and partition rebalance handling",
                    "reasoning_note": "Candidate's prior answer was vague/shallow; strictly drilling into architecture internals to verify hands-on competence.",
                }
            else:
                last_topic = last_ref.replace("Skills Section:", "").replace("Project:", "").strip()
                if len(last_topic) > 40:
                    last_topic = last_topic[:40] + "..."
                payload = {
                    "question": (
                        f"Can you walk me through a concrete scenario from your work with {last_topic} detailing the edge cases or failure modes "
                        f"you encountered, rather than the general architectural pattern?"
                    ),
                    "turn_type": "follow_up",
                    "source": last_meta.get("source", "resume"),
                    "source_ref": f"prior_answer: {last_topic} implementation edge cases",
                    "reasoning_note": "Candidate's answer was non-specific; requiring concrete implementation depth.",
                }
            return json.dumps(payload)

        # Candidate gave a solid / substantive answer! NO follow up!
        # Randomly jump across sources/topics to break any predictable rhythm!

        # Priority 1: If candidate has uncovered public repositories, ask about their REAL repo!
        if uncovered_repos:
            chosen_repo = uncovered_repos[0]
            repo_name = chosen_repo["name"]
            repo_lang = chosen_repo["language"]
            desc_clause = f" ({chosen_repo['description']})" if chosen_repo.get("description") else ""
            payload = {
                "question": (
                    f"That clearly explains the architecture and design choices. Shifting over to your public GitHub work: "
                    f"in your repository '{repo_name}'{desc_clause}, you worked with {repo_lang}. "
                    f"Walk me through how you structured this project, key architectural decisions you made, and how you evaluated its performance."
                ),
                "turn_type": "context_switch",
                "source": "github",
                "source_ref": f"repo: {repo_name} / architecture & implementation in {repo_lang}",
                "reasoning_note": f"Candidate answered previous question well. Pivoting to candidate's real repository '{repo_name}' to test code depth.",
            }
            return json.dumps(payload)

        # Priority 2: Probe a candidate skill anchor claim
        candidate_skills = resume_info.get("skills", [])
        uncovered_skills = [
            s for s in candidate_skills
            if s.lower() not in ["languages", "databases", "frameworks", "tools", "skills"]
            and not any(s.lower() in t for t in covered_texts)
        ]
        if uncovered_skills:
            chosen_skill = uncovered_skills[0]
            payload = {
                "question": (
                    f"You listed '{chosen_skill}' under your technical skills. Where have you actually applied {chosen_skill} in practice — "
                    f"was that in production diagnosing real bottlenecks, or in a specialized project? Walk me through a concrete implementation you built."
                ),
                "turn_type": "skill_anchored",
                "source": "resume",
                "source_ref": f"Skills Section: {chosen_skill} application challenge",
                "reasoning_note": f"Candidate demonstrated solid depth. Breaking rhythm by suddenly pivoting to listed skill '{chosen_skill}' from uploaded resume.",
            }
            return json.dumps(payload)

        if resume_info.get("is_sample_kafka"):
            ebpf_covered = any("ebpf" in t for t in covered_texts)
            if not ebpf_covered:
                payload = {
                    "question": (
                        "You listed 'eBPF / Kernel Tracing' under your technical skills. Where have you actually applied eBPF in practice — "
                        "was that in production diagnosing network bottlenecks, or in an experimental repository? Walk me through a concrete program you loaded."
                    ),
                    "turn_type": "skill_anchored",
                    "source": "resume",
                    "source_ref": "Skills Section: eBPF / Kernel Tracing application challenge",
                    "reasoning_note": "Candidate demonstrated solid depth. Breaking rhythm by suddenly pivoting to a listed skill claim across both sources.",
                }
                return json.dumps(payload)

        # Priority 3: Deep dive into another resume claim
        uncovered_claims = [
            c for c in resume_info.get("claims", [])
            if not any(c["raw"][:30].lower() in t for t in covered_texts)
        ]
        if uncovered_claims:
            chosen_claim = uncovered_claims[0]["raw"]
            clean_claim = re.sub(r"^[-*•\d\.\)]\s*", "", chosen_claim).strip()
            snippet = clean_claim[:50]
            payload = {
                "question": (
                    f"Understood. Shifting to another aspect of your experience: you noted '{clean_claim[:90]}'. "
                    f"Walk me through the technical bottlenecks you diagnosed and how you designed that solution."
                ),
                "turn_type": "resume_claim",
                "source": "resume",
                "source_ref": f"Experience: {snippet}",
                "reasoning_note": "Candidate demonstrated solid technical depth. Pivoting to an unprobed resume achievement.",
            }
            return json.dumps(payload)

        if resume_info.get("is_sample_kafka"):
            postgres_covered = any("postgres" in t or "failover" in t for t in covered_texts)
            if not postgres_covered:
                payload = {
                    "question": (
                        "Understood. Bouncing back to your work at Acme Cloud: under infrastructure projects, you mention designing an automated "
                        "failover controller for PostgreSQL read-replicas. How did you resolve split-brain scenarios when cross-region network partitions occurred?"
                    ),
                    "turn_type": "resume_claim",
                    "source": "resume",
                    "source_ref": "Acme Cloud: PostgreSQL cross-region replica failover controller",
                    "reasoning_note": "Candidate proved depth on skills. Skipping follow-up and jumping back to an unprobed distributed data integrity problem.",
                }
                return json.dumps(payload)

        # Conclude if all major topics are covered
        payload = {
            "question": (
                "Thank you for walking me through your background, repositories, and technical skills. "
                "That covers the core technical areas I wanted to explore today. Do you have any questions for me?"
            ),
            "turn_type": "closing",
            "source": "resume",
            "source_ref": "session_completion",
            "reasoning_note": "Interview session conclusion reached after comprehensive multi-source exploration.",
        }
        return json.dumps(payload)


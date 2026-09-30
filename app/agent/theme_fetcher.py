import random
from typing import Any, Dict, List, Literal, Optional
from app.session.state import ContextSubMemory, SessionState

DEFAULT_JD_SCENARIOS = [
    {
        "scenario_id": "high_throughput_ingestion",
        "title": "High-Throughput Stream Ingestion",
        "problem_statement": "In this role, we handle massive traffic surges where real-time telemetry must be buffered without dropping data or exhausting memory.",
        "key_trade_offs": ["memory bounds vs. message loss", "synchronous vs. asynchronous commit"],
    },
    {
        "scenario_id": "distributed_caching_and_stampedes",
        "title": "Low-Latency Distributed Caching",
        "problem_statement": "Our backend experiences concurrent cache miss stampedes during flash sales, causing database CPU spikes.",
        "key_trade_offs": ["probabilistic expiration vs. mutex locking", "eventual vs. strong consistency"],
    },
]


class ThemeMemoryFetchTool:
    """Deterministic, zero-latency context selector for Profile and JD themes."""

    def initialize_context(
        self,
        theme: Literal["PROFILE", "JD"],
        resume_text: str,
        github_summary: Dict[str, Any],
        jd_scenarios: Optional[List[Dict[str, Any]]] = None,
        preferred_repo: Optional[str] = None,
    ) -> ContextSubMemory:
        """Initializes a new isolated ContextSubMemory for either PROFILE or JD."""
        if theme == "PROFILE":
            repos = (
                github_summary.get("repos", {})
                if isinstance(github_summary, dict)
                else {}
            )
            if repos:
                repo_name = (
                    preferred_repo
                    if preferred_repo in repos
                    else list(repos.keys())[0]
                )
                repo_data = repos[repo_name]
                return ContextSubMemory(
                    context_id=f"github:{repo_name}",
                    theme="PROFILE",
                    source_ref=repo_name,
                    source_slice={
                        "type": "github_repository",
                        "repo_name": repo_name,
                        "description": repo_data.get("description", ""),
                        "language": repo_data.get("language", ""),
                    },
                    pending_dimensions=[
                        "clarity_of_framing",
                        "methodology_depth",
                        "feasibility",
                    ],
                )
            else:
                return ContextSubMemory(
                    context_id="resume:primary_experience",
                    theme="PROFILE",
                    source_ref="Resume Experience",
                    source_slice={
                        "type": "resume_summary",
                        "text_excerpt": resume_text[:600],
                    },
                    pending_dimensions=[
                        "clarity_of_framing",
                        "methodology_depth",
                        "feasibility",
                    ],
                )
        else:
            scenarios = jd_scenarios or DEFAULT_JD_SCENARIOS
            chosen = scenarios[0]
            return ContextSubMemory(
                context_id=f"jd:{chosen['scenario_id']}",
                theme="JD",
                source_ref=chosen["title"],
                source_slice=chosen,
                pending_dimensions=[
                    "clarity_of_framing",
                    "methodology_depth",
                    "feasibility",
                ],
            )

    def fetch_follow_up_context(self, state: SessionState) -> Dict[str, Any]:
        """Pulls the active sub-memory slice, next rubric dimension, and sliding window."""
        active_id = state.orchestration.active_context_id
        sub = state.sub_memories.get(active_id) if active_id else None
        next_dim = (
            sub.pending_dimensions[0]
            if sub and sub.pending_dimensions
            else "methodology_depth"
        )
        return {
            "context_id": active_id,
            "theme": state.orchestration.active_theme,
            "source_slice": sub.source_slice if sub else {},
            "source_ref": sub.source_ref if sub else "General",
            "next_dimension": next_dim,
            "recent_turns": state.recent_dialogue_window[-4:],
            "anti_duplication": state.globally_covered_topics,
        }

    def fetch_bridge_context(
        self,
        state: SessionState,
        target_theme: Literal["PROFILE", "JD"],
        jd_scenarios: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Constructs a composite anchor + target context for seamless bridge transitions."""
        active_id = state.orchestration.active_context_id
        active_sub = state.sub_memories.get(active_id) if active_id else None
        anchor_slice = active_sub.source_slice if active_sub else {}
        target_sub = self.initialize_context(
            theme=target_theme,
            resume_text=state.resume_text,
            github_summary=state.github_summary,
            jd_scenarios=jd_scenarios,
        )
        return {
            "anchor_context_id": active_id,
            "anchor_slice": anchor_slice,
            "anchor_source_ref": active_sub.source_ref if active_sub else "Previous Project",
            "target_context": target_sub,
            "target_theme": target_theme,
            "target_slice": target_sub.source_slice,
            "recent_turns": state.recent_dialogue_window[-4:],
            "anti_duplication": state.globally_covered_topics,
        }

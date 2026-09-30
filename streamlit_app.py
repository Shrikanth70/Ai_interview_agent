import json
from pathlib import Path
import random
from typing import Any, Dict, List, Optional
import httpx
import streamlit as st

# Page Configuration
st.set_page_config(
    page_title="AI Technical Interview Agent — 2-Theme Hierarchical Engine",
    page_icon="🎙️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom Styling (Dark-mode modern theme with badges, metrics & cards)
st.markdown(
    """
    <style>
    .main-header {
        font-size: 1.8rem;
        font-weight: 700;
        margin-bottom: 0.2rem;
        letter-spacing: -0.02em;
    }
    .sub-header {
        font-size: 0.95rem;
        color: #94a3b8;
        margin-bottom: 1.2rem;
    }
    .theme-card {
        background: #111827;
        border: 1px solid #1e293b;
        border-radius: 8px;
        padding: 12px 16px;
        margin-bottom: 14px;
    }
    .tag-badge {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 12px;
        font-weight: 600;
        font-size: 0.75rem;
        margin-right: 6px;
    }
    .badge-profile {
        background-color: rgba(139, 92, 246, 0.15);
        color: #a78bfa;
        border: 1px solid #8b5cf6;
    }
    .badge-jd {
        background-color: rgba(16, 185, 129, 0.15);
        color: #34d399;
        border: 1px solid #10b981;
    }
    .badge-bridge {
        background-color: rgba(245, 158, 11, 0.15);
        color: #fbbf24;
        border: 1px solid #f59e0b;
    }
    .bridge-banner {
        background: linear-gradient(135deg, rgba(245, 158, 11, 0.12), rgba(139, 92, 246, 0.12));
        border-left: 4px solid #f59e0b;
        padding: 10px 14px;
        border-radius: 6px;
        margin: 8px 0;
        font-size: 0.88rem;
    }
    .rubric-pill {
        display: inline-block;
        font-size: 0.72rem;
        padding: 2px 6px;
        border-radius: 4px;
        background: rgba(255, 255, 255, 0.06);
        color: #93c5fd;
        margin-right: 4px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# Preloaded Enterprise Job Description Scenarios
DEFAULT_JD_SCENARIOS = [
    {
        "scenario_id": "high_throughput_ingestion",
        "title": "High-Throughput Stream Ingestion",
        "problem_statement": (
            "In this role, we handle massive traffic surges where real-time telemetry "
            "must be buffered without dropping data or exhausting memory."
        ),
        "key_trade_offs": [
            "memory bounds vs. message loss",
            "synchronous vs. asynchronous commit",
        ],
    },
    {
        "scenario_id": "distributed_caching_and_stampedes",
        "title": "Low-Latency Distributed Caching",
        "problem_statement": (
            "Our backend experiences concurrent cache miss stampedes during flash sales, "
            "causing database CPU spikes."
        ),
        "key_trade_offs": [
            "probabilistic expiration vs. mutex locking",
            "eventual vs. strong consistency",
        ],
    },
    {
        "scenario_id": "event_driven_microservices",
        "title": "Distributed Transaction Consistency",
        "problem_statement": (
            "Our payment and fulfillment services require atomic transactions across decoupled "
            "services without blocking on two-phase commit."
        ),
        "key_trade_offs": [
            "saga pattern orchestrator vs. choreographing events",
            "idempotency keys vs. distributed locks",
        ],
    },
]

# State Initialization
if "session_id" not in st.session_state:
    st.session_state.session_id = None
if "status" not in st.session_state:
    st.session_state.status = "idle"  # idle, active, completed
if "messages" not in st.session_state:
    st.session_state.messages = []
if "covered_refs" not in st.session_state:
    st.session_state.covered_refs = []
if "orchestration" not in st.session_state:
    st.session_state.orchestration = None
if "summary" not in st.session_state:
    st.session_state.summary = None


# Helper: Check Backend Health
def check_backend(base_url: str) -> bool:
    try:
        resp = httpx.get(f"{base_url.rstrip('/')}/health", timeout=3.0)
        return resp.status_code == 200
    except Exception:
        return False


# --- SIDEBAR ---
with st.sidebar:
    st.title("🎙️ Interviewer Control")

    # Backend Connection
    api_url = st.text_input("FastAPI Backend URL", value="http://127.0.0.1:8000")
    is_online = check_backend(api_url)

    if is_online:
        st.caption("🟢 **Backend Connected** (`/health` OK)")
    else:
        st.error("🔴 **Backend Offline** — Start backend: `uvicorn app.main:app --port 8000`")

    st.divider()

    # Session Status Indicator
    status_label = {
        "idle": "⚪ Setup & Idle",
        "active": "🟢 Interview In Progress",
        "completed": "🏁 Interview Concluded",
    }.get(st.session_state.status, "⚪ Idle")

    st.subheader(f"Status: {status_label}")
    if st.session_state.session_id:
        st.code(f"Session: {st.session_state.session_id[:8]}...", language="text")

    # Setup Form (When Idle)
    if st.session_state.status == "idle":
        st.subheader("1. LLM Engine Provider")
        llm_provider_choice = st.radio(
            "Select Provider",
            ["Mock LLM (Fast & Reliable)", "Ollama (Local Offline)", "OpenRouter (Cloud)"],
            index=0,
        )

        def get_ollama_models() -> List[str]:
            for endpoint in ["http://127.0.0.1:11434", "http://localhost:11434"]:
                try:
                    resp = httpx.get(f"{endpoint}/api/tags", timeout=2.0)
                    if resp.status_code == 200:
                        raw_models = [m["name"] for m in resp.json().get("models", [])]
                        local = [m for m in raw_models if not m.endswith(":cloud")]
                        cloud = [m for m in raw_models if m.endswith(":cloud")]
                        return local + cloud
                except Exception:
                    continue
            return []

        local_models = []
        if llm_provider_choice == "Mock LLM (Fast & Reliable)":
            chosen_provider = "mock"
            chosen_model = "mock-interview-agent"
            st.caption("⚡ Zero latency, reproducible structured questions.")
        elif llm_provider_choice == "Ollama (Local Offline)":
            chosen_provider = "ollama"
            local_models = get_ollama_models()
            if local_models:
                best_default = 0
                for pref in ["llama3.2:latest", "llama3.2", "gemma4:latest", "llama3.1:latest", "llama3.1"]:
                    if pref in local_models:
                        best_default = local_models.index(pref)
                        break
                chosen_model = st.selectbox("Ollama Model", local_models, index=best_default)
            else:
                chosen_model = st.text_input("Ollama Model", value="llama3.2:latest")
                st.warning("Ensure Ollama is running (`ollama serve`).")
        else:
            chosen_provider = "openrouter"
            chosen_model = st.text_input("OpenRouter Model", value="anthropic/claude-3.5-sonnet")
            st.caption("Requires `OPENROUTER_API_KEY` in `.env`.")

        st.divider()

        st.subheader("2. Candidate Profile (Theme 1)")
        github_input = st.text_input(
            "GitHub Handle or Profile URL",
            value="octocat",
            help="Candidate public GitHub username (e.g. 'octocat')",
        )
        use_mock_git = st.checkbox(
            "Use Mock GitHub Portfolio",
            value=True,
            help="Avoids hitting GitHub REST API rate limits during testing.",
        )

        resume_mode = st.radio("Resume Source", ["Sample Resume", "Upload File", "Paste Text"], horizontal=True)
        resume_text_to_send = ""
        resume_file_to_send = None

        if resume_mode == "Sample Resume":
            sample_path = Path("sample_resume.txt")
            if sample_path.exists():
                resume_text_to_send = sample_path.read_text(encoding="utf-8")
                st.caption("Loaded `sample_resume.txt` (Distributed Systems Engineer).")
            else:
                resume_text_to_send = "Senior Backend Engineer with Python, Redis, and High Concurrency experience."
        elif resume_mode == "Upload File":
            uploaded_file = st.file_uploader("Upload Resume (.txt, .md, .pdf)", type=["txt", "md", "pdf"])
            if uploaded_file:
                temp_dir = Path("scratch/uploads")
                temp_dir.mkdir(parents=True, exist_ok=True)
                temp_file = temp_dir / uploaded_file.name
                temp_file.write_bytes(uploaded_file.getvalue())
                resume_file_to_send = str(temp_file.resolve())
                st.success(f"Ready: {uploaded_file.name}")
        else:
            resume_text_to_send = st.text_area("Paste Resume Text", height=120)

        st.divider()

        st.subheader("3. Job Description Scenarios (Theme 2)")
        jd_input_mode = st.radio(
            "JD Scenario Source",
            ["Preloaded Technical Scenarios", "Custom Role Text"],
            horizontal=True,
        )
        selected_scenarios = None
        custom_jd_text = None

        if jd_input_mode == "Preloaded Technical Scenarios":
            scenario_names = [s["title"] for s in DEFAULT_JD_SCENARIOS]
            picked = st.multiselect(
                "Select Scenarios for Theme 2",
                scenario_names,
                default=scenario_names[:2],
            )
            selected_scenarios = [s for s in DEFAULT_JD_SCENARIOS if s["title"] in picked]
            st.caption(f"{len(selected_scenarios)} scenario(s) queued for JD probing.")
        else:
            custom_jd_text = st.text_area(
                "Paste Role Description / Criteria",
                height=100,
                placeholder="Senior Systems Engineer: Requires expertise in distributed caching, telemetry...",
            )

        st.divider()

        st.subheader("4. 2-Theme Starting Engine")
        starting_theme_choice = st.radio(
            "Initial Question Theme (Turn 1)",
            [
                "🎲 Auto (50/50 Random Selection per Spec)",
                "💜 Theme 1: Candidate Profile (Resume/GitHub)",
                "🎯 Theme 2: Job Description Scenario",
            ],
            index=0,
        )

        if "Theme 1" in starting_theme_choice:
            chosen_starting_theme = "PROFILE"
        elif "Theme 2" in starting_theme_choice:
            chosen_starting_theme = "JD"
        else:
            chosen_starting_theme = random.choice(["PROFILE", "JD"])

        start_disabled = not is_online
        if st.button("🚀 Start Interview Session", type="primary", use_container_width=True, disabled=start_disabled):
            with st.spinner("Ingesting Dossier & Initializing 2-Theme Hierarchical Engine..."):
                try:
                    payload: Dict[str, Any] = {
                        "llm_provider": chosen_provider,
                        "model_name": chosen_model,
                        "use_mock_github": use_mock_git,
                        "starting_theme": chosen_starting_theme,
                    }
                    if selected_scenarios:
                        payload["jd_scenarios"] = selected_scenarios
                    if custom_jd_text:
                        payload["jd_text"] = custom_jd_text

                    clean_gh = github_input.strip()
                    if clean_gh.startswith(("http://", "https://", "github.com/")):
                        payload["github_url"] = clean_gh
                    else:
                        payload["github_username"] = clean_gh

                    if resume_file_to_send:
                        payload["resume_file_path"] = resume_file_to_send
                    elif resume_text_to_send.strip():
                        payload["resume_text"] = resume_text_to_send.strip()
                    else:
                        st.error("Please provide resume text or upload a file.")
                        st.stop()

                    resp = httpx.post(f"{api_url.rstrip('/')}/session/start", json=payload, timeout=90.0)

                    if resp.status_code == 201:
                        data = resp.json()
                        st.session_state.session_id = data["session_id"]
                        st.session_state.status = "active"
                        st.session_state.messages = []
                        st.session_state.covered_refs = []
                        st.session_state.orchestration = data.get("orchestration")
                        st.session_state.summary = None

                        turn_data = data["turn"]
                        active_theme = data.get("orchestration", {}).get("active_theme") or ("JD" if turn_data.get("source") == "jd" else "PROFILE")
                        is_bridge = data.get("orchestration", {}).get("is_bridge_turn", False) or turn_data.get("turn_type") == "theme_switch"
                        st.session_state.messages.append({
                            "role": "assistant",
                            "content": turn_data["question"],
                            "meta": {
                                "turn_type": turn_data["turn_type"],
                                "source": turn_data["source"],
                                "source_ref": turn_data["source_ref"],
                                "reasoning_note": turn_data["reasoning_note"],
                                "theme": active_theme,
                                "is_bridge": is_bridge,
                            },
                        })
                        if turn_data.get("source_ref"):
                            st.session_state.covered_refs.append({
                                "turn_index": 1,
                                "source": turn_data["source"],
                                "ref": turn_data["source_ref"],
                            })
                        st.rerun()
                    else:
                        st.error(f"Error {resp.status_code}: {resp.json().get('detail', resp.text)}")
                except httpx.TimeoutException:
                    st.error(
                        "⏳ **Session Start Timed Out (90s limit reached).**\n\n"
                        "The LLM provider or GitHub scraper took too long to initialize the first turn.\n\n"
                        "**Quick Solutions:**\n"
                        "- **Switch to Mock LLM**: Under '1. Interview Engine & Model' in the sidebar, select **'Mock LLM'** for instant offline testing.\n"
                        "- **Use Fast Ollama Model**: If using Ollama, ensure a fast model like `llama3.2:latest` is selected.\n"
                        "- **Enable Mock GitHub**: Check **'Use Mock GitHub Portfolio'** to avoid external network rate limits."
                    )
                except Exception as err:
                    st.error(f"Failed to start interview: {err}")

    # Active Session Actions
    if st.session_state.status in ("active", "completed"):
        col1, col2 = st.columns(2)
        with col1:
            if st.session_state.status == "active":
                if st.button("🛑 End Interview", use_container_width=True):
                    with st.spinner("Concluding session..."):
                        try:
                            resp = httpx.post(
                                f"{api_url.rstrip('/')}/session/{st.session_state.session_id}/end",
                                timeout=10.0,
                            )
                            if resp.status_code == 200:
                                end_data = resp.json()
                                st.session_state.status = "completed"
                                st.session_state.summary = end_data["summary"]
                                st.rerun()
                        except Exception as e:
                            st.error(f"Failed to end: {e}")
        with col2:
            if st.button("🗑️ New Session", use_container_width=True):
                st.session_state.session_id = None
                st.session_state.status = "idle"
                st.session_state.messages = []
                st.session_state.covered_refs = []
                st.session_state.orchestration = None
                st.session_state.summary = None
                st.rerun()

        st.divider()

        # Telemetry & Hierarchical Sub-Memory Inspector
        st.subheader("🧠 Hierarchical Memory Inspector")
        orch = st.session_state.orchestration or {}

        active_theme = orch.get("active_theme", "PROFILE")
        theme_icon = "💜" if active_theme == "PROFILE" else "🎯"
        st.markdown(f"**Active Theme:** {theme_icon} `{active_theme}`")
        if orch.get("active_context_id"):
            st.caption(f"Context: `{orch['active_context_id']}`")

        # Rubric Ladder
        curr_dim = orch.get("current_rubric_dimension")
        if curr_dim:
            st.markdown(f"**Target Rubric Dimension:** `{curr_dim}`")

        with st.expander("Sub-Memories Tree", expanded=False):
            sub_mems = orch.get("sub_memories", [])
            if not sub_mems:
                st.caption("No sub-memories initialized yet.")
            else:
                for sm in sub_mems:
                    badge = "💜 PROFILE" if sm["theme"] == "PROFILE" else "🎯 JD"
                    st.markdown(f"**{sm['context_id']}** `[{badge}]`")
                    st.caption(f"Ref: {sm['source_ref']} | Status: `{sm['status']}` ({sm['turn_count']} turns)")
                    if sm.get("completed_dimensions"):
                        st.markdown(f"Probed: {', '.join(sm['completed_dimensions'])}")
                    if sm.get("pending_dimensions"):
                        st.markdown(f"Pending: {', '.join(sm['pending_dimensions'])}")
                    st.markdown("---")

        with st.expander("Anti-Duplication Registry", expanded=False):
            topics = orch.get("globally_covered_topics", [])
            if topics:
                for t in topics:
                    st.markdown(f"- `{t}`")
            else:
                st.caption("Registry clean.")

        # Download Audit JSON
        try:
            raw_transcript_resp = httpx.get(
                f"{api_url.rstrip('/')}/session/{st.session_state.session_id}/transcript",
                timeout=5.0,
            )
            if raw_transcript_resp.status_code == 200:
                st.download_button(
                    label="📥 Download Audit JSON",
                    data=raw_transcript_resp.text,
                    file_name=f"transcript_{st.session_state.session_id[:8]}.json",
                    mime="application/json",
                    use_container_width=True,
                )
        except Exception:
            pass


# --- MAIN CHAT PANEL ---
st.markdown('<div class="main-header">🎙️ AI Technical Interview Agent</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="sub-header">'
    'Grounding State Machine & 2-Theme Engine (Candidate Profile ↔ Job Description Scenarios) with Zero RAG.'
    '</div>',
    unsafe_allow_html=True,
)

if st.session_state.status == "idle":
    st.info("👈 Configure Candidate Dossier and Target Role (JD) in the sidebar, then click **'Start Interview Session'** to begin.")

# Active Dashboard Header (Live Timer, Theme & Rubric Trackers)
if st.session_state.status in ("active", "completed") and st.session_state.orchestration:
    orch = st.session_state.orchestration
    col_t1, col_t2, col_t3 = st.columns([1.2, 1.2, 1.4])

    with col_t1:
        min_rem = orch.get("minutes_remaining", 25.0)
        elapsed = orch.get("elapsed_minutes", 0.0)
        turns_count = len([m for m in st.session_state.messages if m["role"] == "assistant"])
        st.metric("⏱️ 25-Min Session Budget", f"{min_rem:.1f} min left", f"Elapsed: {elapsed:.1f} min")
        # Visual turn progress (max 12 turns)
        st.progress(min(1.0, turns_count / 12.0), text=f"Turn {turns_count} of 12 (Budget Guardrail)")

    with col_t2:
        active_theme = orch.get("active_theme", "PROFILE")
        theme_title = "💜 Theme 1: Candidate Profile" if active_theme == "PROFILE" else "🎯 Theme 2: Target Role JD"
        st.metric("Active Theme", theme_title)
        st.caption(f"Focus: `{orch.get('active_context_id', 'General')}`")

    with col_t3:
        curr_dim = orch.get("current_rubric_dimension", "clarity_of_framing")
        st.metric("Rubric Depth Ladder", curr_dim or "Complete")
        st.markdown(
            '<span class="rubric-pill">1. Framing</span> ➔ '
            '<span class="rubric-pill">2. Methodology</span> ➔ '
            '<span class="rubric-pill">3. Trade-offs</span>',
            unsafe_allow_html=True,
        )

    st.divider()

# Display Conversation History
for msg in st.session_state.messages:
    if msg["role"] == "assistant":
        with st.chat_message("assistant", avatar="🧑‍💼"):
            meta = msg.get("meta") or {}
            is_bridge = meta.get("is_bridge", False) or meta.get("turn_type") == "theme_switch"

            # Render Bridge Question Alert Callout only on actual theme switches
            if is_bridge:
                target_th = meta.get("theme") or ("JD" if meta.get("source") == "jd" else "PROFILE")
                st.markdown(
                    '<div class="bridge-banner">'
                    f'<strong>🌉 Seamless Theme Switch ➔ {target_th}:</strong> '
                    f'Connecting prior project decisions to target scenario <em>"{meta.get("source_ref")}"</em>'
                    '</div>',
                    unsafe_allow_html=True,
                )

            st.markdown(msg["content"])

            # Metadata Expander
            with st.expander("🔍 Turn Metadata & Rubric Anchor", expanded=False):
                col_m1, col_m2 = st.columns(2)
                with col_m1:
                    theme_val = meta.get("theme") or ("JD" if meta.get("source") == "jd" else "PROFILE")
                    badge_class = "badge-profile" if theme_val == "PROFILE" else "badge-jd"
                    src_raw = meta.get("source", "resume").upper()
                    src_detail = f" ({src_raw})" if theme_val == "PROFILE" else ""
                    st.markdown(f"**Theme:** <span class='tag-badge {badge_class}'>{theme_val}{src_detail}</span>", unsafe_allow_html=True)
                    st.markdown(f"**Turn Type:** `{meta.get('turn_type')}`")
                with col_m2:
                    st.markdown(f"**Source Ref:** `{meta.get('source_ref')}`")
                    if meta.get("reasoning_note"):
                        st.markdown(f"**Reasoning:** *{meta.get('reasoning_note')}*")

    elif msg["role"] == "user":
        with st.chat_message("user", avatar="💻"):
            st.markdown(msg["content"])

# Interview Completion Card
if st.session_state.status == "completed" and st.session_state.summary:
    st.success("### 🏁 Technical Interview Completed")
    summary = st.session_state.summary
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Resume Inquiries", summary.get("resume_questions_count", 0))
    c2.metric("GitHub Inquiries", summary.get("github_questions_count", 0))
    c3.metric("Follow-ups", summary.get("follow_up_count", 0))
    c4.metric("Context Switches", summary.get("context_switch_count", 0))

    st.markdown("#### Covered Topics & Scenarios:")
    for topic in summary.get("covered_topics", []):
        st.markdown(f"- `{topic}`")

# Candidate Submission Area with Hybrid JEV Evaluator Buttons
if st.session_state.status == "active":
    st.markdown("### Your Response")
    candidate_answer = st.text_area(
        "Candidate Answer:",
        height=100,
        placeholder="Walk through your architectural trade-offs, code choices, or concurrency patterns...",
        label_visibility="collapsed",
    )

    col_btn1, col_btn2, col_btn3 = st.columns([1.5, 1.8, 2.0])

    def submit_turn(signal: Optional[str] = None):
        if not candidate_answer.strip():
            st.warning("Please enter an answer before submitting.")
            return

        st.session_state.messages.append({"role": "user", "content": candidate_answer.strip()})

        with st.spinner("Interviewer analyzing response, checking grounding & advancing state machine..."):
            try:
                body: Dict[str, Any] = {"answer": candidate_answer.strip()}
                if signal:
                    body["jev_signal"] = signal

                resp = httpx.post(
                    f"{api_url.rstrip('/')}/session/{st.session_state.session_id}/answer",
                    json=body,
                    timeout=90.0,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    turn_data = data["turn"]
                    st.session_state.orchestration = data.get("orchestration")

                    active_theme = data.get("orchestration", {}).get("active_theme") or ("JD" if turn_data.get("source") == "jd" else "PROFILE")
                    is_bridge = data.get("orchestration", {}).get("is_bridge_turn", False) or turn_data.get("turn_type") == "theme_switch"
                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": turn_data["question"],
                        "meta": {
                            "turn_type": turn_data["turn_type"],
                            "source": turn_data["source"],
                            "source_ref": turn_data["source_ref"],
                            "reasoning_note": turn_data["reasoning_note"],
                            "theme": active_theme,
                            "is_bridge": is_bridge,
                        },
                    })
                    if turn_data.get("source_ref") and turn_data["turn_type"] != "closing":
                        st.session_state.covered_refs.append({
                            "turn_index": data["turn_index"],
                            "source": turn_data["source"],
                            "ref": turn_data["source_ref"],
                        })

                    if turn_data["turn_type"] == "closing":
                        st.session_state.status = "completed"

                    st.rerun()
                else:
                    st.error(f"Error {resp.status_code}: {resp.json().get('detail', resp.text)}")
            except httpx.TimeoutException:
                st.error(
                    "⏳ **Turn Response Timed Out (90s limit reached).**\n\n"
                    "The model took longer than 90s to generate a follow-up. Please try submitting again or switch to Mock LLM for rapid testing."
                )
            except Exception as e:
                st.error(f"Error submitting answer: {e}")

    with col_btn1:
        if st.button("💬 Submit Answer (Auto-Evaluate)", type="primary", use_container_width=True):
            submit_turn(signal=None)

    with col_btn2:
        if st.button("🔍 Submit & Force Follow-Up", use_container_width=True, help="Simulates JEV FOLLOW_UP to probe deeper along the rubric ladder"):
            submit_turn(signal="FOLLOW_UP")

    with col_btn3:
        if st.button("🌉 Submit & Force Theme Switch", use_container_width=True, help="Simulates JEV SWITCH_CONTEXT to trigger a seamless bridge question between PROFILE and JD"):
            submit_turn(signal="SWITCH_CONTEXT")

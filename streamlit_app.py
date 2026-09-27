import json
from pathlib import Path
import httpx
import streamlit as st

# Page Configuration
st.set_page_config(
    page_title="AI Technical Interview Agent",
    page_icon="🎙️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS for modern styling
st.markdown(
    """
    <style>
    .main-header {
        font-size: 2rem;
        font-weight: 700;
        margin-bottom: 0.2rem;
    }
    .sub-header {
        font-size: 1rem;
        color: #6c757d;
        margin-bottom: 1.5rem;
    }
    .meta-box {
        background-color: rgba(240, 242, 246, 0.5);
        border-left: 3px solid #0d6efd;
        padding: 8px 12px;
        margin-top: 6px;
        border-radius: 4px;
        font-size: 0.85rem;
    }
    .tag-badge {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 12px;
        font-weight: 600;
        font-size: 0.75rem;
        margin-right: 6px;
    }
    .tag-resume {
        background-color: #e3f2fd;
        color: #0d47a1;
        border: 1px solid #bbdefb;
    }
    .tag-github {
        background-color: #f3e5f5;
        color: #4a148c;
        border: 1px solid #e1bee7;
    }
    .tag-followup {
        background-color: #fff3e0;
        color: #e65100;
        border: 1px solid #ffe0b2;
    }
    .tag-switch {
        background-color: #e8f5e9;
        color: #1b5e20;
        border: 1px solid #c8e6c9;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# State Initialization
if "session_id" not in st.session_state:
    st.session_state.session_id = None
if "status" not in st.session_state:
    st.session_state.status = "idle"  # idle, active, completed
if "messages" not in st.session_state:
    st.session_state.messages = []
if "covered_refs" not in st.session_state:
    st.session_state.covered_refs = []
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
    st.title("🎙️ Interview Controls")

    # Backend Connection
    api_url = st.text_input("Backend API URL", value="http://127.0.0.1:8000")
    is_online = check_backend(api_url)

    if is_online:
        st.caption("🟢 **Backend Connected** (`/health` OK)")
    else:
        st.error("🔴 **Backend Offline** - Make sure FastAPI server is running (`uvicorn app.main:app`)")

    st.divider()

    # Session Status Indicator
    status_label = {
        "idle": "⚪ Not Started",
        "active": "🟢 Interview In Progress",
        "completed": "🏁 Interview Completed",
    }.get(st.session_state.status, "⚪ Idle")

    st.subheader(f"Status: {status_label}")
    if st.session_state.session_id:
        st.code(f"Session: {st.session_state.session_id[:8]}...", language="text")

    # Candidate Ingestion Form
    if st.session_state.status == "idle":
        st.subheader("LLM Provider")
        llm_provider_choice = st.radio(
            "Select Provider",
            ["Mock LLM (Instant Demo)", "OpenRouter (Cloud)", "Ollama (Local)"],
            index=0,
            horizontal=False,
        )

        def get_ollama_models() -> list[str]:
            try:
                resp = httpx.get("http://localhost:11434/api/tags", timeout=1.5)
                if resp.status_code == 200:
                    raw_models = [m["name"] for m in resp.json().get("models", [])]
                    # Put truly local models first; push :cloud models to the end
                    local = [m for m in raw_models if not m.endswith(":cloud")]
                    cloud = [m for m in raw_models if m.endswith(":cloud")]
                    return local + cloud
            except Exception:
                pass
            return []

        if llm_provider_choice == "Mock LLM (Instant Demo)":
            chosen_provider = "mock"
            chosen_model = "mock-interview-agent"
            st.caption("⚡ Realistic structured interviewer with zero setup/keys required.")
        elif llm_provider_choice == "Ollama (Local)":
            chosen_provider = "ollama"
            local_models = get_ollama_models()
            if local_models:
                # Find best available local model
                best_default = 0
                preferred_order = [
                    "llama3.2:latest",
                    "llama3.2",
                    "gemma4:latest",
                    "llama3.1:latest",
                    "llama3.1",
                    "llama3:latest",
                    "llama3",
                ]
                for pref in preferred_order:
                    if pref in local_models:
                        best_default = local_models.index(pref)
                        break

                chosen_model = st.selectbox(
                    "Ollama Model", local_models, index=best_default
                )
                if chosen_model.endswith(":cloud"):
                    st.warning("⚠️ This is an Ollama Cloud model and requires authentication ('ollama login'). Switch to a local model like 'llama3.2:latest' if not logged in.")
                else:
                    st.caption("🟢 Local offline Ollama model ready.")
            else:
                chosen_model = st.text_input("Ollama Model", value="llama3.2:latest")
                st.caption("⚠️ Ensure Ollama is running ('ollama serve') on port 11434.")
        else:
            chosen_provider = "openrouter"
            chosen_model = st.text_input(
                "OpenRouter Model", value="anthropic/claude-3.5-sonnet"
            )
            st.caption("Requires `OPENROUTER_API_KEY` in `.env`.")

        st.divider()
        st.subheader("Candidate Dossier Setup")
        github_input = st.text_input(
            "GitHub Username or Profile URL",
            value="octocat",
            help="Enter public handle (e.g. 'octocat') or full URL (e.g. 'https://github.com/octocat')",
        )
        use_mock_git = st.checkbox(
            "Use Mock GitHub Portfolio (Fast & Rate-limit Free)",
            value=True,
            help="Provides immediate access to mock projects without hitting GitHub API rate limits.",
        )

        # Resume input options
        resume_mode = st.radio("Resume Input Method", ["Sample Resume", "Upload File", "Paste Text"], horizontal=True)
        resume_text_to_send = ""
        resume_file_to_send = None

        if resume_mode == "Sample Resume":
            sample_path = Path("sample_resume.txt")
            if sample_path.exists():
                resume_text_to_send = sample_path.read_text(encoding="utf-8")
                st.info("Loaded `sample_resume.txt` (Distributed Systems Engineer).")
            else:
                st.warning("sample_resume.txt not found in workspace.")
        elif resume_mode == "Upload File":
            uploaded_file = st.file_uploader("Upload Resume (.txt, .md, .pdf)", type=["txt", "md", "pdf"])
            if uploaded_file:
                # Save uploaded file temporarily for loader
                temp_dir = Path("scratch/uploads")
                temp_dir.mkdir(parents=True, exist_ok=True)
                temp_file = temp_dir / uploaded_file.name
                temp_file.write_bytes(uploaded_file.getvalue())
                resume_file_to_send = str(temp_file.resolve())
                st.success(f"Ready: {uploaded_file.name}")
        else:
            resume_text_to_send = st.text_area("Paste Resume Text", height=150, placeholder="Paste resume plain text here...")

        if st.button("🚀 Start Interview", type="primary", use_container_width=True, disabled=not is_online):
            with st.spinner("Ingesting Resume & GitHub profile... Initializing state machine..."):
                try:
                    payload = {
                        "llm_provider": chosen_provider,
                        "model_name": chosen_model,
                        "use_mock_github": use_mock_git,
                    }
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

                    resp = httpx.post(f"{api_url.rstrip('/')}/session/start", json=payload, timeout=120.0)

                    if resp.status_code == 201:
                        data = resp.json()
                        st.session_state.session_id = data["session_id"]
                        st.session_state.status = "active"
                        st.session_state.messages = []
                        st.session_state.covered_refs = []
                        st.session_state.summary = None

                        turn_data = data["turn"]
                        st.session_state.messages.append({
                            "role": "assistant",
                            "content": turn_data["question"],
                            "meta": {
                                "turn_type": turn_data["turn_type"],
                                "source": turn_data["source"],
                                "source_ref": turn_data["source_ref"],
                                "reasoning_note": turn_data["reasoning_note"],
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
                except Exception as err:
                    st.error(f"Failed to start interview: {err}")

    # Active Session Actions
    if st.session_state.status in ("active", "completed"):
        col1, col2 = st.columns(2)
        with col1:
            if st.session_state.status == "active":
                if st.button("🛑 End Interview", use_container_width=True):
                    with st.spinner("Concluding interview session..."):
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
                st.session_state.summary = None
                st.rerun()

        st.divider()

        # Telemetry & Covered References Inspector
        st.subheader("Traceability & Memory")
        st.metric("Total Turns", len([m for m in st.session_state.messages if m["role"] == "assistant"]))
        st.metric("Covered Topics", len(st.session_state.covered_refs))

        with st.expander("Tracked References (`covered_refs`)", expanded=False):
            if not st.session_state.covered_refs:
                st.caption("No topics registered yet.")
            else:
                for item in st.session_state.covered_refs:
                    source_icon = "📄" if item["source"] == "resume" else "🐙"
                    st.markdown(f"**Turn {item.get('turn_index')}** {source_icon} `[{item['source']}]`")
                    st.caption(f"{item['ref']}")

        # Full Transcript Download
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
st.markdown('<div class="main-header">AI Technical Interview Agent</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="sub-header">'
    'Stateful, claim-grounded interviewer with dynamic context switching (Resume ↔ GitHub) and zero RAG.'
    '</div>',
    unsafe_allow_html=True,
)

if st.session_state.status == "idle":
    st.info("👈 Set up candidate resume and GitHub username in the sidebar and click **'Start Interview'** to begin.")

# Display Conversation History
for msg in st.session_state.messages:
    if msg["role"] == "assistant":
        with st.chat_message("assistant", avatar="🧑‍💼"):
            st.markdown(msg["content"])
            meta = msg.get("meta")
            if meta:
                # Render metadata tags
                turn_type = meta.get("turn_type", "")
                source = meta.get("source", "")
                source_ref = meta.get("source_ref", "")
                reasoning = meta.get("reasoning_note", "")

                with st.expander("🔍 Interviewer Reasoning & Metadata", expanded=False):
                    col_a, col_b = st.columns(2)
                    with col_a:
                        st.markdown(f"**Turn Intent**: `{turn_type}`")
                        st.markdown(f"**Source**: `{source}`")
                    with col_b:
                        st.markdown(f"**Grounded Reference**: `{source_ref}`")
                    if reasoning:
                        st.markdown(f"**Internal Reasoning**: *{reasoning}*")
    elif msg["role"] == "user":
        with st.chat_message("user", avatar="💻"):
            st.markdown(msg["content"])

# Completion Summary Card
if st.session_state.status == "completed" and st.session_state.summary:
    st.success("### 🏁 Interview Completed")
    summary = st.session_state.summary
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Resume Probes", summary.get("resume_questions_count", 0))
    c2.metric("GitHub Probes", summary.get("github_questions_count", 0))
    c3.metric("Skill Anchors", summary.get("skill_anchored_count", 0))
    c4.metric("Follow-ups", summary.get("follow_up_count", 0))
    c5.metric("Context Switches", summary.get("context_switch_count", 0))

    st.markdown("#### Topics Explored:")
    for topic in summary.get("covered_topics", []):
        st.markdown(f"- {topic}")

# Candidate Input Box
if st.session_state.status == "active":
    if prompt := st.chat_input("Type your technical answer here..."):
        # 1. Immediately render candidate answer
        st.session_state.messages.append({"role": "user", "content": prompt})

        # 2. Call backend answer endpoint
        with st.spinner("Interviewer is reasoning over your answer and selecting focus..."):
            try:
                resp = httpx.post(
                    f"{api_url.rstrip('/')}/session/{st.session_state.session_id}/answer",
                    json={"answer": prompt},
                    timeout=120.0,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    turn_data = data["turn"]
                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": turn_data["question"],
                        "meta": {
                            "turn_type": turn_data["turn_type"],
                            "source": turn_data["source"],
                            "source_ref": turn_data["source_ref"],
                            "reasoning_note": turn_data["reasoning_note"],
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
            except Exception as e:
                st.error(f"Error submitting answer: {e}")

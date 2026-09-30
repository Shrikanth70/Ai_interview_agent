"""Interactive Localhost Visualizer for AI Interview Agent Codebase & Wiki.

Launch via:
    python visualize.py
or
    python -m wiki.visualize

Spins up a lightweight localhost HTTP server and opens your browser to explore
the interactive graph of the architecture, memory model, agent engine, and wiki docs.
"""

from __future__ import annotations

import json
import mimetypes
import os
import socket
import sys
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

# Base directories
BASE_DIR = Path(__file__).resolve().parent
WIKI_DIR = BASE_DIR / "wiki"
APP_DIR = BASE_DIR / "app"
TESTS_DIR = BASE_DIR / "tests"

# ---------------------------------------------------------------------------
# Graph Dataset Definition (Codebase, State Machine, Wiki, Tests)
# ---------------------------------------------------------------------------

GRAPH_DATA = {
    "nodes": [
        # --- API Layer ---
        {
            "id": "app/main.py",
            "label": "app/main.py",
            "group": "api",
            "title": "FastAPI Entrypoint",
            "path": "app/main.py",
            "role": "Application entrypoint, CORS configuration, system health check, and router mounting.",
            "symbols": ["app", "health_check()", "root()"],
            "layer": "API & Routing",
        },
        {
            "id": "app/api/routes.py",
            "label": "app/api/routes.py",
            "group": "api",
            "title": "Session REST Router",
            "path": "app/api/routes.py",
            "role": "Handles /session/start, /session/submit-answer, /session/{id}/end, and /session/{id}/transcript.",
            "symbols": ["start_session()", "submit_answer()", "end_session()", "get_transcript()", "get_agent()"],
            "layer": "API & Routing",
        },
        {
            "id": "app/api/models.py",
            "label": "app/api/models.py",
            "group": "api",
            "title": "Pydantic API Schemas",
            "path": "app/api/models.py",
            "role": "Validates all incoming requests and outgoing responses using Pydantic v2 schemas.",
            "symbols": ["StartSessionRequest", "StartSessionResponse", "SubmitAnswerRequest", "SubmitAnswerResponse", "SessionSummary"],
            "layer": "API & Routing",
        },

        # --- Agent & Orchestration Layer ---
        {
            "id": "app/agent/interviewer.py",
            "label": "app/agent/interviewer.py",
            "group": "agent",
            "title": "InterviewerAgent (Core Engine)",
            "path": "app/agent/interviewer.py",
            "role": "Stateful interviewer orchestrating turns, 2-theme engine (PROFILE vs JD), JEV signal processing (FOLLOW_UP vs SWITCH_CONTEXT), bridge questions, and 25-minute timer cutoff.",
            "symbols": ["InterviewerAgent", "run_turn()", "synthesize_opening_question()", "generate_bridge_question()", "_enforce_budget_cutoff()"],
            "layer": "Core Agent",
        },
        {
            "id": "app/agent/theme_fetcher.py",
            "label": "app/agent/theme_fetcher.py",
            "group": "agent",
            "title": "ThemeMemoryFetchTool (Zero-RAG)",
            "path": "app/agent/theme_fetcher.py",
            "role": "Deterministic scoped memory retrieval tool. Fetches single-context slices or composite anchor+target bridge slices without vector DB or embeddings.",
            "symbols": ["ThemeMemoryFetchTool", "fetch_scoped_context()", "fetch_bridge_context()", "ScopedContextSlice", "BridgeContextSlice"],
            "layer": "Core Agent",
        },
        {
            "id": "app/agent/grounding.py",
            "label": "app/agent/grounding.py",
            "group": "agent",
            "title": "Grounding & Anti-Hallucination",
            "path": "app/agent/grounding.py",
            "role": "2-tier verification engine. Validates source_ref claims against resume, GitHub repos, and JD criteria with safe fallback.",
            "symbols": ["is_source_ref_grounded()", "build_safe_fallback_question()", "validate_turn_grounding()"],
            "layer": "Core Agent",
        },

        # --- Memory & State Layer ---
        {
            "id": "app/session/state.py",
            "label": "app/session/state.py",
            "group": "state",
            "title": "Hierarchical Session State",
            "path": "app/session/state.py",
            "role": "Hierarchical 3-tier memory model: Global SessionState, Scoped ContextSubMemory, SessionBudget (25-min cutoff), and TurnRecord history.",
            "symbols": ["SessionState", "ContextSubMemory", "SessionBudget", "TurnRecord", "OrchestrationState"],
            "layer": "State & Memory",
        },
        {
            "id": "app/session/store.py",
            "label": "app/session/store.py",
            "group": "state",
            "title": "In-Memory Session Store",
            "path": "app/session/store.py",
            "role": "Thread-safe in-memory session registry providing fast O(1) state lookups and persistence.",
            "symbols": ["SessionStore", "get_session_store()", "get()", "save()", "delete()"],
            "layer": "State & Memory",
        },

        # --- LLM & Prompts Layer ---
        {
            "id": "app/llm/client.py",
            "label": "app/llm/client.py",
            "group": "llm",
            "title": "OpenRouter LLM Client",
            "path": "app/llm/client.py",
            "role": "Async OpenRouter API client with JSON mode enforcement, model routing, and automatic fallback.",
            "symbols": ["LLMClient", "generate_turn_question()", "call_openrouter()"],
            "layer": "LLM & Prompts",
        },
        {
            "id": "app/llm/prompts.py",
            "label": "app/llm/prompts.py",
            "group": "llm",
            "title": "Scoped Prompt Generators",
            "path": "app/llm/prompts.py",
            "role": "Formats scoped turn prompts (single context) and composite bridge prompts (anchor to target transition) under 1,200 tokens.",
            "symbols": ["format_scoped_turn_prompt()", "format_bridge_turn_prompt()", "SYSTEM_PROMPT_INTERVIEWER"],
            "layer": "LLM & Prompts",
        },

        # --- Ingestion Layer ---
        {
            "id": "app/ingestion/resume_loader.py",
            "label": "app/ingestion/resume_loader.py",
            "group": "ingestion",
            "title": "Resume Ingestion Loader",
            "path": "app/ingestion/resume_loader.py",
            "role": "PDF extraction (pdfplumber/pypdf) and structured section parser (skills, work history, projects).",
            "symbols": ["load_resume()", "extract_pdf_text()", "parse_resume_sections()"],
            "layer": "Ingestion",
        },
        {
            "id": "app/ingestion/github_loader.py",
            "label": "app/ingestion/github_loader.py",
            "group": "ingestion",
            "title": "GitHub Profile Loader",
            "path": "app/ingestion/github_loader.py",
            "role": "Async GitHub API loader: extracts public repositories, commit signals, language stats, and README summaries.",
            "symbols": ["fetch_github_profile()", "summarize_repository()", "extract_tech_stack()"],
            "layer": "Ingestion",
        },

        # --- Wiki Documentation Nodes ---
        {
            "id": "wiki/INDEX.md",
            "label": "wiki/INDEX.md",
            "group": "wiki",
            "title": "Master Architecture Index",
            "path": "wiki/INDEX.md",
            "role": "Master graph index, core system invariants (No RAG, 25-min cutoff, JEV signal handshake) and documentation sitemap.",
            "symbols": ["# Master Architecture Index", "Core Invariants", "Sitemap"],
            "layer": "Documentation",
        },
        {
            "id": "wiki/01_SYSTEM_ARCHITECTURE.md",
            "label": "wiki/01_SYSTEM_ARCHITECTURE.md",
            "group": "wiki",
            "title": "01. System Architecture",
            "path": "wiki/01_SYSTEM_ARCHITECTURE.md",
            "role": "Complete system topology, component dependency graph, request lifecycle flow, and module boundaries.",
            "symbols": ["System Topology", "Module Dependency Map", "Request Turn Lifecycle"],
            "layer": "Documentation",
        },
        {
            "id": "wiki/02_MEMORY_AND_STATE_GRAPH.md",
            "label": "wiki/02_MEMORY_AND_STATE_GRAPH.md",
            "group": "wiki",
            "title": "02. Memory & State Graph",
            "path": "wiki/02_MEMORY_AND_STATE_GRAPH.md",
            "role": "3-Tier Hierarchical memory graph, Sub-memory lifecycle, state transition diagram, and session budget enforcement.",
            "symbols": ["Hierarchical Memory Architecture", "Sub-Memory Lifecycle", "State Transition Diagram"],
            "layer": "Documentation",
        },
        {
            "id": "wiki/03_THEMES_AND_INTERVIEWER.md",
            "label": "wiki/03_THEMES_AND_INTERVIEWER.md",
            "group": "wiki",
            "title": "03. Themes & Interviewer",
            "path": "wiki/03_THEMES_AND_INTERVIEWER.md",
            "role": "2-Theme engine (PROFILE vs JD), JEV signal evaluator handshake, rubric depth ladder, and seamless bridge question transitions.",
            "symbols": ["Theme Selection", "JEV Signal Flow", "Bridge Transitions", "Rubric Ladder"],
            "layer": "Documentation",
        },
        {
            "id": "wiki/04_GROUNDING_AND_GUARDRAILS.md",
            "label": "wiki/04_GROUNDING_AND_GUARDRAILS.md",
            "group": "wiki",
            "title": "04. Grounding & Guardrails",
            "path": "wiki/04_GROUNDING_AND_GUARDRAILS.md",
            "role": "Anti-hallucination verification, 2-tier citation matching, safe fallback generator, and testable invariants.",
            "symbols": ["2-Tier Validation Pipeline", "Fallback Generator", "Grounding Flow"],
            "layer": "Documentation",
        },
        {
            "id": "wiki/05_INGESTION_PIPELINE.md",
            "label": "wiki/05_INGESTION_PIPELINE.md",
            "group": "wiki",
            "title": "05. Ingestion Pipeline",
            "path": "wiki/05_INGESTION_PIPELINE.md",
            "role": "Resume PDF extraction, GitHub repo profiling, sub-memory initial seeding, and standalone test CLI commands.",
            "symbols": ["Ingestion Architecture", "Sub-Memory Seeding", "CLI Execution"],
            "layer": "Documentation",
        },
        {
            "id": "wiki/06_API_AND_LIFECYCLE.md",
            "label": "wiki/06_API_AND_LIFECYCLE.md",
            "group": "wiki",
            "title": "06. API & Lifecycle",
            "path": "wiki/06_API_AND_LIFECYCLE.md",
            "role": "FastAPI REST API specification, request/response models, turn orchestration sequence, and error codes.",
            "symbols": ["Endpoint Specifications", "Sequence Diagram", "Error Matrix"],
            "layer": "Documentation",
        },

        # --- Test Suite Nodes ---
        {
            "id": "tests/test_interviewer_scoped_turns.py",
            "label": "tests/test_interviewer_scoped_turns.py",
            "group": "tests",
            "title": "Interviewer Unit Tests",
            "path": "tests/test_interviewer_scoped_turns.py",
            "role": "Verifies turn execution, JEV signal handling, bridge question generation, and 25-minute timer cutoff.",
            "symbols": ["test_run_turn_followup()", "test_run_turn_switch_context()", "test_budget_cutoff()"],
            "layer": "Test Suite",
        },
        {
            "id": "tests/test_theme_fetcher.py",
            "label": "tests/test_theme_fetcher.py",
            "group": "tests",
            "title": "Theme Fetcher Tests",
            "path": "tests/test_theme_fetcher.py",
            "role": "Validates deterministic scoped context retrieval (single slice and composite bridge slice).",
            "symbols": ["test_fetch_scoped_context()", "test_fetch_bridge_context()"],
            "layer": "Test Suite",
        },
        {
            "id": "tests/test_hierarchical_memory.py",
            "label": "tests/test_hierarchical_memory.py",
            "group": "tests",
            "title": "Memory State Tests",
            "path": "tests/test_hierarchical_memory.py",
            "role": "Validates SessionState, ContextSubMemory mutations, SessionBudget time calculations, and TurnRecord appending.",
            "symbols": ["test_sub_memory_creation()", "test_budget_time_remaining()"],
            "layer": "Test Suite",
        },
        {
            "id": "tests/test_e2e_hierarchical_interview.py",
            "label": "tests/test_e2e_hierarchical_interview.py",
            "group": "tests",
            "title": "End-to-End Interview Tests",
            "path": "tests/test_e2e_hierarchical_interview.py",
            "role": "Full multi-turn simulation testing Turn 1 opening, follow-ups, bridge switches, and graceful timer termination.",
            "symbols": ["test_e2e_multi_turn_interview()"],
            "layer": "Test Suite",
        },
    ],
    "edges": [
        # API connections
        {"from": "app/main.py", "to": "app/api/routes.py", "label": "mounts_router", "type": "route"},
        {"from": "app/api/routes.py", "to": "app/api/models.py", "label": "validates_schemas", "type": "schema"},
        {"from": "app/api/routes.py", "to": "app/session/store.py", "label": "persists_state", "type": "storage"},
        {"from": "app/api/routes.py", "to": "app/agent/interviewer.py", "label": "dispatches_turns", "type": "dispatch"},
        {"from": "app/api/routes.py", "to": "app/ingestion/resume_loader.py", "label": "ingests_resume", "type": "ingest"},
        {"from": "app/api/routes.py", "to": "app/ingestion/github_loader.py", "label": "ingests_github", "type": "ingest"},

        # Agent & Memory connections
        {"from": "app/agent/interviewer.py", "to": "app/agent/theme_fetcher.py", "label": "fetches_scoped_slice", "type": "fetch"},
        {"from": "app/agent/interviewer.py", "to": "app/llm/prompts.py", "label": "formats_prompt", "type": "call"},
        {"from": "app/agent/interviewer.py", "to": "app/llm/client.py", "label": "calls_llm", "type": "call"},
        {"from": "app/agent/interviewer.py", "to": "app/agent/grounding.py", "label": "validates_citations", "type": "validate"},
        {"from": "app/agent/interviewer.py", "to": "app/session/state.py", "label": "updates_state", "type": "state"},
        {"from": "app/agent/theme_fetcher.py", "to": "app/session/state.py", "label": "reads_sub_memories", "type": "state"},
        {"from": "app/agent/grounding.py", "to": "app/session/state.py", "label": "verifies_source_refs", "type": "validate"},
        {"from": "app/session/store.py", "to": "app/session/state.py", "label": "manages_instances", "type": "storage"},

        # Wiki Documentation Links
        {"from": "wiki/INDEX.md", "to": "wiki/01_SYSTEM_ARCHITECTURE.md", "label": "links_to", "type": "doc"},
        {"from": "wiki/INDEX.md", "to": "wiki/02_MEMORY_AND_STATE_GRAPH.md", "label": "links_to", "type": "doc"},
        {"from": "wiki/INDEX.md", "to": "wiki/03_THEMES_AND_INTERVIEWER.md", "label": "links_to", "type": "doc"},
        {"from": "wiki/INDEX.md", "to": "wiki/04_GROUNDING_AND_GUARDRAILS.md", "label": "links_to", "type": "doc"},
        {"from": "wiki/INDEX.md", "to": "wiki/05_INGESTION_PIPELINE.md", "label": "links_to", "type": "doc"},
        {"from": "wiki/INDEX.md", "to": "wiki/06_API_AND_LIFECYCLE.md", "label": "links_to", "type": "doc"},

        {"from": "wiki/01_SYSTEM_ARCHITECTURE.md", "to": "app/main.py", "label": "documents", "type": "doc"},
        {"from": "wiki/01_SYSTEM_ARCHITECTURE.md", "to": "app/agent/interviewer.py", "label": "documents", "type": "doc"},
        {"from": "wiki/02_MEMORY_AND_STATE_GRAPH.md", "to": "app/session/state.py", "label": "documents", "type": "doc"},
        {"from": "wiki/02_MEMORY_AND_STATE_GRAPH.md", "to": "app/agent/theme_fetcher.py", "label": "documents", "type": "doc"},
        {"from": "wiki/03_THEMES_AND_INTERVIEWER.md", "to": "app/agent/interviewer.py", "label": "documents", "type": "doc"},
        {"from": "wiki/03_THEMES_AND_INTERVIEWER.md", "to": "app/llm/prompts.py", "label": "documents", "type": "doc"},
        {"from": "wiki/04_GROUNDING_AND_GUARDRAILS.md", "to": "app/agent/grounding.py", "label": "documents", "type": "doc"},
        {"from": "wiki/05_INGESTION_PIPELINE.md", "to": "app/ingestion/resume_loader.py", "label": "documents", "type": "doc"},
        {"from": "wiki/05_INGESTION_PIPELINE.md", "to": "app/ingestion/github_loader.py", "label": "documents", "type": "doc"},
        {"from": "wiki/06_API_AND_LIFECYCLE.md", "to": "app/api/routes.py", "label": "documents", "type": "doc"},

        # Tests Coverage
        {"from": "tests/test_interviewer_scoped_turns.py", "to": "app/agent/interviewer.py", "label": "tests", "type": "test"},
        {"from": "tests/test_theme_fetcher.py", "to": "app/agent/theme_fetcher.py", "label": "tests", "type": "test"},
        {"from": "tests/test_hierarchical_memory.py", "to": "app/session/state.py", "label": "tests", "type": "test"},
        {"from": "tests/test_e2e_hierarchical_interview.py", "to": "app/agent/interviewer.py", "label": "tests", "type": "test"},
    ]
}


# ---------------------------------------------------------------------------
# Visualizer Web Application HTML/JS/CSS Template
# ---------------------------------------------------------------------------

INDEX_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>AI Interview Agent — Codebase & Wiki Visualizer</title>
  
  <!-- Fonts -->
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&family=Outfit:wght@400;500;600;700&display=swap" rel="stylesheet">
  
  <!-- Vis-Network for Graph Physics -->
  <script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
  <!-- Marked for Live Markdown Rendering -->
  <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
  
  <style>
    :root {
      --bg-primary: #0a0d14;
      --bg-surface: #111726;
      --bg-surface-elevated: #182238;
      --border-subtle: #202e4c;
      --border-focus: #3b82f6;
      --text-main: #f1f5f9;
      --text-muted: #94a3b8;
      --text-dim: #64748b;
      
      --color-agent: #8b5cf6;
      --color-state: #3b82f6;
      --color-api: #10b981;
      --color-llm: #f59e0b;
      --color-ingestion: #06b6d4;
      --color-wiki: #f43f5e;
      --color-tests: #14b8a6;
    }
    
    * {
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }
    
    body {
      font-family: 'Outfit', sans-serif;
      background: var(--bg-primary);
      color: var(--text-main);
      overflow: hidden;
      height: 100vh;
      display: flex;
      flex-direction: column;
    }
    
    /* Top Header Bar */
    header {
      height: 60px;
      background: rgba(17, 23, 38, 0.85);
      backdrop-filter: blur(12px);
      border-bottom: 1px solid var(--border-subtle);
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0 24px;
      z-index: 20;
    }
    
    .brand {
      display: flex;
      align-items: center;
      gap: 12px;
    }
    
    .brand-icon {
      width: 32px;
      height: 32px;
      background: linear-gradient(135deg, #3b82f6, #8b5cf6);
      border-radius: 8px;
      display: flex;
      align-items: center;
      justify-content: center;
      font-weight: 700;
      font-size: 16px;
      box-shadow: 0 0 16px rgba(139, 92, 246, 0.4);
    }
    
    .brand h1 {
      font-size: 17px;
      font-weight: 600;
      letter-spacing: -0.02em;
    }
    
    .brand .subtitle {
      font-size: 12px;
      color: var(--text-muted);
      font-family: 'JetBrains Mono', monospace;
      margin-left: 4px;
    }
    
    .header-actions {
      display: flex;
      align-items: center;
      gap: 12px;
    }
    
    .search-box {
      position: relative;
    }
    
    .search-box input {
      background: var(--bg-surface-elevated);
      border: 1px solid var(--border-subtle);
      border-radius: 8px;
      padding: 6px 14px 6px 32px;
      color: var(--text-main);
      font-size: 13px;
      width: 240px;
      outline: none;
      transition: all 0.2s;
    }
    
    .search-box input:focus {
      border-color: var(--border-focus);
      width: 280px;
      box-shadow: 0 0 12px rgba(59, 130, 246, 0.3);
    }
    
    .search-icon {
      position: absolute;
      left: 10px;
      top: 50%;
      transform: translateY(-50%);
      color: var(--text-dim);
      font-size: 13px;
      pointer-events: none;
    }
    
    .btn {
      background: var(--bg-surface-elevated);
      border: 1px solid var(--border-subtle);
      color: var(--text-main);
      padding: 6px 14px;
      border-radius: 8px;
      font-size: 13px;
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 6px;
      transition: all 0.15s ease;
      font-weight: 500;
    }
    
    .btn:hover {
      background: var(--border-subtle);
      border-color: #3b82f6;
    }
    
    .btn.active {
      background: #3b82f6;
      border-color: #3b82f6;
      color: #fff;
    }
    
    /* Main Layout */
    .app-body {
      flex: 1;
      display: flex;
      position: relative;
      overflow: hidden;
    }
    
    /* Left Filter Chips Floating Bar */
    .filter-bar {
      position: absolute;
      top: 16px;
      left: 20px;
      z-index: 10;
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      background: rgba(17, 23, 38, 0.85);
      backdrop-filter: blur(10px);
      padding: 8px 12px;
      border-radius: 12px;
      border: 1px solid var(--border-subtle);
      box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
    }
    
    .filter-chip {
      font-size: 11px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      padding: 4px 10px;
      border-radius: 6px;
      cursor: pointer;
      border: 1px solid transparent;
      background: rgba(255, 255, 255, 0.05);
      color: var(--text-muted);
      transition: all 0.15s;
    }
    
    .filter-chip:hover {
      background: rgba(255, 255, 255, 0.12);
      color: var(--text-main);
    }
    
    .filter-chip.active {
      color: #fff;
    }
    
    .filter-chip[data-layer="all"].active { background: #475569; }
    .filter-chip[data-layer="agent"].active { background: var(--color-agent); }
    .filter-chip[data-layer="state"].active { background: var(--color-state); }
    .filter-chip[data-layer="api"].active { background: var(--color-api); }
    .filter-chip[data-layer="ingestion"].active { background: var(--color-ingestion); }
    .filter-chip[data-layer="llm"].active { background: var(--color-llm); }
    .filter-chip[data-layer="wiki"].active { background: var(--color-wiki); }
    .filter-chip[data-layer="tests"].active { background: var(--color-tests); }

    /* Graph Canvas */
    #network-canvas {
      flex: 1;
      height: 100%;
      background: radial-gradient(circle at 50% 50%, #111827 0%, #0a0d14 100%);
    }

    /* Floating Graph Controls Bottom Left */
    .graph-controls {
      position: absolute;
      bottom: 20px;
      left: 20px;
      z-index: 10;
      display: flex;
      gap: 8px;
      background: rgba(17, 23, 38, 0.85);
      backdrop-filter: blur(10px);
      padding: 6px;
      border-radius: 10px;
      border: 1px solid var(--border-subtle);
    }
    
    .ctrl-btn {
      width: 32px;
      height: 32px;
      display: flex;
      align-items: center;
      justify-content: center;
      background: transparent;
      border: none;
      color: var(--text-muted);
      cursor: pointer;
      border-radius: 6px;
      font-size: 15px;
      transition: all 0.15s;
    }
    
    .ctrl-btn:hover {
      background: var(--bg-surface-elevated);
      color: var(--text-main);
    }
    
    /* Preset Pathways Selector */
    .flow-tour-bar {
      position: absolute;
      top: 16px;
      right: 440px;
      z-index: 10;
      display: flex;
      align-items: center;
      gap: 8px;
      background: rgba(17, 23, 38, 0.85);
      backdrop-filter: blur(10px);
      padding: 6px 12px;
      border-radius: 10px;
      border: 1px solid var(--border-subtle);
    }
    
    .flow-tour-bar label {
      font-size: 12px;
      color: var(--text-muted);
      font-weight: 500;
    }
    
    .flow-select {
      background: var(--bg-surface-elevated);
      color: var(--text-main);
      border: 1px solid var(--border-subtle);
      border-radius: 6px;
      font-size: 12px;
      padding: 4px 8px;
      outline: none;
      cursor: pointer;
    }

    /* Right Details Inspector Panel */
    .inspector-panel {
      width: 420px;
      background: var(--bg-surface);
      border-left: 1px solid var(--border-subtle);
      display: flex;
      flex-direction: column;
      height: 100%;
      z-index: 15;
      transition: transform 0.25s cubic-bezier(0.16, 1, 0.3, 1);
    }
    
    .inspector-panel.collapsed {
      transform: translateX(100%);
    }
    
    .inspector-header {
      padding: 18px 20px;
      border-bottom: 1px solid var(--border-subtle);
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 12px;
    }
    
    .node-badge {
      display: inline-block;
      font-size: 10px;
      font-weight: 700;
      text-transform: uppercase;
      padding: 2px 8px;
      border-radius: 4px;
      letter-spacing: 0.06em;
      margin-bottom: 6px;
    }
    
    .inspector-header h2 {
      font-size: 18px;
      font-weight: 600;
      line-height: 1.3;
    }
    
    .node-filepath {
      font-family: 'JetBrains Mono', monospace;
      font-size: 12px;
      color: var(--text-muted);
      margin-top: 4px;
      word-break: break-all;
    }
    
    .close-inspector {
      background: transparent;
      border: none;
      color: var(--text-dim);
      font-size: 18px;
      cursor: pointer;
      padding: 4px;
    }
    
    .close-inspector:hover {
      color: var(--text-main);
    }
    
    /* Inspector Tabs */
    .inspector-tabs {
      display: flex;
      border-bottom: 1px solid var(--border-subtle);
      background: var(--bg-primary);
    }
    
    .tab-btn {
      flex: 1;
      padding: 10px 0;
      background: transparent;
      border: none;
      border-bottom: 2px solid transparent;
      color: var(--text-muted);
      font-size: 12px;
      font-weight: 600;
      cursor: pointer;
      text-align: center;
      transition: all 0.15s;
    }
    
    .tab-btn.active {
      color: #3b82f6;
      border-bottom-color: #3b82f6;
      background: var(--bg-surface);
    }
    
    .inspector-content {
      flex: 1;
      overflow-y: auto;
      padding: 20px;
    }
    
    .section-title {
      font-size: 11px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--text-dim);
      margin-bottom: 8px;
    }
    
    .role-card {
      background: var(--bg-surface-elevated);
      border-radius: 8px;
      padding: 14px;
      font-size: 13px;
      line-height: 1.5;
      color: var(--text-main);
      border-left: 3px solid #3b82f6;
      margin-bottom: 20px;
    }
    
    .symbol-tags {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin-bottom: 20px;
    }
    
    .symbol-tag {
      font-family: 'JetBrains Mono', monospace;
      font-size: 11px;
      background: rgba(255, 255, 255, 0.05);
      border: 1px solid var(--border-subtle);
      padding: 4px 8px;
      border-radius: 4px;
      color: #93c5fd;
    }
    
    .neighbor-list {
      display: flex;
      flex-direction: column;
      gap: 8px;
      margin-bottom: 20px;
    }
    
    .neighbor-item {
      display: flex;
      align-items: center;
      justify-content: space-between;
      background: var(--bg-surface-elevated);
      border: 1px solid var(--border-subtle);
      border-radius: 6px;
      padding: 8px 12px;
      font-size: 12px;
      cursor: pointer;
      transition: all 0.15s;
    }
    
    .neighbor-item:hover {
      border-color: #3b82f6;
      transform: translateX(2px);
    }
    
    .neighbor-item .relation {
      font-family: 'JetBrains Mono', monospace;
      font-size: 10px;
      color: var(--text-dim);
    }
    
    /* Markdown Preview */
    .markdown-container {
      font-size: 13px;
      line-height: 1.6;
      color: #cbd5e1;
    }
    
    .markdown-container h1, .markdown-container h2, .markdown-container h3 {
      color: #f8fafc;
      margin-top: 16px;
      margin-bottom: 8px;
      font-weight: 600;
    }
    
    .markdown-container h1 { font-size: 18px; border-bottom: 1px solid var(--border-subtle); padding-bottom: 6px; }
    .markdown-container h2 { font-size: 15px; }
    .markdown-container h3 { font-size: 13px; }
    
    .markdown-container pre {
      background: #06090e;
      padding: 12px;
      border-radius: 6px;
      overflow-x: auto;
      font-family: 'JetBrains Mono', monospace;
      font-size: 11px;
      margin: 10px 0;
      border: 1px solid var(--border-subtle);
    }
    
    .markdown-container code {
      font-family: 'JetBrains Mono', monospace;
      font-size: 11px;
      background: rgba(255, 255, 255, 0.08);
      padding: 2px 4px;
      border-radius: 4px;
      color: #38bdf8;
    }
    
    .markdown-container ul, .markdown-container ol {
      padding-left: 20px;
      margin-bottom: 12px;
    }
    
    .markdown-container table {
      width: 100%;
      border-collapse: collapse;
      margin: 12px 0;
      font-size: 11px;
    }
    
    .markdown-container th, .markdown-container td {
      border: 1px solid var(--border-subtle);
      padding: 6px 10px;
      text-align: left;
    }
    
    .markdown-container th {
      background: var(--bg-surface-elevated);
      color: #f1f5f9;
    }
    
    /* Empty State */
    .empty-state {
      height: 100%;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      text-align: center;
      color: var(--text-dim);
      padding: 20px;
    }
    
    .empty-state-icon {
      font-size: 40px;
      margin-bottom: 12px;
      opacity: 0.5;
    }
  </style>
</head>
<body>

  <!-- Header -->
  <header>
    <div class="brand">
      <div class="brand-icon">⚡</div>
      <div>
        <h1>AI Interview Agent</h1>
        <span class="subtitle">Architecture & Wiki Graph</span>
      </div>
    </div>
    
    <div class="header-actions">
      <div class="search-box">
        <span class="search-icon">🔍</span>
        <input type="text" id="search-input" placeholder="Search module, memory, JEV...">
      </div>
      <button class="btn" id="btn-reset-view"><span>↺</span> Reset</button>
      <button class="btn" id="btn-physics-toggle"><span>⚡</span> Physics: ON</button>
    </div>
  </header>

  <!-- Main Body -->
  <div class="app-body">
    
    <!-- Filter Chips Floating Bar -->
    <div class="filter-bar">
      <div class="filter-chip active" data-layer="all">All Subsystems</div>
      <div class="filter-chip" data-layer="agent">Agent Engine</div>
      <div class="filter-chip" data-layer="state">State & Memory</div>
      <div class="filter-chip" data-layer="api">FastAPI & Routing</div>
      <div class="filter-chip" data-layer="ingestion">Ingestion</div>
      <div class="filter-chip" data-layer="llm">LLM & Prompts</div>
      <div class="filter-chip" data-layer="wiki">Wiki Docs</div>
      <div class="filter-chip" data-layer="tests">Tests</div>
    </div>
    
    <!-- Guided Pathway Selector -->
    <div class="flow-tour-bar">
      <label for="flow-preset">Highlight Flow:</label>
      <select id="flow-preset" class="flow-select">
        <option value="none">-- Select Architecture Pathway --</option>
        <option value="turn-exec">🎯 Turn Execution Flow (Route ➔ Agent ➔ Fetcher ➔ LLM ➔ Grounding ➔ State)</option>
        <option value="memory-tree">🧠 Hierarchical Memory Pipeline (State ➔ SubMemories ➔ DialogueWindow ➔ Budget)</option>
        <option value="ingestion-flow">📑 Candidate Ingestion (Resume / GitHub ➔ Ingestion ➔ SubMemory Seeding)</option>
        <option value="wiki-docs">📚 OpenWiki Documentation Map</option>
      </select>
    </div>

    <!-- Graph Canvas Container -->
    <div id="network-canvas"></div>

    <!-- Floating Graph Controls (Zoom) -->
    <div class="graph-controls">
      <button class="ctrl-btn" id="ctrl-zoom-in" title="Zoom In">+</button>
      <button class="ctrl-btn" id="ctrl-zoom-out" title="Zoom Out">−</button>
      <button class="ctrl-btn" id="ctrl-fit" title="Fit to View">⊡</button>
    </div>

    <!-- Right Inspector Drawer -->
    <div class="inspector-panel" id="inspector">
      <div class="inspector-header">
        <div>
          <span class="node-badge" id="insp-badge">MODULE</span>
          <h2 id="insp-title">Select a node</h2>
          <div class="node-filepath" id="insp-path">Click any node in the graph to inspect</div>
        </div>
        <button class="close-inspector" id="insp-close" title="Close Panel">✕</button>
      </div>
      
      <div class="inspector-tabs">
        <button class="tab-btn active" data-tab="overview">Overview</button>
        <button class="tab-btn" data-tab="doc">Wiki / Source Code</button>
      </div>

      <div class="inspector-content" id="tab-overview">
        <div class="section-title">Architectural Role & Invariants</div>
        <div class="role-card" id="insp-role">
          Click any component node in the force graph to see its responsibilities, key functions, dependencies, and doc linkages.
        </div>

        <div class="section-title">Key Classes & Exported Symbols</div>
        <div class="symbol-tags" id="insp-symbols">
          <span class="symbol-tag">--</span>
        </div>

        <div class="section-title">Connected Dependents & Calls</div>
        <div class="neighbor-list" id="insp-neighbors">
          <div class="empty-state">
            <div>No node selected</div>
          </div>
        </div>
      </div>

      <div class="inspector-content" id="tab-doc" style="display: none;">
        <div class="markdown-container" id="markdown-viewer">
          <div class="empty-state">
            <div class="empty-state-icon">📄</div>
            <p>Select a Wiki page or code node to view rendered documentation.</p>
          </div>
        </div>
      </div>

    </div>

  </div>

  <script>
    // Embedded Graph Data
    const rawData = __GRAPH_DATA_PLACEHOLDER__;

    // Palette Mapping
    const colorMap = {
      agent: { background: '#1e1338', border: '#8b5cf6', highlight: { background: '#2e1c56', border: '#a78bfa' } },
      state: { background: '#0e1f3d', border: '#3b82f6', highlight: { background: '#193366', border: '#60a5fa' } },
      api: { background: '#092920', border: '#10b981', highlight: { background: '#104537', border: '#34d399' } },
      llm: { background: '#2c1e08', border: '#f59e0b', highlight: { background: '#452f0d', border: '#fbbf24' } },
      ingestion: { background: '#06262d', border: '#06b6d4', highlight: { background: '#0a3c47', border: '#22d3ee' } },
      wiki: { background: '#2b0e17', border: '#f43f5e', highlight: { background: '#4a1827', border: '#fb7185' } },
      tests: { background: '#0d2524', border: '#14b8a6', highlight: { background: '#163d3b', border: '#2dd4bf' } }
    };

    // Format Nodes for Vis-Network
    const nodes = new vis.DataSet(rawData.nodes.map(n => {
      const colors = colorMap[n.group] || colorMap.agent;
      const isWiki = n.group === 'wiki';
      return {
        id: n.id,
        label: n.label,
        shape: isWiki ? 'box' : 'box',
        color: colors,
        font: {
          color: '#f8fafc',
          face: 'Outfit, sans-serif',
          size: isWiki ? 13 : 12,
          bold: isWiki
        },
        margin: 10,
        borderWidth: 2,
        shadow: { enabled: true, color: 'rgba(0,0,0,0.5)', size: 10, x: 0, y: 4 },
        raw: n
      };
    }));

    // Format Edges for Vis-Network
    const edges = new vis.DataSet(rawData.edges.map((e, idx) => ({
      id: 'e_' + idx,
      from: e.from,
      to: e.to,
      label: e.label,
      arrows: { to: { enabled: true, scaleFactor: 0.7 } },
      color: { color: '#2d3d63', highlight: '#3b82f6', hover: '#60a5fa' },
      font: { color: '#64748b', size: 9, face: 'JetBrains Mono', strokeWidth: 0 },
      smooth: { type: 'cubicBezier', roundness: 0.2 },
      raw: e
    })));

    // Vis-Network Configuration
    const container = document.getElementById('network-canvas');
    const graphData = { nodes: nodes, edges: edges };
    const options = {
      physics: {
        enabled: true,
        solver: 'forceAtlas2Based',
        forceAtlas2Based: {
          gravitationalConstant: -70,
          centralGravity: 0.015,
          springLength: 140,
          springConstant: 0.08,
          damping: 0.4
        },
        stabilization: { iterations: 120 }
      },
      interaction: {
        hover: true,
        tooltipDelay: 100,
        hideEdgesOnDrag: false,
        navigationButtons: false
      }
    };

    const network = new vis.Network(container, graphData, options);

    // Inspector Elements
    const inspector = document.getElementById('inspector');
    const inspBadge = document.getElementById('insp-badge');
    const inspTitle = document.getElementById('insp-title');
    const inspPath = document.getElementById('insp-path');
    const inspRole = document.getElementById('insp-role');
    const inspSymbols = document.getElementById('insp-symbols');
    const inspNeighbors = document.getElementById('insp-neighbors');
    const markdownViewer = document.getElementById('markdown-viewer');

    let selectedNodeId = null;

    // Node Selection Handler
    function selectNode(nodeId) {
      selectedNodeId = nodeId;
      const node = nodes.get(nodeId);
      if (!node) return;

      const data = node.raw;
      
      // Update UI elements
      inspBadge.textContent = data.layer.toUpperCase();
      inspBadge.style.backgroundColor = (colorMap[data.group] || colorMap.agent).border;
      inspBadge.style.color = '#ffffff';
      
      inspTitle.textContent = data.title;
      inspPath.textContent = data.path;
      inspRole.textContent = data.role;

      // Symbols
      inspSymbols.innerHTML = '';
      if (data.symbols && data.symbols.length > 0) {
        data.symbols.forEach(sym => {
          const span = document.createElement('span');
          span.className = 'symbol-tag';
          span.textContent = sym;
          inspSymbols.appendChild(span);
        });
      } else {
        inspSymbols.innerHTML = '<span class="symbol-tag">None</span>';
      }

      // Neighbors
      const connectedEdges = edges.get({
        filter: e => e.from === nodeId || e.to === nodeId
      });

      inspNeighbors.innerHTML = '';
      if (connectedEdges.length === 0) {
        inspNeighbors.innerHTML = '<div class="empty-state">No direct neighbors</div>';
      } else {
        connectedEdges.forEach(e => {
          const isOut = e.from === nodeId;
          const targetId = isOut ? e.to : e.from;
          const targetNode = nodes.get(targetId);
          if (!targetNode) return;

          const item = document.createElement('div');
          item.className = 'neighbor-item';
          item.innerHTML = `
            <div>
              <span style="color: ${isOut ? '#34d399' : '#60a5fa'}; font-size: 10px; margin-right: 4px;">
                ${isOut ? '➔' : '⬅'}
              </span>
              <strong>${targetNode.label}</strong>
            </div>
            <span class="relation">${e.label}</span>
          `;
          item.onclick = () => {
            network.selectNodes([targetId]);
            selectNode(targetId);
            network.focus(targetId, { animation: { duration: 500, easingFunction: 'easeInOutQuad' }, scale: 1.1 });
          };
          inspNeighbors.appendChild(item);
        });
      }

      // Fetch file content for preview tab
      fetchFileContent(data.path);

      // Open inspector panel
      inspector.classList.remove('collapsed');
    }

    // Markdown / File Content Fetcher
    async function fetchFileContent(filePath) {
      markdownViewer.innerHTML = '<div class="empty-state"><p>Loading content...</p></div>';
      try {
        const res = await fetch(`/api/file?path=${encodeURIComponent(filePath)}`);
        if (!res.ok) throw new Error('File not found');
        const text = await res.text();
        
        if (filePath.endsWith('.md')) {
          markdownViewer.innerHTML = marked.parse(text);
        } else {
          markdownViewer.innerHTML = `
            <h2>Source File Preview</h2>
            <pre><code>${escapeHtml(text.slice(0, 4000))}${text.length > 4000 ? '\\n\\n... [File truncated for preview]' : ''}</code></pre>
          `;
        }
      } catch (err) {
        markdownViewer.innerHTML = `<div class="empty-state"><p>Failed to load file content: ${err.message}</p></div>`;
      }
    }

    function escapeHtml(str) {
      return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }

    // Graph Events
    network.on('click', params => {
      if (params.nodes.length > 0) {
        selectNode(params.nodes[0]);
      }
    });

    // Close Inspector Button
    document.getElementById('insp-close').onclick = () => {
      inspector.classList.add('collapsed');
      network.unselectAll();
    };

    // Tabs
    document.querySelectorAll('.tab-btn').forEach(btn => {
      btn.onclick = () => {
        document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        const tab = btn.dataset.tab;
        document.getElementById('tab-overview').style.display = tab === 'overview' ? 'block' : 'none';
        document.getElementById('tab-doc').style.display = tab === 'doc' ? 'block' : 'none';
      };
    });

    // Layer Filter Chips
    document.querySelectorAll('.filter-chip').forEach(chip => {
      chip.onclick = () => {
        document.querySelectorAll('.filter-chip').forEach(c => c.classList.remove('active'));
        chip.classList.add('active');
        const layer = chip.dataset.layer;

        if (layer === 'all') {
          nodes.forEach(n => nodes.update({ id: n.id, hidden: false }));
          edges.forEach(e => edges.update({ id: e.id, hidden: false }));
        } else {
          nodes.forEach(n => {
            const matches = n.raw.group === layer;
            nodes.update({ id: n.id, hidden: !matches });
          });
        }
        network.fit({ animation: { duration: 600 } });
      };
    });

    // Search Box
    const searchInput = document.getElementById('search-input');
    searchInput.oninput = () => {
      const q = searchInput.value.toLowerCase().trim();
      if (!q) {
        nodes.forEach(n => nodes.update({ id: n.id, opacity: 1.0 }));
        return;
      }

      nodes.forEach(n => {
        const match = n.label.toLowerCase().includes(q) ||
                      n.raw.title.toLowerCase().includes(q) ||
                      n.raw.role.toLowerCase().includes(q) ||
                      (n.raw.symbols && n.raw.symbols.some(s => s.toLowerCase().includes(q)));
        nodes.update({ id: n.id, opacity: match ? 1.0 : 0.15 });
      });
    };

    // Guided Pathway Highlighter
    document.getElementById('flow-preset').onchange = (e) => {
      const val = e.target.value;
      if (val === 'none') {
        nodes.forEach(n => nodes.update({ id: n.id, opacity: 1.0 }));
        edges.forEach(edge => edges.update({ id: edge.id, width: 1, color: { color: '#2d3d63' } }));
        return;
      }

      let activeNodes = [];
      let activeEdges = [];

      if (val === 'turn-exec') {
        activeNodes = [
          'app/api/routes.py',
          'app/agent/interviewer.py',
          'app/agent/theme_fetcher.py',
          'app/llm/prompts.py',
          'app/llm/client.py',
          'app/agent/grounding.py',
          'app/session/state.py'
        ];
      } else if (val === 'memory-tree') {
        activeNodes = [
          'app/session/state.py',
          'app/agent/theme_fetcher.py',
          'app/agent/interviewer.py',
          'app/session/store.py'
        ];
      } else if (val === 'ingestion-flow') {
        activeNodes = [
          'app/api/routes.py',
          'app/ingestion/resume_loader.py',
          'app/ingestion/github_loader.py',
          'app/session/state.py'
        ];
      } else if (val === 'wiki-docs') {
        activeNodes = rawData.nodes.filter(n => n.group === 'wiki').map(n => n.id);
      }

      nodes.forEach(n => {
        const inFlow = activeNodes.includes(n.id);
        nodes.update({ id: n.id, opacity: inFlow ? 1.0 : 0.1 });
      });

      edges.forEach(edge => {
        const inFlow = activeNodes.includes(edge.from) && activeNodes.includes(edge.to);
        edges.update({
          id: edge.id,
          width: inFlow ? 3 : 1,
          color: { color: inFlow ? '#38bdf8' : '#1e293b' }
        });
      });

      network.fit({
        nodes: activeNodes,
        animation: { duration: 800, easingFunction: 'easeInOutQuad' }
      });
    };

    // Zoom Controls
    document.getElementById('ctrl-zoom-in').onclick = () => {
      const scale = network.getScale() * 1.3;
      network.moveTo({ scale: scale, animation: { duration: 300 } });
    };

    document.getElementById('ctrl-zoom-out').onclick = () => {
      const scale = network.getScale() * 0.7;
      network.moveTo({ scale: scale, animation: { duration: 300 } });
    };

    document.getElementById('ctrl-fit').onclick = () => {
      network.fit({ animation: { duration: 500 } });
    };

    document.getElementById('btn-reset-view').onclick = () => {
      document.getElementById('flow-preset').value = 'none';
      searchInput.value = '';
      nodes.forEach(n => nodes.update({ id: n.id, hidden: false, opacity: 1.0 }));
      edges.forEach(e => edges.update({ id: e.id, hidden: false, width: 1, color: { color: '#2d3d63' } }));
      network.fit({ animation: { duration: 600 } });
    };

    // Toggle Physics
    let physicsEnabled = true;
    const physicsBtn = document.getElementById('btn-physics-toggle');
    physicsBtn.onclick = () => {
      physicsEnabled = !physicsEnabled;
      network.setOptions({ physics: { enabled: physicsEnabled } });
      physicsBtn.textContent = physicsEnabled ? '⚡ Physics: ON' : '⏸ Physics: OFF';
      physicsBtn.classList.toggle('active', !physicsEnabled);
    };

    // Auto-select Master Index on initial load
    window.addEventListener('load', () => {
      setTimeout(() => {
        network.selectNodes(['wiki/INDEX.md']);
        selectNode('wiki/INDEX.md');
      }, 700);
    });

  </script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Custom HTTP Request Handler
# ---------------------------------------------------------------------------

class VisualizerHTTPHandler(SimpleHTTPRequestHandler):
    """Serves the visualizer UI and provides REST APIs for graph & file contents."""

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path in ("/", "/index.html", "/visualize"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            
            # Embed JSON graph data
            html_payload = INDEX_HTML.replace(
                "__GRAPH_DATA_PLACEHOLDER__",
                json.dumps(GRAPH_DATA)
            )
            self.wfile.write(html_payload.encode("utf-8"))
            return

        elif path == "/api/graph":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(GRAPH_DATA).encode("utf-8"))
            return

        elif path == "/api/file":
            query_params = parse_qs(parsed.query)
            req_file = query_params.get("path", [""])[0]

            if not req_file:
                self.send_error(400, "Missing 'path' parameter")
                return

            # Sanitize path to prevent directory traversal
            clean_path = (BASE_DIR / req_file).resolve()
            if not str(clean_path).startswith(str(BASE_DIR)):
                self.send_error(403, "Access denied")
                return

            if not clean_path.exists() or not clean_path.is_file():
                self.send_error(404, f"File not found: {req_file}")
                return

            try:
                content = clean_path.read_text(encoding="utf-8")
                self.send_response(200)
                mime = "text/markdown" if clean_path.suffix == ".md" else "text/plain"
                self.send_header("Content-Type", f"{mime}; charset=utf-8")
                self.end_headers()
                self.wfile.write(content.encode("utf-8"))
            except Exception as exc:
                self.send_error(500, f"Error reading file: {exc}")
            return

        # Default fallback
        super().do_GET()

    def log_message(self, format, *args):
        # Clean logging: suppress noisy asset logs, print API requests cleanly
        sys.stderr.write(f"[visualizer] {args[0]} -> {args[1]}\n")


# ---------------------------------------------------------------------------
# Server Launcher
# ---------------------------------------------------------------------------

def find_available_port(start_port: int = 8050, max_attempts: int = 20) -> int:
    """Finds an open port starting from start_port."""
    for port in range(start_port, start_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    return start_port


def main():
    port = find_available_port(8050)
    server_address = ("127.0.0.1", port)
    httpd = ThreadingHTTPServer(server_address, VisualizerHTTPHandler)
    url = f"http://127.0.0.1:{port}"

    print("\n" + "=" * 64)
    print("  🚀 AI INTERVIEW AGENT — CODEBASE & WIKI VISUALIZER")
    print("=" * 64)
    print(f"  Local URL : {url}")
    print("  Status    : Serving interactive visual graph & wiki docs")
    print("  Exit      : Press Ctrl+C in this terminal to stop")
    print("=" * 64 + "\n")

    # Automatically open browser
    try:
        webbrowser.open(url)
    except Exception:
        pass

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n\nShutting down visualizer server...")
        httpd.server_close()
        print("Done. Goodbye!\n")


if __name__ == "__main__":
    main()

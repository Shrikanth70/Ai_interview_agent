# 03. Themes & Interviewer Engine

[← Back to Wiki Index](file:///c:/Users/Bhukya%20Shrikanth/OneDrive/Desktop/Interview-agent/wiki/INDEX.md) | [Next: 04. Grounding & Anti-Hallucination Guardrails →](file:///c:/Users/Bhukya%20Shrikanth/OneDrive/Desktop/Interview-agent/wiki/04_GROUNDING_AND_GUARDRAILS.md)

---

## 🎯 The Two Internal Themes

The Interviewer Agent coordinates the technical inquiry across two primary themes, ensuring comprehensive evaluation without generic textbook trivia:

```mermaid
flowchart LR
    subgraph THEMES ["Interviewer Themes"]
        direction TB
        P["Theme: PROFILE<br/>(Hands-on Evidence)"]
        JD["Theme: JD<br/>(Scenario & Reasoning)"]
    end

    subgraph PROFILE_FOCUS ["Profile Evaluation Ladder"]
        P1["1. Explain Project<br/>(Problem framing & user constraints)"] --> P2["2. Explain Architecture<br/>(Framework integration & wiring)"] --> P3["3. Trade-offs & Evals<br/>(Latency, evals, failure modes)"]
    end

    subgraph JD_FOCUS ["JD Scenario Evaluation"]
        JD1["Problem Scenario Framing<br/>(Real-world job criteria)"] --> JD2["Trade-off Probing<br/>(Approach & failure mitigations)"]
    end

    P --> PROFILE_FOCUS
    JD --> JD_FOCUS
```

1. **`PROFILE` Theme**:
   - Evaluates **what the candidate has actually built**.
   - Drills down into **one project at a time** (either a GitHub repo or resume project).
   - Systematically progresses along the rubric ladder:
     - `clarity_of_framing`: User constraints and problem definition.
     - `methodology_depth` & `ai_tool_integration`: Component wiring and framework abstractions.
     - `feasibility` & `ml_technical_depth`: Concurrency, latency, cost, and failure modes.
2. **`JD` Theme**:
   - Evaluates **how the candidate approaches engineering scenarios**.
   - Grounded in realistic role criteria rather than reading out raw job bullets.
   - Probes scaling, trade-offs, and design decisions under real-world constraints.

---

## 🎲 Turn 1: Random Theme Selection

At session start, the agent executes a **random theme selection**:
- Code reference: [`app/agent/interviewer.py`](file:///c:/Users/Bhukya%20Shrikanth/OneDrive/Desktop/Interview-agent/app/agent/interviewer.py#L390-L405).
- If `PROFILE` is picked: Opens with a greeting anchored in their top GitHub repository or resume project.
- If `JD` is picked: Opens with an engineering scenario framed around the role criteria.

---

## 🛠️ The Theme Memory Fetch Tool

Implemented in [`app/agent/theme_fetcher.py`](file:///c:/Users/Bhukya%20Shrikanth/OneDrive/Desktop/Interview-agent/app/agent/theme_fetcher.py).
It is a **deterministic, zero-latency Python context selector** (no extra LLM calls or vector databases).

```mermaid
flowchart TD
    INTERVIEWER["InterviewerAgent.execute_turn()"] --> CHECK{"Action Required?"}
    
    CHECK -- "Follow-Up on Same Topic" --> F_FOLLOW["theme_fetcher.fetch_follow_up_context()"]
    F_FOLLOW --> RES_F["Pulls:<br/>1. Active Project Source Slice<br/>2. Next Pending Rubric Dimension<br/>3. Sliding Dialogue Window (Last 2-3 Q/As)"]
    
    CHECK -- "Context Switch Signal" --> F_BRIDGE["theme_fetcher.fetch_bridge_context()"]
    F_BRIDGE --> RES_B["Pulls Composite:<br/>1. Previous Anchor (Last Project)<br/>2. New Target Scenario Slice<br/>3. Sliding Dialogue Window"]
```

---

## 🌉 Bridge Questions (Context Switching)

When `jev` signals `SWITCH_CONTEXT`, the agent avoids abrupt, disjointed topic jumps by formulating a **Bridge Question**:
- Formatted via [`format_bridge_turn_prompt`](file:///c:/Users/Bhukya%20Shrikanth/OneDrive/Desktop/Interview-agent/app/llm/prompts.py#L250-L265).
- Connects the candidate's demonstrated approach in their previous project to the upcoming theme or scenario.

### Bridge Example: Profile $\rightarrow$ JD
> *"In your `distributed-cache` repo, you implemented probabilistic early expiration to mitigate cache stampedes. In our ingestion pipeline, we deal with severe traffic surges where cache misses can cascade to downstream databases.*  
> *How would you adapt your caching approach to protect our services under those conditions?"*

---

## 🔄 Turn-by-Turn Conversational Cycle

```mermaid
sequenceDiagram
    autonumber
    actor C as Candidate
    participant Agent as app/agent/interviewer.py
    participant Fetcher as app/agent/theme_fetcher.py
    participant State as app/session/state.py
    participant JEV as JEV Evaluator

    C->>Agent: Submits Answer
    Agent->>State: Record Candidate Turn & Append to Window
    Agent->>JEV: Send Answer for Evaluation
    JEV-->>Agent: Signal (FOLLOW_UP or SWITCH_CONTEXT)

    alt Signal == FOLLOW_UP
        Agent->>Fetcher: fetch_follow_up_context(state)
        Fetcher-->>Agent: Active Slice + Next Dimension
        Agent->>C: Emit Deep-Dive Follow-Up Question
    else Signal == SWITCH_CONTEXT
        Agent->>Fetcher: fetch_bridge_context(state, target_theme)
        Fetcher-->>Agent: Composite Anchor + Target Scenario
        Agent->>C: Emit Seamless Bridge Question
        Agent->>State: Switch Active Sub-Memory Pointer
    end
```

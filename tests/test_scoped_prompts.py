from app.llm.prompts import format_scoped_turn_prompt, format_bridge_turn_prompt

def test_format_scoped_turn_prompt():
    prompt = format_scoped_turn_prompt(
        theme="PROFILE",
        source_ref="distributed-cache",
        source_slice={"description": "Cache daemon"},
        next_dimension="methodology_depth",
        anti_duplication=["Redis TTL"],
    )
    assert "THEME: PROFILE" in prompt
    assert "distributed-cache" in prompt
    assert "methodology_depth" in prompt
    assert "Redis TTL" in prompt

def test_format_bridge_turn_prompt():
    prompt = format_bridge_turn_prompt(
        anchor_ref="distributed-cache",
        anchor_slice={"description": "Cache daemon"},
        target_theme="JD",
        target_ref="High-Throughput Stream Ingestion",
        target_slice={"problem_statement": "Handle surges"},
    )
    assert "BRIDGE TRANSITION MANDATE" in prompt
    assert "distributed-cache" in prompt
    assert "High-Throughput Stream Ingestion" in prompt

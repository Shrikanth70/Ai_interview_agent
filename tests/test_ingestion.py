import pytest
from app.ingestion.resume_loader import clean_resume_text, load_resume, parse_resume_sections
from app.ingestion.github_loader import clean_readme_content, GitHubLoader


def test_clean_resume_text():
    raw = "Line 1   \r\n\r\n\r\n• Bullet 1\n– Bullet 2   "
    cleaned = clean_resume_text(raw)
    assert "- Bullet 1" in cleaned
    assert "\r" not in cleaned
    assert "\n\n\n" not in cleaned


def test_parse_resume_sections():
    sample = (
        "John Doe\nSoftware Engineer\n\n"
        "EXPERIENCE\nAcme Corp (2020-2023)\n- Built API gateway\n\n"
        "PROJECTS\nMyRepo\n- Distributed lock in Go\n\n"
        "SKILLS\nPython, Go, Docker"
    )
    sections = parse_resume_sections(sample)
    assert "experience" in sections
    assert "Acme Corp" in sections["experience"]
    assert "projects" in sections
    assert "MyRepo" in sections["projects"]
    assert "skills" in sections


def test_load_resume_from_file(tmp_path):
    resume_file = tmp_path / "resume.txt"
    resume_file.write_text(
        "Jane Doe\nSystems Engineer\n\nEXPERIENCE\nDatacorp (2021-Present)\n- Optimized Kafka to 50k req/s\n\nSKILLS\nGo, C++",
        encoding="utf-8",
    )
    result = load_resume(resume_file)
    assert result["char_count"] > 0
    assert "Datacorp" in result["full_text"]
    assert "experience" in result["sections"]


def test_clean_readme_content():
    raw = "# My Project\n[![Build Status](http://example.com/badge.svg)](http://example.com)\n<div>Some HTML</div>\nReal content here."
    cleaned = clean_readme_content(raw)
    assert "badge.svg" not in cleaned
    assert "<div>" not in cleaned
    assert "Real content here." in cleaned


@pytest.mark.asyncio
async def test_github_loader_public():
    # Test real public profile fetch for octocat
    loader = GitHubLoader()
    try:
        portfolio = await loader.load_candidate_portfolio("octocat", max_repos=3)
        assert portfolio["username"] == "octocat"
        assert "profile" in portfolio
        assert "repos" in portfolio
        assert len(portfolio["repos"]) > 0
    except PermissionError:
        pytest.skip("GitHub rate limit reached for unauthenticated client.")

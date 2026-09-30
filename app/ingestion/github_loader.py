"""GitHub profile and public repository portfolio loader with automatic mock fallback."""

import asyncio
import base64
import json
import logging
import re
import sys
from html import unescape
from typing import Any, Dict, List, Optional
import httpx

from app.config import settings

logger = logging.getLogger(__name__)


def clean_readme_content(raw_readme: str, max_words: int = 1000) -> str:
    """Cleans markdown syntax, badges, and caps README content to approximately max_words."""
    if not raw_readme:
        return ""

    cleaned = re.sub(r"!\[.*?\]\(.*?\)", "", raw_readme)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = re.sub(r"[ \t]+", " ", cleaned).strip()

    words = cleaned.split()
    if len(words) > max_words:
        cleaned = " ".join(words[:max_words]) + " ... [README truncated]"

    return cleaned


def get_mock_portfolio(username: str = "octocat") -> Dict[str, Any]:
    """Generates a rich, realistic mock GitHub portfolio for offline testing and demo resilience."""
    clean_user = username.strip().lstrip("@") or "octocat"
    return {
        "username": clean_user,
        "profile": {
            "login": clean_user,
            "name": f"{clean_user.title()} (Demo Portfolio)",
            "bio": "Systems Engineer, Open Source Contributor & Distributed Systems Enthusiast",
            "public_repos": 5,
            "followers": 1420,
            "html_url": f"https://github.com/{clean_user}",
        },
        "repos": {
            "autotyper": {
                "name": "autotyper",
                "description": "High-performance automated typing daemon with simulated human jitter written in Go.",
                "stars": 482,
                "language": "Go",
                "topics": ["go", "concurrency", "automation", "cli"],
                "updated_at": "2024-09-15T10:12:00Z",
                "readme_excerpt": (
                    "# autotyper\n\n"
                    "A lightweight, low-latency automated typing daemon with simulated human jitter in Go.\n\n"
                    "## Architecture & Concurrency\n"
                    "- Uses Goroutines for non-blocking keystroke emission.\n"
                    "- Implements Gaussian variance to simulate realistic typing intervals (WPM fluctuations).\n"
                    "- Channels and timers are synchronized to prevent OS event queue saturation under high throughput."
                ),
            },
            "event-hub": {
                "name": "event-hub",
                "description": "High-throughput asynchronous event router and stream multiplexer in Go.",
                "stars": 1280,
                "language": "Go",
                "topics": ["events", "streaming", "distributed-systems", "multiplexer"],
                "updated_at": "2024-08-20T14:45:00Z",
                "readme_excerpt": (
                    "# event-hub\n\n"
                    "A distributed, high-throughput event router and stream multiplexer in Go.\n\n"
                    "## Features\n"
                    "- Non-blocking channel fan-out with configurable consumer backpressure buffers.\n"
                    "- Stream snapshotting and state checkpointing.\n"
                    "- Zero-copy buffer pooling to minimize GC pause times under high message rates."
                ),
            },
            "distributed-cache": {
                "name": "distributed-cache",
                "description": "In-memory distributed LRU cache with consistent hashing and Redis synchronization.",
                "stars": 830,
                "language": "Go",
                "topics": ["cache", "lru", "consistent-hashing", "redis"],
                "updated_at": "2024-07-28T09:30:00Z",
                "readme_excerpt": (
                    "# distributed-cache\n\n"
                    "High-throughput partitioned cache with consistent hash ring and virtual nodes.\n\n"
                    "## Consistency Model\n"
                    "- Virtual nodes (100 replicas per physical node) to eliminate hash skew.\n"
                    "- Async replication buffer with Redis backup for persistence and failover recovery."
                ),
            },
            "Spoon-Knife": {
                "name": "Spoon-Knife",
                "description": "This repo is for demonstration purposes only.",
                "stars": 14062,
                "language": "HTML",
                "topics": ["git", "demo", "fork"],
                "updated_at": "2024-08-21T15:25:42Z",
                "readme_excerpt": (
                    "### Well hello there!\n\n"
                    "This repository is meant to provide an example for forking a repository on GitHub.\n"
                    "Creating a fork is producing a personal copy of someone else's project."
                ),
            },
            "Hello-World": {
                "name": "Hello-World",
                "description": "My first repository on GitHub!",
                "stars": 3832,
                "language": "Python",
                "topics": ["starter", "git"],
                "updated_at": "2024-06-10T12:00:00Z",
                "readme_excerpt": "Hello World! A starter repository for exploring Git workflows and commits.",
            },
        },
    }


FALLBACK_PORTFOLIOS: Dict[str, Dict[str, Any]] = {
    "octocat": get_mock_portfolio("octocat"),
    "mock": get_mock_portfolio("mock"),
    "demo": get_mock_portfolio("demo"),
    "test": get_mock_portfolio("test"),
}


class GitHubLoader:
    """Fetches and summarizes a candidate's public GitHub portfolio with graceful mock fallback."""

    def __init__(self, token: Optional[str] = None):
        self.token = token or settings.GITHUB_TOKEN
        self.headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "AI-Interview-Agent",
        }
        if self.token:
            self.headers["Authorization"] = f"token {self.token}"

    async def fetch_user_profile(
        self, client: httpx.AsyncClient, username: str
    ) -> Dict[str, Any]:
        """Fetches core user profile metadata."""
        url = f"https://api.github.com/users/{username}"
        resp = await client.get(url, headers=self.headers, timeout=4.0)

        if resp.status_code == 404:
            raise ValueError(f"GitHub user '{username}' not found.")
        elif resp.status_code == 403:
            raise PermissionError(
                f"GitHub API rate limit exceeded or access forbidden. "
                f"Detail: {resp.text}."
            )
        resp.raise_for_status()

        data = resp.json()
        return {
            "login": data.get("login"),
            "name": data.get("name"),
            "bio": data.get("bio"),
            "public_repos": data.get("public_repos", 0),
            "followers": data.get("followers", 0),
            "html_url": data.get("html_url"),
        }

    async def fetch_repos(
        self, client: httpx.AsyncClient, username: str, limit: int = 8
    ) -> List[Dict[str, Any]]:
        """Fetches public repositories, prioritizing non-forks sorted by recent activity."""
        url = f"https://api.github.com/users/{username}/repos"
        params = {
            "type": "owner",
            "sort": "pushed",
            "direction": "desc",
            "per_page": 15,
        }
        resp = await client.get(url, headers=self.headers, params=params, timeout=4.0)
        resp.raise_for_status()
        raw_repos = resp.json()

        if not isinstance(raw_repos, list):
            return []

        non_forks = [r for r in raw_repos if not r.get("fork")]
        candidates = non_forks if len(non_forks) >= 3 else raw_repos
        return candidates[:limit]

    async def fetch_repo_readme(
        self, client: httpx.AsyncClient, owner: str, repo: str
    ) -> str:
        """Fetches and decodes the default branch README file for a repository."""
        url = f"https://api.github.com/repos/{owner}/{repo}/readme"
        try:
            resp = await client.get(url, headers=self.headers, timeout=2.5)
            if resp.status_code == 404:
                return ""
            resp.raise_for_status()
            data = resp.json()
            content_b64 = data.get("content", "")
            if content_b64:
                decoded = base64.b64decode(content_b64).decode("utf-8", errors="replace")
                return clean_readme_content(decoded)
        except Exception:
            return ""
        return ""

    async def scrape_public_profile(
        self, username: str, max_repos: int = 6
    ) -> Optional[Dict[str, Any]]:
        """Scrapes public GitHub profile and repositories HTML when REST API is rate limited.
        
        This prevents falling back to fake/mock repositories when the candidate provided a real username.
        """
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
        }
        try:
            async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=10.0) as client:
                # 1. Profile Page
                p_resp = await client.get(f"https://github.com/{username}")
                if p_resp.status_code == 404:
                    return None
                
                p_html = p_resp.text
                name_m = re.search(r'itemprop="name">\s*([^<]+)\s*<', p_html)
                name = unescape(name_m.group(1).strip()) if name_m else username
                bio_m = re.search(r'data-bio-text[^>]*>([^<]+)<', p_html)
                if not bio_m:
                    bio_m = re.search(r'class="p-note user-profile-bio[^>]*><div>([^<]+)<', p_html)
                bio = unescape(bio_m.group(1).strip()) if bio_m else ""
                
                # 2. Repositories Tab
                r_resp = await client.get(f"https://github.com/{username}?tab=repositories")
                repos_summary: Dict[str, Any] = {}
                if r_resp.status_code == 200:
                    r_html = r_resp.text
                    pattern = re.compile(
                        r'href="/' + re.escape(username) + r'/([a-zA-Z0-9_\.-]+)"\s+itemprop="name codeRepository"',
                        re.IGNORECASE
                    )
                    for m in pattern.finditer(r_html):
                        repo_name = m.group(1).strip()
                        if repo_name in repos_summary:
                            continue
                        chunk = r_html[m.start():m.start() + 2500]
                        lang_m = re.search(r'itemprop="programmingLanguage">([^<]+)<', chunk)
                        desc_m = re.search(r'itemprop="description">([^<]+)<', chunk)
                        lang = unescape(lang_m.group(1).strip()) if lang_m else "Python"
                        desc = unescape(desc_m.group(1).strip()) if desc_m else ""
                        
                        # Try fetching raw README from GitHub CDN (top 2 repos only, 1.5s timeout)
                        readme_text = ""
                        if len(repos_summary) < 2:
                            for branch in ["main", "master"]:
                                raw_url = f"https://raw.githubusercontent.com/{username}/{repo_name}/{branch}/README.md"
                                try:
                                    raw_resp = await client.get(raw_url, timeout=1.5)
                                    if raw_resp.status_code == 200:
                                        readme_text = clean_readme_content(raw_resp.text, max_words=800)
                                        break
                                except Exception:
                                    pass
                        
                        repos_summary[repo_name] = {
                            "name": repo_name,
                            "description": desc,
                            "stars": 0,
                            "language": lang,
                            "topics": [],
                            "updated_at": "",
                            "readme_excerpt": readme_text or f"# {repo_name}\nProject in {lang}. {desc}".strip(),
                        }
                        if len(repos_summary) >= max_repos:
                            break
                            
                if not repos_summary:
                    return None
                    
                return {
                    "username": username,
                    "profile": {
                        "login": username,
                        "name": name,
                        "bio": bio,
                        "public_repos": len(repos_summary),
                        "followers": 0,
                        "html_url": f"https://github.com/{username}",
                    },
                    "repos": repos_summary,
                }
        except Exception as err:
            logger.warning(f"Public HTML scrape failed for '{username}': {err}")
            return None

    async def load_candidate_portfolio(
        self, username: str, max_repos: int = 6, use_mock: bool = False
    ) -> Dict[str, Any]:
        """Loads complete portfolio: user metadata, repositories, and README excerpts.
        
        Falls back to public web scraping first if the REST API is rate limited (403),
        preventing fake/mock repos from replacing a real user's actual profile.
        """
        clean_user = username.strip().lstrip("@")
        if not clean_user:
            clean_user = "octocat"

        # Explicit mock request or recognized demo handle
        if use_mock or clean_user.lower() in ("mock", "demo", "mock-git", "git-mock", "test"):
            logger.info(f"Using mock GitHub portfolio for '{clean_user}'.")
            return get_mock_portfolio(clean_user)

        try:
            async with httpx.AsyncClient() as client:
                profile = await self.fetch_user_profile(client, clean_user)
                repos_raw = await self.fetch_repos(client, clean_user, limit=max_repos)

                readme_tasks = [
                    self.fetch_repo_readme(client, clean_user, r["name"])
                    for r in repos_raw
                ]
                readmes = await asyncio.gather(*readme_tasks, return_exceptions=True)

                repos_summary: Dict[str, Any] = {}
                for repo, readme_res in zip(repos_raw, readmes):
                    readme_text = readme_res if isinstance(readme_res, str) else ""
                    repo_name = repo["name"]
                    repos_summary[repo_name] = {
                        "name": repo_name,
                        "description": repo.get("description") or "",
                        "stars": repo.get("stargazers_count", 0),
                        "language": repo.get("language") or "Not specified",
                        "topics": repo.get("topics", []),
                        "updated_at": repo.get("pushed_at") or repo.get("updated_at"),
                        "readme_excerpt": readme_text,
                    }

                return {
                    "username": clean_user,
                    "profile": profile,
                    "repos": repos_summary,
                }
        except Exception as err:
            logger.warning(
                f"GitHub REST API unavailable or rate-limited ({err}). "
                f"Attempting public profile scrape for '{clean_user}'..."
            )
            scraped = await self.scrape_public_profile(clean_user, max_repos=max_repos)
            if scraped and scraped.get("repos"):
                logger.info(f"Successfully scraped {len(scraped['repos'])} real public repos for '{clean_user}'.")
                return scraped

            logger.warning(f"Public scrape failed. Falling back to mock GitHub portfolio for '{clean_user}'.")
            return get_mock_portfolio(clean_user)


async def fetch_github_profile(
    username: str, token: Optional[str] = None, use_mock: bool = False
) -> Dict[str, Any]:
    """Helper function to load a candidate's GitHub profile with mock fallback."""
    loader = GitHubLoader(token=token)
    return await loader.load_candidate_portfolio(username, use_mock=use_mock)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m app.ingestion.github_loader <github_username>")
        sys.exit(1)

    user = sys.argv[1]
    try:
        data = asyncio.run(fetch_github_profile(user))
        print(json.dumps(data, indent=2))
    except Exception as err:
        print(f"Error fetching GitHub profile: {err}", file=sys.stderr)
        sys.exit(1)

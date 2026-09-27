import asyncio
import json
from pathlib import Path
from typing import Dict, List, Optional
from app.session.state import SessionState


class SessionStore:
    """Abstract interface for session state storage."""

    async def get(self, session_id: str) -> Optional[SessionState]:
        raise NotImplementedError

    async def save(self, state: SessionState) -> None:
        raise NotImplementedError

    async def delete(self, session_id: str) -> bool:
        raise NotImplementedError

    async def list_all(self) -> List[SessionState]:
        raise NotImplementedError


class InMemorySessionStore(SessionStore):
    """Thread-safe in-memory session store with optional JSON serialization for local inspection."""

    def __init__(self, persist_dir: Optional[str | Path] = None):
        self._sessions: Dict[str, SessionState] = {}
        self._lock = asyncio.Lock()
        self.persist_dir = Path(persist_dir) if persist_dir else None
        if self.persist_dir:
            self.persist_dir.mkdir(parents=True, exist_ok=True)

    async def get(self, session_id: str) -> Optional[SessionState]:
        async with self._lock:
            state = self._sessions.get(session_id)
            if state:
                return state

            # If not in memory but persist_dir exists, try reading from disk
            if self.persist_dir:
                file_path = self.persist_dir / f"{session_id}.json"
                if file_path.exists():
                    try:
                        with open(file_path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                            restored = SessionState.model_validate(data)
                            self._sessions[session_id] = restored
                            return restored
                    except Exception:
                        return None
            return None

    async def save(self, state: SessionState) -> None:
        async with self._lock:
            self._sessions[state.session_id] = state
            if self.persist_dir:
                file_path = self.persist_dir / f"{state.session_id}.json"
                try:
                    with open(file_path, "w", encoding="utf-8") as f:
                        f.write(state.model_dump_json(indent=2))
                except Exception:
                    pass

    async def delete(self, session_id: str) -> bool:
        async with self._lock:
            existed = session_id in self._sessions
            if existed:
                del self._sessions[session_id]
            if self.persist_dir:
                file_path = self.persist_dir / f"{session_id}.json"
                if file_path.exists():
                    file_path.unlink()
            return existed

    async def list_all(self) -> List[SessionState]:
        async with self._lock:
            return list(self._sessions.values())


# Global default store instance
_default_store = InMemorySessionStore(persist_dir="./sessions")


def get_session_store() -> SessionStore:
    """Dependency injection helper returning the global session store."""
    return _default_store

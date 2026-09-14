"""In-memory sessions, jobs, temp dirs, and TTL cleanup."""

from __future__ import annotations

import shutil
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app import limits


@dataclass
class Session:
    id: str
    created: float
    last_used: float
    upload_dir: Path
    paths: list[str] = field(default_factory=list)
    client_ip: str = ""


@dataclass
class Job:
    id: str
    session_id: str
    created: float
    status: str = "queued"  # queued | running | done | error
    progress: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] | None = None
    error: str | None = None
    output_dir: Path | None = None
    html_name: str | None = None
    client_ip: str = ""


class JobStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.sessions: dict[str, Session] = {}
        self.jobs: dict[str, Job] = {}
        self._generate_lock = threading.Lock()
        self._ip_last_generate: dict[str, float] = {}
        self._ip_generate_times: dict[str, list[float]] = {}

    def cleanup_expired(self) -> None:
        now = time.time()
        with self._lock:
            for sid, session in list(self.sessions.items()):
                if now - session.last_used > limits.SESSION_TTL_SECONDS:
                    self._drop_session_unlocked(sid)
            for jid, job in list(self.jobs.items()):
                if now - job.created > limits.JOB_TTL_SECONDS:
                    self._drop_job_unlocked(jid)

    def _drop_session_unlocked(self, session_id: str) -> None:
        session = self.sessions.pop(session_id, None)
        if session is None:
            return
        shutil.rmtree(session.upload_dir, ignore_errors=True)

    def _drop_job_unlocked(self, job_id: str) -> None:
        job = self.jobs.pop(job_id, None)
        if job is None:
            return
        if job.output_dir is not None:
            shutil.rmtree(job.output_dir, ignore_errors=True)

    def create_session(self, client_ip: str = "") -> Session:
        self.cleanup_expired()
        sid = uuid.uuid4().hex
        upload_dir = self.root / "sessions" / sid
        upload_dir.mkdir(parents=True, exist_ok=True)
        now = time.time()
        session = Session(
            id=sid,
            created=now,
            last_used=now,
            upload_dir=upload_dir,
            client_ip=client_ip,
        )
        with self._lock:
            self.sessions[sid] = session
        return session

    def get_session(self, session_id: str) -> Session | None:
        self.cleanup_expired()
        with self._lock:
            session = self.sessions.get(session_id)
            if session is None:
                return None
            session.last_used = time.time()
            return session

    def touch_session(self, session_id: str) -> None:
        with self._lock:
            session = self.sessions.get(session_id)
            if session is not None:
                session.last_used = time.time()

    def create_job(self, session_id: str, client_ip: str = "") -> Job:
        jid = uuid.uuid4().hex
        output_dir = self.root / "jobs" / jid
        output_dir.mkdir(parents=True, exist_ok=True)
        job = Job(
            id=jid,
            session_id=session_id,
            created=time.time(),
            output_dir=output_dir,
            client_ip=client_ip,
        )
        with self._lock:
            self.jobs[jid] = job
        return job

    def get_job(self, job_id: str) -> Job | None:
        self.cleanup_expired()
        with self._lock:
            return self.jobs.get(job_id)

    def try_acquire_generate(self, client_ip: str) -> str | None:
        """Return None if allowed, else an error message."""
        now = time.time()
        with self._lock:
            last = self._ip_last_generate.get(client_ip, 0.0)
            if client_ip and now - last < limits.PER_IP_GENERATE_COOLDOWN_SECONDS:
                wait = int(limits.PER_IP_GENERATE_COOLDOWN_SECONDS - (now - last)) + 1
                return f"Please wait {wait}s before generating again."
            times = [t for t in self._ip_generate_times.get(client_ip, []) if now - t < 3600]
            if client_ip and len(times) >= limits.PER_IP_MAX_GENERATES_PER_HOUR:
                return "Hourly generate limit reached. Try again later."
            self._ip_generate_times[client_ip] = times
        if not self._generate_lock.acquire(blocking=False):
            return "Another report is generating. Please try again in a moment."
        with self._lock:
            self._ip_last_generate[client_ip] = now
            times = self._ip_generate_times.setdefault(client_ip, [])
            times.append(now)
        return None

    def release_generate(self) -> None:
        try:
            self._generate_lock.release()
        except RuntimeError:
            pass

"""Meeting notes storage and orchestration.

Files live under ~/Documents/BerryLink Notes/<date time> <session-id>/:
    notes.md
    session.json
    transcript.txt
    audio/chunk-NNN.wav   (optional, user-controlled retention)

Recording is explicit and desktop-confirmed.  Audio is transcribed only after
the user stops, and only when Gemini transcription was explicitly enabled for
that session.  Speaker labels are best-effort and are never invented locally.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from . import __version__
from .audio_recorder import AudioRecorder, RecordedChunk, RecordingError, recorder_backend, wav_duration
from .config import Config
from .gemini_gateway import AIError
from .security import atomic_write_text, secure_dir

SESSION_ID_RE = re.compile(r"^[a-f0-9]{12}$")
STATUS_RECORDING = "recording"
STATUS_TRANSCRIBING = "transcribing"
STATUS_COMPLETE = "complete"
STATUS_PARTIAL = "partial"
STATUS_RECORDED = "recorded"
STATUS_INTERRUPTED = "interrupted"
STATUS_ERROR = "error"


class MeetingError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def _safe_title(value: str) -> str:
    cleaned = " ".join(str(value or "").split())
    cleaned = "".join(ch for ch in cleaned if ch.isprintable())
    return cleaned[:80] or "Meeting"


def _format_offset(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    h, remainder = divmod(seconds, 3600)
    m, s = divmod(remainder, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


class MeetingStore:
    def __init__(self, root: Path, logger=None) -> None:
        self.root = root
        self.log = logger
        self._lock = threading.RLock()
        secure_dir(self.root, 0o700)

    # ------------------------------------------------------------------ create

    def create_session(
        self,
        *,
        title: str,
        transcribe: bool,
        retain_audio: bool,
        model: str,
    ) -> dict[str, Any]:
        with self._lock:
            secure_dir(self.root, 0o700)
            now = dt.datetime.now()
            session_id = uuid.uuid4().hex[:12]
            folder_name = f"{now.strftime('%Y-%m-%d %H-%M')} {session_id}"
            folder = self.root / folder_name
            counter = 1
            while folder.exists():
                folder = self.root / f"{folder_name} ({counter})"
                counter += 1
            secure_dir(folder, 0o700)
            secure_dir(folder / "audio", 0o700)
            session: dict[str, Any] = {
                "schema_version": 1,
                "id": session_id,
                "title": _safe_title(title),
                "started_at": now.astimezone(dt.timezone.utc).replace(microsecond=0).isoformat(),
                "ended_at": None,
                "status": STATUS_RECORDING,
                "transcribe": bool(transcribe),
                "retain_audio": bool(retain_audio),
                "transcription_model": model,
                "chunks": [],
                "summaries": [],
                "errors": [],
                "app_version": __version__,
                "speaker_labels": "best-effort" if transcribe else "none",
                "privacy": (
                    "Audio is transcribed by Google Gemini only after the user stops and only if "
                    "transcription was enabled for this session. Free-tier content may be used to "
                    "improve Google products and interactions are retained for up to 1 day."
                ),
                "folder": folder.name,
            }
            self._write_session(session, folder)
            self._render_files(session, folder, segments=[])
            return session

    # ------------------------------------------------------------------ update

    def add_chunk(self, session: dict[str, Any], chunk: RecordedChunk) -> dict[str, Any]:
        with self._lock:
            folder = self.folder_for(session)
            entry = {
                "index": chunk.index,
                "file": f"audio/{chunk.path.name}",
                "start_offset": round(chunk.start_offset, 3),
                "duration": round(chunk.duration, 3),
                "transcription_status": "pending" if session.get("transcribe") else "not_requested",
                "error": None,
            }
            session.setdefault("chunks", []).append(entry)
            self._write_session(session, folder)
            self._render_files(session, folder, segments=[])
            return entry

    def chunk_path(self, session: dict[str, Any], entry: dict[str, Any]) -> Path:
        folder = self.folder_for(session)
        relative = entry.get("file", "")
        if not isinstance(relative, str) or not relative.startswith("audio/"):
            raise MeetingError("bad_session", "Invalid audio file path.")
        path = (folder / relative).resolve()
        if path.parent != (folder / "audio").resolve():
            raise MeetingError("bad_session", "Invalid audio file path.")
        return path

    def mark_chunk_done(self, session: dict[str, Any], index: int, summary: str) -> None:
        with self._lock:
            for entry in session.get("chunks", []):
                if entry.get("index") == index:
                    entry["transcription_status"] = "done"
                    entry["error"] = None
            if summary:
                session.setdefault("summaries", []).append(summary)
            self._write_session(session, self.folder_for(session))

    def mark_chunk_error(self, session: dict[str, Any], index: int, message: str) -> None:
        with self._lock:
            for entry in session.get("chunks", []):
                if entry.get("index") == index:
                    entry["transcription_status"] = "error"
                    entry["error"] = message[:500]
            errors = session.setdefault("errors", [])
            if message and message[:500] not in errors:
                errors.append(message[:500])
            self._write_session(session, self.folder_for(session))

    def save(self, session: dict[str, Any], segments: list[dict[str, Any]] | None = None) -> None:
        """Persist metadata and optionally refresh notes without finalising."""
        with self._lock:
            self._write_session(session, self.folder_for(session))
            if segments is not None:
                self._render_files(session, self.folder_for(session), segments=segments)

    def delete_audio_chunk(self, session: dict[str, Any], entry: dict[str, Any]) -> None:
        with self._lock:
            try:
                self.chunk_path(session, entry).unlink(missing_ok=True)
                entry["audio_deleted"] = True
            except (OSError, MeetingError):
                pass
            self._write_session(session, self.folder_for(session))

    def finalize(
        self,
        session: dict[str, Any],
        *,
        status: str,
        segments: list[dict[str, Any]],
        error: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            folder = self.folder_for(session)
            session["ended_at"] = _iso_now()
            session["status"] = status
            if error:
                errors = session.setdefault("errors", [])
                if error[:500] not in errors:
                    errors.append(error[:500])
            self._write_session(session, folder)
            self._render_files(session, folder, segments=segments)
            return session

    def _write_session(self, session: dict[str, Any], folder: Path) -> None:
        payload = dict(session)
        # Never store an absolute path in the public JSON; it is derived.
        payload.pop("folder", None)
        payload["folder_name"] = folder.name
        atomic_write_text(
            folder / "session.json",
            json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            mode=0o600,
        )

    def folder_for(self, session: dict[str, Any]) -> Path:
        folder_name = session.get("folder")
        if not isinstance(folder_name, str) or not folder_name:
            # Recover from a session loaded from disk.
            folder_name = session.get("folder_name", "")
        if not isinstance(folder_name, str) or not folder_name:
            raise MeetingError("bad_session", "Session folder is missing.")
        folder = (self.root / folder_name).resolve()
        if folder.parent != self.root.resolve():
            raise MeetingError("bad_session", "Session folder is outside the notes root.")
        return folder

    # ------------------------------------------------------------------ render

    def _render_files(
        self,
        session: dict[str, Any],
        folder: Path,
        *,
        segments: list[dict[str, Any]],
    ) -> None:
        lines: list[str] = []
        for segment in segments:
            try:
                start = float(segment.get("start", 0))
            except (TypeError, ValueError):
                start = 0.0
            speaker = str(segment.get("speaker", "Speaker")).strip()[:40] or "Speaker"
            text = " ".join(str(segment.get("text", "")).split())
            if text:
                lines.append(f"[{_format_offset(start)}] {speaker}: {text}")
        transcript_text = "\n".join(lines).strip() + "\n" if lines else "No transcript available.\n"
        atomic_write_text(folder / "transcript.txt", transcript_text, mode=0o600)

        duration = 0.0
        for entry in session.get("chunks", []):
            try:
                duration = max(duration, float(entry.get("start_offset", 0)) + float(entry.get("duration", 0)))
            except (TypeError, ValueError):
                pass
        summaries = [str(s).strip() for s in session.get("summaries", []) if str(s).strip()]
        status = str(session.get("status", STATUS_RECORDING))
        notes = [
            f"# {session.get('title', 'Meeting')}",
            "",
            f"- Session: `{session.get('id', '')}`",
            f"- Started: {session.get('started_at', '')}",
            f"- Ended: {session.get('ended_at') or '—'}",
            f"- Duration: {_format_offset(duration)}",
            f"- Status: {status}",
            f"- Transcription: {'Gemini free tier' if session.get('transcribe') else 'not requested'}",
            f"- Speaker labels: {session.get('speaker_labels', 'none')}",
            "",
            "## Notes",
            "",
        ]
        if summaries:
            notes.extend(f"- {summary}" for summary in summaries)
        elif status in (STATUS_RECORDING, STATUS_TRANSCRIBING):
            notes.append("_Transcription will appear after the recording is stopped and processed._")
        elif session.get("transcribe"):
            notes.append("_No summary was produced._")
        else:
            notes.append("_Meeting notes were not transcribed. Audio may be retained locally._")
        if session.get("errors"):
            notes.append("")
            notes.append("### Transcription notes")
            notes.extend(f"- {str(err)[:500]}" for err in session.get("errors", []))
        notes.extend(["", "## Transcript", ""])
        if lines:
            notes.extend(lines)
        else:
            notes.append("_No transcript available._")
        notes.extend(
            [
                "",
                "---",
                "",
                str(session.get("privacy", "")),
                "",
                "_This folder is local. Delete it from BerryLink when you no longer need it._",
                "",
            ]
        )
        atomic_write_text(folder / "notes.md", "\n".join(notes), mode=0o600)

    # ------------------------------------------------------------------- read

    def list_sessions(self) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        try:
            children = sorted(self.root.iterdir(), key=lambda p: p.name, reverse=True)
        except OSError:
            return results
        for folder in children:
            if not folder.is_dir() or folder.is_symlink():
                continue
            session = self._read_session_file(folder / "session.json")
            if not session:
                continue
            sid = session.get("id")
            if not isinstance(sid, str) or not SESSION_ID_RE.fullmatch(sid):
                continue
            duration = 0.0
            for entry in session.get("chunks", []):
                try:
                    duration = max(duration, float(entry.get("start_offset", 0)) + float(entry.get("duration", 0)))
                except (TypeError, ValueError):
                    pass
            transcript_path = folder / "transcript.txt"
            has_transcript = transcript_path.exists() and transcript_path.stat().st_size > 30
            results.append(
                {
                    "id": sid,
                    "title": session.get("title", "Meeting"),
                    "started_at": session.get("started_at"),
                    "ended_at": session.get("ended_at"),
                    "status": session.get("status"),
                    "duration_seconds": round(duration, 1),
                    "has_transcript": has_transcript,
                    "chunk_count": len(session.get("chunks", [])),
                    "summary": " ".join(session.get("summaries", [])[:2])[:600],
                    "folder": folder.name,
                }
            )
        return results

    def read_session(self, session_id: str) -> dict[str, Any]:
        folder = self._find_folder(session_id)
        session = self._read_session_file(folder / "session.json")
        if not session:
            raise MeetingError("not_found", "That meeting session was not found.")
        notes = (folder / "notes.md").read_text(encoding="utf-8", errors="replace")[:500_000]
        transcript = (folder / "transcript.txt").read_text(encoding="utf-8", errors="replace")[:500_000]
        audio_files = []
        try:
            audio_files = sorted(p.name for p in (folder / "audio").glob("*.wav") if p.is_file())
        except OSError:
            pass
        return {
            "session": session,
            "notes_md": notes,
            "transcript": transcript,
            "audio_files": audio_files,
            "has_audio": bool(audio_files),
        }

    def delete_session(self, session_id: str) -> None:
        with self._lock:
            folder = self._find_folder(session_id)
            if folder.is_symlink():
                raise MeetingError("bad_session", "Refusing to delete a symlinked session.")
            shutil.rmtree(folder)
            if self.log:
                self.log.info("Deleted meeting session %s", session_id)

    def folder_path(self, session_id: str) -> Path:
        return self._find_folder(session_id)

    def recover_interrupted(self) -> int:
        changed = 0
        for folder in self.root.iterdir() if self.root.exists() else []:
            if not folder.is_dir() or folder.is_symlink():
                continue
            session = self._read_session_file(folder / "session.json")
            if not session:
                continue
            if session.get("status") in (STATUS_RECORDING, STATUS_TRANSCRIBING):
                session["status"] = STATUS_INTERRUPTED
                session["errors"] = list(session.get("errors", [])) + [
                    "BerryLink closed before this session finished. Existing audio was left in place."
                ]
                self._write_session(session, folder)
                changed += 1
        return changed

    def _find_folder(self, session_id: str) -> Path:
        if not isinstance(session_id, str) or not SESSION_ID_RE.fullmatch(session_id):
            raise MeetingError("not_found", "That meeting session was not found.")
        for folder in self.root.iterdir() if self.root.exists() else []:
            if not folder.is_dir() or folder.is_symlink():
                continue
            if folder.name.endswith(session_id):
                return folder
            session = self._read_session_file(folder / "session.json")
            if session and session.get("id") == session_id:
                return folder
        raise MeetingError("not_found", "That meeting session was not found.")

    @staticmethod
    def _read_session_file(path: Path) -> dict[str, Any] | None:
        try:
            if path.stat().st_size > 500_000:
                return None
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
        except (OSError, ValueError):
            return None


class MeetingManager:
    def __init__(
        self,
        config: Config,
        store: MeetingStore,
        ai_getter: Callable[[], Any],
        on_change: Callable[[], None] | None = None,
        logger=None,
    ) -> None:
        self.config = config
        self.store = store
        self.ai_getter = ai_getter
        self.on_change = on_change or (lambda: None)
        self.log = logger
        self._lock = threading.RLock()
        self._recorder: AudioRecorder | None = None
        self._session: dict[str, Any] | None = None
        self._segments: list[dict[str, Any]] = []
        self._transcribe_thread: threading.Thread | None = None
        self._errors: list[str] = []
        self._status_message = ""
        self._last_error: str | None = None

    @property
    def active(self) -> bool:
        with self._lock:
            return self._recorder is not None

    def status(self) -> dict[str, Any]:
        with self._lock:
            session = self._session
            recorder = self._recorder
            if not session:
                return {
                    "recording": False,
                    "session": None,
                    "available": recorder_backend()[0] is not None,
                    "backend": recorder_backend()[1],
                    "message": self._status_message,
                }
            return {
                "recording": bool(recorder and recorder.recording),
                "session": {
                    "id": session.get("id"),
                    "title": session.get("title"),
                    "status": session.get("status"),
                    "started_at": session.get("started_at"),
                    "chunks": len(session.get("chunks", [])),
                    "transcribe": session.get("transcribe"),
                    "retain_audio": session.get("retain_audio"),
                    "errors": session.get("errors", []),
                },
                "backend": recorder.backend_detail if recorder else recorder_backend()[1],
                "transcribing": bool(self._transcribe_thread and self._transcribe_thread.is_alive()),
                "message": self._status_message,
                "last_error": self._last_error,
            }

    def start(
        self,
        *,
        consent: bool,
        transcribe: bool | None = None,
        retain_audio: bool | None = None,
        title: str = "",
    ) -> dict[str, Any]:
        if not consent:
            raise MeetingError("consent_required", "Recording needs explicit consent.")
        with self._lock:
            if self._recorder is not None:
                raise MeetingError("already_recording", "A meeting recording is already active.")
        transcribe = self.config.meeting_transcribe if transcribe is None else bool(transcribe)
        retain_audio = self.config.meeting_retain_audio if retain_audio is None else bool(retain_audio)
        ai = self.ai_getter()
        if transcribe and not hasattr(ai, "transcribe"):
            raise MeetingError(
                "no_ai",
                "Gemini transcription needs a saved API key. Record locally instead, or add a key first.",
            )
        backend, detail = recorder_backend()
        if not backend:
            raise MeetingError("no_recorder", detail)
        session = self.store.create_session(
            title=title or f"Meeting {dt.datetime.now().strftime('%Y-%m-%d %H:%M')}",
            transcribe=transcribe,
            retain_audio=retain_audio,
            model=self.config.meeting_transcription_model,
        )
        audio_dir = self.store.folder_for(session) / "audio"
        recorder = AudioRecorder(
            audio_dir=audio_dir,
            chunk_seconds=self.config.meeting_chunk_seconds,
            on_chunk=lambda chunk: self._on_chunk(session, chunk),
            on_status=self._on_recorder_status,
            logger=self.log,
        )
        with self._lock:
            self._session = session
            self._segments = []
            self._errors = []
            self._last_error = None
            self._recorder = recorder
            self._status_message = "Recording. Everyone in the meeting should know."
        recorder.start()
        if self.log:
            self.log.info("Meeting recording started id=%s backend=%s transcribe=%s", session["id"], backend, transcribe)
        self.on_change()
        return self.status()

    def stop(self) -> dict[str, Any]:
        with self._lock:
            recorder = self._recorder
            session = self._session
            if recorder is None or session is None:
                raise MeetingError("not_recording", "There is no active meeting recording.")
        chunks = recorder.stop()
        with self._lock:
            self._recorder = None
            self._session = session
            self._status_message = "Recording stopped."
        ai = self.ai_getter()
        can_transcribe = bool(session.get("transcribe")) and hasattr(ai, "transcribe")
        if can_transcribe and chunks:
            session["status"] = STATUS_TRANSCRIBING
            self.store.finalize(session, status=STATUS_TRANSCRIBING, segments=self._segments)
            thread = threading.Thread(
                target=self._transcribe_session,
                args=(session, ai),
                name="berrylink-transcription",
                daemon=True,
            )
            with self._lock:
                self._transcribe_thread = thread
            thread.start()
        else:
            self._finish_without_transcription(session)
        self.on_change()
        return self.status()

    def _on_chunk(self, session: dict[str, Any], chunk: RecordedChunk) -> None:
        try:
            if not session.get("retain_audio") and not session.get("transcribe"):
                # Nothing will read it; remove immediately.
                chunk.path.unlink(missing_ok=True)
                entry = {
                    "index": chunk.index,
                    "file": f"audio/{chunk.path.name}",
                    "start_offset": round(chunk.start_offset, 3),
                    "duration": round(chunk.duration, 3),
                    "transcription_status": "not_requested",
                    "error": None,
                    "audio_deleted": True,
                }
                with self._lock:
                    session.setdefault("chunks", []).append(entry)
                self.store.save(session, segments=self._segments)
            else:
                self.store.add_chunk(session, chunk)
        except Exception as exc:
            with self._lock:
                self._last_error = "A recording chunk could not be saved."
            if self.log:
                self.log.warning("meeting chunk save failed: %s", type(exc).__name__)
        self.on_change()

    def _on_recorder_status(self, level: str, message: str) -> None:
        with self._lock:
            self._status_message = message
            if level == "error":
                self._last_error = message
        if self.log:
            (self.log.error if level == "error" else self.log.info)("meeting recorder: %s", message)
        self.on_change()

    def _finish_without_transcription(self, session: dict[str, Any]) -> None:
        status = STATUS_RECORDED if session.get("chunks") else STATUS_ERROR
        if not session.get("retain_audio") and session.get("chunks"):
            for entry in session.get("chunks", []):
                self.store.delete_audio_chunk(session, entry)
        self.store.finalize(session, status=status, segments=self._segments)
        with self._lock:
            self._status_message = (
                "Meeting saved locally."
                if session.get("retain_audio")
                else "Meeting saved without retained audio."
            )
        self.on_change()

    def _transcribe_session(self, session: dict[str, Any], ai) -> None:
        errors: list[str] = []
        for entry in list(session.get("chunks", [])):
            if entry.get("transcription_status") == "done":
                continue
            path = self.store.chunk_path(session, entry)
            if not path.exists():
                self.store.mark_chunk_error(session, entry["index"], "Audio chunk is missing.")
                errors.append("An audio chunk was missing.")
                continue
            try:
                with self._lock:
                    self._status_message = f"Transcribing chunk {entry['index']}…"
                self.on_change()
                audio = path.read_bytes()
                result = ai.transcribe(audio, chunk_start=float(entry.get("start_offset", 0)))
                segments = result.get("segments", []) if isinstance(result, dict) else []
                with self._lock:
                    self._segments.extend(segments)
                    self._segments.sort(key=lambda s: float(s.get("start", 0)))
                self.store.mark_chunk_done(session, entry["index"], str(result.get("summary", "")))
                if not session.get("retain_audio"):
                    self.store.delete_audio_chunk(session, entry)
            except AIError as exc:
                message = exc.message
                errors.append(message)
                self.store.mark_chunk_error(session, entry["index"], message)
                if exc.code in ("quota_exhausted", "auth_failed", "local_daily_limit", "local_rate_limit", "no_key"):
                    # Do not hammer a quota or a rejected key.
                    break
            except Exception as exc:
                message = "A chunk could not be transcribed."
                errors.append(message)
                self.store.mark_chunk_error(session, entry["index"], message)
                if self.log:
                    self.log.warning("transcription chunk failed: %s", type(exc).__name__)
        final_status = STATUS_PARTIAL if errors else STATUS_COMPLETE
        self.store.finalize(
            session,
            status=final_status,
            segments=self._segments,
            error="; ".join(errors[:3]) if errors else None,
        )
        with self._lock:
            self._last_error = errors[-1] if errors else None
            self._status_message = (
                "Meeting notes are ready."
                if not errors
                else "Meeting notes saved, but transcription is incomplete."
            )
        if self.log:
            self.log.info(
                "Meeting transcription finished id=%s status=%s chunks=%s errors=%s",
                session.get("id"),
                final_status,
                len(session.get("chunks", [])),
                len(errors),
            )
        self.on_change()

    def list_sessions(self) -> list[dict[str, Any]]:
        return self.store.list_sessions()

    def read_session(self, session_id: str) -> dict[str, Any]:
        return self.store.read_session(session_id)

    def delete_session(self, session_id: str) -> None:
        with self._lock:
            if self._session and self._session.get("id") == session_id:
                raise MeetingError("recording_active", "Stop the active recording before deleting it.")
        self.store.delete_session(session_id)
        self.on_change()

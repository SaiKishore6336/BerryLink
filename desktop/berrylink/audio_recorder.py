"""Explicit, chunked microphone recording for meeting notes.

The recorder rotates WAV files every five minutes by default.  It uses the
first available native recorder (PipeWire, then ALSA, then SoX).  Nothing is
uploaded here; transcription only starts after the user stops the recording.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


class RecordingError(RuntimeError):
    pass


@dataclass
class RecordedChunk:
    index: int
    path: Path
    start_offset: float
    duration: float


def _probe(binary: str) -> str | None:
    return shutil.which(binary)


def recorder_backend() -> tuple[str | None, str]:
    if _probe("pw-record"):
        return "pw-record", "PipeWire pw-record (16 kHz mono WAV)"
    if _probe("arecord"):
        return "arecord", "ALSA arecord (16 kHz mono WAV)"
    if _probe("sox") and _probe("parec"):
        return "parec", "PulseAudio parec through SoX"
    if _probe("sox"):
        return "sox", "SoX default audio device (16 kHz mono WAV)"
    return None, "No native recorder found (pw-record, arecord, or sox)."


class AudioRecorder:
    def __init__(
        self,
        audio_dir: Path,
        chunk_seconds: int = 300,
        rate: int = 16000,
        on_chunk: Callable[[RecordedChunk], None] | None = None,
        on_status: Callable[[str, str], None] | None = None,
        logger=None,
    ) -> None:
        self.audio_dir = audio_dir
        self.chunk_seconds = max(5, int(chunk_seconds))
        self.rate = rate
        self.on_chunk = on_chunk
        self.on_status = on_status or (lambda _level, _message: None)
        self.log = logger
        self.backend, self.backend_detail = recorder_backend()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self._chunks: list[RecordedChunk] = []
        self._error: str | None = None
        self._started_at = 0.0

    @property
    def recording(self) -> bool:
        return bool(self._thread and self._thread.is_alive() and not self._stop.is_set())

    @property
    def error(self) -> str | None:
        with self._lock:
            return self._error

    @property
    def chunks(self) -> list[RecordedChunk]:
        with self._lock:
            return list(self._chunks)

    def start(self) -> None:
        if self.backend is None:
            raise RecordingError(self.backend_detail)
        if self.recording:
            raise RecordingError("A recording is already in progress.")
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.audio_dir, 0o700)
        except OSError:
            pass
        self._stop.clear()
        self._error = None
        self._chunks = []
        self._started_at = time.monotonic()
        self._thread = threading.Thread(target=self._record_loop, name="berrylink-recorder", daemon=True)
        self._thread.start()

    def stop(self, join_timeout: float = 8.0) -> list[RecordedChunk]:
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=join_timeout)
        with self._lock:
            chunks = list(self._chunks)
        self.on_status("meeting", "Recording stopped.")
        return chunks

    def _argv(self, path: Path) -> list[str]:
        if self.backend == "pw-record":
            return [
                "pw-record",
                "--format",
                "s16",
                "--rate",
                str(self.rate),
                "--channels",
                "1",
                str(path),
            ]
        if self.backend == "arecord":
            return [
                "arecord",
                "-q",
                "-t",
                "wav",
                "-f",
                "S16_LE",
                "-r",
                str(self.rate),
                "-c",
                "1",
                str(path),
            ]
        if self.backend == "parec":
            return [
                "parec",
                "--format=s16le",
                "--rate",
                str(self.rate),
                "--channels=1",
                "--file-format=wav",
                str(path),
            ]
        if self.backend == "sox":
            return ["sox", "-d", "-t", "wav", "-r", str(self.rate), "-c", "1", str(path)]
        raise RecordingError("No audio recorder backend.")

    def _record_loop(self) -> None:
        index = 0
        while not self._stop.is_set():
            index += 1
            path = self.audio_dir / f"chunk-{index:03d}.wav"
            started = time.monotonic() - self._started_at
            proc: subprocess.Popen | None = None
            stderr = b""
            try:
                proc = subprocess.Popen(
                    self._argv(path),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    stdin=subprocess.DEVNULL,
                    env=os.environ.copy(),
                )
            except (OSError, ValueError) as exc:
                self._set_error("The audio recorder could not start.")
                raise RecordingError("The audio recorder could not start.") from exc
            # Catch an immediately failing backend before presenting a fake
            # successful recording.  A real recorder stays alive.
            time.sleep(0.55)
            if proc.poll() is not None and proc.returncode != 0:
                stderr = proc.stderr.read()[-600:] if proc.stderr else b""
                self._set_error("The audio recorder failed to start. Check the microphone/PipeWire source.")
                if self.log:
                    self.log.warning("recorder backend failed: %s", stderr.decode("utf-8", "replace")[:300])
                self._stop.set()
                break
            try:
                while not self._stop.is_set():
                    if proc.poll() is not None:
                        if proc.returncode not in (0, -15):
                            stderr = proc.stderr.read()[-600:] if proc.stderr else b""
                            self._set_error("The audio recorder stopped unexpectedly.")
                        break
                    if (time.monotonic() - self._started_at) - started >= self.chunk_seconds:
                        break
                    time.sleep(0.2)
            finally:
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=4)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=2)
            try:
                if proc.stderr:
                    stderr += proc.stderr.read()[-600:]
            except Exception:
                pass
            try:
                if path.exists() and path.stat().st_size > 44:
                    duration = wav_duration(path)
                    with self._lock:
                        chunk = RecordedChunk(index=index, path=path, start_offset=started, duration=duration)
                        self._chunks.append(chunk)
                    try:
                        os.chmod(path, 0o600)
                    except OSError:
                        pass
                    if self.on_chunk:
                        self.on_chunk(chunk)
            except OSError:
                pass
            if self._error:
                break
        if self._error:
            self.on_status("error", self._error)


def wav_duration(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as handle:
            frames = handle.getnframes()
            rate = handle.getframerate() or 1
            return frames / rate
    except (wave.Error, OSError):
        return 0.0


def validate_wav(path: Path) -> bool:
    try:
        with wave.open(str(path), "rb") as handle:
            return handle.getnframes() > 0 and handle.getframerate() >= 8000
    except (wave.Error, OSError):
        return False

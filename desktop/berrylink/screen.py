"""X11 screen capture and local OCR.

Screen capture uses ImageMagick's `import`, which is already part of Kali's
standard desktop.  OCR uses a project-local Tesseract binary when the system
package is unavailable.  No cloud service is involved in this module.
"""

from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from PIL import Image


class ScreenError(RuntimeError):
    pass


@dataclass
class Screenshot:
    png: bytes
    width: int
    height: int
    pointer_x: int
    pointer_y: int
    active_window: str
    active_class: str
    captured_at: float = field(default_factory=time.monotonic)

    def jpeg(self, max_width: int = 1400, quality: int = 82) -> bytes:
        image = Image.open(io.BytesIO(self.png)).convert("RGB")
        if image.width > max_width:
            height = round(image.height * (max_width / image.width))
            image = image.resize((max_width, height), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        image.save(out, format="JPEG", quality=quality, optimize=True)
        return out.getvalue()


class X11Capture:
    def __init__(self, import_binary: str | None = None) -> None:
        self.import_binary = import_binary or shutil.which("import") or "/usr/bin/import"

    def available(self) -> tuple[bool, str]:
        if not os.environ.get("DISPLAY"):
            return False, "No X11 DISPLAY is set. Screen capture requires an X11 session."
        if not (os.path.isfile(self.import_binary) and os.access(self.import_binary, os.X_OK)):
            return False, "ImageMagick's `import` command is unavailable."
        return True, "X11 / ImageMagick import"

    def _run(self, argv: list[str], timeout: float = 8) -> subprocess.CompletedProcess:
        try:
            return subprocess.run(
                argv,
                capture_output=True,
                timeout=timeout,
                check=False,
                env=os.environ.copy(),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ScreenError(f"Could not run {argv[0]}.") from exc

    def _pointer(self) -> tuple[int, int]:
        try:
            proc = self._run(["xdotool", "getmouselocation", "--shell"], timeout=2)
            x = y = 0
            for line in proc.stdout.decode("utf-8", "replace").splitlines():
                if line.startswith("X="):
                    x = int(line.split("=", 1)[1])
                elif line.startswith("Y="):
                    y = int(line.split("=", 1)[1])
            return x, y
        except (OSError, ValueError, ScreenError):
            return 0, 0

    def _active_window(self) -> tuple[str, str]:
        try:
            proc = self._run(["xdotool", "getactivewindow"], timeout=2)
        except ScreenError:
            return "", ""
        window_id = proc.stdout.decode("utf-8", "replace").strip()
        if not window_id:
            return "", ""
        try:
            name_proc = self._run(["xdotool", "getwindowname", window_id], timeout=2)
            title = name_proc.stdout.decode("utf-8", "replace").strip()
            prop = self._run(["xprop", "-id", window_id, "WM_CLASS"], timeout=2)
            wm_class = ""
            match = re.search(r'WM_CLASS\(STRING\) = (.*)', prop.stdout.decode("utf-8", "replace"))
            if match:
                wm_class = match.group(1).replace('"', "")
            return title[:300], wm_class[:200]
        except ScreenError:
            return "", ""

    def capture(self) -> Screenshot:
        ok, detail = self.available()
        if not ok:
            raise ScreenError(detail)
        proc = self._run([self.import_binary, "-silent", "-window", "root", "png:-"], timeout=15)
        if proc.returncode != 0 or not proc.stdout:
            message = proc.stderr.decode("utf-8", "replace").strip()[:300]
            raise ScreenError(f"Screen capture failed. {message}".strip())
        png = proc.stdout
        try:
            image = Image.open(io.BytesIO(png))
            width, height = image.size
        except Exception as exc:
            raise ScreenError("ImageMagick returned an unreadable image.") from exc
        pointer_x, pointer_y = self._pointer()
        active_window, active_class = self._active_window()
        return Screenshot(
            png=png,
            width=width,
            height=height,
            pointer_x=pointer_x,
            pointer_y=pointer_y,
            active_window=active_window,
            active_class=active_class,
        )


@dataclass
class OcrWord:
    id: str
    text: str
    left: int
    top: int
    width: int
    height: int
    confidence: float

    @property
    def center(self) -> tuple[int, int]:
        return self.left + self.width // 2, self.top + self.height // 2


@dataclass
class OcrLine:
    id: str
    text: str
    left: int
    top: int
    width: int
    height: int
    words: list[OcrWord]

    @property
    def center(self) -> tuple[int, int]:
        return self.left + self.width // 2, self.top + self.height // 2


@dataclass
class Target:
    id: str
    text: str
    kind: str
    left: int
    top: int
    width: int
    height: int
    confidence: float = 100.0

    @property
    def center(self) -> tuple[int, int]:
        return self.left + self.width // 2, self.top + self.height // 2

    def normalized_center(self, width: int, height: int) -> tuple[int, int]:
        x, y = self.center
        return (
            round(max(0, min(1000, (x / max(1, width)) * 1000))),
            round(max(0, min(1000, (y / max(1, height)) * 1000))),
        )


@dataclass
class ScreenSnapshot:
    id: str
    screenshot: Screenshot
    lines: list[OcrLine] = field(default_factory=list)
    error: str | None = None
    created_at: float = field(default_factory=time.monotonic)

    @property
    def width(self) -> int:
        return self.screenshot.width

    @property
    def height(self) -> int:
        return self.screenshot.height

    def all_targets(self) -> list[Target]:
        result: list[Target] = []
        for line in self.lines:
            result.append(
                Target(line.id, line.text, "line", line.left, line.top, line.width, line.height)
            )
            result.extend(
                Target(
                    word.id,
                    word.text,
                    "word",
                    word.left,
                    word.top,
                    word.width,
                    word.height,
                    word.confidence,
                )
                for word in line.words
            )
        return result

    def target(self, target_id: str) -> Target | None:
        wanted = target_id.strip().upper()
        for target in self.all_targets():
            if target.id.upper() == wanted:
                return target
        return None

    def find_text(self, query: str) -> Target | None:
        query = " ".join(query.split()).strip()
        if not query:
            return None
        lowered = query.casefold()
        # Prefer exact line matches, then exact words, then substrings. The
        # returned line lets the character point confidently at short labels.
        for line in self.lines:
            if line.text.strip().casefold() == lowered:
                return Target(line.id, line.text, "line", line.left, line.top, line.width, line.height)
        for line in self.lines:
            for word in line.words:
                if word.text.strip().casefold() == lowered:
                    return Target(word.id, word.text, "word", word.left, word.top, word.width, word.height, word.confidence)
        for line in self.lines:
            if lowered in line.text.casefold():
                return Target(line.id, line.text, "line", line.left, line.top, line.width, line.height)
        return None

    def context_text(self, max_chars: int = 8000) -> str:
        s = self.screenshot
        rows = [
            f"Screen snapshot {self.id}: {self.width}x{self.height}px, "
            f"pointer at ({s.pointer_x},{s.pointer_y}).",
            f"Active window: {s.active_window or '(unknown)'} "
            f"[{s.active_class or 'no WM_CLASS'}].",
        ]
        if self.error:
            rows.append(f"OCR note: {self.error}")
        if not self.lines:
            rows.append("No readable text was found. You can still point at a spot on screen.")
            return "\n".join(rows)[:max_chars]
        rows.append("On-screen targets (id | kind | text | center in 0-1000 coordinates):")
        count = 0
        for line in self.lines:
            nx, ny = Target(line.id, line.text, "line", line.left, line.top, line.width, line.height).normalized_center(self.width, self.height)
            rows.append(f"{line.id} | line | {line.text[:280]} | {nx},{ny}")
            count += 1
            # Include the words for short lines so the character can point at
            # a single label rather than the whole row.
            for word in line.words[:12]:
                nx, ny = Target(word.id, word.text, "word", word.left, word.top, word.width, word.height).normalized_center(self.width, self.height)
                rows.append(f"{word.id} | word | {word.text[:80]} | {nx},{ny}")
                count += 1
                if count >= 240:
                    break
            if count >= 240:
                rows.append("(More text is on screen; ask me to look again for a fresh list.)")
                break
        return "\n".join(rows)[:max_chars]


class LocalOcr:
    def __init__(
        self,
        binary: Path | str | None = None,
        tessdata: Path | str | None = None,
    ) -> None:
        self.binary = Path(binary) if binary else self._find_binary()
        self.tessdata = Path(tessdata) if tessdata else self._find_tessdata()

    @staticmethod
    def _find_binary() -> Path | None:
        env = os.environ.get("BERRYLINK_TESSERACT")
        if env and Path(env).is_file():
            return Path(env)
        vendor = Path(os.environ.get("BERRYLINK_VENDOR_DIR", Path.home() / ".local/share/berrylink/vendor"))
        candidate = vendor / "tesseract" / "bin" / "tesseract"
        if candidate.is_file():
            return candidate
        found = shutil.which("tesseract")
        return Path(found) if found else None

    def _find_tessdata(self) -> Path | None:
        env = os.environ.get("TESSDATA_PREFIX")
        if env and Path(env).is_dir():
            return Path(env)
        if self.binary:
            sibling = self.binary.parent.parent / "tessdata"
            if sibling.is_dir():
                return sibling
        for candidate in (
            Path("/usr/share/tesseract-ocr/5/tessdata"),
            Path("/usr/share/tesseract-ocr/4.00/tessdata"),
            Path("/usr/share/tessdata"),
        ):
            if (candidate / "eng.traineddata").is_file():
                return candidate
        return None

    def available(self) -> tuple[bool, str]:
        if not self.binary or not self.binary.is_file():
            return False, "Tesseract OCR is not installed. Run scripts/install-local-ocr.sh."
        if not self.tessdata or not (self.tessdata / "eng.traineddata").is_file():
            return False, "Tesseract English language data is missing."
        try:
            proc = subprocess.run(
                [str(self.binary), "--version"],
                capture_output=True,
                text=True,
                timeout=5,
                env=os.environ.copy(),
            )
            first = (proc.stdout or proc.stderr).splitlines()[0] if (proc.stdout or proc.stderr) else "Tesseract"
            return proc.returncode == 0, first
        except (OSError, subprocess.SubprocessError):
            return False, "Tesseract could not be executed."

    def ocr(self, png: bytes) -> tuple[list[OcrLine], str | None]:
        ok, detail = self.available()
        if not ok:
            return [], detail
        with tempfile.TemporaryDirectory(prefix="berrylink-ocr-") as tmp:
            image_path = Path(tmp) / "screen.png"
            image_path.write_bytes(png)
            env = os.environ.copy()
            if self.tessdata:
                env["TESSDATA_PREFIX"] = str(self.tessdata)
            output_base = Path(tmp) / "out"
            try:
                proc = subprocess.run(
                    [
                        str(self.binary),
                        str(image_path),
                        str(output_base),
                        "--psm",
                        "11",
                        "--oem",
                        "3",
                        "-l",
                        "eng",
                        "-c",
                        "tessedit_create_tsv=1",
                    ],
                    capture_output=True,
                    timeout=30,
                    env=env,
                    check=False,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                return [], f"OCR failed: {exc}"
            tsv_path = Path(str(output_base) + ".tsv")
            if proc.returncode != 0 or not tsv_path.exists():
                message = (proc.stderr or b"")[:300].decode("utf-8", "replace").strip()
                return [], f"OCR failed. {message}".strip()
            try:
                lines = self._parse_tsv(tsv_path.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                return [], "OCR output could not be read."
            if not lines:
                return [], "OCR found no readable text."
            return lines, None

    @staticmethod
    def _parse_tsv(text: str) -> list[OcrLine]:
        grouped: dict[tuple[str, str, str], list[dict]] = {}
        header = None
        for raw in text.splitlines():
            cols = raw.split("\t")
            if header is None:
                header = cols
                continue
            if len(cols) < 12:
                continue
            try:
                conf = float(cols[10])
                left = int(cols[6])
                top = int(cols[7])
                width = int(cols[8])
                height = int(cols[9])
            except ValueError:
                continue
            word = cols[11].strip()
            if not word or conf < 35 or width <= 0 or height <= 0:
                continue
            key = (cols[1], cols[2], cols[4])
            grouped.setdefault(key, []).append(
                {"text": word, "left": left, "top": top, "width": width, "height": height, "conf": conf}
            )
        lines: list[OcrLine] = []
        for index, words in enumerate(grouped.values(), start=1):
            words.sort(key=lambda w: w["left"])
            text = " ".join(w["text"] for w in words).strip()
            if not text:
                continue
            left = min(w["left"] for w in words)
            top = min(w["top"] for w in words)
            right = max(w["left"] + w["width"] for w in words)
            bottom = max(w["top"] + w["height"] for w in words)
            line = OcrLine(
                id=f"L{index}",
                text=text[:500],
                left=left,
                top=top,
                width=right - left,
                height=bottom - top,
                words=[],
            )
            for word_index, item in enumerate(words[:24], start=1):
                line.words.append(
                    OcrWord(
                        id=f"W{index}_{word_index}",
                        text=item["text"][:80],
                        left=item["left"],
                        top=item["top"],
                        width=item["width"],
                        height=item["height"],
                        confidence=item["conf"],
                    )
                )
            lines.append(line)
            if len(lines) >= 120:
                break
        return lines


class ScreenAwareness:
    """Capture + OCR with a short cache and a bridge for hiding the overlay."""

    def __init__(
        self,
        capture: X11Capture | None = None,
        ocr: LocalOcr | None = None,
        hide_overlay: Callable[[], None] | None = None,
        show_overlay: Callable[[], None] | None = None,
        cache_seconds: float = 8.0,
    ) -> None:
        self.capture = capture or X11Capture()
        self.ocr = ocr or LocalOcr()
        self.hide_overlay = hide_overlay
        self.show_overlay = show_overlay
        self.cache_seconds = cache_seconds
        self._latest: ScreenSnapshot | None = None
        self._lock = __import__("threading").RLock()

    def available(self) -> dict[str, str | bool]:
        cap_ok, cap_detail = self.capture.available()
        ocr_ok, ocr_detail = self.ocr.available()
        return {
            "capture": cap_ok,
            "capture_detail": cap_detail,
            "ocr": ocr_ok,
            "ocr_detail": ocr_detail,
        }

    def latest(self) -> ScreenSnapshot | None:
        with self._lock:
            return self._latest

    def capture_now(self, hide_overlay: bool = True) -> ScreenSnapshot:
        if hide_overlay and self.hide_overlay:
            try:
                self.hide_overlay()
                time.sleep(0.12)
            except Exception:
                pass
        try:
            shot = self.capture.capture()
        finally:
            if hide_overlay and self.show_overlay:
                try:
                    self.show_overlay()
                except Exception:
                    pass
        lines, error = self.ocr.ocr(shot.png)
        snapshot = ScreenSnapshot(
            id=uuid.uuid4().hex[:10],
            screenshot=shot,
            lines=lines,
            error=error,
        )
        with self._lock:
            self._latest = snapshot
        return snapshot

    def get(self, force: bool = False, hide_overlay: bool = True) -> ScreenSnapshot:
        with self._lock:
            latest = self._latest
            if latest and not force and (time.monotonic() - latest.created_at) < self.cache_seconds:
                return latest
        return self.capture_now(hide_overlay=hide_overlay)

    def point_to_screen(
        self, target: Target, width: int, height: int
    ) -> tuple[int, int]:
        """Convert an OCR target center to X11 root pixel coordinates."""
        x, y = target.center
        return max(0, min(width - 1, x)), max(0, min(height - 1, y))

    def normalized_to_pixels(self, x: int, y: int, width: int, height: int) -> tuple[int, int]:
        px = round((max(0, min(1000, x)) / 1000) * (width - 1))
        py = round((max(0, min(1000, y)) / 1000) * (height - 1))
        return px, py

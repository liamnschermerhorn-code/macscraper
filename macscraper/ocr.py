"""Read the text in listing photos (About This Mac screenshots, model-number stickers, serial labels).

The recognised text is appended to the listing's description, so the normal filters see it: a photo
that says "Chip Apple M2 / Memory 24 GB" settles a listing whose title never named either, and one
that says "Intel Core i7" or shows a serial from the old 11/12-character format rejects it.

Engines (first one available wins):
  * Apple Vision - built into macOS, free, on-device. `uv sync --extra ocr` installs the bridge.
  * Tesseract    - `brew install tesseract` plus `uv add pytesseract pillow` (also works on Linux).
"""
from __future__ import annotations

import io
import re
from typing import Callable

import httpx

OcrFn = Callable[[bytes], str]

MAX_IMAGE_BYTES = 8_000_000
MIN_IMAGE_BYTES = 3_000  # skip icons / spacer pixels


# ------------------------------------------------------------------ engines
def vision_ocr(data: bytes) -> str:
    """Apple's Vision framework (VNRecognizeTextRequest) via PyObjC."""
    import Foundation
    import Vision

    handler = Vision.VNImageRequestHandler.alloc().initWithData_options_(
        Foundation.NSData.dataWithBytes_length_(data, len(data)), None
    )
    request = Vision.VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    # Serial numbers and part numbers aren't words: don't let a dictionary "correct" them.
    request.setUsesLanguageCorrection_(False)
    ok, error = handler.performRequests_error_([request], None)
    if not ok:
        raise RuntimeError(f"Vision failed: {error}")
    lines = []
    for observation in request.results() or []:
        candidates = observation.topCandidates_(1)
        if candidates:
            lines.append(str(candidates[0].string()))
    return "\n".join(lines)


def tesseract_ocr(data: bytes) -> str:
    import pytesseract
    from PIL import Image

    return pytesseract.image_to_string(Image.open(io.BytesIO(data)))


def get_backend(preferred: str = "auto") -> OcrFn | None:
    """The best OCR engine available on this machine, or None."""
    if preferred in ("auto", "vision"):
        try:
            import Foundation  # noqa: F401
            import Vision  # noqa: F401

            return vision_ocr
        except ImportError:
            pass
    if preferred in ("auto", "tesseract"):
        try:
            import pytesseract
            from PIL import Image  # noqa: F401

            pytesseract.get_tesseract_version()
            return tesseract_ocr
        except Exception:
            pass
    return None


# ------------------------------------------------------------------ text -> useful lines
# Photos are full of noise (menu bars, desktop icons). Keep only lines that could say what the machine is.
USEFUL_RE = re.compile(
    r"chip|memory|processor|serial|model|mac\s?book|mac\s?mini|mac\s?studio|\bimac\b|intel|core\s?i[3579]|"
    r"apple\s*m\d|\bm[1-5]\b|\bA\d{4}\b|\d\s?gb\b|touch\s*bar|ghz|retina|inch|\b(?:19|20)\d\d\b|"
    r"activation|icloud|find\s*my|mdm|supervis|managed|enterprise|battery|cycle|storage|macos",
    re.I,
)


def useful_text(raw: str, limit: int = 700) -> str:
    seen, keep = set(), []
    for line in raw.splitlines():
        line = line.strip()
        if 3 <= len(line) <= 140 and USEFUL_RE.search(line) and line.lower() not in seen:
            seen.add(line.lower())
            keep.append(line)
    return " | ".join(keep)[:limit]


# ------------------------------------------------------------------ one listing
def read_photos(client: httpx.Client, item, backend: OcrFn, max_images: int, log=lambda *_: None) -> str:
    """Download a listing's photos, OCR them, and return the useful lines (empty string if none)."""
    chunks = []
    for url in item.images[:max_images]:
        try:
            r = client.get(url, timeout=20)
            r.raise_for_status()
            data = r.content
            if not (MIN_IMAGE_BYTES <= len(data) <= MAX_IMAGE_BYTES):
                continue
            if text := useful_text(backend(data)):
                chunks.append(text)
        except Exception as e:  # a bad photo shouldn't sink the listing
            log(f"  photo skipped ({e.__class__.__name__}) {url[:70]}")
    return " | ".join(chunks)[:1200]

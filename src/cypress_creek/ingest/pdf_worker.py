# ABOUTME: The child process that parses one hostile PDF: limits first, then pypdf, then JSON out.
# ABOUTME: It reads bytes on stdin, keeps only visible page text, and never touches the network.
import contextlib
import io
import json
import math
import os
import socket
import sys
from collections.abc import Sequence
from typing import Any

HIDDEN_WHITE = "hidden_white_text"
HIDDEN_TINY = "hidden_tiny_text"
HIDDEN_OFFPAGE = "hidden_offpage_text"
HIDDEN_INVISIBLE = "hidden_invisible_text"
INVISIBLE_RENDER_MODES = (3.0, 7.0)
MIN_VISIBLE_POINTS = 4.0
NEAR_WHITE = 0.95
NEAR_NO_INK = 0.05


def _blocked(*_args: object, **_kwargs: object) -> Any:
    raise OSError("the PDF worker has no network access")


def block_network() -> None:
    """Defense in depth, not a sandbox: the parser never needs a socket, so none can be made."""
    socket.socket = _blocked  # type: ignore[misc,assignment]
    socket.create_connection = _blocked
    socket.getaddrinfo = _blocked
    socket.gethostbyname = _blocked


def apply_limits(limits: dict[str, Any]) -> bool:
    """POSIX resource limits: memory, CPU seconds, no files created. False when unavailable."""
    try:
        import resource
    except ImportError:
        return False
    memory = int(limits["memory_bytes"])
    cpu = int(math.ceil(float(limits["timeout_seconds"]))) + 1
    for kind, value in (
        (resource.RLIMIT_AS, memory),
        (resource.RLIMIT_CPU, cpu),
        (resource.RLIMIT_FSIZE, 0),
        (resource.RLIMIT_CORE, 0),
    ):
        resource.setrlimit(kind, (value, value))
    return True


def _is_white(components: Sequence[float]) -> bool:
    if len(components) == 4:
        return all(value <= NEAR_NO_INK for value in components)
    return len(components) in (1, 3) and all(value >= NEAR_WHITE for value in components)


class PageText:
    """Collects the visible text of one page and counts what it dropped."""

    def __init__(self, left: float, bottom: float, right: float, top: float) -> None:
        self.box = (left, bottom, right, top)
        self.fill: tuple[float, ...] = (0.0,)
        self.mode = 0.0
        self.saved: list[tuple[tuple[float, ...], float]] = []
        self.pieces: list[str] = []
        self.dropped: dict[str, int] = {}

    def operand(self, operator: bytes, args: list[Any], _cm: Any, _tm: Any) -> None:
        name = operator.decode("latin-1")
        if name == "q":
            self.saved.append((self.fill, self.mode))
        elif name == "Q" and self.saved:
            self.fill, self.mode = self.saved.pop()
        elif name == "Tr":
            with contextlib.suppress(IndexError, TypeError, ValueError):
                self.mode = float(args[0])
        elif name in ("g", "rg", "k", "sc", "scn"):
            with contextlib.suppress(TypeError, ValueError):
                self.fill = tuple(float(value) for value in args)

    def text(self, text: str, cm: list[float], tm: list[float], _font: Any, size: float) -> None:
        if not text.strip():
            self.pieces.append(text)
            return
        reason = self._hidden(cm, tm, size)
        if reason is None:
            self.pieces.append(text)
        else:
            self.dropped[reason] = self.dropped.get(reason, 0) + 1

    def _hidden(self, cm: list[float], tm: list[float], size: float) -> str | None:
        if self.mode in INVISIBLE_RENDER_MODES:
            return HIDDEN_INVISIBLE
        if _is_white(self.fill):
            return HIDDEN_WHITE
        scale = math.sqrt(abs((tm[0] * tm[3] - tm[1] * tm[2]) * (cm[0] * cm[3] - cm[1] * cm[2])))
        if size * scale < MIN_VISIBLE_POINTS:
            return HIDDEN_TINY
        x = tm[4] * cm[0] + tm[5] * cm[2] + cm[4]
        y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
        left, bottom, right, top = self.box
        if not (left <= x <= right and bottom <= y <= top):
            return HIDDEN_OFFPAGE
        return None


def _fail(code: str) -> dict[str, Any]:
    return {"ok": False, "error": code}


def extract(data: bytes, limits: dict[str, Any]) -> dict[str, Any]:
    import logging

    import pypdf
    import pypdf.filters
    from pypdf import errors

    logging.disable(logging.CRITICAL)
    pypdf.filters.ZLIB_MAX_OUTPUT_LENGTH = int(limits["max_decoded_bytes"])
    try:
        reader = pypdf.PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            return _fail("PdfEncrypted")
        root: Any = reader.trailer["/Root"]
        claimed = int(root["/Pages"].get("/Count", 0))
        count = len(reader.pages)
        if max(claimed, count) > int(limits["max_pages"]):
            return _fail("PdfTooManyPages")
        warnings: dict[str, int] = {}
        if reader.metadata:
            warnings["metadata_dropped"] = len(reader.metadata)
        if root.get("/AcroForm"):
            warnings["form_fields_dropped"] = 1
        chunks: list[str] = []
        total = 0
        for page in reader.pages:
            annotations = page.get("/Annots") or []
            if annotations:
                warnings["annotations_dropped"] = warnings.get("annotations_dropped", 0) + len(
                    annotations
                )
            box = page.mediabox
            collector = PageText(
                float(box.left), float(box.bottom), float(box.right), float(box.top)
            )
            page.extract_text(visitor_operand_before=collector.operand, visitor_text=collector.text)
            for kind, number in collector.dropped.items():
                warnings[kind] = warnings.get(kind, 0) + number
            text = "".join(collector.pieces)
            total += len(text)
            if total > int(limits["max_chars"]):
                return _fail("PdfTooMuchText")
            chunks.append(text)
    except errors.LimitReachedError:
        return _fail("PdfResourceLimit")
    except MemoryError:
        return _fail("PdfResourceLimit")
    except errors.FileNotDecryptedError:
        return _fail("PdfEncrypted")
    except (errors.PyPdfError, KeyError, ValueError, TypeError, AttributeError, OSError):
        return _fail("PdfCorrupt")
    text = "\n".join(chunks).strip()
    if not text:
        return _fail("PdfNoText")
    return {
        "ok": True,
        "text": text,
        "pages": count,
        "warnings": [{"kind": kind, "count": number} for kind, number in sorted(warnings.items())],
    }


def self_check(limits: dict[str, Any]) -> dict[str, Any]:
    try:
        socket.socket()
        blocked = False
    except OSError:
        blocked = True
    try:
        with open(os.devnull, "rb"):
            pass
        open_ok = True
    except OSError:
        open_ok = False
    return {
        "env": dict(os.environ),
        "socket_blocked": blocked,
        "limits_applied": limits.get("applied", False),
        "can_open_files_for_reading": open_ok,
    }


def main(argv: list[str]) -> int:
    limits = json.loads(argv[0])
    block_network()
    limits["applied"] = apply_limits(limits)
    if len(argv) > 1 and argv[1] == "--self-check":
        sys.stdout.write(json.dumps(self_check(limits)))
        return 0
    data = sys.stdin.buffer.read(int(limits["max_bytes"]) + 1)
    try:
        result = extract(data, limits)
    except MemoryError:
        result = _fail("PdfResourceLimit")
    sys.stdout.write(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

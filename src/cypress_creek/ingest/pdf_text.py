# ABOUTME: Extracts the visible text of an untrusted PDF in a child process with hard limits.
# ABOUTME: The parent only reads a size-checked JSON answer, so a hostile file cannot hurt it.
import contextlib
import json
import logging
import os
import subprocess
import sys
import tempfile
import threading
from dataclasses import asdict, dataclass
from importlib.metadata import version
from typing import IO, Any

from cypress_creek.ingest.models import Extractor

PDF_MAGIC = b"%PDF-"
WORKER_MODULE = "cypress_creek.ingest.pdf_worker"
MIB = 1024 * 1024
OUTPUT_SLACK_BYTES = 64 * 1024
STDERR_TAIL_BYTES = 2048

logger = logging.getLogger(__name__)


class PdfError(Exception):
    """A PDF that cannot be read. The class name is the stable error code."""


class PdfTooLarge(PdfError):
    pass


class PdfTooManyPages(PdfError):
    pass


class PdfTooMuchText(PdfError):
    pass


class PdfEncrypted(PdfError):
    pass


class PdfCorrupt(PdfError):
    pass


class PdfNoText(PdfError):
    pass


class PdfTimeout(PdfError):
    pass


class PdfResourceLimit(PdfError):
    pass


ERRORS: dict[str, type[PdfError]] = {
    cls.__name__: cls
    for cls in (
        PdfTooLarge,
        PdfTooManyPages,
        PdfTooMuchText,
        PdfEncrypted,
        PdfCorrupt,
        PdfNoText,
        PdfTimeout,
        PdfResourceLimit,
    )
}


@dataclass(frozen=True)
class PdfLimits:
    """Every cap has a safe default. Exceeding one is a typed error, never a silent cut."""

    max_bytes: int = 10 * MIB
    max_pages: int = 50
    max_chars: int = 200_000
    max_decoded_bytes: int = 32 * MIB
    timeout_seconds: float = 20.0
    memory_bytes: int = 1024 * MIB


@dataclass(frozen=True)
class PdfWarning:
    kind: str
    count: int


@dataclass(frozen=True)
class PdfText:
    text: str
    pages: int
    warnings: tuple[PdfWarning, ...]
    extractor: Extractor


def extractor_identity() -> Extractor:
    return Extractor(name="pypdf", version=version("pypdf"))


def worker_command(limits: PdfLimits, *flags: str) -> list[str]:
    return [sys.executable, "-I", "-m", WORKER_MODULE, json.dumps(asdict(limits)), *flags]


def _child_environment() -> dict[str, str]:
    """Nothing from the parent. Windows needs SYSTEMROOT to start Python at all."""
    if os.name == "nt" and "SYSTEMROOT" in os.environ:
        return {"SYSTEMROOT": os.environ["SYSTEMROOT"]}
    return {}


def _feed(process: subprocess.Popen[bytes], data: bytes) -> None:
    assert process.stdin is not None
    try:
        with contextlib.suppress(BrokenPipeError, OSError):
            process.stdin.write(data)
    finally:
        with contextlib.suppress(BrokenPipeError, OSError):
            process.stdin.close()


def _drain(stream: IO[bytes], tail: bytearray) -> None:
    """Read the child's stderr to the end, keeping only the last STDERR_TAIL_BYTES."""
    with contextlib.suppress(OSError, ValueError):
        while chunk := stream.read(4096):
            tail.extend(chunk)
            del tail[:-STDERR_TAIL_BYTES]


def _stopped(process: subprocess.Popen[bytes], tail: bytearray) -> PdfResourceLimit:
    """The error for a worker that failed. The stderr tail goes to the log and the message, which
    the API never sends to a caller, so a maintainer can see why a platform fails."""
    detail = bytes(tail).decode("utf-8", errors="replace").strip()
    message = (
        f"the PDF worker was stopped by its limits (exit {process.returncode}; stderr: {detail!r})"
    )
    logger.warning(message)
    return PdfResourceLimit(message)


def run_worker(limits: PdfLimits, data: bytes, *flags: str) -> bytes:
    """Run the worker with an empty environment in an empty folder.

    The answer is read with a hard cap while the child runs, and the child is killed the moment
    it passes the cap or the timeout, so a flooding child cannot fill the parent's memory."""
    cap = limits.max_chars * 4 + OUTPUT_SLACK_BYTES
    options: dict[str, Any] = {"start_new_session": True} if os.name == "posix" else {}
    with tempfile.TemporaryDirectory() as empty:
        process: subprocess.Popen[bytes] = subprocess.Popen(
            worker_command(limits, *flags),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=_child_environment(),
            cwd=empty,
            close_fds=True,
            **options,
        )
        timed_out = threading.Event()

        def expire() -> None:
            timed_out.set()
            process.kill()

        timer = threading.Timer(limits.timeout_seconds, expire)
        timer.start()
        tail = bytearray()
        feeder = threading.Thread(target=_feed, args=(process, data), daemon=True)
        feeder.start()
        assert process.stderr is not None
        drainer = threading.Thread(target=_drain, args=(process.stderr, tail), daemon=True)
        drainer.start()
        try:
            assert process.stdout is not None
            out = process.stdout.read(cap + 1)
            if len(out) > cap:
                process.kill()
        finally:
            timer.cancel()
            process.kill()
            process.wait()
            feeder.join()
            drainer.join(timeout=2)
            if process.stdout is not None:
                process.stdout.close()
            process.stderr.close()
    if timed_out.is_set():
        raise PdfTimeout("the PDF took too long to read")
    if len(out) > cap or process.returncode != 0:
        raise _stopped(process, tail)
    return out


def extract_pdf_text(data: bytes, limits: PdfLimits | None = None) -> PdfText:
    """The visible text of a PDF, with a warning for each kind of hidden content dropped."""
    limits = limits or PdfLimits()
    if len(data) > limits.max_bytes:
        raise PdfTooLarge("the PDF is larger than the size limit")
    if not data.startswith(PDF_MAGIC):
        raise PdfCorrupt("the file is not a PDF")
    out = run_worker(limits, data)
    try:
        answer = json.loads(out)
    except ValueError:
        raise PdfResourceLimit("the PDF worker gave no answer") from None
    if not isinstance(answer, dict) or not answer.get("ok"):
        code = answer.get("error") if isinstance(answer, dict) else None
        raise ERRORS.get(str(code), PdfCorrupt)("the PDF could not be read")
    return PdfText(
        text=str(answer["text"]),
        pages=int(answer["pages"]),
        warnings=tuple(PdfWarning(str(w["kind"]), int(w["count"])) for w in answer["warnings"]),
        extractor=extractor_identity(),
    )

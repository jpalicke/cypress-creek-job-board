# ABOUTME: Extracts the visible text of an untrusted PDF in a child process with hard limits.
# ABOUTME: The parent only reads a size-checked JSON answer, so a hostile file cannot hurt it.
import json
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from importlib.metadata import version

from cypress_creek.ingest.models import Extractor

PDF_MAGIC = b"%PDF-"
WORKER_MODULE = "cypress_creek.ingest.pdf_worker"
MIB = 1024 * 1024
OUTPUT_SLACK_BYTES = 64 * 1024


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


def run_worker(limits: PdfLimits, data: bytes, *flags: str) -> bytes:
    """Run the worker with an empty environment in an empty folder, and kill it on a timeout."""
    command = [sys.executable, "-I", "-m", WORKER_MODULE, json.dumps(asdict(limits)), *flags]
    cap = limits.max_chars * 4 + OUTPUT_SLACK_BYTES
    with tempfile.TemporaryDirectory() as empty:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env={},
            cwd=empty,
            close_fds=True,
            start_new_session=True,
        )
        try:
            out, _ = process.communicate(data, timeout=limits.timeout_seconds)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            raise PdfTimeout("the PDF took too long to read") from None
    if process.returncode != 0 or len(out) > cap:
        raise PdfResourceLimit("the PDF worker was stopped by its limits")
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

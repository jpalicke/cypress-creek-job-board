# ABOUTME: Extracts readable posting text from bounded, untrusted HTML bytes.
# ABOUTME: Drops hidden content and reports how many hidden elements were removed.
import codecs
import re
from dataclasses import dataclass
from html.parser import HTMLParser

MAX_HTML_BYTES = 10 * 1024 * 1024
MAX_HTML_DEPTH = 128
_BLOCK_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "br", "div", "tr"}
_VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}
_NON_CONTENT_TAGS = {"script", "style", "noscript", "template", "meta", "head"}
_BOILERPLATE_TAGS = {"nav", "footer"}
_COOKIE_MARKERS = {"cookie-banner", "cookie-consent", "cookie-notice"}


class HtmlTextError(Exception):
    """The HTML cannot be extracted safely within the parser limits."""


class HtmlTextTooLarge(HtmlTextError):
    """The input exceeds the HTML byte cap."""


class HtmlTextTooDeep(HtmlTextError):
    """The input exceeds the element depth cap."""


@dataclass(frozen=True)
class HtmlTextWarning:
    kind: str
    count: int


@dataclass(frozen=True)
class ExtractedText:
    text: str
    warnings: tuple[HtmlTextWarning, ...]


@dataclass(frozen=True)
class _Frame:
    tag: str
    suppressed: bool


def _hidden_by_style(value: str) -> bool:
    declarations = dict(
        (property_name.strip().lower(), setting.strip().lower().removesuffix("!important").strip())
        for declaration in value.split(";")
        if ":" in declaration
        for property_name, setting in [declaration.split(":", 1)]
    )
    if declarations.get("display", "").replace(" ", "") == "none":
        return True
    if declarations.get("visibility", "").strip() in {"hidden", "collapse"}:
        return True
    font_size = declarations.get("font-size", "")
    if re.fullmatch(r"0(?:\.0+)?(?:px|em|rem|%)?", font_size):
        return True
    dimensions = (declarations.get("width", ""), declarations.get("height", ""))
    if all(re.fullmatch(r"0(?:\.0+)?(?:px|em|rem|%)?", size) for size in dimensions):
        return True
    if declarations.get("position", "") in {"absolute", "fixed"}:
        for coordinate in (declarations.get("left", ""), declarations.get("top", "")):
            if re.fullmatch(r"-\d+(?:\.\d+)?px", coordinate) and float(coordinate[:-2]) <= -1000:
                return True
    return False


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.stack: list[_Frame] = []
        self.hidden_count = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        markers = {(attributes.get("id") or "").lower()}
        markers.update((attributes.get("class") or "").lower().split())
        is_boilerplate = tag in _BOILERPLATE_TAGS or bool(markers & _COOKIE_MARKERS)
        is_hidden = tag in _NON_CONTENT_TAGS or (
            "hidden" in attributes
            or (attributes.get("aria-hidden") or "").strip().lower() == "true"
            or _hidden_by_style(attributes.get("style") or "")
        )
        if is_hidden:
            self.hidden_count += 1
        suppressed = (
            is_hidden or is_boilerplate or (self.stack[-1].suppressed if self.stack else False)
        )
        if tag in _BLOCK_TAGS and not suppressed:
            self.parts.append("\n")
        if tag not in _VOID_TAGS:
            if len(self.stack) >= MAX_HTML_DEPTH:
                raise HtmlTextTooDeep("HTML element depth exceeds the limit")
            self.stack.append(_Frame(tag, suppressed))

    def handle_endtag(self, tag: str) -> None:
        match = next(
            (i for i in range(len(self.stack) - 1, -1, -1) if self.stack[i].tag == tag),
            None,
        )
        if match is None:
            return
        suppressed = self.stack[match].suppressed
        del self.stack[match:]
        if tag in _BLOCK_TAGS and not suppressed:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.stack or not self.stack[-1].suppressed:
            self.parts.append(data)


def html_to_text(html: bytes, encoding_hint: str | None = None) -> ExtractedText:
    """Extract line-oriented visible text without executing page content."""
    if len(html) > MAX_HTML_BYTES:
        raise HtmlTextTooLarge("HTML input exceeds the byte limit")
    if html.startswith(codecs.BOM_UTF8):
        encoding = "utf-8-sig"
    else:
        meta = re.search(
            rb"<meta\b[^>]*\bcharset\s*=\s*['\"]?([a-z0-9._-]+)",
            html[:1024],
            flags=re.IGNORECASE,
        )
        declared = meta.group(1).decode("ascii") if meta else None
        try:
            encoding = codecs.lookup(encoding_hint or declared or "utf-8").name
        except LookupError:
            encoding = "utf-8"
    parser = _VisibleTextParser()
    parser.feed(html.decode(encoding, errors="replace"))
    parser.close()
    lines = [line.strip() for line in "".join(parser.parts).splitlines()]
    text = "\n".join(line for line in lines if line)
    warnings = (
        (HtmlTextWarning("hidden_elements_removed", parser.hidden_count),)
        if parser.hidden_count
        else ()
    )
    return ExtractedText(text, warnings)

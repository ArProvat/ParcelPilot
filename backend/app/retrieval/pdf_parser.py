"""Section-aware PDF parser for the assessment document corpus."""
from dataclasses import dataclass
from pathlib import Path
import re

from pypdf import PdfReader

from app.retrieval.authority import EvidenceDomain
from app.retrieval.source_registry import SourceDefinition


@dataclass(frozen=True)
class ParsedChunk:
    source: SourceDefinition
    page: int | None
    section: str | None
    content: str
    domain: str
    chunk_index: int


SECTION_RE = re.compile(r"^(?P<number>\d+)\.\s+(?P<title>.+)$")


def parse_pdf_sections(path: Path, source: SourceDefinition) -> list[ParsedChunk]:
    reader = PdfReader(str(path))
    chunks: list[ParsedChunk] = []
    chunk_index = 0

    for page_index, page in enumerate(reader.pages, start=1):
        lines = [_normalize_line(line) for line in (page.extract_text() or "").splitlines()]
        lines = [line for line in lines if line]

        section = _initial_section(source)
        buffer: list[str] = []

        for line in lines:
            if _is_document_header(line, source):
                continue

            heading = _heading_title(line)
            if heading is not None:
                if buffer:
                    chunks.append(_make_chunk(source, page_index, section, buffer, chunk_index))
                    chunk_index += 1
                section = heading
                buffer = []
                continue

            if _is_metadata_line(line):
                continue

            buffer.append(line)

        if buffer:
            chunks.append(_make_chunk(source, page_index, section, buffer, chunk_index))
            chunk_index += 1

    return chunks


def _make_chunk(
    source: SourceDefinition,
    page: int,
    section: str | None,
    buffer: list[str],
    chunk_index: int,
) -> ParsedChunk:
    body = " ".join(buffer)
    content = f"{source.source_name}\n"
    if section:
        content += f"Section: {section}\n"
    content += body
    return ParsedChunk(
        source=source,
        page=page,
        section=section,
        content=content,
        domain=_classify_domain(section, body),
        chunk_index=chunk_index,
    )


def _normalize_line(line: str) -> str:
    return re.sub(r"\s+", " ", line).strip()


def _heading_title(line: str) -> str | None:
    match = SECTION_RE.match(line)
    if not match:
        return None
    return match.group("title").strip()


def _initial_section(source: SourceDefinition) -> str | None:
    if source.source_key == "support_policy_v2":
        return "Severity and response targets"
    return None


def _is_document_header(line: str, source: SourceDefinition) -> bool:
    if line == source.source_name:
        return True
    if source.source_key == "northstar_agreement" and line == "Agreement":
        return True
    return False


def _is_metadata_line(line: str) -> bool:
    return (
        line.startswith("Status:")
        or line.startswith("Effective:")
        or line.startswith("Account:")
        or line.startswith("Opened:")
    )


def _classify_domain(section: str | None, body: str) -> str:
    text = f"{section or ''} {body}".lower()
    if "cancellation" in text or "cancel" in text:
        return EvidenceDomain.CANCELLATION
    if "credit" in text or "failed-pickup" in text or "failed pickup" in text:
        return EvidenceDomain.SERVICE_CREDIT
    if "support" in text or "sla" in text or "p1" in text or "p2" in text or "p3" in text or "severity" in text:
        return EvidenceDomain.SUPPORT_SLA
    if "bulk upload" in text or "plan" in text:
        return EvidenceDomain.PLAN_ENTITLEMENT
    if "known issue" in text or "ki-" in text or "webhook" in text:
        return EvidenceDomain.KNOWN_ISSUE
    if "shipment status" in text or "booked" in text or "picked_up" in text:
        return EvidenceDomain.SHIPMENT_STATUS
    return EvidenceDomain.GENERAL

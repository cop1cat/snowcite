"""Shared typed vocabulary — literals + TypedDicts used across the codebase.

Kept backend/free of runtime code so any module can import from here without
creating cycles.
"""

from typing import Any, Literal, TypedDict


# ─── Literal aliases ────────────────────────────────────────────────────────

type Status = Literal["approved", "maybe", "rejected", "unreviewed"]
type Source = Literal["arxiv", "semantic_scholar", "openalex", "crossref", "pubmed"]
type Direction = Literal["references", "citations"]
# `auto_high` = Claude confident (direct criterion match); `auto_low` = extrapolation
# the user should sanity-check; `user` = user decided.
type ReviewedBy = Literal["auto_high", "auto_low", "user"]
type Confidence = Literal["high", "low"]
type Backend = Literal["latex", "typst"]
type Severity = Literal["ok", "warn", "error"]
type Phase = Literal[
    "not_started",
    "criteria_set",
    "reviewing",
    "snowballing",
    "outline_proposed",
    "outline_approved",
    "skeleton_approved",
    "writing",
    "polishing",
    "done",
]
type ArtifactType = Literal["interview", "code", "document", "note", "dataset"]
# Knowledge-graph note types. Per-paper extraction during review yields the
# first four; cross-paper synthesis (Phase 2) yields the last four.
type NoteType = Literal[
    "claim",
    "finding",
    "method",
    "limitation",
    "gap",
    "contradiction",
    "consensus",
    "open_question",
]
type NoteLinkKind = Literal["supports", "contradicts", "extends", "derived_from"]
# Per-paper types must carry paper_id; cross-paper types must leave it NULL.
PER_PAPER_NOTE_TYPES: frozenset[str] = frozenset({"claim", "finding", "method", "limitation"})
CROSS_PAPER_NOTE_TYPES: frozenset[str] = frozenset(
    {"gap", "contradiction", "consensus", "open_question"}
)


# ─── TypedDicts for DB-shaped data ──────────────────────────────────────────


class PaperRecord(TypedDict, total=False):
    """Paper row + joined review columns, returned by queries after
    `paper_row_to_dict`. Fields are optional because selectors differ per query."""

    id: int
    source: Source
    source_id: str
    doi: str | None
    title: str
    title_normalized: str
    authors: list[str]
    year: int | None
    venue: str | None
    abstract: str | None
    pdf_url: str | None
    bibtex: str | None
    metadata: dict[str, Any]
    created_at: str
    # Joined review columns:
    review_status: Status
    review_reason: str | None
    review_note: str | None
    reviewed_by: ReviewedBy | None
    reviewed_at: str | None
    # Alt key used by get_low_confidence_reviews where status is aliased without prefix:
    status: Status
    reason: str | None


class OutlineSection(TypedDict, total=False):
    """One entry inside the outline's sections_json array."""

    name: str
    target_words: int
    paper_ids: list[int]
    artifact_ids: list[int]


class ArtifactRecord(TypedDict, total=False):
    """A user-supplied research artifact: interview, code, note, document, dataset."""

    id: int
    type: ArtifactType
    label: str
    source_path: str | None
    content: str
    summary: str | None
    metadata: dict[str, Any]
    included: bool
    created_at: str


class SkeletonSection(TypedDict):
    """One entry inside the skeleton's sections_json array."""

    name: str
    draft: str


class DriftWarning(TypedDict):
    severity: Literal["warn", "high"]
    kind: Literal["no_outline", "unknown_section", "word_count"]
    detail: str

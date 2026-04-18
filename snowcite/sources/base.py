from pydantic import BaseModel, Field, field_validator

from snowcite.dedup import normalize_doi
from snowcite.types import Source


class Paper(BaseModel):
    """Common paper representation across all sources."""

    source: Source
    source_id: str = Field(min_length=1)
    doi: str | None = None
    title: str = Field(min_length=1)
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    abstract: str | None = None
    pdf_url: str | None = None
    bibtex: str | None = None
    metadata: dict = Field(default_factory=dict)

    @field_validator("doi", mode="before")
    @classmethod
    def _normalize_doi(cls, v: str | None) -> str | None:
        return normalize_doi(v)

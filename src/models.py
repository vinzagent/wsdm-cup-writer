"""Data shapes for the WSDM Cup note writer (vinzagent).

Fresh implementation. The field names mirror the X Community Notes API
contract (endpoints / payloads documented in ../RULES.md); nothing here
is copied from any starter code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


# Misleading-tag vocabulary from the Community Notes API. One note must
# carry at least one of these.
class Tag:
    FACTUAL_ERROR = "factual_error"
    MANIPULATED_MEDIA = "manipulated_media"
    OUTDATED_INFORMATION = "outdated_information"
    MISSING_IMPORTANT_CONTEXT = "missing_important_context"
    DISPUTED_CLAIM_AS_FACT = "disputed_claim_as_fact"
    MISINTERPRETED_SATIRE = "misinterpreted_satire"
    OTHER = "other"

    ALL = (
        FACTUAL_ERROR,
        MANIPULATED_MEDIA,
        OUTDATED_INFORMATION,
        MISSING_IMPORTANT_CONTEXT,
        DISPUTED_CLAIM_AS_FACT,
        MISINTERPRETED_SATIRE,
        OTHER,
    )


@dataclass
class Media:
    media_key: str
    media_type: str
    url: Optional[str] = None
    preview_image_url: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    duration_ms: Optional[int] = None


@dataclass
class Post:
    post_id: str
    author_id: str
    created_at: datetime
    text: str
    media: list[Media] = field(default_factory=list)
    possibly_sensitive: bool = False


@dataclass
class PostWithContext:
    """A feed post plus the quoted / replied-to post, if any."""

    post: Post
    quoted_post: Optional[Post] = None
    in_reply_to_post: Optional[Post] = None
    # Un-vetted user input from people who requested a note. Useful as a
    # ranking signal, never treated as fact.
    note_request_suggestions: list[dict] = field(default_factory=list)
    suggested_source_links: list[dict] = field(default_factory=list)

    @property
    def request_count(self) -> int:
        return len(self.note_request_suggestions)

    @property
    def suggested_link_count(self) -> int:
        return len(self.suggested_source_links)

    def describe_for_prompt(self) -> str:
        """Plain-text rendering of the post + context for the researcher."""
        parts = [
            f"Post ID: {self.post.post_id}",
            "Post text:",
            "```",
            self.post.text,
            "```",
        ]
        if self.quoted_post is not None:
            parts += [
                f"The post quoted another post (Post ID: {self.quoted_post.post_id}). "
                "Quoted post text:",
                "```",
                self.quoted_post.text,
                "```",
            ]
        if self.in_reply_to_post is not None:
            parts += [
                f"The post was a reply to another post (Post ID: {self.in_reply_to_post.post_id}). "
                "Replied-to post text:",
                "```",
                self.in_reply_to_post.text,
                "```",
            ]
        return "\n".join(parts)


@dataclass
class Note:
    post_id: str
    text: str
    misleading_tags: list[str]
    trustworthy_sources: bool = True


@dataclass
class Outcome:
    """Result of processing one feed post."""

    post_id: str
    decision: str  # WRITE NOTE | NO NOTE NEEDED | NOT ENOUGH EVIDENCE | SKIPPED | ERROR
    note: Optional[Note] = None
    reason: str = ""
    note_id: Optional[str] = None
    submitted: bool = False

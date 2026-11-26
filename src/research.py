"""Research one post and draft a Community Note with Grok.

One xAI Responses API call per post, with the `web_search` and `x_search`
tools (including image/video understanding). The model looks the post up
by ID — including any images or video and any quoted / replied-to post —
researches the claims, and answers with strict JSON:

  decision: "WRITE NOTE" | "NO NOTE NEEDED" | "NOT ENOUGH EVIDENCE"
  note_text: the proposed note ("" unless WRITE NOTE)
  misleading_tags: at least one tag when WRITE NOTE, else []

The prompt is written for the admission bar: a note must address the
post's claims without opinion or speculation (ClaimOpinion), cite
trustworthy sources both sides would accept, and stay short.
"""

from __future__ import annotations

import json
import os

import requests

from models import Note, Outcome, PostWithContext, Tag

DECISION_WRITE = "WRITE NOTE"
DECISION_NO_NOTE = "NO NOTE NEEDED"
DECISION_NO_EVIDENCE = "NOT ENOUGH EVIDENCE"

_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {
            "type": "string",
            "enum": [DECISION_WRITE, DECISION_NO_NOTE, DECISION_NO_EVIDENCE],
        },
        "note_text": {"type": "string"},
        "misleading_tags": {
            "type": "array",
            "items": {"type": "string", "enum": list(Tag.ALL)},
        },
    },
    "required": ["decision", "note_text", "misleading_tags"],
    "additionalProperties": False,
}


def _prompt(post_description: str) -> str:
    return f"""Below is a post on X. Research it using web search and X search to determine whether it is potentially misleading. Look the post up by its Post ID, including any images or video in it, and any quoted or replied-to post by its Post ID.

If the post is misleading and needs a community note, your decision is "{DECISION_WRITE}" and note_text is the proposed community note itself. If the post is not misleading, or contains no concrete fact-checkable claims, or the evidence is not strong enough for a well-supported note, set decision to "{DECISION_NO_NOTE}" or "{DECISION_NO_EVIDENCE}".

A good community note:
- is concise: at most 280 characters (URLs do not count), no wasted words;
- states one verifiable fact that corrects the post, then cites the URL directly in the text (no "[Source]" labels, no "Community Note:" prefix);
- is backed by solid evidence from sources most likely to be found trustworthy by people on both sides of the political spectrum (official statistics, primary records, reputable reporting);
- contains no opinion, speculation, loaded words, hashtags, or emojis;
- includes at least one URL. Nothing else counts as a source.

If you are not writing a note, set note_text to an empty string and misleading_tags to an empty list. If you are writing a note, choose at least one misleading tag:
- "factual_error": the post contains a factual error
- "manipulated_media": the post contains manipulated, fake, or out-of-context media
- "outdated_information": the post contains outdated information
- "missing_important_context": the post is missing important context
- "disputed_claim_as_fact": including unverified claims presented as fact
- "misinterpreted_satire": the post is satire likely to be misinterpreted as fact
- "other": other misleading reasons

Post:

{post_description}
"""


def _call_llm_json(prompt: str, model: str) -> dict:
    """One xAI Responses API call with search tools, strict JSON output."""
    api_key = os.getenv("XAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "XAI_API_KEY is not set. Copy .env.example to .env and fill it in."
        )
    payload = {
        "model": model,
        "input": [{"role": "user", "content": prompt}],
        "tools": [
            {"type": "web_search", "enable_image_understanding": True},
            {
                "type": "x_search",
                "enable_image_understanding": True,
                "enable_video_understanding": True,
            },
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "note",
                "schema": _RESPONSE_SCHEMA,
                "strict": True,
            }
        },
        "store": False,
    }
    resp = requests.post(
        "https://api.x.ai/v1/responses",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        json=payload,
        timeout=300,
    )
    if resp.status_code != 200:
        raise RuntimeError(
            f"xAI API error {resp.status_code}: {resp.text[:500]}"
        )
    data = resp.json()
    text = data.get("output_text") or "".join(
        block.get("text", "")
        for item in data.get("output", [])
        if item.get("type") == "message"
        for block in item.get("content", [])
        if block.get("type") == "output_text"
    )
    return json.loads(text)


def research_post_and_write_note(
    post_with_context: PostWithContext,
    model: str = "grok-4.3",
) -> Outcome:
    """Research one post; return the decision and a drafted note, if any."""
    post_id = post_with_context.post.post_id
    description = post_with_context.describe_for_prompt()
    try:
        answer = _call_llm_json(_prompt(description), model)
    except Exception as exc:  # noqa: BLE001 - surfaced as an ERROR outcome
        return Outcome(post_id=post_id, decision="ERROR", reason=str(exc))

    decision = answer.get("decision", "")
    if decision != DECISION_WRITE:
        return Outcome(
            post_id=post_id,
            decision=decision or "ERROR",
            reason="Model declined to write a note.",
        )
    tags = [t for t in answer.get("misleading_tags", []) if t in Tag.ALL]
    if not tags:
        return Outcome(
            post_id=post_id,
            decision="ERROR",
            reason="Model wrote a note but chose no valid misleading tag.",
        )
    return Outcome(
        post_id=post_id,
        decision=DECISION_WRITE,
        note=Note(
            post_id=post_id,
            text=(answer.get("note_text") or "").strip(),
            misleading_tags=tags,
        ),
    )

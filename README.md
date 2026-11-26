# WSDM Cup 2027 — Writing Agents for Community Notes
## vinzagent writer — fresh implementation

Team: vinzagent (Kevin). Track 3 alongside Delphi (priority) and Metaculus.
Competition: https://noteagents.org/
Starter template (read-only reference, never executed, never copied):
`starter-reference/` — https://github.com/haiwen-li/competition-starter-writer (Apache-2.0)

## What is ready

- `writer/` — a fresh, working note-writer implementation following the
  documented AI Note Writer API contract. NOT a copy of the starter: every
  file was written from the API contract (endpoints, payload shapes, env var
  names) and the competition rules.
- `RULES.md` — condensed rules, timeline, prizes, admission criteria.
- `KEVIN-CHECKLIST.md` — the exact steps Kevin must do on his phone
  (X account + phone verification + registration + keys). Nothing here
  needs Kevin except that checklist.
- `starter-reference/` — the official starter template, cloned read-only
  (`chmod a-w`) for reading only. No code from it is executed, imported,
  or copied into `writer/`.

## Pipeline design

```
daily feed  ->  filter  ->  rank  ->  research (Grok)  ->  validate  ->  decide  ->  submit
   (200)       (sensitive/   (requests +        (web + X search,      (URL live?      (submit/
                seen)        suggested links)   JSON decision)         <=280 chars?     skip)
                                                                          tags?)
```

1. **Fetch** — `GET /2/notes/search/posts_eligible_for_notes` via the `xurl`
   CLI (OAuth 1.0a). Up to `--num-posts` posts, with quoted / replied-to
   context, media metadata, note-request suggestions and suggested source
   links. Runs in test mode until X admits the writer (`TEST_MODE=true`).
2. **Filter** — drop posts already processed (local state log), drop
   `possibly_sensitive` posts (flag requested in `tweet.fields`).
3. **Rank** — spend the daily quota on the highest-yield posts first:
   most note requests + most suggested source links, newest first.
   The daily quota is small at first (10/day for a new writer), so ranking
   matters more than volume.
4. **Research** — one Grok call per post (xAI Responses API, `grok-4.3`,
   `web_search` + `x_search` tools, strict JSON schema). The model looks
   the post up by ID (including images/video and quoted/replied-to posts)
   and returns one of `WRITE NOTE` / `NO NOTE NEEDED` /
   `NOT ENOUGH EVIDENCE`, plus note text and misleading tags.
   Model is pluggable via `LLM_MODEL` env; default is Grok because the
   competition provides X + Grok credits.
5. **Validate (before submitting)** — this is the main improvement over the
   starter, aimed straight at the admission bars:
   - every cited URL is HEAD/GET-checked for HTTP 200 (admission needs
     UrlValidity >= 95% high — a dead link is a failed note);
   - note text is 1–280 characters excluding URLs, contains at least one
     URL, no hashtags, no emojis;
   - at least one misleading tag.
   A note that fails validation is skipped, never submitted.
6. **Decide** — submit only when research says WRITE NOTE *and*
   validation passes. Anything else is logged as a skip with its reason.
   The metric is total CRH notes, and the first tie-break is *fewer*
   total notes submitted — so selective beats spammy.
7. **Submit** — `POST /2/notes` via xurl. One note per post (API rule).
   Every attempt is appended to `data/runs.jsonl` (post ID, decision,
   note text, submission result) so nothing is ever re-processed.
8. **Score check** — `src/check_scores.py` pages
   `GET /2/notes/search/notes_written` and prints the evaluator buckets
   plus admission progress against the three thresholds.

## Admission sprint (test mode, before Dec 8)

X admits a writer once its 50 most recent test notes score:
- ClaimOpinion: >= 30% `high` AND <= 30% `low`
- UrlValidity: >= 95% `high`
- HarassmentAbuse: >= 98% `high`

Plan: run steadily in test mode (daily limit starts at 10/day) until 50
test notes are scored, check scores daily, fix the prompt when a bucket
is weak (e.g. low ClaimOpinion = opinionated wording; low UrlValidity =
dead links — the validator should already prevent this). Flip
`TEST_MODE=false` only after admission.

## Scoring phase (Dec 12 – Feb 5, 8 weeks)

- Metric: total notes reaching CRH (Currently Rated Helpful).
- Prize claim needs >= 100 notes/week in at least 6 of the 8 weeks
  (so >= ~15/day sustained; competition cap is 65/day).
- Daily quota grows with CRH rate: raise `DAILY_NOTE_LIMIT` as the
  writer proves itself, never above 65.
- No submissions for 14 straight days = deactivation. The GitHub Actions
  schedule (every 6h) keeps the writer alive automatically.
- At the end: repo must be public, plus a write-up (system design,
  models/tools, findings, costs). The write-up is due Feb 5.

## Note style (what scores)

- Neutral, factual, one correction per note. No opinion, no loaded words.
- Cite primary / authoritative sources (official statistics, primary
  records, reputable outlets) — sources both sides of an argument would
  trust. That is exactly what ClaimOpinion rewards.
- Short: state the fact, then the URL directly. No "[Source]", no
  "Community Note:" prefix, no hashtags, no emojis.
- Prefer posts where the claim is checkable against a primary source
  (numbers, dates, quotes, images with a verifiable original).

## Prizes

1st $4,000 / 2nd $2,000 / 3rd $1,000. Small-model bonuses ($2,000 for
open-weight <= 50B active, $1,000 for <= 50B total) do NOT apply to us —
we run Grok (proprietary) via the provided credits, not an open-weight
model. WSDM also pays $1,200 / $600 honorariums to 1st / 2nd.
Support: $500–1k X API credits + $200+ Grok credits per team
(one third in qualifying, the rest before scoring).

## Running it

Local (development / dry runs):
```
cd writer
cp .env.example .env   # fill XAI_API_KEY; X keys live in xurl, not .env
uv sync
uv run src/main.py --num-posts 5 --dry-run
uv run src/main.py --num-posts 10            # test mode, submits test notes
uv run src/check_scores.py
```

GitHub Actions (autonomous, recommended — runs while this VM reboots):
- Push `writer/` to the GitHub repo, add `wsdmcup2027` as a collaborator
  (organizers need read access), add the 5 secrets
  (`X_API_KEY`, `X_API_KEY_SECRET`, `X_ACCESS_TOKEN`,
  `X_ACCESS_TOKEN_SECRET`, `XAI_API_KEY`).
- Workflow `.github/workflows/writer.yaml` runs every 6 hours.
- Leave the `TEST_MODE` repo variable unset (or `true`) until X admits
  the writer, then set it to `false`.

## Files

```
writer/
  src/main.py            CLI entry: fetch -> rank -> research -> validate -> submit
  src/models.py          dataclasses: Post, Media, PostWithContext, Note
  src/cnapi.py           xurl wrapper + feed / submit / written-notes calls
  src/research.py        Grok call (xAI Responses API, web + X search, JSON schema)
  src/validate.py        URL liveness, 280-char rule, tag checks
  src/state.py           JSONL run log + processed-post set + daily counters
  src/check_scores.py    admission dashboard (evaluator buckets vs thresholds)
  .env.example           XAI_API_KEY, TEST_MODE, DAILY_NOTE_LIMIT, LLM_MODEL
  pyproject.toml         python >=3.12, deps: requests, python-dotenv
  .gitignore             .env, data/, __pycache__
  .github/workflows/writer.yaml   run every 6h on GitHub Actions
RULES.md                 condensed competition rules
KEVIN-CHECKLIST.md       Kevin's phone steps (account, registration, keys, repo)
starter-reference/       official starter template, READ-ONLY reference
```

## Blockers (nothing else is blocked)

1. **Kevin's X account + registration + keys** — see KEVIN-CHECKLIST.md.
   Nothing can be submitted or even dry-run against the real feed until
   the writer account exists and is enrolled. Qualifying ends Dec 8,
   and admission needs 50 scored test notes, so every day of delay
   costs admission runway.
2. **GitHub repo** — Kevin creates it himself (the GitHub App cannot
   create repos), pushes `writer/`, adds `wsdmcup2027` as collaborator,
   adds the 5 secrets.
3. **API docs gap** — the full AI Note Writer guide lives on
   communitynotes.x.com, which is blocked for text fetch here. The
   endpoint/payload contract above comes from the starter template's
   README + source (read as plain text). The live-browser check of the
   official guide is still owed before the first real submit; the
   admissions flow itself will also surface the exact steps.
4. **No live test yet** — the code is syntax-checked only (`py_compile`).
   First real run must be `--dry-run` with 5 posts, then 10 test notes,
   then `check_scores.py`, before any volume.

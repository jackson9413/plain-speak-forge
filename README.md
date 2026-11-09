# Plain-Speak Forge

**A local-first plain-language and readability workbench.**
Paste a document. Find out whether a real person can actually read it — and what to change first.

No API keys. No network calls. No LLM. Your text never leaves your machine.

---

## The problem

Most writing advice is "make it clearer", which is useless advice. Every document has a
specific, findable set of reasons why a reader struggles: three sentences over 25 words,
a paragraph with no heading above it, a term used nine times that the reader has to guess,
an acronym that was never spelled out, a passive sentence that hides who did what.

Plain-Speak Forge finds those reasons, scores them, and tells you which fix to make first.

## What it does

Paste any document and get back:

- **A 0–100 score across five axes** — readability, jargon, sentence craft, structure,
  inclusive language — with weights that change depending on who is going to read it.
- **Six readability formulas** — Flesch Reading Ease, Flesch-Kincaid Grade, Gunning Fog,
  SMOG, Coleman-Liau and the Automated Readability Index, plus a composite grade.
- **A reading-level verdict** — "reads like a college junior", "your audience needs
  middle school" — and the gap between the two.
- **A jargon table** — every term from a 230-word lexicon across legal, medical, financial,
  business, technical and academic registers, with a plain-language alternative for each.
- **Acronym detection** — acronyms that are never spelled out anywhere in the document.
- **Sentence-craft findings** — long sentences, passive voice, nominalisations, hedge-word
  density, filler phrases, vague phrases and bureaucratic constructions.
- **Structure analysis** — headings, wall-of-text paragraphs, paragraph length, list
  density, skipped heading levels, buried openings.
- **Inclusive-language findings** — gendered, ableist, ageist, colour-only and
  ownership-language terms, each with a replacement.
- **Hardest passages** — the specific sentences most likely to lose a reader, ranked.
- **A paragraph-by-paragraph map** — so you can fix the darkest rows first.
- **A prioritised fix plan** — every finding ranked, with an estimated score gain.
- **A rewrite scaffold** — mechanical before/after rewrites for the sentences that can be
  rewritten safely, plus split points for the long ones.
- **A cleaned draft** — the whole document with the mechanical substitutions applied.
- **Markdown and JSON exports**, a SQLite run log with 1–5 star self-ratings and notes.

## Seven audiences, seven different rubrics

Plain language is not one thing. The same paragraph can be perfect for a developer and
useless to a customer. Pick the audience and the score changes:

| Audience | Target grade | Weights shift toward |
| --- | --- | --- |
| General public | 8 | readability, jargon |
| Consumer notice / policy | 8 | structure (headings matter most) |
| Help / support article | 10 | structure, sentence craft |
| Internal team memo | 12 | sentence craft, inclusive language |
| Technical documentation | 14 | structure, jargon, sentence craft |
| Academic / research | 16 | sentence craft, jargon |
| Marketing web page | 9 | readability, inclusive language |

The same document can score 50 for the general public and 80 for a technical audience.
That is the point: you are being scored against a reader, not against a formula.

## How the score works

Five axes, each 0–100, combined with the audience weights.

- **Readability** starts from the Flesch Reading Ease band and loses points for every
  grade the text sits above the audience target.
- **Jargon** starts at 100 and loses points for jargon density, undefined acronyms and
  bureaucratic constructions.
- **Sentence craft** loses points for long sentences, passive voice, nominalisations,
  hedge density, filler density and vague phrases.
- **Structure** loses points for a missing heading structure, walls of text, paragraphs
  over 80 words, a document with no lists and skipped heading levels.
- **Inclusive language** loses points for each flagged term, weighted by severity.

**Structural caps** stop a document scoring well by skipping the hard part:

- Reading more than 3 grades above the target caps the overall score at 74.
- More than 6 grades above target caps it at 65.
- A very low Flesch score combined with a grade gap caps it at 62.
- Jargon density over 8% caps it at 70.
- Any high-severity inclusive-language finding caps it at 68.

Verdict bands: **Plain-language ready** (85+), **Mostly readable** (70+),
**Needs edits** (55+), **Hard to read** (40+), **Needs rework** (below 40).

Every finding carries the evidence that triggered it, why it matters, and a concrete fix.
Nothing is a black box.

## Install and run

Requires Python 3.10+.

    pip install -r requirements.txt
    python3 app.py

Then open <http://127.0.0.1:8756>.

The database is a single SQLite file (plain_speak.sqlite3) created on first run.
Set PORT to use a different port, or PLAIN_SPEAK_DB to point at a different database file.

## Run the tests

    python3 -m unittest discover -s tests

58 tests: 44 engine tests and 14 API tests.

## API

    GET  /api/health
    GET  /api/audiences                  list the audience profiles
    GET  /api/samples                    list the built-in samples
    GET  /api/sample/<key>               fetch one sample document
    POST /api/analyze                    {text, audience, title, save} -> full report
    GET  /api/sessions                   recent runs
    GET  /api/sessions/<id>              one run with its full payload
    PATCH /api/sessions/<id>             {self_rating, notes}
    GET  /api/export/<id>?fmt=md|json    download the report

Example:

    curl -s -X POST http://127.0.0.1:8756/api/analyze       -H 'Content-Type: application/json'       -d '{"text":"...","audience":"consumer_notice","title":"Policy update"}'

## Built-in samples

Seven documents, calibrated so the engine behaves sensibly across the range:

| Sample | Audience | Expected result |
| --- | --- | --- |
| insurance_notice | consumer_notice | ~47 — hard to read |
| launch_email | marketing_web | ~50 — hype and vague claims |
| medical_instructions | general_public | ~68 — needs edits |
| api_error_guide | technical_docs | ~70 — mostly readable |
| incident_postmortem | internal_team | ~80 — mostly readable |
| refund_policy | consumer_notice | ~95 — plain-language ready |
| password_reset | support_article | ~98 — the control case |

## Project layout

    app.py             Flask app and REST API
    engine.py          the analysis engine (standard library only)
    lexicon.py         all the word lists, as data
    db.py              SQLite run log
    static/            the dark vanilla-JS front end
    samples/           seven calibration documents plus a manifest
    tests/             58 unit and API tests

## Tech stack

- **Backend:** Python 3 + Flask
- **Analysis:** a hand-written standard-library engine — no pandas, no NLTK, no spaCy,
  no external model. Syllable counting, sentence segmentation, six readability formulas,
  passive-voice and nominalisation detection and the rewrite engine are all implemented here.
- **Storage:** SQLite
- **Frontend:** vanilla HTML/CSS/JavaScript, no build step, no framework, no CDN

## Design notes

**Sentence splitting** respects abbreviations (Dr., e.g., U.S.) and decimals, so
"Dr. Smith paid 3.50 dollars." stays one sentence.

**Syllable counting** uses vowel-group counting with silent-e and -es adjustments and a
-le exception, which is accurate enough to keep the readability formulas honest.

**The cleaned draft is mechanical on purpose.** It swaps jargon, bureaucratic phrases,
vague phrases, filler and flagged inclusive terms for their plain equivalents, and fixes
a/an agreement. It does not rewrite your argument. The label on the tab says so, because
a tool that silently rewrites meaning is a tool that lies.

**Code blocks are never rewritten** and never counted as prose.

## License

MIT

"""Plain-language and readability analysis engine.

Standard library only: no network calls, no LLM, no API keys.
"""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict

from lexicon import (
    ACRONYM_WHITELIST,
    BE_FORMS,
    BUREAU,
    FILLER,
    HEDGES,
    INCLUSIVE,
    IRREGULAR_PARTICIPLES,
    JARGON,
    LEVEL_BANDS,
    NOMINALIZATIONS,
    VAGUE,
)

# ---------------------------------------------------------------------------
# Audience profiles
# ---------------------------------------------------------------------------

AUD_PROFILES = {
    "general_public": {
        "label": "General public",
        "blurb": "A reader with no background in the subject. News, community notices, public-facing pages.",
        "target_grade": 8,
        "weights": {"readability": 0.30, "jargon": 0.25, "sentence_craft": 0.20, "structure": 0.15, "inclusivity": 0.10},
    },
    "consumer_notice": {
        "label": "Consumer notice / policy",
        "blurb": "Terms, policy updates, insurance and billing notices that a customer must understand.",
        "target_grade": 8,
        "weights": {"readability": 0.28, "jargon": 0.24, "sentence_craft": 0.16, "structure": 0.22, "inclusivity": 0.10},
    },
    "support_article": {
        "label": "Help / support article",
        "blurb": "How-to guides and troubleshooting steps that a stuck user will read mid-problem.",
        "target_grade": 10,
        "weights": {"readability": 0.24, "jargon": 0.20, "sentence_craft": 0.20, "structure": 0.26, "inclusivity": 0.10},
    },
    "internal_team": {
        "label": "Internal team memo",
        "blurb": "Updates, handovers and announcements read by colleagues who know the context.",
        "target_grade": 12,
        "weights": {"readability": 0.18, "jargon": 0.18, "sentence_craft": 0.22, "structure": 0.22, "inclusivity": 0.20},
    },
    "technical_docs": {
        "label": "Technical documentation",
        "blurb": "READMEs, API references and runbooks read by engineers who know the domain.",
        "target_grade": 14,
        "weights": {"readability": 0.15, "jargon": 0.20, "sentence_craft": 0.22, "structure": 0.25, "inclusivity": 0.18},
    },
    "academic": {
        "label": "Academic / research",
        "blurb": "Papers, literature reviews and methods sections for a specialist audience.",
        "target_grade": 16,
        "weights": {"readability": 0.12, "jargon": 0.22, "sentence_craft": 0.28, "structure": 0.18, "inclusivity": 0.20},
    },
    "marketing_web": {
        "label": "Marketing web page",
        "blurb": "Landing pages, emails and product copy where the reader skims before they commit.",
        "target_grade": 9,
        "weights": {"readability": 0.28, "jargon": 0.18, "sentence_craft": 0.18, "structure": 0.16, "inclusivity": 0.20},
    },
}

AXIS_LABELS = {
    "readability": "Readability",
    "jargon": "Jargon",
    "sentence_craft": "Sentence craft",
    "structure": "Structure",
    "inclusivity": "Inclusive language",
}

AXIS_ORDER = ["readability", "jargon", "sentence_craft", "structure", "inclusivity"]

SEVERITY_GAIN = {"critical": 7.0, "high": 4.5, "medium": 2.5, "low": 1.2}
SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}

MIN_WORDS = 30


# ---------------------------------------------------------------------------
# Tokenising
# ---------------------------------------------------------------------------

WORD_RE = re.compile(r"[A-Za-z][A-Za-z'\u2019-]*")


def word_list(text):
    return WORD_RE.findall(text)


def count_syllables(word):
    w = re.sub(r"[^a-z]", "", word.lower())
    if not w:
        return 0
    if len(w) <= 3:
        return 1
    vowels = "aeiouy"
    count = 0
    prev_vowel = False
    for ch in w:
        is_vowel = ch in vowels
        if is_vowel and not prev_vowel:
            count += 1
        prev_vowel = is_vowel
    if w.endswith("e") and count > 1 and not w.endswith(("le", "ee", "ye")):
        count -= 1
    if w.endswith("es") and count > 1 and not w.endswith(
        ("aes", "ees", "oes", "ses", "xes", "zes", "ches", "shes")
    ):
        count -= 1
    return max(1, count)


def is_complex(word):
    w = re.sub(r"[^a-z]", "", word.lower())
    if not w:
        return False
    if len(w) > 4 and w.endswith(("es", "ed", "ing")):
        base = re.sub(r"(es|ed|ing)$", "", w)
        if base and count_syllables(base) >= 3:
            return True
    return count_syllables(w) >= 3


ABBREV = {
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "vs", "etc", "eg",
    "ie", "inc", "ltd", "co", "corp", "no", "fig", "approx", "dept", "est",
    "us", "uk", "am", "pm", "phd", "bc", "ad", "vol", "art", "para", "cf",
    "al", "viz", "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep",
    "sept", "oct", "nov", "dec", "mon", "tue", "tues", "wed", "thu", "thur",
    "thurs", "fri", "sat", "sun", "gen", "rev", "hon", "sgt", "capt",
    "univ", "dept", "assn", "bros", "inc",
}


CLOSERS = set(chr(34) + chr(39) + ')]}' + chr(8221) + chr(8217))


def split_sentences(text):
    """Split prose into sentences, respecting common abbreviations."""
    out = []
    start = 0
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch in ".!?":
            j = i + 1
            while j < n and text[j] in CLOSERS:
                j += 1
            if ch == ".":
                prev = re.search(r"([A-Za-z][A-Za-z\.]*)$", text[start:i])
                token = prev.group(1).lower() if prev else ""
                bare = token.rstrip(".")
                if bare in ABBREV or (len(bare) == 1 and bare.isalpha()):
                    i = j
                    continue
                if i > 0 and text[i - 1].isdigit() and j < n and text[j].isdigit():
                    i = j
                    continue
            k = j
            while k < n and text[k] in " \t":
                k += 1
            if k < n and (text[k].isalpha() or text[k] in "\"'\u201c\u2018("):
                piece = text[start:j].strip()
                if piece:
                    out.append(piece)
                start = k
                i = k
                continue
            i = j
            continue
        i += 1
    tail = text[start:].strip()
    if tail:
        out.append(tail)
    return out


def parse_blocks(text):
    """Split a document into headings, paragraphs, list items, quotes and code."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks = []
    buf = []
    in_code = False

    def flush():
        nonlocal buf
        if buf:
            blocks.append({"kind": "paragraph", "level": 0, "text": " ".join(buf).strip()})
            buf = []

    i = 0
    n = len(lines)
    while i < n:
        raw = lines[i]
        s = raw.strip()
        if s.startswith("```"):
            flush()
            in_code = not in_code
            i += 1
            continue
        if in_code:
            blocks.append({"kind": "code", "level": 0, "text": raw})
            i += 1
            continue
        if not s:
            flush()
            i += 1
            continue
        if re.fullmatch(r"[=\-]{3,}", s) and buf:
            level = 1 if s[0] == "=" else 2
            heading_text = " ".join(buf).strip()
            buf = []
            blocks.append({"kind": "heading", "level": level, "text": heading_text})
            i += 1
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", s)
        if m:
            flush()
            blocks.append({"kind": "heading", "level": len(m.group(1)), "text": m.group(2).strip()})
            i += 1
            continue
        if re.match(r"^([-*+]|\d+[.)])\s+", s):
            flush()
            clean = re.sub(r"^([-*+]|\d+[.)])\s+", "", s)
            blocks.append({"kind": "list_item", "level": 0, "text": clean})
            i += 1
            continue
        if s.startswith(">"):
            flush()
            blocks.append({"kind": "quote", "level": 0, "text": s.lstrip("> ").strip()})
            i += 1
            continue
        letters = [c for c in s if c.isalpha()]
        if (
            len(letters) > 2
            and s == s.upper()
            and len(s.split()) <= 8
            and not s.endswith((".", ",", ";"))
        ):
            flush()
            blocks.append({"kind": "heading", "level": 2, "text": s})
            i += 1
            continue
        buf.append(s)
        i += 1
    flush()
    return blocks


# ---------------------------------------------------------------------------
# Lexicon matching
# ---------------------------------------------------------------------------


def _norm_key(text):
    return re.sub(r"[\s\-/]+", " ", text.strip().lower())


def _term_pattern(term):
    toks = [t for t in re.split(r"[\s\-/]+", term) if t]
    parts = [re.escape(t) for t in toks]
    body = r"[\s\-/]+".join(parts)
    if len(toks) == 1 and not term.endswith("s"):
        body = body + r"s?"
    return r"(?<![A-Za-z0-9])" + body + r"(?![A-Za-z0-9])"


def _compile_terms(terms):
    ordered = sorted(terms, key=lambda t: (-len(t), t))
    return re.compile("|".join(_term_pattern(t) for t in ordered), re.IGNORECASE)


def _lookup(terms):
    table = {}
    for term, value in terms.items():
        table[_norm_key(term)] = value
        if " " not in term and not term.endswith("s"):
            table[_norm_key(term) + "s"] = value
    return table


JARGON_RE = _compile_terms(JARGON.keys())
JARGON_LOOKUP = _lookup(JARGON)
BUREAU_RE = _compile_terms(BUREAU.keys())
BUREAU_LOOKUP = _lookup(BUREAU)
VAGUE_RE = _compile_terms(VAGUE.keys())
VAGUE_LOOKUP = _lookup(VAGUE)
FILLER_RE = _compile_terms(FILLER.keys())
FILLER_LOOKUP = _lookup(FILLER)
INCLUSIVE_RE = _compile_terms(INCLUSIVE.keys())
INCLUSIVE_LOOKUP = _lookup(INCLUSIVE)

ACRONYM_RE = re.compile(r"(?<![A-Za-z0-9])([A-Z]{2,6})(?![A-Za-z0-9])")
HEDGE_RE = _compile_terms(HEDGES)


def _match_case(original, replacement):
    if not replacement:
        return replacement
    if original[:1].isupper() and not original.isupper():
        return replacement[:1].upper() + replacement[1:]
    return replacement


def _find_matches(text, pattern, lookup):
    out = []
    for m in pattern.finditer(text):
        key = _norm_key(m.group(0))
        value = lookup.get(key)
        if value is None:
            continue
        out.append((m.start(), m.end(), m.group(0), value))
    return out


# ---------------------------------------------------------------------------
# Readability
# ---------------------------------------------------------------------------


def compute_readability(sentences):
    total_words = 0
    total_syllables = 0
    total_letters = 0
    complex_words = 0
    per_sentence = []
    for idx, sent in enumerate(sentences):
        ws = word_list(sent)
        syl = sum(count_syllables(w) for w in ws)
        letters = sum(len(w) for w in ws)
        cx = sum(1 for w in ws if is_complex(w))
        per_sentence.append(
            {
                "index": idx,
                "text": sent,
                "words": len(ws),
                "syllables": syl,
                "complex": cx,
                "letters": letters,
            }
        )
        total_words += len(ws)
        total_syllables += syl
        total_letters += letters
        complex_words += cx

    ns = max(1, len(sentences))
    words = max(1, total_words)
    wps = total_words / ns
    spw = total_syllables / words
    letters_per_word = total_letters / words

    fre = max(0.0, 206.835 - 1.015 * wps - 84.6 * spw)
    fk = 0.39 * wps + 11.8 * spw - 15.59
    fog = 0.4 * (wps + 100 * (complex_words / words))
    smog = (1.0430 * math.sqrt(complex_words * (30 / ns)) + 3.1291) if complex_words else 0.0
    l_per_100 = (total_letters / words) * 100
    s_per_100 = (ns / words) * 100
    cli = 0.0588 * l_per_100 - 0.296 * s_per_100 - 15.8
    ari = 4.71 * letters_per_word + 0.5 * wps - 21.43

    parts = [(fk, 0.30), (fog, 0.25), (cli, 0.20), (ari, 0.15)]
    if smog:
        parts.append((smog, 0.10))
    weight_total = sum(w for _, w in parts)
    composite = sum(v * w for v, w in parts) / weight_total
    composite = max(0.0, composite)

    return {
        "metrics": {
            "flesch_reading_ease": round(fre, 1),
            "flesch_kincaid_grade": round(max(0.0, fk), 1),
            "gunning_fog": round(max(0.0, fog), 1),
            "smog": round(smog, 1),
            "coleman_liau": round(max(0.0, cli), 1),
            "automated_readability_index": round(max(0.0, ari), 1),
            "composite_grade": round(composite, 1),
        },
        "totals": {
            "words": total_words,
            "sentences": len(sentences),
            "syllables": total_syllables,
            "complex_words": complex_words,
            "avg_sentence_words": round(wps, 1),
            "avg_syllables_per_word": round(spw, 2),
            "avg_words_per_sentence": round(wps, 1),
        },
        "per_sentence": per_sentence,
    }


def level_band(grade):
    label = "Graduate school"
    for cutoff, name in LEVEL_BANDS:
        if grade <= cutoff:
            label = name
            break
    return label


# ---------------------------------------------------------------------------
# Sentence craft
# ---------------------------------------------------------------------------

PASSIVE_RE = re.compile(
    r"\b(am|is|are|was|were|be|been|being|get|gets|got|gotten)\b(?:\s+\w+ly)?\s+([A-Za-z]+(?:ed|en))\b",
    re.IGNORECASE,
)

ED_BLACKLIST = {
    "red", "bed", "hundred", "sacred", "speed", "need", "seed", "breed",
    "shred", "embed", "exceed", "proceed", "succeed", "greed", "deed",
    "tweed", "weed", "feed", "bleed", "indeed", "aged", "wicked", "naked",
    "sacred", "hatched", "matched", "blessed", "beloved", "learned",
}


def find_passives(sentence):
    out = []
    for m in PASSIVE_RE.finditer(sentence):
        part = m.group(2).lower()
        if part in IRREGULAR_PARTICIPLES:
            out.append((m.start(), m.group(0)))
        elif part.endswith("ed") and part not in ED_BLACKLIST and len(part) > 4:
            out.append((m.start(), m.group(0)))
    return out


def find_nominalizations(sentence):
    out = []
    for m in re.finditer(r"\b[A-Za-z]+\b", sentence):
        w = m.group(0).lower()
        if w in NOMINALIZATIONS:
            out.append((m.start(), m.group(0), NOMINALIZATIONS[w]))
    return out


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------


def analyze_structure(blocks):
    headings = [b for b in blocks if b["kind"] == "heading"]
    paragraphs = [b for b in blocks if b["kind"] == "paragraph"]
    list_items = [b for b in blocks if b["kind"] == "list_item"]
    quotes = [b for b in blocks if b["kind"] == "quote"]
    code = [b for b in blocks if b["kind"] == "code"]

    para_words = [len(word_list(p["text"])) for p in paragraphs]
    list_words = [len(word_list(p["text"])) for p in list_items]
    total_words = sum(para_words) + sum(list_words) + sum(
        len(word_list(q["text"])) for q in quotes
    )

    walls = [i + 1 for i, w in enumerate(para_words) if w > 120]
    long_paras = [i + 1 for i, w in enumerate(para_words) if 80 < w <= 120]

    issues = []
    if total_words > 120 and not headings:
        issues.append(
            {
                "code": "no_headings",
                "detail": "%d words with no headings to scan" % total_words,
                "fix": "Break the text into 3-6 headed sections. Readers scan for headings before they read.",
            }
        )
    if walls:
        issues.append(
            {
                "code": "wall_of_text",
                "detail": "paragraph(s) %s run over 120 words" % ", ".join(map(str, walls)),
                "fix": "Split each long paragraph into one idea per paragraph, or turn steps into a numbered list.",
            }
        )
    if long_paras:
        issues.append(
            {
                "code": "long_paragraphs",
                "detail": "paragraph(s) %s run 80-120 words" % ", ".join(map(str, long_paras)),
                "fix": "Aim for paragraphs under 80 words. Move detail into a list if it is step-shaped.",
            }
        )
    if total_words > 200 and not list_items:
        issues.append(
            {
                "code": "no_lists",
                "detail": "%d words and not a single list" % total_words,
                "fix": "Anything step-shaped, enumerable or parallel belongs in a list.",
            }
        )
    levels = [h["level"] for h in headings]
    skips = []
    for prev, cur in zip(levels, levels[1:]):
        if cur - prev > 1:
            skips.append("h%d to h%d" % (prev, cur))
    if skips:
        issues.append(
            {
                "code": "heading_depth_skip",
                "detail": "heading levels jump: %s" % ", ".join(skips),
                "fix": "Do not skip heading levels. Use h2 under h1, h3 under h2.",
            }
        )
    if headings and len(headings) > 2 and len(set(levels)) == 1:
        issues.append(
            {
                "code": "flat_headings",
                "detail": "every heading is at the same level",
                "fix": "Use nesting so the structure shows which section belongs to which.",
            }
        )
    if para_words and para_words[0] > 60:
        issues.append(
            {
                "code": "buried_opening",
                "detail": "the first paragraph is %d words" % para_words[0],
                "fix": "Open with what the reader needs to know or do, in two sentences.",
            }
        )

    return {
        "headings": [{"level": h["level"], "text": h["text"]} for h in headings],
        "paragraph_count": len(paragraphs),
        "list_item_count": len(list_items),
        "quote_count": len(quotes),
        "code_block_count": code and len(code) or 0,
        "total_words": total_words,
        "avg_paragraph_words": round(sum(para_words) / len(para_words), 1) if para_words else 0,
        "max_paragraph_words": max(para_words) if para_words else 0,
        "bullet_ratio": round(
            (sum(list_words) / (sum(para_words) + sum(list_words))), 3
        )
        if (sum(para_words) + sum(list_words))
        else 0.0,
        "issues": issues,
    }


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def detect_jargon(sentences):
    per_term = {}
    per_sentence = []
    for idx, sent in enumerate(sentences):
        hits = []
        for start, end, matched, value in _find_matches(sent, JARGON_RE, JARGON_LOOKUP):
            key = _norm_key(matched)
            entry = per_term.setdefault(
                key,
                {
                    "term": key,
                    "category": value[0],
                    "plain": value[1],
                    "count": 0,
                    "first_sentence": idx,
                    "example": sent,
                },
            )
            entry["count"] += 1
            hits.append({"term": key, "category": value[0], "plain": value[1], "offset": start})
        if hits:
            per_sentence.append({"index": idx, "text": sent, "hits": hits})
    return sorted(per_term.values(), key=lambda d: (-d["count"], d["term"])), per_sentence


def detect_acronyms(text, prose):
    defined = set()
    for m in re.finditer(
        r"([A-Z][A-Za-z]+(?:[ ]+[A-Za-z][A-Za-z]+){0,5})[ ]*\(\s*([A-Z]{2,6})\s*\)", text
    ):
        defined.add(m.group(2))
    counts = Counter()
    for m in ACRONYM_RE.finditer(prose):
        token = m.group(1)
        if token in ACRONYM_WHITELIST or token in defined:
            continue
        counts[token] += 1
    return [
        {"acronym": a, "count": c, "defined": False}
        for a, c in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]


def detect_inclusive(sentences):
    per_term = {}
    for idx, sent in enumerate(sentences):
        for start, end, matched, value in _find_matches(sent, INCLUSIVE_RE, INCLUSIVE_LOOKUP):
            key = _norm_key(matched)
            entry = per_term.setdefault(
                key,
                {
                    "term": key,
                    "category": value[0],
                    "alternative": value[1],
                    "severity": value[2],
                    "count": 0,
                    "first_sentence": idx,
                    "example": sent,
                },
            )
            entry["count"] += 1
    return sorted(per_term.values(), key=lambda d: (SEVERITY_RANK[d["severity"]], -d["count"]))


def analyze_craft(sentences, total_words):
    long_sentences = []
    very_long = []
    passive_sentences = []
    nominalizations = []
    hedge_hits = []
    filler_hits = []
    vague_hits = []
    bureau_hits = []

    for idx, sent in enumerate(sentences):
        ws = word_list(sent)
        n = len(ws)
        if n > 25:
            long_sentences.append({"index": idx, "text": sent, "words": n})
        if n > 35:
            very_long.append({"index": idx, "text": sent, "words": n})
        if find_passives(sent):
            passive_sentences.append({"index": idx, "text": sent})
        for _s, word, verb in find_nominalizations(sent):
            nominalizations.append({"index": idx, "text": sent, "word": word, "verb": verb})
        for _s, _e, matched, repl in _find_matches(sent, VAGUE_RE, VAGUE_LOOKUP):
            vague_hits.append({"index": idx, "text": sent, "phrase": _norm_key(matched), "replacement": repl})
        for _s, _e, matched, repl in _find_matches(sent, BUREAU_RE, BUREAU_LOOKUP):
            bureau_hits.append({"index": idx, "text": sent, "phrase": _norm_key(matched), "replacement": repl})
        for _s, _e, matched, repl in _find_matches(sent, FILLER_RE, FILLER_LOOKUP):
            filler_hits.append({"index": idx, "text": sent, "phrase": _norm_key(matched), "replacement": repl})

    hedge_total = len(HEDGE_RE.findall(" ".join(sentences))) if sentences else 0

    words = max(1, total_words)
    return {
        "long_sentences": long_sentences,
        "very_long_sentences": very_long,
        "passive_sentences": passive_sentences,
        "nominalizations": nominalizations,
        "nominalization_count": len(nominalizations),
        "vague_hits": vague_hits,
        "bureau_hits": bureau_hits,
        "filler_hits": filler_hits,
        "hedge_count": hedge_total,
        "hedge_density": round(hedge_total / words * 100, 2),
        "filler_count": len(filler_hits),
        "filler_density": round(len(filler_hits) / words * 100, 2),
        "avg_sentence_words": round(
            sum(len(word_list(s)) for s in sentences) / max(1, len(sentences)), 1
        ),
    }


# ---------------------------------------------------------------------------
# Rewriting
# ---------------------------------------------------------------------------


def _sub_jargon(m, subs):
    key = _norm_key(m.group(0))
    value = JARGON_LOOKUP.get(key)
    if not value:
        return m.group(0)
    if value[1].lower() == key:
        return m.group(0)
    subs.append({"kind": "jargon", "from": m.group(0), "to": value[1], "note": value[0]})
    return _match_case(m.group(0), value[1])


def _sub_dict(pattern, lookup, kind, subs, text):
    def inner(m):
        key = _norm_key(m.group(0))
        value = lookup.get(key)
        if not value:
            return m.group(0)
        repl = value
        if kind == "inclusive":
            repl = value[1]
        if repl.lower() == key:
            return m.group(0)
        subs.append({"kind": kind, "from": m.group(0), "to": repl})
        return _match_case(m.group(0), repl)

    return pattern.sub(inner, text)


def apply_replacements(line):
    subs = []
    new = JARGON_RE.sub(lambda m: _sub_jargon(m, subs), line)
    new = _sub_dict(BUREAU_RE, BUREAU_LOOKUP, "bureau", subs, new)
    new = _sub_dict(VAGUE_RE, VAGUE_LOOKUP, "vague", subs, new)
    new = _sub_dict(FILLER_RE, FILLER_LOOKUP, "filler", subs, new)
    new = _sub_dict(INCLUSIVE_RE, INCLUSIVE_LOOKUP, "inclusive", subs, new)
    new = re.sub(r"[ \t]{2,}", " ", new)
    new = re.sub(r" +([,.;:!?])", r"\1", new)
    new = re.sub(r"\(\s*\)", "", new)
    new = re.sub(r"\s+([,.;:])", r"\1", new)
    new = re.sub(r"\s{2,}", " ", new)
    new = re.sub(r"\b(?:a|A|an|An)\s+(an|An)\b", lambda mm: mm.group(1), new)
    new = re.sub(r"\b([Aa])\s+([aeioAEIO])",
                 lambda mm: ("an " if mm.group(1) == "a" else "An ") + mm.group(2), new)
    new = re.sub(r"\b(?:the|a|an)\s+(this|that|these|those)\b", r"\1", new)
    new = re.sub(r"\b(the|a|an)\s+(the|a|an)\b", r"\2", new)
    return new, subs


def clean_text(text):
    out = []
    total = 0
    applied = []
    in_code = False
    for line in text.split("\n"):
        if line.strip().startswith("```"):
            in_code = not in_code
            out.append(line)
            continue
        if in_code:
            out.append(line)
            continue
        new, subs = apply_replacements(line)
        total += len(subs)
        applied.extend(subs)
        out.append(new)
    return "\n".join(out), total, applied


def split_hint(sentence):
    for marker in ["; ", ", and ", ", but ", ", which ", ", while ", ", so ", ", or "]:
        idx = sentence.find(marker)
        if idx > 25:
            return sentence[:idx].strip() + "  |  " + sentence[idx + len(marker):].strip()
    return None


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

VERDICTS = [
    (85, "plain_language_ready", "Plain-language ready"),
    (70, "mostly_readable", "Mostly readable"),
    (55, "needs_edits", "Needs edits"),
    (40, "hard_to_read", "Hard to read"),
    (0, "needs_rework", "Needs rework"),
]

ISSUE_PENALTY = {
    "no_headings": 35,
    "wall_of_text": 18,
    "long_paragraphs": 12,
    "no_lists": 15,
    "heading_depth_skip": 5,
    "flat_headings": 4,
    "buried_opening": 6,
}


def _mkfinding(fid, axis, severity, title, why, fix, evidence=None, count=1, extra=None):
    f = {
        "id": fid,
        "axis": axis,
        "severity": severity,
        "title": title,
        "why": why,
        "fix": fix,
        "count": count,
    }
    if evidence:
        f["evidence"] = evidence
    if extra:
        f.update(extra)
    return f


def score_document(metrics, totals, jargon_stats, craft, structure, inclusive, profile):
    weights = profile["weights"]
    target = profile["target_grade"]
    grade = metrics["composite_grade"]
    fre = metrics["flesch_reading_ease"]
    gap = round(grade - target, 1)

    if fre >= 90:
        base = 100.0
    elif fre >= 70:
        base = 92.0
    elif fre >= 60:
        base = 82.0
    elif fre >= 50:
        base = 70.0
    elif fre >= 40:
        base = 58.0
    elif fre >= 30:
        base = 46.0
    elif fre >= 20:
        base = 33.0
    else:
        base = 20.0
    readability_score = max(0.0, base - min(30.0, max(0.0, gap) * 3.0))

    density = jargon_stats["density_pct"]
    jargon_score = 100.0 - min(60.0, density * 8.0)
    jargon_score -= min(25.0, 5.0 * len(jargon_stats["undefined_acronyms"]))
    jargon_score -= min(15.0, 3.0 * jargon_stats["bureau_total"])
    jargon_score = max(0.0, jargon_score)

    craft_score = 100.0
    craft_score -= min(25.0, 4.0 * len(craft["long_sentences"]))
    craft_score -= min(15.0, 7.0 * len(craft["very_long_sentences"]))
    craft_score -= min(18.0, 3.0 * len(craft["passive_sentences"]))
    craft_score -= min(12.0, 1.5 * craft["nominalization_count"])
    if craft["hedge_density"] > 2.0:
        craft_score -= min(15.0, (craft["hedge_density"] - 2.0) * 5.0)
    if craft["filler_density"] > 3.0:
        craft_score -= min(12.0, (craft["filler_density"] - 3.0) * 4.0)
    craft_score -= min(15.0, 3.0 * len(craft["vague_hits"]))
    craft_score -= min(12.0, 3.0 * len(craft["bureau_hits"]))
    craft_score = max(0.0, craft_score)

    struct_score = 100.0
    for issue in structure["issues"]:
        struct_score -= ISSUE_PENALTY.get(issue["code"], 5)
    struct_score = max(0.0, struct_score)

    incl_score = 100.0
    for item in inclusive:
        incl_score -= {"high": 12.0, "medium": 6.0, "low": 3.0}[item["severity"]]
    incl_score = max(0.0, incl_score)

    axes = {
        "readability": round(readability_score, 1),
        "jargon": round(jargon_score, 1),
        "sentence_craft": round(craft_score, 1),
        "structure": round(struct_score, 1),
        "inclusivity": round(incl_score, 1),
    }

    overall = sum(axes[a] * weights[a] for a in AXIS_ORDER)

    caps = []
    if gap > 6:
        caps.append({"cap": 65, "reason": "reads far above the target grade for this audience"})
    elif gap > 3:
        caps.append({"cap": 74, "reason": "reads above the target grade for this audience"})
    if density > 8:
        caps.append({"cap": 70, "reason": "jargon density is very high"})
    if any(i["severity"] == "high" for i in inclusive):
        caps.append({"cap": 68, "reason": "high-severity inclusive language present"})
    if fre < 30 and gap > 3:
        caps.append({"cap": 62, "reason": "reading ease is very low and above the target grade"})

    for c in caps:
        overall = min(overall, c["cap"])

    return {
        "score": round(max(0.0, min(100.0, overall)), 1),
        "axes": axes,
        "weights": weights,
        "gap": gap,
        "caps": caps,
    }


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def analyze(text, audience="general_public", title=""):
    text = (text or "").replace("\u00a0", " ")
    if audience not in AUD_PROFILES:
        audience = "general_public"
    profile = AUD_PROFILES[audience]

    blocks = parse_blocks(text)
    prose_blocks = [b for b in blocks if b["kind"] in ("paragraph", "list_item", "quote")]
    sentences = []
    owner = []
    for bi, b in enumerate(prose_blocks):
        for s in split_sentences(b["text"]):
            sentences.append(s)
            owner.append(bi)

    if not sentences:
        return {"ok": False, "error": "no_prose", "message": "No readable prose found in the text."}

    readability = compute_readability(sentences)
    metrics = readability["metrics"]
    totals = readability["totals"]

    if totals["words"] < MIN_WORDS:
        return {
            "ok": False,
            "error": "too_short",
            "message": "Only %d words found. Paste at least %d words for a meaningful score."
            % (totals["words"], MIN_WORDS),
            "words": totals["words"],
        }

    prose_text = " ".join(b["text"] for b in prose_blocks)
    jargon_terms, jargon_per_sentence = detect_jargon(sentences)
    acronyms = detect_acronyms(text, prose_text)
    inclusive = detect_inclusive(sentences)
    craft = analyze_craft(sentences, totals["words"])
    structure = analyze_structure(blocks)

    jargon_total = sum(t["count"] for t in jargon_terms)
    jargon_stats = {
        "terms": jargon_terms,
        "total": jargon_total,
        "density_pct": round(jargon_total / max(1, totals["words"]) * 100, 2),
        "undefined_acronyms": acronyms,
        "bureau_total": len(craft["bureau_hits"]),
    }

    scored = score_document(metrics, totals, jargon_stats, craft, structure, inclusive, profile)

    findings = []
    grade = metrics["composite_grade"]
    gap = scored["gap"]

    if gap > 1.5:
        findings.append(
            _mkfinding(
                "readability.grade_gap",
                "readability",
                "high" if gap > 4 else "medium",
                "Reads %.1f grades above your audience" % gap,
                "Your text lands at about grade %.1f. The %s audience needs about grade %d, so readers will hit unfamiliar vocabulary and long sentence structures."
                % (grade, profile["label"].lower(), profile["target_grade"]),
                "Shorten sentences, swap long words for short ones, and cut one idea per sentence.",
                evidence=(readability["per_sentence"][0]["text"][:180] if readability["per_sentence"] else None),
            )
        )
    if metrics["flesch_reading_ease"] < 40:
        findings.append(
            _mkfinding(
                "readability.flesch",
                "readability",
                "high" if metrics["flesch_reading_ease"] < 30 else "medium",
                "Flesch reading ease is %.0f" % metrics["flesch_reading_ease"],
                "Below 40 means an average reader will need to reread sentences. Above 60 is plain English.",
                "Prefer one-syllable words and sentences under 20 words.",
            )
        )

    density = jargon_stats["density_pct"]
    if density > 2:
        findings.append(
            _mkfinding(
                "jargon.density",
                "jargon",
                "high" if density > 6 else ("medium" if density > 4 else "low"),
                "Jargon is %.1f%% of the text" % density,
                "%d jargon terms appear %d times. Every one is a place the reader either stops or guesses."
                % (len(jargon_terms), jargon_total),
                "Swap each one for the plain alternative listed in the jargon table.",
            )
        )
    if acronyms:
        findings.append(
            _mkfinding(
                "jargon.acronyms",
                "jargon",
                "high" if len(acronyms) >= 4 else "medium",
                "%d acronyms are never spelled out" % len(acronyms),
                "A reader meets %s with no idea what it stands for."
                % ", ".join(a["acronym"] for a in acronyms[:6]),
                "Spell the term out in full the first time it appears, then use the acronym.",
                evidence=", ".join("%s x%d" % (a["acronym"], a["count"]) for a in acronyms[:8]),
            )
        )

    by_category = defaultdict(list)
    for t in jargon_terms:
        by_category[t["category"]].append(t)
    for cat, items in sorted(by_category.items()):
        total = sum(i["count"] for i in items)
        if total < 2:
            continue
        findings.append(
            _mkfinding(
                "jargon.category.%s" % cat,
                "jargon",
                "medium" if total >= 5 else "low",
                "%s jargon: %d uses across %d terms" % (cat.capitalize(), total, len(items)),
                "Terms like %s assume background the reader may not have."
                % ", ".join(i["term"] for i in items[:5]),
                "Use the plain-language alternative for each one.",
                evidence=items[0]["example"][:180],
                count=total,
                extra={"terms": [i["term"] for i in items]},
            )
        )

    if craft["long_sentences"]:
        findings.append(
            _mkfinding(
                "craft.long_sentences",
                "sentence_craft",
                "high" if len(craft["long_sentences"]) >= 6 else "medium",
                "%d sentences run over 25 words" % len(craft["long_sentences"]),
                "Working memory holds about 20 words at a time, so a long sentence hides its own point.",
                "Split each one at a natural break. The rewrite scaffold shows where.",
                evidence=craft["long_sentences"][0]["text"][:200],
                count=len(craft["long_sentences"]),
            )
        )
    if craft["passive_sentences"]:
        findings.append(
            _mkfinding(
                "craft.passive",
                "sentence_craft",
                "medium" if len(craft["passive_sentences"]) >= 4 else "low",
                "%d sentences hide the actor in the passive voice" % len(craft["passive_sentences"]),
                "Passive voice hides who did what, which is exactly what the reader needs.",
                "Name the actor and put it in front of the verb.",
                evidence=craft["passive_sentences"][0]["text"][:200],
                count=len(craft["passive_sentences"]),
            )
        )
    if craft["nominalization_count"]:
        findings.append(
            _mkfinding(
                "craft.nominalizations",
                "sentence_craft",
                "low",
                "%d nouns are doing a verb's job" % craft["nominalization_count"],
                "Words like %s turn an action into a thing, which slows the reader down."
                % ", ".join(sorted({n["word"] for n in craft["nominalizations"]})[:6]),
                "Use the verb: %s." % ", ".join(sorted({n["verb"] for n in craft["nominalizations"]})[:4]),
                count=craft["nominalization_count"],
            )
        )
    if craft["hedge_density"] > 2.0:
        findings.append(
            _mkfinding(
                "craft.hedging",
                "sentence_craft",
                "medium" if craft["hedge_density"] > 4 else "low",
                "Hedging appears %s times per 100 words" % craft["hedge_density"],
                "Words like may, might and generally make the writer sound unsure and the reader guess.",
                "Commit to the claim, or say plainly what the condition is.",
                count=craft["hedge_count"],
            )
        )
    if craft["filler_density"] > 3.0:
        findings.append(
            _mkfinding(
                "craft.filler",
                "sentence_craft",
                "low",
                "Filler phrases appear %s times per 100 words" % craft["filler_density"],
                "Words like basically, actually and simply add length without adding meaning.",
                "Delete them and see if the sentence still means the same thing.",
                count=craft["filler_count"],
            )
        )
    if craft["vague_hits"]:
        findings.append(
            _mkfinding(
                "craft.vague",
                "sentence_craft",
                "medium" if len(craft["vague_hits"]) >= 4 else "low",
                "%d phrases promise more than they deliver" % len(craft["vague_hits"]),
                "Phrases like %s leave the reader with no idea what happens or when."
                % ", ".join(sorted({h["phrase"] for h in craft["vague_hits"]})[:6]),
                "Replace each one with a real date, number or name.",
                evidence=craft["vague_hits"][0]["text"][:200],
                count=len(craft["vague_hits"]),
            )
        )
    if craft["bureau_hits"]:
        findings.append(
            _mkfinding(
                "craft.bureau",
                "sentence_craft",
                "medium" if len(craft["bureau_hits"]) >= 4 else "low",
                "%d bureaucratic phrases add nothing" % len(craft["bureau_hits"]),
                "Phrases like %s are filler that pushes the real message further down the page."
                % ", ".join(sorted({h["phrase"] for h in craft["bureau_hits"]})[:6]),
                "Replace each one with the short word it is hiding.",
                evidence=craft["bureau_hits"][0]["text"][:200],
                count=len(craft["bureau_hits"]),
            )
        )

    for issue in structure["issues"]:
        sev = "high" if issue["code"] == "no_headings" else ("medium" if issue["code"] in ("wall_of_text", "no_lists") else "low")
        findings.append(
            _mkfinding(
                "structure.%s" % issue["code"],
                "structure",
                sev,
                issue["detail"],
                "Readers scan before they read, so shape is part of meaning.",
                issue["fix"],
            )
        )

    for item in inclusive:
        findings.append(
            _mkfinding(
                "inclusive.%s" % item["term"].replace(" ", "_"),
                "inclusivity",
                item["severity"],
                "'%s' is %s language" % (item["term"], item["category"]),
                "Readers notice this wording, and it can make a reader feel the document is not for them.",
                "Say '%s' instead." % item["alternative"],
                evidence=item["example"][:200],
                count=item["count"],
            )
        )

    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    findings.sort(key=lambda f: (order[f["severity"]], -f["count"]))

    fix_plan = []
    for f in findings:
        gain = round(SEVERITY_GAIN[f["severity"]] * (0.5 + profile["weights"].get(f["axis"], 0.2)), 1)
        fix_plan.append(
            {
                "priority": 0,
                "title": f["title"],
                "axis": f["axis"],
                "severity": f["severity"],
                "gain": gain,
                "fix": f["fix"],
            }
        )
    for i, item in enumerate(fix_plan, 1):
        item["priority"] = i

    rewrites = []
    seen = set()
    for idx, sent in enumerate(sentences):
        new, subs = apply_replacements(sent)
        if subs and idx not in seen:
            seen.add(idx)
            rewrites.append(
                {
                    "kind": "substitution",
                    "index": idx,
                    "original": sent,
                    "suggested": new,
                    "changes": ["%s -> %s" % (s["from"], s["to"] or "(delete)") for s in subs[:8]],
                }
            )
        if len(rewrites) >= 14:
            break
    for item in craft["long_sentences"][:6]:
        hint = split_hint(item["text"])
        if hint:
            rewrites.append(
                {
                    "kind": "split",
                    "index": item["index"],
                    "original": item["text"],
                    "suggested": hint,
                    "changes": ["split at a natural break (%d words)" % item["words"]],
                }
            )
    for item in craft["passive_sentences"][:4]:
        rewrites.append(
            {
                "kind": "passive",
                "index": item["index"],
                "original": item["text"],
                "suggested": "Find who does this, then write: '[Actor] [verb] the [object].'",
                "changes": ["passive voice - put the actor first"],
            }
        )

    hotspot_scores = []
    for s in readability["per_sentence"]:
        j_hits = sum(len(h["hits"]) for h in jargon_per_sentence if h["index"] == s["index"])
        p_hits = 1 if any(p["index"] == s["index"] for p in craft["passive_sentences"]) else 0
        n_hits = sum(1 for n in craft["nominalizations"] if n["index"] == s["index"])
        score = s["words"] + 3 * j_hits + 2 * p_hits + 1.5 * n_hits
        hotspot_scores.append(
            {
                "index": s["index"],
                "text": s["text"],
                "words": s["words"],
                "jargon": j_hits,
                "passive": bool(p_hits),
                "score": round(score, 1),
            }
        )
    hotspots = sorted(hotspot_scores, key=lambda h: -h["score"])[:6]

    paragraph_map = []
    for bi, b in enumerate(prose_blocks):
        if b["kind"] != "paragraph":
            continue
        p_words = len(word_list(b["text"]))
        if p_words < 20:
            continue
        p_sents = split_sentences(b["text"])
        p_read = compute_readability(p_sents)
        p_jargon = sum(1 for h in jargon_per_sentence if owner[h["index"]] == bi)
        paragraph_map.append(
            {
                "index": bi,
                "words": p_words,
                "sentences": len(p_sents),
                "grade": p_read["metrics"]["composite_grade"],
                "jargon": p_jargon,
                "preview": b["text"][:160],
            }
        )

    cleaned, cleaned_count, applied = clean_text(text)

    verdict_key, verdict_label = "needs_rework", "Needs rework"
    for threshold, key, label in VERDICTS:
        if scored["score"] >= threshold:
            verdict_key, verdict_label = key, label
            break

    read_seconds = totals["words"] / 225.0 * 60 + jargon_total * 0.6

    return {
        "ok": True,
        "title": title or "Untitled document",
        "audience": {
            "key": audience,
            "label": profile["label"],
            "blurb": profile["blurb"],
            "target_grade": profile["target_grade"],
        },
        "score": scored["score"],
        "verdict": verdict_key,
        "verdict_label": verdict_label,
        "axes": {
            a: {
                "label": AXIS_LABELS[a],
                "score": scored["axes"][a],
                "weight": profile["weights"][a],
            }
            for a in AXIS_ORDER
        },
        "caps": scored["caps"],
        "metrics": metrics,
        "levels": {
            "reader_level": level_band(grade),
            "reader_grade": grade,
            "target_level": level_band(profile["target_grade"]),
            "target_grade": profile["target_grade"],
            "gap": scored["gap"],
        },
        "stats": {
            "words": totals["words"],
            "sentences": totals["sentences"],
            "paragraphs": structure["paragraph_count"],
            "headings": len(structure["headings"]),
            "list_items": structure["list_item_count"],
            "avg_sentence_words": craft["avg_sentence_words"],
            "avg_paragraph_words": structure["avg_paragraph_words"],
            "avg_syllables_per_word": totals["avg_syllables_per_word"],
            "read_time_minutes": round(read_seconds / 60.0, 1),
            "jargon_hits": jargon_total,
            "jargon_density_pct": jargon_stats["density_pct"],
            "undefined_acronyms": len(acronyms),
            "passive_sentences": len(craft["passive_sentences"]),
            "long_sentences": len(craft["long_sentences"]),
            "hedge_density": craft["hedge_density"],
            "filler_density": craft["filler_density"],
            "vague_phrases": len(craft["vague_hits"]),
            "bureau_phrases": len(craft["bureau_hits"]),
            "inclusive_terms": len(inclusive),
        },
        "findings": findings,
        "jargon": jargon_terms,
        "acronyms": acronyms,
        "inclusive": inclusive,
        "structure": structure,
        "hotspots": hotspots,
        "paragraph_map": paragraph_map,
        "fix_plan": fix_plan,
        "rewrites": rewrites,
        "cleaned_draft": cleaned,
        "cleaned_substitutions": cleaned_count,
    }


# ---------------------------------------------------------------------------
# Markdown export
# ---------------------------------------------------------------------------

FENCE = chr(96) * 3


def render_markdown(result):
    if not result.get("ok"):
        return "# Plain-Speak Forge\n\n%s\n" % result.get("message", "Nothing to report.")
    s = result["stats"]
    m = result["metrics"]
    lv = result["levels"]
    lines = []
    lines.append("# Plain-Speak report: %s" % result["title"])
    lines.append("")
    lines.append("**Score: %.1f / 100 - %s**" % (result["score"], result["verdict_label"]))
    lines.append("")
    lines.append("- Audience: %s (target grade %d)" % (result["audience"]["label"], result["audience"]["target_grade"]))
    lines.append("- Reads like: %s (grade %.1f)" % (lv["reader_level"], lv["reader_grade"]))
    lines.append("- Words: %d | Sentences: %d | Read time: ~%s min" % (s["words"], s["sentences"], s["read_time_minutes"]))
    lines.append("")
    lines.append("## Scorecard")
    lines.append("")
    lines.append("| Axis | Score | Weight |")
    lines.append("| --- | ---: | ---: |")
    for a in AXIS_ORDER:
        ax = result["axes"][a]
        lines.append("| %s | %.1f | %.2f |" % (ax["label"], ax["score"], ax["weight"]))
    lines.append("")
    lines.append("## Readability metrics")
    lines.append("")
    for key, label in [
        ("flesch_reading_ease", "Flesch Reading Ease"),
        ("flesch_kincaid_grade", "Flesch-Kincaid Grade"),
        ("gunning_fog", "Gunning Fog"),
        ("smog", "SMOG"),
        ("coleman_liau", "Coleman-Liau"),
        ("automated_readability_index", "Automated Readability Index"),
        ("composite_grade", "Composite grade"),
    ]:
        lines.append("- %s: %s" % (label, m[key]))
    lines.append("")
    if result["caps"]:
        lines.append("## Score caps applied")
        lines.append("")
        for c in result["caps"]:
            lines.append("- Capped at %d because the text %s." % (c["cap"], c["reason"]))
        lines.append("")
    lines.append("## Findings (%d)" % len(result["findings"]))
    lines.append("")
    for f in result["findings"]:
        lines.append("### [%s] %s" % (f["severity"].upper(), f["title"]))
        lines.append("")
        lines.append(f["why"])
        lines.append("")
        lines.append("**Fix:** %s" % f["fix"])
        if f.get("evidence"):
            lines.append("")
            lines.append("> %s" % f["evidence"])
        lines.append("")
    if result["jargon"]:
        lines.append("## Jargon table")
        lines.append("")
        lines.append("| Term | Category | Uses | Plain alternative |")
        lines.append("| --- | --- | ---: | --- |")
        for t in result["jargon"]:
            lines.append("| %s | %s | %d | %s |" % (t["term"], t["category"], t["count"], t["plain"]))
        lines.append("")
    if result["acronyms"]:
        lines.append("## Acronyms never spelled out")
        lines.append("")
        for a in result["acronyms"]:
            lines.append("- **%s** (used %d times)" % (a["acronym"], a["count"]))
        lines.append("")
    lines.append("## Fix plan")
    lines.append("")
    for item in result["fix_plan"]:
        lines.append("%d. **[%s]** %s - %s (est. +%.1f pts)" % (
            item["priority"], item["severity"], item["title"], item["fix"], item["gain"]))
    lines.append("")
    if result["hotspots"]:
        lines.append("## Hardest passages")
        lines.append("")
        for h in result["hotspots"]:
            lines.append("- (%d words, %d jargon) %s" % (h["words"], h["jargon"], h["text"][:200]))
        lines.append("")
    if result["rewrites"]:
        lines.append("## Rewrite scaffold")
        lines.append("")
        for r in result["rewrites"]:
            lines.append("**%s**" % r["kind"])
            lines.append("")
            lines.append("- Before: %s" % r["original"][:220])
            lines.append("- After:  %s" % r["suggested"][:220])
            lines.append("")
    lines.append("## Cleaned draft (mechanical substitutions only)")
    lines.append("")
    lines.append("%d substitutions applied. Meaning still needs a human read." % result["cleaned_substitutions"])
    lines.append("")
    lines.append(FENCE)
    lines.append(result["cleaned_draft"])
    lines.append(FENCE)
    lines.append("")
    return "\n".join(lines)

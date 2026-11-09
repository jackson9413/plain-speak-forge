"""Plain-Speak Forge - local-first plain-language and readability workbench.

Flask + SQLite + vanilla JS. No API keys, no network calls, no LLM.
"""
from __future__ import annotations

import json
import os
import sys

from flask import Flask, Response, jsonify, request, send_from_directory

BASE = os.path.dirname(os.path.abspath(__file__))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import db  # noqa: E402
import engine  # noqa: E402

app = Flask(__name__, static_folder=os.path.join(BASE, "static"), static_url_path="/static")
SAMPLES_DIR = os.path.join(BASE, "samples")


@app.after_request
def no_store(resp):
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.route("/")
def index():
    return send_from_directory(os.path.join(BASE, "static"), "index.html")


@app.get("/api/health")
def health():
    return jsonify({"ok": True, "service": "plain-speak-forge", "version": "1.0.0"})


@app.get("/api/audiences")
def audiences():
    out = []
    for key, prof in engine.AUD_PROFILES.items():
        out.append(
            {
                "key": key,
                "label": prof["label"],
                "blurb": prof["blurb"],
                "target_grade": prof["target_grade"],
                "weights": prof["weights"],
            }
        )
    return jsonify({"audiences": out})


def _manifest():
    path = os.path.join(SAMPLES_DIR, "manifest.json")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


@app.get("/api/samples")
def samples():
    return jsonify({"samples": _manifest()})


@app.get("/api/sample/<key>")
def sample(key):
    for entry in _manifest():
        if entry["key"] == key:
            path = os.path.join(SAMPLES_DIR, entry["file"])
            if not os.path.exists(path):
                break
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            return jsonify(
                {
                    "key": key,
                    "title": entry.get("title", key),
                    "audience": entry.get("audience", "general_public"),
                    "blurb": entry.get("blurb", ""),
                    "text": text,
                }
            )
    return jsonify({"error": "not_found", "message": "No sample named %s." % key}), 404


@app.post("/api/analyze")
def analyze():
    payload = request.get_json(silent=True) or {}
    text = payload.get("text") or ""
    audience = payload.get("audience") or "general_public"
    title = (payload.get("title") or "").strip()
    save = payload.get("save", True)

    if not text.strip():
        return jsonify({"ok": False, "error": "empty", "message": "Paste some text first."}), 400

    result = engine.analyze(text, audience, title)
    if not result.get("ok"):
        return jsonify(result), 422

    if save:
        try:
            result["session_id"] = db.save_session(result)
        except Exception:
            result["session_id"] = None
    return jsonify(result)


@app.get("/api/sessions")
def sessions():
    try:
        limit = min(200, max(1, int(request.args.get("limit", 50))))
    except (TypeError, ValueError):
        limit = 50
    return jsonify({"sessions": db.list_sessions(limit)})


@app.get("/api/sessions/<int:sid>")
def session_detail(sid):
    row = db.get_session(sid)
    if not row:
        return jsonify({"error": "not_found"}), 404
    return jsonify(row)


@app.patch("/api/sessions/<int:sid>")
def session_update(sid):
    payload = request.get_json(silent=True) or {}
    rating = payload.get("self_rating")
    notes = payload.get("notes")
    if rating is not None:
        try:
            rating = max(1, min(5, int(rating)))
        except (TypeError, ValueError):
            rating = None
    row = db.update_session(sid, rating, notes)
    if not row:
        return jsonify({"error": "not_found"}), 404
    return jsonify(row)


@app.get("/api/export/<int:sid>")
def export(sid):
    row = db.get_session(sid)
    if not row:
        return jsonify({"error": "not_found"}), 404
    fmt = (request.args.get("fmt") or "md").lower()
    title = re_slug(row.get("title") or "plain-speak-report")
    if fmt == "json":
        body = json.dumps(row.get("result", {}), indent=2, ensure_ascii=False)
        mime = "application/json"
        ext = "json"
    else:
        body = engine.render_markdown(row.get("result", {}))
        mime = "text/markdown"
        ext = "md"
    resp = Response(body, mimetype=mime)
    resp.headers["Content-Disposition"] = 'attachment; filename="%s.%s"' % (title, ext)
    return resp


def re_slug(text):
    keep = []
    for ch in (text or "").lower():
        if ch.isalnum():
            keep.append(ch)
        elif ch in " -_":
            keep.append("-")
    slug = "".join(keep).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug[:60] or "plain-speak-report"


if __name__ == "__main__":
    db.init_db()
    port = int(os.environ.get("PORT", "8756"))
    app.run(host="127.0.0.1", port=port, debug=False)

var $ = function (id) { return document.getElementById(id); };
var audiences = [], samples = [], lastResult = null;
var filters = { sev: "all", axis: "all" };

function esc(s) {
  return String(s === null || s === undefined ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}
function el(tag, cls, html) {
  var e = document.createElement(tag);
  if (cls) e.className = cls;
  if (html !== undefined) e.innerHTML = html;
  return e;
}
function stat(v, l) {
  return '<div class="stat"><div class="sv">' + esc(v) + '</div><div class="sl">' + esc(l) + '</div></div>';
}
function axisClass(score) {
  if (score >= 85) return "g";
  if (score >= 70) return "y";
  if (score >= 50) return "o";
  return "r";
}

async function boot() {
  try {
    var ar = await fetch("/api/audiences");
    var aj = await ar.json();
    audiences = aj.audiences || [];
    audiences.forEach(function (x) {
      var o = document.createElement("option");
      o.value = x.key; o.textContent = x.label;
      $("audience").appendChild(o);
    });
    var sr = await fetch("/api/samples");
    var sj = await sr.json();
    samples = sj.samples || [];
    samples.forEach(function (x) {
      var o = document.createElement("option");
      o.value = x.key; o.textContent = x.title;
      $("sample").appendChild(o);
    });
  } catch (e) {
    setStatus("Could not reach the API: " + e.message, true);
  }
  updateBlurb();
  updateCounter();
  loadHistory();
}

function updateBlurb() {
  var key = $("audience").value;
  var p = audiences.filter(function (a) { return a.key === key; })[0];
  if (!p) return;
  $("audienceBlurb").textContent = p.label + " - " + p.blurb + " Target reading level: grade " + p.target_grade + ".";
}

function updateCounter() {
  var t = $("text").value;
  var words = t.trim() ? t.trim().split(/\s+/).length : 0;
  $("counter").textContent = words + " words / " + t.length + " characters";
}

function setStatus(msg, isErr) {
  var s = $("status");
  s.textContent = msg || "";
  s.className = isErr ? "status err" : "status";
}

async function analyze() {
  var text = $("text").value;
  if (!text.trim()) { setStatus("Paste some text first.", true); return; }
  setStatus("Analysing...");
  $("analyze").disabled = true;
  try {
    var res = await fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        text: text,
        audience: $("audience").value,
        title: $("title").value,
        save: true
      })
    });
    var data = await res.json();
    if (!data.ok) {
      setStatus(data.message || "Analysis failed.", true);
      return;
    }
    lastResult = data;
    render(data);
    setStatus("Done. Score " + data.score + "/100.");
    loadHistory();
  } catch (e) {
    setStatus("Request failed: " + e.message, true);
  } finally {
    $("analyze").disabled = false;
  }
}

function render(r) {
  $("results").classList.remove("hidden");
  $("score").textContent = r.score;
  var v = $("verdict");
  v.textContent = r.verdict_label;
  v.className = "verdict " + r.verdict;
  $("levels").innerHTML = "Reads like <b>" + esc(r.levels.reader_level) + "</b> (grade " +
    esc(r.levels.reader_grade) + "). Your audience needs <b>" + esc(r.levels.target_level) +
    "</b> (grade " + esc(r.levels.target_grade) + "). Gap: " + esc(r.levels.gap) + " grades.";

  var ax = $("axes");
  ax.innerHTML = "";
  Object.keys(r.axes).forEach(function (k) {
    var a = r.axes[k];
    var d = el("div", "axis " + axisClass(a.score));
    d.innerHTML = '<div class="an">' + esc(a.label) + '</div><div class="av">' + a.score +
      '</div><div class="aw">weight ' + Math.round(a.weight * 100) + '%</div>';
    ax.appendChild(d);
  });

  var caps = $("caps");
  if (r.caps && r.caps.length) {
    caps.classList.remove("hidden");
    caps.innerHTML = "<b>Score capped.</b> " + r.caps.map(function (c) {
      return "Capped at " + c.cap + " - " + esc(c.reason) + ".";
    }).join(" ");
  } else { caps.classList.add("hidden"); caps.innerHTML = ""; }

  var s = r.stats;
  $("stats").innerHTML = [
    stat(s.words, "Words"),
    stat(s.sentences, "Sentences"),
    stat(s.paragraphs, "Paragraphs"),
    stat(s.headings, "Headings"),
    stat(s.list_items, "List items"),
    stat(s.avg_sentence_words, "Avg sentence words"),
    stat(s.read_time_minutes + " min", "Read time"),
    stat(s.jargon_hits, "Jargon hits"),
    stat(s.jargon_density_pct + "%", "Jargon density"),
    stat(s.undefined_acronyms, "Undefined acronyms"),
    stat(s.passive_sentences, "Passive sentences"),
    stat(s.long_sentences, "Sentences over 25 words")
  ].join("");

  $("c-findings").textContent = r.findings.length;
  $("c-jargon").textContent = r.jargon.length;
  renderFindings(r);
  renderJargon(r);
  renderStructure(r);
  renderHotspots(r);
  renderFixPlan(r);
  renderRewrites(r);
  renderParagraphs(r);
  $("cleanedDraft").value = r.cleaned_draft;
  $("cleanedNote").textContent = r.cleaned_substitutions + " mechanical substitutions applied. Meaning still needs a human read.";
}

function renderFindings(r) {
  var box = $("findings");
  box.innerHTML = "";
  var shown = r.findings.filter(function (f) {
    if (filters.sev !== "all" && f.severity !== filters.sev) return false;
    if (filters.axis !== "all" && f.axis !== filters.axis) return false;
    return true;
  });
  if (!shown.length) {
    box.appendChild(el("div", "card", "<h3>Nothing to fix here</h3><p>No findings match this filter.</p>"));
    return;
  }
  shown.forEach(function (f) {
    var c = el("div", "card " + f.severity);
    var h = "<h3>" + esc(f.title) + '<span class="tagpill ' + f.severity + '">' + f.severity + "</span>" +
      '<span class="tagpill">' + esc(f.axis.replace("_", " ")) + "</span>";
    if (f.count > 1) h += '<span class="tagpill">x' + f.count + "</span>";
    h += "</h3>";
    h += "<p>" + esc(f.why) + "</p>";
    h += '<p class="fix"><b>Fix:</b> ' + esc(f.fix) + "</p>";
    if (f.evidence) h += '<div class="evidence">' + esc(f.evidence) + "</div>";
    c.innerHTML = h;
    box.appendChild(c);
  });
}

function renderJargon(r) {
  $("jargonIntro").textContent = r.jargon.length
    ? r.jargon.length + " jargon terms, " + r.stats.jargon_hits + " uses, " + r.stats.jargon_density_pct + "% of the text."
    : "No jargon from the lexicon found in this text.";
  var tb = $("jargonTable").querySelector("tbody");
  tb.innerHTML = "";
  r.jargon.forEach(function (t) {
    var tr = document.createElement("tr");
    tr.innerHTML = "<td><b>" + esc(t.term) + "</b></td><td>" + esc(t.category) + "</td><td class='num'>" +
      t.count + "</td><td class='alt'>" + esc(t.plain) + "</td><td class='ex'>" + esc(t.example) + "</td>";
    tb.appendChild(tr);
  });
  var ab = $("acronyms");
  ab.innerHTML = "";
  if (r.acronyms.length) {
    var head = el("div", "note", "<b>Acronyms never spelled out:</b> " +
      r.acronyms.map(function (a) { return esc(a.acronym) + " (x" + a.count + ")"; }).join(", "));
    ab.appendChild(head);
  }
}

function renderStructure(r) {
  var st = r.structure;
  $("structureStats").innerHTML = [
    stat(st.paragraph_count, "Paragraphs"),
    stat(st.list_item_count, "List items"),
    stat(st.headings.length, "Headings"),
    stat(st.avg_paragraph_words, "Avg paragraph words"),
    stat(st.max_paragraph_words, "Longest paragraph"),
    stat(Math.round(st.bullet_ratio * 100) + "%", "Words in lists")
  ].join("");
  var box = $("structureIssues");
  box.innerHTML = "";
  if (!st.issues.length) {
    box.appendChild(el("div", "card", "<h3>Shape looks good</h3><p>No structural problems found.</p>"));
  } else {
    st.issues.forEach(function (i) {
      box.appendChild(el("div", "card medium",
        "<h3>" + esc(i.detail) + "</h3><p class='fix'><b>Fix:</b> " + esc(i.fix) + "</p>"));
    });
  }
  var hb = $("headings");
  hb.innerHTML = "";
  if (st.headings.length) {
    hb.appendChild(el("div", "note", "<b>Headings found</b>"));
    st.headings.forEach(function (h) {
      hb.appendChild(el("div", "headingrow", "H" + h.level + " &nbsp; <b>" + esc(h.text) + "</b>"));
    });
  }
}

function renderHotspots(r) {
  var box = $("hotspots");
  box.innerHTML = "";
  if (!r.hotspots.length) {
    box.appendChild(el("div", "card", "<h3>No hotspots</h3><p>No sentence stood out as hard to read.</p>"));
    return;
  }
  r.hotspots.forEach(function (h) {
    var reasons = [];
    if (h.words > 25) reasons.push(h.words + " words");
    if (h.jargon) reasons.push(h.jargon + " jargon terms");
    if (h.passive) reasons.push("passive voice");
    box.appendChild(el("div", "card medium",
      "<h3>Sentence " + (h.index + 1) + '<span class="tagpill">score ' + h.score + "</span></h3>" +
      "<p>" + esc(h.text) + "</p>" +
      "<p class='fix'>Why it is hard: " + esc(reasons.join(", ") || "long and dense") + "</p>"));
  });
}

function renderFixPlan(r) {
  var box = $("fixplan");
  box.innerHTML = "";
  r.fix_plan.forEach(function (p) {
    box.appendChild(el("div", "card " + p.severity,
      "<h3>" + p.priority + ". " + esc(p.title) + '<span class="tagpill">' + p.severity + "</span>" +
      '<span class="tagpill">est +' + p.gain + " pts</span></h3>" +
      "<p class='fix'>" + esc(p.fix) + "</p>"));
  });
  if (!r.fix_plan.length) {
    box.appendChild(el("div", "card", "<h3>Nothing to do</h3><p>No fixes queued.</p>"));
  }
}

function renderRewrites(r) {
  var box = $("rewrites");
  box.innerHTML = "";
  if (!r.rewrites.length) {
    box.appendChild(el("div", "card", "<h3>No mechanical rewrites</h3><p>There was nothing the engine could safely rewrite for you.</p>"));
    return;
  }
  r.rewrites.forEach(function (w) {
    var c = el("div", "rewrite");
    c.innerHTML = '<div class="before"><b>Before:</b> ' + esc(w.original) + "</div>" +
      '<div class="after"><b>After:</b> ' + esc(w.suggested) + "</div>" +
      '<div class="chg">' + esc(w.changes.join(" | ")) + "</div>";
    box.appendChild(c);
  });
}

function renderParagraphs(r) {
  var box = $("paragraphs");
  box.innerHTML = "";
  if (!r.paragraph_map.length) {
    box.appendChild(el("div", "card", "<h3>No long enough paragraphs</h3><p>Only paragraphs of 20 words or more are shown.</p>"));
    return;
  }
  r.paragraph_map.forEach(function (p) {
    box.appendChild(el("div", "card " + (p.grade > 14 ? "high" : (p.grade > 10 ? "medium" : "low")),
      "<h3>Paragraph " + (p.index + 1) + '<span class="gradepill">grade ' + p.grade + "</span>" +
      '<span class="tagpill">' + p.words + " words</span>" +
      (p.jargon ? '<span class="tagpill">' + p.jargon + " jargon</span>" : "") + "</h3>" +
      "<p>" + esc(p.preview) + "</p>"));
  });
}

async function loadHistory() {
  try {
    var res = await fetch("/api/sessions?limit=25");
    var data = await res.json();
    var box = $("history");
    box.innerHTML = "";
    if (!data.sessions.length) {
      box.appendChild(el("div", "card", "<h3>No runs yet</h3><p>Analyse something and it will show up here.</p>"));
      return;
    }
    data.sessions.forEach(function (s) {
      var row = el("div", "hrow");
      var stars = "";
      for (var i = 1; i <= 5; i++) {
        stars += '<span class="star' + (s.self_rating && s.self_rating >= i ? " on" : "") + '" data-id="' + s.id + '" data-v="' + i + '">*</span>';
      }
      row.innerHTML = '<span class="hs">' + s.score + "</span>" +
        '<span class="ht">' + esc(s.title || "Untitled") + "</span>" +
        '<span class="hm">' + esc(s.audience) + " | " + s.word_count + " words | " + esc((s.created_at || "").replace("T", " ")) + "</span>" +
        '<span class="stars" title="Self rating">' + stars + "</span>" +
        '<input type="text" class="notes" data-id="' + s.id + '" placeholder="Notes" value="' + esc(s.notes || "") + '" />' +
        '<a class="tagpill" href="/api/export/' + s.id + '?fmt=md">MD</a>' +
        '<a class="tagpill" href="/api/export/' + s.id + '?fmt=json">JSON</a>' +
        '<button class="ghost reopen" data-id="' + s.id + '">Open</button>';
      box.appendChild(row);
    });
  } catch (e) { /* history is best effort */ }
}

async function reopen(id) {
  try {
    var res = await fetch("/api/sessions/" + id);
    var data = await res.json();
    if (!data.result || !data.result.ok) return;
    lastResult = data.result;
    $("title").value = data.title || "";
    $("audience").value = data.audience || "general_public";
    updateBlurb();
    $("text").value = "";
    render(data.result);
    window.scrollTo({ top: 0, behavior: "smooth" });
    setStatus("Reopened run #" + id + ".");
  } catch (e) { setStatus("Could not open that run.", true); }
}

document.addEventListener("DOMContentLoaded", function () {
  boot();
  $("analyze").addEventListener("click", analyze);
  $("text").addEventListener("input", updateCounter);
  $("audience").addEventListener("change", updateBlurb);
  $("clear").addEventListener("click", function () {
    $("text").value = ""; $("title").value = ""; updateCounter();
    $("results").classList.add("hidden");
    setStatus("");
  });
  $("loadSample").addEventListener("click", async function () {
    var key = $("sample").value;
    if (!key) { setStatus("Choose a sample first.", true); return; }
    try {
      var res = await fetch("/api/sample/" + key);
      var data = await res.json();
      $("text").value = data.text;
      $("title").value = data.title;
      $("audience").value = data.audience || "general_public";
      updateBlurb(); updateCounter();
      setStatus("Loaded '" + data.title + "'. Press Analyze.");
    } catch (e) { setStatus("Could not load the sample.", true); }
  });
  $("tabs").addEventListener("click", function (ev) {
    var b = ev.target.closest("button[data-tab]");
    if (!b) return;
    var all = $("tabs").querySelectorAll("button");
    for (var i = 0; i < all.length; i++) all[i].classList.remove("active");
    b.classList.add("active");
    var panes = document.querySelectorAll(".tabpane");
    for (var j = 0; j < panes.length; j++) panes[j].classList.remove("active");
    $("tab-" + b.getAttribute("data-tab")).classList.add("active");
  });
  $("filters").addEventListener("click", function (ev) {
    var c = ev.target.closest(".chip");
    if (!c) return;
    var chips = $("filters").querySelectorAll(".chip");
    for (var i = 0; i < chips.length; i++) chips[i].classList.remove("active");
    c.classList.add("active");
    filters.sev = c.getAttribute("data-sev");
    if (lastResult) renderFindings(lastResult);
  });
  $("axisFilter").addEventListener("change", function () {
    filters.axis = this.value;
    if (lastResult) renderFindings(lastResult);
  });
  $("copyCleaned").addEventListener("click", function () {
    var ta = $("cleanedDraft");
    ta.select();
    try { document.execCommand("copy"); setStatus("Cleaned draft copied."); }
    catch (e) { setStatus("Copy failed - select the text and copy manually.", true); }
  });
  $("refreshHistory").addEventListener("click", loadHistory);
  $("history").addEventListener("click", async function (ev) {
    var star = ev.target.closest(".star");
    if (star) {
      var id = star.getAttribute("data-id");
      var v = parseInt(star.getAttribute("data-v"), 10);
      try {
        await fetch("/api/sessions/" + id, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ self_rating: v })
        });
        loadHistory();
      } catch (e) { setStatus("Could not save the rating.", true); }
      return;
    }
    var open = ev.target.closest(".reopen");
    if (open) reopen(open.getAttribute("data-id"));
  });
  $("history").addEventListener("change", async function (ev) {
    var n = ev.target.closest(".notes");
    if (!n) return;
    try {
      await fetch("/api/sessions/" + n.getAttribute("data-id"), {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ notes: n.value })
      });
      setStatus("Notes saved.");
    } catch (e) { setStatus("Could not save the notes.", true); }
  });
});

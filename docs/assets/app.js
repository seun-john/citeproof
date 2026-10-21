/* CiteProof browser demo. Everything the student pastes is handled in this tab.
   Network use: this site's own files, Pyodide from one pinned CDN URL, and (only if the student
   turns it on and presses send) api.crossref.org. */
"use strict";

const PYODIDE_VERSION = "0.29.5";
const PYODIDE_BASE = `https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/`;
const PYODIDE_SRI = "sha384-VR47TfKeAmT7vMej7bwOVg0tHTQLLGMSIpsXtFMCZG5OpKZSIXoSLtGY//qHcxc6";
const PY_FILES = [
  "citeproof/__init__.py", "citeproof/core.py", "citeproof/references.py",
  "citeproof/bibtex.py", "citeproof/claims.py", "demo_logic.py", "text_references.py",
];
const MAX_CATALOGUE_BYTES = 8 * 1000 * 1000;
const LOOKUP_GAP_MS = 400;
const LOOKUP_TIMEOUT_MS = 12000;

const $ = (id) => document.getElementById(id);
const state = {
  demo: null, // Python module demo_logic, once the engine is ready
  sample: null, // { label, records } for the bundled sample catalogue
  file: null, // { label, records, notices } for the student's own catalogue file
  result: null,
  lookupAbort: null,
  lookupLog: null,
  searchLog: null,
  extra: [], // catalogue records added from Crossref for this result
  overrides: {}, // reference id -> DOI the person chose from a title search
  candidates: {}, // reference id -> possible DOIs from a title search (suggestions)
};

/* ---------- small DOM helpers (text only, never innerHTML) ---------- */

function h(tag, props = {}, ...kids) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === false || value == null) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid == null || kid === false) continue;
    node.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  return node;
}

function call(fn, ...args) {
  return JSON.parse(state.demo[fn](...args));
}

function setEngine(text, ready = false) {
  $("engine-text").textContent = text;
  $("engine").classList.toggle("ready", ready);
}

/* ---------- loading the Python engine ---------- */

function loadScript(src, integrity) {
  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = src;
    script.integrity = integrity;
    script.crossOrigin = "anonymous";
    script.onload = resolve;
    script.onerror = () => reject(new Error("The Pyodide script could not be loaded."));
    document.head.append(script);
  });
}

async function startEngine() {
  $("engine-failed").hidden = true;
  $("engine").hidden = false;
  setEngine("Loading the Python engine (about 12 MB, first visit only)…");
  const slow = setTimeout(
    () => setEngine("Still loading. This can take a minute on a slow connection…"), 20000);
  try {
    if (!window.loadPyodide) await loadScript(`${PYODIDE_BASE}pyodide.js`, PYODIDE_SRI);
    const pyodide = await window.loadPyodide({ indexURL: PYODIDE_BASE });
    setEngine("Loading CiteProof…");
    await pyodide.loadPackage("sqlite3"); // CiteProof's core.py imports it
    for (const file of PY_FILES) {
      const response = await fetch(`py/${file}`, { cache: "no-cache" });
      if (!response.ok) throw new Error(`py/${file} returned HTTP ${response.status}`);
      const dir = file.includes("/") ? `/app/${file.split("/")[0]}` : "/app";
      pyodide.FS.mkdirTree(dir);
      pyodide.FS.writeFile(`/app/${file}`, await response.text());
    }
    pyodide.runPython("import sys\nsys.path.insert(0, '/app')");
    state.demo = pyodide.pyimport("demo_logic");
    const info = JSON.parse(state.demo.api_info());
    $("cp-version").textContent = info.citeproof_version;
    setEngine(`Ready. CiteProof ${info.citeproof_version} is running in this tab (Python ${info.python}).`, true);
    await prepareSampleCatalogue();
    $("check-btn").disabled = false;
    $("check-hint").textContent = "";
  } catch (error) {
    console.error(error);
    $("engine").hidden = true;
    $("engine-failed").hidden = false;
    $("engine-failed-text").textContent =
      `This demo needs Pyodide, the Python engine for browsers, and it could not be started (${error.message}).`;
    $("check-hint").textContent = "The checker is unavailable until the engine loads.";
    $("retry-engine").focus();
  } finally {
    clearTimeout(slow);
  }
}

/* ---------- catalogue ---------- */

async function prepareSampleCatalogue() {
  const response = await fetch("data/sample-catalogue.json");
  if (!response.ok) throw new Error(`the sample catalogue returned HTTP ${response.status}`);
  const parsed = call("api_parse_catalogue", await response.text(), "sample-catalogue.json");
  if (!parsed.ok) throw new Error(parsed.error.message);
  state.sample = { label: "the sample catalogue", records: parsed.records };
  $("sample-count").textContent = `(${parsed.records.length} records)`;
  const list = $("sample-list");
  list.replaceChildren(...parsed.records.map((r) => h("li", {},
    h("strong", { text: r.title }), h("br"),
    h("code", { text: r.doi }), ` · ${r.year} · ${r.journal} · `,
    r.retracted ? "flagged retracted" : "not flagged retracted", h("br"),
    h("span", { class: "muted", text: `Source: ${r.provenance}` }))));
}

async function onCatalogueFile(event) {
  const file = event.target.files[0];
  const status = $("cat-status");
  if (!file) return;
  $("cat-file").checked = true;
  if (file.size > MAX_CATALOGUE_BYTES) {
    status.textContent = `That file is ${(file.size / 1e6).toFixed(1)} MB; this demo accepts up to 8 MB. Try a smaller extract.`;
    event.target.value = "";
    return;
  }
  let text;
  try {
    text = await file.text();
  } catch (error) {
    status.textContent = `Could not read that file: ${error.message}`;
    return;
  }
  if (!state.demo) {
    status.textContent = "The Python engine is still loading. Choose the file again when it is ready.";
    return;
  }
  const parsed = call("api_parse_catalogue", text, file.name);
  if (!parsed.ok) {
    status.replaceChildren(h("strong", { text: `${parsed.error.title}. ` }), parsed.error.message,
      parsed.error.hint ? ` ${parsed.error.hint}` : "");
    event.target.value = "";
    $("cat-sample").checked = true;
    return;
  }
  state.file = { label: `your file ${file.name}`, records: parsed.records, notices: parsed.notices };
  status.replaceChildren(`Loaded ${parsed.records.length} records from ${file.name} (${parsed.format.toUpperCase()}). It stays in this tab. `,
    ...parsed.notices.map((n) => h("span", { class: "notice", text: n })));
}

function chosenCatalogue() {
  return $("cat-file").checked ? state.file : state.sample;
}

/* ---------- rendering ---------- */

function renderError(error) {
  return h("div", { class: "error", role: "alert" },
    h("h3", { text: error.title }),
    h("p", { text: error.message }),
    error.hint ? h("p", { text: error.hint }) : null,
    error.detail ? h("details", {}, h("summary", { text: "Technical detail" }), h("p", { text: error.detail })) : null);
}

function tile(kind, name, status, summary, what) {
  const part = summary[kind];
  return h("li", { class: `tile ${kind}` },
    h("div", { class: "big", text: `${part.count} of ${summary.total}` }),
    h("div", { class: "pct", text: `${part.percent}%` }),
    h("div", { class: "name", text: name }),
    h("p", { class: "what" }, h("code", { text: status }), " — ", what));
}

function badgeClass(verdict) {
  return verdict.toLowerCase();
}

function renderRow(row) {
  return h("li", {},
    h("article", { class: `ref ${badgeClass(row.verdict)}`, "aria-label": `Reference ${row.id}` },
      h("div", { class: "ref-head" },
        h("span", { class: "ref-id", text: row.id }),
        h("span", { class: `badge ${badgeClass(row.verdict)}`, text: row.verdict }),
        row.flags.map((f) => h("span", { class: "badge flag", text: f.status })),
        row.doi_chosen ? h("span", { class: "badge needs_review", text: "DOI added by you" }) : null,
        row.from_crossref && !row.doi_chosen ? h("span", { class: "badge needs_review", text: "live Crossref record" }) : null),
      h("p", { class: "ref-title", text: row.title || "(no title in your reference)" }),
      h("p", { class: "headline", text: row.headline }),
      h("p", { class: "says" }, h("span", { class: "label", text: "CiteProof says: " }), `“${row.message}”`),
      h("dl", { class: "evidence" }, row.evidence.map((e) => [h("dt", { text: e.label }), h("dd", { text: e.value })])),
      row.read ? renderRead(row.read) : null,
      renderCandidates(row),
      row.flags.length ? h("ul", { class: "flag-list" }, row.flags.map((f) => h("li", {},
        h("strong", { text: `${f.status}: ` }), `“${f.message}”`, f.note ? ` ${f.note}` : ""))) : null,
      h("p", { class: "person", text: row.person_note })));
}

function renderCandidates(row) {
  const found = state.candidates[row.id];
  if (!found || row.doi_chosen) return null;
  if (!found.length) {
    return h("div", { class: "candidates" }, h("p", { class: "help", text: "Crossref's title search returned no possible matches for this reference." }));
  }
  return h("div", { class: "candidates" },
    h("h4", { text: "Possible DOIs found by Crossref (suggestions, not checked)" }),
    h("p", { class: "help", text: "Crossref matched on your title, first author and year. These may be different works with similar titles. Read each one. Nothing is chosen for you." }),
    h("ul", { class: "cand-list" }, found.map((c) => h("li", {},
      h("strong", { text: c.title }), h("br"),
      `${c.authors} \u00b7 ${c.year} \u00b7 ${c.journal}`, h("br"),
      h("code", { text: c.doi }),
      ` \u00b7 title similarity ${c.title_similarity} \u00b7 year ${c.year_matches ? "matches" : "differs or was not read"}`, h("br"),
      h("button", {
        type: "button", class: "btn", "aria-label": `Use DOI ${c.doi} for reference ${row.id} and check again`,
        "data-use-doi": c.doi, "data-ref": row.id,
      }, "Use this DOI and check again")))));
}

function useCandidate(refId, doi) {
  const picked = (state.candidates[refId] || []).find((c) => c.doi === doi);
  if (!picked) return;
  state.overrides[refId] = doi;
  state.extra.push(picked.record);
  runCheck();
}

function renderRead(read) {
  return h("details", { class: "read" },
    h("summary", { text: "How this was read" }),
    h("p", { class: "help" }, "Your text: ", h("q", { text: read.raw })),
    h("p", { class: "help", text: `Layout recognised: ${read.style}. This reading is the demo's own, not CiteProof's. If a field is wrong or missing, fix the text and check again.` }),
    h("dl", { class: "evidence" }, read.fields.map((f) => [h("dt", { text: f.label }), h("dd", { text: f.value })])));
}

function renderMissing(item) {
  return h("li", {},
    h("article", { class: "ref missing_reference", "aria-label": `Citation ${item.id}` },
      h("div", { class: "ref-head" },
        h("span", { class: "ref-id", text: item.id }),
        h("span", { class: "badge missing_reference", text: item.verdict })),
      h("p", { class: "says" }, h("span", { class: "label", text: "CiteProof says: " }), `“${item.message}”`),
      h("p", { class: "person", text: item.person_note })));
}

function flagsLine(flags) {
  const names = {
    RETRACTED: "marked retracted by the catalogue",
    DUPLICATE: "duplicate",
    UNCITED_REFERENCE: "in the list but not cited",
    MISSING_REFERENCE: "cited but not in the list",
    RETRACTION_STATUS_NOT_SUPPLIED: "catalogue gave no retraction status",
  };
  const parts = Object.entries(flags).filter(([, n]) => n > 0).map(([k, n]) => `${n} ${names[k]}`);
  return parts.length ? `Also flagged: ${parts.join(" · ")}.` : "No other flags.";
}

function renderResult(result) {
  const s = result.summary;
  const body = $("results-body");
  const kids = [
    h("p", { class: "meta", text: `Checked ${s.total} reference${s.total === 1 ? "" : "s"} (${{ bibtex: "BibTeX", json: "JSON", text: "plain text" }[result.input_format]}) against ${result.catalogue_label} — ${result.catalogue_size} records — with CiteProof ${result.citeproof_version}.` }),
    h("p", { class: "standing", text: "These are comparisons with one catalogue, not judgements. A person must decide what each result means." }),
    h("p", { class: "summary-line", text: `Of ${s.total} reference${s.total === 1 ? "" : "s"}: ${s.verified.count} verified (${s.verified.percent}%) \u00b7 ${s.metadata_mismatch.count} metadata mismatch (${s.metadata_mismatch.percent}%) \u00b7 ${s.no_verdict.count} no verdict (${s.no_verdict.percent}%).` }),
    ...result.notices.map((n) => h("p", { class: "notice", text: n })),
    h("ul", { class: "tiles", "aria-label": "Summary" },
      tile("verified", "Verified", "VERIFIED", s, "the DOI was found and every compared field matches."),
      tile("metadata_mismatch", "Metadata mismatch", "METADATA_MISMATCH", s, "the DOI was found but a field differs or is missing."),
      tile("no_verdict", "No verdict", "NEEDS_REVIEW", s, "no DOI, or the DOI is not in this catalogue. This says nothing about whether the reference is real.")),
    h("div", { class: "bar", "aria-hidden": "true" }, ["verified", "metadata_mismatch", "no_verdict"].map((k) => {
      const seg = h("span", { class: k });
      seg.style.flexGrow = String(s[k].count);
      return seg;
    })),
    h("p", { class: "flags-line", text: flagsLine(s.other_flags) }),
    h("div", { class: "exports" },
      h("button", { type: "button", class: "btn", id: "dl-csv" }, "Download results (CSV)"),
      h("button", { type: "button", class: "btn", id: "dl-json" }, "Download CiteProof report (JSON)")),
  ];
  kids.push(h("h3", { text: "Reference by reference" }),
    h("ol", { class: "refs" }, result.rows.map(renderRow), result.missing_references.map(renderMissing)));
  body.replaceChildren(...kids);
  $("dl-csv").addEventListener("click", () => download("citeproof-results.csv", "text/csv", "﻿" + call("api_csv", JSON.stringify(result)).csv));
  $("dl-json").addEventListener("click", () => download("citeproof-report.json", "application/json", JSON.stringify(result.report, null, 2)));
  for (const button of body.querySelectorAll("[data-use-doi]")) {
    button.addEventListener("click", () => useCandidate(button.dataset.ref, button.dataset.useDoi));
  }
  renderSearchPanel(result);
  renderLookupPanel(result);
}

function showResults(node, heading = "Results") {
  const section = $("results");
  section.hidden = false;
  $("results-h").textContent = heading;
  if (node) $("results-body").replaceChildren(node);
  $("results-h").focus();
  $("results-h").scrollIntoView({ block: "start" });
}

function download(name, type, text) {
  const url = URL.createObjectURL(new Blob([text], { type: `${type};charset=utf-8` }));
  const link = h("a", { href: url, download: name });
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/* ---------- running a check ---------- */

function runCheck() {
  const catalogue = chosenCatalogue();
  if (!catalogue) {
    showResults(renderError({
      title: "No catalogue file chosen",
      message: "“My own catalogue file” is selected but no file has been loaded.",
      hint: "Choose a CSV or JSON file in step 2, or select the sample catalogue.", detail: "",
    }), "Nothing to show yet");
    return null;
  }
  const out = call("api_check", $("refs").value, JSON.stringify(catalogue.records), catalogue.label,
    state.extra.length ? JSON.stringify(state.extra) : "",
    Object.keys(state.overrides).length ? JSON.stringify(state.overrides) : "");
  if (!out.ok) {
    state.result = null;
    showResults(renderError(out.error), "Nothing to show yet");
    return null;
  }
  state.result = out;
  renderResult(out);
  showResults(null);
  return out;
}

async function onSubmit(event) {
  event.preventDefault();
  if (!state.demo) return;
  state.lookupLog = null;
  state.searchLog = null;
  state.extra = [];
  state.overrides = {};
  state.candidates = {};
  runCheck();
}

/* ---------- optional Crossref lookup ---------- */

function renderLookupPanel(result) {
  const old = $("lookup-panel");
  if (old) old.remove();
  if (!$("crossref-on").checked) return;
  const { items, truncated, unusable } = result.lookup;
  const panel = h("section", { class: "lookup", id: "lookup-panel", "aria-labelledby": "lookup-h" });
  panel.append(h("h3", { id: "lookup-h", text: "Crossref lookup (you turned this on)" }));
  if (state.lookupLog) {
    panel.append(h("p", { text: "What happened:" }),
      h("ul", {}, state.lookupLog.map((l) => h("li", {}, h("code", { text: l.doi }), ` — ${l.text}`))));
  }
  if (items.length && !state.lookupLog) {
    panel.append(
      h("p", {}, `Nothing has been sent. If you press the button below, this page will make ${items.length} request${items.length === 1 ? "" : "s"} to api.crossref.org, one at a time, with these addresses and nothing else:`),
      h("ul", {}, items.map((i) => h("li", {}, h("code", { text: i.url })))),
      h("p", { class: "help", text: "Crossref will also see your IP address and the usual request headers. No email address or key is used." }),
      h("div", { class: "exports" },
        h("button", { type: "button", class: "btn primary", id: "lookup-go" }, `Send ${items.length} request${items.length === 1 ? "" : "s"} to Crossref`),
        h("button", { type: "button", class: "btn", id: "lookup-cancel", hidden: true }, "Stop")),
      h("p", { id: "lookup-progress", class: "help", role: "status", "aria-live": "polite" }));
  } else if (!items.length && !state.lookupLog) {
    panel.append(h("p", { text: "Nothing to look up: every reference with a DOI is already in the catalogue, or none has a DOI. Nothing was sent." }));
  }
  if (truncated) panel.append(h("p", { class: "notice", text: `${truncated} more DOI(s) are not shown. The demo looks up at most 25 at a time.` }));
  if (unusable.length) panel.append(h("p", { class: "notice", text: `Not sent, because they do not look like DOIs: ${unusable.join(", ")}` }));
  $("results-body").prepend(panel);
  const go = $("lookup-go");
  if (go) go.addEventListener("click", () => doLookup(items));
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function fetchCrossref(url, outer, attempt = 0) {
  const timer = new AbortController();
  const stop = setTimeout(() => timer.abort(), LOOKUP_TIMEOUT_MS);
  const relay = () => timer.abort();
  outer.addEventListener("abort", relay);
  try {
    const response = await fetch(url, {
      method: "GET", mode: "cors", credentials: "omit", referrerPolicy: "no-referrer",
      cache: "no-store", headers: { Accept: "application/json" }, signal: timer.signal,
    });
    if (response.status === 200) return { kind: "ok", json: await response.json() };
    if (response.status === 404) return { kind: "not_found" };
    if (response.status === 429) {
      const wait = Math.min(Number(response.headers.get("Retry-After")) || 5, 30);
      if (attempt < 2) {
        await sleep(wait * 1000);
        return fetchCrossref(url, outer, attempt + 1);
      }
      return { kind: "rate_limited" };
    }
    return { kind: "http", status: response.status };
  } catch (error) {
    if (outer.aborted) return { kind: "stopped" };
    return { kind: error.name === "AbortError" ? "timeout" : "network" };
  } finally {
    clearTimeout(stop);
    outer.removeEventListener("abort", relay);
  }
}

const OUTCOME_TEXT = {
  not_found: "Crossref has no record for this DOI. That is not proof it does not exist: other agencies, such as DataCite, register DOIs too.",
  rate_limited: "Crossref asked this page to slow down (HTTP 429), so it stopped. Wait a minute and try again.",
  timeout: "Crossref did not answer in time.",
  network: "Could not reach Crossref (you may be offline, or something is blocking it).",
  stopped: "Stopped by you before this was sent.",
};

async function doLookup(items) {
  const abort = new AbortController();
  state.lookupAbort = abort;
  $("lookup-go").disabled = true;
  $("lookup-cancel").hidden = false;
  $("lookup-cancel").addEventListener("click", () => abort.abort());
  const log = [];
  let halted = false;
  for (let i = 0; i < items.length; i++) {
    const { doi, url } = items[i];
    if (halted || abort.signal.aborted) {
      log.push({ doi, text: "Not looked up. Nothing was sent for this DOI." });
      continue;
    }
    $("lookup-progress").textContent = `Looking up ${i + 1} of ${items.length}…`;
    const outcome = await fetchCrossref(url, abort.signal);
    if (outcome.kind === "ok") {
      const mapped = call("api_crossref_record", JSON.stringify(outcome.json), new Date().toISOString().slice(0, 10));
      if (mapped.ok) {
        state.extra.push(mapped.record);
        log.push({ doi, text: "Crossref returned a record. It was added to the catalogue for this run." });
      } else {
        log.push({ doi, text: `${mapped.error.title}. ${mapped.error.message}` });
      }
    } else if (outcome.kind === "http") {
      log.push({ doi, text: `Crossref answered with HTTP ${outcome.status}, so nothing was added.` });
    } else {
      log.push({ doi, text: OUTCOME_TEXT[outcome.kind] });
      if (["rate_limited", "network", "stopped"].includes(outcome.kind)) halted = true;
    }
    if (i < items.length - 1 && !halted) await sleep(LOOKUP_GAP_MS);
  }
  state.lookupAbort = null;
  state.lookupLog = log;
  const result = runCheck();
  if (result) $("results-h").textContent = "Results (with Crossref lookup)";
}

/* ---------- optional title search for references with no DOI ---------- */

function renderSearchPanel(result) {
  const old = $("search-panel");
  if (old) old.remove();
  if (!$("search-on").checked) return;
  const { items, truncated, unreadable } = result.search;
  const panel = h("section", { class: "lookup", id: "search-panel", "aria-labelledby": "search-h" });
  panel.append(h("h3", { id: "search-h", text: "Find possible DOIs by title (you turned this on)" }));
  if (state.searchLog) {
    panel.append(h("p", { text: "What happened:" }),
      h("ul", {}, state.searchLog.map((l) => h("li", {}, h("code", { text: l.id }), ` \u2014 ${l.text}`))));
  } else if (items.length) {
    panel.append(
      h("p", {}, `Nothing has been sent. If you press the button below, this page will make ${items.length} search request${items.length === 1 ? "" : "s"} to api.crossref.org, one at a time. This is exactly what each one contains:`),
      h("ul", {}, items.map((i) => h("li", {},
        h("strong", { text: `${i.id}: ` }), `\u201c${i.query}\u201d`, h("br"), h("code", { text: i.url })))),
      h("p", { class: "help", text: "That is each reference's title, first author's family name and year. Crossref will also see your IP address and the usual request headers. No email address or key is used." }),
      h("div", { class: "exports" },
        h("button", { type: "button", class: "btn primary", id: "search-go" }, `Send ${items.length} search${items.length === 1 ? "" : "es"} to Crossref`),
        h("button", { type: "button", class: "btn", id: "search-cancel", hidden: true }, "Stop")),
      h("p", { id: "search-progress", class: "help", role: "status", "aria-live": "polite" }));
  } else {
    panel.append(h("p", { text: "Nothing to search for: every reference either has a DOI or has no readable title. Nothing was sent." }));
  }
  if (truncated) panel.append(h("p", { class: "notice", text: `${truncated} more reference(s) are not shown. The demo searches at most 25 at a time.` }));
  if (unreadable.length) panel.append(h("p", { class: "notice", text: `Not searched, because no usable title could be read: ${unreadable.join(", ")}` }));
  $("results-body").prepend(panel);
  const go = $("search-go");
  if (go) go.addEventListener("click", () => doSearch(items));
}

async function doSearch(items) {
  const abort = new AbortController();
  $("search-go").disabled = true;
  $("search-cancel").hidden = false;
  $("search-cancel").addEventListener("click", () => abort.abort());
  const log = [];
  let halted = false;
  for (let i = 0; i < items.length; i++) {
    const item = items[i];
    if (halted || abort.signal.aborted) {
      log.push({ id: item.id, text: "Not searched. Nothing was sent for this reference." });
      continue;
    }
    $("search-progress").textContent = `Searching ${i + 1} of ${items.length}\u2026`;
    const outcome = await fetchCrossref(item.url, abort.signal);
    if (outcome.kind === "ok") {
      const mapped = call("api_crossref_candidates", JSON.stringify(outcome.json), item.title, item.year,
        new Date().toISOString().slice(0, 10));
      if (mapped.ok) {
        state.candidates[item.id] = mapped.candidates;
        log.push({ id: item.id, text: mapped.candidates.length ? `${mapped.candidates.length} possible match(es) are shown on its card. Nothing has been chosen.` : "Crossref returned no possible matches." });
      } else {
        log.push({ id: item.id, text: `${mapped.error.title}. ${mapped.error.message}` });
      }
    } else if (outcome.kind === "http") {
      log.push({ id: item.id, text: `Crossref answered with HTTP ${outcome.status}, so there are no suggestions.` });
    } else {
      log.push({ id: item.id, text: outcome.kind === "not_found" ? "Crossref returned no possible matches." : OUTCOME_TEXT[outcome.kind] });
      if (["rate_limited", "network", "stopped"].includes(outcome.kind)) halted = true;
    }
    if (i < items.length - 1 && !halted) await sleep(LOOKUP_GAP_MS);
  }
  state.searchLog = log;
  renderResult(state.result);
  $("results-h").textContent = "Results (with Crossref title search)";
  $("results-h").focus({ preventScroll: true });
  const first = document.querySelector(".candidates");
  if (first) first.scrollIntoView({ block: "center" });
}

/* ---------- wiring ---------- */

function init() {
  $("pyodide-version").textContent = PYODIDE_VERSION;
  $("check-form").addEventListener("submit", onSubmit);
  $("cat-input").addEventListener("change", onCatalogueFile);
  $("cat-sample").addEventListener("change", () => { $("cat-status").textContent = ""; });
  $("cat-file").addEventListener("change", () => {
    $("cat-status").textContent = state.file ? `Using ${state.file.label}.` : "Choose a file below.";
  });
  $("clear-refs").addEventListener("click", () => { $("refs").value = ""; $("refs").focus(); });
  $("retry-engine").addEventListener("click", startEngine);
  $("crossref-on").addEventListener("change", () => { if (state.result) renderLookupPanel(state.result); });
  $("search-on").addEventListener("change", () => { if (state.result) renderSearchPanel(state.result); });
  for (const button of document.querySelectorAll("[data-sample]")) {
    button.addEventListener("click", async () => {
      try {
        const response = await fetch(button.dataset.sample);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        $("refs").value = await response.text();
        $("refs").focus();
      } catch (error) {
        showResults(renderError({ title: "Could not load the example", message: error.message, hint: "", detail: "" }), "Nothing to show yet");
      }
    });
  }
  startEngine();
}

document.addEventListener("DOMContentLoaded", init);

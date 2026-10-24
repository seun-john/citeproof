/* CiteProof browser demo. Everything the student pastes is handled in this tab.
   Network use: this site's own files, Pyodide from one pinned CDN URL, and (only if the student
   turns it on and presses send) api.crossref.org. */
"use strict";

const PYODIDE_VERSION = "0.29.5";
const PYODIDE_BASE = `https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/`;
const PYODIDE_SRI = "sha384-VR47TfKeAmT7vMej7bwOVg0tHTQLLGMSIpsXtFMCZG5OpKZSIXoSLtGY//qHcxc6";
const PY_FILES = [
  "citeproof/__init__.py", "citeproof/core.py", "citeproof/references.py",
  "citeproof/bibtex.py", "citeproof/claims.py", "demo_logic.py", "text_references.py", "styles.py",
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
  online: null, // progress and log of the Crossref lookups for this result
  pyodide: null,
  styleList: [],
  styleReady: false, // the citation-style engine is loaded on first use
  checkedText: "", // exactly what was checked, so later steps use the same text
  catalogueUsed: null,
  reformat: { style: "apa", out: null, open: false },
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
    state.pyodide = pyodide;
    state.demo = pyodide.pyimport("demo_logic");
    state.styleList = JSON.parse(state.demo.api_styles());
    const info = JSON.parse(state.demo.api_info());
    $("cp-version").textContent = info.citeproof_version;
    setEngine(`Ready \u00b7 CiteProof ${info.citeproof_version} runs in this tab`, true);
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
  $("file-row").hidden = false;
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
    $("file-row").hidden = true;
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

const SECONDARY = new Set(["Catalogue searched", "Catalogue provenance", "Compared"]);

function tile(kind, name, summary, what) {
  const part = summary[kind];
  return h("li", { class: `tile ${kind}` },
    h("div", { class: "big", text: `${part.count} of ${summary.total}` }),
    h("div", { class: "pct", text: `${part.percent}%` }),
    h("div", { class: "name", text: name }),
    h("p", { class: "what", text: what }));
}

function badgeClass(verdict) {
  return verdict.toLowerCase();
}

function evidenceList(items) {
  return h("dl", { class: "evidence" }, items.map((e) => [h("dt", { text: e.label }), h("dd", { text: e.value })]));
}

function renderRow(row) {
  const main = row.evidence.filter((e) => !SECONDARY.has(e.label));
  const more = row.evidence.filter((e) => SECONDARY.has(e.label));
  return h("li", { "data-verdict": row.verdict, "data-flagged": row.flags.length ? "yes" : "no" },
    h("article", { class: `ref ${badgeClass(row.verdict)}`, "aria-label": `Reference ${row.id}` },
      h("div", { class: "ref-head" },
        h("span", { class: "ref-id", text: row.id }),
        h("span", { class: `badge ${badgeClass(row.verdict)}`, text: row.verdict }),
        row.flags.map((f) => h("span", { class: "badge flag", text: f.status })),
        row.doi_chosen ? h("span", { class: "badge needs_review", text: "DOI added by you" }) : null,
        row.from_crossref && !row.doi_chosen ? h("span", { class: "badge needs_review", text: "Crossref record" }) : null),
      h("p", { class: "ref-title", text: row.title || "(no title in your reference)" }),
      h("p", { class: `headline ${badgeClass(row.verdict)}`, text: row.headline }),
      evidenceList(main),
      row.flags.length ? h("ul", { class: "flag-list" }, row.flags.map((f) => h("li", {},
        h("strong", { text: `${f.status}: ` }), f.note || f.message))) : null,
      renderCandidates(row),
      h("details", { class: "more" },
        h("summary", { text: "Details" }),
        h("p", { class: "subhead", text: "CiteProof says" }),
        h("p", { class: "says", text: `“${row.message}”` }),
        row.flags.map((f) => h("p", { class: "says", text: `${f.status}: “${f.message}”` })),
        more.length ? [h("p", { class: "subhead", text: "More evidence" }), evidenceList(more)] : null,
        row.read ? renderRead(row.read) : null),
      h("p", { class: "person", text: row.person_note })));
}

function renderCandidates(row) {
  const found = state.candidates[row.id];
  if (!found || row.doi_chosen) return null;
  if (!found.length) {
    return h("div", { class: "candidates" }, h("p", { class: "hint", text: "Crossref's title search returned no possible matches." }));
  }
  return h("div", { class: "candidates" },
    h("p", { class: "subhead", text: "Possible DOIs from Crossref" }),
    h("p", { class: "hint", text: "Suggestions only. They may be different works with similar titles. Nothing is chosen for you." }),
    h("ul", { class: "cand-list" }, found.map((c) => h("li", {},
      h("strong", { text: c.title }), h("br"),
      `${c.authors} · ${c.year} · ${c.journal}`, h("br"),
      h("code", { text: c.doi }),
      ` · title similarity ${c.title_similarity} · year ${c.year_matches ? "matches" : "differs or was not read"}`, h("br"),
      h("button", {
        type: "button", class: "btn small", "aria-label": `Use DOI ${c.doi} for reference ${row.id} and check again`,
        "data-use-doi": c.doi, "data-ref": row.id,
      }, "Use this DOI")))));
}

function useCandidate(refId, doi) {
  const picked = (state.candidates[refId] || []).find((c) => c.doi === doi);
  if (!picked) return;
  state.overrides[refId] = doi;
  state.extra.push(picked.record);
  runCheck();
}

function renderRead(read) {
  return [
    h("p", { class: "subhead", text: "How this was read" }),
    h("p", { class: "hint" }, "Your text: ", h("q", { text: read.raw })),
    h("p", { class: "hint", text: `Layout: ${read.style}. This page's own reader, not CiteProof's. Fix the text and check again if a field is wrong.` }),
    evidenceList(read.fields),
  ];
}

function renderMissing(item) {
  return h("li", { "data-verdict": item.verdict, "data-flagged": "yes" },
    h("article", { class: "ref missing_reference", "aria-label": `Citation ${item.id}` },
      h("div", { class: "ref-head" },
        h("span", { class: "ref-id", text: item.id }),
        h("span", { class: "badge missing_reference", text: item.verdict })),
      h("p", { class: "headline", text: "Cited in the text but not in the reference list." }),
      h("details", { class: "more" },
        h("summary", { text: "Details" }),
        h("p", { class: "subhead", text: "CiteProof says" }),
        h("p", { class: "says", text: `“${item.message}”` })),
      h("p", { class: "person", text: item.person_note })));
}

function flagsLine(flags) {
  const names = {
    RETRACTED: "marked retracted by the catalogue",
    DUPLICATE: "duplicate",
    UNCITED_REFERENCE: "in the list but not cited",
    MISSING_REFERENCE: "cited but not in the list",
    RETRACTION_STATUS_NOT_SUPPLIED: "no retraction status in the catalogue",
  };
  const parts = Object.entries(flags).filter(([, n]) => n > 0).map(([k, n]) => `${n} ${names[k]}`);
  return parts.length ? `Also flagged: ${parts.join(" · ")}` : null;
}

function filterButtons(result) {
  const s = result.summary;
  const flagged = result.rows.filter((r) => r.flags.length).length + result.missing_references.length;
  const defs = [
    ["all", `All ${s.total + result.missing_references.length}`],
    ["VERIFIED", `Verified ${s.verified.count}`],
    ["METADATA_MISMATCH", `Mismatch ${s.metadata_mismatch.count}`],
    ["NEEDS_REVIEW", `No verdict ${s.no_verdict.count}`],
  ];
  if (flagged) defs.push(["flagged", `Flagged ${flagged}`]);
  return defs.map(([key, label]) => h("button", {
    type: "button", class: "chip", "data-filter": key, "aria-pressed": key === "all" ? "true" : "false",
  }, label));
}

function applyFilter(key) {
  for (const button of document.querySelectorAll("[data-filter]")) {
    button.setAttribute("aria-pressed", String(button.dataset.filter === key));
  }
  for (const item of document.querySelectorAll(".refs > li")) {
    const show = key === "all" || (key === "flagged" ? item.dataset.flagged === "yes" : item.dataset.verdict === key);
    item.hidden = !show;
  }
}

function renderResult(result) {
  const s = result.summary;
  const body = $("results-body");
  const extra = flagsLine(s.other_flags);
  const layouts = Object.entries(result.layouts_read || {}).map(([name, n]) => `${name} \u00d7${n}`).join(", ");
  const kids = [
    h("p", { class: "meta", text: `${s.total} reference${s.total === 1 ? "" : "s"} · ${result.catalogue_label} (${result.catalogue_size} records) · ${{ bibtex: "BibTeX", json: "JSON", text: "pasted text" }[result.input_format]}${layouts ? ` (${layouts})` : ""} · CiteProof ${result.citeproof_version}` }),
    h("p", { class: "banner", text: "These are comparisons, not judgements. A person must decide what each result means." }),
    h("ul", { class: "tiles", "aria-label": "Summary" },
      tile("verified", "Verified", s, "DOI found, all fields match"),
      tile("metadata_mismatch", "Mismatch", s, "DOI found, a field differs"),
      tile("no_verdict", "No verdict", s, "No DOI, or not in this catalogue")),
    h("div", { class: "bar", "aria-hidden": "true" }, ["verified", "metadata_mismatch", "no_verdict"].map((k) => {
      const seg = h("span", { class: k });
      seg.style.flexGrow = String(s[k].count);
      return seg;
    })),
    s.metadata_mismatch.only_given_names ? h("p", { class: "flags-line", text: `${s.metadata_mismatch.only_given_names} of the ${s.metadata_mismatch.count} mismatch${s.metadata_mismatch.count === 1 ? "" : "es"} differ only in how given names are written (initials or full names).` }) : null,
    extra ? h("p", { class: "flags-line", text: extra }) : null,
    h("details", { class: "legend how" },
      h("summary", { text: "What do these mean?" }),
      h("ul", {},
        h("li", {}, h("code", { text: "VERIFIED" }), " the DOI is in the catalogue and title, authors, year and journal all match."),
        h("li", {}, h("code", { text: "METADATA_MISMATCH" }), " the DOI is in the catalogue but a field differs or is missing."),
        h("li", {}, h("code", { text: "NEEDS_REVIEW" }), " no DOI, or the DOI is not in this catalogue. It says nothing about whether the reference is real."))),
    renderReformatPanel(),
    result.notices.length ? h("details", { class: "notes" },
      h("summary", { text: `Notes (${result.notices.length})` }),
      result.notices.map((n) => h("p", { text: n }))) : null,
    h("div", { class: "toolbar" },
      h("div", { class: "filters", role: "group", "aria-label": "Show" }, filterButtons(result)),
      h("div", { class: "exports" },
        h("button", { type: "button", class: "btn small", id: "dl-csv" }, "Download CSV"),
        h("button", { type: "button", class: "btn small", id: "dl-json" }, "Download report (JSON)"))),
    h("ol", { class: "refs" }, result.rows.map(renderRow), result.missing_references.map(renderMissing)),
  ];
  body.replaceChildren(...kids.filter(Boolean));
  $("dl-csv").addEventListener("click", () => download("citeproof-results.csv", "text/csv", "﻿" + call("api_csv", JSON.stringify(result)).csv));
  $("dl-json").addEventListener("click", () => download("citeproof-report.json", "application/json", JSON.stringify(result.report, null, 2)));
  for (const button of body.querySelectorAll("[data-filter]")) {
    button.addEventListener("click", () => applyFilter(button.dataset.filter));
  }
  for (const button of body.querySelectorAll("[data-use-doi]")) {
    button.addEventListener("click", () => useCandidate(button.dataset.ref, button.dataset.useDoi));
  }
  renderOnlinePanel();
  wireReformat();
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

function runCheck({ focus = true } = {}) {
  const catalogue = state.catalogueUsed;
  if (!catalogue) {
    showResults(renderError({
      title: "No catalogue file chosen",
      message: "“My own catalogue file” is selected but no file has been loaded.",
      hint: "Choose a CSV or JSON file above, or select the sample catalogue.", detail: "",
    }), "Nothing to show yet");
    return null;
  }
  const out = call("api_check", state.checkedText, JSON.stringify(catalogue.records), catalogue.label,
    state.extra.length ? JSON.stringify(state.extra) : "",
    Object.keys(state.overrides).length ? JSON.stringify(state.overrides) : "");
  if (!out.ok) {
    state.result = null;
    showResults(renderError(out.error), "Nothing to show yet");
    return null;
  }
  state.result = out;
  renderResult(out);
  if (focus) showResults(null);
  return out;
}

async function onSubmit(event) {
  event.preventDefault();
  if (!state.demo) return;
  state.online = null;
  state.extra = [];
  state.overrides = {};
  state.candidates = {};
  state.reformat.out = null;
  state.checkedText = $("refs").value;
  state.catalogueUsed = chosenCatalogue();
  const first = runCheck();
  if (first) await runOnline();
}

/* ---------- Crossref lookups (on by default, switchable) ---------- */

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
  stopped: "Stopped by you.",
};
const STOPPERS = ["rate_limited", "network", "stopped"];

function setProgress(text) {
  const node = $("online-progress");
  if (node) node.textContent = text;
}

/* One run: DOI lookups first (they can change the result), then title searches. */
async function runOnline() {
  const doiOn = $("crossref-on").checked;
  const searchOn = $("search-on").checked;
  if (!state.demo || !state.result || (!doiOn && !searchOn)) return;
  const abort = new AbortController();
  state.lookupAbort = abort;
  state.online = { running: true, log: [], sent: [] };
  renderResult(state.result);
  let halted = false;

  const doiItems = doiOn ? state.result.lookup.items : [];
  for (let i = 0; i < doiItems.length; i++) {
    const { doi, url } = doiItems[i];
    if (halted || abort.signal.aborted) {
      state.online.log.push({ who: doi, text: "Not looked up. Nothing was sent for this DOI." });
      continue;
    }
    setProgress(`Looking up DOI ${i + 1} of ${doiItems.length}…`);
    state.online.sent.push(url);
    const outcome = await fetchCrossref(url, abort.signal);
    if (outcome.kind === "ok") {
      const mapped = call("api_crossref_record", JSON.stringify(outcome.json), new Date().toISOString().slice(0, 10));
      if (mapped.ok) {
        state.extra.push(mapped.record);
        state.online.log.push({ who: doi, text: "Crossref returned a record. It was added to the comparison for this run." });
      } else {
        state.online.log.push({ who: doi, text: `${mapped.error.title}. ${mapped.error.message}` });
      }
    } else if (outcome.kind === "http") {
      state.online.log.push({ who: doi, text: `Crossref answered with HTTP ${outcome.status}, so nothing was added.` });
    } else {
      state.online.log.push({ who: doi, text: OUTCOME_TEXT[outcome.kind] });
      if (STOPPERS.includes(outcome.kind)) halted = true;
    }
    if (i < doiItems.length - 1 && !halted) await sleep(LOOKUP_GAP_MS);
  }
  if (state.extra.length) runCheck({ focus: false });

  const searchItems = searchOn ? state.result.search.items : [];
  for (let i = 0; i < searchItems.length; i++) {
    const item = searchItems[i];
    if (halted || abort.signal.aborted) {
      state.online.log.push({ who: item.id, text: "Not searched. Nothing was sent for this reference." });
      continue;
    }
    setProgress(`Searching for a DOI ${i + 1} of ${searchItems.length}…`);
    state.online.sent.push(item.url);
    const outcome = await fetchCrossref(item.url, abort.signal);
    if (outcome.kind === "ok") {
      const mapped = call("api_crossref_candidates", JSON.stringify(outcome.json), item.title, item.year,
        new Date().toISOString().slice(0, 10));
      if (mapped.ok) {
        state.candidates[item.id] = mapped.candidates;
        state.online.log.push({ who: item.id, text: mapped.candidates.length ? `${mapped.candidates.length} possible DOI${mapped.candidates.length === 1 ? " is" : "s are"} shown on its card. Nothing has been chosen.` : "Crossref returned no possible matches." });
      } else {
        state.online.log.push({ who: item.id, text: `${mapped.error.title}. ${mapped.error.message}` });
      }
    } else if (outcome.kind === "http") {
      state.online.log.push({ who: item.id, text: `Crossref answered with HTTP ${outcome.status}, so there are no suggestions.` });
    } else {
      state.online.log.push({ who: item.id, text: outcome.kind === "not_found" ? "Crossref returned no possible matches." : OUTCOME_TEXT[outcome.kind] });
      if (STOPPERS.includes(outcome.kind)) halted = true;
    }
    if (i < searchItems.length - 1 && !halted) await sleep(LOOKUP_GAP_MS);
  }
  state.lookupAbort = null;
  state.online.running = false;
  state.online.halted = halted;
  renderResult(state.result);
}

function renderOnlinePanel() {
  const old = $("online-panel");
  if (old) old.remove();
  const online = state.online;
  if (!online) return;
  const panel = h("section", { class: "lookup", id: "online-panel", "aria-labelledby": "online-h" });
  panel.append(h("h3", { id: "online-h", text: online.running ? "Looking things up on Crossref…" : "Crossref lookups" }));
  if (online.running) {
    panel.append(
      h("p", { id: "online-progress", class: "hint", role: "status", "aria-live": "polite", text: "Starting…" }),
      h("button", { type: "button", class: "btn small", id: "online-stop" }, "Stop"));
  } else if (!online.log.length) {
    panel.append(h("p", { class: "hint", text: "Nothing needed looking up. Nothing was sent." }));
  } else {
    panel.append(h("ul", {}, online.log.map((l) => h("li", {}, h("code", { text: l.who }), ` — ${l.text}`))));
    if (online.sent.length) {
      panel.append(h("details", { class: "how" },
        h("summary", { text: `Exactly what was sent (${online.sent.length} request${online.sent.length === 1 ? "" : "s"})` }),
        h("ul", {}, online.sent.map((u) => h("li", {}, h("code", { text: u }))))));
    }
    if (online.halted) {
      panel.append(h("button", { type: "button", class: "btn small", id: "online-retry" }, "Try the lookups again"));
    }
  }
  const { truncated } = state.result.lookup;
  if (!online.running && (truncated || state.result.search.truncated)) {
    panel.append(h("p", { class: "notice", text: "The demo looks up at most 25 at a time. Check a smaller batch for the rest." }));
  }
  $("results-body").prepend(panel);
  const stop = $("online-stop");
  if (stop) stop.addEventListener("click", () => state.lookupAbort && state.lookupAbort.abort());
  const retry = $("online-retry");
  if (retry) retry.addEventListener("click", () => runOnline());
}

/* ---------- reformat into another citation style ---------- */

async function ensureStyleEngine() {
  if (state.styleReady) return;
  await state.pyodide.loadPackage("lxml"); // needed by the style engine, loaded only when used
  const manifest = await (await fetch("py/engine-files.json")).json();
  const jobs = [
    ...manifest.engine.map((file) => ({ from: `py/${file}`, to: `/app/${file}` })),
    ...manifest.csl.map((file) => ({ from: `csl/${file}`, to: `/app/csl/${file}` })),
  ];
  for (const job of jobs) {
    const response = await fetch(job.from);
    if (!response.ok) throw new Error(`${job.from} returned HTTP ${response.status}`);
    const dir = job.to.slice(0, job.to.lastIndexOf("/"));
    state.pyodide.FS.mkdirTree(dir);
    state.pyodide.FS.writeFile(job.to, await response.text());
  }
  state.styleReady = true;
}

function setReformatStatus(text) {
  const node = $("reformat-status");
  if (node) node.textContent = text;
}

async function doReformat() {
  const style = $("style-pick").value;
  const button = $("reformat-go");
  button.disabled = true;
  try {
    setReformatStatus(state.styleReady ? "Formatting…" : "Loading the citation style engine (about 3 MB, once)…");
    await ensureStyleEngine();
    const catalogue = state.catalogueUsed;
    const out = call("api_reformat", state.checkedText, JSON.stringify(catalogue.records),
      state.extra.length ? JSON.stringify(state.extra) : "",
      Object.keys(state.overrides).length ? JSON.stringify(state.overrides) : "", style);
    state.reformat = { style, out, open: true, error: out.ok ? null : out.error };
  } catch (error) {
    console.error(error);
    state.reformat = { style, out: null, open: true, error: { title: "The style engine could not be loaded", message: error.message, hint: "Check your connection and try again. Nothing you pasted was sent anywhere.", detail: "" } };
  }
  renderResult(state.result);
  $("reformat-h")?.focus();
}

function formattedHtml(out) {
  const esc = (t) => t.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  return out.entries.map((e) => `<p>${e.segments.map((seg) => {
    let t = esc(seg.text);
    if (seg.italic) t = `<i>${t}</i>`;
    if (seg.bold) t = `<b>${t}</b>`;
    return t;
  }).join("")}</p>`).join("");
}

async function copyFormatted(out) {
  const text = out.entries.map((e) => e.text).join("\n");
  try {
    if (window.ClipboardItem) {
      await navigator.clipboard.write([new ClipboardItem({
        "text/html": new Blob([formattedHtml(out)], { type: "text/html" }),
        "text/plain": new Blob([text], { type: "text/plain" }),
      })]);
    } else {
      await navigator.clipboard.writeText(text);
    }
    setReformatStatus("Copied. Italics are kept when you paste into Word or Google Docs.");
  } catch (error) {
    setReformatStatus("Could not copy automatically. Use Download instead.");
  }
}

function renderFormatted(out) {
  const verdicts = Object.fromEntries(state.result.rows.map((r) => [r.id, r.verdict]));
  return h("div", { class: "formatted" },
    h("h3", { id: "reformat-h", tabindex: "-1", text: `${out.style}: ${out.entries.length} reference${out.entries.length === 1 ? "" : "s"}` }),
    h("p", { class: "hint", text: out.caveats.find((c) => c.startsWith("Formatted automatically")) || "" }),
    out.entries.length ? h("div", { class: "exports" },
      h("button", { type: "button", class: "btn small", id: "copy-formatted" }, "Copy all"),
      h("button", { type: "button", class: "btn small", id: "download-formatted" }, "Download (.txt)")) : null,
    h("ul", { class: "bib" }, out.entries.map((e) => h("li", {},
      h("p", { class: "bib-entry" }, e.segments.map((seg) => {
        if (seg.italic) return h("i", { text: seg.text });
        if (seg.bold) return h("b", { text: seg.text });
        return seg.text;
      })),
      h("p", { class: "bib-meta" },
        verdicts[e.id] ? h("span", { class: `badge ${badgeClass(verdicts[e.id])}`, text: verdicts[e.id] }) : null,
        e.notes.length ? ` ${e.notes.join(" ")}` : ""),
    ))),
    out.skipped.length ? h("details", { class: "how", open: true },
      h("summary", { text: `Not formatted (${out.skipped.length})` }),
      h("ul", {}, out.skipped.map((k) => h("li", {}, h("code", { text: k.id }), ` — ${k.reason}.`)))) : null,
    h("details", { class: "how" },
      h("summary", { text: "Things to check" }),
      h("ul", {}, out.caveats.map((c) => h("li", { text: c })))));
}

function renderReformatPanel() {
  const rf = state.reformat;
  const select = h("select", { id: "style-pick", class: "select" },
    state.styleList.map((st) => h("option", { value: st.id, selected: st.id === rf.style }, st.label)));
  const panel = h("details", { class: "reformat how", id: "reformat" },
    h("summary", { text: "Reformat these references into another style" }),
    h("div", { class: "reformat-controls" },
      h("label", { for: "style-pick", text: "Style" }), select,
      h("button", { type: "button", class: "btn small", id: "reformat-go" }, "Reformat")),
    h("p", { id: "reformat-status", class: "hint", role: "status", "aria-live": "polite" }),
    rf.error ? renderError(rf.error) : null,
    rf.out ? renderFormatted(rf.out) : null);
  panel.open = Boolean(rf.open);
  panel.addEventListener("toggle", () => { state.reformat.open = panel.open; });
  return panel;
}

function wireReformat() {
  const go = $("reformat-go");
  if (go) go.addEventListener("click", doReformat);
  const out = state.reformat.out;
  const copy = $("copy-formatted");
  if (copy && out) copy.addEventListener("click", () => copyFormatted(out));
  const dl = $("download-formatted");
  if (dl && out) dl.addEventListener("click", () => download(`citeproof-references-${out.style_id}.txt`, "text/plain", out.entries.map((e) => e.text).join("\r\n") + "\r\n"));
  const pick = $("style-pick");
  if (pick) pick.addEventListener("change", () => { state.reformat.style = pick.value; });
}

/* ---------- wiring ---------- */

function init() {
  $("pyodide-version").textContent = PYODIDE_VERSION;
  $("check-form").addEventListener("submit", onSubmit);
  $("cat-input").addEventListener("change", onCatalogueFile);
  const syncCatalogueChoice = () => {
    const mine = $("cat-file").checked;
    $("file-row").hidden = !mine;
    $("cat-status").textContent = mine && state.file ? `Using ${state.file.label}.` : "";
  };
  $("cat-sample").addEventListener("change", syncCatalogueChoice);
  $("cat-file").addEventListener("change", syncCatalogueChoice);
  $("clear-refs").addEventListener("click", () => { $("refs").value = ""; $("refs").focus(); });
  $("retry-engine").addEventListener("click", startEngine);
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

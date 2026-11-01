() => {
  const out = [];
  const visible = (e) => {
    const r = e.getBoundingClientRect();
    const s = getComputedStyle(e);
    return r.width > 0 && r.height > 0 && s.visibility !== "hidden"
      && s.display !== "none" && s.opacity !== "0";
  };
  const selector = "button, summary, select, input:not([type=hidden]), label[for], a[href]";
  for (const e of document.querySelectorAll(selector)) {
    if (!visible(e)) continue;
    // A tick-box or radio is operated through its label, which is what must be large.
    if (e.matches("input[type=radio], input[type=checkbox]") && e.labels.length) continue;
    if (e.tagName === "A" && e.closest("p, li")) continue; // links inside a sentence
    if (e.tagName === "LABEL" && e.closest(".choice, .segmented") === null) continue;
    const r = e.getBoundingClientRect();
    if (r.height < 43.5) {
      const name = (e.textContent || "").trim().slice(0, 30);
      out.push([e.tagName.toLowerCase(), e.id || e.className || "", name, Math.round(r.height)]);
    }
  }
  return out;
}

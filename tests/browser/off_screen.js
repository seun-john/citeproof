(sel) => [...document.querySelectorAll(sel)]
  .filter((e) => {
    const r = e.getBoundingClientRect();
    return r.width > 0 && r.right > innerWidth + 0.5;
  })
  .map((e) => (e.className || e.tagName) + ":" + Math.round(e.getBoundingClientRect().right))

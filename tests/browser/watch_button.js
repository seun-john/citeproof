() => {
  window.__labels = [];
  const button = document.getElementById("check-btn");
  new MutationObserver(() => window.__labels.push(button.textContent))
    .observe(button, { childList: true, characterData: true, subtree: true });
}

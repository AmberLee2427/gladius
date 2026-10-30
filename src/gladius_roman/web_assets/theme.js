/* Shared by the run builder and acknowledgements page; no network access. */
(() => {
  const key = "gladius-theme";
  const system = window.matchMedia("(prefers-color-scheme: dark)");
  let preference = null;
  try {
    const saved = localStorage.getItem(key);
    if (saved === "dark" || saved === "light") preference = saved;
  } catch {
    /* Storage can be unavailable; the toggle still works for this page. */
  }
  function apply() {
    const dark = (preference || (system.matches ? "dark" : "light")) === "dark";
    document.documentElement.dataset.theme = dark ? "dark" : "light";
    const button = document.getElementById("themeToggle");
    if (button) {
      button.textContent = dark ? "Light mode" : "Dark mode";
      button.setAttribute("aria-pressed", String(dark));
    }
  }
  apply();
  system.addEventListener("change", () => {
    if (preference === null) apply();
  });
  document.addEventListener("DOMContentLoaded", () => {
    const button = document.getElementById("themeToggle");
    if (button)
      button.addEventListener("click", () => {
        preference =
          document.documentElement.dataset.theme === "dark" ? "light" : "dark";
        try {
          localStorage.setItem(key, preference);
        } catch {
          /* Keep the in-memory choice. */
        }
        apply();
      });
    apply();
  });
})();

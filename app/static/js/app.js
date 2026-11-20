
(() => {
  const toggle = document.querySelector(".sidebar-toggle");
  const sidebar = document.querySelector("#app-sidebar");

  if (!toggle || !sidebar) return;

  const storageKey = "qms-lis-sidebar-collapsed";

  const setCollapsed = (collapsed, persist = true) => {
    document.body.classList.toggle("sidebar-collapsed", collapsed);
    toggle.setAttribute("aria-expanded", String(!collapsed));
    toggle.setAttribute(
      "aria-label",
      collapsed ? "แสดงเมนูหลัก" : "ซ่อนเมนูหลัก",
    );
    sidebar.setAttribute("aria-hidden", String(collapsed));
    sidebar.inert = collapsed;

    if (persist) {
      try {
        window.localStorage.setItem(storageKey, String(collapsed));
      } catch {
        // The control still works when browser storage is unavailable.
      }
    }
  };

  let collapsed = false;
  try {
    collapsed = window.localStorage.getItem(storageKey) === "true";
  } catch {
    collapsed = false;
  }
  setCollapsed(collapsed, false);

  toggle.addEventListener("click", () => {
    setCollapsed(!document.body.classList.contains("sidebar-collapsed"));
  });
})();

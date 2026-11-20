
(() => {
  const loading = document.querySelector("#interaction-loading");
  const success = document.querySelector("#interaction-success");
  const successTitle = document.querySelector("#interaction-success-title");
  const successDetail = document.querySelector("#interaction-success-detail");
  const messages = {
    "patient-created": ["ลงทะเบียนผู้ป่วยเสร็จสิ้น", "HN "],
    "patient-updated": ["แก้ไขข้อมูลผู้ป่วยเสร็จสิ้น", ""],
    "order-created": ["สร้างคำสั่งตรวจเสร็จสิ้น", "เลข Order "],
    "specimen-collected": ["บันทึกการเก็บสิ่งส่งตรวจแล้ว", ""],
    "specimen-rejected": ["ปฏิเสธสิ่งส่งตรวจแล้ว", ""],
    "specimen-received": ["รับสิ่งส่งตรวจเสร็จสิ้น", "Accession "],
    "result-verified": ["ตรวจสอบผลเสร็จสิ้น", ""],
    "result-rejected": ["ส่งผลกลับแก้ไขแล้ว", ""],
    "results-released": ["เผยแพร่ผลตรวจเสร็จสิ้น", ""],
    "results-saved": ["บันทึกผลตรวจเสร็จสิ้น", ""],
  };
  const params = new URLSearchParams(window.location.search);
  const successCode = params.get("success");
  if (success && messages[successCode]) {
    const [title, detailPrefix] = messages[successCode];
    successTitle.textContent = title;
    const detailValue = successCode === "patient-created" ? params.get("hn")
      : successCode === "order-created" ? params.get("order_number")
        : successCode === "specimen-received" ? params.get("accession") : "";
    successDetail.textContent = detailValue ? `${detailPrefix}${detailValue}` : "";
    success.classList.add("is-visible");
    success.setAttribute("aria-hidden", "false");
    window.setTimeout(() => {
      success.classList.remove("is-visible");
      success.setAttribute("aria-hidden", "true");
      if (successCode === "results-saved") {
        window.location.replace("/worklist?queue=results");
      }
    }, 1500);
    params.delete("success");
    params.delete("hn");
    params.delete("order_number");
    params.delete("accession");
    const query = params.toString();
    window.history.replaceState({}, "", `${window.location.pathname}${query ? `?${query}` : ""}${window.location.hash}`);
  }

  document.querySelectorAll('form[method="post"], form[method="POST"]').forEach((form) => {
    form.addEventListener("submit", (event) => {
      if (event.defaultPrevented || !form.checkValidity()) return;
      if (form.dataset.allowRepeat === "true") return;
      const submitter = event.submitter;
      if (submitter) {
        submitter.dataset.originalLabel = submitter.textContent;
        submitter.textContent = "กำลังดำเนินการ...";
        submitter.disabled = true;
      }
      if (loading) {
        loading.classList.add("is-visible");
        loading.setAttribute("aria-hidden", "false");
      }
    });
  });

  ["national_id", "phone_number"].forEach((fieldId) => {
    const field = document.getElementById(fieldId);
    if (!field || field.readOnly) return;
    field.addEventListener("input", () => {
      field.value = field.value.replace(/\D/g, "").slice(0, fieldId === "national_id" ? 13 : 10);
    });
  });

  ["first_name_en", "last_name_en"].forEach((fieldId) => {
    const field = document.getElementById(fieldId);
    if (!field) return;
    field.addEventListener("input", () => {
      if (field.value) field.value = field.value[0].toUpperCase() + field.value.slice(1);
    });
  });

  const titleChoice = document.querySelector("#title_option");
  const customTitleWrap = document.querySelector("#title_custom_wrap");
  if (titleChoice && customTitleWrap) {
    titleChoice.addEventListener("change", () => {
      customTitleWrap.hidden = titleChoice.value !== "__OTHER__";
    });
  }

  const createdId = params.get("created_id");
  if (createdId) {
    document.querySelector(`#patient-${CSS.escape(createdId)}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
    params.delete("created_id");
    const query = params.toString();
    window.history.replaceState({}, "", `${window.location.pathname}${query ? `?${query}` : ""}`);
  }

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

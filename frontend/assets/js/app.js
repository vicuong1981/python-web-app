// Frontend behaviour: talks to the FastAPI JSON API under /api.
(() => {
  const $ = (id) => document.getElementById(id);
  const el = (tag, props = {}, ...children) => {
    const node = Object.assign(document.createElement(tag), props);
    node.append(...children);
    return node;
  };

  // A stable per-browser id, so percentage rollouts stay sticky for this visitor.
  let userId = "anonymous";
  try {
    userId = localStorage.getItem("userId") || crypto.randomUUID();
    localStorage.setItem("userId", userId);
  } catch (_) { /* storage blocked: stay anonymous */ }
  const headers = { "Content-Type": "application/json", "X-User-Id": userId };
  const api = (path, opts = {}) => fetch(path, { ...opts, headers: { ...headers, ...(opts.headers || {}) } });
  const send = (path, method, body) => api(path, { method, body: JSON.stringify(body) });

  const state = {
    maxLength: 500,
    notes: [],
    categories: [],
    tags: [],
    selected: new Set(),
    filter: { tag: null, categoryId: "", q: "" },
    editing: null,
    shareIds: [],
    share: null,
  };

  const parseTags = (s) => s.split(",").map((t) => t.trim()).filter(Boolean);
  const categoryName = (id) => state.categories.find((c) => c.id === id)?.name;

  async function errorText(r, fallback) {
    const body = await r.json().catch(() => ({}));
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail) && body.detail[0]?.msg) return body.detail[0].msg.replace(/^Value error, /, "");
    return fallback;
  }

  // ---------- flags & status ----------
  // Banner text comes from the site-banner flag. Dismissing hides that exact
  // text in this browser; a new message shows up again.
  function showBanner(text) {
    const banner = $("site-banner");
    if (!banner || !text) return;
    let dismissed = null;
    try { dismissed = localStorage.getItem("dismissedBanner"); } catch (_) { /* ignore */ }
    if (dismissed === text) return;
    $("site-banner-text").textContent = text;
    banner.hidden = false;
    $("site-banner-close").onclick = () => {
      banner.hidden = true;
      try { localStorage.setItem("dismissedBanner", text); } catch (_) { /* ignore */ }
    };
  }

  // Right-hand ad slot, from the sidebar-ad flag: "off" (or missing) hides it,
  // "house" shows the built-in banner, an Elfsight widget ID loads that widget.
  function showSidebarAd(value) {
    const aside = $("sidebar-ad");
    if (!aside || !value || value === "off") return;
    if (value === "house") {
      $("sidebar-ad-house").hidden = false;
    } else {
      const slot = $("sidebar-ad-elfsight");
      const widget = document.createElement("div");
      widget.className = `elfsight-app-${value}`;
      widget.setAttribute("data-elfsight-app-lazy", "");
      slot.replaceChildren(widget);
      const script = document.createElement("script");
      script.src = "https://elfsightcdn.com/platform.js";
      script.async = true;
      document.body.append(script);
    }
    aside.hidden = false;
    // Widen the whole page (header, banner, content, footer) together.
    document.body.classList.add("with-aside");
  }

  async function loadFlags() {
    try {
      const { flags } = await (await api("/api/flags")).json();
      showBanner(flags["site-banner"]);
      showSidebarAd(flags["sidebar-ad"]);
      state.maxLength = flags["max-note-length"];
      if (flags["new-homepage"] && $("hero")) {
        $("hero").hidden = false;
        $("classic-intro").hidden = true;
      }
    } catch (_) { /* flags unavailable: keep defaults */ }
  }

  async function loadStatus() {
    try {
      const h = await (await fetch("/health")).json();
      $("status").textContent = `API ${h.status}, flags: ${h.flags}`;
    } catch (_) {
      $("status").textContent = "API unreachable";
    }
  }

  // ---------- categories ----------
  function fillCategorySelects() {
    for (const sel of document.querySelectorAll(".category-select")) {
      const current = sel.value;
      sel.replaceChildren();
      if (sel.dataset.all) sel.append(el("option", { value: "", textContent: sel.dataset.all }));
      else if (sel.dataset.placeholder) sel.append(el("option", { value: "", textContent: sel.dataset.placeholder }));
      else sel.append(el("option", { value: "", textContent: "No category" }));
      if (sel.dataset.placeholder) sel.append(el("option", { value: "none", textContent: "No category" }));
      for (const c of state.categories) sel.append(el("option", { value: String(c.id), textContent: c.name }));
      if ([...sel.options].some((o) => o.value === current)) sel.value = current;
    }
  }

  function renderCategories() {
    const list = $("category-list");
    list.replaceChildren();
    if (!state.categories.length) list.append(el("span", { className: "muted", textContent: "No categories yet." }));
    for (const c of state.categories) {
      const del = el("button", { className: "chip-x", type: "button", textContent: "×", title: `Delete ${c.name}` });
      del.setAttribute("aria-label", `Delete category ${c.name}`);
      del.onclick = async () => {
        if (!confirm(`Delete the category "${c.name}"? Its notes are kept.`)) return;
        await api(`/api/categories/${c.id}`, { method: "DELETE" });
        if (state.filter.categoryId === String(c.id)) state.filter.categoryId = "";
        refresh();
      };
      list.append(el("span", { className: "chip category" }, `${c.name} `, el("small", { textContent: c.note_count }), del));
    }
    fillCategorySelects();
  }

  async function addCategory(e) {
    e.preventDefault();
    const err = $("category-error");
    err.hidden = true;
    const r = await send("/api/categories", "POST", { name: $("category-name").value });
    if (r.ok) {
      $("category-name").value = "";
      refresh();
    } else {
      err.textContent = await errorText(r, "Couldn't add the category.");
      err.hidden = false;
    }
  }

  // ---------- tags ----------
  function renderTagFilters() {
    const box = $("tag-filters");
    box.replaceChildren();
    for (const { tag, count } of state.tags) {
      const active = state.filter.tag === tag;
      const b = el("button", { type: "button", className: `chip tag${active ? " active" : ""}`, textContent: `#${tag} ${count}` });
      b.setAttribute("aria-pressed", String(active));
      b.onclick = () => { state.filter.tag = active ? null : tag; loadNotes(); };
      box.append(b);
    }
    $("tag-suggestions").replaceChildren(...state.tags.map(({ tag }) => el("option", { value: tag })));
  }

  // ---------- notes ----------
  function noteMeta(note) {
    const meta = el("div", { className: "note-meta" });
    const cat = categoryName(note.category_id);
    if (cat) meta.append(el("span", { className: "chip category small", textContent: cat }));
    for (const t of note.tags) {
      const b = el("button", { type: "button", className: "chip tag small", textContent: `#${t}` });
      b.onclick = () => { state.filter.tag = t; loadNotes(); };
      meta.append(b);
    }
    return meta;
  }

  function editForm(note) {
    const text = el("textarea", { rows: 3, value: note.text });
    const tags = el("input", { type: "text", value: note.tags.join(", "), placeholder: "Tags, comma separated" });
    tags.setAttribute("list", "tag-suggestions");
    const cat = el("select", { className: "category-select" });
    const err = el("p", { className: "error", hidden: true });
    const save = el("button", { type: "submit", textContent: "Save" });
    const cancel = el("button", { type: "button", className: "secondary", textContent: "Cancel" });
    cancel.onclick = () => { state.editing = null; renderNotes(); };
    const form = el("form", { className: "edit-form" }, text, el("div", { className: "field-row" }, tags, cat), err,
      el("div", { className: "form-row" }, el("span"), el("span", {}, cancel, " ", save)));
    form.onsubmit = async (e) => {
      e.preventDefault();
      const r = await send(`/api/notes/${note.id}`, "PATCH", {
        text: text.value,
        tags: parseTags(tags.value),
        category_id: cat.value ? Number(cat.value) : null,
      });
      if (r.ok) { state.editing = null; refresh(); }
      else { err.textContent = await errorText(r, "Couldn't save."); err.hidden = false; }
    };
    queueMicrotask(() => {
      fillCategorySelects();
      cat.value = note.category_id ? String(note.category_id) : "";
      text.focus();
    });
    return form;
  }

  function renderNotes() {
    const list = $("notes");
    list.replaceChildren();
    for (const note of state.notes) {
      const box = el("input", { type: "checkbox", checked: state.selected.has(note.id) });
      box.setAttribute("aria-label", "Select note");
      box.onchange = () => {
        box.checked ? state.selected.add(note.id) : state.selected.delete(note.id);
        renderBulkBar();
      };
      const body = el("div", { className: "note-body" });
      if (state.editing === note.id) {
        body.append(editForm(note));
      } else {
        body.append(el("p", { className: "note-text", textContent: note.text }), noteMeta(note));
      }
      const edit = el("button", { type: "button", className: "link", textContent: "Edit" });
      edit.onclick = () => { state.editing = note.id; renderNotes(); };
      const share = el("button", { type: "button", className: "link", textContent: "Share" });
      share.onclick = () => openShare([note.id]);
      const del = el("button", { type: "button", className: "link danger-link", textContent: "Delete" });
      del.onclick = async () => { await api(`/api/notes/${note.id}`, { method: "DELETE" }); state.selected.delete(note.id); refresh(); };
      const actions = state.editing === note.id ? el("div") : el("div", { className: "note-actions" }, edit, share, del);
      list.append(el("li", { className: state.selected.has(note.id) ? "selected" : "" }, box, body, actions));
    }
    const filtered = state.filter.tag || state.filter.categoryId || state.filter.q;
    $("notes-empty").textContent = filtered ? "No notes match these filters." : ($("notes-empty").dataset.emptyText || "No notes yet.");
    $("notes-empty").hidden = state.notes.length > 0;
    $("notes-count").textContent = state.notes.length ? `${state.notes.length} shown` : "";
    renderBulkBar();
  }

  function renderBulkBar() {
    // Drop selections that are no longer visible.
    const visible = new Set(state.notes.map((n) => n.id));
    for (const id of state.selected) if (!visible.has(id)) state.selected.delete(id);
    const n = state.selected.size;
    $("bulk-bar").hidden = state.notes.length === 0;
    $("selected-count").textContent = n ? `${n} selected` : "Select all";
    $("select-all").checked = n > 0 && n === state.notes.length;
    $("select-all").indeterminate = n > 0 && n < state.notes.length;
    for (const b of document.querySelectorAll("[data-bulk]")) b.disabled = n === 0;
    $("bulk-category").disabled = n === 0;
    for (const li of $("notes").children) {
      const box = li.querySelector("input[type=checkbox]");
      li.classList.toggle("selected", box.checked);
    }
  }

  async function loadNotes() {
    const params = new URLSearchParams();
    if (state.filter.tag) params.set("tag", state.filter.tag);
    if (state.filter.categoryId) params.set("category_id", state.filter.categoryId);
    if (state.filter.q) params.set("q", state.filter.q);
    const r = await api(`/api/notes${params.size ? `?${params}` : ""}`);
    const off = r.status === 503;
    $("notes-unavailable").hidden = !off;
    for (const b of document.querySelectorAll("form button[type=submit]")) b.disabled = off;
    state.notes = r.ok ? await r.json() : [];
    renderTagFilters();
    renderNotes();
  }

  async function refresh() {
    const [cats, tags] = await Promise.all([api("/api/categories"), api("/api/tags")]);
    state.categories = cats.ok ? await cats.json() : [];
    state.tags = tags.ok ? await tags.json() : [];
    if (state.filter.tag && !state.tags.some((t) => t.tag === state.filter.tag)) state.filter.tag = null;
    renderCategories();
    $("filter-category").value = state.filter.categoryId;
    await loadNotes();
  }

  function updateCount() {
    $("char-count").textContent = `${$("note-text").value.length} / ${state.maxLength}`;
  }

  async function saveNote(e) {
    e.preventDefault();
    const err = $("form-error");
    err.hidden = true;
    const category = $("note-category").value;
    const r = await send("/api/notes", "POST", {
      text: $("note-text").value,
      tags: parseTags($("note-tags").value),
      category_id: category ? Number(category) : null,
    });
    if (r.ok) {
      $("note-text").value = "";
      $("note-tags").value = "";
      updateCount();
      refresh();
    } else {
      err.textContent = await errorText(r, "Couldn't save the note.");
      err.hidden = false;
    }
  }

  // ---------- bulk actions ----------
  async function bulk(action, extra = {}) {
    const r = await send("/api/notes/bulk", "POST", { ids: [...state.selected], action, ...extra });
    if (!r.ok) { alert(await errorText(r, "That didn't work.")); return; }
    if (action === "delete") state.selected.clear();
    refresh();
  }

  async function onBulkClick(e) {
    const action = e.target.dataset.bulk;
    const n = state.selected.size;
    if (!action || !n) return;
    if (action === "share") return openShare([...state.selected]);
    if (action === "delete") {
      if (confirm(`Delete ${n} note${n > 1 ? "s" : ""}?`)) bulk("delete");
      return;
    }
    const verb = action === "add_tags" ? "add to" : "remove from";
    const input = prompt(`Tags to ${verb} ${n} note${n > 1 ? "s" : ""} (comma separated):`);
    if (input && parseTags(input).length) bulk(action, { tags: parseTags(input) });
  }

  function onBulkCategory(e) {
    const v = e.target.value;
    if (!v) return;
    bulk("set_category", { category_id: v === "none" ? null : Number(v) });
    e.target.value = "";
  }

  // ---------- sharing ----------
  async function openShare(ids) {
    state.shareIds = ids;
    $("share-summary").textContent = ids.length === 1 ? "Sharing 1 note." : `Sharing ${ids.length} notes.`;
    $("share-dialog").showModal();
  }

  async function buildShare() {
    const to = $("share-to").value.trim();
    const r = await send("/api/notes/share", "POST", { ids: state.shareIds, to: to || null });
    if (!r.ok) { alert(await errorText(r, "Couldn't prepare the email.")); return null; }
    return r.json();
  }

  async function sendShare() {
    if (!$("share-to").checkValidity()) { $("share-to").reportValidity(); return; }
    const share = await buildShare();
    if (!share) return;
    window.location.href = share.mailto;
    $("share-dialog").close();
  }

  async function copyShare() {
    const share = await buildShare();
    if (!share) return;
    try {
      await navigator.clipboard.writeText(`${share.subject}\n\n${share.body}`);
      $("share-copy").textContent = "Copied!";
      setTimeout(() => { $("share-copy").textContent = "Copy text"; }, 1500);
    } catch (_) {
      alert("Couldn't copy automatically. Use Open email instead.");
    }
  }

  // ---------- wiring ----------
  document.addEventListener("DOMContentLoaded", async () => {
    loadStatus();
    await loadFlags();
    if (!$("note-form")) return;
    $("note-form").addEventListener("submit", saveNote);
    $("note-text").addEventListener("input", updateCount);
    $("category-form").addEventListener("submit", addCategory);
    let searchTimer;
    $("search").addEventListener("input", (e) => {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => { state.filter.q = e.target.value.trim(); loadNotes(); }, 250);
    });
    $("filter-category").addEventListener("change", (e) => { state.filter.categoryId = e.target.value; loadNotes(); });
    $("select-all").addEventListener("change", (e) => {
      state.selected = e.target.checked ? new Set(state.notes.map((n) => n.id)) : new Set();
      renderNotes();
    });
    $("bulk-bar").addEventListener("click", onBulkClick);
    $("bulk-category").addEventListener("change", onBulkCategory);
    $("share-send").addEventListener("click", sendShare);
    $("share-copy").addEventListener("click", copyShare);
    updateCount();
    refresh();
  });
})();

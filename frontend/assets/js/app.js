// Frontend behaviour: talks to the FastAPI JSON API under /api.
(() => {
  const $ = (id) => document.getElementById(id);

  // A stable per-browser id, so percentage rollouts stay sticky for this visitor.
  let userId = "anonymous";
  try {
    userId = localStorage.getItem("userId") || crypto.randomUUID();
    localStorage.setItem("userId", userId);
  } catch (_) { /* storage blocked: stay anonymous */ }
  const headers = { "Content-Type": "application/json", "X-User-Id": userId };

  const api = (path, opts = {}) => fetch(path, { ...opts, headers: { ...headers, ...(opts.headers || {}) } });

  let maxLength = 500;

  async function loadFlags() {
    try {
      const { flags } = await (await api("/api/flags")).json();
      maxLength = flags["max-note-length"];
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

  function renderNotes(notes) {
    const list = $("notes");
    list.replaceChildren();
    for (const note of notes) {
      const li = document.createElement("li");
      const text = document.createElement("span");
      text.className = "note-text";
      text.textContent = note.text;
      const del = document.createElement("button");
      del.className = "link";
      del.textContent = "Delete";
      del.setAttribute("aria-label", "Delete note");
      del.onclick = async () => { await api(`/api/notes/${note.id}`, { method: "DELETE" }); loadNotes(); };
      li.append(text, del);
      list.append(li);
    }
    $("notes-empty").hidden = notes.length > 0;
  }

  async function loadNotes() {
    const r = await api("/api/notes");
    const off = r.status === 503;
    $("notes-unavailable").hidden = !off;
    $("note-form").querySelector("button").disabled = off;
    if (r.ok) renderNotes(await r.json());
  }

  function updateCount() {
    const n = $("note-text").value.length;
    $("char-count").textContent = `${n} / ${maxLength}`;
  }

  async function saveNote(e) {
    e.preventDefault();
    const err = $("form-error");
    err.hidden = true;
    const r = await api("/api/notes", { method: "POST", body: JSON.stringify({ text: $("note-text").value }) });
    if (r.ok) {
      $("note-text").value = "";
      updateCount();
      loadNotes();
    } else {
      const body = await r.json().catch(() => ({}));
      err.textContent = typeof body.detail === "string" ? body.detail : "Couldn't save the note.";
      err.hidden = false;
    }
  }

  document.addEventListener("DOMContentLoaded", async () => {
    loadStatus();
    await loadFlags();
    if ($("note-form")) {
      $("note-form").addEventListener("submit", saveNote);
      $("note-text").addEventListener("input", updateCount);
      updateCount();
      loadNotes();
    }
  });
})();

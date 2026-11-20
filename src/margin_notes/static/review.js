// margin-notes review overlay: select text -> comment; notes save beside the document.
(() => {
  if (window.__marginNotes) return;
  window.__marginNotes = true;

  const DOC = encodeURIComponent(location.pathname);
  const API = "/__review/api/notes";
  const SKIP = new Set(["SCRIPT", "STYLE", "NOSCRIPT", "TEMPLATE", "TEXTAREA", "SELECT", "MJX-CONTAINER"]);
  const SVG_NS = "http://www.w3.org/2000/svg";
  const CTX = 48;
  let notes = [];
  let notesFile = "";
  let pending = null; // selection waiting for the Comment button
  let editing = null; // {note, isNew}

  // ---------- highlight styles live in the page; all UI lives in a shadow root ----------
  const pageStyle = document.createElement("style");
  pageStyle.textContent = `
    mark.__rv { background: rgba(255, 210, 70, .5) !important; color: inherit !important;
      padding: 0 !important; margin: 0 !important; border-radius: 2px; cursor: pointer;
      box-decoration-break: clone; -webkit-box-decoration-break: clone; }
    mark.__rv.__rv-on { background: rgba(255, 150, 20, .7) !important;
      box-shadow: 0 0 0 2px rgba(240, 120, 0, .9); }`;
  (document.head || document.documentElement).appendChild(pageStyle);

  const host = document.createElement("div");
  host.id = "__review-host";
  host.style.cssText = "all: initial; position: fixed; inset: 0 auto auto 0; width: 0; height: 0; z-index: 2147483647;";
  document.documentElement.appendChild(host);
  const root = host.attachShadow({ mode: "open" });
  root.innerHTML = `
  <style>
    :host { --bg:#fff; --fg:#1d1d1f; --muted:#6e6e73; --line:#d9d9de; --accent:#2f6fde; --hl:#ffe08a; --danger:#c62828; }
    @media (prefers-color-scheme: dark) {
      :host { --bg:#1f1f22; --fg:#f2f2f4; --muted:#a1a1a8; --line:#3a3a40; --accent:#6ea0ff; --hl:#6b5a1e; --danger:#ff6b6b; }
    }
    * { box-sizing: border-box; font: 13px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif; }
    a { color: var(--accent); text-decoration: none; }
    a:hover { text-decoration: underline; }
    button { cursor: pointer; border: 1px solid var(--line); background: var(--bg); color: var(--fg);
      border-radius: 6px; padding: 5px 10px; }
    button:hover { border-color: var(--accent); }
    button.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
    button.danger { color: var(--danger); }
    [hidden] { display: none !important; }
    #add { position: fixed; padding: 4px 10px; font-weight: 600; box-shadow: 0 2px 10px rgba(0,0,0,.25); }
    #editor { position: fixed; width: min(340px, calc(100vw - 16px)); background: var(--bg); color: var(--fg);
      border: 1px solid var(--line); border-radius: 10px; padding: 12px; box-shadow: 0 8px 30px rgba(0,0,0,.3); z-index: 2; }
    .quote { border-left: 3px solid var(--hl); padding: 2px 8px; color: var(--muted); max-height: 7.5em;
      overflow: auto; white-space: pre-wrap; margin-bottom: 6px; }
    .section { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: .04em; margin-bottom: 6px; }
    textarea { width: 100%; min-height: 90px; resize: vertical; background: var(--bg); color: var(--fg);
      border: 1px solid var(--line); border-radius: 6px; padding: 6px 8px; }
    textarea:focus { outline: 2px solid var(--accent); outline-offset: -1px; }
    .row { display: flex; gap: 6px; margin-top: 8px; align-items: center; flex-wrap: wrap; }
    .sp { flex: 1; }
    .hint { color: var(--muted); font-size: 11px; }
    #toggle { position: fixed; right: 16px; bottom: 16px; font-weight: 600; box-shadow: 0 2px 12px rgba(0,0,0,.25); }
    #panel { position: fixed; top: 0; right: 0; bottom: 0; width: min(360px, 100vw); background: var(--bg); color: var(--fg);
      border-left: 1px solid var(--line); box-shadow: -6px 0 24px rgba(0,0,0,.18); display: flex; flex-direction: column; z-index: 1; }
    #panel header { display: flex; align-items: center; gap: 8px; padding: 12px 14px; border-bottom: 1px solid var(--line); }
    #panel header b { font-size: 14px; flex: 1; }
    .meta { padding: 8px 14px; color: var(--muted); font-size: 12px; border-bottom: 1px solid var(--line); display: flex; gap: 8px; }
    .meta .status { flex: 1; }
    .meta .err { color: var(--danger); }
    .copy { padding: 8px 14px; border-bottom: 1px solid var(--line); display: flex; gap: 6px; align-items: center; }
    .copy code { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; direction: rtl;
      text-align: left; color: var(--muted); font-size: 11px; }
    .copy button { font-size: 12px; padding: 3px 8px; white-space: nowrap; }
    ol { list-style: none; margin: 0; padding: 6px; overflow: auto; flex: 1; }
    li { padding: 8px 10px; border-radius: 8px; cursor: pointer; border: 1px solid transparent; }
    li:hover { border-color: var(--line); }
    li.on { border-color: var(--accent); }
    li .q { color: var(--muted); border-left: 3px solid var(--hl); padding-left: 6px; margin: 2px 0 4px;
      display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
    li .c { white-space: pre-wrap; }
    li .c.empty { color: var(--muted); font-style: italic; }
    .badge { font-size: 10px; color: var(--danger); border: 1px solid var(--danger); border-radius: 4px; padding: 0 4px; margin-left: 4px; }
    .empty-list { color: var(--muted); padding: 14px; cursor: default; }
  </style>
  <button id="add" hidden>💬 Comment</button>
  <div id="editor" hidden>
    <div class="section"></div>
    <div class="quote"></div>
    <textarea placeholder="Comment (optional; a bare highlight is fine)"></textarea>
    <div class="row">
      <button class="danger del">Delete</button><span class="sp"></span>
      <span class="hint">⌘↵ save · Esc cancel</span>
      <button class="cancel">Cancel</button><button class="primary save">Save</button>
    </div>
  </div>
  <button id="toggle">Notes · 0</button>
  <aside id="panel" hidden>
    <header><b>Review notes</b><button class="general">+ General note</button><button class="close" title="Close">✕</button></header>
    <div class="meta"><span class="status"></span><a class="folder" href="./">Folder</a></div>
    <div class="copy"><code class="path"></code><button class="copy-path" title="Copy the notes file's full path">Copy path</button><button class="copy-json" title="Copy the notes file's JSON">Copy JSON</button></div>
    <ol></ol>
  </aside>`;

  const $ = (s) => root.querySelector(s);
  const addBtn = $("#add"), ed = $("#editor"), ta = $("#editor textarea"), panel = $("#panel"), list = $("#panel ol");

  // Keep the page's own keyboard shortcuts from firing while typing in our UI.
  for (const t of ["keydown", "keyup", "keypress"]) host.addEventListener(t, (e) => e.stopPropagation());
  const inHost = (e) => e.composedPath().includes(host);

  // ---------- helpers ----------
  const norm = (s) => s.replace(/\s+/g, " ").trim();
  const newId = () => "n" + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
  const clean = (n) => Object.fromEntries(Object.entries(n).filter(([k]) => !k.startsWith("_")));
  function nowIso() {
    const d = new Date(), off = -d.getTimezoneOffset();
    const p = (n) => String(Math.floor(Math.abs(n))).padStart(2, "0");
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}` +
      `${off >= 0 ? "+" : "-"}${p(off / 60)}:${p(off % 60)}`;
  }

  // Concatenated text of the document body plus where each text node starts in it.
  function textMap() {
    const nodes = [];
    let text = "";
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {
      acceptNode(n) {
        for (let p = n.parentNode; p && p !== document.body; p = p.parentNode)
          if (SKIP.has(p.nodeName) || p.namespaceURI === SVG_NS) return NodeFilter.FILTER_REJECT;
        return NodeFilter.FILTER_ACCEPT;
      },
    });
    for (let n; (n = walker.nextNode()); ) { nodes.push({ node: n, start: text.length }); text += n.data; }
    return { nodes, text };
  }

  function rangeToOffsets(range, map) {
    let start = null, end = null;
    for (const { node, start: s } of map.nodes) {
      if (!range.intersectsNode(node)) continue;
      const a = node === range.startContainer ? range.startOffset : 0;
      const b = node === range.endContainer ? range.endOffset : node.data.length;
      if (start === null) start = s + a;
      end = s + b;
    }
    return start === null || end <= start ? null : { start, end };
  }

  function sectionFor(node) {
    let best = null;
    for (const h of document.body.querySelectorAll("h1,h2,h3,h4,h5,h6")) {
      if (h.contains(node) || (h.compareDocumentPosition(node) & Node.DOCUMENT_POSITION_FOLLOWING)) best = h;
      else break;
    }
    return best ? norm(best.textContent).slice(0, 200) || null : null;
  }

  const commonPrefix = (a, b) => { let i = 0; while (i < a.length && i < b.length && a[i] === b[i]) i++; return i; };
  const commonSuffix = (a, b) => { let i = 0; while (i < a.length && i < b.length && a[a.length - 1 - i] === b[b.length - 1 - i]) i++; return i; };

  // Find the occurrence of the quote whose surrounding text best matches what was saved.
  function locate(anchor, map) {
    const t = map.text, q = anchor.exact;
    if (!q) return null;
    let best = null, bestScore = -Infinity;
    for (let i = t.indexOf(q); i !== -1; i = t.indexOf(q, i + 1)) {
      const pre = t.slice(Math.max(0, i - (anchor.prefix || "").length), i);
      const suf = t.slice(i + q.length, i + q.length + (anchor.suffix || "").length);
      const score = commonSuffix(pre, anchor.prefix || "") + commonPrefix(suf, anchor.suffix || "") - Math.abs(i - (anchor.start ?? i)) / 1e7;
      if (score > bestScore) { bestScore = score; best = i; }
    }
    return best === null ? null : { start: best, end: best + q.length };
  }

  function wrap(start, end, id, map) {
    const marks = [];
    for (const { node, start: s } of map.nodes) {
      const e = s + node.data.length;
      if (e <= start || s >= end) continue;
      const a = Math.max(start, s) - s, b = Math.min(end, e) - s;
      if (!node.data.slice(a, b).trim()) continue; // whitespace between block elements
      let n = node;
      if (b < n.data.length) n.splitText(b);
      if (a > 0) n = n.splitText(a);
      const m = document.createElement("mark");
      m.className = "__rv";
      m.dataset.rv = id;
      n.parentNode.insertBefore(m, n);
      m.appendChild(n);
      marks.push(m);
    }
    return marks;
  }

  function clearMarks() {
    const parents = new Set();
    for (const m of document.querySelectorAll("mark.__rv")) {
      const p = m.parentNode;
      while (m.firstChild) p.insertBefore(m.firstChild, m);
      p.removeChild(m);
      parents.add(p);
    }
    for (const p of parents) if (p.isConnected) p.normalize();
  }

  function sortNotes() {
    notes.sort((a, b) => {
      if (!a.anchor !== !b.anchor) return a.anchor ? 1 : -1;
      if (!a.anchor) return String(a.created_at).localeCompare(String(b.created_at));
      return (a.anchor.start || 0) - (b.anchor.start || 0);
    });
  }

  // ---------- rendering ----------
  function render() {
    clearMarks();
    for (const n of notes) {
      n._orphan = false;
      if (!n.anchor) continue;
      const map = textMap();
      const loc = locate(n.anchor, map);
      if (!loc || !wrap(loc.start, loc.end, n.id, map).length) n._orphan = true;
    }
    renderList();
  }

  function markActive() {
    const id = editing && editing.note.id;
    for (const m of document.querySelectorAll("mark.__rv")) m.classList.toggle("__rv-on", m.dataset.rv === id);
    for (const li of list.children) li.classList.toggle("on", li.dataset.id === id);
  }

  function renderList() {
    $("#toggle").textContent = `Notes · ${notes.length}`;
    list.replaceChildren();
    if (!notes.length) {
      const li = document.createElement("li");
      li.className = "empty-list";
      li.textContent = "Select text in the document, then click “Comment”.";
      list.append(li);
    }
    for (const n of notes) {
      const li = document.createElement("li");
      li.dataset.id = n.id;
      const sec = document.createElement("div");
      sec.className = "section";
      sec.textContent = n.anchor ? (n.section || "—") : "General";
      if (n._orphan) { const b = document.createElement("span"); b.className = "badge"; b.textContent = "not found"; sec.append(b); }
      li.append(sec);
      if (n.quote) { const q = document.createElement("div"); q.className = "q"; q.textContent = n.quote; li.append(q); }
      const c = document.createElement("div");
      c.className = "c" + (n.comment ? "" : " empty");
      c.textContent = n.comment || "highlight only";
      li.append(c);
      li.addEventListener("click", () => focusNote(n));
      list.append(li);
    }
    markActive();
  }

  function setStatus(msg, err = false) {
    const s = $(".meta .status");
    s.className = "status" + (err ? " err" : "");
    s.textContent = msg;
  }

  // ---------- persistence: one request per note, applied server-side under a lock ----------
  let chain = Promise.resolve();
  function send(method, path, body) {
    setStatus("Saving…");
    chain = chain
      .then(() => fetch(`${API}${path}?doc=${DOC}`, {
        method, headers: body ? { "Content-Type": "application/json" } : {}, body: body && JSON.stringify(body),
      }))
      .then(async (r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const data = await r.json();
        setStatus(`Saved to ${data.notes_file} at ${new Date().toLocaleTimeString()}`);
        setFile(data);
        // Pick up notes other reviewers added, unless we're mid-edit.
        if (!editing && Array.isArray(data.notes)) { notes = data.notes; sortNotes(); render(); }
      })
      .catch((e) => setStatus(`Save failed (${e.message}). Is the server still running?`, true));
  }
  const saveNote = (n) => send("PUT", "", clean(n));
  const deleteNote = (n) => send("DELETE", `/${encodeURIComponent(n.id)}`);

  // ---------- editor ----------
  function place(rect) {
    const W = ed.offsetWidth || 340, H = ed.offsetHeight || 230;
    if (!rect) { ed.style.left = `${(innerWidth - W) / 2}px`; ed.style.top = `${Math.max(8, (innerHeight - H) / 3)}px`; return; }
    const left = Math.min(Math.max(8, rect.left), innerWidth - W - 8);
    let top = rect.bottom + 8;
    if (top + H > innerHeight - 8) top = Math.max(8, rect.top - H - 8);
    ed.style.left = `${left}px`;
    ed.style.top = `${top}px`;
  }

  function openEditor(note, isNew, rect) {
    editing = { note, isNew };
    $("#editor .section").textContent = note.anchor ? (note.section || "") : "General note";
    const q = $("#editor .quote");
    q.textContent = note.quote || "";
    q.hidden = !note.quote;
    ta.value = note.comment || "";
    $("#editor .del").hidden = isNew;
    ed.hidden = false;
    place(rect);
    markActive();
    ta.focus();
  }

  function closeEditor() { editing = null; ed.hidden = true; markActive(); }

  function save() {
    const { note, isNew } = editing;
    const comment = ta.value.trim();
    closeEditor();
    if (!isNew && comment === (note.comment || "")) return;
    note.comment = comment;
    note.updated_at = nowIso();
    renderList();
    saveNote(note);
  }

  function cancel() {
    if (!editing) return;
    const { note, isNew } = editing;
    closeEditor();
    if (isNew) { notes = notes.filter((n) => n !== note); render(); }
  }

  function remove() {
    const { note } = editing;
    if (!confirm("Delete this note?")) return;
    notes = notes.filter((n) => n !== note);
    closeEditor();
    render();
    deleteNote(note);
  }

  function focusNote(n) {
    const m = document.querySelector(`mark.__rv[data-rv="${CSS.escape(n.id)}"]`);
    if (m) { m.scrollIntoView({ block: "center" }); openEditor(n, false, m.getBoundingClientRect()); }
    else openEditor(n, false, null);
  }

  $("#editor .save").addEventListener("click", save);
  $("#editor .cancel").addEventListener("click", cancel);
  $("#editor .del").addEventListener("click", remove);
  ta.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); save(); }
    else if (e.key === "Escape") { e.preventDefault(); cancel(); }
  });

  // ---------- selection -> Comment button ----------
  function hideAdd() { addBtn.hidden = true; pending = null; }

  function checkSelection() {
    const sel = document.getSelection();
    if (!sel || !sel.rangeCount || sel.isCollapsed) return hideAdd();
    const range = sel.getRangeAt(0);
    if (!document.body.contains(range.commonAncestorContainer)) return hideAdd();
    const map = textMap();
    const off = rangeToOffsets(range, map);
    if (!off) return hideAdd();
    while (off.start < off.end && /\s/.test(map.text[off.start])) off.start++;
    while (off.end > off.start && /\s/.test(map.text[off.end - 1])) off.end--;
    if (off.end <= off.start) return hideAdd();
    const rects = range.getClientRects();
    const last = rects.length ? rects[rects.length - 1] : range.getBoundingClientRect();
    pending = { ...off, text: map.text, node: range.startContainer, rect: range.getBoundingClientRect() };
    addBtn.hidden = false;
    addBtn.style.left = `${Math.min(Math.max(8, last.right - 40), innerWidth - 120)}px`;
    addBtn.style.top = `${Math.min(last.bottom + 6, innerHeight - 40)}px`;
  }

  document.addEventListener("mouseup", (e) => { if (!inHost(e)) setTimeout(checkSelection, 0); });
  document.addEventListener("keyup", (e) => { if (!inHost(e) && (e.shiftKey || e.key === "Shift")) setTimeout(checkSelection, 0); });
  document.addEventListener("scroll", () => { if (!addBtn.hidden) checkSelection(); }, { passive: true, capture: true });

  addBtn.addEventListener("mousedown", (e) => e.preventDefault());
  addBtn.addEventListener("click", () => {
    const p = pending;
    if (!p) return;
    const exact = p.text.slice(p.start, p.end);
    const t = nowIso();
    const note = {
      id: newId(), quote: norm(exact), section: sectionFor(p.node), comment: "", created_at: t, updated_at: t,
      anchor: { exact, prefix: p.text.slice(Math.max(0, p.start - CTX), p.start), suffix: p.text.slice(p.end, p.end + CTX), start: p.start },
    };
    hideAdd();
    document.getSelection().removeAllRanges();
    notes.push(note);
    sortNotes();
    render();
    openEditor(note, true, p.rect);
  });

  // Click a highlight to open its note.
  document.addEventListener("click", (e) => {
    if (inHost(e)) return;
    const m = e.target.closest && e.target.closest("mark.__rv");
    const sel = document.getSelection();
    if (!m || (sel && !sel.isCollapsed)) return;
    const n = notes.find((x) => x.id === m.dataset.rv);
    if (n) { e.preventDefault(); openEditor(n, false, m.getBoundingClientRect()); }
  });

  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    if (editing) cancel(); else hideAdd();
  });

  // ---------- panel ----------
  // The server sends the file's path and contents with every response, so copying is synchronous:
  // Safari refuses clipboard writes that happen after an await.
  let filePath = "", fileJson = null;
  function setFile(data) {
    if (typeof data.notes_path === "string") { filePath = data.notes_path; $(".copy .path").textContent = "\u200e" + filePath; $(".copy .path").title = filePath; }
    if ("notes_json" in data) fileJson = data.notes_json;
  }
  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text);
    // Plain http on a LAN address (--host 0.0.0.0) has no clipboard API; fall back to execCommand.
    const t = document.createElement("textarea");
    t.value = text;
    t.style.cssText = "position:fixed;top:0;left:0;opacity:0";
    root.appendChild(t);
    t.select();
    const ok = document.execCommand("copy");
    t.remove();
    return ok ? Promise.resolve() : Promise.reject(new Error("copy blocked"));
  }
  function copyButton(sel, label, get) {
    const b = $(sel);
    b.addEventListener("click", () => {
      const text = get();
      if (text == null) { setStatus("Nothing to copy yet", true); return; }
      copyText(text).then(
        () => { b.textContent = "Copied ✓"; setTimeout(() => { b.textContent = label; }, 1200); },
        (e) => setStatus(`Copy failed (${e.message})`, true));
    });
  }
  copyButton(".copy-path", "Copy path", () => filePath || null);
  copyButton(".copy-json", "Copy JSON", () => (fileJson ? JSON.stringify(fileJson, null, 2) : null));
  $("#toggle").addEventListener("click", () => { panel.hidden = !panel.hidden; });
  $("#panel .close").addEventListener("click", () => { panel.hidden = true; });
  $("#panel .general").addEventListener("click", () => {
    const t = nowIso();
    const note = { id: newId(), quote: null, section: null, comment: "", created_at: t, updated_at: t, anchor: null };
    notes.push(note);
    sortNotes();
    renderList();
    openEditor(note, true, null);
  });

  // ---------- boot: wait for math and diagrams to render so highlights anchor on final text ----------
  async function boot() {
    const waits = Array.isArray(window.__reviewWait) ? window.__reviewWait : [];
    await Promise.race([Promise.allSettled(waits), new Promise((r) => setTimeout(r, 10000))]);
    try {
      const r = await fetch(`${API}?doc=${DOC}`, { cache: "no-store" });
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
      notes = Array.isArray(data.notes) ? data.notes : [];
      notesFile = data.notes_file;
      setFile(data);
      setStatus(notes.length ? `Loaded ${notes.length} note(s) from ${notesFile}` : `Notes save to ${notesFile}`);
    } catch (e) {
      setStatus(`Couldn't load notes (${e.message})`, true);
    }
    sortNotes();
    render();
  }
  if (document.readyState === "complete") boot(); else window.addEventListener("load", boot);
})();

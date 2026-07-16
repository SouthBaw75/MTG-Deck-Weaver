/* =============================================================================
   MTG Deck Weaver — frontend logic (vanilla JS, no dependencies)

   Structure:
     - Small helpers (DOM, fetch, escaping, formatting)
     - Theme toggle (persisted in localStorage, respects prefers-color-scheme)
     - Hash router (#home #card #analyze #build)
     - Per-view controllers (home / card / analyze / build)
     - Autocomplete widget (shared by card lookup + build commander/partner)
     - Chart renderers (curve, sources-vs-pips, roles, land drops) — pure CSS/DOM
   ========================================================================== */

"use strict";

/* ---------- Tiny DOM helpers --------------------------------------------- */
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

/** Create an element with attributes + children. `children` may be nodes/strings. */
function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "html") node.innerHTML = v;
    else if (k === "text") node.textContent = v;
    else if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2), v);
    else if (k === "dataset") Object.assign(node.dataset, v);
    else node.setAttribute(k, v);
  }
  for (const c of [].concat(children)) {
    if (c == null) continue;
    node.append(c.nodeType ? c : document.createTextNode(String(c)));
  }
  return node;
}

/** Escape a string for safe interpolation into innerHTML contexts. */
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

/** Debounce: delay `fn` until `wait`ms have passed since the last call. */
function debounce(fn, wait = 220) {
  let t;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), wait);
  };
}

const fmtNum = (n) => (typeof n === "number" ? n.toLocaleString("en-US") : n);
const fmtPrice = (p) => (p == null ? null : `$${Number(p).toFixed(2)}`);
const clamp01 = (x) => Math.max(0, Math.min(1, Number(x) || 0));

/* ---------- Fetch helper -------------------------------------------------- */
/**
 * Single reusable fetch wrapper. Parses JSON, and on non-2xx throws an Error
 * carrying the API's `detail` message (503 "knowledge base empty", 404, ...).
 */
async function api(path, options = {}) {
  let res;
  try {
    res = await fetch(path, {
      headers: options.body ? { "Content-Type": "application/json" } : undefined,
      ...options,
    });
  } catch (networkErr) {
    throw new Error("Could not reach the Weaver server. Is it running?");
  }
  let data = null;
  const text = await res.text();
  if (text) {
    try { data = JSON.parse(text); } catch { data = text; }
  }
  if (!res.ok) {
    const detail = data && typeof data === "object" && data.detail ? data.detail : null;
    const err = new Error(detail || `Request failed (${res.status}).`);
    err.status = res.status;
    throw err;
  }
  return data;
}

/* ---------- Toast / notice banner ---------------------------------------- */
const toastEl = $("#toast");
let toastTimer;
function showToast(message) {
  toastEl.textContent = message;
  toastEl.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (toastEl.hidden = true), 6000);
}
function clearToast() {
  toastEl.hidden = true;
}

/* ---------- Card popup (global) ------------------------------------------
   Any element with class "card-link" and a data-card="<name>" attribute opens
   a modal showing that card's image + full details. Rendering is delegated at
   the document level, so every card name anywhere in the app is clickable
   without wiring each render site to a handler. */

/** An inline, clickable card name that opens the card popup. */
function cardLink(name, extraClass) {
  return el("button", {
    type: "button",
    class: "card-link" + (extraClass ? " " + extraClass : ""),
    "data-card": name,
    title: `View ${name}`,
    text: name,
  });
}

let _modal = null;
let _modalReturnFocus = null;

function ensureModal() {
  if (_modal) return _modal;
  const body = el("div", { class: "modal__body" });
  const closeBtn = el("button", {
    type: "button", class: "modal__close", "aria-label": "Close", html: "&times;",
    onclick: closeCardModal,
  });
  const dialog = el("div", {
    class: "modal", role: "dialog", "aria-modal": "true", "aria-label": "Card details",
  }, [closeBtn, body]);
  const overlay = el("div", {
    class: "modal-overlay", hidden: "",
    onclick: (e) => { if (e.target === overlay) closeCardModal(); },
  }, [dialog]);
  document.body.append(overlay);
  // Escape is handled by the unified overlay keydown listener (see below).
  _modal = { overlay, dialog, body, closeBtn };
  return _modal;
}

async function openCardModal(name) {
  const { overlay, body, closeBtn } = ensureModal();
  _modalReturnFocus = document.activeElement;
  body.innerHTML = "";
  body.append(loadingNode("Summoning card…"));
  overlay.hidden = false;
  document.body.classList.add("modal-open");
  closeBtn.focus();
  try {
    const card = await api(`/api/card/${encodeURIComponent(name)}`);
    body.innerHTML = "";
    body.append(renderCard(card));
  } catch (err) {
    body.innerHTML = "";
    const msg = err.status === 404
      ? `No card data for “${name}”. If you're on the demo database it only has 68 cards — run \`weaver update\` for the full set.`
      : err.message;
    body.append(el("div", { class: "banner", text: msg }));
  }
}

function closeCardModal() {
  if (!_modal || _modal.overlay.hidden) return;
  _modal.overlay.hidden = true;
  if (!imgLightboxOpen()) document.body.classList.remove("modal-open");
  if (_modalReturnFocus && _modalReturnFocus.focus) _modalReturnFocus.focus();
}

/* ---------- Image lightbox (enlarge a card image) ------------------------- */
let _lightbox = null;

function imgLightboxOpen() {
  return !!_lightbox && !_lightbox.overlay.hidden;
}

function ensureLightbox() {
  if (_lightbox) return _lightbox;
  const img = el("img", { class: "img-lightbox__img", alt: "" });
  const overlay = el("div", {
    class: "img-lightbox", hidden: "", "aria-hidden": "true",
    onclick: closeImgLightbox,
  }, [img]);
  document.body.append(overlay);
  _lightbox = { overlay, img };
  return _lightbox;
}

function openImgLightbox(src, alt) {
  if (!src) return;
  const { overlay, img } = ensureLightbox();
  img.src = src;
  img.alt = alt || "Card image";
  overlay.hidden = false;
  document.body.classList.add("modal-open");
}

function closeImgLightbox() {
  if (!imgLightboxOpen()) return;
  _lightbox.overlay.hidden = true;
  // Keep scroll locked if the card modal is still open underneath.
  if (!_modal || _modal.overlay.hidden) document.body.classList.remove("modal-open");
}

// One document-level listener catches card-name links AND card-image clicks.
document.addEventListener("click", (e) => {
  const image = e.target.closest(".card-image");
  if (image) {
    e.preventDefault();
    openImgLightbox(image.currentSrc || image.src, image.alt);
    return;
  }
  const addBtn = e.target.closest("[data-add-card]");
  if (addBtn) {
    e.preventDefault();
    // The editable analysis that owns this button carries its own context
    // (Analyze input, or a Weaver-built deck's working copy).
    const ctx = addBtn.closest(".analysis")?.__weaverCtx;
    if (ctx) beginComboUpgrade(ctx, addBtn.getAttribute("data-add-card"), addBtn.hasAttribute("data-arena-illegal"));
    return;
  }
  const link = e.target.closest(".card-link[data-card]");
  if (link) {
    e.preventDefault();
    openCardModal(link.getAttribute("data-card"));
  }
});

// Keyboard: Enter/Space enlarges a focused card image.
document.addEventListener("keydown", (e) => {
  if (e.key !== "Enter" && e.key !== " ") return;
  const image = e.target.closest?.(".card-image");
  if (image) {
    e.preventDefault();
    openImgLightbox(image.currentSrc || image.src, image.alt);
  }
});

// Single Escape handler for the layered overlays (topmost first).
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  if (cutChooserOpen()) { closeCutChooser(); return; }
  if (imgLightboxOpen()) { closeImgLightbox(); return; }
  if (_modal && !_modal.overlay.hidden) { closeCardModal(); return; }
});

/* ---------- Theme ---------------------------------------------------------- */
const THEME_KEY = "weaver.theme";
const themeBtn = $("#theme-toggle");

function applyTheme(theme) {
  // theme is "light" | "dark". Absence of the attribute would defer to the OS,
  // but once a user chooses we always set it explicitly.
  document.documentElement.setAttribute("data-theme", theme);
  const isLight = theme === "light";
  themeBtn.setAttribute("aria-pressed", String(isLight));
  themeBtn.querySelector(".theme-toggle__icon").innerHTML = isLight ? "&#9728;" : "&#9790;"; // sun / moon
  themeBtn.title = isLight ? "Switch to dark theme" : "Switch to light theme";
}

function initTheme() {
  const stored = localStorage.getItem(THEME_KEY);
  if (stored === "light" || stored === "dark") {
    applyTheme(stored);
  } else {
    // Follow the OS preference for the initial look; default to dark (the splash look).
    const prefersLight = window.matchMedia("(prefers-color-scheme: light)").matches;
    applyTheme(prefersLight ? "light" : "dark");
  }
}

themeBtn.addEventListener("click", () => {
  const next = document.documentElement.getAttribute("data-theme") === "light" ? "dark" : "light";
  applyTheme(next);
  localStorage.setItem(THEME_KEY, next);
});

/* ---------- Autocomplete widget ------------------------------------------- */
/**
 * Wires a text input + <ul> listbox to /api/search. Debounced. Keyboard support
 * (ArrowUp/Down, Enter, Escape). `onPick(name)` fires when a suggestion is chosen.
 */
function attachAutocomplete(input, list, onPick, kind) {
  let items = [];
  let active = -1;

  const close = () => {
    list.hidden = true;
    list.innerHTML = "";
    input.setAttribute("aria-expanded", "false");
    active = -1;
    items = [];
  };

  const render = () => {
    list.innerHTML = "";
    items.forEach((name, i) => {
      const li = el("li", {
        class: "suggest__item",
        role: "option",
        id: `${list.id}-opt-${i}`,
        "aria-selected": String(i === active),
        text: name,
        // mousedown (not click) so it fires before the input's blur.
        onmousedown: (e) => { e.preventDefault(); choose(i); },
      });
      list.append(li);
    });
    list.hidden = items.length === 0;
    input.setAttribute("aria-expanded", String(items.length > 0));
  };

  const choose = (i) => {
    if (i < 0 || i >= items.length) return;
    // Capture the picked name BEFORE close() — close() clears `items`, so
    // reading items[i] afterwards would yield undefined.
    const picked = items[i];
    input.value = picked;
    close();
    if (onPick) onPick(picked);
  };

  const lookup = debounce(async (q) => {
    if (!q || q.trim().length < 2) { close(); return; }
    try {
      const kindParam = kind ? `&kind=${encodeURIComponent(kind)}` : "";
      items = await api(`/api/search?q=${encodeURIComponent(q.trim())}${kindParam}`);
      active = -1;
      render();
    } catch (err) {
      close(); // search failures are quiet — the field still works on submit
    }
  }, 200);

  input.addEventListener("input", () => lookup(input.value));
  input.addEventListener("focus", () => { if (input.value.trim().length >= 2) lookup(input.value); });
  input.addEventListener("blur", () => setTimeout(close, 120));
  input.addEventListener("keydown", (e) => {
    if (list.hidden) return;
    if (e.key === "ArrowDown") { e.preventDefault(); active = Math.min(active + 1, items.length - 1); render(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); active = Math.max(active - 1, 0); render(); }
    else if (e.key === "Enter" && active >= 0) { e.preventDefault(); choose(active); }
    else if (e.key === "Escape") { close(); }
  });

  return { close };
}

/* =============================================================================
   HOME
   ========================================================================== */
let homeLoaded = false;
async function initHome() {
  if (homeLoaded) return;
  homeLoaded = true;
  const statsEl = $("#home-stats");
  const emptyEl = $("#home-empty");
  try {
    const stats = await api("/api/stats");
    const c = stats.counts || {};
    if (!c.cards) {
      emptyEl.hidden = false;
      statsEl.textContent = "";
      return;
    }
    // Compose a small, elegant stat line.
    const parts = [
      `${fmtNum(c.cards)} cards`,
      `${fmtNum(c.combos || 0)} combos`,
      c.rules ? `${fmtNum(c.rules)} rules loaded` : null,
    ].filter(Boolean);
    statsEl.innerHTML = parts.map(esc).join('<span class="dot">&middot;</span>');
  } catch (err) {
    statsEl.textContent = "";
    // A missing knowledge base surfaces as the friendly banner, not a scary toast.
    if (err.status === 503) emptyEl.hidden = false;
    else showToast(err.message);
  }
}

/* =============================================================================
   CARD LOOKUP
   ========================================================================== */
function initCard() {
  const form = $("#card-form");
  const input = $("#card-search");
  const list = $("#card-suggest");
  const out = $("#card-result");

  if (form.dataset.ready) return;
  form.dataset.ready = "1";

  attachAutocomplete(input, list, (name) => loadCard(name));

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    if (input.value.trim()) loadCard(input.value.trim());
  });

  async function loadCard(name) {
    out.innerHTML = "";
    out.append(loadingNode("Consulting the archive…"));
    try {
      const card = await api(`/api/card/${encodeURIComponent(name)}`);
      out.innerHTML = "";
      out.append(renderCard(card));
    } catch (err) {
      out.innerHTML = "";
      if (err.status === 404) {
        out.append(el("div", { class: "banner", text: `No card matching "${name}".` }));
      } else {
        out.append(el("div", { class: "banner banner--empty", text: err.message }));
      }
    }
  }
}

function renderCard(card) {
  const panel = el("div", { class: "panel" });

  // Card artwork (loaded from Scryfall by the browser — needs internet; the
  // image quietly removes itself if it can't load, so the text view still works).
  if (card.image_url) {
    panel.append(el("img", {
      class: "card-image",
      src: card.image_url,
      alt: `${card.name} card image`,
      loading: "lazy",
      role: "button",
      tabindex: "0",
      title: "Click to enlarge",
      "aria-label": `Enlarge ${card.name} image`,
      onerror: (e) => e.target.remove(),
    }));
  }

  // Header: name + mana cost
  panel.append(
    el("div", { class: "card-head" }, [
      el("h2", { class: "card-name", text: card.name }),
      card.mana_cost ? el("span", { class: "card-cost", text: card.mana_cost }) : null,
    ])
  );
  if (card.type_line) panel.append(el("p", { class: "card-type", text: card.type_line }));

  // Badge row
  const badges = el("div", { class: "badges" });
  if (card.legal_commander) {
    const legal = card.legal_commander === "legal";
    badges.append(el("span", {
      class: `badge ${legal ? "badge--legal" : "badge--illegal"}`,
      text: legal ? "Commander legal" : `Commander: ${card.legal_commander}`,
    }));
  }
  if (card.is_game_changer) badges.append(el("span", { class: "badge badge--gold", text: "★ Game Changer" }));
  if (card.edhrec_rank != null) badges.append(el("span", { class: "badge badge--sapphire", text: `EDHREC #${fmtNum(card.edhrec_rank)}` }));
  const price = fmtPrice(card.price_usd);
  if (price) badges.append(el("span", { class: "badge badge--price", text: price }));
  if (card.combo_count > 0) badges.append(el("span", { class: "badge", text: `${card.combo_count} combo${card.combo_count === 1 ? "" : "s"}` }));
  if (badges.children.length) panel.append(badges);

  // Oracle text (preserve line breaks via CSS pre-wrap)
  if (card.oracle_text) {
    panel.append(el("div", { class: "section-label", text: "Oracle text" }));
    panel.append(el("div", { class: "card-oracle", text: card.oracle_text }));
  }

  // Roles as chips with quality meters
  if (Array.isArray(card.roles) && card.roles.length) {
    panel.append(el("div", { class: "section-label", text: "Roles" }));
    const chips = el("div", { class: "chips" });
    for (const role of card.roles) {
      const q = clamp01(role.quality);
      chips.append(
        el("div", { class: "chip" }, [
          el("span", { class: "chip__tag", text: role.tag }),
          el("div", { class: "chip__meter", role: "meter", "aria-label": `${role.tag} quality`,
                      "aria-valuenow": q.toFixed(2), "aria-valuemin": "0", "aria-valuemax": "1" }, [
            el("div", { class: "chip__fill", style: `width:${Math.round(q * 100)}%` }),
          ]),
          el("span", { class: "chip__q", text: `quality ${q.toFixed(2)}` }),
        ])
      );
    }
    panel.append(chips);
  }

  return panel;
}

/* =============================================================================
   ANALYZE
   ========================================================================== */
function initAnalyze() {
  const form = $("#analyze-form");
  const input = $("#analyze-input");
  const btn = $("#analyze-btn");
  const out = $("#analyze-result");
  const arena = $("#analyze-arena");

  if (form.dataset.ready) return;
  form.dataset.ready = "1";

  // Remember the Arena preference across visits.
  if (arena) {
    arena.checked = localStorage.getItem("weaver.analyze.arena") === "1";
    arena.addEventListener("change", () => {
      localStorage.setItem("weaver.analyze.arena", arena.checked ? "1" : "0");
      // Re-render the current analysis so combo badges appear/disappear.
      if (input.value.trim() && out.querySelector(".analysis")) form.requestSubmit();
    });
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const decklist = input.value.trim();
    if (!decklist) { showToast("Paste a decklist first."); return; }
    out.innerHTML = "";
    out.append(loadingNode("Analyzing the weave…"));
    btn.disabled = true;
    try {
      const result = await api("/api/analyze", { method: "POST", body: JSON.stringify({ decklist }) });
      out.innerHTML = "";
      out.append(saveBar(decklist, { commander: result.commanders && result.commanders[0] }));
      // Editable: "+ Add" combo upgrades act on the Analyze textarea and re-submit.
      const ctx = {
        getDecklist: () => input.value,
        apply: (dl) => { input.value = dl; form.requestSubmit(); },
        arena: !!(arena && arena.checked),
      };
      out.append(renderAnalysis(result, true, ctx, ctx.arena));
    } catch (err) {
      out.innerHTML = "";
      out.append(el("div", { class: "banner banner--empty", text: err.message }));
    } finally {
      btn.disabled = false;
    }
  });
}

/** Full analysis renderer: header + each section (with charts).
 *  `editable` enables in-place combo upgrades; `ctx` is the upgrade context
 *  ({getDecklist, apply}) that the "+ Add" buttons act on. Attached to the root
 *  so the document-level click handler can find it (works in Analyze and in a
 *  Weaver-built deck's validation panel alike). */
function renderAnalysis(a, editable = false, ctx = null, arena = false) {
  const frag = el("div", { class: "analysis" });
  if (editable && ctx) frag.__weaverCtx = ctx;

  // Header
  const head = el("div", { class: "analysis-head" });
  const cmd = (a.commanders && a.commanders.length) ? a.commanders.join(" + ") : "None detected";
  head.append(el("h2", { text: `Commander: ${cmd}` }));
  head.append(el("p", { class: "meta", html:
    `<strong>${fmtNum(a.total_cards)}</strong> cards &middot; <strong>${fmtNum(a.land_count)}</strong> lands` }));
  if (a.unresolved && a.unresolved.length) {
    const banner = el("div", { class: "banner banner--empty", style: "margin-top:.8rem" },
      [document.createTextNode(`Unresolved (${a.unresolved.length}): `)]);
    a.unresolved.forEach((n, i) => {
      if (i) banner.append(document.createTextNode(", "));
      banner.append(cardLink(n));
    });
    head.append(banner);
  }
  frag.append(head);

  // Sections
  for (const section of a.sections || []) frag.append(renderSection(section, editable, arena));
  return frag;
}

/** One analysis section card, colored by worst_severity, with findings + charts. */
function renderSection(section, editable = false, arena = false) {
  const node = el("section", { class: "asection", dataset: { sev: section.worst_severity || "info" } });
  node.append(el("h3", { class: "asection__title", text: section.title }));

  // Findings
  const ul = el("ul", { class: "findings" });
  for (const f of section.findings || []) {
    ul.append(
      el("li", { class: "finding", dataset: { sev: f.severity } }, [
        el("span", { class: "finding__dot", "aria-hidden": "true" }),
        el("span", { class: "finding__msg", text: f.message }),
      ])
    );
  }
  node.append(ul);

  // Charts by section title (data-driven; augment, never replace, the findings).
  const data = section.data || {};
  if (section.title === "Mana Base") appendManaCharts(node, data);
  else if (section.title === "Role Coverage") appendRoleChart(node, data);
  else if (section.title === "Consistency") appendConsistencyChart(node, data);
  else if (section.title === "Combos & Win Lines") appendComboCards(node, data, editable, arena);
  else if (section.title === "Synergy") appendSynergyCards(node, data);

  return node;
}

/** Combos section: actionable "one card away" upgrades (Analyze view only),
 *  then clickable card chips for every card named in the section. When `arena`
 *  is set, each upgrade is badged on/off MTG Arena so the deck stays legal. */
function appendComboCards(node, data, editable = false, arena = false) {
  const near = data.near_miss || [];

  // When we have an editable decklist in scope, offer one-click completion of
  // each near-miss combo: add the single missing card and re-analyze.
  if (editable && near.length) {
    const wrap = el("div", { class: "combo-adds" });
    const label = arena
      ? "Complete a combo — add the missing card (Arena legality shown)"
      : "Complete a combo — add the missing card";
    wrap.append(el("p", { class: "section-sublabel", text: label }));
    for (const c of near) {
      const missing = (c.missing || [])[0];
      if (!missing) continue;
      const have = (c.cards || []).filter((n) => n !== missing);
      const produces = (c.produces && c.produces.length) ? c.produces.join(", ") : "a combo result";
      // arena_legal: true=on Arena, false=not, null/undefined=unknown.
      const onArena = c.arena_legal === true;
      const offArena = arena && c.arena_legal === false;
      const btn = el("button", {
        type: "button",
        class: "combo-add__btn" + (offArena ? " combo-add__btn--illegal" : ""),
        "data-add-card": missing,
        title: offArena
          ? `${missing} is not on MTG Arena — adding it makes the deck illegal for Arena`
          : `Add ${missing} to the decklist and re-analyze`,
        ...(offArena ? { "data-arena-illegal": "1" } : {}),
      }, [document.createTextNode("+ Add "), el("strong", { text: missing })]);
      const row = el("div", { class: "combo-add" }, [btn]);
      if (arena) {
        row.append(onArena
          ? el("span", { class: "arena-badge arena-badge--ok", text: "On Arena" })
          : el("span", { class: "arena-badge arena-badge--no", text: "Not on Arena" }));
      }
      row.append(el("span", { class: "combo-add__desc" }, [
        document.createTextNode(have.length ? `pairs with ${have.join(" + ")} → ` : `→ `),
        el("span", { class: "combo-add__produces", text: produces }),
      ]));
      wrap.append(row);
    }
    node.append(wrap);
  }

  const names = new Set();
  for (const c of (data.present || [])) (c.cards || []).forEach((n) => names.add(n));
  for (const c of near) {
    (c.cards || []).forEach((n) => names.add(n));
    (c.missing || []).forEach((n) => names.add(n));
  }
  appendCardChipRow(node, names);
}

/** A decklist line's card name, stripped of a leading "1 " / "2x " quantity. */
const cardNameOfLine = (line) => line.replace(/^\s*\d+\s*x?\s*/i, "").trim();

/** Is `name` already present in the decklist text (any quantity)? */
function cardInList(text, name) {
  const target = name.toLowerCase();
  return text.split("\n").some((l) => l.trim() && cardNameOfLine(l).toLowerCase() === target);
}

/** Remove one copy of `name` from the decklist text (decrement qty if >1). */
function removeCardLine(text, name) {
  const target = name.toLowerCase();
  const out = [];
  let removed = false;
  for (const line of text.split("\n")) {
    if (!removed && line.trim() && cardNameOfLine(line).toLowerCase() === target) {
      const m = line.match(/^(\s*)(\d+)\s*x?\s+(.*)$/i);
      const qty = m ? parseInt(m[2], 10) : 1;
      if (m && qty > 1) out.push(`${m[1]}${qty - 1} ${m[3].trim()}`);
      removed = true;
      continue;
    }
    out.push(line);
  }
  return out.join("\n");
}

/** Accept a combo upgrade in the given context: fetch cut candidates, then let
 *  the user choose how to make room (swap one out, or add anyway). `ctx` is
 *  {getDecklist, apply} — the Analyze textarea or a Weaver deck's working copy. */
async function beginComboUpgrade(ctx, name, arenaWarn = false) {
  if (!ctx) return;
  const decklist = ctx.getDecklist();
  if (cardInList(decklist, name)) {
    showToast(`${name} is already in the decklist.`);
    return;
  }
  let suggestions = [];
  try {
    const r = await api("/api/cut-suggestions", {
      method: "POST",
      body: JSON.stringify({ decklist, adding: name, count: 5 }),
    });
    suggestions = r.suggestions || [];
  } catch (_err) {
    /* No suggestions available — the chooser still offers "add anyway". */
  }
  openCutChooser(ctx, name, suggestions, arenaWarn);
}

/** Apply the user's choice: optionally cut `cutName`, add `addName`, re-analyze
 *  through the context's apply(). */
function applyCut(ctx, addName, cutName) {
  closeCutChooser();
  if (!ctx) return;
  const text = cutName ? removeCardLine(ctx.getDecklist(), cutName) : ctx.getDecklist();
  const body = text.replace(/\s*$/, "");
  const next = (body ? body + "\n" : "") + `1 ${addName}`;
  showToast(
    cutName
      ? `Swapped ${cutName} → ${addName}. Re-analyzing…`
      : `Added ${addName} — you're at 101. Trim a card to reach 100.`
  );
  ctx.apply(next);
}

/* ---------- Cut chooser modal (make room for an upgrade) ------------------ */
let _cutModal = null;

function ensureCutModal() {
  if (_cutModal) return _cutModal;
  const body = el("div", { class: "modal__body cut-chooser" });
  const closeBtn = el("button", {
    type: "button", class: "modal__close", "aria-label": "Close", html: "&times;",
    onclick: closeCutChooser,
  });
  const dialog = el("div", {
    class: "modal cut-modal", role: "dialog", "aria-modal": "true",
    "aria-label": "Choose a card to cut",
  }, [closeBtn, body]);
  const overlay = el("div", {
    class: "modal-overlay", hidden: "",
    onclick: (e) => { if (e.target === overlay) closeCutChooser(); },
  }, [dialog]);
  document.body.append(overlay);
  _cutModal = { overlay, body };
  return _cutModal;
}

function cutChooserOpen() {
  return !!_cutModal && !_cutModal.overlay.hidden;
}

function openCutChooser(ctx, name, suggestions, arenaWarn = false) {
  const { overlay, body } = ensureCutModal();
  body.innerHTML = "";
  body.append(el("h3", { class: "cut-chooser__title", text: `Add ${name}` }));
  if (arenaWarn) {
    body.append(el("div", { class: "banner cut-chooser__warn", text:
      `⚠ ${name} is not on MTG Arena. Adding it will make this deck illegal to import into Arena (Brawl). You can still add it for a paper/Commander build.` }));
  }
  body.append(el("p", { class: "cut-chooser__lead", text:
    `A Commander deck is exactly 100 cards. Pick one to cut so ${name} has a slot — or add it anyway and trim later.` }));

  if (suggestions.length) {
    body.append(el("p", { class: "section-sublabel", text: "Suggested cuts (safest first)" }));
    const list = el("div", { class: "cut-options" });
    for (const s of suggestions) {
      const btn = el("button", { type: "button", class: "cut-option", onclick: () => applyCut(ctx, name, s.name) });
      const head = el("span", { class: "cut-option__head" }, [
        el("span", { class: "cut-option__name", text: `Cut ${s.name}` }),
      ]);
      if (s.mv_label) head.append(el("span", { class: "cut-option__mv", text: `MV ${s.mv_label}` }));
      btn.append(head);
      btn.append(el("span", { class: "cut-option__reason", text: s.reason }));
      list.append(btn);
    }
    body.append(list);
  } else {
    body.append(el("p", { class: "cut-chooser__none", text:
      "No automatic cut to suggest — combo pieces and cards holding up a needed role are protected. You can add it anyway and remove a card yourself." }));
  }

  const actions = el("div", { class: "cut-actions" });
  actions.append(el("button", {
    type: "button", class: "cut-action cut-action--secondary",
    text: "Add without cutting (101)", onclick: () => applyCut(ctx, name, null),
  }));
  actions.append(el("button", {
    type: "button", class: "cut-action cut-action--ghost",
    text: "Cancel", onclick: closeCutChooser,
  }));
  body.append(actions);

  overlay.hidden = false;
  document.body.classList.add("modal-open");
}

function closeCutChooser() {
  if (!cutChooserOpen()) return;
  _cutModal.overlay.hidden = true;
  if (!imgLightboxOpen() && (!_modal || _modal.overlay.hidden)) {
    document.body.classList.remove("modal-open");
  }
}

/** Clickable card chips for every card named in the synergy section. */
function appendSynergyCards(node, data) {
  const names = new Set();
  for (const pair of [...(data.top_pairs || []), ...(data.nonbos || [])]) {
    if (pair[0]) names.add(pair[0]);
    if (pair[1]) names.add(pair[1]);
  }
  Object.keys(data.per_card || {}).forEach((n) => names.add(n));
  appendCardChipRow(node, names);
}

function appendCardChipRow(node, names) {
  if (!names || !names.size) return;
  const row = el("div", { class: "card-chip-row" });
  [...names].sort().forEach((n) => row.append(cardLink(n, "card-chip")));
  node.append(el("div", { class: "section-sublabel", text: "Cards mentioned" }));
  node.append(row);
}

/* ---------- Chart builders ------------------------------------------------ */
const PIP_COLOR = { W: "var(--mtg-w)", U: "var(--mtg-u)", B: "var(--mtg-b)", R: "var(--mtg-r)", G: "var(--mtg-g)" };
const PIP_NAME = { W: "White", U: "Blue", B: "Black", R: "Red", G: "Green" };
const COLOR_ORDER = ["W", "U", "B", "R", "G"];

function chartWrap(title) {
  const w = el("div", { class: "chart" });
  w.append(el("p", { class: "chart__title", text: title }));
  return w;
}

/** Horizontal bar: label, filled track (optional marker), trailing value text. */
function hbar(label, value, max, color, { marker, markerLabel } = {}) {
  const pct = max > 0 ? Math.round((value / max) * 100) : 0;
  const track = el("div", { class: "hbar__track" }, [
    el("div", { class: "hbar__fill", style: `width:${pct}%;background:${color}` }),
  ]);
  if (marker != null && max > 0) {
    const mpct = Math.min(100, Math.round((marker / max) * 100));
    track.append(el("span", { class: "hbar__marker", style: `left:${mpct}%`, dataset: { label: markerLabel || "" } }));
  }
  return el("div", { class: "hbar" }, [
    el("span", { class: "hbar__label", text: label }),
    track,
    el("span", { class: "hbar__val", text: value }),
  ]);
}

/** Mana Base: MV curve bars + sources-vs-pips per color. */
function appendManaCharts(node, data) {
  // --- Curve (keys 0..7, 7 shown as "7+") ---
  if (data.curve && typeof data.curve === "object") {
    const keys = [0, 1, 2, 3, 4, 5, 6, 7];
    const vals = keys.map((k) => Number(data.curve[k] ?? data.curve[String(k)] ?? 0));
    const max = Math.max(1, ...vals);
    const wrap = chartWrap("Mana curve (nonland spells)");
    const chart = el("div", { class: "curve" });
    keys.forEach((k, i) => {
      const h = Math.round((vals[i] / max) * 100);
      chart.append(
        el("div", { class: "curve__col" }, [
          el("span", { class: "curve__n", text: vals[i] }),
          el("div", { class: "curve__bar", style: `height:${h}%`,
                      title: `MV ${k === 7 ? "7+" : k}: ${vals[i]}`,
                      role: "img", "aria-label": `MV ${k === 7 ? "7 or more" : k}: ${vals[i]} cards` }),
          el("span", { class: "curve__x", text: k === 7 ? "7+" : String(k) }),
        ])
      );
    });
    wrap.append(chart);
    node.append(wrap);
  }

  // --- Sources vs pips per color ---
  const src = data.sources_by_color || {};
  const pips = data.pips_by_color || {};
  const active = COLOR_ORDER.filter((c) => (Number(src[c]) || 0) > 0 || (Number(pips[c]) || 0) > 0);
  if (active.length) {
    const wrap = chartWrap("Color sources vs. pip demand");
    wrap.append(
      el("div", { class: "pair__legend" }, [
        el("span", {}, [el("span", { class: "legend-swatch", style: "background:var(--gold)" }), "sources"]),
        el("span", {}, [el("span", { class: "legend-swatch", style: "background:var(--text-mute)" }), "pips"]),
      ])
    );
    // Shared scale so bars are comparable across colors.
    const max = Math.max(1, ...active.map((c) => Math.max(Number(src[c]) || 0, Number(pips[c]) || 0)));
    const pair = el("div", { class: "pair" });
    for (const c of active) {
      const s = Number(src[c]) || 0;
      const p = Number(pips[c]) || 0;
      pair.append(
        el("div", { class: "pair__row" }, [
          el("span", { class: "hbar__label", style: `color:${PIP_COLOR[c]}`, title: PIP_NAME[c], text: c }),
          el("div", { class: "pair__bars" }, [
            hbar("src", s, max, PIP_COLOR[c]),
            hbar("pip", p, max, "var(--text-mute)"),
          ]),
        ])
      );
    }
    wrap.append(pair);
    node.append(wrap);
  }
}

/** Role Coverage: bar per group, count vs. ideal, with the `min` marked. */
function appendRoleChart(node, data) {
  const roles = data.roles;
  if (!roles || typeof roles !== "object") return;
  const entries = Object.entries(roles);
  if (!entries.length) return;

  const wrap = chartWrap("Role coverage (count vs. ideal, ❘ = minimum)");
  const bars = el("div", { class: "hbars" });
  for (const [group, spec] of entries) {
    const count = Number(spec.count) || 0;
    const ideal = Number(spec.ideal) || 0;
    const min = Number(spec.min) || 0;
    const max = Math.max(1, ideal, count, min);
    // Green when at/over ideal, amber when >= min, ember when short of min.
    const color = count >= ideal ? "var(--sev-ok)" : count >= min ? "var(--sev-warn)" : "var(--sev-problem)";
    bars.append(
      hbar(prettyRole(group), count, max, color, { marker: min, markerLabel: `min ${min}` })
    );
  }
  wrap.append(bars);
  node.append(wrap);
}

function prettyRole(key) {
  const LABELS = {
    ramp: "Ramp", card_advantage: "Draw", spot_removal: "Spot", board_wipe: "Wipes",
    targeted_disruption: "Disrupt", protection: "Protect", wincon: "Wincon",
  };
  return LABELS[key] || key.replace(/_/g, " ");
}

/** Consistency: land-drop probabilities T2..T5 as a small bar row of percentages. */
function appendConsistencyChart(node, data) {
  const drops = data.land_drops;
  if (!drops || typeof drops !== "object") return;
  const turns = [2, 3, 4, 5];
  const wrap = chartWrap("Land drops on the play (P of hitting Tth land by turn T)");
  const bars = el("div", { class: "hbars" });
  for (const t of turns) {
    const p = Number(drops[t] ?? drops[String(t)] ?? 0);
    const pct = Math.round(p * 100);
    // Full scale is 0..100%; color hot below the shaky T4 floor (~50%).
    const color = pct >= 60 ? "var(--sev-ok)" : pct >= 45 ? "var(--sev-warn)" : "var(--sev-problem)";
    bars.append(hbar(`T${t}`, `${pct}%`, 100, color, {}));
    // The hbar value expects a number for width; recompute with percentage width:
    bars.lastChild.querySelector(".hbar__fill").style.width = `${pct}%`;
  }
  wrap.append(bars);
  node.append(wrap);
}

/* =============================================================================
   BUILD
   ========================================================================== */
let archetypesLoaded = false;
async function initBuild() {
  const form = $("#build-form");
  const cmdInput = $("#build-commander");
  const cmdList = $("#build-suggest");
  const partnerInput = $("#build-partner");
  const themeSelect = $("#build-theme");
  const btn = $("#build-btn");
  const out = $("#build-result");

  // Populate archetypes once.
  if (!archetypesLoaded) {
    archetypesLoaded = true;
    try {
      const archs = await api("/api/archetypes");
      for (const a of archs) {
        themeSelect.append(el("option", { value: a.key, text: a.name, title: a.description || "" }));
      }
    } catch { /* Auto-detect option remains; non-fatal. */ }
  }

  if (form.dataset.ready) return;
  form.dataset.ready = "1";

  // Commander autocomplete — restricted to commander-eligible cards (legendary
  // creatures or "can be your commander"), not the whole card pool.
  attachAutocomplete(cmdInput, cmdList, (name) => { cmdInput.value = name; }, "commander");
  // Partner shares a listbox element; build a lightweight second one dynamically.
  const partnerList = el("ul", { id: "build-partner-suggest", class: "suggest", role: "listbox", hidden: "" });
  partnerInput.closest(".field").append(partnerList);
  partnerInput.setAttribute("aria-controls", "build-partner-suggest");
  // Partner also allows Backgrounds (for "Choose a Background" commanders).
  attachAutocomplete(partnerInput, partnerList, (name) => { partnerInput.value = name; }, "partner");

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const commander = cmdInput.value.trim();
    if (!commander) { showToast("A commander is required."); cmdInput.focus(); return; }

    const body = {
      commander,
      partner: partnerInput.value.trim() || null,
      bracket: Number($("#build-bracket").value) || 3,
      budget: $("#build-budget").value ? Number($("#build-budget").value) : null,
      theme: themeSelect.value || null,
      arena_only: $("#build-arena").checked,
    };

    out.innerHTML = "";
    out.append(loadingNode("Weaving your deck — this can take a moment…"));
    btn.disabled = true;
    try {
      const dossier = await api("/api/build", { method: "POST", body: JSON.stringify(body) });
      out.innerHTML = "";
      out.append(renderDossier(dossier));
    } catch (err) {
      out.innerHTML = "";
      out.append(el("div", { class: "banner banner--empty", text: err.message }));
    } finally {
      btn.disabled = false;
    }
  });
}

function renderDossier(d) {
  const frag = document.createDocumentFragment();

  // A mutable working copy of the decklist so combo upgrades can be applied in
  // place (Save, Copy, and the validation panel all read from it). The card
  // breakdown above the validation reflects the original build.
  const state = { decklist: d.decklist };
  const builtArena = !!d.arena_only;  // badge combo upgrades for Arena legality
  let validationBody = null, editedBanner = null, copyTextarea = null, saveHolder = null;

  const rebuildSaveBar = () => {
    if (!saveHolder) return;
    saveHolder.innerHTML = "";
    saveHolder.append(saveBar(state.decklist, { commander: d.commander, bracket: d.bracket }));
  };

  // Upgrade context for the Weaver: apply() edits the working copy, refreshes
  // Save/Copy, and re-runs the validation analysis in place.
  const buildCtx = {
    getDecklist: () => state.decklist,
    arena: builtArena,
    apply: async (dl) => {
      state.decklist = dl;
      if (copyTextarea) copyTextarea.value = dl;
      rebuildSaveBar();
      if (editedBanner) editedBanner.hidden = false;
      if (!validationBody) return;
      validationBody.innerHTML = "";
      validationBody.append(loadingNode("Re-analyzing…"));
      try {
        const res = await api("/api/analyze", { method: "POST", body: JSON.stringify({ decklist: dl }) });
        validationBody.innerHTML = "";
        validationBody.append(renderAnalysis(res, true, buildCtx, builtArena));
      } catch (err) {
        validationBody.innerHTML = "";
        validationBody.append(el("div", { class: "banner banner--empty", text: err.message }));
      }
    },
  };

  // ---- Header ----
  const head = el("div", { class: "build-head" });
  const titleH = el("h2", { class: "build-title" }, [cardLink(d.commander, "card-link--heading")]);
  if (d.partner) {
    titleH.append(document.createTextNode("  +  "));
    titleH.append(cardLink(d.partner, "card-link--heading"));
  }
  head.append(titleH);

  const stats = el("div", { class: "build-stats" });
  stats.append(el("span", { html: `Bracket <strong>${esc(d.bracket)}</strong>` }));
  const spent = fmtPrice(d.spent_usd) || "$0.00";
  const budgetTxt = d.budget != null ? ` / ${fmtPrice(d.budget)} budget` : "";
  stats.append(el("span", { html: `Spend <strong>${esc(spent)}</strong>${esc(budgetTxt)}` }));
  stats.append(el("span", { html: `<strong>${fmtNum(d.total_cards)}</strong> cards` }));
  if (d.land_count != null) stats.append(el("span", { html: `<strong>${fmtNum(d.land_count)}</strong> lands` }));
  head.append(stats);

  if (d.notes && d.notes.length) {
    const notes = el("ul", { class: "build-notes" });
    d.notes.forEach((n) => notes.append(el("li", { text: n })));
    head.append(notes);
  }
  saveHolder = el("div", { class: "save-holder" });
  rebuildSaveBar();
  const tuneBtn = el("button", {
    type: "button", class: "btn btn--ghost", text: "Tune in Analyze",
    title: "Open this deck in the Analyze tab to refine it",
    onclick: () => sendToAnalyze(state.decklist),
  });
  head.append(el("div", { class: "build-actions" }, [saveHolder, tuneBtn]));
  frag.append(head);

  // ---- Card groups ----
  for (const group of d.groups || []) {
    const g = el("section", { class: "group" });
    g.append(
      el("h3", { class: "group__title" }, [
        el("span", { text: group.label || group.role }),
        el("span", { class: "group__count", text: `${(group.cards || []).length} card${group.cards.length === 1 ? "" : "s"}` }),
      ])
    );
    const list = el("ul", { class: "cardlist" });
    for (const card of group.cards || []) {
      const price = fmtPrice(card.price_usd);
      list.append(
        el("li", {}, [
          el("div", {}, [
            cardLink(card.name, "cl-name"),
            card.reason ? el("div", { class: "cl-reason", text: card.reason }) : null,
          ]),
          el("span", { class: "cl-price", text: price || "—" }),
        ])
      );
    }
    g.append(list);
    frag.append(g);
  }

  // ---- Mana base ----
  if (d.lands && d.lands.length) {
    const g = el("section", { class: "group" });
    g.append(el("h3", { class: "group__title" }, [
      el("span", { text: "Mana base" }),
      el("span", { class: "group__count", text: `${d.land_count || ""} lands` }),
    ]));
    const pills = el("div", { class: "manabase-list" });
    for (const land of d.lands) {
      pills.append(el("span", { class: "mana-pill" }, [
        el("b", { text: `${land.quantity}× ` }),
        cardLink(land.name),
      ]));
    }
    g.append(pills);
    frag.append(g);
  }

  // ---- Validation + combo upgrades (editable; opens if a combo is available) ----
  if (d.validation) {
    const nearMiss = comboNearMissCount(d.validation);
    const details = el("details", { class: "collapsible" });
    if (nearMiss) details.setAttribute("open", "");
    const worst = worstOfAnalysis(d.validation);
    details.append(el("summary", { html: nearMiss
      ? `Validation &amp; combo upgrades &mdash; <span class="muted">${nearMiss} one-card-away combo${nearMiss === 1 ? "" : "s"} (${esc(worst)})</span>`
      : `Validation summary &mdash; <span class="muted">built deck self-check (${esc(worst)})</span>` }));
    editedBanner = el("div", { class: "banner edited-banner", hidden: "", text:
      "Decklist edited here — the card breakdown above still reflects the original build. Use Save deck or Copy decklist to keep your changes." });
    details.append(editedBanner);
    validationBody = el("div", { class: "validation-body" });
    validationBody.append(renderAnalysis(d.validation, true, buildCtx, builtArena));
    details.append(validationBody);
    frag.append(details);
  }

  // ---- Full decklist (collapsible) with Copy ----
  if (d.decklist) {
    const details = el("details", { class: "collapsible" });
    details.append(el("summary", { text: "Full decklist" }));
    copyTextarea = el("textarea", { class: "textarea", readonly: "", rows: "16", "aria-label": "Full decklist" });
    copyTextarea.value = state.decklist;
    details.append(copyTextarea);
    const status = el("span", { class: "copy-status", role: "status", "aria-live": "polite" });
    const copyBtn = el("button", { type: "button", class: "btn btn--small", text: "Copy decklist",
      onclick: async () => {
        try {
          await navigator.clipboard.writeText(state.decklist);
          status.textContent = "Copied!";
        } catch {
          copyTextarea.select();
          status.textContent = document.execCommand?.("copy") ? "Copied!" : "Press Ctrl/Cmd+C to copy.";
        }
        setTimeout(() => (status.textContent = ""), 2500);
      } });
    details.append(el("div", { class: "copy-row" }, [copyBtn, status]));
    frag.append(details);
  }

  return frag;
}

/** Worst severity across an analysis payload's sections (for the summary label). */
function worstOfAnalysis(a) {
  const rank = { problem: 0, warn: 1, info: 2, ok: 3 };
  let worst = "ok";
  for (const s of a.sections || []) {
    if (rank[s.worst_severity] < rank[worst]) worst = s.worst_severity;
  }
  return worst;
}

/** How many one-card-away combos an analysis payload reports. */
function comboNearMissCount(a) {
  const s = (a.sections || []).find((x) => x.title === "Combos & Win Lines");
  return s && s.data ? (s.data.near_miss_count || 0) : 0;
}

/** Load a decklist into the Analyze tab and run it (used by build + saved decks). */
function sendToAnalyze(decklist) {
  location.hash = "#analyze";
  // Let the route switch render the Analyze view before filling + submitting.
  setTimeout(() => {
    const input = $("#analyze-input");
    if (input) { input.value = decklist; $("#analyze-form").requestSubmit(); }
  }, 40);
}

/* ---------- Shared bits --------------------------------------------------- */
function loadingNode(label) {
  return el("div", { class: "loading" }, [
    el("div", { class: "spinner", "aria-hidden": "true" }),
    el("span", { text: label }),
  ]);
}

/* =============================================================================
   ROUTER
   ========================================================================== */
/* =============================================================================
   SAVED DECKS
   ========================================================================== */

/** Inline "Save deck" control appended to analyze/build results. */
function saveBar(decklist, opts = {}) {
  const { commander, bracket } = opts;
  const wrap = el("div", { class: "save-bar" });
  const btn = el("button", { type: "button", class: "btn btn--ghost",
    text: "★ Save deck",
    onclick: () => {
      wrap.innerHTML = "";
      const input = el("input", { class: "input save-bar__input", type: "text",
        value: commander || "My deck", "aria-label": "Deck name" });
      const doSave = async () => {
        try {
          await api("/api/decks", { method: "POST", body: JSON.stringify({
            name: input.value.trim() || "My deck", decklist, commander, bracket,
          }) });
          wrap.innerHTML = "";
          wrap.append(el("span", { class: "save-bar__done", text: "✓ Saved to My Decks" }));
        } catch (err) { showToast(err.message); }
      };
      const save = el("button", { type: "button", class: "btn btn--primary", text: "Save", onclick: doSave });
      const cancel = el("button", { type: "button", class: "btn btn--ghost", text: "Cancel",
        onclick: () => wrap.replaceWith(saveBar(decklist, opts)) });
      input.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); doSave(); } });
      wrap.append(input, save, cancel);
      input.focus(); input.select();
    },
  });
  wrap.append(btn);
  return wrap;
}

async function loadDecks() {
  const out = $("#decks-list");
  out.innerHTML = "";
  out.append(loadingNode("Loading your decks…"));
  try {
    const decks = await api("/api/decks");
    out.innerHTML = "";
    if (!decks.length) {
      out.append(el("div", { class: "banner banner--empty",
        text: "No saved decks yet. Build or analyze a deck, then click “Save deck”." }));
      return;
    }
    const list = el("div", { class: "deck-cards" });
    decks.forEach((d) => list.append(renderDeckRow(d)));
    out.append(list);
  } catch (err) {
    out.innerHTML = "";
    out.append(el("div", { class: "banner banner--empty", text: err.message }));
  }
}

function renderDeckRow(d) {
  const meta = [d.commander || "no commander", `${d.card_count} cards`,
    d.bracket ? `bracket ${d.bracket}` : null].filter(Boolean).join("  ·  ");
  return el("div", { class: "deck-card" }, [
    el("div", { class: "deck-card__main" }, [
      el("div", { class: "deck-card__name", text: d.name }),
      el("div", { class: "deck-card__meta", text: meta }),
    ]),
    el("div", { class: "deck-card__actions" }, [
      el("button", { type: "button", class: "btn btn--ghost", text: "Open",
        onclick: () => openSavedDeck(d.id) }),
      el("button", { type: "button", class: "btn btn--ghost", text: "Rename",
        onclick: () => renameSavedDeck(d) }),
      el("button", { type: "button", class: "btn btn--ghost btn--danger", text: "Delete",
        onclick: () => deleteSavedDeck(d) }),
    ]),
  ]);
}

async function openSavedDeck(id) {
  try {
    const d = await api(`/api/decks/${id}`);
    sendToAnalyze(d.decklist);
  } catch (err) { showToast(err.message); }
}

async function renameSavedDeck(d) {
  const name = window.prompt("Rename deck:", d.name);
  if (name == null) return;
  try {
    await api(`/api/decks/${d.id}`, { method: "PUT", body: JSON.stringify({ name }) });
    loadDecks();
  } catch (err) { showToast(err.message); }
}

async function deleteSavedDeck(d) {
  if (!window.confirm(`Delete “${d.name}”? This can't be undone.`)) return;
  try {
    await api(`/api/decks/${d.id}`, { method: "DELETE" });
    loadDecks();
  } catch (err) { showToast(err.message); }
}

const ROUTES = ["home", "card", "analyze", "build", "decks"];
const VIEWS = {
  home: $("#view-home"),
  card: $("#view-card"),
  analyze: $("#view-analyze"),
  build: $("#view-build"),
  decks: $("#view-decks"),
};

function currentRoute() {
  const hash = (location.hash || "#home").replace(/^#/, "");
  return ROUTES.includes(hash) ? hash : "home";
}

function router() {
  const route = currentRoute();
  clearToast();

  // Show/hide views
  for (const [name, node] of Object.entries(VIEWS)) node.hidden = name !== route;

  // Nav active state
  $$(".nav__link").forEach((link) =>
    link.setAttribute("aria-current", link.dataset.route === route ? "page" : "false")
  );

  // Lazy-init the active view's controller
  if (route === "home") initHome();
  else if (route === "card") { initCard(); $("#card-search")?.focus(); }
  else if (route === "analyze") initAnalyze();
  else if (route === "build") initBuild();
  else if (route === "decks") loadDecks();

  window.scrollTo({ top: 0, behavior: "instant" in window ? "instant" : "auto" });
}

window.addEventListener("hashchange", router);

/* ---------- Mobile hamburger nav ------------------------------------------ */
const navToggle = $("#nav-toggle");
const primaryNav = $("#primary-nav");
function closeNav() {
  if (!primaryNav) return;
  primaryNav.classList.remove("nav--open");
  navToggle?.setAttribute("aria-expanded", "false");
}
if (navToggle && primaryNav) {
  navToggle.addEventListener("click", () => {
    const open = primaryNav.classList.toggle("nav--open");
    navToggle.setAttribute("aria-expanded", String(open));
  });
  // Choosing a destination closes the menu.
  primaryNav.addEventListener("click", (e) => {
    if (e.target.closest(".nav__link")) closeNav();
  });
  // Escape closes and returns focus to the toggle.
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && primaryNav.classList.contains("nav--open")) {
      closeNav();
      navToggle.focus();
    }
  });
}

/* ---------- Boot ---------------------------------------------------------- */
initTheme();
if (!location.hash) location.hash = "#home";
router();

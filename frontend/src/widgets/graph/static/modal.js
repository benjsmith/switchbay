/* Forked from curiosity-engine's wiki-view (MIT License, Copyright (c)
 * 2026 curiosity-engine authors). Adapted for switchbay. See
 * docs/THIRD-PARTY-NOTICES.md. */

/* Doc viewer modal.
 *
 * open(pageId) populates the title + properties + body, sets
 * body[data-modal=open] to fade graph + sidebar, and shows the modal.
 * close() hides + clears state. Clicking the backdrop or the X button
 * closes; ESC also closes.
 */
import { sanitizeHtml } from "../../../lib/sanitizeHtml";
import { isCollapsibleList, readSourcesOpen, writeSourcesOpen } from "../../editor/previewLists";
import { classifySourceRef, normalizeWorkspacePath } from "../../../lib/localPath";

window.Modal = (function () {
  let pages = {};
  let modal, backdrop, closeBtn, titleEl, propsEl, bodyEl, slidesBtn;
  let onClose = null;
  let currentPageId = null;

  // Slideshow button is only meaningful for prose pages — figures and
  // tables don't carry heading structure, so we hide it for those types
  // instead of failing on click.
  const SLIDES_HIDDEN_TYPES = new Set(['figure', 'table']);

  function init(data) {
    pages = data.pages || {};
    modal = document.querySelector('#modal');
    backdrop = document.querySelector('#modal-backdrop');
    closeBtn = document.querySelector('#modal-close');
    titleEl = document.querySelector('#modal-title');
    propsEl = document.querySelector('#modal-properties');
    bodyEl = document.querySelector('#modal-body');
    slidesBtn = document.querySelector('#modal-slides');

    backdrop.addEventListener('click', close);
    closeBtn.addEventListener('click', close);
    if (slidesBtn) slidesBtn.addEventListener('click', onSlidesClick);
    document.addEventListener('keydown', (ev) => {
      if (ev.key === 'Escape' && document.body.dataset.modal === 'open') {
        close();
      }
    });

    // Body wikilink delegation — clicking a wikilink swaps the modal
    // to that page without closing.
    bodyEl.addEventListener('click', (ev) => {
      const a = ev.target.closest && ev.target.closest('a.wikilink');
      if (!a) return;
      ev.preventDefault();
      if (a.classList.contains('unresolved')) return;
      const target = a.dataset.page;
      if (target) {
        window.location.hash = '#page=' + encodeURIComponent(target);
      }
    });

    // Frontmatter sources → OS default app (Preview / browser / …).
    propsEl.addEventListener('click', (ev) => {
      const a = ev.target.closest && ev.target.closest('a.sy-source-cite');
      if (!a) return;
      const path = a.getAttribute('data-open-path');
      if (!path) return;
      ev.preventDefault();
      ev.stopPropagation();
      void openNative(path);
    });
  }

  function open(pageId) {
    const page = pages[pageId];
    if (!page) {
      console.warn('Modal: unknown page', pageId);
      return false;
    }
    currentPageId = pageId;
    titleEl.textContent = page.title || pageId;
    renderProperties(page);
    // body_html is CE-rendered from agent/user-authored markdown and can
    // carry raw HTML; sanitize before injecting (same-origin daemon has
    // fs/shell authority — see lib/sanitizeHtml).
    bodyEl.innerHTML = sanitizeHtml(page.body_html || '');
    // KaTeX pass: walk the rendered body for $…$ / $$…$$ math
    // and render in-place. CE's wiki_render emits the math as raw
    // text — we render client-side so source files stay plain
    // markdown. Best-effort: a bad LaTeX string logs and leaves
    // the raw text alone, rather than crashing the modal.
    if (window.renderMathInElement) {
      try {
        window.renderMathInElement(bodyEl, {
          delimiters: [
            { left: '$$', right: '$$', display: true },
            { left: '\\[', right: '\\]', display: true },
            { left: '$', right: '$', display: false },
            { left: '\\(', right: '\\)', display: false },
          ],
          throwOnError: false,
          ignoredTags: ['script', 'noscript', 'style', 'textarea', 'pre', 'code'],
        });
      } catch (e) {
        console.warn('Modal: KaTeX render failed', e);
      }
    }
    // Drop a "↗ Sheet" button before every <table> in the body so
    // the user can swap any markdown table into the Sheet tab —
    // same affordance the Editor's preview has. Cross-boundary
    // bridge via the `sy:open-as-sheet` custom event because the
    // modal is vanilla JS and the Sheet tab lives in React-land.
    attachTableLinkouts(bodyEl, page.path || pageId);
    modal.classList.remove('hidden');
    backdrop.classList.remove('hidden');
    modal.setAttribute('aria-hidden', 'false');
    backdrop.setAttribute('aria-hidden', 'false');
    document.body.dataset.modal = 'open';
    bodyEl.parentElement.scrollTop = 0;
    if (window.Subgraph) Subgraph.render(pageId);
    if (window.Edit) Edit.updateForPage(page);
    if (slidesBtn) {
      const hide = SLIDES_HIDDEN_TYPES.has(String(page.type || ''));
      slidesBtn.style.display = hide ? 'none' : '';
      slidesBtn.dataset.mode = 'slideshow';
      slidesBtn.setAttribute(
        'title',
        'Create an HTML slideshow from this doc',
      );
      slidesBtn.setAttribute('aria-label', 'Make HTML slideshow');
    }
    return true;
  }

  /* Resolve the wiki path for the currently-open page, normalising
   * the optional `wiki/` prefix. */
  function currentDocPath() {
    if (!currentPageId) return null;
    const page = pages[currentPageId];
    if (!page) return null;
    let docPath = page.path || '';
    if (docPath && !docPath.startsWith('wiki/')) {
      docPath = 'wiki/' + docPath;
    }
    return docPath || null;
  }

  /* Create an HTML slideshow from this doc and open the Slideshow tab.
   * Legacy `kind: deck` wiki pages are treated the same way: their
   * member sketches stay in the Sketch library. */
  async function onSlidesClick() {
    const docPath = currentDocPath();
    if (!docPath) {
      console.warn('Modal: page has no path; cannot build slideshow');
      return;
    }
    slidesBtn.disabled = true;
    try {
      const r = await fetch('/api/slideshows/from-md', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: docPath, open: true, generate_media: false }),
      });
      if (!r.ok) {
        console.warn('Modal: slideshow from-md failed', r.status);
        return;
      }
      const body = await r.json();
      if (!body || !body.slug) return;
      window.dispatchEvent(new CustomEvent('sy:open-as-slideshow', {
        detail: { slug: body.slug, title: body.title || body.slug },
      }));
    } catch (e) {
      console.warn('Modal: slideshow scaffold crashed', e);
    } finally {
      slidesBtn.disabled = false;
    }
  }

  /* Refresh the cached `pages` dict (called after a successful edit
   * so the modal shows the rebuilt body_html on next open). */
  function refresh(data) { pages = data.pages || {}; }

  function close() {
    currentPageId = null;
    modal.classList.add('hidden');
    backdrop.classList.add('hidden');
    modal.setAttribute('aria-hidden', 'true');
    backdrop.setAttribute('aria-hidden', 'true');
    document.body.dataset.modal = '';
    if (window.Subgraph) Subgraph.clear();
    if (typeof onClose === 'function') onClose();
    // Strip the page=… part of the hash if present, so closing leaves
    // a clean URL the user can bookmark for the graph view.
    if (window.location.hash.startsWith('#page=')) {
      history.replaceState(null, '', window.location.pathname);
    }
  }

  /* setOnClose registers a *persistent* close listener (not one-shot).
   * main.js uses this to clear the graph focus on every close. */
  function setOnClose(cb) { onClose = cb; }

  /* Inject a "↗ Sheet" button before every <table> rendered into
   * the modal body. Click → parse the table into a 2-D array,
   * dispatch `sy:open-as-sheet` with the values + a breadcrumb
   * origin so App.tsx can set the selection + switch to the
   * Sheet tab. */
  function attachTableLinkouts(root, originHint) {
    if (!root || !root.querySelectorAll) return;
    root.querySelectorAll('.sy-mdview-table-linkout, .sy-mdview-table-linkout-row')
      .forEach((b) => b.remove());
    const tables = root.querySelectorAll('table');
    tables.forEach((table, i) => {
      const row = document.createElement('div');
      row.className = 'sy-mdview-table-linkout-row';

      const sheetBtn = document.createElement('button');
      sheetBtn.type = 'button';
      sheetBtn.className = 'sy-mdview-table-linkout';
      sheetBtn.textContent = '↗ Sheet';
      sheetBtn.title = 'Open this table in the Sheet tab for editing';
      sheetBtn.addEventListener('click', (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        const values = parseTableValues(table);
        if (!values.length) return;
        window.dispatchEvent(new CustomEvent('sy:open-as-sheet', {
          detail: {
            origin: (originHint || 'graph-modal') + '#table-' + (i + 1),
            values,
          },
        }));
      });
      row.appendChild(sheetBtn);

      // ↗ Plot — kicks an agent run that authors Vega-Lite plots
      // from this table's values. Same cross-boundary pattern as
      // the Sheet linkout: dispatch + React handles the rest.
      const plotBtn = document.createElement('button');
      plotBtn.type = 'button';
      plotBtn.className = 'sy-mdview-table-linkout';
      plotBtn.textContent = '↗ Plot';
      plotBtn.title = 'Ask the agent to author Vega-Lite plots from this table';
      plotBtn.addEventListener('click', async (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        const values = parseTableValues(table);
        if (!values.length) return;
        plotBtn.disabled = true;
        const origin = (originHint || 'graph-modal') + '#table-' + (i + 1);
        try {
          // Existence check — skip the agent run if this table
          // already has plots tagged with the same origin. The
          // Plot tab's right-click → "Regenerate with edits…" is
          // the path for asking for changes; this avoids
          // duplicate plots when a user re-clicks ↗ Plot.
          let already = false;
          try {
            const list = await fetch('/api/plots').then((r) => r.ok ? r.json() : null);
            const matches = (list && list.plots ? list.plots : []).filter(
              (p) => p && p.origin === origin,
            );
            if (matches.length > 0) already = true;
          } catch (_) { /* fall through */ }
          if (already) {
            window.dispatchEvent(new CustomEvent('sy:switch-tab-kind', {
              detail: { kind: 'vega' },
            }));
            return;
          }
          const body = await fetch('/api/plots/from-table', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ origin, values }),
          }).then((r) => r.json());
          if (body && body.run_id) {
            window.dispatchEvent(new CustomEvent('sy:rail-system-tip', {
              detail: {
                text:
                  'Plotting from `' + origin + '` — the agent is '
                  + 'authoring 2-4 Vega-Lite plots from the table. '
                  + 'Watch them land in the Plot tab, or open the '
                  + 'Agents tab to follow the transcript (run `'
                  + body.run_id + '`).',
                focus: false,
              },
            }));
            window.dispatchEvent(new CustomEvent('sy:switch-tab-kind', {
              detail: { kind: 'vega' },
            }));
          } else {
            console.warn('Modal: from-table failed', body);
          }
        } catch (e) {
          console.warn('Modal: from-table crashed', e);
        } finally {
          plotBtn.disabled = false;
        }
      });
      row.appendChild(plotBtn);

      table.parentNode && table.parentNode.insertBefore(row, table);
    });
  }

  function parseTableValues(table) {
    const rows = [];
    const headRow = table.tHead && table.tHead.rows && table.tHead.rows[0];
    if (headRow) {
      const cells = [];
      for (let i = 0; i < headRow.cells.length; i++) {
        cells.push((headRow.cells[i].textContent || '').trim());
      }
      rows.push(cells);
    }
    const bodies = table.tBodies || [];
    for (let bi = 0; bi < bodies.length; bi++) {
      const tbody = bodies[bi];
      for (let ri = 0; ri < tbody.rows.length; ri++) {
        const tr = tbody.rows[ri];
        const cells = [];
        for (let ci = 0; ci < tr.cells.length; ci++) {
          const text = (tr.cells[ci].textContent || '').trim();
          // Match Editor's coercion: digit-shaped cells go in as
          // numbers so the Sheet treats them numerically.
          if (/^-?\d+(?:\.\d+)?$/.test(text)) {
            cells.push(Number(text));
          } else {
            cells.push(text);
          }
        }
        rows.push(cells);
      }
    }
    return rows;
  }

  function renderProperties(page) {
    const rows = [];
    rows.push(propRow('title', page.title, 'list'));
    rows.push(propRow('type',  page.type,  'list'));
    const props = page.properties || {};
    const order = ['created', 'updated', 'sources'];
    const seen = new Set(['title', 'type']);
    for (const key of order) {
      if (key in props) {
        rows.push(propRow(key, props[key], iconForKey(key)));
        seen.add(key);
      }
    }
    for (const [k, v] of Object.entries(props)) {
      if (seen.has(k)) continue;
      rows.push(propRow(k, v, 'list'));
    }
    propsEl.innerHTML = rows.join('');
    propsEl.querySelectorAll("details.sy-prop-list").forEach((el) => {
      el.addEventListener("toggle", () => writeSourcesOpen(el.open));
    });
  }

  function openNative(path) {
    return fetch("/api/fs/open-external", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
    }).then(async (r) => {
      if (!r.ok) {
        const b = await r.json().catch(() => ({}));
        window.alert("Couldn't open: " + (b.error || r.status));
      }
    }).catch((e) => {
      window.alert("Couldn't open: " + (e && e.message ? e.message : e));
    });
  }

  function propRow(key, value, iconKind) {
    const v = formatValue(value, key);
    const icon = renderIcon(iconKind);
    return `<tr>
      <td class="prop-key">${icon}<span>${escapeHtml(key)}</span></td>
      <td class="prop-val">${v}</td>
    </tr>`;
  }

  function iconForKey(k) {
    if (k === 'created' || k === 'updated') return 'calendar';
    return 'list';
  }

  function renderIcon(kind) {
    if (kind === 'calendar') {
      return `<span class="prop-icon"><svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"><rect x="2.5" y="3.5" width="11" height="10" rx="1.5"/><line x1="2.5" y1="6.5" x2="13.5" y2="6.5"/><line x1="5.5" y1="2.5" x2="5.5" y2="4.5"/><line x1="10.5" y1="2.5" x2="10.5" y2="4.5"/></svg></span>`;
    }
    return `<span class="prop-icon"><svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"><line x1="3" y1="5" x2="13" y2="5"/><line x1="3" y1="8" x2="13" y2="8"/><line x1="3" y1="11" x2="13" y2="11"/></svg></span>`;
  }

  function formatSourceRef(item, forceLocal) {
    const raw = String(item);
    const kind = classifySourceRef(raw) || (forceLocal && normalizeWorkspacePath(raw) ? "local" : null);
    if (kind === "url") {
      return (
        `<a class="sy-source-cite" href="${escapeHtml(raw)}" `
        + `target="_blank" rel="noreferrer">${escapeHtml(raw)}</a>`
      );
    }
    if (kind === "local") {
      const path = normalizeWorkspacePath(raw) || raw;
      return (
        `<a class="sy-source-cite" href="#file=${encodeURIComponent(path)}" `
        + `data-open-path="${escapeHtml(path)}" `
        + `title="Open with the system default app">${escapeHtml(raw)}</a>`
      );
    }
    return escapeHtml(raw);
  }

  function formatValue(v, key) {
    if (v == null) return '<span style="color:var(--text-faint)">—</span>';
    const forceLocal = key === "sources" || key === "extracted_from";
    if (isCollapsibleList(key, v)) {
      const open = readSourcesOpen() ? " open" : "";
      const items = v.map((item) => `<div>${formatSourceRef(item, true)}</div>`).join("");
      return `<details class="sy-prop-list"${open}><summary>${v.length} sources</summary>${items}</details>`;
    }
    if (Array.isArray(v)) {
      return v.map((item) => `<div>${formatSourceRef(item, forceLocal)}</div>`).join("");
    }
    return formatSourceRef(v, forceLocal);
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"]/g, c =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  }

  return { init, open, close, setOnClose, refresh };
})();

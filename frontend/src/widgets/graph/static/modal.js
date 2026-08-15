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

window.Modal = (function () {
  let pages = {};
  let modal, backdrop, closeBtn, titleEl, propsEl, bodyEl, slidesBtn;
  let onClose = null;
  let currentPageId = null;

  // Slides button is only meaningful for prose pages — figures and
  // tables don't carry the heading structure the from-doc scaffold
  // walks, so we hide it for those types instead of failing on click.
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
      // Two title-prefix shapes determine the affordance:
      //   · `[deck] …` → existing Sketch (Excalidraw) deck. Button
      //                  opens it in the Sketch tab.
      //   · anything else (analyses, prose pages) → scaffold a new
      //                  Sketch deck from this doc's headings.
      const lowered = String(page.title || '').trim().toLowerCase();
      const isSketchDeck = lowered.startsWith('[deck]');
      slidesBtn.style.display = hide ? 'none' : '';
      slidesBtn.dataset.mode = isSketchDeck ? 'open-deck' : 'scaffold';
      slidesBtn.setAttribute(
        'title',
        isSketchDeck
          ? 'Open this Sketch deck in the Sketch tab'
          : 'Scaffold a Sketch deck from this doc',
      );
      slidesBtn.setAttribute(
        'aria-label',
        isSketchDeck ? 'Open Sketch deck' : 'Make sketch deck',
      );
    }
    return true;
  }

  /* Resolve the wiki path for the currently-open page, normalising
   * the optional `wiki/` prefix. Shared between the reveal.js and
   * Sketch-deck button handlers. */
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

  /* On a Sketch-deck page (kind: deck): open the existing deck in the
   * Sketch tab. Otherwise: scaffold a new Sketch deck from this doc's
   * headings and route the user into Sketcher, then kick the
   * autopopulate agent against the new deck.
   *
   * The vanilla-JS world doesn't know about React state — we bridge
   * via the same `sy:open-as-deck` / `sy:register-deck-run` custom
   * events the rest of the app uses. */
  async function onSlidesClick() {
    const docPath = currentDocPath();
    if (!docPath) {
      console.warn('Modal: page has no path; cannot scaffold deck');
      return;
    }
    slidesBtn.disabled = true;
    try {
      if (slidesBtn.dataset.mode === 'open-deck') {
        try {
          const existing = await fetch(
            `/api/analysis?path=${encodeURIComponent(docPath)}`,
          );
          if (existing.ok) {
            const ej = await existing.json();
            const a = ej && ej.analysis;
            if (a) {
              window.dispatchEvent(new CustomEvent('sy:open-as-deck', {
                detail: { path: a.path, title: a.title, slug: a.slug, analysis: a },
              }));
            }
          }
        } catch (_) { /* fall through */ }
        return;
      }
      const r = await fetch('/api/analysis/from-doc', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: docPath }),
      });
      if (!r.ok) {
        console.warn('Modal: from-doc failed', r.status);
        return;
      }
      const body = await r.json();
      const a = body.analysis;
      if (!a) return;
      window.dispatchEvent(new CustomEvent('sy:open-as-deck', {
        detail: { path: a.path, title: a.title, slug: a.slug, analysis: a },
      }));
      try {
        const pop = await fetch('/api/analysis/populate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ analysis_path: a.path }),
        });
        if (pop.ok) {
          const pj = await pop.json();
          if (pj && pj.run_id) {
            window.dispatchEvent(new CustomEvent('sy:register-deck-run', {
              detail: { analysis_path: a.path, run_id: pj.run_id },
            }));
          }
        }
      } catch (e) { console.warn('Modal: populate failed', e); }
    } catch (e) {
      console.warn('Modal: sketch-deck scaffold crashed', e);
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

  function formatValue(v, key) {
    if (v == null) return '<span style="color:var(--text-faint)">—</span>';
    if (isCollapsibleList(key, v)) {
      const open = readSourcesOpen() ? " open" : "";
      const items = v.map((item) => `<div>${escapeHtml(String(item))}</div>`).join("");
      return `<details class="sy-prop-list"${open}><summary>${v.length} sources</summary>${items}</details>`;
    }
    if (Array.isArray(v)) {
      return v.map(item => `<div>${escapeHtml(String(item))}</div>`).join('');
    }
    return escapeHtml(String(v));
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"]/g, c =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  }

  return { init, open, close, setOnClose, refresh };
})();

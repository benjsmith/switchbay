/* Forked from curiosity-engine's wiki-view (MIT License, Copyright (c)
 * 2026 curiosity-engine authors). Adapted for switchbay. See
 * docs/THIRD-PARTY-NOTICES.md. */

/* Sidebar: blazingly responsive search + type-grouped page list with
 * collapsible sections.
 *
 * Idle state: pages grouped by type, each group with a header (label +
 * count + chevron). Click header to collapse/expand. Within a group,
 * entries are alphabetical.
 *
 * Search active: groups dissolve into a flat ranked list (Fuse.js).
 * Empty query restores the grouped view.
 */
window.Sidebar = (function () {
  // Frontmatter uses singular type names (entity, fact, …); the plural
  // form occasionally leaks in. Canonicalise to the singular so a page
  // typed `entity` and one typed `entities` end up in the same section.
  // Order is the human reading order; unknown types fall to alphabetical.
  const TYPE_CANONICAL = {
    project:      'project',      projects: 'project',
    analysis:     'analysis',     analyses: 'analysis',
    concept:      'concept',      concepts: 'concept',
    entity:       'entity',       entities: 'entity',
    evidence:     'evidence',
    fact:         'fact',         facts:    'fact',
    figure:       'figure',       figures:  'figure',
    table:        'table',        tables:   'table',
    source:       'source',       sources:  'source',
    note:         'note',         notes:    'note',
    todo:         'todo-list',    'todo-list': 'todo-list',
    unclassified: 'unclassified',
  };
  // Order matches the label-types panel in the graph view (top-bar
  // dialog). Issue 23 — sidebar should follow the same canonical
  // ordering so categories appear in consistent positions across
  // surfaces.
  // Mirrors CE's wiki-view TYPE_ORDER so the same workspace reads
  // consistently across Switch Bay and the upstream viewer (CE
  // canonical: project → analysis → concept → entity → evidence
  // → fact → figure → table → source → note → todo-list →
  // unclassified).
  const TYPE_ORDER = [
    'project', 'analysis', 'concept', 'entity', 'evidence', 'fact',
    'figure', 'table', 'source', 'note', 'todo-list', 'unclassified',
  ];
  const TYPE_LABEL = {
    project:      'Projects',
    concept:      'Concepts',
    entity:       'Entities',
    evidence:     'Evidence',
    fact:         'Facts',
    analysis:     'Analyses',
    figure:       'Figures',
    table:        'Tables',
    source:       'Sources',
    note:         'Notes',
    'todo-list':  'Todos',
    unclassified: 'Unclassified',
  };
  function canonicalType(t) {
    return TYPE_CANONICAL[t] || t || 'default';
  }

  let listEl, searchEl, fuse, allRecords, allPages;
  let collapsed = new Set();   // type names currently collapsed

  function init(data) {
    listEl = document.querySelector('#sidebar-list');
    searchEl = document.querySelector('#sidebar-search');
    allPages = data.pages || {};

    allRecords = data.nodes.map(n => {
      const page = allPages[n.id] || {};
      const props = Object.values(page.properties || {})
        .map(v => Array.isArray(v) ? v.join(' ') : String(v))
        .join(' ');
      return { id: n.id, title: n.title || n.id, type: n.type, props };
    });
    fuse = new Fuse(allRecords, {
      keys: [
        { name: 'title', weight: 0.7 },
        { name: 'type',  weight: 0.1 },
        { name: 'props', weight: 0.2 },
      ],
      threshold: 0.35,
      ignoreLocation: true,
      minMatchCharLength: 1,
    });

    // Restore collapsed state from localStorage so it survives reloads.
    try {
      const stored = JSON.parse(localStorage.getItem('curiosity-engine.collapsed-types') || '[]');
      collapsed = new Set(stored);
    } catch (e) { collapsed = new Set(); }

    renderGrouped();

    searchEl.addEventListener('input', (ev) => {
      const q = ev.target.value.trim();
      if (!q) { renderGrouped(); return; }
      const results = fuse.search(q, { limit: 200 }).map(r => r.item);
      renderFlat(results);
    });

    // [Switch Bay fork] CE's sidebar collapse/restore block was removed
    // here. The collapse button (#sidebar-toggle) and the restore button
    // were both DOM-mutating against #graph-pane, which only exists when
    // the graph tab is mounted. In Switch Bay the column chrome is owned
    // by the Browser pane, so the in-sidebar collapse UX is unnecessary.
    // Re-introduce a guarded version if/when full collapse is wanted.

    const counts = document.querySelector('#meta-counts');
    if (counts) {
      counts.textContent = `${data.nodes.length} pages · ${(data.edges || []).length} links`;
    }
  }

  /* Grouped (idle) view. Pages clustered by type with a header per group. */
  function renderGrouped() {
    const byType = new Map();
    for (const rec of allRecords) {
      const t = canonicalType(rec.type);
      if (!byType.has(t)) byType.set(t, []);
      byType.get(t).push(rec);
    }
    // Order: known types first (TYPE_ORDER), then any unknown alphabetical.
    const seen = new Set();
    const ordered = [];
    for (const t of TYPE_ORDER) {
      if (byType.has(t) && !seen.has(t)) { ordered.push(t); seen.add(t); }
    }
    for (const t of [...byType.keys()].sort()) {
      if (!seen.has(t)) ordered.push(t);
    }

    const html = ordered.map(t => {
      const recs = byType.get(t).slice().sort((a, b) =>
        a.title.localeCompare(b.title, undefined, { sensitivity: 'base' }));
      const isCollapsed = collapsed.has(t);
      const label = TYPE_LABEL[t] || (t.charAt(0).toUpperCase() + t.slice(1));
      return `<section class="type-group" data-type="${escapeAttr(t)}" data-collapsed="${isCollapsed ? 'true' : 'false'}">
        <button class="type-group-header" data-action="toggle-group" data-type="${escapeAttr(t)}">
          <span class="group-chev"><svg viewBox="0 0 10 10" width="10" height="10"><path d="M2 4 L5 7 L8 4" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg></span>
          <span class="dot dot-${escapeAttr(t)}"></span>
          <span class="type-group-name">${escapeHtml(label)}</span>
          <span class="type-group-count">${recs.length}</span>
        </button>
        <div class="type-group-body">${recs.map(rowHtml).join('')}</div>
      </section>`;
    }).join('');
    listEl.innerHTML = html;
  }

  /* Flat view (during search). */
  function renderFlat(items) {
    listEl.innerHTML = items.map(rowHtml).join('');
  }

  function rowHtml(rec) {
    return `<button class="sidebar-row" data-id="${escapeAttr(rec.id)}" role="option">
      <span class="dot dot-${escapeAttr(rec.type)}"></span>
      <span class="row-title">${escapeHtml(rec.title)}</span>
    </button>`;
  }

  function setActive(pageId) {
    listEl.querySelectorAll('.sidebar-row').forEach(row => {
      row.dataset.active = (row.dataset.id === pageId) ? 'true' : '';
    });
    const active = listEl.querySelector(`.sidebar-row[data-active="true"]`);
    if (active && active.scrollIntoView) {
      active.scrollIntoView({ block: 'nearest' });
    }
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"]/g, c =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  }
  function escapeAttr(s) { return escapeHtml(s); }

  // Click delegation: handle group-toggle buttons and row clicks here.
  document.addEventListener('click', (ev) => {
    // Collapse/expand ALL type groups (the button in the search row).
    // Any group expanded → collapse everything; else expand all.
    // During an active search the list is flat — just persist the
    // state for when the grouped view returns.
    const allBtn = ev.target.closest && ev.target.closest('[data-action="toggle-all-groups"]');
    if (allBtn && allRecords) {
      const types = [...new Set(allRecords.map(r => canonicalType(r.type)))];
      if (!types.length) return;
      const anyExpanded = types.some(t => !collapsed.has(t));
      collapsed = anyExpanded ? new Set(types) : new Set();
      try {
        localStorage.setItem('curiosity-engine.collapsed-types', JSON.stringify([...collapsed]));
      } catch (e) {}
      if (!searchEl || !searchEl.value.trim()) renderGrouped();
      return;
    }
    const header = ev.target.closest && ev.target.closest('[data-action="toggle-group"]');
    if (header) {
      const t = header.dataset.type;
      if (collapsed.has(t)) collapsed.delete(t); else collapsed.add(t);
      try {
        localStorage.setItem('curiosity-engine.collapsed-types', JSON.stringify([...collapsed]));
      } catch (e) {}
      const group = header.closest('.type-group');
      if (group) group.dataset.collapsed = collapsed.has(t) ? 'true' : 'false';
      return;
    }
    const row = ev.target.closest && ev.target.closest('.sidebar-row');
    if (!row) return;
    window.location.hash = '#page=' + encodeURIComponent(row.dataset.id);
  });

  return { init, setActive };
})();

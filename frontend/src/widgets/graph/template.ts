/**
 * HTML body content for the forked CE wiki-view, mounted inside the
 * graph tab. Mirrors curiosity-engine/template/wiki-view/index.html
 * minus the sidebar (which now lives in Switch Bay's Browser column —
 * see Sidebar.tsx) and the editor padlock (the editor lives in its
 * own tab, step D).
 */

export const template = /* html */ `
<main id="graph-pane">
  <div id="graph"></div>
  <div class="graph-controls">
    <button id="viewer-mode" class="ctrl-btn hidden" title="Switch graph viewer" aria-label="Switch graph viewer">
      <span class="ctrl-label">view:</span><span id="viewer-mode-state">classic</span>
    </button>
    <button id="label-mode" class="ctrl-btn" title="Label visibility" aria-label="Label visibility">
      <span class="ctrl-label">labels:</span><span id="label-mode-state">auto</span>
    </button>
    <button id="label-types" class="ctrl-btn" title="Which page types show labels" aria-label="Which page types show labels">
      <span class="ctrl-label">types:</span><span id="label-types-state">4/11</span>
    </button>
    <div id="label-types-panel" class="label-types-panel hidden" role="dialog" aria-label="Label types">
      <div class="label-types-head">Show labels for</div>
      <label class="label-types-row" data-type="project"><input type="checkbox"><span class="dot dot-project"></span><span>Projects</span></label>
      <label class="label-types-row" data-type="concept"><input type="checkbox"><span class="dot dot-concept"></span><span>Concepts</span></label>
      <label class="label-types-row" data-type="entity"><input type="checkbox"><span class="dot dot-entity"></span><span>Entities</span></label>
      <label class="label-types-row" data-type="evidence"><input type="checkbox"><span class="dot dot-evidence"></span><span>Evidence</span></label>
      <label class="label-types-row" data-type="fact"><input type="checkbox"><span class="dot dot-fact"></span><span>Facts</span></label>
      <label class="label-types-row" data-type="analysis"><input type="checkbox"><span class="dot dot-analysis"></span><span>Analyses</span></label>
      <label class="label-types-row" data-type="figure"><input type="checkbox"><span class="dot dot-figure"></span><span>Figures</span></label>
      <label class="label-types-row" data-type="table"><input type="checkbox"><span class="dot dot-table"></span><span>Tables</span></label>
      <label class="label-types-row" data-type="source"><input type="checkbox"><span class="dot dot-source"></span><span>Sources</span></label>
      <label class="label-types-row" data-type="note"><input type="checkbox"><span class="dot dot-note"></span><span>Notes</span></label>
      <label class="label-types-row" data-type="todo"><input type="checkbox"><span class="dot dot-todo"></span><span>Todos</span></label>
      <label class="label-types-row" data-type="unclassified"><input type="checkbox"><span class="dot dot-unclassified"></span><span>Unclassified</span></label>
      <button id="label-types-reset" class="settings-reset">Reset</button>
    </div>
  </div>
  <button id="settings-trigger" class="icon-btn settings-trigger" title="Physics settings" aria-label="Physics settings">
    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
      <path d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"/>
      <circle cx="12" cy="12" r="3"/>
    </svg>
  </button>
  <div id="settings-panel" class="settings-panel hidden" role="dialog" aria-label="Physics settings">
    <div class="settings-head">Physics</div>
    <div class="settings-row">
      <label for="phys-charge">Repulsion</label>
      <input id="phys-charge" type="range" min="-1200" max="-50" step="10" value="-420">
      <span id="phys-charge-val" class="settings-val">-420</span>
    </div>
    <div class="settings-row">
      <label for="phys-link">Link distance</label>
      <input id="phys-link" type="range" min="20" max="300" step="5" value="110">
      <span id="phys-link-val" class="settings-val">110</span>
    </div>
    <div class="settings-row">
      <label for="phys-collide">Collide pad</label>
      <input id="phys-collide" type="range" min="0" max="40" step="1" value="10">
      <span id="phys-collide-val" class="settings-val">10</span>
    </div>
    <button id="phys-reset" class="settings-reset">Reset</button>
  </div>
</main>

<div id="modal-backdrop" class="hidden" aria-hidden="true"></div>
<div id="modal" class="hidden" role="dialog" aria-modal="true" aria-hidden="true" data-tour="node-modal">
  <button id="modal-slides" class="icon-btn modal-slides" title="Scaffold a Sketch deck from this doc" aria-label="Make sketch deck" style="display:none">
    <svg viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">
      <rect x="2.5" y="3.5" width="11" height="7.5" rx="1"/>
      <line x1="5" y1="13.5" x2="11" y2="13.5"/>
      <line x1="8" y1="11" x2="8" y2="13.5"/>
    </svg>
  </button>
  <button id="modal-padlock" class="icon-btn modal-padlock" title="Edit" aria-label="Edit page" data-editing="false" style="display:none">
    <svg class="padlock-closed" viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">
      <rect x="3.5" y="7.5" width="9" height="6" rx="1"/>
      <path d="M5.5 7.5 V5.5 a 2.5 2.5 0 0 1 5 0 V7.5"/>
    </svg>
    <svg class="padlock-open" viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">
      <rect x="3.5" y="7.5" width="9" height="6" rx="1"/>
      <path d="M5.5 7.5 V5.5 a 2.5 2.5 0 0 1 5 0"/>
    </svg>
  </button>
  <button id="modal-close" class="icon-btn modal-close" title="Close" aria-label="Close">
    <svg viewBox="0 0 16 16" width="12" height="12"><line x1="4" y1="4" x2="12" y2="12" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/><line x1="12" y1="4" x2="4" y2="12" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>
  </button>
  <div id="modal-content">
    <h1 id="modal-title"></h1>
    <section class="properties">
      <div class="properties-head">Properties</div>
      <table id="modal-properties"></table>
    </section>
    <article id="modal-body"></article>
    <section class="subgraph-pane">
      <div class="subgraph-head" id="modal-subgraph-head"></div>
      <div id="modal-subgraph"></div>
    </section>
  </div>
</div>
`;

/** CE's sidebar HTML — now mounted in Switch Bay's Browser column.
 *  See sidebar/Sidebar.tsx. */
export const sidebarTemplate = /* html */ `
<aside id="sidebar">
  <div class="sidebar-search-wrap">
    <input id="sidebar-search" type="search" placeholder="Search pages…" autocomplete="off" spellcheck="false">
    <button id="sidebar-toggle-all" class="icon-btn sidebar-toggle-all" data-action="toggle-all-groups" title="Collapse / expand all page types" aria-label="Collapse or expand all page types">
      <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
        <path d="M3 6 L8 2.5 L13 6"/>
        <path d="M3 10 L8 13.5 L13 10"/>
      </svg>
    </button>
    <button id="sidebar-upload" class="icon-btn sidebar-upload" title="Upload to vault — starts background ingest (step J.1)" aria-label="Upload">
      <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
        <line x1="8" y1="3" x2="8" y2="13"/>
        <line x1="3" y1="8" x2="13" y2="8"/>
      </svg>
    </button>
  </div>
  <div id="sidebar-list" class="sidebar-list" role="listbox"></div>
  <footer class="sidebar-foot">
    <span class="meta-counts" id="meta-counts"></span>
  </footer>
</aside>
`;

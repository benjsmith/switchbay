/* Forked from curiosity-engine's wiki-view (MIT License, Copyright (c)
 * 2026 curiosity-engine authors). Adapted for switchbay. See
 * docs/THIRD-PARTY-NOTICES.md. */

/* Edit + upload bridge between the static frontend and viewer_server.py.
 *
 * Two pieces:
 *   1. Vault upload — `+` icon next to the sidebar search opens a file
 *      picker. The chosen file is POSTed as multipart/form-data to
 *      /api/upload-vault, which writes it to vault/raw/.
 *   2. Page edit — padlock icon in the modal header (visible only for
 *      notes/* and todos/* pages). Closed by default ("Edit" tooltip);
 *      click to enter edit mode, swap the rendered article for a raw-
 *      markdown textarea, and surface Save / Cancel buttons. Save
 *      POSTs to /api/page; the server writes the file and rebuilds
 *      data.json so the frontend can refetch and re-render.
 *
 * Public API:
 *   window.Edit = { init(data, refetchData), updateForPage(page) }
 *
 * The host (main.js) supplies a `refetchData` callback so this module
 * doesn't need to know about other modules — after a save we just call
 * it and the host orchestrates the re-render.
 */
window.Edit = (function () {
  let _refetch = null;
  let _currentPage = null;
  let _editing = false;
  let _originalContent = null;

  let modal, articleEl, padlockBtn, padlockTooltip;
  let editorWrap, textareaEl, saveBtn, cancelBtn;
  let toastEl;
  let uploadInput, uploadTrigger;

  function init(data, refetchData) {
    _refetch = refetchData;
    modal = document.querySelector('#modal');
    articleEl = document.querySelector('#modal-body');
    padlockBtn = document.querySelector('#modal-padlock');
    padlockTooltip = padlockBtn;     // tooltip via title attr on the button itself
    uploadTrigger = document.querySelector('#sidebar-upload');
    uploadInput = document.querySelector('#sidebar-upload-input');

    // Build the editor scaffold once and append into modal-content,
    // hidden by default. The Modal module fills #modal-body with HTML;
    // entering edit mode hides #modal-body and reveals #modal-editor.
    const modalContent = document.querySelector('#modal-content');
    if (modalContent && !modalContent.querySelector('#modal-editor')) {
      const wrap = document.createElement('section');
      wrap.id = 'modal-editor';
      wrap.className = 'modal-editor hidden';
      wrap.innerHTML = `
        <textarea class="modal-editor-textarea" spellcheck="false" autocomplete="off"></textarea>
        <div class="modal-editor-actions">
          <button class="modal-editor-cancel" type="button">Cancel</button>
          <button class="modal-editor-save" type="button">Save</button>
        </div>
      `;
      modalContent.appendChild(wrap);
    }
    editorWrap = document.querySelector('#modal-editor');
    textareaEl = editorWrap.querySelector('.modal-editor-textarea');
    saveBtn    = editorWrap.querySelector('.modal-editor-save');
    cancelBtn  = editorWrap.querySelector('.modal-editor-cancel');

    // Toast container (lazy-created on first toast).
    toastEl = null;

    if (padlockBtn) {
      padlockBtn.addEventListener('click', onPadlockClick);
    }
    if (saveBtn)   saveBtn.addEventListener('click', onSave);
    if (cancelBtn) cancelBtn.addEventListener('click', onCancel);
    // Double-click anywhere in the body → enter edit mode. The user
    // expects an inline-edit feel; the lock icon stays as the
    // primary affordance for clicks coming from outside the body
    // (and for the second click that saves out).
    if (articleEl) {
      articleEl.addEventListener('dblclick', (ev) => {
        if (_editing) return;
        if (!_currentPage || !isEditablePage(_currentPage)) return;
        // Don't intercept double-clicks on wiki links / buttons —
        // those have their own meaning. Body prose is fair game.
        const t = ev.target;
        if (t && t.closest && (
          t.closest('a') || t.closest('button') || t.closest('.sy-mdview-table-linkout')
        )) return;
        ev.preventDefault();
        void enterEditMode();
      });
    }

    if (uploadTrigger && uploadInput) {
      uploadTrigger.addEventListener('click', () => uploadInput.click());
      uploadInput.addEventListener('change', onUploadChange);
    }
  }

  /* Called by main.js whenever the modal opens for a page (or the
   * current page changes). Determines whether the padlock should be
   * shown and resets edit state. */
  function updateForPage(page) {
    _currentPage = page || null;
    leaveEditMode();
    const editable = isEditablePage(page);
    if (padlockBtn) {
      padlockBtn.style.display = editable ? '' : 'none';
      padlockBtn.dataset.editing = 'false';
      padlockBtn.title = 'Edit';
    }
  }

  function isEditablePage(page) {
    // [Switch Bay fork] CE only allows editing notes/* and todos/* —
    // we open the padlock to every .md page in the wiki. Daemon's
    // POST /api/page enforces that the path stays under wiki/.
    if (!page) return false;
    const path = page.path || '';
    return path.endsWith('.md');
  }

  // ── Padlock + edit flow ─────────────────────────────────────────
  // Click semantics, by user convention:
  //   · padlock when closed → enter edit mode
  //   · padlock when open → SAVE and leave edit mode (the open
  //     padlock is the "commit" button — Cancel is the only path
  //     that discards). Skips the save round-trip when the buffer
  //     is unchanged.
  async function onPadlockClick() {
    if (!_currentPage) return;
    if (_editing) {
      if (textareaEl.value === _originalContent) {
        // Nothing changed — treat as a no-op close.
        leaveEditMode();
        return;
      }
      await onSave();
      return;
    }
    await enterEditMode();
  }

  async function enterEditMode() {
    if (!_currentPage) return;
    const path = _currentPage.path;
    let content = '';
    try {
      const res = await fetch('/api/page?path=' + encodeURIComponent(path));
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const payload = await res.json();
      content = payload.content || '';
    } catch (e) {
      toast('Could not load source: ' + e.message, 'error');
      return;
    }
    _originalContent = content;
    textareaEl.value = content;
    articleEl.classList.add('hidden');
    editorWrap.classList.remove('hidden');
    _editing = true;
    if (padlockBtn) {
      padlockBtn.dataset.editing = 'true';
      padlockBtn.title = 'Lock';
    }
    // Auto-grow textarea to fit content; cap at modal height.
    autosize();
    textareaEl.focus();
  }

  function leaveEditMode() {
    _editing = false;
    _originalContent = null;
    if (editorWrap) editorWrap.classList.add('hidden');
    if (articleEl)  articleEl.classList.remove('hidden');
    if (padlockBtn) {
      padlockBtn.dataset.editing = 'false';
      padlockBtn.title = 'Edit';
    }
  }

  function onCancel() {
    if (textareaEl.value !== _originalContent) {
      if (!window.confirm('Discard unsaved changes?')) return;
    }
    leaveEditMode();
  }

  async function onSave() {
    if (!_currentPage) return;
    const path = _currentPage.path;
    const content = textareaEl.value;
    saveBtn.disabled = true;
    saveBtn.textContent = 'Saving…';
    try {
      const res = await fetch('/api/page', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path, content }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error || `HTTP ${res.status}`);
      }
      // Server rebuilt the bundle; refetch data.json + re-render the
      // current page.
      if (_refetch) await _refetch(_currentPage.id);
      leaveEditMode();
      toast('Saved');
    } catch (e) {
      toast('Save failed: ' + e.message, 'error');
    } finally {
      saveBtn.disabled = false;
      saveBtn.textContent = 'Save';
    }
  }

  function autosize() {
    textareaEl.style.height = 'auto';
    const max = Math.max(200, window.innerHeight * 0.7);
    textareaEl.style.height = Math.min(max, textareaEl.scrollHeight + 4) + 'px';
  }

  // ── Vault upload ─────────────────────────────────────────────────
  async function onUploadChange(ev) {
    const files = ev.target.files;
    if (!files || files.length === 0) return;
    const form = new FormData();
    for (const f of files) form.append('file', f, f.name);
    try {
      const res = await fetch('/api/upload-vault', { method: 'POST', body: form });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error || `HTTP ${res.status}`);
      }
      const payload = await res.json();
      const names = (payload.saved || []).join(', ');
      toast(`Uploaded ${names || 'file'} to vault/raw/`);
    } catch (e) {
      toast('Upload failed: ' + e.message, 'error');
    } finally {
      ev.target.value = '';   // allow re-selecting the same file
    }
  }

  // ── Toast ────────────────────────────────────────────────────────
  function toast(msg, kind) {
    if (!toastEl) {
      toastEl = document.createElement('div');
      toastEl.id = 'edit-toast';
      toastEl.className = 'edit-toast';
      document.body.appendChild(toastEl);
    }
    toastEl.textContent = msg;
    toastEl.dataset.kind = kind === 'error' ? 'error' : 'ok';
    toastEl.classList.add('visible');
    clearTimeout(toast._timer);
    toast._timer = setTimeout(() => {
      toastEl.classList.remove('visible');
    }, 2400);
  }

  return { init, updateForPage };
})();

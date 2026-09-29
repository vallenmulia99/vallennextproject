class EditorManager {
  constructor() {
    this.monaco = null;
    this.editor = null;
    this.diffEditor = null;
    this.openTabs = new Map();
    this.activePath = null;
    this.diffActive = false;
    this.activeDiffData = null;
    this.historyList = [];
    this.historyIndex = -1;
  }

  normalizePath(rawPath) {
    if (!rawPath) return "";
    let p = String(rawPath).trim().replace(/\\/g, '/');
    const titleEl = document.getElementById('sidebar-project-title');
    const projName = titleEl ? titleEl.textContent.trim().toLowerCase() : "";

    if (p.startsWith('/') && projName && projName !== 'explorer') {
      const parts = p.split('/');
      const lowerParts = parts.map(s => s.toLowerCase());
      const idx = lowerParts.lastIndexOf(projName);
      if (idx !== -1 && idx < parts.length - 1) {
        p = parts.slice(idx + 1).join('/');
      }
    }
    return p.replace(/^\/+/, '');
  }

  async init() {
    return new Promise((resolve) => {
      require.config({ paths: { vs: 'https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.45.0/min/vs' } });
      require(['vs/editor/editor.main'], () => {
        this.monaco = window.monaco;

        this.monaco.editor.defineTheme('vscode-dark-modern', {
          base: 'vs-dark',
          inherit: true,
          rules: [
            { token: 'comment', foreground: '6e7681', fontStyle: 'italic' },
            { token: 'keyword', foreground: 'ff7b72', fontStyle: 'bold' },
            { token: 'string', foreground: 'a5d6ff' },
            { token: 'number', foreground: '79c0ff' },
            { token: 'type', foreground: 'ffa657' },
            { token: 'function', foreground: 'd2a8ff' }
          ],
          colors: {
            'editor.background': '#1e1e1e',
            'editor.foreground': '#cccccc',
            'editor.lineHighlightBackground': '#282828',
            'editorLineNumber.foreground': '#6e7681',
            'editorLineNumber.activeForeground': '#cccccc',
            'editor.selectionBackground': '#04395e',
            'editorCursor.foreground': '#ffffff',
            'editorIndentGuide.background': '#2d2d2d',
            'editorIndentGuide.activeBackground': '#404040'
          }
        });

        const container = document.getElementById('editor-container');
        this.editor = this.monaco.editor.create(container, {
          theme: 'vscode-dark-modern',
          automaticLayout: true,
          fontFamily: "'JetBrains Mono', 'Fira Code', Menlo, Monaco, Consolas, monospace",
          fontSize: 13,
          lineHeight: 21,
          minimap: { enabled: true, scale: 0.75 },
          scrollBeyondLastLine: false,
          smoothScrolling: true,
          cursorBlinking: 'smooth',
          renderWhitespace: 'selection',
          bracketPairColorization: { enabled: true }
        });

        const diffContainer = document.getElementById('diff-editor-container');
        this.diffEditor = this.monaco.editor.createDiffEditor(diffContainer, {
          theme: 'vscode-dark-modern',
          automaticLayout: true,
          fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
          fontSize: 13,
          readOnly: true,
          renderSideBySide: true,
          smoothScrolling: true
        });

        // Ctrl+S / Cmd+S: Save file
        this.editor.addCommand(this.monaco.KeyMod.CtrlCmd | this.monaco.KeyCode.KeyS, () => {
          this.saveActiveFile();
        });

        // Ctrl+K / Cmd+K: Inline Code Edit
        this.editor.addCommand(this.monaco.KeyMod.CtrlCmd | this.monaco.KeyCode.KeyK, () => {
          this.showInlineEdit();
        });

        // Dirty status detection
        this.editor.onDidChangeModelContent(() => {
          if (this.activePath && this.openTabs.has(this.activePath)) {
            const tab = this.openTabs.get(this.activePath);
            const currentVal = this.editor.getValue();
            tab.isDirty = (currentVal !== tab.savedContent);
            this.updateTabUI(this.activePath);
          }
        });

        // ── Monaco Context Menu Quick Actions ─────────────────────────
        this.editor.addAction({
          id: "vallen-inline-edit",
          label: "⚡ VALLEN: Edit / Generate Inline (Ctrl+K)",
          keybindings: [this.monaco.KeyMod.CtrlCmd | this.monaco.KeyCode.KeyK],
          contextMenuGroupId: "1_modification",
          contextMenuOrder: 1.0,
          run: () => {
            this.showInlineEdit();
          }
        });

        this.editor.addAction({
          id: "vallen-ask",
          label: "🤖 Ask VALLEN About Selection",
          contextMenuGroupId: "1_modification",
          contextMenuOrder: 1.5,
          run: (ed) => {
            const selection = ed.getSelection();
            const selectedText = ed.getModel().getValueInRange(selection);
            if (window.copilot) {
              window.copilot.askWithContext("Bagaimana cara memperbaiki atau meningkatkan kode ini?", selectedText, false);
            }
          }
        });

        this.editor.addAction({
          id: "vallen-explain",
          label: "💡 VALLEN: Jelaskan Kode Ini (Explain)",
          contextMenuGroupId: "1_modification",
          contextMenuOrder: 1.6,
          run: (ed) => {
            const selection = ed.getSelection();
            const selectedText = ed.getModel().getValueInRange(selection);
            if (window.copilot) {
              window.copilot.askWithContext("Jelaskan cara kerja potongan kode berikut secara detail dan jelas:", selectedText, true);
            }
          }
        });

        this.editor.addAction({
          id: "vallen-refactor",
          label: "⚡ VALLEN: Refactor & Optimalkan",
          contextMenuGroupId: "1_modification",
          contextMenuOrder: 1.7,
          run: (ed) => {
            const selection = ed.getSelection();
            const selectedText = ed.getModel().getValueInRange(selection);
            if (window.copilot) {
              window.copilot.askWithContext("Tolong refactor dan optimalkan kode ini agar lebih efisien dan bersih:", selectedText, true);
            }
          }
        });

        this.editor.addAction({
          id: "vallen-test",
          label: "🧪 VALLEN: Buatkan Unit Test",
          contextMenuGroupId: "1_modification",
          contextMenuOrder: 1.8,
          run: (ed) => {
            const selection = ed.getSelection();
            const selectedText = ed.getModel().getValueInRange(selection);
            if (window.copilot) {
              window.copilot.askWithContext("Buatkan unit test komprehensif untuk kode berikut menggunakan test framework yang sesuai:", selectedText, true);
            }
          }
        });

        // Cursor position listener -> Status Bar Ln, Col
        this.editor.onDidChangeCursorPosition((e) => {
          this.updateCursorStatus(e.position.lineNumber, e.position.column);
        });

        this.setupInlineEdit();
        resolve();
      });
    });
  }

  layout() {
    if (this.editor) this.editor.layout();
    if (this.diffEditor) this.diffEditor.layout();
  }

  updateCursorStatus(line, col) {
    const el = document.getElementById('status-cursor');
    if (el) el.textContent = `Ln ${line}, Col ${col}`;
  }

  updateLanguageStatus(lang) {
    const el = document.getElementById('status-language');
    if (el) {
      const display = lang.charAt(0).toUpperCase() + lang.slice(1);
      el.textContent = display;
    }
  }

  updateBreadcrumbs(path) {
    const bc = document.getElementById('editor-breadcrumbs');
    if (!bc) return;
    bc.classList.remove('hidden');
    bc.innerHTML = "";

    const parts = path.split('/');
    const rootName = document.getElementById('sidebar-project-title')?.textContent.toLowerCase() || 'workspace';

    const rootEl = document.createElement('span');
    rootEl.className = 'bc-item bc-root';
    rootEl.textContent = rootName;
    bc.appendChild(rootEl);

    for (let i = 0; i < parts.length; i++) {
      const sep = document.createElement('span');
      sep.className = 'bc-sep';
      sep.textContent = '›';
      bc.appendChild(sep);

      const item = document.createElement('span');
      item.className = 'bc-item';
      item.textContent = parts[i];
      bc.appendChild(item);
    }
  }

  getLanguageForFile(path) {
    const ext = path.split('.').pop().toLowerCase();
    const map = {
      js: 'javascript', mjs: 'javascript', cjs: 'javascript',
      ts: 'typescript', py: 'python', html: 'html',
      css: 'css', scss: 'scss', json: 'json', md: 'markdown',
      sh: 'shell', bash: 'shell', yml: 'yaml', yaml: 'yaml',
      rs: 'rust', go: 'go', toml: 'ini', sql: 'sql',
      dockerfile: 'dockerfile'
    };
    return map[ext] || 'plaintext';
  }

  async openFile(rawPath) {
    const path = this.normalizePath(rawPath);
    if (!path) return;

    if (this.diffActive) {
      this.closeDiff();
    }

    document.getElementById('getting-started-view')?.classList.add('hidden');
    document.getElementById('center-shortcuts-view')?.classList.add('hidden');
    document.getElementById('monaco-viewport')?.classList.remove('hidden');

    if (this.openTabs.has(path)) {
      this.switchTab(path);
      return;
    }

    try {
      const res = await fetch(`/api/workspace/file?path=${encodeURIComponent(path)}`);
      const data = await res.json();
      if (data.is_binary) {
        alert("Binary file cannot be viewed in text editor.");
        return;
      }

      const lang = this.getLanguageForFile(path);
      const model = this.monaco.editor.createModel(data.content, lang);

      this.openTabs.set(path, {
        model,
        savedContent: data.content,
        isDirty: false
      });

      this.createTabUI(path);
      this.switchTab(path);
    } catch (e) {
      console.error("Failed to open file", e);
    }
  }

  async openFileAtLine(rawPath, lineNumber) {
    const path = this.normalizePath(rawPath);
    await this.openFile(path);
    if (this.editor && lineNumber) {
      setTimeout(() => {
        this.editor.setPosition({ lineNumber, column: 1 });
        this.editor.revealLineInCenter(lineNumber);
        this.editor.focus();
      }, 50);
    }
  }

  getSafeTabId(path) {
    return 'tab-' + encodeURIComponent(path).replace(/%/g, '_').replace(/\./g, '-').replace(/\//g, '-');
  }

  createTabUI(path) {
    const tabBar = document.getElementById('editor-tab-bar');
    const safeId = this.getSafeTabId(path);
    if (document.getElementById(safeId)) return;

    const tabEl = document.createElement('div');
    tabEl.className = 'vscode-tab';
    tabEl.id = safeId;

    const fileName = path.split('/').pop();
    const icon = window.explorer ? window.explorer.getFileIcon(fileName, false) : '📄';

    tabEl.innerHTML = `
      <span class="tab-icon">${icon}</span>
      <span class="tab-title" title="${path}">${fileName}</span>
      <span class="tab-dirty" style="display:none;">●</span>
      <span class="tab-close-icon" title="Close (Ctrl+W)">✕</span>
    `;

    tabEl.addEventListener('click', (e) => {
      if (e.target.classList.contains('tab-close-icon')) {
        e.stopPropagation();
        this.closeTab(path);
      } else {
        this.switchTab(path);
      }
    });

    tabBar.appendChild(tabEl);
  }

  updateTabUI(path) {
    const tabEl = document.getElementById(this.getSafeTabId(path));
    if (!tabEl) return;
    const tab = this.openTabs.get(path);
    const dot = tabEl.querySelector('.tab-dirty');
    const closeBtn = tabEl.querySelector('.tab-close-icon');
    if (tab && dot) {
      dot.style.display = tab.isDirty ? 'inline' : 'none';
      if (closeBtn) closeBtn.style.display = tab.isDirty ? 'none' : 'inline-flex';
    }
  }

  switchTab(rawPath, recordHistory = true) {
    const path = this.normalizePath(rawPath);
    if (!this.openTabs.has(path)) return;
    this.activePath = path;

    if (recordHistory) {
      if (this.historyList[this.historyList.length - 1] !== path) {
        this.historyList.push(path);
        if (this.historyList.length > 20) this.historyList.shift();
      }
      this.historyIndex = this.historyList.length - 1;
    }

    document.querySelectorAll('.vscode-tab').forEach(t => t.classList.remove('active'));
    const currentTab = document.getElementById(this.getSafeTabId(path));
    if (currentTab) currentTab.classList.add('active');

    const tab = this.openTabs.get(path);
    this.editor.setModel(tab.model);

    // Update top search title to: project › file — Ctrl+P to search
    const topTitle = document.getElementById('top-title-text');
    const projTitle = document.getElementById('sidebar-project-title')?.textContent.trim().toLowerCase() || 'workspace';
    if (topTitle) topTitle.textContent = `${projTitle} › ${path} — Ctrl+P to search`;
    this.updateBreadcrumbs(path);

    const lang = this.getLanguageForFile(path);
    this.updateLanguageStatus(lang);

    const pos = this.editor.getPosition();
    if (pos) this.updateCursorStatus(pos.lineNumber, pos.column);

    this.editor.focus();
  }

  closeTab(rawPath) {
    const path = this.normalizePath(rawPath);
    const tab = this.openTabs.get(path);
    if (!tab) return;
    tab.model.dispose();
    this.openTabs.delete(path);

    const tabEl = document.getElementById(this.getSafeTabId(path));
    if (tabEl) tabEl.remove();

    if (this.activePath === path) {
      const remaining = Array.from(this.openTabs.keys());
      if (remaining.length > 0) {
        this.switchTab(remaining[remaining.length - 1]);
      } else {
        this.activePath = null;
        this.editor.setModel(null);
        document.getElementById('editor-breadcrumbs')?.classList.add('hidden');
        const topTitle = document.getElementById('top-title-text');
        const projTitle = document.getElementById('sidebar-project-title')?.textContent.trim().toLowerCase() || 'workspace';
        if (topTitle) topTitle.textContent = `${projTitle} — Ctrl+P to search`;
        if (window.welcome) {
          window.welcome.showShortcutsView();
        }
      }
    }
  }

  insertAtCursor(textToInsert) {
    if (!this.editor) return;
    const selection = this.editor.getSelection();
    const op = { range: selection, text: textToInsert, forceMoveMarkers: true };
    this.editor.executeEdits("copilot-insert", [op]);
    this.editor.focus();
  }

  replaceActiveContent(newFullContent) {
    if (!this.editor) return;
    const model = this.editor.getModel();
    if (!model) return;
    const fullRange = model.getFullModelRange();
    this.editor.executeEdits("copilot-replace", [{ range: fullRange, text: newFullContent, forceMoveMarkers: true }]);
    this.editor.focus();
  }

  async saveActiveFile() {
    if (!this.activePath || !this.openTabs.has(this.activePath)) return;
    const tab = this.openTabs.get(this.activePath);
    const content = this.editor.getValue();

    try {
      const res = await fetch('/api/workspace/file', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: this.activePath, content })
      });
      if (res.ok) {
        tab.savedContent = content;
        tab.isDirty = false;
        this.updateTabUI(this.activePath);
        if (window.explorer) window.explorer.loadGitStatus();

        // Feedback in status bar
        const statusAgent = document.getElementById('status-agent');
        if (statusAgent) {
          const orig = statusAgent.innerHTML;
          statusAgent.innerHTML = `<span style="color: var(--accent-green); font-weight: 600;">✓ Saved ${this.activePath.split('/').pop()}</span>`;
          setTimeout(() => { statusAgent.innerHTML = orig; }, 2000);
        }
      }
    } catch (e) {
      console.error("Failed to save file", e);
    }
  }

  showDiff(diffData) {
    this.diffActive = true;
    this.activeDiffData = diffData;

    document.getElementById('getting-started-view')?.classList.add('hidden');
    document.getElementById('center-shortcuts-view')?.classList.add('hidden');
    document.getElementById('monaco-viewport')?.classList.remove('hidden');

    const banner = document.getElementById('diff-banner');
    banner.classList.add('visible');

    const cleanPath = this.normalizePath(diffData.path);
    document.getElementById('diff-file-name').textContent = cleanPath;
    document.getElementById('diff-additions').textContent = `+${diffData.additions}`;
    document.getElementById('diff-deletions').textContent = `-${diffData.deletions}`;

    const lang = this.getLanguageForFile(cleanPath);
    const origModel = this.monaco.editor.createModel(diffData.original, lang);
    const modModel = this.monaco.editor.createModel(diffData.modified, lang);

    this.diffEditor.setModel({ original: origModel, modified: modModel });

    document.getElementById('editor-container').classList.add('hidden');
    document.getElementById('diff-editor-container').classList.remove('hidden');
  }

  closeDiff() {
    this.diffActive = false;
    this.activeDiffData = null;
    document.getElementById('diff-banner').classList.remove('visible');
    document.getElementById('diff-editor-container').classList.add('hidden');
    document.getElementById('editor-container').classList.remove('hidden');
  }

  async acceptDiff(diffData = null) {
    const data = diffData || this.activeDiffData;
    if (!data) return;
    const path = this.normalizePath(data.path);
    const modifiedContent = data.modified;

    await fetch('/api/workspace/file', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path, content: modifiedContent })
    });

    this.closeDiff();
    await this.openFile(path);
    if (this.openTabs.has(path)) {
      this.openTabs.get(path).model.setValue(modifiedContent);
      this.openTabs.get(path).savedContent = modifiedContent;
      this.openTabs.get(path).isDirty = false;
      this.updateTabUI(path);
    }
    if (window.explorer) window.explorer.loadGitStatus();
  }

  async rejectDiff(diffData = null) {
    const data = diffData || this.activeDiffData;
    if (!data) return;
    const path = this.normalizePath(data.path);

    await fetch('/api/agent/diff/revert', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path })
    });

    this.closeDiff();
    if (this.openTabs.has(path)) {
      this.openFile(path);
    }
    if (window.explorer) window.explorer.loadGitStatus();
  }

  async syncOpenFile(filePath) {
    const cleanPath = this.normalizePath(filePath);
    if (!this.openTabs.has(cleanPath)) return;
    const tab = this.openTabs.get(cleanPath);
    if (tab.isDirty) return;

    try {
      const res = await fetch(`/api/workspace/file?path=${encodeURIComponent(cleanPath)}`);
      if (res.ok) {
        const data = await res.json();
        if (data && typeof data.content === 'string') {
          if (tab.model.getValue() !== data.content) {
            tab.model.setValue(data.content);
            tab.savedContent = data.content;
            tab.isDirty = false;
            this.updateTabUI(cleanPath);
          }
        }
      }
    } catch (e) {
      console.warn('Failed to sync open file:', cleanPath, e);
    }
  }

  navigateHistory(direction) {
    if (!this.historyList || this.historyList.length <= 1) return;
    this.historyIndex = Math.max(0, Math.min(this.historyList.length - 1, this.historyIndex + direction));
    const target = this.historyList[this.historyIndex];
    if (target && this.openTabs.has(target)) {
      this.switchTab(target, false);
    }
  }

  setupInlineEdit() {
    let widget = document.getElementById("monaco-inline-edit-widget");
    if (!widget) {
      widget = document.createElement("div");
      widget.id = "monaco-inline-edit-widget";
      widget.className = "inline-edit-widget hidden";
      widget.innerHTML = `
        <div class="inline-edit-header">
          <span>⚡ VALLEN Inline Code Edit</span>
          <span class="badge">Ctrl+K</span>
        </div>
        <div class="inline-edit-input-row">
          <input type="text" id="inline-edit-prompt" class="inline-edit-input" placeholder="Tanya / instruksikan perubahan kode (Enter untuk kirim)..." />
          <button id="inline-edit-submit" class="inline-edit-btn-submit">Generate ⚡</button>
        </div>
        <div class="inline-edit-footer">
          <span id="inline-edit-status" class="inline-edit-status">Tekan Enter untuk generate</span>
          <div id="inline-edit-review-actions" class="inline-edit-actions-group" style="display: none;">
            <button id="inline-edit-accept" class="inline-btn-accept">✓ Accept (Enter)</button>
            <button id="inline-edit-reject" class="inline-btn-reject">✕ Reject (Esc)</button>
          </div>
        </div>
      `;
      const container = document.getElementById("editor-container") || document.body;
      container.appendChild(widget);

      const input = widget.querySelector("#inline-edit-prompt");
      const submitBtn = widget.querySelector("#inline-edit-submit");
      const acceptBtn = widget.querySelector("#inline-edit-accept");
      const rejectBtn = widget.querySelector("#inline-edit-reject");

      submitBtn.addEventListener("click", () => this.submitInlineEdit());
      acceptBtn.addEventListener("click", () => this.acceptInlineEdit());
      rejectBtn.addEventListener("click", () => this.rejectInlineEdit());

      input.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          if (this.inlineEditState === "review") {
            this.acceptInlineEdit();
          } else {
            this.submitInlineEdit();
          }
        } else if (e.key === "Escape") {
          e.preventDefault();
          this.rejectInlineEdit();
        }
      });
    }
  }

  showInlineEdit() {
    if (!this.editor) return;
    this.setupInlineEdit();
    const widget = document.getElementById("monaco-inline-edit-widget");
    if (!widget) return;

    const selection = this.editor.getSelection();
    let targetRange = selection;
    if (!selection || selection.isEmpty()) {
      const pos = this.editor.getPosition() || { lineNumber: 1, column: 1 };
      const maxCol = this.editor.getModel().getLineMaxColumn(pos.lineNumber);
      targetRange = new this.monaco.Range(pos.lineNumber, 1, pos.lineNumber, maxCol);
    }

    this.activeInlineRange = targetRange;
    this.originalInlineText = this.editor.getModel().getValueInRange(targetRange);
    this.inlineEditDecorations = [];
    this.inlineEditState = "ready";

    const input = document.getElementById("inline-edit-prompt");
    const status = document.getElementById("inline-edit-status");
    const review = document.getElementById("inline-edit-review-actions");
    const submitBtn = document.getElementById("inline-edit-submit");

    if (input) {
      input.value = "";
      setTimeout(() => input.focus(), 50);
    }
    if (status) status.textContent = "Ketik instruksi, lalu tekan Enter";
    if (review) review.style.display = "none";
    if (submitBtn) submitBtn.style.display = "block";

    widget.classList.remove("hidden");
  }

  async submitInlineEdit() {
    const input = document.getElementById("inline-edit-prompt");
    const status = document.getElementById("inline-edit-status");
    const review = document.getElementById("inline-edit-review-actions");
    const submitBtn = document.getElementById("inline-edit-submit");
    const prompt = input ? input.value.trim() : "";

    if (!prompt) return;

    if (status) status.textContent = "⏳ Menghasilkan kode...";
    if (submitBtn) submitBtn.disabled = true;

    try {
      const model = this.editor.getModel();
      const pos = this.editor.getPosition();
      const totalLines = model.getLineCount();
      const startContext = Math.max(1, (this.activeInlineRange?.startLineNumber || pos.lineNumber) - 15);
      const endContext = Math.min(totalLines, (this.activeInlineRange?.endLineNumber || pos.lineNumber) + 15);
      const surrounding = model.getValueInRange(new this.monaco.Range(startContext, 1, endContext, model.getLineMaxColumn(endContext)));

      const activeModelSelect = document.getElementById("model-select");
      const chosenModel = (activeModelSelect && activeModelSelect.value !== "default") ? activeModelSelect.value : null;

      const res = await fetch("/api/agent/inline-edit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          prompt,
          selection: this.originalInlineText,
          surrounding,
          language: model.getLanguageId(),
          path: this.activePath || "",
          model: chosenModel,
        }),
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Gagal generate inline code");
      }

      const data = await res.json();
      const replacement = data.replacement;

      this.editor.executeEdits("vallen-inline", [{
        range: this.activeInlineRange,
        text: replacement,
        forceMoveMarkers: true,
      }]);

      const linesAdded = replacement.split("\n").length;
      const endLine = this.activeInlineRange.startLineNumber + linesAdded - 1;
      const highlightRange = new this.monaco.Range(
        this.activeInlineRange.startLineNumber,
        1,
        endLine,
        model.getLineMaxColumn(endLine)
      );

      this.inlineEditDecorations = this.editor.deltaDecorations([], [{
        range: highlightRange,
        options: {
          isWholeLine: true,
          className: "inline-edit-highlight-line"
        }
      }]);

      this.inlineEditState = "review";
      if (status) status.textContent = "✓ Preview aktif! Enter untuk Accept, Esc untuk Reject";
      if (review) review.style.display = "flex";
      if (submitBtn) submitBtn.style.display = "none";

      if (input) input.focus();
    } catch (err) {
      if (status) status.textContent = `✗ Error: ${err.message}`;
    } finally {
      if (submitBtn) submitBtn.disabled = false;
    }
  }

  acceptInlineEdit() {
    if (this.inlineEditDecorations && this.inlineEditDecorations.length) {
      this.editor.deltaDecorations(this.inlineEditDecorations, []);
      this.inlineEditDecorations = [];
    }
    const widget = document.getElementById("monaco-inline-edit-widget");
    if (widget) widget.classList.add("hidden");
    this.inlineEditState = "idle";

    if (this.activePath && this.openTabs.has(this.activePath)) {
      const tab = this.openTabs.get(this.activePath);
      tab.isDirty = true;
      this.updateTabUI(this.activePath);
    }
    this.editor.focus();
  }

  rejectInlineEdit() {
    if (this.inlineEditState === "review" && this.originalInlineText !== null) {
      this.editor.trigger("vallen-inline", "undo", null);
    }
    if (this.inlineEditDecorations && this.inlineEditDecorations.length) {
      this.editor.deltaDecorations(this.inlineEditDecorations, []);
      this.inlineEditDecorations = [];
    }
    const widget = document.getElementById("monaco-inline-edit-widget");
    if (widget) widget.classList.add("hidden");
    this.inlineEditState = "idle";
    this.editor.focus();
  }

}

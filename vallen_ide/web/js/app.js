document.addEventListener('DOMContentLoaded', async () => {
  // 1. Initialize Core Managers
  window.editor = new EditorManager();
  await window.editor.init();

  window.explorer = new ExplorerManager(window.editor);
  await window.explorer.init();

  window.terminal = new TerminalManager();
  window.terminal.init();

  window.copilot = new CopilotManager(window.editor);
  window.copilot.init();

  window.welcome = new WelcomeManager(window.editor);
  window.welcome.init();

  window.palette = new PaletteManager(window.editor);
  window.palette.init();

  window.contextMenu = new ContextMenuManager(window.explorer, window.editor);
  window.contextMenu.init();

  // 2. Load Agent Info, Models & Git
  loadAgentInfo();
  loadGitStatus();

  // Fetch and apply current workspace info
  fetch('/api/workspace/current').then(r => r.json()).then(data => {
    if (data && data.name) {
      const el = document.getElementById('sidebar-project-title');
      if (el) el.textContent = data.name.toUpperCase();
      const topTitle = document.getElementById('top-title-text');
      if (topTitle) topTitle.textContent = `${data.name} — Ctrl+P to search`;
      const bcRoot = document.getElementById('bc-root');
      if (bcRoot) bcRoot.textContent = data.name.toLowerCase();
      if (window.copilot) window.copilot.loadHistory();
      if (window.explorer) window.explorer.refreshTree();
    }
  }).catch(() => {});

  // 3. Bind Top Bar & Layout Action Buttons
  setupLayoutButtons();

  // 4. Bind Activity Bar Tabs
  setupActivityBar();

  // 5. Setup Top Dropdown Menus
  setupMenuDropdowns();

  // 6. Setup Drag Resizers
  setupDragResizers();

  // 7. Diff Banner Buttons
  document.getElementById('btn-diff-accept')?.addEventListener('click', () => {
    window.editor.acceptDiff();
  });
  document.getElementById('btn-diff-reject')?.addEventListener('click', () => {
    window.editor.rejectDiff();
  });

  // 8. Global Hotkeys
  setupGlobalHotkeys();

  // 9. Initial View: Show Welcome & Folder Selection
  window.welcome.showGettingStarted();
});

function getShortModelName(rawId) {
  if (!rawId || rawId === "default") return "Default";
  const id = rawId.toLowerCase();

  if (id.includes("claude-opus") || id.includes("opus")) return "Opus 4.6";
  if (id.includes("claude-sonnet") || id.includes("sonnet")) return "Sonnet 4.6";
  if (id.includes("claude-3-7") || id.includes("claude-3.7")) return "Claude 3.7";
  if (id.includes("claude-3-5") || id.includes("claude-3.5")) return "Claude 3.5";
  if (id.includes("claude")) return "Claude";

  if (id.includes("gemini") && id.includes("flash")) return "Gemini Flash";
  if (id.includes("gemini") && id.includes("pro")) return "Gemini Pro";
  if (id.includes("gemini")) return "Gemini";

  if (id.includes("gpt-4o")) return "GPT-4o";
  if (id.includes("gpt-4")) return "GPT-4";
  if (id.includes("o1-mini")) return "o1-mini";
  if (id.includes("o1")) return "o1";
  if (id.includes("o3-mini")) return "o3-mini";
  if (id.includes("o3")) return "o3";
  if (id.includes("gpt-oss")) return "GPT-OSS";

  if (id.includes("llama-4")) return "Llama 4";
  if (id.includes("llama-3.3")) return "Llama 3.3";
  if (id.includes("llama-3")) return "Llama 3";
  if (id.includes("llama")) return "Llama";

  if (id.includes("qwen3")) return "Qwen 3";
  if (id.includes("qwen")) return "Qwen";

  if (id.includes("deepseek")) return (id.includes("r1") || id.includes("reasoner")) ? "DeepSeek R1" : "DeepSeek";

  const segs = rawId.split("/");
  const last = segs[segs.length - 1].replace(/-instruct|-chat|-versatile|-preview/gi, "");
  return last.length > 13 ? last.slice(0, 11) + "…" : last;
}

let registeredModels = [];

function refreshModelSelectOptions(expandAll = false) {
  const modelSelect = document.getElementById('model-select');
  if (!modelSelect || !registeredModels.length) return;
  const currentVal = modelSelect.value;
  modelSelect.innerHTML = "";
  for (const m of registeredModels) {
    const opt = document.createElement('option');
    opt.value = m.id;
    if (expandAll) {
      opt.textContent = `${m.provider ? '[' + m.provider + '] ' : ''}${m.display_name || m.id}`;
    } else {
      opt.textContent = (m.id === currentVal) ? getShortModelName(m.id) : `${m.provider ? '[' + m.provider + '] ' : ''}${m.display_name || m.id}`;
    }
    if (m.id === currentVal) opt.selected = true;
    modelSelect.appendChild(opt);
  }
}

async function loadAgentInfo() {
  try {
    const res = await fetch('/api/agent/info');
    const data = await res.json();

    const modelSelect = document.getElementById('model-select');
    if (modelSelect && data.models) {
      registeredModels = data.models;
      // Pre-set active model
      modelSelect.value = data.active_model || (data.models[0] ? data.models[0].id : "");
      refreshModelSelectOptions(false);

      modelSelect.addEventListener('mousedown', () => refreshModelSelectOptions(true));
      modelSelect.addEventListener('focus', () => refreshModelSelectOptions(true));
      modelSelect.addEventListener('change', async () => {
        refreshModelSelectOptions(false);
        await fetch('/api/agent/set-model', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ model: modelSelect.value })
        });
      });
      modelSelect.addEventListener('blur', () => refreshModelSelectOptions(false));
    }

    // Render Skills in Activity View
    const skillsContainer = document.getElementById('skills-list-container');
    if (skillsContainer && data.skills) {
      skillsContainer.innerHTML = "";
      for (const s of data.skills) {
        const card = document.createElement('div');
        card.style.cssText = 'background: var(--bg-card); border: 1px solid var(--border-subtle); border-radius: 4px; padding: 10px; margin-bottom: 8px;';
        card.innerHTML = `
          <div style="font-weight: 700; color: var(--accent-purple-light); font-size: 12px; margin-bottom: 4px;">⚡ ${s.name}</div>
          <div style="font-size: 11px; color: var(--text-muted); line-height: 1.4;">${s.description || 'Custom Agent Skill'}</div>
        `;
        skillsContainer.appendChild(card);
      }
    }
  } catch (e) {
    console.error("Agent info error", e);
  }
}

async function loadGitStatus() {
  try {
    const res = await fetch('/api/workspace/git-status');
    const data = await res.json();
    const branchEl = document.getElementById('status-branch-name');
    if (branchEl) branchEl.textContent = `${data.branch || 'main'}*`;
  } catch (e) {
    console.error("Git status error", e);
  }
}

function setupLayoutButtons() {
  // Panel Tabs Switching (Terminal / Output / Problems)
  const tabTerm = document.getElementById('term-tab-terminal');
  const tabOut = document.getElementById('term-tab-output');
  const tabProb = document.getElementById('term-tab-problems');
  const termMount = document.getElementById('terminal-container');
  const outMount = document.getElementById('panel-output-container');
  const probMount = document.getElementById('panel-problems-container');

  function selectPanelTab(activeTab, showMount) {
    [tabTerm, tabOut, tabProb].forEach(t => t?.classList.remove('active'));
    [termMount, outMount, probMount].forEach(m => m?.classList.add('hidden'));
    activeTab?.classList.add('active');
    showMount?.classList.remove('hidden');
    if (activeTab === tabTerm && window.terminal?.fitAddon) {
      setTimeout(() => window.terminal.fitAddon.fit(), 50);
    }
  }

  tabTerm?.addEventListener('click', () => selectPanelTab(tabTerm, termMount));
  tabOut?.addEventListener('click', () => selectPanelTab(tabOut, outMount));
  tabProb?.addEventListener('click', () => selectPanelTab(tabProb, probMount));

  document.getElementById('status-problems')?.addEventListener('click', () => {
    const bp = document.getElementById('bottom-terminal-panel');
    bp?.classList.remove('collapsed');
    selectPanelTab(tabProb, probMount);
    if (window.editor) window.editor.layout();
  });
  // Navigation arrows
  document.getElementById('btn-nav-back')?.addEventListener('click', () => {
    window.editor?.navigateHistory(-1);
  });
  document.getElementById('btn-nav-forward')?.addEventListener('click', () => {
    window.editor?.navigateHistory(1);
  });

  // Toggle Sidebar
  document.getElementById('btn-toggle-sidebar')?.addEventListener('click', () => {
    const sb = document.getElementById('primary-sidebar');
    sb.classList.toggle('collapsed');
    setTimeout(() => { if (window.editor) window.editor.layout(); }, 150);
  });

  // Toggle Terminal
  document.getElementById('btn-toggle-terminal-top')?.addEventListener('click', () => {
    const bp = document.getElementById('bottom-terminal-panel');
    bp.classList.toggle('collapsed');
    if (!bp.classList.contains('collapsed') && window.terminal && window.terminal.fitAddon) {
      setTimeout(() => window.terminal.fitAddon.fit(), 100);
    }
    setTimeout(() => { if (window.editor) window.editor.layout(); }, 150);
  });

  // Toggle Copilot
  document.getElementById('btn-toggle-copilot-top')?.addEventListener('click', () => {
    const cp = document.getElementById('copilot-panel');
    cp.classList.toggle('collapsed');
    setTimeout(() => { if (window.editor) window.editor.layout(); }, 150);
  });

  // Agent Focus
  document.getElementById('btn-agent-focus')?.addEventListener('click', () => {
    const cp = document.getElementById('copilot-panel');
    cp.classList.remove('collapsed');
    document.getElementById('chat-prompt-textarea')?.focus();
    setTimeout(() => { if (window.editor) window.editor.layout(); }, 150);
  });

  // Global search pill in top center
  document.getElementById('global-search-pill')?.addEventListener('click', () => {
    if (window.palette) window.palette.open();
  });

  // Terminal Controls
  document.getElementById('btn-clear-terminal')?.addEventListener('click', () => {
    if (window.terminal && window.terminal.term) window.terminal.term.clear();
  });
  document.getElementById('btn-close-terminal')?.addEventListener('click', () => {
    document.getElementById('bottom-terminal-panel')?.classList.add('collapsed');
    if (window.editor) window.editor.layout();
  });
  document.getElementById('btn-maximize-terminal')?.addEventListener('click', () => {
    const panel = document.getElementById('bottom-terminal-panel');
    if (panel) {
      if (panel.style.height === '80vh') {
        panel.style.height = '220px';
      } else {
        panel.style.height = '80vh';
      }
      if (window.terminal && window.terminal.fitAddon) {
        setTimeout(() => window.terminal.fitAddon.fit(), 100);
      }
      if (window.editor) window.editor.layout();
    }
  });

  // Window Controls
  document.getElementById('btn-win-min')?.addEventListener('click', () => {
    const statusAgent = document.getElementById('status-agent');
    if (statusAgent) {
      statusAgent.innerHTML = `<span style="color: var(--accent-purple-light);">VALLEN IDE is running</span>`;
      setTimeout(() => { statusAgent.innerHTML = `<span style="color: var(--accent-purple); font-weight: 700;">⚡ VALLEN PRO</span>`; }, 2500);
    }
  });
  document.getElementById('btn-win-max')?.addEventListener('click', () => {
    if (!document.fullscreenElement) {
      document.documentElement.requestFullscreen().catch(() => {});
    } else {
      document.exitFullscreen().catch(() => {});
    }
  });
  document.getElementById('btn-win-close')?.addEventListener('click', () => {
    if (confirm("Close VALLEN IDE session?")) {
      window.close();
    }
  });
}

function setupDragResizers() {
  // 1. Sidebar Resizer
  const sidebarResizer = document.getElementById('resizer-sidebar');
  const sidebar = document.getElementById('primary-sidebar');
  if (sidebarResizer && sidebar) {
    let isDragging = false;

    sidebarResizer.addEventListener('mousedown', (e) => {
      isDragging = true;
      sidebarResizer.classList.add('resizing');
      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';
    });

    window.addEventListener('mousemove', (e) => {
      if (!isDragging) return;
      const activityWidth = 48;
      const newWidth = Math.max(160, Math.min(600, e.clientX - activityWidth));
      sidebar.style.width = `${newWidth}px`;
      if (window.editor) window.editor.layout();
    });

    window.addEventListener('mouseup', () => {
      if (isDragging) {
        isDragging = false;
        sidebarResizer.classList.remove('resizing');
        document.body.style.cursor = 'default';
        document.body.style.userSelect = 'auto';
        if (window.editor) window.editor.layout();
      }
    });
  }

  // 2. Copilot Resizer
  const copilotResizer = document.getElementById('resizer-copilot');
  const copilot = document.getElementById('copilot-panel');
  if (copilotResizer && copilot) {
    let isDragging = false;

    copilotResizer.addEventListener('mousedown', (e) => {
      isDragging = true;
      copilotResizer.classList.add('resizing');
      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';
    });

    window.addEventListener('mousemove', (e) => {
      if (!isDragging) return;
      const newWidth = Math.max(260, Math.min(800, window.innerWidth - e.clientX));
      copilot.style.width = `${newWidth}px`;
      if (window.editor) window.editor.layout();
    });

    window.addEventListener('mouseup', () => {
      if (isDragging) {
        isDragging = false;
        copilotResizer.classList.remove('resizing');
        document.body.style.cursor = 'default';
        document.body.style.userSelect = 'auto';
        if (window.editor) window.editor.layout();
      }
    });
  }

  // 3. Terminal Height Resizer
  const termDragBar = document.getElementById('terminal-drag-bar');
  const termPanel = document.getElementById('bottom-terminal-panel');
  if (termDragBar && termPanel) {
    let isDragging = false;
    let startY = 0;
    let startHeight = 0;

    termDragBar.addEventListener('mousedown', (e) => {
      isDragging = true;
      startY = e.clientY;
      startHeight = termPanel.offsetHeight;
      document.body.style.cursor = 'row-resize';
      document.body.style.userSelect = 'none';
    });

    window.addEventListener('mousemove', (e) => {
      if (!isDragging) return;
      const delta = startY - e.clientY;
      const newHeight = Math.max(80, Math.min(window.innerHeight - 100, startHeight + delta));
      termPanel.style.height = `${newHeight}px`;
      if (window.terminal && window.terminal.fitAddon) {
        window.terminal.fitAddon.fit();
      }
      if (window.editor) window.editor.layout();
    });

    window.addEventListener('mouseup', () => {
      if (isDragging) {
        isDragging = false;
        document.body.style.cursor = 'default';
        document.body.style.userSelect = 'auto';
        if (window.editor) window.editor.layout();
      }
    });
  }
}

function setupMenuDropdowns() {
  const menuItems = document.querySelectorAll('.window-menu-bar .menu-item');
  const dropdowns = document.querySelectorAll('.menu-dropdown');

  function closeAllDropdowns() {
    menuItems.forEach(i => i.classList.remove('active'));
    dropdowns.forEach(d => d.classList.add('hidden'));
  }

  menuItems.forEach(item => {
    item.addEventListener('click', (e) => {
      e.stopPropagation();
      const menuType = item.getAttribute('data-menu');
      const targetDropdown = document.getElementById(`menu-dropdown-${menuType}`);
      const isOpen = targetDropdown && !targetDropdown.classList.contains('hidden');

      closeAllDropdowns();

      if (!isOpen && targetDropdown) {
        item.classList.add('active');
        const rect = item.getBoundingClientRect();
        targetDropdown.style.left = `${rect.left}px`;
        targetDropdown.style.top = `${rect.bottom + 2}px`;
        targetDropdown.classList.remove('hidden');
      }
    });
  });

  document.addEventListener('click', (e) => {
    if (!e.target.closest('#menu-dropdown-container') && !e.target.closest('.window-menu-bar')) {
      closeAllDropdowns();
    }
  });

  // Bind Menu Actions
  document.getElementById('m-file-new')?.addEventListener('click', () => {
    closeAllDropdowns();
    window.explorer?.promptCreate('file');
  });
  document.getElementById('m-file-open-folder')?.addEventListener('click', () => {
    closeAllDropdowns();
    window.welcome?.openFolderPicker();
  });
  document.getElementById('m-file-save')?.addEventListener('click', () => {
    closeAllDropdowns();
    window.editor?.saveActiveFile();
  });
  document.getElementById('m-file-close')?.addEventListener('click', () => {
    closeAllDropdowns();
    if (window.editor?.activePath) window.editor.closeTab(window.editor.activePath);
  });

  // Edit Menu Dropdown Items
  document.getElementById('m-edit-undo')?.addEventListener('click', () => {
    closeAllDropdowns();
    window.editor?.editor?.trigger('menu', 'undo');
  });
  document.getElementById('m-edit-redo')?.addEventListener('click', () => {
    closeAllDropdowns();
    window.editor?.editor?.trigger('menu', 'redo');
  });
  document.getElementById('m-edit-cut')?.addEventListener('click', () => {
    closeAllDropdowns();
    window.editor?.editor?.focus();
    document.execCommand('cut');
  });
  document.getElementById('m-edit-copy')?.addEventListener('click', () => {
    closeAllDropdowns();
    window.editor?.editor?.focus();
    document.execCommand('copy');
  });
  document.getElementById('m-edit-paste')?.addEventListener('click', async () => {
    closeAllDropdowns();
    try {
      const text = await navigator.clipboard.readText();
      if (text && window.editor?.insertAtCursor) {
        window.editor.insertAtCursor(text);
      }
    } catch {
      window.editor?.editor?.focus();
      document.execCommand('paste');
    }
  });
  document.getElementById('m-sel-all')?.addEventListener('click', () => {
    closeAllDropdowns();
    window.editor?.editor?.trigger('menu', 'editor.action.selectAll');
  });

  document.getElementById('m-view-explorer')?.addEventListener('click', () => {
    closeAllDropdowns();
    document.getElementById('act-explorer')?.click();
  });
  document.getElementById('m-view-search')?.addEventListener('click', () => {
    closeAllDropdowns();
    document.getElementById('act-search')?.click();
  });
  document.getElementById('m-view-git')?.addEventListener('click', () => {
    closeAllDropdowns();
    document.getElementById('act-git')?.click();
  });
  document.getElementById('m-view-terminal')?.addEventListener('click', () => {
    closeAllDropdowns();
    document.getElementById('btn-toggle-terminal-top')?.click();
  });
  document.getElementById('m-view-copilot')?.addEventListener('click', () => {
    closeAllDropdowns();
    document.getElementById('btn-toggle-copilot-top')?.click();
  });

  document.getElementById('m-go-file')?.addEventListener('click', () => {
    closeAllDropdowns();
    window.palette?.open();
  });

  document.getElementById('m-term-toggle')?.addEventListener('click', () => {
    closeAllDropdowns();
    document.getElementById('btn-toggle-terminal-top')?.click();
  });
  document.getElementById('m-term-clear')?.addEventListener('click', () => {
    closeAllDropdowns();
    window.terminal?.term?.clear();
  });

  document.getElementById('m-help-welcome')?.addEventListener('click', () => {
    closeAllDropdowns();
    window.welcome?.showGettingStarted();
  });
  document.getElementById('m-help-shortcuts')?.addEventListener('click', () => {
    closeAllDropdowns();
    window.welcome?.showShortcutsView();
  });
  document.getElementById('m-help-about')?.addEventListener('click', () => {
    closeAllDropdowns();
    alert("VALLEN IDE v1.0.0\nAutonomous AI Software Engineering Studio\nPowered by VALLEN Core & Textual Agent");
  });
}

function setupActivityBar() {
  const map = {
    'act-explorer': 'view-files',
    'act-search': 'view-search',
    'act-git': 'view-git',
    'act-skills': 'view-skills'
  };

  for (const [btnId, viewId] of Object.entries(map)) {
    document.getElementById(btnId)?.addEventListener('click', () => {
      const sidebar = document.getElementById('primary-sidebar');
      const isAlreadyActive = document.getElementById(btnId).classList.contains('active');

      if (isAlreadyActive && !sidebar.classList.contains('collapsed')) {
        sidebar.classList.add('collapsed');
        document.querySelectorAll('.act-btn').forEach(b => b.classList.remove('active'));
        setTimeout(() => { if (window.editor) window.editor.layout(); }, 150);
        return;
      }

      sidebar.classList.remove('collapsed');
      document.querySelectorAll('.act-btn').forEach(b => b.classList.remove('active'));
      document.getElementById(btnId).classList.add('active');

      document.querySelectorAll('.sidebar-content-view').forEach(v => v.classList.add('hidden'));
      document.getElementById(viewId)?.classList.remove('hidden');

      if (viewId === 'view-git') {
        window.explorer.loadGitStatus();
      }

      setTimeout(() => { if (window.editor) window.editor.layout(); }, 150);
    });
  }

  // Act Agent
  document.getElementById('act-agent')?.addEventListener('click', () => {
    const cp = document.getElementById('copilot-panel');
    cp.classList.remove('collapsed');
    document.getElementById('chat-prompt-textarea')?.focus();
    setTimeout(() => { if (window.editor) window.editor.layout(); }, 150);
  });

  // Run & Debug (Ctrl+Shift+D)
  document.getElementById('act-debug')?.addEventListener('click', () => {
    const bp = document.getElementById('bottom-terminal-panel');
    bp?.classList.remove('collapsed');
    const activeFile = window.editor?.activePath;
    if (activeFile && activeFile.endsWith('.py')) {
      window.terminal?.runCommand(`python3 ${activeFile}`);
    } else if (activeFile && activeFile.endsWith('.sh')) {
      window.terminal?.runCommand(`bash ${activeFile}`);
    } else if (activeFile && (activeFile.endsWith('.js') || activeFile.endsWith('.mjs'))) {
      window.terminal?.runCommand(`node ${activeFile}`);
    } else if (activeFile) {
      window.terminal?.runCommand(`./${activeFile}`);
    }
    setTimeout(() => { if (window.editor) window.editor.layout(); }, 150);
  });

  // Settings Modal Handlers
  const settingsBackdrop = document.getElementById('settings-modal-backdrop');
  function openSettings() {
    if (!settingsBackdrop) return;
    const modelSelect = document.getElementById('setting-model-select');
    if (modelSelect && registeredModels.length) {
      modelSelect.innerHTML = '';
      registeredModels.forEach(m => {
        const opt = document.createElement('option');
        opt.value = m.id;
        opt.textContent = `${m.provider ? '[' + m.provider + '] ' : ''}${m.display_name || m.id}`;
        if (m.id === document.getElementById('model-select')?.value) opt.selected = true;
        modelSelect.appendChild(opt);
      });
    }
    const savedFontSize = localStorage.getItem('vallen_editor_font_size') || '13';
    const savedFontFam = localStorage.getItem('vallen_editor_font_family') || "'JetBrains Mono', 'Fira Code', monospace";
    const fontIn = document.getElementById('setting-font-size');
    const famIn = document.getElementById('setting-font-family');
    if (fontIn) fontIn.value = savedFontSize;
    if (famIn) famIn.value = savedFontFam;
    settingsBackdrop.classList.remove('hidden');
  }

  function closeSettings() {
    settingsBackdrop?.classList.add('hidden');
  }

  document.getElementById('act-settings')?.addEventListener('click', openSettings);
  document.getElementById('btn-close-settings-modal')?.addEventListener('click', closeSettings);
  document.getElementById('btn-cancel-settings')?.addEventListener('click', closeSettings);
  settingsBackdrop?.addEventListener('click', (e) => {
    if (e.target === settingsBackdrop) closeSettings();
  });

  document.getElementById('btn-save-settings')?.addEventListener('click', async () => {
    const fontSize = parseInt(document.getElementById('setting-font-size')?.value || '13', 10);
    const fontFamily = document.getElementById('setting-font-family')?.value || "'JetBrains Mono', monospace";
    const selectedModel = document.getElementById('setting-model-select')?.value;
    const autoPilot = document.getElementById('setting-default-autopilot')?.value === 'true';
    const autoAccept = document.getElementById('setting-default-autoaccept')?.value === 'true';

    localStorage.setItem('vallen_editor_font_size', fontSize);
    localStorage.setItem('vallen_editor_font_family', fontFamily);

    if (window.editor?.editor) {
      window.editor.editor.updateOptions({ fontSize, fontFamily });
    }

    if (selectedModel) {
      const topModelSelect = document.getElementById('model-select');
      if (topModelSelect) topModelSelect.value = selectedModel;
      await fetch('/api/agent/set-model', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model: selectedModel })
      });
    }

    if (window.copilot) {
      window.copilot.autopilotActive = autoPilot;
      window.copilot.alwaysAccept = autoAccept;
    }
    closeSettings();
  });
}

function setupGlobalHotkeys() {
  window.addEventListener('keydown', (e) => {
    // Ctrl + P: Quick Open Palette
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'p' && !e.shiftKey) {
      e.preventDefault();
      if (window.palette) window.palette.toggle();
    }

    // Ctrl + Shift + P: Quick Open Palette (Commands)
    if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === 'p') {
      e.preventDefault();
      if (window.palette) window.palette.open(true);
    }

    // Shift + Alt + F: Format Document
    if (e.shiftKey && e.altKey && e.key.toLowerCase() === 'f') {
      e.preventDefault();
      window.editor?.editor?.getAction('editor.action.formatDocument')?.run();
    }

    // Ctrl + B: Toggle primary sidebar
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'b') {
      e.preventDefault();
      document.getElementById('btn-toggle-sidebar')?.click();
    }

    // Ctrl + `: Toggle Terminal
    if ((e.ctrlKey || e.metaKey) && e.key === '`') {
      e.preventDefault();
      document.getElementById('btn-toggle-terminal-top')?.click();
    }

    // Ctrl + Shift + L: Focus Copilot Chat
    if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === 'l') {
      e.preventDefault();
      document.getElementById('btn-agent-focus')?.click();
    }

    // Ctrl + Shift + E: Explorer
    if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === 'e') {
      e.preventDefault();
      document.getElementById('act-explorer')?.click();
    }

    // Ctrl + Shift + F: Search
    if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === 'f') {
      e.preventDefault();
      document.getElementById('act-search')?.click();
    }

    // Ctrl + Shift + G: Git
    if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === 'g') {
      e.preventDefault();
      document.getElementById('act-git')?.click();
    }
  });
}


// ── VALLEN CIHUY Auto-Execution Bridge ──────────────────────────────
window.addEventListener("DOMContentLoaded", () => {
  const urlParams = new URLSearchParams(window.location.search);
  if (urlParams.get("autostart") === "cihuy") {
    const pendingPrompt = localStorage.getItem("vallen_cihuy_pending_prompt");
    if (pendingPrompt) {
      localStorage.removeItem("vallen_cihuy_pending_prompt");
      setTimeout(() => {
        if (window.copilot) {
          const textarea = document.getElementById("chat-prompt-textarea");
          if (textarea) {
            textarea.value = pendingPrompt;
            window.copilot.sendMessage();
          }
        }
      }, 1200);
    }
  }
});

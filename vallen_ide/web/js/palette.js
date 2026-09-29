class PaletteManager {
  constructor(editorManager) {
    this.editorManager = editorManager;
    this.files = [];
    this.selectedIndex = 0;
    this.isOpen = false;
    this.commands = [
      {
        id: 'settings',
        label: 'Preferences: Open Settings',
        icon: '⚙️',
        category: 'Preferences',
        action: () => document.getElementById('act-settings')?.click()
      },
      {
        id: 'new-file',
        label: 'File: New File',
        icon: '📄',
        category: 'File',
        action: () => window.explorer?.promptCreate('file')
      },
      {
        id: 'open-folder',
        label: 'File: Open Folder / Project',
        icon: '📁',
        category: 'File',
        action: () => window.welcome?.openFolderPicker()
      },
      {
        id: 'save-file',
        label: 'File: Save Active File',
        icon: '💾',
        category: 'File',
        action: () => window.editor?.saveActiveFile()
      },
      {
        id: 'close-tab',
        label: 'File: Close Active Tab',
        icon: '✕',
        category: 'File',
        action: () => {
          if (window.editor?.activePath) window.editor.closeTab(window.editor.activePath);
        }
      },
      {
        id: 'format-document',
        label: 'Editor: Format Document',
        icon: '✨',
        category: 'Editor',
        action: () => window.editor?.editor?.getAction('editor.action.formatDocument')?.run()
      },
      {
        id: 'toggle-terminal',
        label: 'Terminal: Toggle Terminal Panel',
        icon: '🖥️',
        category: 'Terminal',
        action: () => document.getElementById('btn-toggle-terminal-top')?.click()
      },
      {
        id: 'clear-terminal',
        label: 'Terminal: Clear Terminal Output',
        icon: '🗑️',
        category: 'Terminal',
        action: () => window.terminal?.term?.clear()
      },
      {
        id: 'git-commit',
        label: 'Source Control: Commit Changes',
        icon: '⑂',
        category: 'Git',
        action: () => {
          document.getElementById('act-git')?.click();
          document.getElementById('git-commit-msg')?.focus();
        }
      },
      {
        id: 'git-view',
        label: 'Source Control: Show Git Changes',
        icon: '🌿',
        category: 'Git',
        action: () => document.getElementById('act-git')?.click()
      },
      {
        id: 'agent-focus',
        label: 'VALLEN AI: Focus Agent Chat',
        icon: '⚡',
        category: 'Agent',
        action: () => document.getElementById('btn-agent-focus')?.click()
      },
      {
        id: 'agent-new-session',
        label: 'VALLEN AI: Start New Chat Session',
        icon: '➕',
        category: 'Agent',
        action: () => window.copilot?.startNewSession()
      },
      {
        id: 'agent-clear-chat',
        label: 'VALLEN AI: Clear Chat Messages',
        icon: '🗑️',
        category: 'Agent',
        action: () => window.copilot?.clearChat()
      },
      {
        id: 'toggle-sidebar',
        label: 'View: Toggle Primary Side Bar',
        icon: '◫',
        category: 'View',
        action: () => document.getElementById('btn-toggle-sidebar')?.click()
      },
      {
        id: 'view-explorer',
        label: 'View: Show File Explorer',
        icon: '📁',
        category: 'View',
        action: () => document.getElementById('act-explorer')?.click()
      },
      {
        id: 'view-search',
        label: 'View: Search in Files',
        icon: '🔍',
        category: 'View',
        action: () => {
          document.getElementById('act-search')?.click();
          document.getElementById('search-input')?.focus();
        }
      },
      {
        id: 'view-welcome',
        label: 'View: Welcome / Getting Started',
        icon: '⚡',
        category: 'View',
        action: () => window.welcome?.showGettingStarted()
      },
      {
        id: 'view-shortcuts',
        label: 'View: Keyboard Shortcuts Watermark',
        icon: '⌨️',
        category: 'View',
        action: () => window.welcome?.showShortcutsView()
      },
      {
        id: 'toggle-fullscreen',
        label: 'View: Toggle Fullscreen Window',
        icon: '□',
        category: 'View',
        action: () => document.getElementById('btn-win-max')?.click()
      }
    ];
  }

  init() {
    this.close();
    this.bindEvents();
    this.loadFiles();
  }

  async loadFiles() {
    try {
      const res = await fetch('/api/workspace/all-files');
      this.files = await res.json();
    } catch (e) {
      console.error("Failed to load workspace files", e);
    }
  }

  bindEvents() {
    window.addEventListener('keydown', (e) => {
      // Ctrl + Shift + P: Open Command Palette
      if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === 'p') {
        e.preventDefault();
        this.open(true);
      } else if ((e.ctrlKey || e.metaKey) && !e.shiftKey && e.key.toLowerCase() === 'p') {
        // Ctrl + P: Open File Finder
        e.preventDefault();
        this.toggle();
      }
      if (e.key === 'Escape' && this.isOpen) {
        this.close();
      }
    });

    document.getElementById('quick-open-trigger')?.addEventListener('click', () => {
      this.open();
    });

    const backdrop = document.getElementById('command-palette-backdrop');
    backdrop?.addEventListener('click', (e) => {
      if (e.target === backdrop) this.close();
    });

    const input = document.getElementById('palette-input');
    input?.addEventListener('input', () => {
      this.selectedIndex = 0;
      this.renderResults();
    });

    input?.addEventListener('keydown', (e) => {
      const items = document.querySelectorAll('.palette-item');
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        if (items.length > 0) {
          this.selectedIndex = (this.selectedIndex + 1) % items.length;
          this.updateActiveItem();
        }
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        if (items.length > 0) {
          this.selectedIndex = (this.selectedIndex - 1 + items.length) % items.length;
          this.updateActiveItem();
        }
      } else if (e.key === 'Enter') {
        e.preventDefault();
        if (items.length > 0 && items[this.selectedIndex]) {
          items[this.selectedIndex].click();
        }
      }
    });
  }

  open(asCommand = false) {
    this.isOpen = true;
    const backdrop = document.getElementById('command-palette-backdrop');
    const input = document.getElementById('palette-input');
    backdrop?.classList.remove('hidden');
    if (input) {
      input.value = asCommand ? ">" : "";
      input.placeholder = asCommand ? "Type a command to run..." : "Type a file name or '>' for commands...";
      input.focus();
      if (asCommand) {
        input.setSelectionRange(1, 1);
      }
    }
    this.loadFiles().then(() => this.renderResults());
  }

  close() {
    this.isOpen = false;
    document.getElementById('command-palette-backdrop')?.classList.add('hidden');
  }

  toggle() {
    if (this.isOpen) this.close();
    else this.open(false);
  }

  renderResults() {
    const container = document.getElementById('palette-results');
    const rawVal = document.getElementById('palette-input')?.value || "";
    const isCommandMode = rawVal.startsWith('>');
    const query = (isCommandMode ? rawVal.slice(1) : rawVal).toLowerCase().trim();

    if (!container) return;
    container.innerHTML = "";

    if (isCommandMode) {
      const filtered = this.commands.filter(c =>
        c.label.toLowerCase().includes(query) || c.category.toLowerCase().includes(query)
      );

      if (filtered.length === 0) {
        container.innerHTML = '<div style="padding: 12px; color: var(--text-dim); text-align: center; font-size: 13px;">No commands matching</div>';
        return;
      }

      filtered.forEach((cmd, idx) => {
        const item = document.createElement('div');
        item.className = `palette-item ${idx === this.selectedIndex ? 'active' : ''}`;
        item.innerHTML = `
          <div style="display: flex; align-items: center; gap: 8px;">
            <span style="font-size: 13px;">${cmd.icon}</span>
            <span style="font-weight: 500; font-size: 13px;">${cmd.label}</span>
          </div>
          <span style="font-size: 11px; color: var(--accent-purple-light);">${cmd.category}</span>
        `;
        item.addEventListener('click', () => {
          this.close();
          cmd.action();
        });
        container.appendChild(item);
      });
      return;
    }

    // File Mode
    const filtered = this.files.filter(f =>
      f.name.toLowerCase().includes(query) || f.path.toLowerCase().includes(query)
    ).slice(0, 30);

    if (filtered.length === 0) {
      container.innerHTML = '<div style="padding: 12px; color: var(--text-dim); text-align: center; font-size: 13px;">No files matching</div>';
      return;
    }

    filtered.forEach((f, idx) => {
      const item = document.createElement('div');
      item.className = `palette-item ${idx === this.selectedIndex ? 'active' : ''}`;
      const icon = window.explorer ? window.explorer.getFileIcon(f.name, false) : '📄';
      item.innerHTML = `
        <div style="display: flex; align-items: center; gap: 8px;">
          <span>${icon}</span>
          <span style="font-weight: 600; font-size: 13px;">${f.name}</span>
        </div>
        <span style="font-size: 11px; color: var(--text-dim); font-family: var(--font-mono);">${f.path}</span>
      `;
      item.addEventListener('click', () => {
        this.close();
        if (window.welcome) window.welcome.hide();
        this.editorManager.openFile(f.path);
      });
      container.appendChild(item);
    });
  }

  updateActiveItem() {
    const items = document.querySelectorAll('.palette-item');
    items.forEach((it, i) => {
      if (i === this.selectedIndex) {
        it.classList.add('active');
        it.scrollIntoView({ block: 'nearest' });
      } else {
        it.classList.remove('active');
      }
    });
  }
}
window.PaletteManager = PaletteManager;

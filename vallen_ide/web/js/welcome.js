class WelcomeManager {
  constructor(editorManager) {
    this.editorManager = editorManager;
    this.recentStorageKey = 'vallen_ide_recent_projects';
    this.currentBrowsingPath = '/home/VALLEN/Desktop';
  }

  init() {
    this.renderRecentProjects();
    this.bindEvents();
  }

  bindEvents() {
    // Top logo click returns to Welcome
    document.getElementById('btn-show-getting-started')?.addEventListener('click', () => {
      this.showGettingStarted();
    });

    // Getting started tab click
    document.getElementById('tab-getting-started')?.addEventListener('click', (e) => {
      if (e.target.classList.contains('tab-close-icon')) {
        this.closeGettingStartedTab();
      } else {
        this.showGettingStarted();
      }
    });

    // Open a project button -> Try Native Picker first, then In-App Dialog
    document.getElementById('btn-gs-open-project')?.addEventListener('click', () => {
      this.openFolderPicker();
    });

    // In-app folder picker modal events
    document.getElementById('btn-close-folder-picker')?.addEventListener('click', () => {
      this.closeFolderPicker();
    });
    document.getElementById('btn-cancel-folder-picker')?.addEventListener('click', () => {
      this.closeFolderPicker();
    });
    document.getElementById('btn-confirm-folder-picker')?.addEventListener('click', () => {
      this.confirmOpenCurrentFolder();
    });

    document.getElementById('btn-clear-recent-projects')?.addEventListener('click', async (e) => {
      e.stopPropagation();
      if (confirm("Clear all recent projects from history?")) {
        await this.clearAllRecentProjects();
      }
    });
    document.getElementById('btn-folder-picker-go')?.addEventListener('click', () => {
      const input = document.getElementById('folder-picker-input');
      if (input && input.value.trim()) {
        this.browseTo(input.value.trim());
      }
    });
    document.getElementById('folder-picker-input')?.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        const input = document.getElementById('folder-picker-input');
        if (input && input.value.trim()) {
          this.browseTo(input.value.trim());
        }
      }
    });

    // Backdrop click to close folder picker
    const backdrop = document.getElementById('folder-picker-backdrop');
    backdrop?.addEventListener('click', (e) => {
      if (e.target === backdrop) {
        this.closeFolderPicker();
      }
    });

    // Clone & Connect buttons
    document.getElementById('btn-gs-clone')?.addEventListener('click', () => {
      const repo = prompt("Enter Git Repository URL to clone:");
      if (repo && window.terminal) {
        document.getElementById('bottom-terminal-panel')?.classList.remove('collapsed');
        window.terminal.term.writeln(`git clone ${repo}`);
        if (window.terminal.socket && window.terminal.socket.readyState === WebSocket.OPEN) {
          window.terminal.socket.send(JSON.stringify({ type: 'input', data: `git clone ${repo}\n` }));
        }
      }
    });

    document.getElementById('btn-gs-connect')?.addEventListener('click', () => {
      alert("Remote SSH / Container Connect: Ready to configure.");
    });
  }

  showGettingStarted() {
    document.getElementById('primary-sidebar')?.classList.add('collapsed');
    document.getElementById('copilot-panel')?.classList.add('collapsed');
    document.querySelectorAll('.act-btn').forEach(b => b.classList.remove('active'));

    let tab = document.getElementById('tab-getting-started');
    if (!tab) {
      const tabBar = document.getElementById('editor-tab-bar');
      if (tabBar) {
        tab = document.createElement('div');
        tab.className = 'vscode-tab';
        tab.id = 'tab-getting-started';
        tab.innerHTML = `
          <span class="tab-icon">⚡</span>
          <span class="tab-title">Welcome</span>
          <span class="tab-close-icon">✕</span>
        `;
        tab.addEventListener('click', (e) => {
          if (e.target.classList.contains('tab-close-icon')) {
            this.closeGettingStartedTab();
          } else {
            this.showGettingStarted();
          }
        });
        tabBar.prepend(tab);
      }
    }

    document.querySelectorAll('.vscode-tab').forEach(t => t.classList.remove('active'));
    tab?.classList.add('active');

    document.getElementById('getting-started-view')?.classList.remove('hidden');
    document.getElementById('center-shortcuts-view')?.classList.add('hidden');
    document.getElementById('monaco-viewport')?.classList.add('hidden');
    document.getElementById('editor-breadcrumbs')?.classList.add('hidden');
    document.getElementById('top-title-text').textContent = 'vallen [workspace] — Ctrl+P to search';
    this.renderRecentProjects();
  }

  hide() {
    document.getElementById('getting-started-view')?.classList.add('hidden');
  }

  // --- Folder Picker Logic ---
  async openFolderPicker() {
    // 1. Try Native OS Folder Picker first (VS Code behavior)
    try {
      const res = await fetch('/api/workspace/pick-folder', { method: 'POST' });
      if (res.ok) {
        const data = await res.json();
        if (data.status === 'ok' && data.path) {
          await this.openProject(data.path);
          return;
        } else if (data.status === 'cancel') {
          return; // User cancelled native chooser
        }
      }
    } catch (e) {
      console.warn("Native folder dialog unavailable, using in-app modal:", e);
    }

    // 2. Fallback: Show In-App Folder Picker Modal
    this.showInAppFolderPicker();
  }

  showInAppFolderPicker() {
    const backdrop = document.getElementById('folder-picker-backdrop');
    if (backdrop) {
      backdrop.classList.remove('hidden');
      this.browseTo(this.currentBrowsingPath);
    }
  }

  closeFolderPicker() {
    const backdrop = document.getElementById('folder-picker-backdrop');
    if (backdrop) {
      backdrop.classList.add('hidden');
    }
  }

  async browseTo(dirPath) {
    this.currentBrowsingPath = dirPath;
    const input = document.getElementById('folder-picker-input');
    const container = document.getElementById('folder-picker-list');
    if (input) input.value = dirPath;
    if (!container) return;

    container.innerHTML = '<div style="color: var(--text-dim); padding: 8px; font-size: 11px;">Loading directories...</div>';

    try {
      const res = await fetch(`/api/workspace/browse-folders?dir_path=${encodeURIComponent(dirPath)}`);
      const data = await res.json();
      container.innerHTML = "";

      if (data.parent_path) {
        const parentRow = document.createElement('div');
        parentRow.className = 'tree-node';
        parentRow.style.cssText = 'padding: 6px 10px; border-radius: 4px;';
        parentRow.innerHTML = `<span style="margin-right: 6px;">⬆️</span> <span style="font-weight: 600;">.. (Go Up)</span>`;
        parentRow.addEventListener('click', () => this.browseTo(data.parent_path));
        container.appendChild(parentRow);
      }

      if (!data.folders || data.folders.length === 0) {
        container.innerHTML += '<div style="color: var(--text-dim); padding: 8px; font-size: 11px;">No subdirectories found</div>';
        return;
      }

      data.folders.forEach(f => {
        const row = document.createElement('div');
        row.className = 'tree-node';
        row.style.cssText = 'padding: 6px 10px; display: flex; align-items: center; justify-content: space-between; border-radius: 4px;';
        row.innerHTML = `
          <div style="display: flex; align-items: center; gap: 8px; overflow: hidden;">
            <span>📁</span>
            <span style="font-weight: 500; color: #fff; overflow: hidden; text-overflow: ellipsis;">${f.name}</span>
          </div>
          <button class="btn-secondary" style="font-size: 10px; padding: 2px 8px;">Select</button>
        `;

        row.querySelector('button').addEventListener('click', (e) => {
          e.stopPropagation();
          this.openProject(f.path);
        });

        row.addEventListener('click', () => {
          this.browseTo(f.path);
        });

        container.appendChild(row);
      });
    } catch (e) {
      container.innerHTML = `<div style="color: var(--accent-red); padding: 8px; font-size: 11px;">Error: ${e.message}</div>`;
    }
  }

  confirmOpenCurrentFolder() {
    const input = document.getElementById('folder-picker-input');
    const path = input ? input.value.trim() : this.currentBrowsingPath;
    if (path) {
      this.openProject(path);
    }
  }

  async openProject(folderPath) {
    try {
      const res = await fetch('/api/workspace/open-project', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: folderPath })
      });
      const data = await res.json();

      if (res.ok) {
        this.closeFolderPicker();

        const projName = data.name || folderPath.split('/').pop() || 'WORKSPACE';
        const el = document.getElementById('sidebar-project-title');
        if (el) el.textContent = projName.toUpperCase();
        const topTitle = document.getElementById('top-title-text');
        if (topTitle) topTitle.textContent = `${projName} — Ctrl+P to search`;
        const bcRoot = document.getElementById('bc-root');
        if (bcRoot) bcRoot.textContent = projName.toLowerCase();

        document.getElementById('primary-sidebar')?.classList.remove('collapsed');
        document.getElementById('copilot-panel')?.classList.remove('collapsed');
        document.getElementById('act-explorer')?.classList.add('active');

        this.showShortcutsView();

        if (window.explorer) {
          window.explorer.refreshTree();
          window.explorer.loadGitStatus();
        }

        // Fresh session for newly opened project
        if (window.copilot) {
          window.copilot.loadHistory();
        }

        this.addRecentProject(projName, data.path || folderPath);
      } else {
        alert(data.detail || "Failed to open folder");
      }
    } catch (e) {
      alert("Error: " + e.message);
    }
  }

  showShortcutsView() {
    document.querySelectorAll('.vscode-tab').forEach(t => t.classList.remove('active'));
    document.getElementById('getting-started-view')?.classList.add('hidden');
    document.getElementById('center-shortcuts-view')?.classList.remove('hidden');
    document.getElementById('monaco-viewport')?.classList.add('hidden');
    document.getElementById('editor-breadcrumbs')?.classList.add('hidden');
  }

  closeGettingStartedTab() {
    document.getElementById('tab-getting-started')?.remove();
    this.showShortcutsView();
  }

  addRecentProject(name, fullPath) {
    let recents = this.getRecentProjects();
    recents = recents.filter(p => p.path !== fullPath);
    recents.unshift({ name, path: fullPath });
    if (recents.length > 10) recents.pop();
    localStorage.setItem(this.recentStorageKey, JSON.stringify(recents));
    this.renderRecentProjects();
  }

  getRecentProjects() {
    try {
      const saved = localStorage.getItem(this.recentStorageKey);
      if (saved) return JSON.parse(saved);
    } catch {}
    return [];
  }

  async clearAllRecentProjects() {
    localStorage.removeItem(this.recentStorageKey);
    try {
      await fetch('/api/workspace/clear-recent-projects', { method: 'POST' });
    } catch {}
    await this.renderRecentProjects();
  }

  async removeRecentProject(path) {
    let recents = this.getRecentProjects().filter(p => p.path !== path);
    localStorage.setItem(this.recentStorageKey, JSON.stringify(recents));
    try {
      await fetch('/api/workspace/remove-recent-project', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path })
      });
    } catch {}
    await this.renderRecentProjects();
  }

  async renderRecentProjects() {
    let list = [];
    try {
      const res = await fetch('/api/workspace/recent-projects');
      if (res.ok) {
        const serverProjs = await res.json();
        if (Array.isArray(serverProjs)) {
          list = serverProjs;
        }
      }
    } catch {}

    if (list.length === 0) {
      list = this.getRecentProjects();
    } else {
      localStorage.setItem(this.recentStorageKey, JSON.stringify(list));
    }

    const container = document.getElementById('gs-recent-projects-list');
    if (!container) return;
    container.innerHTML = "";

    if (list.length === 0) {
      container.innerHTML = '<div style="padding: 12px; color: var(--text-dim); text-align: center; font-size: 11px;">No recent projects found. Click "Open Folder" to start.</div>';
      return;
    }

    list.forEach(item => {
      const row = document.createElement('div');
      row.className = 'gs-recent-row';
      const cleanPath = item.path.replace('/home/VALLEN', '~');
      row.innerHTML = `
        <div style="display: flex; align-items: center; gap: 8px; overflow: hidden; flex: 1;">
          <span style="font-size: 12px;">📁</span>
          <span class="gs-recent-name">${item.name}</span>
          ${item.is_active ? '<span style="font-size: 9px; color: var(--accent-purple-light); border: 1px solid var(--accent-purple); padding: 0 4px; border-radius: 3px; font-weight: 700;">ACTIVE</span>' : ''}
        </div>
        <div style="display: flex; align-items: center; gap: 8px; flex-shrink: 0;">
          <span class="gs-recent-path">${cleanPath}</span>
          <span class="btn-remove-recent-item" title="Remove from recent" style="color: var(--text-dim); padding: 1px 5px; cursor: pointer; border-radius: 3px; font-size: 11px; transition: color 0.15s ease;">✕</span>
        </div>
      `;

      row.querySelector('.btn-remove-recent-item')?.addEventListener('click', async (e) => {
        e.stopPropagation();
        await this.removeRecentProject(item.path);
      });

      row.addEventListener('click', () => {
        this.openProject(item.path);
      });

      container.appendChild(row);
    });
  }
}
window.WelcomeManager = WelcomeManager;

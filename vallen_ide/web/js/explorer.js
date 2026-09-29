class ExplorerManager {
  constructor(editorManager) {
    this.editorManager = editorManager;
    this.expandedFolders = new Set();
  }

  async init() {
    this.bindEvents();
    await this.refreshTree();
    await this.loadGitStatus();
  }

  bindEvents() {
    document.getElementById('btn-new-file')?.addEventListener('click', () => this.promptCreate('file'));
    document.getElementById('btn-new-folder')?.addEventListener('click', () => this.promptCreate('folder'));
    document.getElementById('btn-refresh-tree')?.addEventListener('click', () => this.refreshTree());
    document.getElementById('btn-collapse-tree')?.addEventListener('click', () => this.collapseAll());

    // Search Box
    const searchInput = document.getElementById('search-input');
    searchInput?.addEventListener('keydown', async (e) => {
      if (e.key === 'Enter') {
        this.executeSearch(searchInput.value.trim());
      }
    });

    // Git Commit Button
    document.getElementById('btn-git-commit')?.addEventListener('click', async () => {
      const msgInput = document.getElementById('git-commit-msg');
      const msg = msgInput ? msgInput.value.trim() : "";
      if (!msg) {
        alert("Commit message cannot be empty");
        return;
      }

      try {
        const res = await fetch('/api/workspace/git-commit', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message: msg })
        });
        if (res.ok) {
          msgInput.value = "";
          await this.loadGitStatus();
          alert("✓ Commit successful!");
        } else {
          const err = await res.json();
          alert("Error commit: " + (err.detail || 'Failed'));
        }
      } catch (e) {
        alert("Error: " + e.message);
      }
    });
  }

  getFileIcon(name, isDir, isOpen = false) {
    if (isDir) return isOpen ? '📂' : '📁';
    const ext = name.split('.').pop().toLowerCase();
    const icons = {
      py: '🐍', js: '🟨', ts: '🔷', html: '🌐', css: '🎨',
      json: '📦', md: '📝', sh: '⚙️', toml: '⚙️', png: '🖼️',
      jpg: '🖼️', jpeg: '🖼️', gitignore: '🔒', svg: '🎨'
    };
    return icons[ext] || '📄';
  }

  async refreshTree() {
    const container = document.getElementById('file-tree-container');
    if (!container) return;
    container.innerHTML = '<div style="padding: 10px; color: var(--text-dim); font-size: 11px;">Loading files...</div>';

    try {
      const items = await this.fetchDir("");
      container.innerHTML = "";
      this.renderItems(items, container, 0);
    } catch (e) {
      container.innerHTML = `<div style="padding: 10px; color: var(--accent-red); font-size: 11px;">Error loading tree</div>`;
    }
  }

  collapseAll() {
    this.expandedFolders.clear();
    const subContainers = document.querySelectorAll('.tree-subcontainer');
    subContainers.forEach(c => c.style.display = 'none');
    const chevrons = document.querySelectorAll('.tree-chevron');
    chevrons.forEach(ch => ch.textContent = '›');
    const folderIcons = document.querySelectorAll('.tree-folder-icon');
    folderIcons.forEach(ic => ic.textContent = '📁');
  }

  async fetchDir(path) {
    const res = await fetch(`/api/workspace/tree?dir_path=${encodeURIComponent(path)}`);
    return await res.json();
  }

  renderItems(items, container, depth) {
    for (const item of items) {
      if (item.is_ignored) continue;

      const node = document.createElement('div');
      node.className = 'tree-node';
      node.style.paddingLeft = `${depth * 14 + 8}px`;

      if (item.is_dir) {
        const isExpanded = this.expandedFolders.has(item.path);
        const chevron = document.createElement('span');
        chevron.className = 'tree-chevron';
        chevron.textContent = isExpanded ? '⌄' : '›';

        const icon = document.createElement('span');
        icon.className = 'tree-node-icon tree-folder-icon';
        icon.textContent = this.getFileIcon(item.name, true, isExpanded);

        const label = document.createElement('span');
        label.className = 'tree-node-label';
        label.textContent = item.name;

        node.appendChild(chevron);
        node.appendChild(icon);
        node.appendChild(label);

        const subContainer = document.createElement('div');
        subContainer.className = 'tree-subcontainer';
        subContainer.style.display = isExpanded ? 'block' : 'none';

        node.addEventListener('click', async () => {
          if (subContainer.style.display === 'none') {
            subContainer.style.display = 'block';
            chevron.textContent = '⌄';
            icon.textContent = '📂';
            this.expandedFolders.add(item.path);

            if (subContainer.children.length === 0) {
              const subItems = await this.fetchDir(item.path);
              this.renderItems(subItems, subContainer, depth + 1);
            }
          } else {
            subContainer.style.display = 'none';
            chevron.textContent = '›';
            icon.textContent = '📁';
            this.expandedFolders.delete(item.path);
          }
        });

        // Right Click Context Menu
        node.addEventListener('contextmenu', (e) => {
          if (window.contextMenu) window.contextMenu.show(e, item);
        });

        container.appendChild(node);
        container.appendChild(subContainer);
      } else {
        const spacer = document.createElement('span');
        spacer.className = 'tree-chevron';
        spacer.textContent = ' ';

        const icon = document.createElement('span');
        icon.className = 'tree-node-icon';
        icon.textContent = this.getFileIcon(item.name, false);

        const label = document.createElement('span');
        label.className = 'tree-node-label';
        label.textContent = item.name;

        node.appendChild(spacer);
        node.appendChild(icon);
        node.appendChild(label);

        node.addEventListener('click', () => {
          document.querySelectorAll('.tree-node').forEach(n => n.classList.remove('active'));
          node.classList.add('active');
          this.editorManager.openFile(item.path);
        });

        node.addEventListener('contextmenu', (e) => {
          if (window.contextMenu) window.contextMenu.show(e, item);
        });

        container.appendChild(node);
      }
    }
  }

  async promptCreate(type) {
    const name = prompt(`Enter new ${type} name (relative path):`);
    if (!name) return;

    try {
      const res = await fetch('/api/workspace/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: name, type })
      });
      if (res.ok) {
        await this.refreshTree();
        if (type === 'file') {
          this.editorManager.openFile(name);
        }
      } else {
        const err = await res.json();
        alert(err.detail || 'Creation failed');
      }
    } catch (e) {
      alert("Error: " + e);
    }
  }

  async executeSearch(query) {
    const resultsContainer = document.getElementById('search-results');
    if (!resultsContainer) return;
    resultsContainer.innerHTML = '<div style="color: var(--text-dim); padding: 8px; font-size: 11px;">Searching...</div>';

    try {
      const res = await fetch('/api/workspace/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query, case_sensitive: false })
      });
      const results = await res.json();
      resultsContainer.innerHTML = "";

      if (results.length === 0) {
        resultsContainer.innerHTML = '<div style="color: var(--text-dim); padding: 8px; font-size: 11px;">No matches found</div>';
        return;
      }

      for (const r of results) {
        const item = document.createElement('div');
        item.className = 'tree-node';
        item.style.padding = '4px 8px';
        item.innerHTML = `
          <div style="display: flex; flex-direction: column; overflow: hidden; width: 100%;">
            <span style="color: var(--accent-cyan); font-family: var(--font-mono); font-size: 11px;">${r.path}:${r.line}</span>
            <span style="color: var(--text-muted); font-size: 11px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${r.content}</span>
          </div>
        `;
        item.addEventListener('click', () => {
          this.editorManager.openFileAtLine(r.path, r.line);
        });
        resultsContainer.appendChild(item);
      }
    } catch (e) {
      resultsContainer.innerHTML = `<div style="color: var(--accent-red); padding: 8px; font-size: 11px;">Search error</div>`;
    }
  }

  async loadGitStatus() {
    try {
      const res = await fetch('/api/workspace/git-status');
      const data = await res.json();

      const branchNameEl = document.getElementById('status-branch-name');
      const branchIcon = document.getElementById('status-branch')?.querySelector('span:first-child');
      const badge = document.getElementById('git-changes-count');
      const statusBadge = document.getElementById('status-changes-badge');
      const actBadge = document.getElementById('act-git-badge');
      const gitList = document.getElementById('git-changed-list');
      

      if (!data.is_git || !data.branch) {
        if (branchNameEl) branchNameEl.textContent = "No Git";
        if (badge) badge.textContent = "0";
        if (statusBadge) statusBadge.textContent = "0";
        if (actBadge) actBadge.classList.add('hidden');
        if (gitList) gitList.innerHTML = '<div style="padding: 10px; color: var(--text-dim); font-size: 11px; text-align: center;">Not a git repository</div>';
        return;
      }

      if (branchNameEl) branchNameEl.textContent = `${data.branch}*`;
      if (badge) badge.textContent = `${data.count || 0}`;
      if (statusBadge) statusBadge.textContent = `${data.count || 0}`;
      if (actBadge) {
        actBadge.textContent = `${data.count || 0}`;
        actBadge.classList.toggle('hidden', !data.count || data.count === 0);
      }

      
      if (!gitList) return;
      gitList.innerHTML = "";

      if (!data.modified || data.modified.length === 0) {
        gitList.innerHTML = '<div style="padding: 10px; color: var(--text-dim); font-size: 11px; text-align: center;">Working tree clean ✓</div>';
        return;
      }

      for (const f of data.modified) {
        const row = document.createElement('div');
        row.className = 'tree-node';
        row.style.padding = '4px 8px';
        const color = f.status === 'M' ? 'var(--accent-yellow)' : 'var(--accent-green)';
        row.innerHTML = `
          <div style="display: flex; align-items: center; justify-content: space-between; width: 100%;">
            <div style="display: flex; align-items: center; gap: 6px; overflow: hidden; flex: 1;">
              <span style="color: ${color}; font-weight: bold; font-size: 11px; width: 16px;">${f.status}</span>
              <span style="font-size: 12px; color: var(--text-main); overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${f.path}</span>
            </div>
            <button type="button" class="btn-mini-diff" title="View Git Diff" style="font-size: 10px; padding: 1px 6px; margin-left: 4px;">Diff</button>
          </div>
        `;
        row.querySelector('.btn-mini-diff')?.addEventListener('click', async (e) => {
          e.stopPropagation();
          try {
            const res = await fetch(`/api/workspace/git-file-diff?path=${encodeURIComponent(f.path)}`);
            if (res.ok) {
              const diffData = await res.json();
              window.editor?.showDiff(diffData);
            }
          } catch (err) {
            console.error("Git diff error", err);
          }
        });
        row.addEventListener('click', () => {
          this.editorManager.openFile(f.path);
        });
        gitList.appendChild(row);
      }
    } catch (e) {
      console.error("Git status error", e);
    }
  }
}
window.ExplorerManager = ExplorerManager;

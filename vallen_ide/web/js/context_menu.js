class ContextMenuManager {
  constructor(explorerManager, editorManager) {
    this.explorerManager = explorerManager;
    this.editorManager = editorManager;
    this.activeItem = null;
    this.menuEl = document.getElementById('file-context-menu');
  }

  init() {
    this.hide();
    this.bindEvents();
  }

  bindEvents() {
    document.addEventListener('click', (e) => {
      if (this.menuEl && !this.menuEl.contains(e.target)) {
        this.hide();
      }
    });

    document.getElementById('ctx-open')?.addEventListener('click', () => {
      if (this.activeItem && !this.activeItem.is_dir) {
        this.editorManager.openFile(this.activeItem.path);
      }
      this.hide();
    });

    document.getElementById('ctx-new-file')?.addEventListener('click', async () => {
      if (!this.activeItem) return;
      const baseDir = this.activeItem.is_dir ? this.activeItem.path : this.activeItem.path.split('/').slice(0, -1).join('/');
      const name = prompt(`New file name inside "${baseDir || '.'}":`);
      if (name) {
        const fullPath = baseDir ? `${baseDir}/${name}` : name;
        await fetch('/api/workspace/create', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path: fullPath, type: 'file' })
        });
        await this.explorerManager.refreshTree();
        this.editorManager.openFile(fullPath);
      }
      this.hide();
    });

    document.getElementById('ctx-new-folder')?.addEventListener('click', async () => {
      if (!this.activeItem) return;
      const baseDir = this.activeItem.is_dir ? this.activeItem.path : this.activeItem.path.split('/').slice(0, -1).join('/');
      const name = prompt(`New folder name inside "${baseDir || '.'}":`);
      if (name) {
        const fullPath = baseDir ? `${baseDir}/${name}` : name;
        await fetch('/api/workspace/create', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path: fullPath, type: 'folder' })
        });
        await this.explorerManager.refreshTree();
      }
      this.hide();
    });

    document.getElementById('ctx-rename')?.addEventListener('click', async () => {
      if (!this.activeItem) return;
      const oldPath = this.activeItem.path;
      const newName = prompt("Nama baru:", oldPath.split('/').pop());
      if (newName) {
        const parts = oldPath.split('/');
        parts.pop();
        const newPath = parts.length > 0 ? `${parts.join('/')}/${newName}` : newName;
        
        await fetch('/api/workspace/rename', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ old_path: oldPath, new_path: newPath })
        });
        this.explorerManager.refreshTree();
      }
      this.hide();
    });

    document.getElementById('ctx-delete')?.addEventListener('click', async () => {
      if (!this.activeItem) return;
      if (confirm(`Yakin ingin menghapus ${this.activeItem.path}?`)) {
        await fetch('/api/workspace/delete', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path: this.activeItem.path })
        });
        this.explorerManager.refreshTree();
      }
      this.hide();
    });

    document.getElementById('ctx-copy-path')?.addEventListener('click', () => {
      if (this.activeItem) {
        navigator.clipboard.writeText(this.activeItem.path);
      }
      this.hide();
    });
  }

  show(e, item) {
    e.preventDefault();
    this.activeItem = item;
    if (!this.menuEl) return;

    this.menuEl.style.left = `${e.clientX}px`;
    this.menuEl.style.top = `${e.clientY}px`;
    this.menuEl.classList.remove('hidden');
  }

  hide() {
    if (this.menuEl) {
      this.menuEl.classList.add('hidden');
    }
  }
}
window.ContextMenuManager = ContextMenuManager;

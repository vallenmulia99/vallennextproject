class TerminalManager {
  constructor() {
    this.instances = new Map(); // id -> { id, name, term, fitAddon, socket, el }
    this.activeId = null;
    this.nextId = 1;
  }

  get activeInstance() {
    return this.instances.get(this.activeId) || null;
  }

  get term() {
    return this.activeInstance ? this.activeInstance.term : null;
  }

  get fitAddon() {
    return this.activeInstance ? this.activeInstance.fitAddon : null;
  }

  get socket() {
    return this.activeInstance ? this.activeInstance.socket : null;
  }

  init() {
    this.bindGlobalEvents();
    // Create initial primary terminal
    this.createTerminal("bash");
  }

  bindGlobalEvents() {
    document.getElementById('btn-add-terminal')?.addEventListener('click', () => {
      this.createTerminal("bash");
    });

    window.addEventListener('resize', () => {
      if (this.fitAddon) {
        this.fitAddon.fit();
        this.sendResize(this.activeId);
      }
    });
  }

  createTerminal(shellName = "bash") {
    const container = document.getElementById('terminal-container');
    if (!container || !window.Terminal) return null;

    const id = String(this.nextId++);
    const displayName = `${id}: ${shellName}`;

    // 1. Create sub-wrapper element inside terminal-container
    const wrapper = document.createElement('div');
    wrapper.id = `term-viewport-${id}`;
    wrapper.className = 'term-instance-viewport';
    wrapper.style.display = 'none';
    container.appendChild(wrapper);

    // 2. Initialize xterm & fit addon
    const term = new window.Terminal({
      cursorBlink: true,
      fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
      fontSize: 12,
      lineHeight: 1.2,
      theme: {
        background: '#080a0f',
        foreground: '#f8fafc',
        cursor: '#38bdf8',
        selectionBackground: '#2563eb55',
        black: '#1e293b',
        red: '#ef4444',
        green: '#10b981',
        yellow: '#f59e0b',
        blue: '#3b82f6',
        magenta: '#8b5cf6',
        cyan: '#06b6d4',
        white: '#f1f5f9'
      }
    });

    let fitAddon = null;
    if (window.FitAddon && window.FitAddon.FitAddon) {
      fitAddon = new window.FitAddon.FitAddon();
      term.loadAddon(fitAddon);
    }

    term.open(wrapper);

    // 3. Connect WebSocket for this terminal ID
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${location.host}/ws/terminal/${id}`;
    const socket = new WebSocket(wsUrl);
    socket.binaryType = 'arraybuffer';

    socket.onopen = () => {
      term.writeln(`\x1b[1;35m⚡ VALLEN IDE Terminal [${displayName}] Connected\x1b[0m\r\n`);
      if (term.cols && term.rows) {
        socket.send(JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows }));
      }
    };

    socket.onmessage = (event) => {
      if (event.data instanceof ArrayBuffer) {
        const text = new TextDecoder().decode(event.data);
        term.write(text);
      } else {
        term.write(event.data);
      }
    };

    socket.onclose = () => {
      term.writeln('\r\n\x1b[1;31m[Session closed]\x1b[0m\r\n');
    };

    term.onData((data) => {
      if (socket && socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: 'input', data }));
      }
    });

    const instance = { id, name: displayName, term, fitAddon, socket, el: wrapper };
    this.instances.set(id, instance);

    // 4. Render Tabs and Switch
    this.renderTabs();
    this.switchTerminal(id);

    return instance;
  }

  switchTerminal(id) {
    if (!this.instances.has(id)) return;
    this.activeId = id;

    // Show only active viewport
    this.instances.forEach((inst, key) => {
      if (key === id) {
        inst.el.style.display = 'block';
        if (inst.fitAddon) {
          setTimeout(() => {
            inst.fitAddon.fit();
            this.sendResize(id);
          }, 50);
        }
        inst.term.focus();
      } else {
        inst.el.style.display = 'none';
      }
    });

    this.renderTabs();
  }

  closeTerminal(id) {
    const inst = this.instances.get(id);
    if (!inst) return;

    try {
      if (inst.socket && inst.socket.readyState === WebSocket.OPEN) {
        inst.socket.close();
      }
      inst.term.dispose();
      inst.el.remove();
    } catch {}

    this.instances.delete(id);

    if (this.activeId === id) {
      const remaining = Array.from(this.instances.keys());
      if (remaining.length > 0) {
        this.switchTerminal(remaining[remaining.length - 1]);
      } else {
        this.createTerminal("bash");
      }
    } else {
      this.renderTabs();
    }
  }

  renderTabs() {
    const subtabsList = document.getElementById('term-subtabs-list');
    if (!subtabsList) return;
    subtabsList.innerHTML = '';

    this.instances.forEach((inst, id) => {
      const chip = document.createElement('div');
      chip.className = `term-chip ${id === this.activeId ? 'active' : ''}`;
      chip.title = `Terminal ${inst.name} (Click to switch)`;
      chip.innerHTML = `
        <span>${inst.name}</span>
        <span class="chip-close" title="Close this terminal">✕</span>
      `;

      chip.addEventListener('click', () => {
        this.switchTerminal(id);
      });

      chip.querySelector('.chip-close')?.addEventListener('click', (e) => {
        e.stopPropagation();
        this.closeTerminal(id);
      });

      subtabsList.appendChild(chip);
    });
  }

  sendResize(id = null) {
    const targetId = id || this.activeId;
    const inst = this.instances.get(targetId);
    if (inst && inst.socket && inst.socket.readyState === WebSocket.OPEN && inst.term) {
      inst.socket.send(JSON.stringify({
        type: 'resize',
        cols: inst.term.cols,
        rows: inst.term.rows
      }));
    }
  }

  runCommand(cmd, targetId = null) {
    // 1. Open bottom terminal panel if collapsed
    const panel = document.getElementById('bottom-terminal-panel');
    if (panel) {
      panel.classList.remove('collapsed');
    }

    // 2. Switch to Terminal tab if Output/Problems was active
    document.getElementById('term-tab-terminal')?.click();

    // 3. Select target instance or active instance
    let inst = targetId ? this.instances.get(targetId) : this.activeInstance;
    if (!inst) {
      inst = this.createTerminal("bash");
    }

    if (inst) {
      this.switchTerminal(inst.id);
      setTimeout(() => {
        if (inst.socket && inst.socket.readyState === WebSocket.OPEN) {
          inst.socket.send(JSON.stringify({ type: 'input', data: `${cmd}\n` }));
        }
      }, 100);
    }
  }
}
window.TerminalManager = TerminalManager;

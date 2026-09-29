class CopilotManager {
  constructor(editorManager) {
    this.editorManager = editorManager;
    this.isStreaming = false;
    this.autopilotActive = true;
    this.alwaysAccept = (localStorage.getItem('vallen_always_accept') !== 'false');
    this.abortController = null;
    this.isFileContextActive = false;
    this.steps = [];
    this.isStepsCollapsed = false;
    this.pendingAttachments = [];
  }

  init() {
    this.setupMarkedRenderer();
    this.bindEvents();
    this.setupProgressCardControls();
    this.setupMentionAutocomplete();
    this.loadHistory();
  }

  setupMarkedRenderer() {
    if (window.marked) {
      window.marked.setOptions({
        gfm: true,
        breaks: true,
        highlight: function(code, lang) {
          if (window.hljs) {
            if (lang && hljs.getLanguage(lang)) {
              try {
                return hljs.highlight(code, { language: lang, ignoreIllegals: true }).value;
              } catch {}
            }
            try {
              return hljs.highlightAuto(code).value;
            } catch {}
          }
          return code;
        }
      });
    }
  }

  bindEvents() {
    const actionBtn = document.getElementById('btn-submit-prompt');
    const textarea = document.getElementById('chat-prompt-textarea');

    // Smart Action Button: sends if idle, stops if streaming
    actionBtn?.addEventListener('click', () => {
      if (this.isStreaming) {
        this.stopGeneration();
      } else {
        this.sendMessage();
      }
    });

    textarea?.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        if (!this.isStreaming) {
          this.sendMessage();
        }
      }
    });

    // Sliding toggle: Always Accept
    const alwaysAcceptToggle = document.getElementById('always-accept-switch');
    if (alwaysAcceptToggle) {
      const track = alwaysAcceptToggle.querySelector('.slider-track');
      track?.classList.toggle('active', this.alwaysAccept);
      alwaysAcceptToggle.classList.toggle('active', this.alwaysAccept);
      alwaysAcceptToggle.addEventListener('click', () => {
        this.alwaysAccept = !this.alwaysAccept;
        localStorage.setItem('vallen_always_accept', this.alwaysAccept);
        track?.classList.toggle('active', this.alwaysAccept);
        alwaysAcceptToggle.classList.toggle('active', this.alwaysAccept);
      });
    }

    // Sliding toggle: Autopilot
    const autopilotToggle = document.getElementById('autopilot-switch');
    if (autopilotToggle) {
      const track = autopilotToggle.querySelector('.slider-track');
      track?.classList.toggle('active', this.autopilotActive);
      autopilotToggle.classList.toggle('active', this.autopilotActive);
      autopilotToggle.addEventListener('click', () => {
        this.autopilotActive = !this.autopilotActive;
        track?.classList.toggle('active', this.autopilotActive);
        autopilotToggle.classList.toggle('active', this.autopilotActive);
      });
    }

    // Toggleable # File Context Button
        // Attach File / Photo input click
    const fileInput = document.getElementById('chat-file-input');
    document.getElementById('btn-attach-file')?.addEventListener('click', () => {
      fileInput?.click();
    });

    fileInput?.addEventListener('change', (e) => {
      if (e.target.files) {
        this.processFileList(e.target.files);
        fileInput.value = '';
      }
    });

    // Clipboard image paste (Ctrl+V)
    textarea?.addEventListener('paste', (e) => {
      if (e.clipboardData && e.clipboardData.items) {
        const items = e.clipboardData.items;
        for (let i = 0; i < items.length; i++) {
          if (items[i].type.startsWith('image/')) {
            const blob = items[i].getAsFile();
            if (blob) {
              e.preventDefault();
              this.addFileAttachment(blob, `pasted_screenshot_${Date.now()}.png`);
            }
          }
        }
      }
    });

    // Drag & drop files onto chat card
    const chatCard = document.querySelector('.floating-chat-card');
    if (chatCard) {
      chatCard.addEventListener('dragover', (e) => {
        e.preventDefault();
        chatCard.style.borderColor = 'var(--accent-purple)';
      });
      chatCard.addEventListener('dragleave', () => {
        chatCard.style.borderColor = '';
      });
      chatCard.addEventListener('drop', (e) => {
        e.preventDefault();
        chatCard.style.borderColor = '';
        if (e.dataTransfer && e.dataTransfer.files) {
          this.processFileList(e.dataTransfer.files);
        }
      });
    }

        // New Session & Clear Chat
    document.getElementById('btn-new-chat-session')?.addEventListener('click', () => this.startNewSession());
    document.getElementById('btn-clear-chat')?.addEventListener('click', () => this.clearChat());
    document.getElementById('btn-chat-history')?.addEventListener('click', () => this.openHistoryModal());
    document.getElementById('btn-close-history-modal')?.addEventListener('click', () => this.closeHistoryModal());
    const historyBackdrop = document.getElementById('session-history-backdrop');
    historyBackdrop?.addEventListener('click', (e) => {
      if (e.target === historyBackdrop) this.closeHistoryModal();
    });

    document.getElementById('btn-close-copilot')?.addEventListener('click', () => {
      document.getElementById('copilot-panel')?.classList.add('collapsed');
      if (this.editorManager) this.editorManager.layout();
    });
  }

  
  processFileList(files) {
    Array.from(files).forEach(f => this.addFileAttachment(f));
  }

  addFileAttachment(file, customName = null) {
    const reader = new FileReader();
    const isImage = file.type.startsWith('image/');
    const name = customName || file.name || 'attachment';

    reader.onload = (e) => {
      this.pendingAttachments.push({
        name: name,
        type: isImage ? 'image' : 'file',
        mime_type: file.type || (isImage ? 'image/png' : 'text/plain'),
        size: file.size,
        data: e.target.result
      });
      this.renderAttachmentPreviews();
      document.getElementById('btn-submit-prompt')?.classList.add('active');
    };

    reader.readAsDataURL(file);
  }

  removeAttachment(index) {
    this.pendingAttachments.splice(index, 1);
    this.renderAttachmentPreviews();
  }

  renderAttachmentPreviews() {
    const container = document.getElementById('chat-attachments-preview');
    if (!container) return;

    if (!this.pendingAttachments || this.pendingAttachments.length === 0) {
      container.classList.add('hidden');
      container.innerHTML = '';
      return;
    }

    container.classList.remove('hidden');
    container.innerHTML = '';

    this.pendingAttachments.forEach((att, idx) => {
      if (att.type === 'image') {
        const wrap = document.createElement('div');
        wrap.className = 'attachment-img-wrap';
        wrap.innerHTML = `
          <img src="${att.data}" class="attachment-img-preview" alt="${att.name}" title="${att.name}" />
          <button type="button" class="attachment-remove-btn" style="position: absolute; top: -5px; right: -5px;" title="Remove image">✕</button>
        `;
        wrap.querySelector('button').addEventListener('click', (e) => {
          e.stopPropagation();
          this.removeAttachment(idx);
        });
        container.appendChild(wrap);
      } else {
        const chip = document.createElement('div');
        chip.className = 'attachment-chip';
        chip.innerHTML = `
          <span>📄</span>
          <span style="font-family: var(--font-mono); font-size: 11px; max-width: 140px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${att.name}</span>
          <button type="button" class="attachment-remove-btn" title="Remove file">✕</button>
        `;
        chip.querySelector('button').addEventListener('click', (e) => {
          e.stopPropagation();
          this.removeAttachment(idx);
        });
        container.appendChild(chip);
      }
    });
  }

  setupProgressCardControls() {
    const header = document.getElementById('progress-card-header');
    const chevron = document.getElementById('btn-toggle-progress-steps');
    const list = document.getElementById('progress-steps-list');

    header?.addEventListener('click', () => {
      this.isStepsCollapsed = !this.isStepsCollapsed;
      list?.classList.toggle('collapsed', this.isStepsCollapsed);
      chevron?.classList.toggle('collapsed', this.isStepsCollapsed);
    });
  }

  // --- Live Glowing Activity & Progress Checklist Engine ---
  startProgressTracking() {
    this.steps = [];
    const card = document.getElementById('agent-progress-card');
    const beacon = document.getElementById('progress-pulse-beacon');
    const label = document.getElementById('progress-status-label');
    const list = document.getElementById('progress-steps-list');
    const counter = document.getElementById('progress-step-counter');

    if (card) card.classList.remove('hidden');
    if (beacon) {
      beacon.className = 'pulse-beacon';
    }
    if (label) label.textContent = 'Analyzing & Planning...';
    if (counter) counter.textContent = '0/1';
    if (list) list.innerHTML = '';

    this.addStep('init', 'Analyzing prompt and workspace context', 'running');
  }

  updateLiveStatus(text) {
    const label = document.getElementById('progress-status-label');
    if (label) label.textContent = text;
  }

  addStep(id, text, status = 'running') {
    // Complete previous running step
    for (const s of this.steps) {
      if (s.status === 'running') {
        s.status = 'completed';
      }
    }

    // Check if step exists
    const existing = this.steps.find(s => s.id === id);
    if (existing) {
      existing.text = text;
      existing.status = status;
    } else {
      this.steps.push({ id, text, status });
    }

    this.renderSteps();
  }

  completeStep(id, updateText = null) {
    const step = this.steps.find(s => s.id === id);
    if (step) {
      step.status = 'completed';
      if (updateText) step.text = updateText;
    }
    this.renderSteps();
  }

  renderSteps() {
    const list = document.getElementById('progress-steps-list');
    const counter = document.getElementById('progress-step-counter');
    if (!list) return;

    list.innerHTML = '';
    const completedCount = this.steps.filter(s => s.status === 'completed').length;
    const totalCount = Math.max(this.steps.length, 1);

    if (counter) {
      counter.textContent = `${completedCount}/${totalCount}`;
    }

    this.steps.forEach(s => {
      const row = document.createElement('div');
      row.className = 'progress-step-item';

      let iconHtml = '';
      let labelClass = 'step-label';

      if (s.status === 'completed') {
        iconHtml = '<span class="step-icon check">✓</span>';
        labelClass += ' completed';
      } else if (s.status === 'running') {
        iconHtml = '<span class="step-icon spinner">⟳</span>';
        labelClass += ' active';
      } else {
        iconHtml = '<span class="step-icon pending">○</span>';
      }

      row.innerHTML = `
        <div class="step-item-left">
          ${iconHtml}
          <span class="${labelClass}">${s.text}</span>
        </div>
      `;
      list.appendChild(row);
    });

    list.scrollTop = list.scrollHeight;
  }

  finishProgressTracking(success = true, hitLimit = false) {
    for (const s of this.steps) {
      if (s.status === 'running') s.status = 'completed';
    }
    this.renderSteps();

    const beacon = document.getElementById('progress-pulse-beacon');
    const label = document.getElementById('progress-status-label');

    if (beacon) {
      if (!success) {
        beacon.className = 'pulse-beacon error';
      } else if (hitLimit) {
        beacon.className = 'pulse-beacon warning';
      } else {
        beacon.className = 'pulse-beacon done';
      }
    }
    if (label) {
      if (!success) {
        label.textContent = '✕ Stopped with error';
      } else if (hitLimit) {
        label.textContent = '⏸ Reached round limit (Click Lanjut)';
      } else {
        label.textContent = '✓ All tasks completed';
      }
    }
  }

  sendQuickPrompt(text) {
    const input = document.getElementById('chat-prompt-textarea');
    if (input) {
      input.value = text;
      input.focus();
    }
    this.submitPrompt();
  }

  sendLanjutPrompt() {
    this.sendQuickPrompt('Lanjutkan pekerjaan sampai tuntas dan compile/test kembali untuk memverifikasi.');
  }

  async startNewSession() {
    try {
      const res = await fetch('/api/agent/new-session', { method: 'POST' });
      const data = await res.json();
      if (data && data.session_id) {
        localStorage.setItem('vallen_copilot_session_id', data.session_id);
        await this.loadHistory(data.session_id);
        return;
      }
    } catch (e) {
      console.error('Failed to start new session:', e);
    }
    await this.clearChat();
  }

  async clearChat() {
    const currentSid = localStorage.getItem('vallen_copilot_session_id');
    try {
      await fetch('/api/agent/clear-chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: currentSid || null })
      });
    } catch (e) {
      console.error('Failed to clear chat on server:', e);
    }
    const stream = document.getElementById('copilot-messages-stream');
    if (stream) stream.innerHTML = '';
    const hero = document.getElementById('copilot-welcome-hero');
    const wf = document.getElementById('copilot-workflows-list');
    const card = document.getElementById('agent-progress-card');
    if (hero) hero.classList.remove('hidden');
    if (wf) wf.classList.remove('hidden');
    if (card) card.classList.add('hidden');
  }

  selectWorkflow(workflowTitle) {
    const textarea = document.getElementById('chat-prompt-textarea');
    if (textarea) {
      textarea.value = `[Workflow: ${workflowTitle}]\n`;
      textarea.focus();
      document.getElementById('btn-submit-prompt')?.classList.add('active');
    }
  }

  stopGeneration() {
    if (this.abortController) {
      this.abortController.abort();
      this.abortController = null;
    }
    this.isStreaming = false;
    this.toggleButtons(false);
    this.finishProgressTracking(false);
  }

  toggleButtons(isStreaming) {
    const actionBtn = document.getElementById('btn-submit-prompt');
    if (!actionBtn) return;
    const sendIcon = actionBtn.querySelector('.icon-send');
    const stopIcon = actionBtn.querySelector('.icon-stop');

    if (isStreaming) {
      actionBtn.classList.add('streaming');
      actionBtn.title = 'Stop Generation';
      sendIcon?.classList.add('hidden');
      stopIcon?.classList.remove('hidden');
    } else {
      actionBtn.classList.remove('streaming');
      actionBtn.title = 'Send Message (Enter)';
      stopIcon?.classList.add('hidden');
      sendIcon?.classList.remove('hidden');
    }
  }

  async handleDiffAction(cardId, diff, action) {
    const card = document.getElementById(cardId);
    if (card) {
      const actionsRow = card.querySelector('.diff-actions-row');
      if (actionsRow) {
        if (action === 'accept') {
          actionsRow.innerHTML = `<span style="color: var(--accent-green); font-weight: 600; font-size: 11px;">✓ Changes Accepted</span>`;
        } else {
          actionsRow.innerHTML = `<span style="color: var(--text-dim); font-size: 11px;">✕ Changes Reverted</span>`;
        }
      }
    }

    if (action === 'accept') {
      await this.editorManager.acceptDiff(diff);
    } else {
      await this.editorManager.rejectDiff(diff);
    }
  }

  askWithContext(userPrompt, selectedCode = "", autoSend = false) {
    const panel = document.getElementById("copilot-panel");
    if (panel) {
      panel.classList.remove("collapsed");
      document.getElementById("act-agent")?.classList.add("active");
    }

    const textarea = document.getElementById("chat-prompt-textarea");
    if (!textarea) return;

    let fullPrompt = userPrompt;
    if (selectedCode && selectedCode.trim()) {
      const activePath = this.editorManager?.activePath || "selected code";
      const ext = activePath.split(".").pop() || "";
      fullPrompt += `\n\n\`\`\`${ext}\n// File: ${activePath}\n${selectedCode.trim()}\n\`\`\``;
    }

    textarea.value = fullPrompt;
    textarea.focus();
    textarea.style.height = "auto";
    textarea.style.height = Math.min(textarea.scrollHeight, 180) + "px";
    document.getElementById("btn-submit-prompt")?.classList.add("active");

    if (autoSend) {
      setTimeout(() => this.sendMessage(), 100);
    }
  }

  async sendMessage() {
    const textarea = document.getElementById('chat-prompt-textarea');
    const prompt = textarea.value.trim();
    const hasAttachments = this.pendingAttachments && this.pendingAttachments.length > 0;
    if ((!prompt && !hasAttachments) || this.isStreaming) return;

    const actualPrompt = prompt || (hasAttachments ? "Analyze the attached file(s)/image(s)." : "");
    textarea.value = '';
    document.getElementById('btn-submit-prompt')?.classList.remove('active');
    this.isStreaming = true;
    this.toggleButtons(true);

    document.getElementById('copilot-welcome-hero')?.classList.add('hidden');
    document.getElementById('copilot-workflows-list')?.classList.add('hidden');

    const sentAttachments = [...this.pendingAttachments];
    this.pendingAttachments = [];
    this.renderAttachmentPreviews();

    this.appendUserMessage(actualPrompt, sentAttachments);
    this.startProgressTracking();

    let context = '';
    // Auto-inject active file if user typed @active or @file
    if ((actualPrompt.includes('@active') || actualPrompt.includes('@file')) && this.editorManager && this.editorManager.activePath) {
      const activeFile = this.editorManager.activePath;
      const code = this.editorManager.editor ? this.editorManager.editor.getValue() : '';
      context += "[Active File @" + activeFile + "]\n```\n" + code.slice(0, 3500) + "\n```\n\n";
    }

    // Extract any @files mentioned in prompt (e.g. @index.html) and inject contents
    const mentionMatches = [...actualPrompt.matchAll(/@([\w\.\-\/]+\.\w+)/g)];
    for (const m of mentionMatches) {
      const filePath = m[1];
      if (filePath === 'file' || filePath === 'active') continue;
      try {
        const res = await fetch(`/api/workspace/file?path=${encodeURIComponent(filePath)}`);
        if (res.ok) {
          const fileData = await res.json();
          if (fileData && fileData.content) {
            context += "[Referenced File Context @" + filePath + "]\n```\n" + fileData.content.slice(0, 4000) + "\n```\n\n";
          }
        }
      } catch {}
    }

    const modeSelect = document.getElementById('agent-mode-dropdown');
    const mode = modeSelect ? modeSelect.value : 'auto';
    if (mode === 'ask') {
      context = `[MODE: ASK / READ-ONLY ONLY]\n` + context;
    }

    const modelSelect = document.getElementById('model-select');
    const model = (modelSelect && modelSelect.value !== 'default') ? modelSelect.value : null;

    const agentBubble = this.createAgentBubble();
    this.abortController = new AbortController();
    try {
      const response = await fetch('/api/agent/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          prompt: actualPrompt,
          context,
          model,
          mode,
          session_id: localStorage.getItem('vallen_copilot_session_id') || undefined,
          attachments: sentAttachments,
          autopilot: this.autopilotActive
        }),
        signal: this.abortController.signal
      });

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const raw = line.slice(6).trim();
            if (raw === '[DONE]') continue;

            try {
              const event = JSON.parse(raw);
              this.handleAgentEvent(event, agentBubble);
            } catch (err) {
              console.error('Parse event error', err);
            }
          }
        }
      }
      this.finishProgressTracking(true, Boolean(agentBubble._hitRoundLimit));
    } catch (e) {
      if (e.name !== 'AbortError') {
        this.appendError(agentBubble, 'Error: ' + e.message);
        this.finishProgressTracking(false);
      }
    } finally {
      this.isStreaming = false;
      this.abortController = null;
      this.toggleButtons(false);
      const activeSid = localStorage.getItem('vallen_copilot_session_id');
      if (activeSid) {
        fetch(`/api/agent/history?session_id=${encodeURIComponent(activeSid)}`)
          .then(r => r.json())
          .then(d => {
            if (d && d.title) {
              const sessTitle = document.getElementById('copilot-session-title');
              if (sessTitle) sessTitle.textContent = d.title;
            }
          }).catch(() => {});
      }
      if (window.editor && window.editor.openTabs) {
        for (const [openPath] of window.editor.openTabs) {
          window.editor.syncOpenFile(openPath);
        }
      }
      if (window.explorer) {
        window.explorer.refreshTree();
        window.explorer.loadGitStatus();
      }
    }
  }

  appendUserMessage(text, attachments = []) {
    const container = document.getElementById('copilot-messages-stream');
    const bubble = document.createElement('div');
    bubble.className = 'chat-bubble-user';

    if (attachments && attachments.length > 0) {
      const attWrap = document.createElement('div');
      attWrap.style.cssText = 'display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 6px;';
      attachments.forEach(att => {
        if (att.type === 'image') {
          const img = document.createElement('img');
          img.src = att.data;
          img.style.cssText = 'max-width: 180px; max-height: 120px; border-radius: 6px; border: 1px solid rgba(255,255,255,0.2); object-fit: cover; cursor: pointer; display: block;';
          img.onclick = () => window.open(att.data, '_blank');
          attWrap.appendChild(img);
        } else {
          const chip = document.createElement('div');
          chip.style.cssText = 'padding: 2px 6px; background: rgba(0,0,0,0.4); border-radius: 4px; font-size: 10.5px; font-family: monospace; display: flex; align-items: center; gap: 4px;';
          chip.innerHTML = `<span>📎</span> <span>${att.name}</span>`;
          attWrap.appendChild(chip);
        }
      });
      bubble.appendChild(attWrap);
    }

    const textNode = document.createElement('div');
    textNode.className = 'user-message-text';
    textNode.style.cssText = 'white-space: pre-wrap; word-break: break-word; user-select: text !important;';
    textNode.textContent = text;
    bubble.appendChild(textNode);

    // User Message Action Buttons (Copy & Resend)
    const actionsRow = document.createElement('div');
    actionsRow.className = 'user-bubble-actions';
    actionsRow.innerHTML = `
      <button type="button" class="btn-user-action btn-copy-user" title="Salin pertanyaan">
        <span>📋</span><span>Salin</span>
      </button>
      <button type="button" class="btn-user-action btn-resend-user" title="Kirim ulang pertanyaan ini">
        <span>🔄</span><span>Kirim Ulang</span>
      </button>
    `;

    const copyBtn = actionsRow.querySelector('.btn-copy-user');
    copyBtn?.addEventListener('click', async (e) => {
      e.stopPropagation();
      await navigator.clipboard.writeText(text);
      copyBtn.innerHTML = '<span>✓</span><span>Tersalin!</span>';
      setTimeout(() => {
        copyBtn.innerHTML = '<span>📋</span><span>Salin</span>';
      }, 2000);
    });

    const resendBtn = actionsRow.querySelector('.btn-resend-user');
    resendBtn?.addEventListener('click', (e) => {
      e.stopPropagation();
      const textarea = document.getElementById('chat-prompt-textarea');
      if (textarea) {
        textarea.value = text;
        textarea.focus();
        document.getElementById('btn-submit-prompt')?.classList.add('active');
        this.sendMessage();
      }
    });

    bubble.appendChild(actionsRow);
    container.appendChild(bubble);
    container.scrollTop = container.scrollHeight;
  }

  createAgentBubble() {
    const container = document.getElementById('copilot-messages-stream');
    const bubble = document.createElement('div');
    bubble.className = 'chat-bubble-agent';

    bubble.innerHTML = `
      <div class="agent-header-pill" style="display: flex; align-items: center; justify-content: space-between; width: 100%;">
        <span>⚡ VALLEN AGENT</span>
        <div class="agent-header-actions" style="display: flex; align-items: center; gap: 6px;">
          <button type="button" class="btn-bubble-action btn-copy-agent" title="Salin respon">
            <span>📋</span><span>Salin</span>
          </button>
        </div>
      </div>
      <div class="agent-thinking-wrapper"></div>
      <div class="agent-tools-container"></div>
      <div class="agent-diffs-container"></div>
      <div class="agent-text-content" style="color: var(--text-main); user-select: text !important;"></div>
    `;

    const copyBtn = bubble.querySelector('.btn-copy-agent');
    copyBtn?.addEventListener('click', async (e) => {
      e.stopPropagation();
      const textToCopy = bubble._rawText || bubble.querySelector('.agent-text-content')?.innerText || '';
      if (textToCopy) {
        await navigator.clipboard.writeText(textToCopy);
        copyBtn.innerHTML = '<span>✓</span><span>Tersalin!</span>';
        setTimeout(() => {
          copyBtn.innerHTML = '<span>📋</span><span>Salin</span>';
        }, 2000);
      }
    });

    bubble._diffDataMap = new Map();
    container.appendChild(bubble);
    container.scrollTop = container.scrollHeight;
    return bubble;
  }

  handleAgentEvent(event, bubble) {
    const textContainer = bubble.querySelector('.agent-text-content');
    const thinkingWrapper = bubble.querySelector('.agent-thinking-wrapper');
    const toolsContainer = bubble.querySelector('.agent-tools-container');
    const diffsContainer = bubble.querySelector('.agent-diffs-container');
    const chatContainer = document.getElementById('copilot-messages-stream');

    if (event.kind === 'reasoning') {
      this.updateLiveStatus('💭 Thinking & Analyzing...');
      let thinkingCard = thinkingWrapper.querySelector('.agent-thinking-card');
      if (!thinkingCard) {
        thinkingCard = document.createElement('div');
        thinkingCard.className = 'agent-thinking-card';
        thinkingCard.innerHTML = `
          <div class="thinking-header">
            <span>💭 Thinking...</span>
          </div>
          <div class="thinking-body"></div>
        `;
        thinkingCard.querySelector('.thinking-header').addEventListener('click', () => {
          const body = thinkingCard.querySelector('.thinking-body');
          body.classList.toggle('hidden');
        });
        thinkingWrapper.appendChild(thinkingCard);
        this.addStep('reasoning', 'Reasoning & formulating architecture plan', 'running');
      }
      const body = thinkingCard.querySelector('.thinking-body');
      body.textContent += event.data;
      chatContainer.scrollTop = chatContainer.scrollHeight;
    } else if (event.kind === 'token') {
      this.updateLiveStatus('✍️ Generating response...');
      if (!bubble._rawText) bubble._rawText = '';
      bubble._rawText += event.data;
      if (window.marked) {
        textContainer.innerHTML = window.marked.parse(bubble._rawText);
      } else {
        textContainer.textContent = bubble._rawText;
      }
      if (!bubble._enhanceDebounce) {
        bubble._enhanceDebounce = setTimeout(() => {
          this.enhanceCodeBlocks(textContainer);
          bubble._enhanceDebounce = null;
        }, 150);
      }
      chatContainer.scrollTop = chatContainer.scrollHeight;
    } else if (event.kind === 'round_limit') {
      const data = event.data || {};
      const maxR = data.max_rounds || 50;
      bubble._hitRoundLimit = true;
      this.updateLiveStatus(`⏸ Limit ${maxR} rounds reached. Click Lanjut to keep going.`);
      const warnCard = document.createElement('div');
      warnCard.className = 'agent-round-limit-card';
      warnCard.style.cssText = 'display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 8px 12px; background: rgba(245, 158, 11, 0.15); border: 1px solid rgba(245, 158, 11, 0.4); border-radius: 6px; margin: 8px 0;';
      warnCard.innerHTML = `
        <span style="font-size: 11.5px; color: #fbbf24;">⏸ <strong>Mencapai Batas ${maxR} Ronde:</strong> Tekan Lanjut untuk meneruskan task tanpa mengetik ulang.</span>
        <button type="button" class="btn-primary" style="font-size: 11px; padding: 3px 10px; background: #d97706; flex-shrink: 0;" onclick="window.copilot.sendLanjutPrompt()">⚡ Lanjut Terus</button>
      `;
      toolsContainer.appendChild(warnCard);
      chatContainer.scrollTop = chatContainer.scrollHeight;
    } else if (event.kind === 'tool_start') {
      const toolData = event.data || {};
      const toolName = toolData.tool || toolData.name || 'tool';
      const args = toolData.args || {};

      let stepLabel = `Running ${toolName}`;
      if (toolName === 'read' || toolName === 'read_file') {
        const p = args.filePath || args.path || '';
        stepLabel = `Read ${p.split('/').pop() || p}`;
      } else if (toolName === 'write' || toolName === 'write_file') {
        const p = args.filePath || args.path || '';
        stepLabel = `Write ${p.split('/').pop() || p}`;
      } else if (toolName === 'edit' || toolName === 'edit_file') {
        const p = args.filePath || args.path || '';
        stepLabel = `Edit ${p.split('/').pop() || p}`;
      } else if (toolName === 'glob') {
        stepLabel = `Scan workspace (${args.pattern || '*'})`;
      } else if (toolName === 'grep') {
        stepLabel = `Search for "${args.pattern || ''}"`;
      } else if (toolName === 'shell') {
        stepLabel = `Exec: ${(args.command || '').slice(0, 24)}`;
      } else if (toolName === 'todowrite') {
        stepLabel = 'Update project tasks';
        if (Array.isArray(args.todos)) {
          this.steps = args.todos.map((t, idx) => ({
            id: t.id || `todo-${idx}`,
            text: t.content,
            status: t.status === 'completed' ? 'completed' : (t.status === 'in_progress' ? 'running' : 'pending')
          }));
          this.renderSteps();
        }
      } else if (toolName === 'skill') {
        stepLabel = `Load skill: ${args.name || ''}`;
      }

      this.updateLiveStatus(`⚙️ ${stepLabel}...`);
      const stepId = `tool-${Date.now()}`;
      this.addStep(stepId, stepLabel, 'running');

      const card = document.createElement('div');
      card.className = 'agent-tool-card';
      card.id = stepId;
      const isSudoCmd = (toolName === 'shell' && (args.command || '').includes('sudo '));
      const termBtnHtml = (toolName === 'shell' && args.command) ? `
        <button type="button" class="btn-mini-diff" style="margin-left: 6px; ${isSudoCmd ? 'background: rgba(239, 68, 68, 0.25); border-color: var(--accent-red); color: #fff;' : ''}" title="${isSudoCmd ? 'Jalankan dengan hak akses root (sudo) di terminal live' : 'Run in live Linux terminal'}" onclick='window.terminal.runCommand(${JSON.stringify(args.command)})'>${isSudoCmd ? '🔑 Run Sudo' : '🖥️ Terminal'}</button>
      ` : '';

      if (isSudoCmd) {
        const bp = document.getElementById('bottom-terminal-panel');
        if (bp && bp.classList.contains('collapsed')) {
          bp.classList.remove('collapsed');
          if (window.terminal && window.terminal.fitAddon) {
            setTimeout(() => window.terminal.fitAddon.fit(), 100);
          }
        }
      }
      card.innerHTML = `
        <div class="tool-card-header">
          <div style="display: flex; align-items: center; gap: 6px;">
            <span style="color: var(--accent-cyan);">⚙️ ${toolName}</span>
            ${termBtnHtml}
          </div>
          <span style="font-size: 10px; color: var(--text-muted);">${stepLabel}</span>
        </div>
      `;
      toolsContainer.appendChild(card);
      chatContainer.scrollTop = chatContainer.scrollHeight;
    } else if (event.kind === 'tool_result') {
      const res = event.data || {};
      const toolName = res.tool || res.name || 'tool';
      const lastCard = toolsContainer.querySelector('.agent-tool-card:last-child');

      if (lastCard) {
        const header = lastCard.querySelector('.tool-card-header');
        if (header) {
          const status = res.success !== false ? '✓ Done' : '✕ Failed';
          const color = res.success !== false ? 'var(--accent-green)' : 'var(--accent-red)';
          header.innerHTML = `
            <span style="color: var(--accent-cyan);">⚙️ ${toolName}</span>
            <span style="font-size: 10px; color: ${color}; font-weight: bold;">${status}</span>
          `;
        }
        const outText = res.output || res.error || '';
        const dataObj = res.data || {};
        const isSudoNeeded = dataObj.requires_sudo || (outText && (outText.includes("sudo: a password is required") || outText.includes("terminal is required") || outText.includes("no tty present")));

        if (outText) {
          const outEl = document.createElement('pre');
          outEl.className = 'tool-card-output';
          outEl.textContent = outText.slice(0, 1000);
          lastCard.appendChild(outEl);
        }

        if (isSudoNeeded) {
          const bp = document.getElementById('bottom-terminal-panel');
          if (bp && bp.classList.contains('collapsed')) {
            bp.classList.remove('collapsed');
            if (window.terminal && window.terminal.fitAddon) {
              setTimeout(() => window.terminal.fitAddon.fit(), 100);
            }
          }
          const targetCmd = dataObj.command || (res.args && res.args.command) || '';
          const banner = document.createElement('div');
          banner.style.cssText = 'margin-top: 6px; padding: 6px 10px; background: rgba(239, 68, 68, 0.15); border: 1px solid rgba(239, 68, 68, 0.4); border-left: 3px solid var(--accent-red); border-radius: 4px; font-size: 11px; display: flex; align-items: center; justify-content: space-between; gap: 8px;';
          banner.innerHTML = `
            <span style="color: #fca5a5;">🔑 <strong>Sudo Password Diperlukan:</strong> Ketik password root Anda di Terminal bawah.</span>
            ${targetCmd ? `<button type="button" class="btn-primary" style="font-size: 10px; padding: 2px 8px; background: var(--accent-red); flex-shrink: 0;" onclick='window.terminal.runCommand(${JSON.stringify(targetCmd)})'>Jalankan di Terminal</button>` : ''}
          `;
          lastCard.appendChild(banner);
        }
      }

      // Mark the step completed with green checkmark
      if (this.steps.length > 0) {
        const lastStep = this.steps[this.steps.length - 1];
        if (lastStep.status === 'running') {
          lastStep.status = 'completed';
          this.renderSteps();
        }
      }

      chatContainer.scrollTop = chatContainer.scrollHeight;
    } else if (event.kind === 'diff_detected') {
      const diff = event.data;
      const cleanPath = window.editor ? window.editor.normalizePath(diff.path) : diff.path;
      diff.path = cleanPath;

      bubble._diffDataMap.set(cleanPath, diff);

      if (this.alwaysAccept) {
        window.editor.acceptDiff(diff);
      } else if (window.editor) {
        window.editor.syncOpenFile(cleanPath);
      }

      this.addStep(`diff-${cleanPath}`, `Modified ${cleanPath} (+${diff.additions} -${diff.deletions})`, 'completed');
      this.renderGroupedDiffWidget(bubble);
      chatContainer.scrollTop = chatContainer.scrollHeight;
    } else if (event.kind === 'error') {
      this.appendError(bubble, event.data);
      this.finishProgressTracking(false);
    }
  }

  renderGroupedDiffWidget(bubble) {
    const diffsContainer = bubble.querySelector('.agent-diffs-container');
    if (!diffsContainer) return;

    const diffs = Array.from(bubble._diffDataMap.values());
    if (diffs.length === 0) {
      diffsContainer.innerHTML = '';
      return;
    }

    let totalAdd = 0;
    let totalDel = 0;
    diffs.forEach(d => {
      totalAdd += (d.additions || 0);
      totalDel += (d.deletions || 0);
    });

    const isAuto = this.alwaysAccept;
    const countLabel = diffs.length === 1 ? '1 file changed' : `${diffs.length} files changed`;

    let widget = diffsContainer.querySelector('.grouped-diff-widget');
    if (!widget) {
      widget = document.createElement('div');
      widget.className = 'grouped-diff-widget';
      diffsContainer.appendChild(widget);
    }

    widget.innerHTML = `
      <div class="grouped-diff-header">
        <div class="grouped-diff-title-wrap">
          <svg width="14" height="14" viewBox="0 0 16 16" fill="var(--accent-purple)"><path d="M1 8h14v1H1V8zm3-5h8v1H4V3zm2 10h4v1H6v-1z"/></svg>
          <span>Changes (${countLabel})</span>
          <span class="diff-badge-add">+${totalAdd}</span>
          <span class="diff-badge-del">-${totalDel}</span>
          ${isAuto ? '<span class="grouped-diff-badge-auto">✓ Auto-Applied</span>' : ''}
        </div>
        <div style="display: flex; align-items: center; gap: 6px;">
          ${!isAuto ? `
            <button class="btn-primary" style="font-size: 10px; padding: 2px 8px;" id="btn-group-accept-all">✓ Accept All</button>
          ` : ''}
          <button class="btn-secondary" style="font-size: 10px; padding: 2px 8px; color: var(--accent-red);" id="btn-group-revert-all">✕ Revert All</button>
        </div>
      </div>
      <div class="grouped-diff-list" id="grouped-diff-list"></div>
    `;

    const listEl = widget.querySelector('#grouped-diff-list');
    diffs.forEach(diff => {
      const item = document.createElement('div');
      item.className = 'grouped-diff-item';
      const icon = window.explorer ? window.explorer.getFileIcon(diff.path, false) : '📄';

      item.innerHTML = `
        <div class="grouped-diff-item-left">
          <span>${icon}</span>
          <span class="grouped-diff-filename" title="${diff.path}">${diff.path}</span>
        </div>
        <div class="grouped-diff-item-right">
          <span class="diff-badge-add">+${diff.additions}</span>
          <span class="diff-badge-del">-${diff.deletions}</span>
          <button class="btn-mini-diff" title="View Diff in Editor">Diff</button>
        </div>
      `;

      item.querySelector('.btn-mini-diff').addEventListener('click', (e) => {
        e.stopPropagation();
        window.editor.showDiff(diff);
      });

      item.addEventListener('click', () => {
        window.editor.openFile(diff.path);
      });

      listEl.appendChild(item);
    });

    widget.querySelector('#btn-group-accept-all')?.addEventListener('click', async (e) => {
      e.stopPropagation();
      for (const d of diffs) {
        await window.editor.acceptDiff(d);
      }
      widget.querySelector('.grouped-diff-header .grouped-diff-title-wrap').innerHTML += `
        <span class="grouped-diff-badge-auto">✓ All Accepted</span>
      `;
      widget.querySelector('#btn-group-accept-all')?.remove();
    });

    widget.querySelector('#btn-group-revert-all')?.addEventListener('click', async (e) => {
      e.stopPropagation();
      if (confirm(`Revert all changes (${diffs.length} files)?`)) {
        for (const d of diffs) {
          await window.editor.rejectDiff(d);
        }
        widget.querySelector('.grouped-diff-header .grouped-diff-title-wrap').innerHTML += `
          <span style="color: var(--text-dim); font-size: 10px;">✕ All Reverted</span>
        `;
        widget.querySelector('#btn-group-revert-all')?.remove();
      }
    });
  }

  appendError(bubble, err) {
    const div = document.createElement('div');
    div.style.color = 'var(--accent-red)';
    div.style.fontSize = '12px';
    div.style.padding = '6px';
    div.textContent = typeof err === 'string' ? err : JSON.stringify(err);
    bubble.appendChild(div);
  }

  async openHistoryModal() {
    const backdrop = document.getElementById('session-history-backdrop');
    const list = document.getElementById('session-history-list');
    const title = document.getElementById('history-modal-title');
    if (!backdrop || !list) return;

    list.innerHTML = '<div style="color: var(--text-dim); padding: 12px; font-size: 11px; text-align: center;">Loading sessions...</div>';
    backdrop.classList.remove('hidden');

    try {
      const res = await fetch('/api/agent/sessions');
      const data = await res.json();
      if (title) title.textContent = `Chat History for ${data.project_name || 'Project'}`;
      list.innerHTML = '';

      if (!data.sessions || data.sessions.length === 0) {
        list.innerHTML = '<div style="color: var(--text-dim); padding: 12px; font-size: 11px; text-align: center;">No chat sessions found for this project.</div>';
        return;
      }

      const currentActiveSid = localStorage.getItem('vallen_copilot_session_id');
      data.sessions.forEach(s => {
        const item = document.createElement('div');
        item.className = 'tree-node';
        const isCurrent = s.id === currentActiveSid;
        item.style.cssText = `padding: 8px 12px; display: flex; align-items: center; justify-content: space-between; border-radius: 4px; cursor: pointer; border: 1px solid ${isCurrent ? 'var(--accent-purple)' : 'var(--border-subtle)'}; background: ${isCurrent ? 'var(--bg-active)' : 'transparent'}; margin-bottom: 4px;`;

        const dateStr = s.updated_at ? new Date(s.updated_at).toLocaleString() : '';
        item.innerHTML = `
          <div style="display: flex; flex-direction: column; gap: 2px; overflow: hidden; flex: 1;" class="session-target">
            <div style="font-weight: 600; color: #fff; font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${s.title} ${isCurrent ? '<span style="font-size: 9px; color: var(--accent-purple-light); border: 1px solid var(--accent-purple); padding: 1px 4px; border-radius: 3px; margin-left: 4px;">ACTIVE</span>' : ''}</div>
            <div style="font-size: 10px; color: var(--text-dim);">${dateStr} · ${s.model || 'default model'}</div>
          </div>
          <div style="display: flex; align-items: center; gap: 8px; flex-shrink: 0;">
            <span class="badge" style="font-size: 10px;">${s.message_count} msgs</span>
            <span class="btn-delete-session" title="Delete this session" style="color: var(--text-dim); padding: 2px 6px; cursor: pointer; border-radius: 3px; font-size: 12px;">🗑</span>
          </div>
        `;

        item.querySelector('.session-target')?.addEventListener('click', async () => {
          this.closeHistoryModal();
          localStorage.setItem('vallen_copilot_session_id', s.id);
          await this.loadHistory(s.id);
        });

        item.querySelector('.btn-delete-session')?.addEventListener('click', async (e) => {
          e.stopPropagation();
          if (confirm(`Delete session "${s.title}"?`)) {
            await fetch('/api/agent/delete-session', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ session_id: s.id })
            });
            if (s.id === currentActiveSid) {
              await this.startNewSession();
            } else {
              this.openHistoryModal();
            }
          }
        });

        list.appendChild(item);
      });
    } catch (e) {
      list.innerHTML = `<div style="color: var(--accent-red); padding: 12px; font-size: 11px;">Error loading sessions: ${e.message}</div>`;
    }
  }

  closeHistoryModal() {
    document.getElementById('session-history-backdrop')?.classList.add('hidden');
  }

  async loadHistory(sessionId = null) {
    try {
      const targetId = sessionId || localStorage.getItem('vallen_copilot_session_id');
      const url = targetId ? `/api/agent/history?session_id=${encodeURIComponent(targetId)}` : '/api/agent/history';
      const res = await fetch(url);
      if (!res.ok) return;
      const data = await res.json();
      if (!data) return;

      if (data.session_id) {
        localStorage.setItem('vallen_copilot_session_id', data.session_id);
      }

      // Update project & session labels
      const projLabel = document.getElementById('copilot-project-label');
      if (projLabel && data.project_name) projLabel.textContent = data.project_name.toUpperCase();
      const sessTitle = document.getElementById('copilot-session-title');
      if (sessTitle) sessTitle.textContent = data.title || 'New Session';

      const container = document.getElementById('copilot-messages-stream');
      if (!container) return;
      container.innerHTML = '';

      if (!data.messages || data.messages.length === 0) {
        document.getElementById('copilot-welcome-hero')?.classList.remove('hidden');
        document.getElementById('copilot-workflows-list')?.classList.remove('hidden');
        return;
      }

      // Hide hero & workflows since we have history
      document.getElementById('copilot-welcome-hero')?.classList.add('hidden');
      document.getElementById('copilot-workflows-list')?.classList.add('hidden');

      for (const m of data.messages) {
        if (m.role === 'user') {
          this.appendUserMessage(m.content);
        } else if (m.role === 'assistant') {
          if (m.content && m.content.trim()) {
            const bubble = this.createAgentBubble();
            const textContainer = bubble.querySelector('.agent-text-content');
            if (window.marked) {
              textContainer.innerHTML = window.marked.parse(m.content);
            } else {
              textContainer.textContent = m.content;
            }
            this.enhanceCodeBlocks(textContainer);
          }
        }
      }
      container.scrollTop = container.scrollHeight;
    } catch (e) {
      console.warn("Failed to load chat history:", e);
    }
  }

  enhanceCodeBlocks(container) {
    if (!container) return;
    const preBlocks = container.querySelectorAll('pre');
    preBlocks.forEach(pre => {
      if (pre._enhanced) return;
      pre._enhanced = true;

      const codeEl = pre.querySelector('code');
      const langMatch = codeEl ? codeEl.className.match(/language-(\w+)/) : null;
      const lang = langMatch ? langMatch[1] : 'code';

      const header = document.createElement('div');
      header.className = 'code-block-header';
      header.innerHTML = `
        <span class="code-block-lang">${lang}</span>
        <div class="code-block-actions">
          <button type="button" class="btn-code-action btn-copy" title="Copy code snippet">📋 Copy</button>
          <button type="button" class="btn-code-action btn-insert" title="Insert code at editor cursor">📥 Insert</button>
          <button type="button" class="btn-code-action btn-replace" title="Replace active file content">⚡ Replace File</button>
        </div>
      `;

      header.querySelector('.btn-copy')?.addEventListener('click', async (e) => {
        e.stopPropagation();
        const codeText = codeEl ? codeEl.innerText : pre.innerText;
        await navigator.clipboard.writeText(codeText);
        const btn = header.querySelector('.btn-copy');
        if (btn) {
          const orig = btn.innerHTML;
          btn.innerHTML = '✓ Copied!';
          setTimeout(() => { btn.innerHTML = orig; }, 2000);
        }
      });

      header.querySelector('.btn-insert')?.addEventListener('click', (e) => {
        e.stopPropagation();
        const codeText = codeEl ? codeEl.innerText : pre.innerText;
        if (window.editor && window.editor.insertAtCursor) {
          window.editor.insertAtCursor(codeText);
        }
      });

      header.querySelector('.btn-replace')?.addEventListener('click', (e) => {
        e.stopPropagation();
        const codeText = codeEl ? codeEl.innerText : pre.innerText;
        if (window.editor && window.editor.replaceActiveContent) {
          if (confirm('Replace entire content of active editor file with this code?')) {
            window.editor.replaceActiveContent(codeText);
          }
        }
      });

      pre.parentNode.insertBefore(header, pre);
    });
  }

  setupMentionAutocomplete() {
    const textarea = document.getElementById('chat-prompt-textarea');
    const container = document.querySelector('.copilot-input-container');
    if (!textarea || !container) return;

    let popup = document.getElementById('copilot-mention-popup');
    if (!popup) {
      popup = document.createElement('div');
      popup.id = 'copilot-mention-popup';
      popup.className = 'mention-popup hidden';
      container.appendChild(popup);
    }

    let filesCache = [];
    let selectedIndex = 0;
    let currentFiltered = [];
    let currentMatch = null;

    const loadProjectFiles = async () => {
      try {
        const res = await fetch('/api/workspace/all-files');
        if (res.ok) {
          const data = await res.json();
          filesCache = (data || []).map(d => d.path || d.name).filter(Boolean);
        } else {
          const treeRes = await fetch('/api/workspace/tree');
          const data = await treeRes.json();
          const list = [];
          const walk = (items) => {
            for (const it of items) {
              if (!it.is_dir && !it.is_ignored) list.push(it.path);
              if (it.children) walk(it.children);
            }
          };
          walk(data);
          filesCache = list;
        }
      } catch {}
    };
    loadProjectFiles();

    const selectMention = (filePath) => {
      const cursor = textarea.selectionStart;
      const textBefore = textarea.value.slice(0, cursor);
      if (!currentMatch) return;
      const beforeAt = textBefore.slice(0, currentMatch.index);
      const afterCursor = textarea.value.slice(cursor);
      textarea.value = beforeAt + '@' + filePath + ' ' + afterCursor;
      textarea.focus();
      const newPos = beforeAt.length + filePath.length + 2;
      textarea.setSelectionRange(newPos, newPos);
      popup.classList.add('hidden');
      currentFiltered = [];
      currentMatch = null;
    };

    const renderPopup = () => {
      popup.innerHTML = '';
      currentFiltered.forEach((f, idx) => {
        const item = document.createElement('div');
        item.className = 'mention-item' + (idx === selectedIndex ? ' selected' : '');
        item.innerHTML = `
          <span>📄</span>
          <span style="font-weight: 500;">${f.split('/').pop()}</span>
          <span class="mention-path">${f}</span>
        `;
        item.addEventListener('mousedown', (e) => {
          e.preventDefault();
          selectMention(f);
        });
        popup.appendChild(item);
      });
      const activeEl = popup.children[selectedIndex];
      if (activeEl) {
        activeEl.scrollIntoView({ block: 'nearest' });
      }
    };

    textarea.addEventListener('input', () => {
      const cursor = textarea.selectionStart;
      const textBefore = textarea.value.slice(0, cursor);
      const match = textBefore.match(/@([\w\.\-\/]*)$/);

      if (!match) {
        popup.classList.add('hidden');
        currentFiltered = [];
        currentMatch = null;
        return;
      }

      currentMatch = match;
      const query = match[1].toLowerCase();
      currentFiltered = filesCache.filter(f => f.toLowerCase().includes(query)).slice(0, 10);

      if (currentFiltered.length === 0) {
        popup.classList.add('hidden');
        return;
      }

      selectedIndex = 0;
      renderPopup();
      popup.classList.remove('hidden');
    });

    textarea.addEventListener('keydown', (e) => {
      if (!popup.classList.contains('hidden') && currentFiltered.length > 0) {
        if (e.key === 'ArrowDown') {
          e.preventDefault();
          selectedIndex = (selectedIndex + 1) % currentFiltered.length;
          renderPopup();
        } else if (e.key === 'ArrowUp') {
          e.preventDefault();
          selectedIndex = (selectedIndex - 1 + currentFiltered.length) % currentFiltered.length;
          renderPopup();
        } else if (e.key === 'Enter' || e.key === 'Tab') {
          e.preventDefault();
          e.stopPropagation();
          selectMention(currentFiltered[selectedIndex]);
        } else if (e.key === 'Escape') {
          e.preventDefault();
          popup.classList.add('hidden');
        }
      }
    }, true);

    document.addEventListener('click', (e) => {
      if (!popup.contains(e.target) && e.target !== textarea) {
        popup.classList.add('hidden');
      }
    });
  }
}
window.CopilotManager = CopilotManager;

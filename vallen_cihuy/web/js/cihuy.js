/**
 * ⚡ VALLEN CIHUY — Studio Client Controller
 * Powered by 'code-architect' Skill & VALLEN NEXT Engine.
 */

(function () {
  let currentBlueprint = null;
  let activeCanvasTab = 'prd';
  let isReasoningActive = true;
  let loadedQuestions = [];
  let userAnswers = {};

  const heroContainer = document.getElementById('hero-container');
  const wizardContainer = document.getElementById('wizard-container');
  const canvasContainer = document.getElementById('canvas-container');
  const heroInput = document.getElementById('hero-input');
  const btnSubmit = document.getElementById('btn-submit-hero');
  const canvasEditor = document.getElementById('canvas-editor');
  const canvasTitle = document.getElementById('canvas-app-title');
  const toggleReasoning = document.getElementById('toggle-reasoning');
  const questionsListEl = document.getElementById('wizard-questions-list');
  const btnWizardSubmit = document.getElementById('btn-wizard-submit');
  const btnWizardQuick = document.getElementById('btn-wizard-quick');
  const btnWizardBack = document.getElementById('btn-wizard-back');

  // ── 1. Auto-resize Textarea ──
  function autoResizeTextarea() {
    if (!heroInput) return;
    heroInput.style.height = 'auto';
    const newHeight = Math.min(heroInput.scrollHeight, 180);
    heroInput.style.height = Math.max(newHeight, 60) + 'px';
  }

  if (heroInput) {
    heroInput.addEventListener('input', autoResizeTextarea);
    setTimeout(() => heroInput.focus(), 100);
  }

  // ── 2. Load Dynamic AI Models ──
  async function loadModels() {
    try {
      const res = await fetch('/api/agent/info');
      if (res.ok) {
        const data = await res.json();
        const select = document.getElementById('model-select');
        if (data.models && data.models.length && select) {
          select.innerHTML = '';
          data.models.forEach(m => {
            const opt = document.createElement('option');
            opt.value = m.id;
            opt.textContent = m.display_name || m.id;
            if (m.id === data.active_model) opt.selected = true;
            select.appendChild(opt);
          });
        }
      }
    } catch (e) {
      console.warn("Could not load dynamic models:", e);
    }
  }
  loadModels();

  // ── 3. Toggle Mode Arsitek (Reasoning) ──
  if (toggleReasoning) {
    toggleReasoning.addEventListener('click', () => {
      isReasoningActive = !isReasoningActive;
      toggleReasoning.classList.toggle('active', isReasoningActive);
    });
  }

  // ── 4. Preset Suggestion Starter Cards ──
  const presetData = {
    "pos-kasir": "Aplikasi Point of Sale (POS) modern untuk usaha laundry kiloan dan satuan. Fitur: input nota order masuk, kalkulasi otomatis berat/harga, pelacak status cuci-kering-setrika-siap ambil, cetak struk via bluetooth thermal printer, serta dashboard laporan omset harian kasir.",
    "micro-saas": "Platform Micro-SaaS AI yang mengubah 1 video YouTube atau audio podcast menjadi 10 thread Twitter/X, artikel LinkedIn, dan rangkuman blog post otomatis. Dilengkapi sistem token kredit dan langganan payment gateway.",
    "inventory-erp": "Sistem inventaris internal untuk toko retail multi-cabang. Fitur: scan barcode SKU barang, mutasi transfer antar cabang, notifikasi stok menipis (low stock alert), rekap kartu stok, dan export laporan bulanan ke Excel/PDF.",
    "cli-devkit": "Terminal CLI tool untuk automasi setup boilerplate repository baru: auto konfigurasi Git pre-commit hooks, linter formatting, Dockerfile multi-stage, dan GitHub Actions CI/CD pipeline dengan 1 perintah interaktif."
  };

  document.querySelectorAll('.starter-card').forEach(card => {
    card.addEventListener('click', () => {
      const key = card.dataset.preset;
      if (presetData[key] && heroInput) {
        heroInput.value = presetData[key];
        autoResizeTextarea();
        heroInput.focus();
      }
    });
  });

  // ── 5. Step 1: Start Discovery Questions ──
  async function startDiscovery() {
    if (!heroInput) return;
    const idea = heroInput.value.trim();
    if (!idea) {
      alert("Silakan ceritakan ide aplikasi terlebih dahulu!");
      heroInput.focus();
      return;
    }

    if (btnSubmit) {
      btnSubmit.disabled = true;
      btnSubmit.innerHTML = `
        <svg class="spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:16px;height:16px;animation:spin 1s linear infinite;">
          <circle cx="12" cy="12" r="10" stroke-opacity="0.25"></circle>
          <path d="M12 2a10 10 0 0 1 10 10"></path>
        </svg>
      `;
    }

    const stack = document.getElementById('stack-select')?.value || "Modern Fullstack";
    const chosenModel = document.getElementById('model-select')?.value || null;

    try {
      const res = await fetch('/api/cihuy/questions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          idea,
          target_stack: stack,
          model: chosenModel
        })
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Gagal merumuskan pertanyaan arsitektur");
      }

      const data = await res.json();
      loadedQuestions = data.questions || [];
      renderQuestionsWizard(loadedQuestions);

      // Switch to Wizard View
      if (heroContainer) heroContainer.classList.add('hidden');
      if (wizardContainer) wizardContainer.classList.remove('hidden');
      window.scrollTo({ top: 0, behavior: 'smooth' });
    } catch (err) {
      alert("Error: " + err.message);
    } finally {
      if (btnSubmit) {
        btnSubmit.disabled = false;
        btnSubmit.innerHTML = `
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:16px;height:16px;">
            <line x1="5" y1="12" x2="19" y2="12"></line>
            <polyline points="12 5 19 12 12 19"></polyline>
          </svg>
        `;
      }
    }
  }

  // Render Discovery Questions
  function renderQuestionsWizard(questions) {
    if (!questionsListEl) return;
    questionsListEl.innerHTML = '';
    userAnswers = {};

    questions.forEach((q, idx) => {
      // Default to option A
      const defaultOpt = q.options[0];
      userAnswers[q.id] = defaultOpt ? `[${defaultOpt.key}] ${defaultOpt.label}` : "Rekomendasi";

      const block = document.createElement('div');
      block.className = 'question-block';
      block.innerHTML = `
        <div class="question-header-row">
          <span class="question-topic">${idx + 1}. ${q.header || 'Arsitektur'}</span>
          <span style="font-size: 11px; color: var(--text-dim); font-weight: 500;">Pilih A, B, atau C</span>
        </div>
        <div class="question-text">${q.question}</div>
        <div class="options-group" id="opts-${q.id}"></div>
      `;

      const optsContainer = block.querySelector(`#opts-${q.id}`);
      q.options.forEach((opt, optIdx) => {
        const isSelected = optIdx === 0;
        const optEl = document.createElement('div');
        optEl.className = 'option-item' + (isSelected ? ' selected' : '');
        optEl.innerHTML = `
          <div class="opt-key">${opt.key}</div>
          <div class="opt-details">
            <div class="opt-label">${opt.label}</div>
            <div class="opt-desc">${opt.desc}</div>
          </div>
          <div class="opt-check">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" style="width:16px;height:16px;">
              <polyline points="20 6 9 17 4 12"></polyline>
            </svg>
          </div>
        `;

        optEl.addEventListener('click', () => {
          optsContainer.querySelectorAll('.option-item').forEach(el => el.classList.remove('selected'));
          optEl.classList.add('selected');
          userAnswers[q.id] = `[${opt.key}] ${opt.label}`;
        });

        optsContainer.appendChild(optEl);
      });

      questionsListEl.appendChild(block);
    });
  }

  // ── 6. Step 2: Final Generate Blueprint with Answers ──
  async function triggerFinalGenerate() {
    if (!heroInput) return;
    const idea = heroInput.value.trim();
    if (!idea) return;

    if (btnWizardSubmit) {
      btnWizardSubmit.disabled = true;
      btnWizardSubmit.innerHTML = `
        <svg class="spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:16px;height:16px;animation:spin 1s linear infinite;">
          <circle cx="12" cy="12" r="10" stroke-opacity="0.25"></circle>
          <path d="M12 2a10 10 0 0 1 10 10"></path>
        </svg>
        <span>Meracik PRD & Arsitektur...</span>
      `;
    }

    const stack = document.getElementById('stack-select')?.value || "Modern Fullstack";
    const complexity = document.getElementById('complexity-select')?.value || "MVP";
    const chosenModel = document.getElementById('model-select')?.value || null;

    try {
      const res = await fetch('/api/cihuy/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          idea,
          target_stack: stack,
          complexity: isReasoningActive ? `${complexity} + Deep Architectural Blueprint` : complexity,
          answers: userAnswers,
          model: chosenModel
        })
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Gagal membuat blueprint");
      }

      const data = await res.json();
      currentBlueprint = data.blueprint;

      // Switch to Canvas View
      if (wizardContainer) wizardContainer.classList.add('hidden');
      if (canvasContainer) canvasContainer.classList.remove('hidden');

      if (canvasTitle) canvasTitle.textContent = currentBlueprint.title || "VALLEN CIHUY Blueprint";
      renderCanvasContent();

      const cliPreview = document.getElementById('cli-command-preview');
      if (cliPreview) {
        cliPreview.textContent = `vallencli run "Selesaikan proyek ${currentBlueprint.title} berdasarkan TASKS.md"`;
      }
    } catch (err) {
      alert("Error: " + err.message);
    } finally {
      if (btnWizardSubmit) {
        btnWizardSubmit.disabled = false;
        btnWizardSubmit.innerHTML = `<span>✨ Racik PRD & Blueprint Sekarang ➔</span>`;
      }
    }
  }

  // Quick accept all recommendations
  if (btnWizardQuick) {
    btnWizardQuick.addEventListener('click', () => {
      // Ensure all option A are selected
      loadedQuestions.forEach(q => {
        const firstOpt = q.options[0];
        if (firstOpt) userAnswers[q.id] = `[${firstOpt.key}] ${firstOpt.label}`;
      });
      triggerFinalGenerate();
    });
  }

  if (btnWizardSubmit) {
    btnWizardSubmit.addEventListener('click', triggerFinalGenerate);
  }

  if (btnWizardBack) {
    btnWizardBack.addEventListener('click', () => {
      if (wizardContainer) wizardContainer.classList.add('hidden');
      if (heroContainer) heroContainer.classList.remove('hidden');
      heroInput?.focus();
    });
  }

  if (btnSubmit) {
    btnSubmit.addEventListener('click', startDiscovery);
  }

  if (heroInput) {
    heroInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        startDiscovery();
      }
    });
  }

  // ── 7. Canvas Navigation & Tabs ──
  document.getElementById('btn-back-hero')?.addEventListener('click', () => {
    canvasContainer?.classList.add('hidden');
    heroContainer?.classList.remove('hidden');
  });

  document.getElementById('btn-dock-new')?.addEventListener('click', () => {
    canvasContainer?.classList.add('hidden');
    wizardContainer?.classList.add('hidden');
    heroContainer?.classList.remove('hidden');
    if (heroInput) {
      heroInput.value = '';
      autoResizeTextarea();
      heroInput.focus();
    }
  });

  document.getElementById('btn-dock-home')?.addEventListener('click', () => {
    canvasContainer?.classList.add('hidden');
    wizardContainer?.classList.add('hidden');
    heroContainer?.classList.remove('hidden');
  });

  document.querySelectorAll('.ctab').forEach(tab => {
    tab.addEventListener('click', () => {
      document.querySelectorAll('.ctab').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      activeCanvasTab = tab.dataset.tab;
      renderCanvasContent();
    });
  });

  function renderCanvasContent() {
    if (!currentBlueprint || !canvasEditor) return;
    if (activeCanvasTab === 'prd') {
      canvasEditor.textContent = currentBlueprint.prd_markdown || "Belum ada dokumen PRD.";
    } else if (activeCanvasTab === 'schema') {
      canvasEditor.textContent = currentBlueprint.schema_sql || "Belum ada skema SQL.";
    } else if (activeCanvasTab === 'api') {
      canvasEditor.textContent = currentBlueprint.api_spec_markdown || "Belum ada API Spec.";
    } else if (activeCanvasTab === 'tasks') {
      canvasEditor.textContent = currentBlueprint.tasks_markdown || "Belum ada Tasks Checklist.";
    }
  }

  // ── 8. Export & 1-Click Gaspol ──
  async function exportToDisk() {
    if (!currentBlueprint) return false;
    try {
      const res = await fetch('/api/cihuy/export', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: currentBlueprint.title,
          prd_markdown: currentBlueprint.prd_markdown,
          schema_sql: currentBlueprint.schema_sql,
          api_spec_markdown: currentBlueprint.api_spec_markdown,
          tasks_markdown: currentBlueprint.tasks_markdown
        })
      });
      const data = await res.json();
      return data.status === 'ok';
    } catch (err) {
      alert("Gagal export: " + err.message);
      return false;
    }
  }

  document.getElementById('btn-export-disk')?.addEventListener('click', async () => {
    const ok = await exportToDisk();
    if (ok) alert("✓ Berhasil menulis PRD.md, SCHEMA.sql, dan TASKS.md ke workspace!");
  });

  document.getElementById('btn-copy-tab')?.addEventListener('click', () => {
    if (!canvasEditor) return;
    navigator.clipboard.writeText(canvasEditor.textContent);
    alert("✓ Teks tab berhasil disalin!");
  });

  document.getElementById('btn-gaspol-action')?.addEventListener('click', async () => {
    const ok = await exportToDisk();
    if (!ok) return;

    const promptText = `Saya telah meracik blueprint aplikasi '${currentBlueprint.title}'. File PRD.md, SCHEMA.sql, dan TASKS.md sudah siap di workspace. Tolong pelajari dan mulai selesaikan Task 01 sekarang!`;
    localStorage.setItem('vallen_cihuy_pending_prompt', promptText);
    window.location.href = '/?autostart=cihuy';
  });
})();

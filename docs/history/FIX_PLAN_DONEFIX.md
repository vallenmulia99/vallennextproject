# FIX_PLAN.md — Perbaikan VALLEN CLI (vallennextproject)

Dokumen ini dibuat dari analisis kode (baca statis, belum dijalankan). Tugas kamu, agent: kerjakan SEMUA item di bawah sampai tuntas, berurutan dari P0 ke P2.

## Aturan kerja (wajib)

1. Jangan tanya "lanjut?" di antara item. Kerjakan sampai semua item selesai atau benar-benar terblokir.
2. Sebelum mulai: jalankan `pytest -q`, catat tes yang sudah gagal (baseline). Jangan anggap itu disebabkan kamu.
3. Tiap item: (a) reproduksi bug dulu dengan tes baru yang gagal, (b) perbaiki seminimal mungkin, (c) pastikan tes baru lolos dan `pytest -q` tidak nambah kegagalan, (d) commit terpisah `fix(<ID>): <ringkas>`.
4. Klaim di dokumen ini berasal dari membaca kode. Kalau ternyata bug tidak bisa direproduksi, tulis "tidak terbukti" di laporan dan lanjut. Jangan ngarang perbaikan.
5. Jangan ubah hal di luar item. Jangan tambah dependency baru. Jangan buat file `.md` lain kecuali laporan akhir `FIX_REPORT.md`.
6. Cari kode pakai nama simbol/string yang tertulis di item, bukan nomor baris (nomor bisa geser).
7. Akhir: tulis `FIX_REPORT.md` berisi tabel ID | status (fixed/tidak terbukti/terblokir) | file yang diubah | tes yang ditambah.

## F0 — Cek dulu: patch sebelumnya sudah masuk atau belum

Empat perubahan ini mungkin sudah diterapkan (dari `vallen-fix.patch`). Cek dengan grep. Kalau belum ada, terapkan sesuai deskripsi.

| Cek | Harus ada | Isi perubahan |
|---|---|---|
| `grep -n "args_error" vallen_cli/core/agent.py` | ada | JSON argumen tool rusak tidak lagi jadi `{}`; model dikasih error jelas (+ hint kalau `finish_reason == "length"`) |
| `grep -n "stream_finish_reason" vallen_cli/core/agent.py` | ada | finish_reason dilacak; tool call tanpa `index` dari proxy tidak nyampur |
| `grep -n "verify_timed_out" vallen_cli/core/agent.py` | ada | timeout verifikasi (exit_code 124) = inkonklusif, bukan gagal karena edit |
| `grep -n "split(\"/\")\[-1\]" vallen_cli/core/token.py` | ada | ID model ber-prefix router (`contoh cc/claude-sonnet-5-5`) dikenali (200k). Juga `max_tokens` default di `config.py` = 32768 |

---

## P0 — Penyebab utama agent kelihatan "bego"

### P0-1. Output tool yang gagal dibuang (paling parah)
- Lokasi: `core/agent.py` baris `output = result.output if result.success else f"Error: {result.error}"`, dan `tools/task_tool.py` baris `output = res.output if res.success else f"Error: {res.error}"`.
- Bukti: `ShellTool` mengembalikan `success=False, output=<stdout+stderr>, error="Command exited with code N"` kalau exit code bukan 0. Agent hanya mengirim `Error: Command exited with code N` ke model. Compiler error, traceback, dan output test hilang. Model buta, lalu menebak. System prompt menyuruh "baca compiler errors", padahal errornya tidak pernah sampai.
- Perbaikan: buat helper `format_tool_output(result) -> str` di `tools/base.py`: kalau success → `result.output`; kalau gagal → `f"Error: {result.error}"` + (`"\n" + result.output` bila output tidak kosong). Pakai di kedua tempat tadi dan di mana pun pola yang sama muncul (`grep -rn "if .*success else f\"Error"`).
- Tes: jalankan `ShellTool` dengan `echo boom; exit 3` lewat jalur agent/helper, pastikan string `boom` dan `code 3` ada di output yang dikirim ke model.

### P0-2. Argumen JSON rusak jadi `{}` di subagent
- Lokasi: `tools/task_tool.py`, fungsi `execute_subagent_tool` (`except json.JSONDecodeError: args = {}`).
- Perbaikan: samakan dengan F0 di `agent.py`: kembalikan string error ke model, jangan jalankan tool dengan `{}`. Tolak juga kalau hasil parse bukan dict.
- Tes: tool call dengan `arguments='{"filePath": "a.txt", "content": "abc'` menghasilkan pesan error, tool tidak dieksekusi.

### P0-3. Balasan teks terpotong `max_tokens` dianggap selesai
- Lokasi: `core/agent.py`, cabang `else:` setelah `if pending_tool_calls:` (`session.add_assistant_message(delta_buffer); break`).
- Bukti: `stream_finish_reason == "length"` tanpa tool call = jawaban terpotong di tengah kalimat, tapi turn dianggap selesai.
- Perbaikan: kalau `stream_finish_reason == "length"` dan tidak ada tool call, simpan pesan, lalu lanjutkan loop dengan pesan user sintetis: "Balasanmu terpotong batas token. Lanjutkan tepat dari titik berhenti." Maksimal 2 kali per turn supaya tidak looping. Tampilkan event info ke TUI.
- Tes: provider palsu yang mengembalikan `finish_reason="length"` sekali lalu `"stop"`; pastikan ada dua panggilan provider dan hasil akhir gabungan.

### P0-4. Cancel (Ctrl+H) tidak menghentikan agent
- Lokasi: `tui/app.py`, `action_cancel_generation` hanya `self._cancel_event.set()`; `on_event` cuma `return` kalau `cancel.is_set()`. `run_agent(...)` tidak menerima event itu.
- Bukti: setelah user menekan Halt, agent tetap streaming, tetap mengeksekusi tool (edit file, shell) di belakang layar, dan input baru tetap terkunci sampai `run_agent` selesai.
- Perbaikan: tambah parameter `cancel_event: asyncio.Event | None = None` ke `run_agent`. Cek di awal tiap ronde, di dalam loop stream, dan sebelum tiap eksekusi tool. Saat batal: beri hasil tool `"Cancelled by user"` untuk semua tool call yang masih menggantung (supaya riwayat sesi tetap valid), lalu keluar bersih. Di TUI, teruskan `self._cancel_event`. Sebagai pengaman kedua, bungkus panggilan `run_agent` di `asyncio.Task` dan `cancel()` task-nya. Proses shell yang berjalan harus ikut dimatikan (lihat P1-4).
- Tes: agent dengan provider palsu yang lambat; set event; pastikan tidak ada tool dieksekusi setelahnya dan fungsi kembali cepat.

### P0-5. Subagent membuang hasil tool call duplikat, riwayat pesan jadi invalid
- Lokasi: `tools/task_tool.py`, blok `unique_calls` / `seen_calls` lalu `asyncio.gather(...)`.
- Bukti: pesan assistant disimpan dengan SEMUA `tool_calls`, tapi pesan `tool` hanya dibuat untuk yang unik. Setiap `tool_call_id` wajib punya balasan; kalau ada yang hilang, request berikutnya ditolak API (HTTP 400) atau model bingung.
- Perbaikan: tetap eksekusi hanya yang unik (hemat), tapi tambahkan pesan `tool` untuk SETIAP `tool_call_id`, isi dengan hasil dari panggilan unik yang sama.
- Tes: dua tool call identik dengan id berbeda → dua pesan tool ada.

---

## P1 — Sering bikin salah, harus dibenahi

### P1-1. Edit/write merusak line ending dan encoding
- Lokasi: `tools/file_tools.py` (`EditTool`, `WriteTool`), `tools/patch_tools.py`. Pola: `p.read_text(errors="replace")` lalu `p.write_text(...)`.
- Bukti: `read_text` memakai universal newline, jadi CRLF berubah jadi LF saat dibaca; cabang CRLF di `smart_replace` tidak pernah aktif. Tulis balik mengubah SELURUH file jadi LF (diff raksasa). `errors="replace"` mengganti byte non-UTF-8 dengan U+FFFD dan menulisnya balik (korupsi data). Cabang hashline di `EditTool` dan beberapa `write_text` di `patch_tools` tanpa `encoding="utf-8"` (bermasalah di Windows).
- Perbaikan: buat helper `read_text_preserve(path) -> (text, newline)` dan `write_text_preserve(path, text, newline)` (baca bytes, decode utf-8 dengan `surrogateescape`, deteksi CRLF, tulis balik dengan encoding dan newline yang sama). Pakai di edit, write, dan patch. Kalau file bukan UTF-8 valid, jangan gunakan `replace`.
- Tes: file CRLF diedit satu baris, hasilnya masih CRLF semua dan diff hanya 1 baris. File dengan byte `\xff` tidak berubah di bagian lain.

### P1-2. `grep` bilang "No matches" padahal regex-nya error
- Lokasi: `GrepTool.execute` (jalur `rg`).
- Bukti: stdout `rg` kosong saat error (exit code 2, misalnya regex tidak valid), lalu kode menampilkan `No matches found`. Model menyimpulkan kode tidak ada. Selain itu `--max-count 100` berlaku per file, bukan total.
- Perbaikan: periksa `proc.returncode` (0 = ada, 1 = tidak ada, >=2 = error → kembalikan `success=False` dengan stderr). Batasi total baris output. Jangan telan exception diam-diam; kalau `rg` gagal jalan, fallback Python harus tetap menghormati `.gitignore` sederhana atau minimal daftar ignore yang sama.
- Tes: pattern `(` → error jelas, bukan "No matches".

### P1-3. Output `read` dipotong dan petunjuk lanjutannya hilang; ada pajak token
- Lokasi: `ReadTool.execute` (blok `<line_hashes>` dan `<response clipped>`), dan `core/agent.py` (`if len(output) > 25000`).
- Bukti: baca 2000 baris gampang lewat 25.000 karakter; agent memotong dari belakang, jadi catatan `offset=... limit=...` (ada di akhir) ikut terbuang, dan model mengira sudah baca semuanya. Selain itu `<line_hashes>` ditambahkan di SETIAP read (±8 karakter per baris), padahal skema `edit` mewajibkan `oldString` sehingga mode hashline hampir tak terpakai.
- Perbaikan: batasi output `read` per karakter di dalam tool (misal ~20.000) dan letakkan catatan lanjut yang benar. Hapus `<line_hashes>` dari output default (jadikan opsional lewat parameter, atau buang). Di `agent.py`, kalau memotong, pertahankan ekor yang berisi catatan lanjut atau tambahkan instruksi "gunakan offset/limit".
- Tes: file 5000 baris → output berisi `offset=` yang valid dan panjangnya di bawah batas.

### P1-4. `shell` tool: bisa nge-hang, false positive, proses yatim
- Lokasi: `tools/shell_tools.py` (`_run_command`, `_DANGEROUS_PATTERNS`).
- Bukti:
  - `create_subprocess_shell` tanpa `stdin=DEVNULL`: perintah interaktif (prompt `npm create`, `git` minta kredensial) mewarisi stdin TUI dan hang sampai timeout 120 detik.
  - Saat timeout hanya `proc.kill()` pada shell, anak proses (server dev, watcher) tetap hidup, dan tidak ada `await proc.communicate()` setelahnya. Output parsial hilang.
  - Regex `\bshutdown\b`, `\breboot\b`, `\bhalt\b` cocok di mana saja, termasuk `git commit -m "fix shutdown handler"` atau `grep -r shutdown src`, dan pesan errornya tidak menyebut pola mana.
- Perbaikan: `stdin=asyncio.subprocess.DEVNULL`; jalankan di process group baru (`start_new_session=True` di POSIX; `CREATE_NEW_PROCESS_GROUP` di Windows) dan matikan seluruh grup saat timeout atau cancel (terhubung ke P0-4); kembalikan output parsial + pesan timeout; ubah pola berbahaya agar hanya cocok di posisi perintah (awal string atau setelah `;`, `&&`, `||`, `|`) dan sebut pola yang cocok di pesan error.
- Tes: `git commit -m "fix shutdown"` (dry-run/echo) tidak diblokir; `sleep 300 & wait` dengan timeout 1 detik tidak meninggalkan proses; perintah yang membaca stdin selesai cepat, tidak hang.

### P1-5. Deskripsi tool dipotong 320 karakter di tengah kalimat
- Lokasi: `tools/base.py`, `to_openai_schema` → `compact(...)` memotong `description` > 320 karakter jadi `...`.
- Bukti: deskripsi `read`, `write`, `edit` panjang dan berisi aturan penting (wajib `read` dulu, jangan sertakan prefix nomor baris, keunikan `oldString`, `replaceAll`). Model hanya menerima potongan awal yang terputus.
- Perbaikan: tulis ulang deskripsi tool inti agar padat dan lengkap dalam ≤ ~600 karakter, lalu naikkan batas atau hapus pemotongan otomatis untuk tool inti. Jangan biarkan ada deskripsi yang berakhir `...`.
- Tes: untuk semua tool terdaftar, `schema["function"]["description"]` tidak berakhir `...` dan berisi aturan "read before edit" pada `edit`/`write`.

### P1-6. Verifikasi otomatis setelah tiap edit terlalu berat dan terlalu galak
- Lokasi: `core/agent.py` (`ensure_verification_baseline`, blok `[Automatic verification]`, `MAX_VERIFICATION_RETRIES`), `tools/verify_tool.py`.
- Bukti: setiap edit menjalankan seluruh `pytest -q` atau `npm test` (batas 30 detik) plus baseline di awal run. Untuk proyek besar ini timeout atau lambat terus. Diagnostik sintaks dari edit antara (edit file A dulu, B belakangan) dihitung sebagai kegagalan; setelah 2 kali, output diberi tambahan "Stop editing this file and report", yang bertentangan dengan prompt "NEVER stop early".
- Sudah ditangani di F0: timeout dianggap inkonklusif. Yang tersisa: (1) jangan jalankan test suite penuh per edit; jalankan cek ringan per file (sintaks) per edit, dan verifikasi penuh sekali di akhir run atau lewat tool `verify` eksplisit; (2) ganti pesan "Stop editing" jadi saran non-terminal ("perbaiki diagnostik ini sebelum edit lain"); (3) izinkan `verify.command` di config untuk menimpa perintah default.
- Tes: dua edit berturut-turut yang menghasilkan diagnostik tidak menambahkan kalimat "Stop editing"; verifikasi penuh tidak dipanggil per edit.

### P1-7. Pemangkasan konteks bikin model lupa isi file tanpa jalan pulang
- Lokasi: `core/compact.py` (`prune_tool_outputs`, `prune_tool_outputs_to_budget`, `KEEP_RECENT`, `COMPACT_SYSTEM_PROMPT`).
- Bukti: output tool lama dipotong jadi 2000 karakter (saat compact) atau 256 karakter (saat melewati budget) lalu ditambah penanda generik `[output pruned for context efficiency]`. Penanda tidak menyebut tool, path, rentang baris, atau argumen, jadi model tidak tahu apa yang hilang dan cara membacanya lagi. Hanya 2 output tool terakhir yang dilindungi. Ekor ringkasan lokal memakai `KEEP_RECENT = 4` pesan (bukan budget token). Template ringkasan bebas, tidak memaksa daftar file yang dibaca/diubah dan langkah berikutnya.
- Perbaikan: (1) saat memangkas, ganti isi dengan stub yang memuat nama tool, argumen kunci (path, offset, limit atau command), ukuran asli, dan kalimat "baca ulang dengan tool X bila perlu"; (2) lindungi ekor berdasarkan budget token, bukan jumlah pesan tetap; (3) ganti `COMPACT_SYSTEM_PROMPT` dengan template terstruktur: Goal, Progress, Decisions, Files (dibaca/diubah), Commands (build/test), Next Steps; (4) tambahkan prefix pada ringkasan yang menyatakan pekerjaan di dalamnya sudah dilakukan dan file mungkin sudah berubah.
- Tes: sesi dengan 30 hasil `read` besar, setelah pemangkasan setiap stub berisi path dan rentang; ringkasan mengandung bagian Files dan Next Steps.

---

## P2 — Kualitas dan keamanan

### P2-1. `ToolRegistry.execute` menjalankan tool dua kali saat ada `TypeError`
- Lokasi: `tools/base.py`, `except TypeError` yang memanggil `tool.execute(**valid_args)` lagi.
- Bukti: `TypeError` yang muncul DARI DALAM tool (bug sungguhan) ikut tertangkap, lalu tool dijalankan ulang (efek ganda: shell dua kali, tulis dua kali) dan bug aslinya tersembunyi.
- Perbaikan: filter argumen memakai `inspect.signature` SEBELUM memanggil; kecuali tool menerima `**kwargs`. Hapus retry berbasis `except TypeError`.

### P2-2. Pelacakan perubahan file tidak konsisten
- Lokasi: `EditTool` memanggil `tracker.record_edit` SEBELUM menulis file dan SEBELUM formatter; `agent._record_change` mencatat lagi untuk `edit`/`write`; `WriteTool` sendiri juga mencatat.
- Perbaikan: satu jalur pencatatan saja, dilakukan setelah tulis dan format (isi akhir di disk), seperti yang sudah dilakukan `WriteTool`. Hapus catatan ganda.

### P2-3. `smart_replace` bisa merusak indentasi atau salah potong
- Lokasi: `tools/file_tools.py`, `smart_replace`.
- Bukti: langkah 4 (cocok toleran whitespace) menyisipkan `new_str` apa adanya tanpa menyesuaikan indentasi blok yang cocok, jadi tab/spasi bisa tercampur. Langkah 2 membuang pola `^\s*\d+:\s?` dari SETIAP baris, sehingga baris kode sah seperti `1: "a",` ikut terpotong.
- Perbaikan: langkah 2 hanya aktif jika SEMUA baris non-kosong cocok pola prefix nomor baris. Langkah 4: hitung selisih indentasi baris pertama lalu terapkan ke `new_str`.
- Tes: dua kasus di atas.

### P2-4. Cache "sudah dibaca" global dan tanpa deteksi perubahan
- Lokasi: `_read_cache` di `tools/file_tools.py`; `clear_read_cache` hanya dipakai di tes.
- Bukti: cache tidak dibersihkan saat sesi baru/`/clear`, dan `write` tidak memeriksa apakah file berubah sejak dibaca (mis. oleh shell, formatter, `git checkout`).
- Perbaikan: simpan `(mtime_ns, size)` saat dibaca; `write`/`edit` menolak dengan pesan "file berubah sejak dibaca, baca ulang" bila berbeda; panggil `clear_read_cache()` saat sesi baru/clear.

### P2-5. `read` gambar tidak pernah sampai ke model
- Lokasi: `ReadTool` mengembalikan blok `image_url` di `data`, tapi `agent.py` hanya mengirim `result.output` (teks) ke `session.add_tool_result`.
- Perbaikan: kalau `result.data` adalah list blok konten, kirim itu sebagai isi pesan tool (atau hapus klaim dukungan gambar dari deskripsi). Cabang list di `compact.py` sudah siap menerimanya.

### P2-6. Aturan permission dan celah rantai perintah
- Lokasi: `core/permission.py`.
- Bukti: `git_diff` masuk `SENSITIVE_TOOLS` padahal read-only (selalu minta izin). Aturan seperti `"shell:git *" = "allow"` memakai `fnmatch`, jadi `git status; rm -rf ~/x` juga cocok.
- Perbaikan: pindahkan `git_diff` ke `SAFE_TOOLS`. Untuk `shell`, tolak pencocokan "allow" bila perintah mengandung `;`, `&&`, `||`, `|`, `` ` ``, `$(`, atau newline (jatuh ke `ASK`).

### P2-7. Cek sintaks pakai `python3` keras dan meninggalkan `__pycache__`
- Lokasi: `core/format.py`, `check_file_syntax`.
- Perbaikan: pakai `ast.parse`/`compile` di dalam proses (atau `sys.executable`), bukan `python3 -m py_compile`; hindari file `.pyc` di proyek user dan hindari gagal diam-diam di Windows.

---

## Hipotesis belum terbukti (jangan diubah tanpa bukti)

- `Message.to_api_dict` menambahkan field `name` pada pesan role `tool`. Beberapa backend OpenAI-compatible yang ketat menolaknya. Hanya ubah kalau ada error HTTP 400 yang terbukti dari 9router.
- System prompt (`DEFAULT_OPENCODE_PROMPT`) sangat agresif ("NEVER stop", "NEVER skip") dan daftar skill panjang ikut masuk prompt tiap turn. Bisa bikin model boros ronde. Ukur dulu (jumlah ronde/token per tugas) sebelum mengubah.
- Estimasi token 4 karakter/token dan ambang compact 85% terlalu kasar untuk kode. Pertimbangkan `context_window` per model di `config`/`models.json`.

## Definisi selesai

- Semua item P0 dan P1 berstatus fixed atau "tidak terbukti" dengan alasan.
- `pytest -q` tidak punya kegagalan baru dibanding baseline.
- Setiap fix punya minimal satu tes baru.
- `FIX_REPORT.md` ada di root proyek.

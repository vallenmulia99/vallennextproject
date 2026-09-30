# TASK: Tampilan tool yang rapi + alur kerja agent yang lebih teliti di `vallen_cli/`

Kamu adalah coding agent. Kerjakan perubahan di repo `vallennextproject` (paket `vallen_cli/`).
Tugas ini dipecah jadi **4 tahap berurutan**. **Kerjakan SATU tahap, jalankan tes, laporkan, lalu BERHENTI** dan tunggu instruksi untuk tahap berikutnya. Jangan loncat tahap.

## Tujuan (dari sisi pengguna)

Saat agent bekerja, TUI harus menampilkan alur yang bersih dan berurutan:

```
🗂️  cari file   src/**/*.js                        ✓ 12 item
🔎  grep        'parseInt' di app.js               ✓ 4 cocok di 2 file
📖  read        app.js (baris 220-234)             ✓ 15 baris dibaca
✍️  menyiapkan patch ...
📝  vallen_ide/web/js/app.js (diubah, +3 -1)
    @@ -225,7 +225,9 @@
    -  const x = parseInt(a);
    +  const x = parseInt(a, 10);
```

Aturan tampilan:

1. Tool **baca/cari** (`read`, `grep`, `glob`, dll.) **TIDAK boleh menampilkan isi kode/hasil mentah** di layar. Cukup satu baris: emoji + nama tool + target + ringkasan singkat.
2. Tool **pengubah file** (`edit`, `write`, `apply_patch`) menampilkan **diff**: path relatif lengkap dengan folder, jumlah `+` dan `-`, dan baris yang berubah (`-` merah, `+` hijau).
3. Agent harus **lebih teliti sebelum patch**: baca bagian yang relevan dulu, dan tidak boleh patch file yang belum dibaca.

## Aturan kerja (berlaku untuk semua tahap)

- Ubah **seminimal mungkin**. **Jangan refactor** kode yang tidak terkait. Jangan hapus fitur.
- Jalankan `pytest tests/` **sebelum** dan **sesudah** tiap tahap. Laporkan tes yang sudah gagal sejak awal (pre-existing) dan jangan salah menganggapnya regresi.
- **Catatan jujur:** analisis di dokumen ini dibuat lewat pembacaan kode. `pytest` belum pernah dijalankan untuk temuan ini. Nomor baris di bawah hanya perkiraan. **Verifikasi ulang tiap klaim sebelum mengubah kode.** Kalau ada yang tidak terbukti, lewati dan tulis alasannya.
- Setiap tahap **wajib** punya tes baru (lihat bagian Tes di tiap tahap).
- **Output yang dilihat model** (isi `ToolResult.output` yang masuk ke sesi/LLM) **tidak boleh berubah** kecuali tahap itu secara eksplisit menyebutnya. Diff untuk layar dikirim lewat **data event UI**, bukan lewat output ke model (supaya token tidak membengkak).
- Gaya kode dan bahasa komentar: ikuti file yang sedang diedit.
- Di akhir tiap tahap, tulis ringkasan: file yang diubah, perilaku yang berubah, tes baru, hasil `pytest`.

## Konteks kode saat ini (hasil analisis, verifikasi ulang)

- **Kartu tool:** `vallen_cli/tui/widgets/message.py` → `ToolCallCard`. `_render_card()` menampilkan `output[:1200]` mentah untuk semua tool. Hanya `edit`/`edit_file`/`apply_patch` (atau output berisi `@@` + `+`/`-`) yang dirender sebagai `Syntax(..., "diff")`.
- **Event ke TUI:** `vallen_cli/tui/app.py` → `on_event` (sekitar baris 1171 `tool_start`, 1186 `tool_result`). Kartu dibuat saat `tool_start`, diperbarui saat `tool_result`.
- **Event dari agent:** `vallen_cli/core/agent.py`. Jenis event yang ada: `token`, `reasoning`, `tool_start`, `tool_result`, `stream_reset`, `provider_retry`, `compact`, `token_usage`, `verification_retry`, `round_limit`, `info`, `error`, `done`. **Tidak ada event "sedang menyiapkan tool".**
- **Stream tool call:** di `agent.py` (sekitar baris 268-290) potongan `chunk.tool_calls` ditimbun ke `attempt_pending_tool_calls`. `tool_start` baru dikirim **setelah seluruh stream selesai** (sekitar baris 422, di dalam loop `pending_tool_calls`).
- **Deskripsi tool:** `_describe_tool_call()` (sekitar baris 625) hanya punya kasus khusus untuk `write`/`edit`/`shell`/`apply_patch`/`git_diff`. Tool lain jatuh ke fallback `nama(k=v, k=v)`, itulah kenapa kartu `read` menampilkan `read(limit=190, filePath='app.js')`.
- **Hasil tool pengubah file:**
  - `apply_patch` (`vallen_cli/tools/patch_tools.py`) hanya mengembalikan `M app.js` (pakai `p.name`, tanpa folder dan tanpa isi perubahan).
  - `write` (`file_tools.py`) hanya `✓ Updated X (N bytes)`.
  - `edit` (`file_tools.py` sekitar baris 755-765) menyertakan diff tapi dipotong `diff_lines[:12]` dan hanya nama file.
- **Snapshot:** `_snapshot_before()` di `agent.py` hanya menangani `write`/`write_file`/`edit`/`edit_file`. `apply_patch` **tidak** di-snapshot; padahal daftar path patch sudah di-parse (`patch_paths`) di bagian permission check.
- **Read-before-edit:** `write` dan `edit` sudah wajib `read` dulu (`mark_file_read` di `file_tools.py`, pesan "You must Read ... before ..."). `apply_patch` **tidak punya guard ini**.
- **Prompt:** `vallen_cli/core/system_prompt.py`, bagian "## 1. Explore & Analyze Before Acting" sudah menyuruh `glob` → `grep` → `read`, tapi hanya sebagai saran.

---

## TAHAP 1 — Tampilan ringkas untuk baca/cari + diff untuk patch

**File utama:** `vallen_cli/tui/widgets/message.py`, `vallen_cli/tui/app.py`, `vallen_cli/core/agent.py`.

### 1.1 Tool baca/cari → satu baris emoji

- Buat pemetaan tool → emoji, misalnya: `read`/`read_file` 📖, `grep`/`search_files` 🔎, `glob`/`list_files` 🗂️, `webfetch`/`websearch` 🌐, `lsp` 🧭, `skill` 🧠, `git_status`/`git_diff`/`git_log` 🌿.
- Kartu untuk tool ini, setelah selesai, **tidak memuat isi output**. Format satu baris: `emoji nama target ✓ ringkasan`.
- Ringkasan dihitung dari output (tanpa menampilkannya): `read` → jumlah baris; `grep` → jumlah cocok dan jumlah file; `glob` → jumlah item; "tidak ada hasil" kalau kosong.
- Status `error` dan `rejected` tetap menampilkan **satu baris alasan** (maksimal ±100 karakter). Jangan sembunyikan error.
- Perbaiki `_describe_tool_call()` supaya `read` menampilkan `path (baris a-b)` dari argumen `offset`/`limit`, `grep` menampilkan `'pattern' di path/include`, `glob` menampilkan pattern. Tidak ada lagi tampilan `read(limit=190, filePath=...)`.

### 1.2 Tool pengubah file → diff dengan folder

- Tampilkan diff untuk `edit`, `write`, `apply_patch`: header per file `📝 path/relatif (diubah|file baru|dihapus, +A -B)`, lalu baris diff (`-` merah, `+` hijau) lewat `Syntax(..., "diff")`.
- **Path relatif terhadap root workspace/project** (folder harus kelihatan, mis. `vallen_ide/web/js/app.js`, bukan `app.js`). Kalau di luar root, tampilkan path apa adanya.
- Batas tampilan: total maksimal ±120 baris diff per panggilan; kalau lebih, tambahkan baris `... (diff dipotong)`. Header per file tetap ditampilkan semua.
- `apply_patch` yang menyentuh banyak file → satu header per file.

### 1.3 Cara data diff sampai ke UI (penting)

- Di `agent.py`: sebelum eksekusi tool pengubah file, **snapshot isi semua file yang akan disentuh** (untuk `apply_patch` pakai `patch_paths`; untuk `write`/`edit` pakai `filePath`). Bungkus dengan try/except (`PermissionError`/`OSError`): kalau path di luar workspace, lewati tanpa crash; tool sendiri yang akan menolak.
- Setelah eksekusi, bangun unified diff (`difflib`) antara snapshot dan isi file sekarang. Kirim sebagai field baru di event `tool_result`, mis. `data["diff"]`.
- **Jangan** memasukkan diff ini ke `output` yang dikirim ke model.
- `app.py` meneruskan `diff` ke `ToolCallCard.update_result(...)`.
- **Kompatibilitas:** tes yang sudah ada (`tests/test_cli_fixes.py::test_tool_call_card_diff_render`) membuat `ToolCallCard(tool_name="edit", output=<teks diff>)` tanpa field `diff` dan mengharapkan lexer `diff`. Perilaku itu harus tetap jalan (kalau `diff` kosong, pakai logika lama untuk output yang berisi diff).
- Jika patch gagal/sebagian gagal dan tidak ada perubahan file, tampilkan pesan hasil tool (error) seperti biasa, bukan diff kosong.

### Tes (tahap 1)

- Kartu `read` selesai **tidak** mengandung isi kode dari output, hanya satu baris ringkasan.
- Kartu `grep`/`glob` idem; status `error` tetap menampilkan alasan.
- `_describe_tool_call("read", {...offset, limit...})` menghasilkan rentang baris yang benar.
- Builder diff: file diubah, file baru, file dihapus, banyak file, path di luar workspace (tidak crash), batas 120 baris.
- Event `tool_result` membawa `diff`, sedangkan pesan tool yang masuk ke sesi **tidak** berisi diff itu.
- Tes lama `test_tool_call_card_diff_render` tetap lulus.

### Selesai tahap 1 jika

Saat agent `read`/`grep`/`glob`, layar hanya menampilkan satu baris per panggilan; saat `edit`/`write`/`apply_patch`, layar menampilkan diff dengan path relatif dan jumlah `+`/`-`; semua tes hijau.

---

## TAHAP 2 — Tahap "preparing" (urutan kerja terlihat)

**File utama:** `vallen_cli/core/agent.py` (loop stream), `vallen_cli/tui/app.py`, `vallen_cli/tui/widgets/message.py`, cek juga `vallen_cli/providers/openai_compatible.py` dan `ollama.py`.

### Masalah

Sekarang tidak ada momen "menyiapkan tool": `tool_start` baru muncul setelah seluruh stream selesai. Saat model menyusun patch besar, layar terasa diam.

### Yang dibuat

- Event baru dari `agent.py`, mis. `tool_prepare` dengan data `{"index": i, "name": nama_tool}`. Kirim **sekali per tool call** begitu nama tool pertama kali muncul di potongan stream (saat `entry["function"]["name"]` pertama kali terisi), **bukan** tiap potongan argumen.
- Opsional (ringan): perbarui progres argumen (jumlah karakter argumen yang sudah masuk) dengan throttle, hanya untuk tool pengubah file. Jangan membanjiri UI.
- Label urutan di UI:
  - `glob`/`list_files` → `🗂️ menyiapkan pencarian file`
  - `grep` → `🔎 menyiapkan grep`
  - `read` → `📖 menyiapkan read`
  - `edit`/`write`/`apply_patch` → `✍️ menyiapkan patch`
- `app.py`: saat `tool_prepare`, finalisasi `StreamingMessage` (sama seperti di `tool_start`) lalu pasang kartu berstatus "preparing". Saat `tool_start` datang, **pakai ulang kartu yang sama** (jangan buat duplikat). Pencocokan untuk banyak tool call paralel: berdasarkan urutan/indeks.
- **Kartu yatim:** kalau terjadi `stream_reset` (retry provider), cancel, atau stream gagal, semua kartu "preparing" yang belum punya `tool_start` harus dihapus.
- **Fallback provider:** sebagian provider mengirim seluruh tool call sekaligus di akhir. Dalam kasus itu `tool_prepare` dan `tool_start` datang hampir bersamaan. UI harus tetap rapi (tidak berkedip, tidak ganda). Periksa bagaimana `openai_compatible.py` dan `ollama.py` meneruskan `delta.tool_calls`, dan catat provider mana yang mengirim nama lebih awal.

### Tes (tahap 2)

- Dengan provider palsu yang mengirim potongan bertahap: urutan event = `tool_prepare` → `tool_start` → `tool_result`, satu `tool_prepare` per tool call.
- Dengan provider palsu yang mengirim sekaligus: tetap tidak ada kartu ganda.
- Setelah `stream_reset`/cancel: tidak ada kartu "preparing" yang tertinggal.
- Dua tool call paralel: dua kartu, masing-masing dipasangkan dengan benar.

### Selesai tahap 2 jika

Urutan cari file → grep → read → menyiapkan patch → patch terlihat berurutan di layar tanpa kartu ganda atau tertinggal; semua tes hijau.

---

## TAHAP 3 — Guard dan kepintaran agent

**File utama:** `vallen_cli/tools/patch_tools.py`, `vallen_cli/tools/file_tools.py` (mekanisme `mark_file_read`), `vallen_cli/core/agent.py`, `vallen_cli/core/system_prompt.py`.

Prinsip: **guard di kode lebih kuat daripada aturan di prompt** (model kecil/gratis sering mengabaikan prompt). Jangan memaksa urutan cari → grep → read secara kaku untuk perubahan sepele. Yang dikunci hanya: **tidak boleh patch file yang belum dibaca**.

### 3.1 `apply_patch` wajib sudah `read`

- Untuk hunk `update` dan `delete`: file harus sudah dibaca di sesi ini, dengan mekanisme yang sama seperti `edit`/`write`. Kalau belum, tolak dengan pesan jelas yang menyuruh `read` file itu dulu.
- Hunk `add` (file baru) dikecualikan.
- Penolakan harus **per hunk**, tidak menggagalkan hunk lain yang valid, dan tetap menghasilkan tepat satu tool result.
- Tes lama di `tests/test_patch_tools.py` kemungkinan memanggil `apply_patch` tanpa `read` dulu. Sesuaikan tes itu (panggil `mark_file_read` atau `read` lebih dulu) dan jelaskan di ringkasan. Jangan melonggarkan guard demi tes.

### 3.2 Pesan error patch yang mengarahkan

- Saat chunk gagal cocok (sekarang hanya: "context lines didn't match. Use read_file..."), sertakan: nama file (path relatif), nomor chunk, baris konteks pertama yang tidak ketemu, dan **nomor baris terdekat** di file (mis. lewat `difflib.get_close_matches`), lalu arahkan: "`read` file ini dengan offset di sekitar baris N sebelum mencoba lagi."
- Tujuannya agar model kecil tidak menebak-nebak berulang.

### 3.3 Peringatan baca berulang

- Di loop agent, hitung pembacaan identik (`path`, `offset`, `limit`) tanpa ada perubahan file di antaranya. Pada pembacaan ke-3 dst., **tambahkan petunjuk** ke output ("isi ini sudah kamu baca; gunakan hasil sebelumnya atau `grep`"). **Jangan memblokir** eksekusi. Reset hitungan jika file itu diubah.

### 3.4 Prompt (singkat)

- Di `system_prompt.py` bagian "## 1. Explore & Analyze Before Acting", tambahkan aturan ringkas: sebelum patch, `read` jendela yang cukup di sekitar bagian yang akan diubah; saat mengubah simbol, `grep` pemakaiannya; untuk perubahan sepele boleh langsung. Jaga tetap pendek (model kecil).

### Tes (tahap 3)

- `apply_patch` update tanpa `read` → ditolak dengan pesan yang benar; setelah `read` → berhasil. Hunk `add` tetap jalan tanpa `read`.
- Patch dengan banyak file: satu ditolak, satu valid → yang valid tetap diproses, hasil tetap satu tool result.
- Chunk tidak cocok → pesan berisi path, nomor chunk, dan saran nomor baris.
- Pembacaan identik ke-3 → ada petunjuk; setelah file diubah → hitungan reset; tidak ada pemblokiran.

### Selesai tahap 3 jika

Agent tidak bisa mem-patch file yang belum dibaca, error patch memberi arahan konkret, baca berulang diberi petunjuk, dan semua tes hijau.

---

## TAHAP 4 (opsional, kerjakan setelah tahap 1-3 hijau)

1. **Diff tampil di modal izin (sebelum patch jalan).** `PermRequest` (`vallen_cli/core/permission.py`) hanya punya `tool_name`, `description`, `path`. Tambahkan field opsional `preview: str = ""` (default menjaga kompatibilitas). Isi di `agent.py` sebelum `perm.guard(...)` (untuk `edit`: dari `oldString`/`newString`; untuk `apply_patch`: dari `patchText`; untuk `write`: ringkasan/diff terhadap file yang ada). Tampilkan di `vallen_cli/tui/widgets/permission_modal.py` dengan batas ukuran dan bisa di-scroll. Pengguna bisa menolak sebelum file berubah.
2. **Undo per patch.** **Catatan:** `/revert` dan `_do_revert_file` **sudah ada**, tetapi `FileTracker.record_write` mempertahankan `before` **pertama** per path, jadi `revert` mengembalikan file ke kondisi **sebelum sesi/agent pertama kali menyentuhnya**, bukan sebelum patch terakhir. Untuk undo per patch, tambahkan riwayat (stack) `before` per path di `FileTracker` dan perintah baru, mis. `/undo`, yang membatalkan **hanya patch terakhir**. Jangan ubah perilaku `/revert` yang sudah ada.
3. **Lipat langkah baca beruntun.** Beberapa kartu baca/cari berturutan dalam satu ronde digabung jadi satu ringkasan (mis. `📖 6 file · 🔎 2 grep`), detail tetap bisa dibuka.
4. **Diff panjang bisa dilipat per file** (ringkasan `path +A -B`, isi baris bisa dibuka).
5. **Satu baris hasil verifikasi setelah patch** (mis. `✓ syntax · ✓ format · ✓ tes`), hanya dari data yang sudah ada (`diagnostics`, blok `[Automatic verification]`). Jangan menjalankan verifikasi tambahan.

Tes: tiap butir punya tes sendiri; `/revert` lama tetap lulus.

---

## DI LUAR TUGAS INI (jalur terpisah, jangan dikerjakan sekarang)

Ini temuan lain yang sengaja **tidak** digabung supaya tugas ini tetap fokus. Minta dokumen tugas sendiri:

- **Keamanan backend `vallen_ide`:** CORS `allow_origins=["*"]` dengan credentials, WebSocket `/ws/terminal` yang men-spawn shell PTY tanpa cek Origin/auth, endpoint `/api/workspace/*` tanpa auth, `__main__` bind `0.0.0.0` dengan `reload=True`, dan `Access-Control-Allow-Origin: *` di `agent_bridge.py`.
- **Kebersihan repo:** `.vallen_launcher.sh` dan `.vallennext_launcher.sh` berisi path hardcoded ke mesin tertentu (hasil generate `install.sh`, sebaiknya masuk `.gitignore`); hack `not str(p).startswith("/tmp/pytest")` di `vallen_ide/backend/workspace_api.py` (kode tes di produksi); `package-data` di `pyproject.toml` belum mencakup file web `vallen_ide/web` dan `vallen_cihuy/web` untuk instalasi non-editable.

---

## Definition of Done (per tahap)

- [ ] Tes baru tahap itu ada dan lulus.
- [ ] `pytest tests/` tidak punya regresi dibanding kondisi awal (kegagalan pre-existing dilaporkan terpisah).
- [ ] Output yang dilihat model tidak berubah (kecuali yang disebut eksplisit di tahap itu).
- [ ] Tidak ada refactor di luar cakupan tahap.
- [ ] Ringkasan akhir ditulis: file yang diubah, perilaku yang berubah, tes baru, hasil `pytest`, dan hal yang sengaja dilewati beserta alasannya.
- [ ] **Berhenti** setelah tahap selesai dan tunggu instruksi tahap berikutnya.

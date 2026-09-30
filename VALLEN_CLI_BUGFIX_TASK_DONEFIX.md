# TASK: Perbaiki bug & hardening di `vallen_cli/`

Kamu adalah coding agent. Perbaiki bug di bawah ini pada repo `vallennextproject` (paket `vallen_cli/`).
Kerjakan **berurutan berdasarkan prioritas (P0 → P2)**. Setiap bug punya: lokasi, gejala, bukti, dan arahan fix.

## Aturan kerja

- Ubah seminimal mungkin. **Jangan refactor** kode yang tidak terkait.
- Setiap fix P0 dan P1 **wajib** disertai tes regresi baru di `tests/test_security_regressions.py` (P0) atau file tes yang relevan (P1).
- Jalankan `pytest tests/` sebelum dan sesudah perubahan. Laporkan tes yang gagal sejak awal (pre-existing) dan jangan salah menganggapnya sebagai regresi.
- Jangan menghapus fitur. Kalau perilaku perlu berubah, jelaskan di ringkasan akhir.
- Semua temuan di bawah sudah direproduksi lewat pembacaan kode dan skrip uji kecil, **tetapi `pytest` belum pernah dijalankan**. Verifikasi ulang tiap bug sebelum memperbaiki. Kalau ada yang tidak terbukti, lewati dan tulis alasannya.
- Bahasa komentar kode: ikuti gaya yang sudah ada di file tersebut.

---

## P0 — Kritis (keamanan / korupsi sesi)

### P0-1. `tool_call` melewati seluruh sistem permission

- **File:** `vallen_cli/core/permission.py` (`SAFE_TOOLS`), `vallen_cli/tools/deferred_tools.py` (`ToolCallTool.execute`), `vallen_cli/core/agent.py`
- **Gejala:** `tool_call` ada di `SAFE_TOOLS`, jadi selalu di-ALLOW. Padahal `ToolCallTool.execute` memanggil `reg.execute(name, **args)` untuk tool apa pun, termasuk `shell`, `write`, `edit`, `apply_patch`. Plan mode, deny rule, dan doom-loop check ikut terlewati.
- **Bukti:** `PermissionManager().check(PermRequest("shell", ...))` → `REJECT`, tetapi `check(PermRequest("tool_call", ...))` → `ONCE`, lalu `reg.execute("tool_call", name="shell", arguments={"command": "touch /tmp/x"})` benar-benar membuat file.
- **Fix:**
  1. Hapus `tool_call` dari `SAFE_TOOLS`.
  2. Di `agent.py`, sebelum permission check, **unwrap** `tool_call`: ganti `tool_name` dan `args` dengan target sebenarnya (`args["name"]`, `args["arguments"]`), lalu jalankan seluruh pipeline yang sama (plan-mode check, permission, snapshot, verifikasi).
  3. Di `ToolCallTool.execute`, tolak target `tool_call` (cegah rekursi), dan tolak target yang tidak ada di profil tool sesi aktif.
  4. Sebagai pertahanan berlapis, buat `ToolRegistry.execute` (atau wrapper) menolak tool di luar profil aktif. Saat ini profil hanya menyaring schema, bukan eksekusi.
- **Tes:** tool_call→shell tanpa callback harus ditolak. Di plan mode, tool_call→write harus ditolak. tool_call→tool_call harus error.

### P0-2. Server `/chat` tanpa autentikasi + CORS `*`

- **File:** `vallen_cli/core/server.py`
- **Gejala:**
  - Tidak ada auth.
  - `Access-Control-Allow-Origin: *` di semua respons.
  - `POST /chat` menerima `project` dari body dan memanggil `ws.set_active_project(project)`.
  - Halaman web mana pun bisa mengirim `fetch("http://127.0.0.1:4096/chat", {method:"POST", mode:"no-cors", body: JSON})`. Content-Type `text/plain` tidak memicu preflight, dan server tidak mengecek Content-Type. Digabung dengan P0-1, ini eksekusi kode lewat browser korban.
  - `int(headers["content-length"])` tanpa batas atas dan tanpa penanganan error (DoS memori / crash).
- **Fix:**
  1. Wajib token: generate token acak saat `serve` start (atau dari config), cetak sekali, dan wajibkan header `Authorization: Bearer <token>` di **semua** endpoint kecuali (opsional) `/health`. Bandingkan dengan `hmac.compare_digest`.
  2. Hapus `Access-Control-Allow-Origin: *`. Kalau CORS dibutuhkan, pakai allowlist origin dari config.
  3. Validasi header `Host` (hanya loopback / host yang dikonfigurasi) untuk mencegah DNS rebinding. Tolak request yang punya `Origin` bukan allowlist.
  4. Wajibkan `Content-Type: application/json` untuk `POST /chat` (415 kalau bukan).
  5. Batasi `Content-Length` (mis. 1 MB), tangani `ValueError` (400), dan beri timeout baca.
  6. Kalau `--host` bukan loopback dan tidak ada token: tolak start atau cetak peringatan keras.
  7. Validasi `project` (harus direktori yang ada, resolve realpath). Pertimbangkan allowlist root.
  8. Batalkan task agent (`task.cancel()`) kalau klien putus (`ConnectionResetError` saat `writer.drain()`). Simpan referensi task supaya tidak di-GC.
  9. Ganti versi hardcoded `"0.1.0"` dengan `vallen_cli.__version__`.
- **Tes:** tanpa token → 401. Origin asing → 403. Content-Type salah → 415. Content-Length raksasa → 413.

### P0-3. `run_agent` crash & sesi korup saat tool menulis di luar workspace

- **File:** `vallen_cli/core/agent.py` (`_snapshot_before`, `_record_change`, dan pemanggilnya)
- **Gejala:** `_snapshot_before` memanggil `resolve_workspace_path(path)` **di luar try/except**. Kalau model mengirim `filePath="/etc/hosts"`, `PermissionError` naik keluar dari `run_agent`. Tool call itu tidak pernah mendapat `tool` result, sehingga request berikutnya ke provider bisa gagal (400: tool_call tanpa response).
- **Bukti:** `with workspace_scope(tmp): await agent._snapshot_before("write", {"filePath": "/etc/hosts"})` → `PermissionError`.
- **Fix:**
  1. Bungkus `_snapshot_before` dan `_record_change` dengan try/except (`PermissionError`/`OSError`) → kembalikan `None`/no-op.
  2. Pastikan eksekusi tool tetap jalan sehingga tool itu sendiri yang mengembalikan error yang rapi ("outside workspace root") ke model.
  3. **Invariant:** setiap `tool_call_id` di pesan assistant **harus** berakhir dengan tepat satu tool result, apa pun yang terjadi. Bungkus seluruh pemrosesan satu tool call dalam `try/finally` yang menjamin ini, termasuk pada `asyncio.CancelledError` (sekarang `raise` meninggalkan sisa tool call tanpa jawaban).
- **Tes:** agent loop dengan provider palsu yang memanggil `write` ke `/etc/hosts` → tidak raise, tool result berisi error, dan `get_api_messages()` valid (tiap tool_call punya tepat satu result).

---

## P1 — Bug sedang

### P1-1. Blocklist regex shell rusak (alternatif kosong)

- **File:** `vallen_cli/tools/shell_tools.py` (`_CMD_START`, `_DANGEROUS_PATTERNS`)
- **Gejala:** Grup `(?:^|[;]|&&|\|\|||\||`)` mengandung alternatif kosong (`||` di tengah), jadi anchor tidak pernah bekerja.
  - **False positive** (diblokir padahal aman): `grep -r halt src/`, `cat shutdown.log`, `npm run halt-dev`, `git log --grep=mkfs`.
  - **False negative** (lolos): `rm -rf /*`, `rm -rf ~`, `rm -rf $HOME`, `rm -r -f /`, `rm --recursive --force /`, `rm -rf --no-preserve-root /`.
- **Fix (disarankan):** ganti regex dengan tokenizer.
  1. Pecah command menjadi segmen di `;`, `&&`, `||`, `|`, newline, backtick, `$(`. Gunakan `shlex.split` per segmen dengan fallback aman kalau gagal parse.
  2. Buang prefix wrapper (`sudo`, `env`, `command`, `nohup`, `time`, `exec`, `xargs`) untuk menemukan `argv[0]` sebenarnya.
  3. Cek `argv[0]` terhadap set `{mkfs*, fdisk, shutdown, reboot, halt, poweroff}`.
  4. Untuk `rm`: rekursif = ada flag yang mengandung `r`/`R` atau `--recursive`. Blokir jika target termasuk `/`, `/*`, `~`, `~/*`, `$HOME`, `${HOME}`, `/home`, `/etc`, `/usr`, `/bin`, `/sbin`, `/boot`, `/var`, atau ada `--no-preserve-root`.
  5. Pertahankan deteksi fork bomb `:(){` dan `dd` ke `/dev/*`.
  6. Blokir juga redirect ke perangkat blok (`> /dev/sd*`, `/dev/nvme*`).
- Catatan: blocklist ini hanya lapisan tambahan. Permission manager tetap pertahanan utama. Jangan mengklaimnya sebagai sandbox.
- **Tes:** tabel parametrik untuk semua contoh di atas (aman → lolos, berbahaya → diblokir).

### P1-2. Cancel di antara ronde menggandakan tool result

- **File:** `vallen_cli/core/agent.py` (awal `while tool_round <= effective_max_rounds`)
- **Gejala:** Blok cancel di awal loop menjawab `pending_tool_calls`, tetapi variabel itu masih berisi ronde **sebelumnya** yang sudah dijawab semua (baru direset setelah blok cancel). Hasilnya tool result duplikat untuk `tool_call_id` yang sama.
- **Fix:** hapus loop jawab-pending di awal iterasi (cukup `break`). Jawaban untuk sisa tool call sudah dijamin oleh invariant di P0-3. Kalau tetap dipertahankan, lacak set `answered_ids` dan lewati yang sudah dijawab.

### P1-3. Cancel saat streaming: error palsu atau pesan tersimpan dua kali

- **File:** `vallen_cli/core/agent.py` (loop `async for chunk in provider.stream_completion`)
- **Gejala:** Saat cancel, kode hanya `break` dari `async for` (dan sudah memanggil `session.add_assistant_message(delta_buffer)`), lalu:
  - Kalau belum ada konten → `raise RuntimeError("Provider returned an empty response")` (error palsu ke pengguna).
  - Kalau ada konten → ia tersimpan lagi di cabang `else: session.add_assistant_message(delta_buffer)` (duplikat).
  - `pending_tool_calls` parsial (JSON terpotong) bisa ikut diproses.
- **Fix:** pakai flag `cancelled = True`. Setelah stream keluar: kalau `cancelled`, simpan `delta_buffer` **sekali** (kalau tidak kosong), buang `pending_tool_calls` parsial, lalu `break` dari loop luar tanpa raise.

### P1-4. Retry provider menggandakan teks

- **File:** `vallen_cli/core/agent.py`
- **Gejala:** `full_response += chunk.content`, `output_tokens_total`, dan event `token`/`reasoning` sudah terkirim sebelum percobaan gagal, tetapi tidak dibatalkan saat retry. Jawaban parsial muncul dua kali di UI dan di `full_response`.
- **Fix:** akumulasi per-percobaan (`attempt_response`) dan gabungkan ke `full_response` hanya saat stream sukses. Kirim event baru `stream_reset` saat retry dan tangani di TUI (`tui/app.py`), server, dan headless supaya teks parsial dibuang.

### P1-5. Argumen CLI: `serve -h`, `--no-tools`, `--continue`, `--port`

- **File:** `vallen_cli/__main__.py`
- **Gejala:**
  - Cek `"-h" in args` dan `"-v" in args` berlaku global **sebelum** subcommand, sehingga `vallencli serve -h 0.0.0.0` menampilkan help. `run "fix -v bug"` juga bisa salah terbaca.
  - `--no-tools` diparse, tetapi `use_tools` **tidak dipakai** di `run_headless`.
  - `--continue` diparse lalu diabaikan.
  - `--port abc` → traceback `ValueError`.
  - Pesan error `ImportError` mengarah ke path hardcoded `/home/VALLEN/Desktop/src`.
- **Fix:** ganti dengan `argparse` (subparser `run`, `serve`). Jadikan `-h` bagian dari `run`/`serve` hanya sebagai `--help`. Gunakan `--host` tanpa alias `-h`. Implementasikan `--no-tools` (kirim `tools=None` / profil kosong ke `run_agent`), implementasikan `--continue` (`sess.resume_last()`), validasi port (1–65535), dan ganti pesan ImportError menjadi `pip install -e .`.

### P1-6. Mode headless tidak bisa mengedit / menjalankan shell

- **File:** `vallen_cli/core/headless.py`, `vallen_cli/core/permission.py`
- **Gejala:** Callback permission hanya dipasang di TUI (`tui/app.py:957`). Di headless tidak ada callback, jadi `PermissionManager.check` mengembalikan `REJECT` untuk `write`/`edit`/`shell`/`apply_patch`. `vallencli run "fix bug"` tidak bisa mengubah apa pun dan pesannya menyesatkan ("rejected by user").
- **Fix:**
  1. Tambah flag `--yes` / `--autopilot` di `run` yang mengeset `perm.allow_unsupervised = True` (nonaktif secara default).
  2. Tanpa flag itu, pasang callback yang menolak dengan pesan jelas: "Headless mode: aksi ini butuh persetujuan. Jalankan ulang dengan --yes".
  3. Tambah opsi `--allow "shell:git *"` atau dukung rule dari config.
  4. Exit code non-zero bila ada operasi yang ditolak.

### P1-7. Fuzzy edit gagal jika `oldString` memuat baris kosong

- **File:** `vallen_cli/tools/file_tools.py` (`smart_replace`, langkah 4)
- **Gejala:** `target_lines` membuang baris kosong, sedangkan `lines_stripped` menyimpan semuanya, sehingga perbandingan list tidak pernah cocok untuk blok yang punya baris kosong. Fallback whitespace-tolerant tidak jalan justru di kasus umum (fungsi dengan baris kosong di tengah).
- **Bukti:** konten `"def a():\n    x = 1\n\n    y = 2\n"` dengan `oldString` yang indentasinya tab → `smart_replace(...)[0] == False`.
- **Fix:** bangun daftar `(index_asli, stripped)` hanya untuk baris **tidak kosong** pada file, cocokkan urutan non-kosong dengan `target_lines`, lalu petakan kembali ke rentang baris asli (dari indeks awal sampai indeks akhir) saat mengganti.

### P1-8. Deny rule bisa dilewati lewat alias argumen

- **File:** `vallen_cli/core/agent.py` (penentuan `perm_path`), `vallen_cli/tools/base.py`
- **Gejala:** `perm_path = args.get("filePath") or args.get("path", "")`, padahal `EditTool` juga menerima `file_path`. Rule `"edit:*.env" = "deny"` tidak cocok karena target jatuh ke deskripsi.
- **Fix:** normalisasi argumen (`file_path` → `filePath`, dst.) **sebelum** permission check. Hindari fallback ke `description` sebagai target untuk tool file. Tolak kalau path kosong.

---

## P2 — Kecil

1. **`grep` pola berawalan `-`** (`file_tools.py`): pola seperti `-foo` dibaca `rg` sebagai flag. Pakai `["-e", pattern]` atau `--` sebelum pola/path.
2. **`grep` `--max-count 100` per file**, bukan total, sehingga output bisa sangat besar sebelum dipotong. Selain itu path `rg` absolut sedangkan fallback relatif. Seragamkan (relatif ke `search_dir`).
3. **`grep` fallback Python:** `include="*.{ts,tsx}"` tidak didukung `fnmatch` padahal deskripsi tool menjanjikannya. Expand brace. Fallback juga blocking (sync IO di async) dan tanpa timeout. Jalankan di `asyncio.to_thread` dengan batas waktu. Log (bukan `pass`) saat `rg` gagal.
4. **MIME gambar:** `data:image/jpg` → seharusnya `image/jpeg` (`ReadTool`). Tambahkan batas ukuran gambar.
5. **`ReadTool` truncation:** pemotongan 20.000 karakter menyarankan `offset=end_idx+1` yang salah (baris di antara titik potong dan `end_idx` terlewat), dan catatan bisa muncul dua kali. Hitung offset dari baris terakhir yang benar-benar ditampilkan. Tambahkan batas ukuran file sebelum `read_text`.
6. **Telemetry:** `input_tokens_total` hanya dihitung sekali di awal padahal konteks dikirim ulang tiap ronde. Akumulasikan per ronde, dan pakai `effective_model` (bukan `cfg.active_model`) untuk usage.
7. **Doom loop:** `pending_tool_calls.index(tc)` mencari berdasarkan kesetaraan dict. Ganti dengan `for idx, tc in enumerate(...)`.
8. **MCP init:** `except Exception: pass` di `run_agent` menyembunyikan kegagalan. Log dengan `logging` dan tampilkan event `info` yang ringkas.
9. **Shell tool:** `is_sudo_needed` bernilai true untuk substring `"sudo "` apa pun (termasuk `echo "sudo "`) dan menjanjikan "interactive terminal will open automatically". Pastikan janji itu benar atau ubah pesannya. Validasi `timeout` (`int()` bisa `ValueError`, nilai negatif/raksasa perlu dibatasi) dan output parsial saat timeout selalu kosong (komunikasi sudah dibatalkan oleh `wait_for`). Baca stream secara inkremental bila ingin output parsial.
10. **Konkurensi file:** tambahkan `asyncio.Lock` per path pada `write`/`edit`/`apply_patch` untuk mencegah balapan bila tool dijalankan bersamaan.
11. **Prompt cache:** `session.cached_system_prompt` dipakai selama sesi, jadi perubahan `AGENTS.md` atau pergantian mode plan/build mungkin tidak tercermin. Pastikan `mode` setter dan perubahan agents.md meng-invalidasi cache (periksa `core/session.py` baris ~74 dan ~152).
12. **`stream_finish_reason`** hanya diisi saat `break`. Kalau stream berakhir tanpa `break`, deteksi `length` tidak jalan. Isi dari chunk terakhir yang punya `finish_reason`.

---

## Saran fitur (opsional, kerjakan setelah semua di atas hijau)

- `vallencli run --json` (keluaran terstruktur) dan exit code yang terdokumentasi.
- Server: satu sesi/workspace per request (hindari singleton global yang dipakai bersama antar request), dan endpoint untuk cancel.
- Log terstruktur (`logging`) menggantikan `except Exception: pass`.
- Izinkan konfigurasi profil tool untuk mode headless (`--profile explore`).

---

## Definition of Done

- [ ] P0-1 s/d P0-3 selesai, tes regresi hijau.
- [ ] P1-1 s/d P1-8 selesai, tiap item punya tes.
- [ ] `pytest tests/` tidak punya kegagalan baru dibanding baseline.
- [ ] Tidak ada `tool_call_id` tanpa result atau dengan result ganda dalam skenario cancel, retry, atau path di luar workspace.
- [ ] Ringkasan akhir: daftar file yang diubah, perubahan perilaku yang terlihat pengguna (mis. server sekarang butuh token, `-h` di `serve` berubah), dan item yang sengaja dilewati beserta alasannya.

# BUG: TUI lag berat setelah kartu tool menampilkan diff (`write`/`edit`)

## Gejala
- Setelah agent menjalankan tool `write`/`edit` dan kartu diff muncul di chat (contoh: `write [ DONE ] ... login.html (file baru, +23 -0)` diikuti baris `@@ -0,0 +1,23 @@`), TUI jadi sangat berat.
- Ngetik di input nge-lag, scroll chat nge-lag.
- Ngetik `/clear` langsung membuat TUI ringan lagi.
- Animasi kotak input terlihat lancar, jadi **animasi BUKAN penyebab utama** (jangan habiskan waktu di sana dulu).

## Kesimpulan awal
Beban render sebanding dengan jumlah widget berat yang ter-mount di panel chat. `/clear` membuang widget-widget itu, makanya ringan lagi. Kandidat utama: kartu diff dan pesan assistant yang dirender dengan Rich yang mahal.

## Lokasi kode yang dicurigai
1. `vallen_cli/tui/widgets/message.py`, class `ToolCallCard._render_card()` (sekitar baris 445-465)
   - `Static.update(Syntax(self._diff, "diff", theme="monokai", word_wrap=True))`
   - `Syntax` melakukan lexing pygments dan word-wrap. Jalur diff **tidak dipotong** (jalur output biasa dipotong 1200 karakter), dan mungkin dirender ulang setiap layout pass.
2. `vallen_cli/tui/widgets/message.py`, fungsi `_render_content()` (sekitar baris 40-85)
   - Pesan assistant dirender dengan `Markdown(content, code_theme="monokai")`, yang juga mahal kalau dirender ulang terus.
3. `vallen_cli/tui/app.py` (sekitar baris 1237-1260)
   - Tempat kartu dibuat/di-update (`update_result(..., diff=diff)`). Cek apakah kartu bisa ter-update berulang atau kartu lama tidak pernah dibersihkan.
4. Diff dibangun di `vallen_cli/core/agent.py` `_build_unified_diff(max_total_lines=120)`, jadi ukuran diff sudah terbatas. Masalahnya kemungkinan besar biaya render, bukan ukuran data.

## Langkah 1: buktikan dulu (jangan langsung menebak fix)
- Jalankan dengan Textual devtools (`textual run --dev`) atau profil dengan `py-spy top` / `cProfile` saat TUI lag.
- Cek apakah waktu terbanyak ada di `rich.syntax`, `pygments`, `rich.markdown`, atau `Widget._get_content_height` / `render_lines`.
- Uji A/B cepat: ganti `Syntax(...)` di `ToolCallCard._render_card` dengan `Text(self._diff)` polos. Kalau lag hilang, penyebab terkonfirmasi.
- Catat jumlah widget di chat panel saat lag (`len(panel.children)`) dan bandingkan sebelum dan sesudah beberapa kartu diff.

## Langkah 2: fix (urut prioritas, berhenti kalau sudah teratasi)
1. **Ganti `Syntax` untuk diff dengan `rich.text.Text` yang diwarnai per baris** (tanpa pygments):
   - baris `+` hijau, `-` merah, `@@` abu/ungu, lainnya warna default.
   - Bangun `Text` **sekali** (di `_render_card`), jangan dibangun ulang tiap render.
   - Potong maksimal ~120 baris dan tambahkan "... (dipotong)" seperti jalur output biasa.
2. Kalau `Markdown` pesan assistant ikut berat: render sekali setelah streaming selesai, dan jangan bikin ulang widget lama.
3. **Batasi jumlah widget chat yang ter-mount** (misalnya 150-200 terakhir). Pesan yang lebih lama dipangkas atau diganti ringkasan satu baris.
4. Pastikan `ToolCallCard` selalu keluar dari status `running` (timer `_tick_tool` harus berhenti) dan tidak ada `update()` berulang pada kartu yang sudah `done`.
5. Hanya kalau profil menunjukkan animasi ikut berkontribusi: pakai `update(..., layout=False)` di animasi input (tergantung versi Textual, cek dulu dengan `pip show textual`).

## Kriteria selesai
- Setelah 10+ kartu `write`/`edit` muncul di chat, ngetik dan scroll tetap lancar tanpa `/clear`.
- Tampilan diff tetap berwarna dan terbaca (`+`/`-`/`@@` jelas).
- Test yang ada tetap lulus: `pytest tests/test_tool_ux_phase*.py tests/test_cli_fixes.py`.
- Tambahkan test kecil yang memastikan jalur diff tidak memakai `Syntax` dan terpotong di batas baris.

## Jangan diubah
- **Animasi (label terminal, water, spinner kartu tool) HARUS tetap jalan dan tampil sama.** Jangan dimatikan, dihapus, atau dilambatkan. Langkah 5 hanya boleh dilakukan kalau profil membuktikan perlu, dan hasilnya tidak boleh mengubah tampilan animasi.
- Logika permission, tool, dan agent loop. Bug ini murni di lapisan render TUI.
- Format diff dari `_build_unified_diff` (dipakai juga oleh IDE).

## Catatan
Diagnosis ini berasal dari membaca kode, belum dari menjalankan TUI. Kalau hasil profil di Langkah 1 menunjuk tempat lain, ikuti hasil profil.

---

## Status Update (_DONEUPDATE) - SELESAI
1. **Zero-Pygments Fast Diff (`_render_diff_text`)**:
   - `Syntax(..., "diff")` yang berat digantikan dengan `rich.text.Text` berwarna per baris:
     - `+` hijau cerah (`#4ade80`), `-` merah (`#f87171`), `@@` ungu (`#c084fc`), `+++`/`---` biru-abu (`#9999bb`), `📝 ` cyan (`#38bdf8`).
   - Diff dipotong maksimal 120 baris dengan catatan `... (N baris dipotong)`.
   - `Text` di-cache di `_cached_diff_render` pada `ToolCallCard` dan hanya dibangun sekali saat diff diset/diupdate.
2. **Assistant Markdown Rendering**:
   - `StreamingMessage` hanya merender Markdown sekali saat `finalize()`. Selama token streaming menggunakan Text ringan.
3. **Budget DOM Chat Widget**:
   - `_mount_chat_widget` membatasi widget ter-mount maksimal 160 widget di panel chat. Widget lama di-prune secara otomatis.
   - Semua jalur mount di `vallen_cli/tui/app.py` (`_post_system`, `_post_message`, streaming, dan tool cards) menggunakan helper ini.
4. **Timer Card & Update Idempotent**:
   - `_tick_tool` berhenti dan membersihkan `_timer` saat status bukan `running`.
   - `update_result()` menghentikan `_timer`, membersihkannya, dan mencegah re-render jika status/output/diff sudah identik.
   - Status kartu yang bertransisi dari `preparing` ke `running` memastikan timer aktif, dan saat selesai (`done`/`error`/`rejected`) timer dijamin mati.
5. **Verifikasi & Test**:
   - Semua test di `tests/test_tool_ux_phase*.py` dan `tests/test_cli_fixes.py` lulus (34 passed).
   - Test suite penuh lulus (167 passed).
   - Benchmark 15-20 kartu diff ter-mount dalam ~380ms tanpa freeze/lag.

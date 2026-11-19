# Bot Café Retri

Bot Telegram untuk mengurus jadwal shift (barista & chef), cuti, overtime, absensi, dan stok inventory Café Retri. Semua perintah hanya untuk admin.

## Fitur

**Jadwal & cuti**
`/jadwal`, `/cuti`, `/batalcuti`, `/cekjatah`, `/setjatah`, `/pindahlibur`, `/tukarjam`, `/bataltukarjam`, `/batallibur`, `/pulihkanlibur`, `/daftarcuti`

**Overtime**
`/startovertime`, `/ot`, `/ambilot`, `/saldo`, `/semuasaldo`, `/rekap`, `/history`, `/tutupbulan`

**Backup & file**
- `/backupdata` membuat backup (.zip). Kirim file .zip ke bot untuk restore.
- Kirim file .txt (log scan absensi) untuk dijadikan laporan PDF.
- Kirim file .xlsx (stok) untuk update inventory.

**Inventory**
`/setbaseline`, `/setbatas`, `/cekstok`

## Environment variable

| Nama | Wajib | Keterangan |
|---|---|---|
| `BOT_TOKEN` | Ya | Token bot dari @BotFather. Jangan pernah di-commit. |
| `ADMIN_IDS` | Ya | ID Telegram admin, dipisah koma (contoh: `111,222`). Kalau kosong, semua perintah ditolak. |
| `DATA_DIR` | Disarankan | Folder penyimpanan data JSON. Default `.` (hilang tiap deploy di Railway). |

## Menjalankan di lokal

```bash
pip install -r requirements.txt
export BOT_TOKEN=...
export ADMIN_IDS=111,222
python bot.py
```

## Deploy di Railway

1. Hubungkan repo ini ke project Railway (service worker, `Procfile`: `worker: python bot.py`).
2. Isi variable `BOT_TOKEN` dan `ADMIN_IDS`.
3. Tambah **Volume** yang di-mount ke `/data`, lalu set `DATA_DIR=/data` supaya data tidak hilang saat redeploy.

## Struktur file

- `bot.py`: semua command dan logika bot
- `absensi_import.py`: parsing log absensi dan pembuatan PDF
- `inventory_import.py`: parsing Excel stok dan pencocokan nama barang
- `Procfile`, `requirements.txt`: konfigurasi deploy dan dependency

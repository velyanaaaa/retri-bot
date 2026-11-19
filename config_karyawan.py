"""Data karyawan & jadwal tetap Café Retri.

Edit file ini kalau ada karyawan baru, libur tetap berubah, atau jam shift berubah.
Tidak perlu menyentuh bot.py.
"""

BARISTA = ["Dian", "Yuyu", "Krisna", "Ayuk"]

# Hari libur tetap tiap barista (1x per minggu)
LIBUR_TETAP_BARISTA = {
    "senin":  "Yuyu",
    "selasa": "Ayuk",
    "rabu":   "Dian",
    "kamis":  None,
    "jumat":  None,
    "sabtu":  None,
    "minggu": "Krisna",
}

# Jadwal shift barista per hari (fixed, sesuai papan tulis)
# Kalau orangnya libur/cuti hari itu, entrinya di-skip (bukan dibaca dari sini)
JADWAL_BARISTA = {
    "senin":  {"Krisna": "09:30", "Dian": "08:30", "Ayuk": "06:30", "Yuyu": "LIBUR"},
    "selasa": {"Krisna": "09:30", "Dian": "06:30", "Ayuk": "LIBUR", "Yuyu": "08:30"},
    "rabu":   {"Krisna": "06:30", "Dian": "LIBUR", "Ayuk": "09:30", "Yuyu": "08:30"},
    "kamis":  {"Krisna": "06:30", "Dian": "09:30", "Ayuk": "09:30", "Yuyu": "06:30"},
    "jumat":  {"Krisna": "09:30", "Dian": "06:30", "Ayuk": "06:30", "Yuyu": "09:30"},
    "sabtu":  {"Krisna": "06:30", "Dian": "09:30", "Ayuk": "06:30", "Yuyu": "09:30"},
    "minggu": {"Krisna": "LIBUR", "Dian": "06:30", "Ayuk": "09:30", "Yuyu": "08:30"},
}

# ─────────────────────────────────────────────
#  TIM CHEF
# ─────────────────────────────────────────────
CHEF = ["Adi", "Ucil", "Dito"]

# Hari libur tetap tiap chef (1x per minggu)
LIBUR_TETAP_CHEF = {
    "senin":  "Ucil",
    "selasa": None,
    "rabu":   "Adi",
    "kamis":  "Dito",
    "jumat":  None,
    "sabtu":  None,
    "minggu": None,
}

# Jadwal shift chef per hari (fixed)
JADWAL_CHEF = {
    "senin":  {"Adi": "09:30", "Ucil": "LIBUR", "Dito": "06:30"},
    "selasa": {"Adi": "06:30", "Ucil": "09:30", "Dito": "08:00"},
    "rabu":   {"Adi": "LIBUR", "Ucil": "09:30", "Dito": "06:30"},
    "kamis":  {"Adi": "09:30", "Ucil": "06:30", "Dito": "LIBUR"},
    "jumat":  {"Adi": "08:00", "Ucil": "06:30", "Dito": "09:30"},
    "sabtu":  {"Adi": "09:30", "Ucil": "08:00", "Dito": "06:30"},
    "minggu": {"Adi": "08:00", "Ucil": "06:30", "Dito": "09:30"},
}

# Gabungan semua karyawan untuk validasi nama
SEMUA_KARYAWAN = BARISTA + CHEF

"""
Bot Café Retri — Jadwal + Overtime (1 file)
=============================================
Gabungan bot jadwal shift & bot overtime karyawan.
- Command jadwal (/jadwal, /cuti, dst) → generate PDF jadwal
- Command overtime (/ot, /rekap, /history, dst) → generate PDF overtime
"""

import os, json, logging
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters

from absensi_import import parse_absensi_txt, generate_pdf_absensi, rekap_ringkas

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_IDS = [int(x) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip()]

DATA_FILE      = "cuti_requests.json"   # data jadwal (mingguan)
JATAH_CUTI_FILE = "jatah_cuti.json"     # data sisa jatah cuti tahunan per karyawan
JATAH_CUTI_DEFAULT = 12                 # jatah cuti per tahun (sama rata semua karyawan)

HARI_VALID = ["senin", "selasa", "rabu", "kamis", "jumat", "sabtu", "minggu"]

# ─────────────────────────────────────────────
#  TIM BARISTA
# ─────────────────────────────────────────────
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


# ─────────────────────────────────────────────
#  HELPER: ADMIN CHECK
# ─────────────────────────────────────────────
def is_admin(uid):
    return uid in ADMIN_IDS


# ─────────────────────────────────────────────
#  HELPER: DATA STORAGE
# ─────────────────────────────────────────────
def load_data():
    """Load semua data cuti & pembatalan libur tetap dari file JSON."""
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE) as f:
            return json.load(f)
    return {}

def save_data(data):
    """Simpan data ke file JSON."""
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ─────────────────────────────────────────────
#  HELPER: JATAH CUTI TAHUNAN
# ─────────────────────────────────────────────
def load_jatah_cuti():
    """
    Load sisa jatah cuti tahunan per karyawan.
    Format: {"Nama": sisa_jatah, ...}
    Kalau file belum ada / karyawan belum tercatat → pakai JATAH_CUTI_DEFAULT.
    """
    data = {}
    if os.path.exists(JATAH_CUTI_FILE):
        with open(JATAH_CUTI_FILE) as f:
            data = json.load(f)
    for nama in SEMUA_KARYAWAN:
        if nama not in data:
            data[nama] = JATAH_CUTI_DEFAULT
    return data

def save_jatah_cuti(data):
    with open(JATAH_CUTI_FILE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def kurangi_jatah_cuti(nama):
    """Kurangi jatah cuti nama sebanyak 1. Return sisa jatah setelah dikurangi."""
    data = load_jatah_cuti()
    data[nama] = data.get(nama, JATAH_CUTI_DEFAULT) - 1
    save_jatah_cuti(data)
    return data[nama]

def kembalikan_jatah_cuti(nama):
    """Kembalikan jatah cuti nama sebanyak 1 (batal cuti). Return sisa jatah setelah dikembalikan."""
    data = load_jatah_cuti()
    data[nama] = data.get(nama, JATAH_CUTI_DEFAULT) + 1
    save_jatah_cuti(data)
    return data[nama]


# ─────────────────────────────────────────────
#  HELPER: MINGGU TARGET
# ─────────────────────────────────────────────
def get_target_monday():
    """
    Kalau hari ini Minggu → jadwal yang dikelola adalah minggu depan.
    Selain itu → jadwal minggu berjalan.
    """
    today  = datetime.now()
    monday = today - timedelta(days=today.weekday())
    if today.weekday() == 6:  # Minggu
        monday += timedelta(weeks=1)
    return monday

def get_week_key():
    return get_target_monday().strftime("%Y-W%W")

def get_week_data():
    return load_data().get(get_week_key(), {})


# ─────────────────────────────────────────────
#  LOGIKA JADWAL
# ─────────────────────────────────────────────
def siapa_tidak_masuk(hari, week_data, tim="barista"):
    """
    Return list nama karyawan yang tidak masuk di hari ini.
    Tidak masuk = libur tetap mingguan ATAU request cuti yang disetujui.
    Libur tetap bisa dibatalkan admin (karyawan jadi masuk).
    """
    tidak_masuk = []
    dibatalkan  = week_data.get("batal_libur_tetap", [])  # key: "hari_nama"

    libur_tetap_map = LIBUR_TETAP_BARISTA if tim == "barista" else LIBUR_TETAP_CHEF
    libur_tetap     = libur_tetap_map.get(hari)

    # Cek apakah libur tetap hari ini dipindah ke hari lain minggu ini
    # Format: {"Yuyu": "kamis"} → Yuyu pindah libur dari hari asli ke Kamis
    pindah_libur = week_data.get("pindah_libur", {})

    if libur_tetap and f"{hari}_{libur_tetap}" not in dibatalkan:
        if libur_tetap in pindah_libur:
            pass  # hari asli: dia masuk karena liburnya dipindah
        else:
            tidak_masuk.append(libur_tetap)

    # Kalau hari ini adalah hari libur pindahan → tambahkan ke tidak_masuk
    anggota_tim = BARISTA if tim == "barista" else CHEF
    for nama_pindah, hari_baru in pindah_libur.items():
        if hari_baru == hari and nama_pindah in anggota_tim and nama_pindah not in tidak_masuk:
            tidak_masuk.append(nama_pindah)

    # Masukkan request cuti yang disetujui
    anggota = BARISTA if tim == "barista" else CHEF
    for nama, hari_list in week_data.get("cuti", {}).items():
        if nama in anggota and hari in hari_list and nama not in tidak_masuk:
            tidak_masuk.append(nama)

    return tidak_masuk


def hitung_jadwal_barista_seminggu(week_data):
    """
    - Hari normal (cuma libur tetap terjadwal, sesuai LIBUR_TETAP_BARISTA) →
      pakai jadwal fix dari JADWAL_BARISTA (sesuai papan tulis).
    - Kalau ada 1 orang tambahan yang TIDAK masuk di luar libur tetap normal
      (cuti mendadak / pindah libur tambahan), sisa 3 orang masuk:
        * Orang yang jam fix-nya SUDAH UNIK (tidak sama dengan siapa pun,
          termasuk yang cuti) di hari itu → TETAP di jam fix-nya, tidak digeser.
        * Orang yang jam fix-nya SAMA (double) dengan orang yang cuti →
          salah satunya (rotasi fairness) digeser mengisi slot 08:30 yang
          kosong, sisanya tetap di jam fix.
    - Kalau ada 2 orang (atau lebih) yang tidak masuk sekaligus, sisa 2 orang
      masuk → dipaksa ke 06:30 & 09:30 saja (08:30 di-skip), rotasi fairness.
    - Yang tidak masuk ditandai LIBUR.
    """
    hasil = {hari: {} for hari in HARI_VALID}
    dapat = {nama: {"06:30": 0, "08:30": 0, "09:30": 0} for nama in BARISTA}

    for hari in HARI_VALID:
        tidak_masuk       = siapa_tidak_masuk(hari, week_data, tim="barista")
        masuk              = [n for n in BARISTA if n not in tidak_masuk]
        libur_tetap_hari   = LIBUR_TETAP_BARISTA.get(hari)
        # "Ekstra" tidak masuk = tidak_masuk di luar libur tetap terjadwal hari ini
        tidak_masuk_ekstra = [n for n in tidak_masuk if n != libur_tetap_hari]

        for nama in tidak_masuk:
            hasil[hari][nama] = "LIBUR"

        if not tidak_masuk_ekstra:
            # Hari normal (paling banyak 1 orang libur tetap): pakai jadwal fix
            for nama in masuk:
                hasil[hari][nama] = JADWAL_BARISTA[hari][nama]

        elif len(masuk) == 3:
            # 1 orang tambahan gak masuk: pertahankan yang jamnya sudah unik,
            # cuma geser yang double dengan orang yang gak masuk
            jam_fix_masuk = {nama: JADWAL_BARISTA[hari][nama] for nama in masuk}
            hitung_jam    = {}
            for jam in jam_fix_masuk.values():
                hitung_jam[jam] = hitung_jam.get(jam, 0) + 1

            perlu_geser = []
            for nama in masuk:
                jam = jam_fix_masuk[nama]
                if hitung_jam[jam] == 1:
                    # Unik (tidak double dengan siapa pun yang masih masuk) → tetap
                    hasil[hari][nama] = jam
                else:
                    perlu_geser.append(nama)

            # Slot yang sudah terisi vs yang masih kosong dari 3 slot standar
            slot_standar = ["06:30", "08:30", "09:30"]
            slot_terisi  = set(hasil[hari][n] for n in masuk if n not in perlu_geser)
            slot_kosong  = [j for j in slot_standar if j not in slot_terisi]

            # Bagikan slot kosong ke yang perlu digeser, rotasi fairness
            sisa = list(perlu_geser)
            for jam in slot_kosong:
                if not sisa:
                    break
                kandidat = sorted(sisa, key=lambda n: dapat[n][jam])
                terpilih = kandidat[0]
                hasil[hari][terpilih] = jam
                dapat[terpilih][jam] += 1
                sisa.remove(terpilih)

        else:
            # 2 orang (atau lebih) gak masuk sekaligus: paksa 06:30 & 09:30 saja
            sisa_masuk = list(masuk)
            for jam in ["06:30", "09:30"]:
                if not sisa_masuk:
                    break
                kandidat = sorted(sisa_masuk, key=lambda n: dapat[n][jam])
                terpilih = kandidat[0]
                hasil[hari][terpilih] = jam
                dapat[terpilih][jam] += 1
                sisa_masuk.remove(terpilih)
            # Edge case: kalau masih ada sisa, isi pakai jadwal fix
            for nama in sisa_masuk:
                hasil[hari][nama] = JADWAL_BARISTA[hari][nama]

    return hasil


def buat_jadwal_barista(hari, week_data, jadwal_seminggu=None):
    """
    Return list {"nama": ..., "jam": ...} barista yang masuk hari ini.
    Pakai jadwal_seminggu (pre-computed) kalau tersedia.
    """
    if jadwal_seminggu:
        return [
            {"nama": nama, "jam": jadwal_seminggu[hari][nama]}
            for nama in BARISTA
            if jadwal_seminggu[hari].get(nama, "LIBUR") != "LIBUR"
        ]

    # Fallback manual (tidak dipakai normalnya)
    tidak_masuk = siapa_tidak_masuk(hari, week_data, tim="barista")
    return [
        {"nama": nama, "jam": JADWAL_BARISTA[hari][nama]}
        for nama in BARISTA
        if nama not in tidak_masuk
    ]


def hitung_jadwal_chef_seminggu(week_data):
    """
    - Hari normal (cuma libur tetap terjadwal, sesuai LIBUR_TETAP_CHEF) → pakai
      jadwal fix dari JADWAL_CHEF, karena tabel itu sudah dibuat dengan asumsi
      1 orang libur tetap per hari.
    - Kalau ada tambahan yang TIDAK masuk di luar libur tetap normal (cuti
      mendadak / pindah libur tambahan, sehingga cuma 2 orang masuk) → dua
      slot penting WAJIB terisi: 06:30 & 09:30 (slot 08:00 di-skip). Siapa
      dapat 06:30 vs 09:30 digilir tiap minggu (fairness/rotasi) biar rata.
    - Yang tidak masuk ditandai LIBUR.
    """
    hasil = {hari: {} for hari in HARI_VALID}
    dapat = {nama: {"06:30": 0, "09:30": 0} for nama in CHEF}

    for hari in HARI_VALID:
        tidak_masuk       = siapa_tidak_masuk(hari, week_data, tim="chef")
        masuk              = [n for n in CHEF if n not in tidak_masuk]
        libur_tetap_hari   = LIBUR_TETAP_CHEF.get(hari)
        # "Ekstra" tidak masuk = tidak_masuk di luar libur tetap terjadwal hari ini
        tidak_masuk_ekstra = [n for n in tidak_masuk if n != libur_tetap_hari]

        for nama in tidak_masuk:
            hasil[hari][nama] = "LIBUR"

        if not tidak_masuk_ekstra:
            # Hari normal (paling banyak 1 orang libur tetap): pakai jadwal fix
            for nama in masuk:
                hasil[hari][nama] = JADWAL_CHEF[hari][nama]
        else:
            # Ada tambahan yang gak masuk: cover 06:30 & 09:30 via rotasi fairness
            sisa_masuk = list(masuk)
            for jam in ["06:30", "09:30"]:
                if not sisa_masuk:
                    break
                kandidat = sorted(sisa_masuk, key=lambda n: dapat[n][jam])
                terpilih = kandidat[0]
                hasil[hari][terpilih] = jam
                dapat[terpilih][jam] += 1
                sisa_masuk.remove(terpilih)
            # Kalau masih ada sisa (3 orang tetap masuk, edge case), isi pakai jadwal fix
            for nama in sisa_masuk:
                hasil[hari][nama] = JADWAL_CHEF[hari][nama]

    return hasil


def buat_jadwal_chef(hari, week_data, jadwal_seminggu=None):
    """
    Return list {"nama": ..., "jam": ...} chef yang masuk hari ini.
    Pakai jadwal_seminggu (pre-computed dengan fairness) kalau tersedia.
    """
    if jadwal_seminggu:
        return [
            {"nama": nama, "jam": jadwal_seminggu[hari][nama]}
            for nama in CHEF
            if jadwal_seminggu[hari].get(nama, "LIBUR") != "LIBUR"
        ]

    # Fallback manual (tidak dipakai normalnya)
    tidak_masuk = siapa_tidak_masuk(hari, week_data, tim="chef")
    return [
        {"nama": nama, "jam": JADWAL_CHEF[hari][nama]}
        for nama in CHEF
        if nama not in tidak_masuk
    ]


# ─────────────────────────────────────────────
#  GENERATE PDF
# ─────────────────────────────────────────────
def generate_pdf(week_data):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        SimpleDocTemplate, Table, TableStyle,
        Paragraph, Spacer, HRFlowable
    )
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

    # Palet warna
    BLACK      = colors.HexColor("#111111")
    DARK_GRAY  = colors.HexColor("#2D2D2D")
    MID_GRAY   = colors.HexColor("#757575")
    LIGHT_GRAY = colors.HexColor("#F7F7F7")
    WHITE      = colors.white
    ACCENT_B   = colors.HexColor("#1A73E8")   # biru untuk barista
    ACCENT_C   = colors.HexColor("#E8711A")   # oranye untuk chef
    RED        = colors.HexColor("#D32F2F")   # merah untuk libur tetap
    AMBER      = colors.HexColor("#E65100")   # amber untuk cuti
    TODAY_BG   = colors.HexColor("#E8F0FE")
    BORDER     = colors.HexColor("#E0E0E0")
    HEADER_BG  = colors.HexColor("#FAFAFA")

    today  = datetime.now()
    monday = get_target_monday()
    sunday = monday + timedelta(days=6)
    tanggal = {
        HARI_VALID[i]: (monday + timedelta(days=i)).strftime("%d/%m")
        for i in range(7)
    }

    pdf_path = "jadwal_cafe.pdf"
    doc = SimpleDocTemplate(
        pdf_path, pagesize=A4,
        topMargin=1.5*cm, bottomMargin=1.2*cm,
        leftMargin=1.5*cm, rightMargin=1.5*cm
    )

    styles = getSampleStyleSheet()
    def ps(name, **kw):
        return ParagraphStyle(name, parent=styles["Normal"], **kw)

    title_s = ps("t",   alignment=1, fontName="Helvetica-Bold", fontSize=22, textColor=BLACK,     spaceAfter=3)
    sub_s   = ps("s",   alignment=1, fontName="Helvetica",      fontSize=10, textColor=MID_GRAY,  spaceAfter=2)
    gen_s   = ps("g",   alignment=1, fontName="Helvetica",      fontSize=8,  textColor=MID_GRAY)
    c_head  = ps("ch",  alignment=1, fontName="Helvetica-Bold", fontSize=9,  textColor=WHITE)
    c_day   = ps("cd",  alignment=1, fontName="Helvetica-Bold", fontSize=8,  textColor=DARK_GRAY, leading=11)
    c_norm  = ps("cn",  alignment=1, fontName="Helvetica-Bold", fontSize=9,  textColor=DARK_GRAY)
    c_libur = ps("cl",  alignment=1, fontName="Helvetica-Bold", fontSize=9,  textColor=RED)
    c_cuti  = ps("cct", alignment=1, fontName="Helvetica-Bold", fontSize=8,  textColor=AMBER)
    c_leg   = ps("leg", alignment=1, fontName="Helvetica",      fontSize=7,  textColor=MID_GRAY)

    dibatalkan   = week_data.get("batal_libur_tetap", [])
    is_next_week = today.weekday() == 6
    today_row    = -1 if is_next_week else (today.weekday() + 1)
    pw           = A4[0] - 3*cm

    def section_header(label, accent):
        t = Table(
            [[Paragraph(f"<b>{label}</b>",
              ps("sh", fontName="Helvetica-Bold", fontSize=10, textColor=WHITE))]],
            colWidths=[pw]
        )
        t.setStyle(TableStyle([
            ("BACKGROUND",    (0,0), (-1,-1), accent),
            ("LEFTPADDING",   (0,0), (-1,-1), 10),
            ("TOPPADDING",    (0,0), (-1,-1), 6),
            ("BOTTOMPADDING", (0,0), (-1,-1), 6),
        ]))
        return t

    def build_table(anggota, jadwal_fn, libur_tetap_map, tim, accent):
        header = [Paragraph("HARI", c_head)] + [
            Paragraph(n.upper(), c_head) for n in anggota
        ]
        data = [header]

        for hari in HARI_VALID:
            jadwal_hari = jadwal_fn(hari, week_data)
            tidak_masuk = siapa_tidak_masuk(hari, week_data, tim=tim)
            row = [Paragraph(
                f"<b>{hari[:3].capitalize()}</b><br/>"
                f"<font size='7' color='#757575'>{tanggal[hari]}</font>",
                c_day
            )]

            pindah_libur = week_data.get("pindah_libur", {})
            for nama in anggota:
                if nama in tidak_masuk:
                    libur_tetap = libur_tetap_map.get(hari)
                    # Libur tetap normal (belum dibatalkan)
                    if libur_tetap == nama and f"{hari}_{nama}" not in dibatalkan:
                        row.append(Paragraph("Libur", c_libur))
                    # Hari ini adalah hari pindahan libur karyawan ini
                    elif pindah_libur.get(nama) == hari:
                        row.append(Paragraph("Libur", c_libur))
                    else:
                        row.append(Paragraph("Cuti", c_cuti))
                else:
                    entry = next((j for j in jadwal_hari if j["nama"] == nama), None)
                    row.append(Paragraph(entry["jam"] if entry else "—", c_norm))

            data.append(row)

        n  = len(anggota)
        cw = [2.2*cm] + [(pw - 2.2*cm) / n] * n
        t  = Table(data, colWidths=cw, repeatRows=1)
        cmds = [
            ("BACKGROUND",    (0,0),  (-1,0),  accent),
            ("ROWBACKGROUNDS",(1,1),  (-1,-1), [WHITE, LIGHT_GRAY]),
            ("BACKGROUND",    (0,1),  (0,-1),  HEADER_BG),
            ("LINEBELOW",     (0,0),  (-1,-1), 0.4, BORDER),
            ("LINEAFTER",     (0,0),  (-1,-1), 0.4, BORDER),
            ("BOX",           (0,0),  (-1,-1), 0.8, BORDER),
            ("ALIGN",         (0,0),  (-1,-1), "CENTER"),
            ("VALIGN",        (0,0),  (-1,-1), "MIDDLE"),
            ("TOPPADDING",    (0,0),  (-1,-1), 7),
            ("BOTTOMPADDING", (0,0),  (-1,-1), 7),
        ]
        if 1 <= today_row <= 7:
            cmds.append(("BACKGROUND", (0,today_row), (-1,today_row), TODAY_BG))
            cmds.append(("TEXTCOLOR",  (1,today_row), (-1,today_row), ACCENT_B))
        t.setStyle(TableStyle(cmds))
        return t

    # Hitung jadwal seminggu penuh untuk kedua tim (dengan rotasi fairness)
    jadwal_barista_minggu = hitung_jadwal_barista_seminggu(week_data)
    jadwal_chef_minggu    = hitung_jadwal_chef_seminggu(week_data)
    period = f"{monday.strftime('%d %b')} – {sunday.strftime('%d %b %Y')}"

    story = [
        Paragraph("Jadwal Kerja Café Retri", title_s),
        Paragraph(period, sub_s),
        Paragraph(f"Dibuat: {today.strftime('%d/%m/%Y %H:%M')}", gen_s),
        Spacer(1, 0.4*cm),
        HRFlowable(width="100%", thickness=1.5, color=ACCENT_B, spaceAfter=4),
        Spacer(1, 0.2*cm),
        section_header("☕  BARISTA", ACCENT_B),
        build_table(
            BARISTA,
            lambda h, w: buat_jadwal_barista(h, w, jadwal_barista_minggu),
            LIBUR_TETAP_BARISTA, "barista", ACCENT_B
        ),
        Spacer(1, 0.35*cm),
        section_header("🍳  CHEF", ACCENT_C),
        build_table(
            CHEF,
            lambda h, w: buat_jadwal_chef(h, w, jadwal_chef_minggu),
            LIBUR_TETAP_CHEF, "chef", ACCENT_C
        ),
        Spacer(1, 0.3*cm),
        HRFlowable(width="100%", thickness=0.5, color=BORDER),
        Spacer(1, 0.1*cm),
        Paragraph(
            "Libur = libur tetap mingguan  ·  Cuti = request cuti  ·  Baris biru = hari ini",
            c_leg
        ),
    ]
    doc.build(story)
    return pdf_path


# ─────────────────────────────────────────────
#  HELPER: KIRIM PDF KE TELEGRAM
# ─────────────────────────────────────────────
async def kirim_pdf(update, context):
    week_data = get_week_data()
    pdf_path  = generate_pdf(week_data)
    monday    = get_target_monday()
    with open(pdf_path, "rb") as f:
        await update.message.reply_document(
            document=f,
            filename=f"Jadwal_{monday.strftime('%d%b%Y')}.pdf",
            caption=f"☕ Jadwal Café Retri — Minggu {monday.strftime('%d %b %Y')}"
        )


# ─────────────────────────────────────────────
#  COMMAND: /start
# ─────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if is_admin(uid):
        msg = (
            "☕ Bot Jadwal Café Retri — ADMIN\n\n"
            "📋 Perintah yang tersedia:\n\n"
            "▸ /cuti [nama] [hari]\n"
            "  Ajukan request cuti karyawan\n"
            "  Contoh: /cuti ucil minggu\n\n"
            "▸ /batalcuti [nama] [hari]\n"
            "  Batalkan request cuti\n"
            "  Contoh: /batalcuti ucil minggu\n\n"
            "▸ /cekjatah [nama]\n"
            "  Cek sisa jatah cuti tahunan (kosongkan nama = semua)\n"
            "  Contoh: /cekjatah ucil\n\n"
            "▸ /setjatah [nama] [jumlah]\n"
            "  Set/reset jatah cuti manual\n"
            "  Contoh: /setjatah ucil 12\n"
            "  Contoh: /setjatah semua 12  ← reset semua\n\n"
            "▸ /pindahlibur [nama] [hari_baru]\n"
            "  Pindah hari libur tetap karyawan (bukan cuti)\n"
            "  Contoh: /pindahlibur yuyu kamis\n\n"
            "▸ /batallibur [hari] [tim]\n"
            "  Batalkan libur tetap → karyawan masuk hari itu\n"
            "  Contoh: /batallibur senin barista\n"
            "  Contoh: /batallibur rabu chef\n"
            "  Contoh: /batallibur senin  ← semua tim\n\n"
            "▸ /pulihkanlibur [hari] [tim]\n"
            "  Kembalikan libur tetap yang sudah dibatalkan\n"
            "  Contoh: /pulihkanlibur senin barista\n\n"
            "▸ /daftarcuti\n"
            "  Lihat semua request cuti & perubahan libur minggu ini\n\n"
            "▸ /jadwal\n"
            "  Generate & kirim PDF jadwal minggu ini\n\n"
            "⏱ /startovertime\n"
            "  Lihat daftar perintah untuk fitur Overtime"
        )
    else:
        msg = (
            "☕ Bot Jadwal Café Retri\n\n"
            "Untuk request cuti, hubungi owner atau admin."
        )
    await update.message.reply_text(msg)


# ─────────────────────────────────────────────
#  COMMAND: /cuti — request cuti karyawan
# ─────────────────────────────────────────────
async def cuti(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Perintah ini hanya untuk admin.")
        return
    if len(context.args) < 2:
        await update.message.reply_text(
            "Format: /cuti [nama] [hari]\n"
            "Contoh: /cuti ucil minggu"
        )
        return

    nama = next((n for n in SEMUA_KARYAWAN if n.lower() == context.args[0].lower()), None)
    hari = context.args[1].lower()

    if not nama:
        await update.message.reply_text(
            f"❌ Nama tidak dikenal.\n"
            f"Pilihan: {', '.join(SEMUA_KARYAWAN)}"
        )
        return
    if hari not in HARI_VALID:
        await update.message.reply_text(
            f"❌ Hari tidak valid.\n"
            f"Pilihan: {', '.join(HARI_VALID)}"
        )
        return

    week_key  = get_week_key()
    all_data  = load_data()
    week_data = all_data.get(week_key, {})
    tim       = "barista" if nama in BARISTA else "chef"

    libur_tetap_map = LIBUR_TETAP_BARISTA if tim == "barista" else LIBUR_TETAP_CHEF
    dibatalkan      = week_data.get("batal_libur_tetap", [])

    # Cek: hari ini sudah libur tetap karyawan tersebut (dan belum dibatalkan)
    libur_tetap = libur_tetap_map.get(hari)
    if libur_tetap == nama and f"{hari}_{nama}" not in dibatalkan:
        await update.message.reply_text(
            f"ℹ️ {nama} sudah libur tetap di hari {hari.capitalize()}.\n"
            f"Tidak perlu request cuti."
        )
        return

    # Cek: sudah ada karyawan lain yang tidak masuk di hari itu (tim yang sama)
    tidak_masuk = siapa_tidak_masuk(hari, week_data, tim=tim)
    if tidak_masuk:
        konflik = tidak_masuk[0]
        # Cari hari alternatif yang kosong untuk nama ini
        hari_tersedia = []
        for h in HARI_VALID:
            tm = siapa_tidak_masuk(h, week_data, tim=tim)
            lt = libur_tetap_map.get(h)
            if lt == nama:
                continue  # Hari libur tetap dia sendiri, skip
            if not tm and h != hari:
                hari_tersedia.append(h.capitalize())
        saran = (
            f"\n\n💡 Hari yang tersedia untuk cuti {nama}:\n"
            f"{', '.join(hari_tersedia)}"
        ) if hari_tersedia else ""
        await update.message.reply_text(
            f"❌ {konflik} sudah tidak masuk di {hari.capitalize()}.\n"
            f"Maksimal 1 karyawan cuti/libur per hari per tim.{saran}"
        )
        return

    # Cek sisa jatah cuti tahunan
    jatah = load_jatah_cuti()
    sisa_jatah = jatah.get(nama, JATAH_CUTI_DEFAULT)
    if sisa_jatah <= 0:
        await update.message.reply_text(
            f"❌ Jatah cuti {nama} sudah habis (0 tersisa dari {JATAH_CUTI_DEFAULT}/tahun).\n"
            f"Gunakan /setjatah {nama.lower()} [jumlah] kalau mau menambah manual."
        )
        return

    # Simpan request cuti
    week_data.setdefault("cuti", {}).setdefault(nama, [])
    if hari in week_data["cuti"][nama]:
        await update.message.reply_text(
            f"ℹ️ {nama} sudah punya request cuti di {hari.capitalize()}."
        )
        return

    week_data["cuti"][nama].append(hari)
    all_data[week_key] = week_data
    save_data(all_data)
    sisa_setelah = kurangi_jatah_cuti(nama)

    await update.message.reply_text(
        f"✅ Cuti {hari.capitalize()} untuk {nama} berhasil dicatat!\n"
        f"📋 Sisa jatah cuti {nama}: {sisa_setelah}/{JATAH_CUTI_DEFAULT} tahun ini.\n"
        f"Generating jadwal..."
    )
    await kirim_pdf(update, context)


# ─────────────────────────────────────────────
#  COMMAND: /batalcuti — batalkan request cuti
# ─────────────────────────────────────────────
async def batalcuti(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Perintah ini hanya untuk admin.")
        return
    if len(context.args) < 2:
        await update.message.reply_text(
            "Format: /batalcuti [nama] [hari]\n"
            "Contoh: /batalcuti ucil minggu"
        )
        return

    nama = next((n for n in SEMUA_KARYAWAN if n.lower() == context.args[0].lower()), None)
    hari = context.args[1].lower()

    if not nama:
        await update.message.reply_text("❌ Nama tidak dikenal.")
        return

    week_key  = get_week_key()
    all_data  = load_data()
    week_data = all_data.get(week_key, {})

    if hari not in week_data.get("cuti", {}).get(nama, []):
        await update.message.reply_text(
            f"ℹ️ Tidak ada request cuti {hari.capitalize()} untuk {nama}."
        )
        return

    week_data["cuti"][nama].remove(hari)
    if not week_data["cuti"][nama]:
        del week_data["cuti"][nama]
    all_data[week_key] = week_data
    save_data(all_data)
    sisa_setelah = kembalikan_jatah_cuti(nama)

    await update.message.reply_text(
        f"✅ Request cuti {hari.capitalize()} untuk {nama} dibatalkan.\n"
        f"📋 Sisa jatah cuti {nama}: {sisa_setelah}/{JATAH_CUTI_DEFAULT} tahun ini.\n"
        f"Generating jadwal..."
    )
    await kirim_pdf(update, context)


# ─────────────────────────────────────────────
#  COMMAND: /cekjatah — cek sisa jatah cuti tahunan
# ─────────────────────────────────────────────
async def cekjatah(update: Update, context: ContextTypes.DEFAULT_TYPE):
    jatah = load_jatah_cuti()

    if context.args:
        nama = next((n for n in SEMUA_KARYAWAN if n.lower() == context.args[0].lower()), None)
        if not nama:
            await update.message.reply_text(
                f"❌ Nama tidak dikenal.\n"
                f"Pilihan: {', '.join(SEMUA_KARYAWAN)}"
            )
            return
        sisa = jatah.get(nama, JATAH_CUTI_DEFAULT)
        await update.message.reply_text(
            f"📋 Sisa jatah cuti {nama}: {sisa}/{JATAH_CUTI_DEFAULT} tahun ini."
        )
        return

    lines = ["📋 Sisa jatah cuti tahun ini:\n"]
    lines.append("*Barista:*")
    for nama in BARISTA:
        sisa = jatah.get(nama, JATAH_CUTI_DEFAULT)
        lines.append(f"• {nama}: {sisa}/{JATAH_CUTI_DEFAULT}")
    lines.append("\n*Chef:*")
    for nama in CHEF:
        sisa = jatah.get(nama, JATAH_CUTI_DEFAULT)
        lines.append(f"• {nama}: {sisa}/{JATAH_CUTI_DEFAULT}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ─────────────────────────────────────────────
#  COMMAND: /setjatah — set/reset jatah cuti manual (admin)
# ─────────────────────────────────────────────
async def setjatah(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Perintah ini hanya untuk admin.")
        return
    if len(context.args) < 2:
        await update.message.reply_text(
            "Format: /setjatah [nama] [jumlah]\n"
            "Contoh: /setjatah ucil 12\n\n"
            "Tips: /setjatah semua [jumlah] untuk reset semua karyawan sekaligus."
        )
        return

    nama_input = context.args[0].lower()
    try:
        jumlah = int(context.args[1])
    except ValueError:
        await update.message.reply_text("❌ Jumlah harus berupa angka.")
        return
    if jumlah < 0:
        await update.message.reply_text("❌ Jumlah tidak boleh negatif.")
        return

    jatah = load_jatah_cuti()

    if nama_input == "semua":
        for nama in SEMUA_KARYAWAN:
            jatah[nama] = jumlah
        save_jatah_cuti(jatah)
        await update.message.reply_text(
            f"✅ Jatah cuti SEMUA karyawan di-set jadi {jumlah}."
        )
        return

    nama = next((n for n in SEMUA_KARYAWAN if n.lower() == nama_input), None)
    if not nama:
        await update.message.reply_text(
            f"❌ Nama tidak dikenal.\n"
            f"Pilihan: {', '.join(SEMUA_KARYAWAN)}, atau 'semua'"
        )
        return

    jatah[nama] = jumlah
    save_jatah_cuti(jatah)
    await update.message.reply_text(
        f"✅ Jatah cuti {nama} di-set jadi {jumlah}."
    )


# ─────────────────────────────────────────────
#  COMMAND: /batallibur — batalkan libur tetap
#  (karyawan jadi masuk di hari itu)
# ─────────────────────────────────────────────
async def batallibur(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Perintah ini hanya untuk admin.")
        return
    if not context.args:
        await update.message.reply_text(
            "Format: /batallibur [hari] [tim]\n"
            "Contoh: /batallibur senin barista\n"
            "        /batallibur rabu chef\n"
            "        /batallibur senin  ← batalkan semua tim di hari itu"
        )
        return

    hari       = context.args[0].lower()
    tim_filter = context.args[1].lower() if len(context.args) > 1 else "semua"

    if hari not in HARI_VALID:
        await update.message.reply_text("❌ Hari tidak valid.")
        return
    if tim_filter not in ("barista", "chef", "semua"):
        await update.message.reply_text("❌ Tim tidak valid. Pilihan: barista / chef")
        return

    # Kumpulkan karyawan yang punya libur tetap di hari ini sesuai filter
    kandidat = []
    if tim_filter in ("barista", "semua"):
        lt = LIBUR_TETAP_BARISTA.get(hari)
        if lt: kandidat.append(lt)
    if tim_filter in ("chef", "semua"):
        lt = LIBUR_TETAP_CHEF.get(hari)
        if lt: kandidat.append(lt)

    if not kandidat:
        await update.message.reply_text(
            f"ℹ️ Tidak ada libur tetap di {hari.capitalize()} untuk tim yang dipilih."
        )
        return

    week_key   = get_week_key()
    all_data   = load_data()
    week_data  = all_data.get(week_key, {})
    dibatalkan = week_data.get("batal_libur_tetap", [])

    msg_parts = []
    for nama in kandidat:
        key = f"{hari}_{nama}"
        if key in dibatalkan:
            msg_parts.append(
                f"ℹ️ Libur tetap {nama} di {hari.capitalize()} sudah dibatalkan sebelumnya."
            )
        else:
            dibatalkan.append(key)
            msg_parts.append(
                f"✅ Libur tetap {nama} dibatalkan → {nama} masuk di {hari.capitalize()} (shift 09:30)."
            )

    week_data["batal_libur_tetap"] = dibatalkan
    all_data[week_key] = week_data
    save_data(all_data)

    await update.message.reply_text("\n".join(msg_parts) + "\nGenerating jadwal...")
    await kirim_pdf(update, context)


# ─────────────────────────────────────────────
#  COMMAND: /pulihkanlibur — kembalikan libur tetap
#  yang sebelumnya dibatalkan
# ─────────────────────────────────────────────
async def pulihkanlibur(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Perintah ini hanya untuk admin.")
        return
    if not context.args:
        await update.message.reply_text(
            "Format: /pulihkanlibur [hari] [tim]\n"
            "Contoh: /pulihkanlibur senin barista"
        )
        return

    hari       = context.args[0].lower()
    tim_filter = context.args[1].lower() if len(context.args) > 1 else "semua"

    if hari not in HARI_VALID:
        await update.message.reply_text("❌ Hari tidak valid.")
        return
    if tim_filter not in ("barista", "chef", "semua"):
        await update.message.reply_text("❌ Tim tidak valid. Pilihan: barista / chef")
        return

    kandidat = []
    if tim_filter in ("barista", "semua"):
        lt = LIBUR_TETAP_BARISTA.get(hari)
        if lt: kandidat.append(lt)
    if tim_filter in ("chef", "semua"):
        lt = LIBUR_TETAP_CHEF.get(hari)
        if lt: kandidat.append(lt)

    if not kandidat:
        await update.message.reply_text(
            f"ℹ️ Tidak ada libur tetap di {hari.capitalize()} untuk tim yang dipilih."
        )
        return

    week_key   = get_week_key()
    all_data   = load_data()
    week_data  = all_data.get(week_key, {})
    dibatalkan = week_data.get("batal_libur_tetap", [])

    msg_parts = []
    for nama in kandidat:
        key = f"{hari}_{nama}"
        if key not in dibatalkan:
            msg_parts.append(
                f"ℹ️ Libur tetap {nama} di {hari.capitalize()} belum pernah dibatalkan."
            )
        else:
            dibatalkan.remove(key)
            msg_parts.append(
                f"✅ Libur tetap {nama} di {hari.capitalize()} dipulihkan kembali."
            )

    week_data["batal_libur_tetap"] = dibatalkan
    all_data[week_key] = week_data
    save_data(all_data)

    await update.message.reply_text("\n".join(msg_parts) + "\nGenerating jadwal...")
    await kirim_pdf(update, context)


# ─────────────────────────────────────────────
#  COMMAND: /pindahlibur — pindah hari libur tetap
#  Bukan cuti, ini geser hari libur tetap ke hari lain
# ─────────────────────────────────────────────
async def pindahlibur(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Perintah ini hanya untuk admin.")
        return
    if len(context.args) < 2:
        await update.message.reply_text(
            "Format: /pindahlibur [nama] [hari_baru]\n"
            "Contoh: /pindahlibur yuyu kamis\n\n"
            "Libur tetap karyawan dipindah ke hari lain untuk minggu ini.\n"
            "Hari aslinya dia masuk, hari baru dia libur."
        )
        return

    nama     = next((n for n in SEMUA_KARYAWAN if n.lower() == context.args[0].lower()), None)
    hari_baru = context.args[1].lower()

    if not nama:
        await update.message.reply_text(f"❌ Nama tidak dikenal.\nPilihan: {', '.join(SEMUA_KARYAWAN)}")
        return
    if hari_baru not in HARI_VALID:
        await update.message.reply_text(f"❌ Hari tidak valid.\nPilihan: {', '.join(HARI_VALID)}")
        return

    tim             = "barista" if nama in BARISTA else "chef"
    libur_tetap_map = LIBUR_TETAP_BARISTA if tim == "barista" else LIBUR_TETAP_CHEF

    # Cari hari libur tetap asli karyawan ini
    hari_asli = next((h for h, n in libur_tetap_map.items() if n == nama), None)
    if not hari_asli:
        await update.message.reply_text(f"ℹ️ {nama} tidak punya libur tetap mingguan.")
        return
    if hari_baru == hari_asli:
        await update.message.reply_text(f"ℹ️ {nama} memang sudah libur di {hari_asli.capitalize()}.")
        return

    week_key  = get_week_key()
    all_data  = load_data()
    week_data = all_data.get(week_key, {})

    # Cek: sudah ada karyawan lain yang tidak masuk di hari_baru (tim yang sama)
    tidak_masuk_di_hari_baru = siapa_tidak_masuk(hari_baru, week_data, tim=tim)
    # Filter: keluarkan nama itu sendiri dari pengecekan (kalau sebelumnya udah dipindah ke sini)
    konflik = [n for n in tidak_masuk_di_hari_baru if n != nama]
    if konflik:
        await update.message.reply_text(
            f"❌ {konflik[0]} sudah tidak masuk di {hari_baru.capitalize()}.\n"
            f"Maksimal 1 karyawan libur per hari per tim.\n\n"
            f"💡 Hari libur asli {nama}: {hari_asli.capitalize()}"
        )
        return

    # Simpan perpindahan libur
    week_data.setdefault("pindah_libur", {})[nama] = hari_baru
    all_data[week_key] = week_data
    save_data(all_data)

    await update.message.reply_text(
        f"✅ Libur {nama} dipindah: {hari_asli.capitalize()} → {hari_baru.capitalize()}\n"
        f"Minggu ini {nama} masuk di {hari_asli.capitalize()} dan libur di {hari_baru.capitalize()}.\n"
        f"Generating jadwal..."
    )
    await kirim_pdf(update, context)


# ─────────────────────────────────────────────
#  COMMAND: /daftarcuti — lihat status minggu ini
# ─────────────────────────────────────────────
async def daftarcuti(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Perintah ini hanya untuk admin.")
        return

    week_data  = get_week_data()
    cuti_req   = week_data.get("cuti", {})
    dibatalkan = week_data.get("batal_libur_tetap", [])

    msg = "📋 Status Minggu Ini:\n\n"

    if cuti_req:
        msg += "Request Cuti yang Disetujui:\n"
        for nama, hari_list in cuti_req.items():
            hari_str = ", ".join(h.capitalize() for h in hari_list)
            msg += f"  • {nama}: {hari_str}\n"
    else:
        msg += "Belum ada request cuti minggu ini.\n"

    pindah_req = week_data.get("pindah_libur", {})
    if pindah_req:
        msg += "\nLibur Tetap yang Dipindah:\n"
        for nama_p, hari_baru_p in pindah_req.items():
            tim_p           = "barista" if nama_p in BARISTA else "chef"
            libur_tetap_map = LIBUR_TETAP_BARISTA if tim_p == "barista" else LIBUR_TETAP_CHEF
            hari_asli_p     = next((h for h, n in libur_tetap_map.items() if n == nama_p), "?")
            msg += f"  • {nama_p}: {hari_asli_p.capitalize()} → {hari_baru_p.capitalize()}\n"
    else:
        msg += "\nTidak ada perpindahan libur minggu ini.\n"

    if dibatalkan:
        msg += "\nLibur Tetap yang Dibatalkan (karyawan jadi masuk):\n"
        for item in dibatalkan:
            hari, nama = item.split("_", 1)
            msg += f"  • {nama} masuk di {hari.capitalize()}\n"

    await update.message.reply_text(msg)


# ─────────────────────────────────────────────
#  COMMAND: /jadwal — generate PDF jadwal
# ─────────────────────────────────────────────
async def jadwal_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Perintah ini hanya untuk admin.")
        return
    await update.message.reply_text("⏳ Generating jadwal, sebentar...")
    await kirim_pdf(update, context)




TARIF_OT = 25_000  # Rp per jam
OT_DATA_FILE = "overtime_data.json"   # data overtime (bulanan)

# ─────────────────────────────────────────────
#  KARYAWAN (reuse BARISTA/CHEF dari bagian jadwal)
# ─────────────────────────────────────────────
SEMUA = BARISTA + CHEF

TIM_LABEL = {n: "Barista" for n in BARISTA}
TIM_LABEL.update({n: "Chef" for n in CHEF})


# ─────────────────────────────────────────────
#  HELPER: DATA STORAGE
# ─────────────────────────────────────────────
def ot_load_data() -> dict:
    if os.path.exists(OT_DATA_FILE):
        with open(OT_DATA_FILE) as f:
            return json.load(f)
    return {}

def ot_save_data(data: dict):
    with open(OT_DATA_FILE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def get_bulan_key():
    return datetime.now().strftime("%Y-%m")

def get_bulan_data() -> dict:
    return ot_load_data().get(get_bulan_key(), {})

def get_saldo(nama: str, all_data: dict = None) -> float:
    """Hitung saldo OT karyawan dari akumulasi semua bulan yang masih tersimpan."""
    if all_data is None:
        all_data = ot_load_data()
    total = 0.0
    for bulan_data in all_data.values():
        for tx in bulan_data.get(nama, {}).get("history", []):
            total += tx["delta"]
    return total

def nama_valid(nama_raw: str):
    return next((n for n in SEMUA if n.lower() == nama_raw.lower()), None)

def fmt_jam(jam: float) -> str:
    if jam == int(jam):
        return f"{int(jam)} jam"
    h = int(jam)
    m = int(round((jam - h) * 60))
    if h == 0:
        return f"{m} menit"
    return f"{h} jam {m} menit"

def fmt_rp(n: float) -> str:
    return f"Rp {int(n):,}".replace(",", ".")


# ─────────────────────────────────────────────
#  HELPER: TAMBAH TRANSAKSI
# ─────────────────────────────────────────────
def catat_transaksi(nama: str, delta: float, keterangan: str):
    """
    delta positif = tambah OT
    delta negatif = kurangi OT (ambil pulang duluan / dibayar)
    """
    all_data  = ot_load_data()
    bulan_key = get_bulan_key()
    all_data.setdefault(bulan_key, {})
    all_data[bulan_key].setdefault(nama, {"history": []})
    all_data[bulan_key][nama]["history"].append({
        "waktu":      datetime.now().strftime("%Y-%m-%d %H:%M"),
        "delta":      delta,
        "keterangan": keterangan,
    })
    ot_save_data(all_data)


# ─────────────────────────────────────────────
#  GENERATE PDF REKAP OT
# ─────────────────────────────────────────────
def generate_pdf_ot(mode: str = "saldo", nama_filter: str = None) -> str:
    """
    mode:
      - "saldo"  → rekap saldo semua karyawan (akhir bulan / kapanpun)
      - "history" → detail history transaksi satu karyawan
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        SimpleDocTemplate, Table, TableStyle,
        Paragraph, Spacer, HRFlowable
    )
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

    # ── Palet (konsisten dengan bot jadwal) ──
    BLACK      = colors.HexColor("#111111")
    DARK_GRAY  = colors.HexColor("#2D2D2D")
    MID_GRAY   = colors.HexColor("#757575")
    LIGHT_GRAY = colors.HexColor("#F7F7F7")
    WHITE      = colors.white
    ACCENT_B   = colors.HexColor("#1A73E8")   # barista
    ACCENT_C   = colors.HexColor("#E8711A")   # chef
    GREEN      = colors.HexColor("#1B8A4E")   # saldo positif
    RED        = colors.HexColor("#D32F2F")   # saldo nol
    AMBER      = colors.HexColor("#E65100")   # highlight
    BORDER     = colors.HexColor("#E0E0E0")
    HEADER_BG  = colors.HexColor("#FAFAFA")
    TODAY_BG   = colors.HexColor("#E8F0FE")

    now    = datetime.now()
    bulan  = now.strftime("%B %Y")
    all_data = ot_load_data()

    pdf_path = f"overtime_rekap_{now.strftime('%Y%m%d_%H%M')}.pdf"
    doc = SimpleDocTemplate(
        pdf_path, pagesize=A4,
        topMargin=1.5*cm, bottomMargin=1.2*cm,
        leftMargin=1.5*cm, rightMargin=1.5*cm
    )

    styles = getSampleStyleSheet()
    def ps(name, **kw):
        return ParagraphStyle(name, parent=styles["Normal"], **kw)

    title_s  = ps("t",   alignment=1, fontName="Helvetica-Bold", fontSize=22, textColor=BLACK,    spaceAfter=3)
    sub_s    = ps("s",   alignment=1, fontName="Helvetica",      fontSize=10, textColor=MID_GRAY, spaceAfter=2)
    gen_s    = ps("g",   alignment=1, fontName="Helvetica",      fontSize=8,  textColor=MID_GRAY)
    c_head   = ps("ch",  alignment=1, fontName="Helvetica-Bold", fontSize=9,  textColor=WHITE)
    c_norm   = ps("cn",  alignment=1, fontName="Helvetica",      fontSize=9,  textColor=DARK_GRAY)
    c_bold   = ps("cb",  alignment=1, fontName="Helvetica-Bold", fontSize=9,  textColor=DARK_GRAY)
    c_green  = ps("cg",  alignment=1, fontName="Helvetica-Bold", fontSize=9,  textColor=GREEN)
    c_red    = ps("cr",  alignment=1, fontName="Helvetica-Bold", fontSize=9,  textColor=RED)
    c_amber  = ps("ca",  alignment=1, fontName="Helvetica-Bold", fontSize=9,  textColor=AMBER)
    c_left   = ps("cl",  alignment=0, fontName="Helvetica",      fontSize=9,  textColor=DARK_GRAY)
    c_leg    = ps("leg", alignment=1, fontName="Helvetica",      fontSize=7,  textColor=MID_GRAY)
    c_sum    = ps("csum",alignment=1, fontName="Helvetica-Bold", fontSize=10, textColor=WHITE)

    pw = A4[0] - 3*cm

    def section_header(label, accent):
        t = Table(
            [[Paragraph(f"<b>{label}</b>",
              ps("sh", fontName="Helvetica-Bold", fontSize=10, textColor=WHITE))]],
            colWidths=[pw]
        )
        t.setStyle(TableStyle([
            ("BACKGROUND",    (0,0), (-1,-1), accent),
            ("LEFTPADDING",   (0,0), (-1,-1), 10),
            ("TOPPADDING",    (0,0), (-1,-1), 6),
            ("BOTTOMPADDING", (0,0), (-1,-1), 6),
        ]))
        return t

    # ── MODE: SALDO SEMUA KARYAWAN ──
    def build_saldo_table(anggota, accent):
        header = [
            Paragraph("NAMA",        c_head),
            Paragraph("SALDO (JAM)", c_head),
            Paragraph("NILAI",       c_head),
            Paragraph("STATUS",      c_head),
        ]
        rows = [header]
        total_jam = 0.0
        total_rp  = 0.0

        for nama in anggota:
            saldo = get_saldo(nama, all_data)
            rp    = saldo * TARIF_OT
            total_jam += saldo
            total_rp  += rp

            if saldo > 0:
                style_saldo  = c_green
                style_rp     = c_green
                status_para  = Paragraph("Ada saldo", c_green)
            elif saldo < 0:
                style_saldo  = c_red
                style_rp     = c_red
                status_para  = Paragraph("Minus ⚠", c_red)
            else:
                style_saldo  = c_norm
                style_rp     = c_norm
                status_para  = Paragraph("Lunas", c_norm)

            rows.append([
                Paragraph(f"<b>{nama}</b>", c_bold),
                Paragraph(fmt_jam(saldo),   style_saldo),
                Paragraph(fmt_rp(rp),       style_rp),
                status_para,
            ])

        # Row total
        rows.append([
            Paragraph("<b>TOTAL</b>",        c_sum),
            Paragraph(fmt_jam(total_jam),    c_sum),
            Paragraph(fmt_rp(total_rp),      c_sum),
            Paragraph(f"{len([n for n in anggota if get_saldo(n,all_data)>0])} orang ada saldo", c_sum),
        ])

        cw = [pw*0.28, pw*0.22, pw*0.25, pw*0.25]
        t  = Table(rows, colWidths=cw, repeatRows=1)
        n_data = len(rows)
        cmds = [
            ("BACKGROUND",    (0,0),     (-1,0),      accent),
            ("BACKGROUND",    (0,n_data-1), (-1,n_data-1), colors.HexColor("#2D2D2D")),
            ("ROWBACKGROUNDS",(1,1),     (-1,n_data-2), [WHITE, LIGHT_GRAY]),
            ("LINEBELOW",     (0,0),     (-1,-1),     0.4, BORDER),
            ("LINEAFTER",     (0,0),     (-1,-1),     0.4, BORDER),
            ("BOX",           (0,0),     (-1,-1),     0.8, BORDER),
            ("ALIGN",         (0,0),     (-1,-1),     "CENTER"),
            ("VALIGN",        (0,0),     (-1,-1),     "MIDDLE"),
            ("TOPPADDING",    (0,0),     (-1,-1),     7),
            ("BOTTOMPADDING", (0,0),     (-1,-1),     7),
        ]
        t.setStyle(TableStyle(cmds))
        return t, total_jam, total_rp

    # ── MODE: HISTORY SATU KARYAWAN ──
    def build_history_table(nama):
        semua_tx = []
        for bk, bd in sorted(all_data.items()):
            for tx in bd.get(nama, {}).get("history", []):
                semua_tx.append((bk, tx))

        if not semua_tx:
            return None, 0.0

        header = [
            Paragraph("TANGGAL",     c_head),
            Paragraph("KETERANGAN",  c_head),
            Paragraph("DELTA",       c_head),
            Paragraph("SALDO",       c_head),
        ]
        rows   = [header]
        saldo_run = 0.0

        for _, tx in semua_tx:
            saldo_run += tx["delta"]
            delta = tx["delta"]
            tgl   = tx["waktu"][:10]

            delta_str = f"+{fmt_jam(delta)}" if delta > 0 else f"-{fmt_jam(abs(delta))}"
            delta_style = c_green if delta > 0 else c_red

            rows.append([
                Paragraph(tgl, c_norm),
                Paragraph(tx["keterangan"], c_left),
                Paragraph(delta_str, delta_style),
                Paragraph(fmt_jam(saldo_run), c_bold if saldo_run > 0 else c_norm),
            ])

        cw = [pw*0.18, pw*0.42, pw*0.20, pw*0.20]
        t  = Table(rows, colWidths=cw, repeatRows=1)
        n_data = len(rows)
        cmds = [
            ("BACKGROUND",    (0,0),  (-1,0),  ACCENT_B),
            ("ROWBACKGROUNDS",(1,1),  (-1,-1), [WHITE, LIGHT_GRAY]),
            ("LINEBELOW",     (0,0),  (-1,-1), 0.4, BORDER),
            ("LINEAFTER",     (0,0),  (-1,-1), 0.4, BORDER),
            ("BOX",           (0,0),  (-1,-1), 0.8, BORDER),
            ("ALIGN",         (0,0),  (-1,-1), "CENTER"),
            ("VALIGN",        (0,0),  (-1,-1), "MIDDLE"),
            ("TOPPADDING",    (0,0),  (-1,-1), 7),
            ("BOTTOMPADDING", (0,0),  (-1,-1), 7),
        ]
        t.setStyle(TableStyle(cmds))
        return t, saldo_run

    # ── BUILD STORY ──
    story = []

    if mode == "saldo":
        story += [
            Paragraph("Rekap Overtime Café Retri", title_s),
            Paragraph(f"Per {now.strftime('%d %B %Y')}", sub_s),
            Paragraph(f"Dibuat: {now.strftime('%d/%m/%Y %H:%M')}", gen_s),
            Spacer(1, 0.4*cm),
            HRFlowable(width="100%", thickness=1.5, color=ACCENT_B, spaceAfter=4),
            Spacer(1, 0.2*cm),
            section_header("☕  BARISTA", ACCENT_B),
        ]
        tbl_b, jam_b, rp_b = build_saldo_table(BARISTA, ACCENT_B)
        story.append(tbl_b)
        story += [Spacer(1, 0.35*cm), section_header("🍳  CHEF", ACCENT_C)]
        tbl_c, jam_c, rp_c = build_saldo_table(CHEF, ACCENT_C)
        story.append(tbl_c)

        # Summary box
        story += [Spacer(1, 0.5*cm)]
        total_all_jam = jam_b + jam_c
        total_all_rp  = rp_b + rp_c
        sum_data = [[
            Paragraph("TOTAL SEMUA KARYAWAN", ps("st", alignment=1, fontName="Helvetica-Bold", fontSize=10, textColor=WHITE)),
            Paragraph(fmt_jam(total_all_jam), ps("sv", alignment=1, fontName="Helvetica-Bold", fontSize=10, textColor=WHITE)),
            Paragraph(fmt_rp(total_all_rp),   ps("sr", alignment=1, fontName="Helvetica-Bold", fontSize=10, textColor=AMBER)),
        ]]
        sum_t = Table(sum_data, colWidths=[pw*0.5, pw*0.25, pw*0.25])
        sum_t.setStyle(TableStyle([
            ("BACKGROUND",    (0,0), (-1,-1), colors.HexColor("#111111")),
            ("ALIGN",         (0,0), (-1,-1), "CENTER"),
            ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
            ("TOPPADDING",    (0,0), (-1,-1), 10),
            ("BOTTOMPADDING", (0,0), (-1,-1), 10),
            ("BOX",           (0,0), (-1,-1), 0.8, BORDER),
        ]))
        story.append(sum_t)

        story += [
            Spacer(1, 0.3*cm),
            HRFlowable(width="100%", thickness=0.5, color=BORDER),
            Spacer(1, 0.1*cm),
            Paragraph(f"Tarif overtime: {fmt_rp(TARIF_OT)}/jam  ·  Saldo = akumulasi semua bulan belum dibayar", c_leg),
        ]

    elif mode == "history_all":
        story += [
            Paragraph("History Overtime — Semua Karyawan", title_s),
            Paragraph(f"Per {now.strftime('%d %B %Y')}", sub_s),
            Paragraph(f"Dibuat: {now.strftime('%d/%m/%Y %H:%M')}", gen_s),
            Spacer(1, 0.4*cm),
            HRFlowable(width="100%", thickness=1.5, color=ACCENT_B, spaceAfter=4),
            Spacer(1, 0.2*cm),
        ]

        def tambah_section(nama, accent):
            saldo_kini = get_saldo(nama, all_data)
            story.append(section_header(f"{nama}  ({TIM_LABEL.get(nama,'')})  ·  Saldo: {fmt_jam(saldo_kini)} ({fmt_rp(saldo_kini * TARIF_OT)})", accent))
            tbl, _ = build_history_table(nama)
            if tbl:
                story.append(tbl)
            else:
                story.append(Paragraph("Belum ada transaksi.", c_norm))
            story.append(Spacer(1, 0.3*cm))

        story.append(Paragraph("☕  BARISTA", ps("grp", fontName="Helvetica-Bold", fontSize=12, textColor=BLACK, spaceAfter=6)))
        for n in BARISTA:
            tambah_section(n, ACCENT_B)

        story.append(Paragraph("🍳  CHEF", ps("grp2", fontName="Helvetica-Bold", fontSize=12, textColor=BLACK, spaceAfter=6)))
        for n in CHEF:
            tambah_section(n, ACCENT_C)

        story += [
            HRFlowable(width="100%", thickness=0.5, color=BORDER),
            Spacer(1, 0.1*cm),
            Paragraph(f"Tarif overtime: {fmt_rp(TARIF_OT)}/jam  ·  + = tambah OT  ·  - = ambil/bayar OT", c_leg),
        ]

    elif mode == "history" and nama_filter:
        tim = TIM_LABEL.get(nama_filter, "")
        accent = ACCENT_B if tim == "Barista" else ACCENT_C
        saldo_kini = get_saldo(nama_filter, all_data)

        story += [
            Paragraph(f"History Overtime — {nama_filter}", title_s),
            Paragraph(f"Tim {tim}  ·  Saldo sekarang: {fmt_jam(saldo_kini)}  ({fmt_rp(saldo_kini * TARIF_OT)})", sub_s),
            Paragraph(f"Dibuat: {now.strftime('%d/%m/%Y %H:%M')}", gen_s),
            Spacer(1, 0.4*cm),
            HRFlowable(width="100%", thickness=1.5, color=accent, spaceAfter=4),
            Spacer(1, 0.2*cm),
            section_header(f"📋  RIWAYAT TRANSAKSI — {nama_filter.upper()}", accent),
        ]
        tbl, _ = build_history_table(nama_filter)
        if tbl:
            story.append(tbl)
        else:
            story.append(Paragraph("Belum ada transaksi.", c_norm))

        story += [
            Spacer(1, 0.3*cm),
            HRFlowable(width="100%", thickness=0.5, color=BORDER),
            Spacer(1, 0.1*cm),
            Paragraph(f"Tarif overtime: {fmt_rp(TARIF_OT)}/jam  ·  + = tambah OT  ·  - = ambil/bayar OT", c_leg),
        ]

    doc.build(story)
    return pdf_path


# ─────────────────────────────────────────────
#  HELPER: KIRIM PDF
# ─────────────────────────────────────────────
async def kirim_pdf_saldo(update, caption=""):
    pdf = generate_pdf_ot(mode="saldo")
    with open(pdf, "rb") as f:
        await update.message.reply_document(
            document=f,
            filename=f"OT_Rekap_{datetime.now().strftime('%d%b%Y')}.pdf",
            caption=caption or f"📊 Rekap Overtime Café Retri — {datetime.now().strftime('%d %B %Y')}"
        )

async def kirim_pdf_history(update):
    pdf = generate_pdf_ot(mode="history_all")
    with open(pdf, "rb") as f:
        await update.message.reply_document(
            document=f,
            filename=f"OT_History_Semua_{datetime.now().strftime('%d%b%Y')}.pdf",
            caption=f"📋 History Overtime Semua Karyawan — {datetime.now().strftime('%d %B %Y')}"
        )


# ─────────────────────────────────────────────
#  HANDLER: FILE ABSENSI MASUK (.TXT)
# ─────────────────────────────────────────────
async def terima_file_absensi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Dipicu saat admin kirim file .TXT (raw scan log absensi) ke bot.
    Otomatis: download → parse → generate PDF → kirim balik ke chat yang sama.
    """
    if not is_admin(update.effective_user.id):
        return  # diam saja kalau bukan admin, biar ga ganggu chat lain

    doc = update.message.document
    if not doc or not doc.file_name.lower().endswith(".txt"):
        return  # bukan file txt, abaikan (biar ga bentrok sama file lain)

    status_msg = await update.message.reply_text("⏳ File absensi diterima, memproses...")

    try:
        tg_file    = await doc.get_file()
        file_bytes = bytes(await tg_file.download_as_bytearray())

        records = parse_absensi_txt(file_bytes)
        if not records:
            await status_msg.edit_text("❌ Tidak ada data yang bisa dibaca dari file ini. Cek format file-nya.")
            return

        pdf_path = generate_pdf_absensi(records)
        ringkasan = rekap_ringkas(records)

        with open(pdf_path, "rb") as f:
            await update.message.reply_document(
                document=f,
                filename=f"Laporan_Absensi_{datetime.now().strftime('%d%b%Y')}.pdf",
                caption=f"📄 Laporan absensi otomatis dari {doc.file_name}\n\n{ringkasan}"
            )
        await status_msg.delete()

    except Exception as e:
        logger.exception("Gagal proses file absensi")
        await status_msg.edit_text(f"❌ Gagal memproses file: {e}")


# ─────────────────────────────────────────────
#  COMMAND: /start
# ─────────────────────────────────────────────
async def start_overtime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if is_admin(uid):
        msg = (
            "⏱ Bot Overtime Café Retri — ADMIN\n\n"
            "📋 Perintah:\n\n"
            "▸ /ot [nama] [jam]\n"
            "  Tambah overtime\n"
            "  Contoh: /ot krisna 1\n"
            "  Contoh: /ot krisna 1.5  (1 jam 30 menit)\n\n"
            "▸ /ambilot [nama] [jam] [keterangan]\n"
            "  Kurangi OT (pulang duluan / dibayar cash)\n"
            "  Contoh: /ambilot krisna 1 pulang duluan\n"
            "  Contoh: /ambilot krisna 2 dibayar cash\n\n"
            "▸ /saldo [nama]\n"
            "  Cek saldo OT satu karyawan\n"
            "  Contoh: /saldo krisna\n\n"
            "▸ /semuasaldo\n"
            "  Lihat saldo semua karyawan (teks)\n\n"
            "▸ /rekap\n"
            "  Generate PDF rekap saldo semua karyawan\n\n"
            "▸ /history\n"
            "  Generate PDF history transaksi SEMUA karyawan sekaligus\n\n"
            "▸ /tutupbulan\n"
            "  Bayar semua saldo OT → saldo jadi 0 & generate PDF rekap final\n\n"
            "▸ Kirim file .TXT (scan log absensi)\n"
            "  Bot otomatis parse & kirim balik PDF laporan absensi\n\n"
            f"👥 Karyawan: {', '.join(SEMUA)}"
        )
    else:
        msg = "⏱ Bot Overtime Café Retri\nHubungi admin untuk informasi overtime kamu."
    await update.message.reply_text(msg)


# ─────────────────────────────────────────────
#  COMMAND: /ot — tambah overtime
# ─────────────────────────────────────────────
async def tambah_ot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Hanya admin.")
        return
    if len(context.args) < 2:
        await update.message.reply_text(
            "Format: /ot [nama] [jam]\n"
            "Contoh: /ot krisna 1\n"
            "        /ot krisna 1.5"
        )
        return

    nama = nama_valid(context.args[0])
    if not nama:
        await update.message.reply_text(
            f"❌ Nama tidak dikenal.\nPilihan: {', '.join(SEMUA)}"
        )
        return

    try:
        jam = float(context.args[1])
        assert jam > 0
    except:
        await update.message.reply_text("❌ Jam harus angka positif. Contoh: 1 atau 1.5")
        return

    ket = " ".join(context.args[2:]) if len(context.args) > 2 else "Overtime"
    catat_transaksi(nama, jam, ket)
    saldo_baru = get_saldo(nama)

    await update.message.reply_text(
        f"✅ OT {nama} +{fmt_jam(jam)}\n"
        f"📊 Saldo sekarang: {fmt_jam(saldo_baru)} ({fmt_rp(saldo_baru * TARIF_OT)})"
    )


# ─────────────────────────────────────────────
#  COMMAND: /ambilot — kurangi overtime
# ─────────────────────────────────────────────
async def ambil_ot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Hanya admin.")
        return
    if len(context.args) < 2:
        await update.message.reply_text(
            "Format: /ambilot [nama] [jam] [keterangan opsional]\n"
            "Contoh: /ambilot krisna 1 pulang duluan\n"
            "        /ambilot krisna 2 dibayar cash"
        )
        return

    nama = nama_valid(context.args[0])
    if not nama:
        await update.message.reply_text(
            f"❌ Nama tidak dikenal.\nPilihan: {', '.join(SEMUA)}"
        )
        return

    try:
        jam = float(context.args[1])
        assert jam > 0
    except:
        await update.message.reply_text("❌ Jam harus angka positif.")
        return

    saldo = get_saldo(nama)
    if jam > saldo:
        await update.message.reply_text(
            f"❌ Saldo {nama} hanya {fmt_jam(saldo)}. Tidak bisa ambil {fmt_jam(jam)}."
        )
        return

    ket = " ".join(context.args[2:]) if len(context.args) > 2 else "Ambil OT"
    catat_transaksi(nama, -jam, ket)
    saldo_baru = get_saldo(nama)

    await update.message.reply_text(
        f"✅ OT {nama} -{fmt_jam(jam)} ({ket})\n"
        f"📊 Saldo sekarang: {fmt_jam(saldo_baru)} ({fmt_rp(saldo_baru * TARIF_OT)})"
    )


# ─────────────────────────────────────────────
#  COMMAND: /saldo — cek saldo satu orang
# ─────────────────────────────────────────────
async def saldo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Hanya admin.")
        return
    if not context.args:
        await update.message.reply_text("Format: /saldo [nama]\nContoh: /saldo krisna")
        return

    nama = nama_valid(context.args[0])
    if not nama:
        await update.message.reply_text(f"❌ Nama tidak dikenal.\nPilihan: {', '.join(SEMUA)}")
        return

    s = get_saldo(nama)
    tim = TIM_LABEL.get(nama, "")
    await update.message.reply_text(
        f"📊 Saldo OT {nama} ({tim})\n"
        f"⏱ {fmt_jam(s)}\n"
        f"💵 {fmt_rp(s * TARIF_OT)}"
    )


# ─────────────────────────────────────────────
#  COMMAND: /semuasaldo — lihat semua saldo (teks)
# ─────────────────────────────────────────────
async def semua_saldo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Hanya admin.")
        return

    all_data = ot_load_data()
    lines = [f"📊 Saldo OT — {datetime.now().strftime('%d %B %Y')}\n"]

    lines.append("☕ BARISTA:")
    total_b = 0.0
    for n in BARISTA:
        s = get_saldo(n, all_data)
        total_b += s
        icon = "✅" if s > 0 else "—"
        lines.append(f"  {icon} {n}: {fmt_jam(s)} ({fmt_rp(s * TARIF_OT)})")

    lines.append(f"\n🍳 CHEF:")
    total_c = 0.0
    for n in CHEF:
        s = get_saldo(n, all_data)
        total_c += s
        icon = "✅" if s > 0 else "—"
        lines.append(f"  {icon} {n}: {fmt_jam(s)} ({fmt_rp(s * TARIF_OT)})")

    total = total_b + total_c
    lines.append(f"\n💵 Total wajib bayar: {fmt_rp(total * TARIF_OT)}")

    await update.message.reply_text("\n".join(lines))


# ─────────────────────────────────────────────
#  COMMAND: /rekap — generate PDF saldo semua
# ─────────────────────────────────────────────
async def rekap(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Hanya admin.")
        return
    await update.message.reply_text("⏳ Generating PDF rekap...")
    await kirim_pdf_saldo(update)


# ─────────────────────────────────────────────
#  COMMAND: /history — PDF history satu karyawan
# ─────────────────────────────────────────────
async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Hanya admin.")
        return

    await update.message.reply_text("⏳ Generating PDF history semua karyawan...")
    await kirim_pdf_history(update)


# ─────────────────────────────────────────────
#  COMMAND: /tutupbulan — bayar semua OT → saldo 0
# ─────────────────────────────────────────────
async def tutup_bulan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Hanya admin.")
        return

    all_data = ot_load_data()
    ada_saldo = [(n, get_saldo(n, all_data)) for n in SEMUA if get_saldo(n, all_data) > 0]

    if not ada_saldo:
        await update.message.reply_text("ℹ️ Semua saldo sudah 0. Tidak ada yang perlu dibayar.")
        return

    await update.message.reply_text("⏳ Generating PDF final & menutup bulan...")
    # Generate PDF dulu sebelum di-reset
    await kirim_pdf_saldo(update, caption=f"📊 REKAP FINAL — {datetime.now().strftime('%B %Y')} (sebelum tutup buku)")

    # Reset semua saldo: catat transaksi -saldo untuk yang punya saldo
    lines = [f"✅ Tutup bulan {datetime.now().strftime('%B %Y')}:\n"]
    for nama, s in ada_saldo:
        ket = f"Bayar cash tutup bulan {datetime.now().strftime('%B %Y')}"
        catat_transaksi(nama, -s, ket)
        lines.append(f"  • {nama}: dibayar {fmt_rp(s * TARIF_OT)}")

    total = sum(s for _, s in ada_saldo)
    lines.append(f"\n💵 Total dibayar: {fmt_rp(total * TARIF_OT)}")
    lines.append("📌 Saldo semua karyawan kini = 0")

    await update.message.reply_text("\n".join(lines))




# ─────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # ── Command jadwal ──
    app.add_handler(CommandHandler("start",         start))
    app.add_handler(CommandHandler("cuti",          cuti))
    app.add_handler(CommandHandler("batalcuti",     batalcuti))
    app.add_handler(CommandHandler("cekjatah",      cekjatah))
    app.add_handler(CommandHandler("setjatah",      setjatah))
    app.add_handler(CommandHandler("pindahlibur",   pindahlibur))
    app.add_handler(CommandHandler("batallibur",    batallibur))
    app.add_handler(CommandHandler("pulihkanlibur", pulihkanlibur))
    app.add_handler(CommandHandler("daftarcuti",    daftarcuti))
    app.add_handler(CommandHandler("jadwal",        jadwal_cmd))

    # ── Command overtime ──
    app.add_handler(CommandHandler("startovertime", start_overtime))
    app.add_handler(CommandHandler("ot",            tambah_ot))
    app.add_handler(CommandHandler("ambilot",       ambil_ot))
    app.add_handler(CommandHandler("saldo",         saldo))
    app.add_handler(CommandHandler("semuasaldo",    semua_saldo))
    app.add_handler(CommandHandler("rekap",         rekap))
    app.add_handler(CommandHandler("history",       history))
    app.add_handler(CommandHandler("tutupbulan",    tutup_bulan))

    # ── Handler file absensi (.txt) ──
    app.add_handler(MessageHandler(filters.Document.ALL, terima_file_absensi))

    logger.info("Bot Café Retri (Jadwal + Overtime) berjalan...")
    app.run_polling()


if __name__ == "__main__":
    main()

"""
Cafe Schedule Bot
- 4 orang masuk = 2 shift (06:30 & 09:30), pasangan random
- 3 orang masuk (ada OFF) = 3 shift (06:30, 08:30, 09:30)
- Admin bisa cancel OFF → hari otomatis jadi 2 shift
- Admin bisa request libur tambahan
- Max 1 karyawan libur per hari
"""

import os, json, random, logging
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
REQUESTS_FILE = "libur_requests.json"
_raw_ids = os.environ.get("ADMIN_IDS", "").strip()
ADMIN_IDS = [int(x.strip()) for x in _raw_ids.split(",") if x.strip().isdigit()]

HARI_VALID = ["senin", "selasa", "rabu", "kamis", "jumat", "sabtu", "minggu"]

# === TIM BARISTA ===
BARISTA = ["Dian", "Yuyu", "Krisna", "Ayuk"]
PASANGAN_BARISTA = [["Krisna", "Dian"], ["Ayuk", "Yuyu"]]
OFF_TETAP_BARISTA = {
    "senin":  "Yuyu",
    "selasa": "Ayuk",
    "rabu":   None,
    "kamis":  None,
    "jumat":  None,
    "sabtu":  "Dian",
    "minggu": "Krisna",
}
SHIFT_3_BARISTA = ["06:30", "08:30", "09:30"]
SHIFT_2_BARISTA = ["06:30", "09:30"]

# Jadwal tetap Barista (fixed, bukan auto-generate)
# Logika: sehari sebelum OFF → 06:30, sehari setelah OFF → 09:30, sisanya → 08:30
# Hari dengan semua masuk (rabu/kamis/jumat) → 2 shift: 06:30 & 09:30
JADWAL_BARISTA = {
    "senin":  {"Dian": "08:30", "Yuyu": "OFF",   "Krisna": "09:30", "Ayuk": "06:30"},
    "selasa": {"Dian": "09:30", "Yuyu": "08:30",  "Krisna": "06:30", "Ayuk": "OFF"},
    "rabu":   {"Dian": "09:30", "Yuyu": "08:30",  "Krisna": "06:30", "Ayuk": "09:30"},
    "kamis":  {"Dian": "06:30", "Yuyu": "06:30",  "Krisna": "09:30", "Ayuk": "09:30"},
    "jumat":  {"Dian": "06:30", "Yuyu": "09:30",  "Krisna": "09:30", "Ayuk": "06:30"},
    "sabtu":  {"Dian": "OFF",   "Yuyu": "08:30",  "Krisna": "06:30", "Ayuk": "09:30"},
    "minggu": {"Dian": "09:30", "Yuyu": "06:30",  "Krisna": "OFF",   "Ayuk": "08:30"},
}

# === TIM CHEF ===
CHEF = ["Adi", "Ucil", "Dito"]
OFF_TETAP_CHEF = {
    "senin":  "Ucil",
    "selasa": None,
    "rabu":   "Adi",
    "kamis":  "Dito",
    "jumat":  None,
    "sabtu":  None,
    "minggu": None,
}
# Jadwal tetap Chef (bukan auto-generate, fixed dari foto)
JADWAL_CHEF = {
    "senin":  {"Adi": "09:30", "Ucil": "OFF", "Dito": "06:30"},
    "selasa": {"Adi": "06:30", "Ucil": "09:30", "Dito": "08:00"},
    "rabu":   {"Adi": "OFF",   "Ucil": "09:30", "Dito": "06:30"},
    "kamis":  {"Adi": "09:30", "Ucil": "06:30", "Dito": "OFF"},
    "jumat":  {"Adi": "08:00", "Ucil": "06:30", "Dito": "09:30"},
    "sabtu":  {"Adi": "09:30", "Ucil": "08:00", "Dito": "06:30"},
    "minggu": {"Adi": "08:00", "Ucil": "06:30", "Dito": "09:30"},
}

# Legacy
NAMA_VALID = BARISTA + CHEF  # untuk validasi command /libur dll
SHIFT_3 = SHIFT_3_BARISTA
SHIFT_2 = SHIFT_2_BARISTA
OFF_TETAP = OFF_TETAP_BARISTA


def is_admin(uid): return uid in ADMIN_IDS

def load_data():
    if os.path.exists(REQUESTS_FILE):
        with open(REQUESTS_FILE) as f:
            return json.load(f)
    return {}

def save_data(data):
    with open(REQUESTS_FILE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def get_target_monday():
    """Kalau hari ini Minggu → return Senin minggu depan. Selainnya → Senin minggu ini."""
    today = datetime.now()
    monday = today - timedelta(days=today.weekday())
    if today.weekday() == 6:  # 6 = Minggu
        monday += timedelta(weeks=1)
    return monday

def get_week_key():
    return get_target_monday().strftime("%Y-W%W")

def get_week_data():
    return load_data().get(get_week_key(), {})

def siapa_off(hari, week_data, tim="barista"):
    """Return nama yang OFF di hari ini (OFF tetap atau request libur)."""
    off_list = []
    cancelled = week_data.get("cancelled_off", [])
    off_tetap_map = OFF_TETAP_BARISTA if tim == "barista" else OFF_TETAP_CHEF
    off_tetap = off_tetap_map.get(hari)
    if off_tetap and f"{hari}_{off_tetap}" not in cancelled:
        off_list.append(off_tetap)
    # Request libur tambahan
    anggota = BARISTA if tim == "barista" else CHEF
    for nama, hari_list in week_data.get("libur", {}).items():
        if nama in anggota and hari in hari_list and nama not in off_list:
            off_list.append(nama)
    return off_list

def hitung_shift_cancel_off(hari, nama_masuk_extra, week_data):
    """
    Saat OFF tetap seseorang di-cancel → dia masuk di hari itu.
    Shiftnya ditentukan dari logika: sehari setelah OFF tetapnya
    (karena dia harusnya OFF hari ini, berarti kemarin = pagi, besok = siang,
    tapi karena dia cancel OFF = masuk hari ini, dia dapat siang/09:30
    karena posisinya adalah 'sehari setelah OFF' dari perspektif minggunya).
    
    Sederhana: kalau cancel OFF → shift siang (09:30), karena dia 'dipanggil masuk'
    di hari yang harusnya OFF.
    """
    return "09:30"


def buat_jadwal_hari(hari, week_data):
    """Barista: Return list {"nama": ..., "jam": ...} untuk hari ini."""
    off_list = siapa_off(hari, week_data, tim="barista")
    cancelled = week_data.get("cancelled_off", [])
    result = []

    for nama in BARISTA:
        jam_base = JADWAL_BARISTA[hari][nama]

        if nama in off_list:
            # OFF (baik tetap atau request libur) → skip
            continue

        # Cek: apakah ini orang yang OFF tetapnya di-cancel (dia harusnya OFF tapi masuk)
        off_tetap = OFF_TETAP_BARISTA.get(hari)
        if off_tetap == nama and f"{hari}_{nama}" in cancelled:
            # Cancel OFF → logika: dia masuk siang (09:30)
            result.append({"nama": nama, "jam": "09:30"})
            continue

        # Cek: ada request libur dari orang lain → shift mungkin perlu adjust
        # Tapi untuk sekarang, kalau ada request libur tambahan → pakai jadwal base dari JADWAL_BARISTA
        # Kalau masuk normal → pakai jam dari jadwal tetap
        if jam_base == "OFF":
            # Harusnya OFF tetap tapi sudah di-cancel → handled di atas
            # Kalau sampai sini, berarti logika salah, skip saja
            continue

        result.append({"nama": nama, "jam": jam_base})

    # Handle request libur tambahan: kalau ada yang request libur di hari ini,
    # shift orang yang masuk ikut logika: yang 'kehilangan teman' tetap pakai jam masing-masing
    # (tidak ada auto-rebalance shift untuk request libur tambahan)
    return result


def buat_jadwal_chef(hari, week_data):
    """
    Chef: Return list {"nama": ..., "jam": ...} untuk hari ini.
    Aturan: kalau ada 1 Chef libur (tinggal 2 orang),
    jam 09:30 otomatis turun jadi 08:30.
    """
    off_list = siapa_off(hari, week_data, tim="chef")
    result = []
    for nama in CHEF:
        jam_tetap = JADWAL_CHEF[hari][nama]
        if nama in off_list:
            continue  # OFF, skip
        # Kalau ada yang libur, turunkan 09:30 → 08:30
        jam_final = "08:30" if (len(off_list) > 0 and jam_tetap == "09:30") else jam_tetap
        result.append({"nama": nama, "jam": jam_final})
    return result


def generate_pdf(week_data):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

    BLACK      = colors.HexColor("#111111")
    DARK_GRAY  = colors.HexColor("#2D2D2D")
    MID_GRAY   = colors.HexColor("#757575")
    LIGHT_GRAY = colors.HexColor("#F7F7F7")
    WHITE      = colors.white
    ACCENT_B   = colors.HexColor("#1A73E8")
    ACCENT_C   = colors.HexColor("#E8711A")
    RED        = colors.HexColor("#D32F2F")
    AMBER      = colors.HexColor("#E65100")
    TODAY_BG   = colors.HexColor("#E8F0FE")
    BORDER     = colors.HexColor("#E0E0E0")
    HEADER_BG  = colors.HexColor("#FAFAFA")

    today  = datetime.now()
    monday = get_target_monday()
    sunday = monday + timedelta(days=6)
    tanggal = {HARI_VALID[i]: (monday + timedelta(days=i)).strftime("%d/%m") for i in range(7)}

    pdf_path = "jadwal_cafe.pdf"
    doc = SimpleDocTemplate(pdf_path, pagesize=A4,
        topMargin=1.5*cm, bottomMargin=1.2*cm, leftMargin=1.5*cm, rightMargin=1.5*cm)

    styles = getSampleStyleSheet()
    def ps(name, **kw):
        return ParagraphStyle(name, parent=styles["Normal"], **kw)

    title_s = ps("t",  alignment=1, fontName="Helvetica-Bold", fontSize=22, textColor=BLACK, spaceAfter=3)
    sub_s   = ps("s",  alignment=1, fontName="Helvetica", fontSize=10, textColor=MID_GRAY, spaceAfter=2)
    gen_s   = ps("g",  alignment=1, fontName="Helvetica", fontSize=8,  textColor=MID_GRAY)
    c_head  = ps("ch", alignment=1, fontName="Helvetica-Bold", textColor=WHITE, fontSize=9)
    c_day   = ps("cd", alignment=1, fontName="Helvetica-Bold", textColor=DARK_GRAY, fontSize=8, leading=11)
    c_norm  = ps("cn", alignment=1, fontName="Helvetica-Bold", fontSize=9, textColor=DARK_GRAY)
    c_off   = ps("co", alignment=1, fontName="Helvetica-Bold", textColor=RED, fontSize=9)
    c_libur = ps("cl", alignment=1, fontName="Helvetica-Bold", textColor=AMBER, fontSize=8)
    c_leg   = ps("leg",alignment=1, fontName="Helvetica", fontSize=7, textColor=MID_GRAY)

    cancelled = week_data.get("cancelled_off", [])
    is_next_week = today.weekday() == 6
    today_row = -1 if is_next_week else (today.weekday() + 1)
    pw = A4[0] - 3*cm

    def section_header(label, accent):
        t = Table([[Paragraph(f"<b>{label}</b>",
                    ps("sh", fontName="Helvetica-Bold", fontSize=10, textColor=WHITE))]], colWidths=[pw])
        t.setStyle(TableStyle([
            ("BACKGROUND",    (0,0), (-1,-1), accent),
            ("LEFTPADDING",   (0,0), (-1,-1), 10),
            ("TOPPADDING",    (0,0), (-1,-1), 6),
            ("BOTTOMPADDING", (0,0), (-1,-1), 6),
        ]))
        return t

    def build_table(anggota, jadwal_fn, off_tetap_map, tim, accent):
        header = [Paragraph("HARI", c_head)] + [Paragraph(n.upper(), c_head) for n in anggota]
        data = [header]
        for hari in HARI_VALID:
            jadwal_hari = jadwal_fn(hari, week_data)
            off_list = siapa_off(hari, week_data, tim=tim)
            row = [Paragraph(
                f"<b>{hari[:3].capitalize()}</b><br/>"
                f"<font size='7' color='#757575'>{tanggal[hari]}</font>", c_day)]
            for nama in anggota:
                if nama in off_list:
                    off_t = off_tetap_map.get(hari)
                    if off_t == nama and f"{hari}_{nama}" not in cancelled:
                        row.append(Paragraph("OFF", c_off))
                    else:
                        row.append(Paragraph("LIBUR", c_libur))
                else:
                    entry = next((j for j in jadwal_hari if j["nama"] == nama), None)
                    row.append(Paragraph(entry["jam"] if entry else "—", c_norm))
            data.append(row)

        n = len(anggota)
        cw = [2.2*cm] + [(pw - 2.2*cm) / n] * n
        t = Table(data, colWidths=cw, repeatRows=1)
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

    story = []
    period = f"{monday.strftime('%d %b')} – {sunday.strftime('%d %b %Y')}"
    story += [
        Paragraph("Jadwal Kerja Café", title_s),
        Paragraph(period, sub_s),
        Paragraph(f"Generated {today.strftime('%d/%m/%Y %H:%M')}", gen_s),
        Spacer(1, 0.4*cm),
        HRFlowable(width="100%", thickness=1.5, color=ACCENT_B, spaceAfter=4),
        Spacer(1, 0.2*cm),
        section_header("☕  BARISTA", ACCENT_B),
        build_table(BARISTA, buat_jadwal_hari, OFF_TETAP_BARISTA, "barista", ACCENT_B),
        Spacer(1, 0.35*cm),
        section_header("🍳  CHEF", ACCENT_C),
        build_table(CHEF, buat_jadwal_chef, OFF_TETAP_CHEF, "chef", ACCENT_C),
        Spacer(1, 0.3*cm),
        HRFlowable(width="100%", thickness=0.5, color=BORDER),
        Spacer(1, 0.1*cm),
        Paragraph("OFF = libur tetap  ·  LIBUR = request libur  ·  Baris biru = hari ini", c_leg),
    ]
    doc.build(story)
    return pdf_path


async def kirim_pdf(update, context):
    week_data = get_week_data()
    pdf_path = generate_pdf(week_data)
    today  = datetime.now()
    monday = get_target_monday()
    with open(pdf_path, "rb") as f:
        await update.message.reply_document(
            document=f,
            filename=f"Jadwal_{monday.strftime('%d%b%Y')}.pdf",
            caption=f"☕ Jadwal Cafe - Minggu {monday.strftime('%d %b %Y')}"
        )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if is_admin(uid):
        msg = (
            "☕ Cafe Schedule Bot — ADMIN\n\n"
            "/libur [nama] [hari] — request libur\n"
            "  contoh: /libur ayuk rabu\n\n"
            "/batalkan [nama] [hari] — batalkan request libur\n\n"
            "/canceloff [hari] [tim] — cancel OFF tetap\n"
            "  contoh: /canceloff senin barista\n"
            "  contoh: /canceloff rabu chef\n"
            "  contoh: /canceloff senin  ← semua tim\n\n"
            "/restoreoff [hari] [tim] — kembalikan OFF tetap\n"
            "  contoh: /restoreoff senin barista\n\n"
            "/liburlist — lihat semua request minggu ini\n"
            "/jadwal — generate PDF jadwal"
        )
    else:
        msg = "☕ Cafe Schedule Bot\n\nHubungi owner untuk request libur."
    await update.message.reply_text(msg)


async def libur(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Hanya admin.")
        return
    if len(context.args) < 2:
        await update.message.reply_text("Format: /libur [nama] [hari]\nContoh: /libur ayuk rabu")
        return

    nama = next((n for n in NAMA_VALID if n.lower() == context.args[0].lower()), None)
    hari = context.args[1].lower()

    if not nama:
        await update.message.reply_text(f"❌ Nama tidak valid. Pilihan: {', '.join(NAMA_VALID)}")
        return
    if hari not in HARI_VALID:
        await update.message.reply_text(f"❌ Hari tidak valid. Pilihan: {', '.join(HARI_VALID)}")
        return

    week_key = get_week_key()
    all_data = load_data()
    week_data = all_data.get(week_key, {})

    # Tentuin tim
    tim = "barista" if nama in BARISTA else "chef"
    off_tetap_map = OFF_TETAP_BARISTA if tim == "barista" else OFF_TETAP_CHEF

    # Cek sudah OFF tetap
    off_tetap = off_tetap_map.get(hari)
    cancelled = week_data.get("cancelled_off", [])
    if off_tetap == nama and f"{hari}_{nama}" not in cancelled:
        await update.message.reply_text(f"ℹ️ {nama} sudah OFF tetap di {hari.capitalize()}.")
        return

    # Cek konflik — sudah ada yang libur di hari ini (dalam tim yang sama)?
    off_list = siapa_off(hari, week_data, tim=tim)
    if off_list:
        konflik = off_list[0]
        # Cari hari lain yang bisa
        hari_bebas = []
        for h in HARI_VALID:
            ol = siapa_off(h, week_data, tim=tim)
            off_t = off_tetap_map.get(h)
            if off_t == nama:
                continue
            if not ol and h != hari:
                hari_bebas.append(h.capitalize())
        saran = f"\n\n💡 Hari available untuk {nama}: {', '.join(hari_bebas)}" if hari_bebas else ""
        await update.message.reply_text(
            f"❌ {konflik} sudah libur di {hari.capitalize()}.\nMaks 1 karyawan libur per hari.{saran}"
        )
        return

    # Simpan
    week_data.setdefault("libur", {}).setdefault(nama, [])
    if hari in week_data["libur"][nama]:
        await update.message.reply_text(f"ℹ️ {nama} sudah request libur {hari.capitalize()}.")
        return
    week_data["libur"][nama].append(hari)
    all_data[week_key] = week_data
    save_data(all_data)

    await update.message.reply_text(f"✅ Libur {hari.capitalize()} untuk {nama} tercatat!\nGenerating jadwal...")
    await kirim_pdf(update, context)


async def batalkan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Hanya admin.")
        return
    if len(context.args) < 2:
        await update.message.reply_text("Format: /batalkan [nama] [hari]")
        return

    nama = next((n for n in NAMA_VALID if n.lower() == context.args[0].lower()), None)
    hari = context.args[1].lower()
    if not nama:
        await update.message.reply_text(f"❌ Nama tidak valid.")
        return

    week_key = get_week_key()
    all_data = load_data()
    week_data = all_data.get(week_key, {})

    if hari not in week_data.get("libur", {}).get(nama, []):
        await update.message.reply_text(f"ℹ️ Tidak ada request libur {hari} untuk {nama}.")
        return

    week_data["libur"][nama].remove(hari)
    if not week_data["libur"][nama]:
        del week_data["libur"][nama]
    all_data[week_key] = week_data
    save_data(all_data)

    await update.message.reply_text(f"✅ Request libur {hari.capitalize()} untuk {nama} dibatalkan.\nGenerating jadwal...")
    await kirim_pdf(update, context)


async def canceloff(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Hanya admin.")
        return
    if not context.args:
        await update.message.reply_text(
            "Format: /canceloff [hari] [tim]\n"
            "Contoh: /canceloff senin barista\n"
            "        /canceloff senin chef\n"
            "        /canceloff senin  ← cancel semua tim di hari itu"
        )
        return

    hari = context.args[0].lower()
    tim_filter = context.args[1].lower() if len(context.args) > 1 else "semua"

    if hari not in HARI_VALID:
        await update.message.reply_text("❌ Hari tidak valid.")
        return
    if tim_filter not in ("barista", "chef", "semua"):
        await update.message.reply_text("❌ Tim tidak valid. Pilihan: barista / chef")
        return

    kandidat = []
    if tim_filter in ("barista", "semua"):
        off = OFF_TETAP_BARISTA.get(hari)
        if off: kandidat.append(off)
    if tim_filter in ("chef", "semua"):
        off = OFF_TETAP_CHEF.get(hari)
        if off: kandidat.append(off)

    if not kandidat:
        await update.message.reply_text(f"ℹ️ Tidak ada OFF tetap di {hari.capitalize()} untuk tim yang dipilih.")
        return

    week_key = get_week_key()
    all_data = load_data()
    week_data = all_data.get(week_key, {})
    cancelled = week_data.get("cancelled_off", [])

    msg_parts = []
    for off_tetap in kandidat:
        key = f"{hari}_{off_tetap}"
        if key in cancelled:
            msg_parts.append(f"ℹ️ OFF {off_tetap} di {hari.capitalize()} sudah di-cancel sebelumnya.")
        else:
            cancelled.append(key)
            msg_parts.append(f"✅ {off_tetap} di-cancel OFF → sekarang masuk {hari.capitalize()}.")

    week_data["cancelled_off"] = cancelled
    all_data[week_key] = week_data
    save_data(all_data)

    await update.message.reply_text("\n".join(msg_parts) + "\nGenerating jadwal...")
    await kirim_pdf(update, context)


async def restoreoff(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Hanya admin.")
        return
    if not context.args:
        await update.message.reply_text("Format: /restoreoff [hari]\nContoh: /restoreoff senin")
        return

    hari = context.args[0].lower()
    tim_filter = context.args[1].lower() if len(context.args) > 1 else "semua"

    if hari not in HARI_VALID:
        await update.message.reply_text("❌ Hari tidak valid.")
        return
    if tim_filter not in ("barista", "chef", "semua"):
        await update.message.reply_text("❌ Tim tidak valid. Pilihan: barista / chef")
        return

    kandidat = []
    if tim_filter in ("barista", "semua"):
        off = OFF_TETAP_BARISTA.get(hari)
        if off: kandidat.append(off)
    if tim_filter in ("chef", "semua"):
        off = OFF_TETAP_CHEF.get(hari)
        if off: kandidat.append(off)

    if not kandidat:
        await update.message.reply_text(f"ℹ️ Tidak ada OFF tetap di {hari.capitalize()} untuk tim yang dipilih.")
        return

    week_key = get_week_key()
    all_data = load_data()
    week_data = all_data.get(week_key, {})
    cancelled = week_data.get("cancelled_off", [])

    msg_parts = []
    for off_tetap in kandidat:
        key = f"{hari}_{off_tetap}"
        if key not in cancelled:
            msg_parts.append(f"ℹ️ OFF {off_tetap} di {hari.capitalize()} belum di-cancel.")
        else:
            cancelled.remove(key)
            msg_parts.append(f"✅ OFF {off_tetap} di {hari.capitalize()} dikembalikan!")

    week_data["cancelled_off"] = cancelled
    all_data[week_key] = week_data
    save_data(all_data)

    await update.message.reply_text("\n".join(msg_parts) + "\nGenerating jadwal...")
    await kirim_pdf(update, context)


async def liburlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Hanya admin.")
        return
    week_data = get_week_data()
    libur_req = week_data.get("libur", {})
    cancelled = week_data.get("cancelled_off", [])

    msg = "📋 Status Minggu Ini:\n\n"

    if libur_req:
        msg += "Request Libur:\n"
        for nama, hari_list in libur_req.items():
            msg += f"- {nama}: {', '.join([h.capitalize() for h in hari_list])}\n"
    else:
        msg += "Belum ada request libur.\n"

    if cancelled:
        msg += "\nOFF Tetap yang Di-cancel:\n"
        for c in cancelled:
            hari, nama = c.split("_", 1)
            msg += f"- {nama} masuk di {hari.capitalize()}\n"

    await update.message.reply_text(msg)


async def jadwal_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Hanya admin.")
        return
    await update.message.reply_text("Generating jadwal...")
    await kirim_pdf(update, context)


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("libur", libur))
    app.add_handler(CommandHandler("batalkan", batalkan))
    app.add_handler(CommandHandler("canceloff", canceloff))
    app.add_handler(CommandHandler("restoreoff", restoreoff))
    app.add_handler(CommandHandler("liburlist", liburlist))
    app.add_handler(CommandHandler("jadwal", jadwal_cmd))
    logger.info("Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()



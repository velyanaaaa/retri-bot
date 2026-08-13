"""
Modul Import Absensi — Parse file TXT scan log + generate PDF laporan
========================================================================
Dipanggil dari bot.py saat admin kirim file .TXT ke bot.
"""

import csv
import io
from collections import defaultdict
from datetime import datetime, timedelta, time


# ─────────────────────────────────────────────
#  PATOKAN JAM KERJA
# ─────────────────────────────────────────────
SHIFT_PAGI_RANGE  = (time(5, 30), time(7, 30))    # jam masuk shift pagi
SHIFT_SIANG_RANGE = (time(7, 30), time(10, 0))    # jam masuk shift siang
MIN_DURASI = timedelta(hours=7, minutes=30)       # di bawah ini = pulang duluan
MAX_DURASI = timedelta(hours=8, minutes=30)       # di atas ini = overtime


def _detect_shift(jam_masuk: time) -> str:
    if SHIFT_PAGI_RANGE[0] <= jam_masuk <= SHIFT_PAGI_RANGE[1]:
        return "pagi"
    elif SHIFT_SIANG_RANGE[0] < jam_masuk <= SHIFT_SIANG_RANGE[1]:
        return "siang"
    return "tidak jelas"


def parse_absensi_txt(file_bytes: bytes):
    """
    Parse raw scan log (format tab-delimited dengan kolom Name & DateTime).
    Return list of dict per (nama, tanggal): jam masuk, jam pulang, durasi, status.
    Nama di-normalize jadi lowercase-stripped untuk auto-matching,
    tapi ditampilkan title-case di laporan.
    """
    text = file_bytes.decode("utf-8", errors="ignore")
    reader = csv.DictReader(io.StringIO(text), delimiter="\t")

    scans = defaultdict(list)  # (nama_norm, tanggal) -> [datetime, ...]
    nama_display = {}          # nama_norm -> nama asli buat ditampilkan

    for row in reader:
        raw_name = (row.get("Name") or "").strip()
        raw_dt   = (row.get("DateTime") or "").strip()
        if not raw_name or not raw_dt:
            continue
        try:
            dt = datetime.strptime(raw_dt, "%Y/%m/%d %H:%M:%S")
        except ValueError:
            continue

        nama_norm = raw_name.lower()
        nama_display.setdefault(nama_norm, raw_name.title())
        scans[(nama_norm, dt.date())].append(dt)

    hasil = []
    for (nama_norm, tanggal), times in scans.items():
        times.sort()
        masuk  = times[0]
        pulang = times[-1]
        n_scan = len(times)

        rec = {
            "nama": nama_display[nama_norm],
            "tanggal": tanggal,
            "jumlah_scan": n_scan,
            "jam_masuk": masuk.time(),
            "jam_pulang": pulang.time(),
            "durasi": None,
            "shift": None,
            "status": None,
        }

        if n_scan < 2:
            rec["status"] = "1x_scan"
            hasil.append(rec)
            continue

        shift = _detect_shift(masuk.time())
        rec["shift"] = shift
        durasi = pulang - masuk
        rec["durasi"] = durasi

        if shift == "tidak jelas":
            rec["status"] = "tidak_jelas"
        elif durasi < MIN_DURASI:
            rec["status"] = "pulang_duluan"
        elif durasi > MAX_DURASI:
            rec["status"] = "overtime"
        else:
            rec["status"] = "normal"

        hasil.append(rec)

    hasil.sort(key=lambda r: (r["tanggal"], r["nama"]))
    return hasil


def fmt_durasi(td: timedelta) -> str:
    if td is None:
        return "-"
    total_menit = int(td.total_seconds() // 60)
    jam, menit = divmod(total_menit, 60)
    return f"{jam}j {menit}m"


STATUS_LABEL = {
    "pulang_duluan": "Pulang duluan",
    "normal":        "Normal",
    "overtime":       "Overtime",
    "1x_scan":       "1x scan",
    "tidak_jelas":   "Shift tidak jelas",
}


def generate_pdf_absensi(records: list, periode_label: str = None) -> str:
    """
    Generate PDF laporan absensi dari hasil parse_absensi_txt().
    Style konsisten dengan generate_pdf_ot() di bot.py.
    """
    from reportlab.lib.pagesizes import landscape, A4
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import (
        SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    )
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

    BLACK      = colors.HexColor("#111111")
    DARK_GRAY  = colors.HexColor("#2D2D2D")
    MID_GRAY   = colors.HexColor("#757575")
    WHITE      = colors.white
    HEADER_BG  = colors.HexColor("#2D2D2D")
    BORDER     = colors.HexColor("#E0E0E0")
    ROW_ALT    = colors.HexColor("#F7F7F7")

    STATUS_BG = {
        "pulang_duluan": colors.HexColor("#FFC7CE"),
        "overtime":       colors.HexColor("#FFD98C"),
        "normal":        colors.HexColor("#C6EFCE"),
        "1x_scan":       colors.HexColor("#FFEB9C"),
        "tidak_jelas":   colors.HexColor("#D9D9D9"),
    }

    now = datetime.now()
    if not periode_label and records:
        tanggal_list = [r["tanggal"] for r in records]
        periode_label = f"{min(tanggal_list).strftime('%d %b %Y')} - {max(tanggal_list).strftime('%d %b %Y')}"

    pdf_path = f"laporan_absensi_{now.strftime('%Y%m%d_%H%M')}.pdf"
    doc = SimpleDocTemplate(
        pdf_path, pagesize=landscape(A4),
        topMargin=1.2*cm, bottomMargin=1.2*cm,
        leftMargin=1.5*cm, rightMargin=1.5*cm
    )

    styles = getSampleStyleSheet()
    def ps(name, **kw):
        return ParagraphStyle(name, parent=styles["Normal"], **kw)

    title_s = ps("t", alignment=1, fontName="Helvetica-Bold", fontSize=18, textColor=BLACK, spaceAfter=3)
    sub_s   = ps("s", alignment=1, fontName="Helvetica", fontSize=9, textColor=MID_GRAY, spaceAfter=10)
    c_head  = ps("ch", alignment=1, fontName="Helvetica-Bold", fontSize=8, textColor=WHITE)
    c_norm  = ps("cn", alignment=1, fontName="Helvetica", fontSize=8, textColor=DARK_GRAY)

    story = [
        Paragraph("Laporan Absensi — Café Retri", title_s),
        Paragraph(
            f"Periode {periode_label}  |  Shift pagi masuk 05:30-07:30, shift siang masuk 07:30-10:00. "
            f"Durasi kerja &lt;7j30m = Pulang duluan, 7j30m-8j30m = Normal, &gt;8j30m = Overtime.",
            sub_s
        ),
    ]

    header = ["Nama", "Tanggal", "Shift", "Jml Scan", "Jam Masuk", "Jam Pulang", "Durasi", "Status"]
    data = [header]

    for r in records:
        data.append([
            r["nama"],
            r["tanggal"].strftime("%Y-%m-%d"),
            r["shift"] or "-",
            str(r["jumlah_scan"]),
            r["jam_masuk"].strftime("%H:%M:%S"),
            r["jam_pulang"].strftime("%H:%M:%S"),
            fmt_durasi(r["durasi"]),
            STATUS_LABEL.get(r["status"], r["status"]),
        ])

    col_widths = [3*cm, 2.6*cm, 2*cm, 1.8*cm, 2.6*cm, 2.6*cm, 2.2*cm, 3.4*cm]
    tbl = Table(data, colWidths=col_widths, repeatRows=1)

    ts = [
        ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
        ("TEXTCOLOR",  (0, 0), (-1, 0), WHITE),
        ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",   (0, 0), (-1, -1), 8),
        ("ALIGN",      (0, 0), (-1, -1), "CENTER"),
        ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
        ("GRID",       (0, 0), (-1, -1), 0.5, BORDER),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, ROW_ALT]),
    ]
    for i, r in enumerate(records, start=1):
        bg = STATUS_BG.get(r["status"])
        if bg:
            ts.append(("BACKGROUND", (-1, i), (-1, i), bg))

    tbl.setStyle(TableStyle(ts))
    story.append(tbl)

    doc.build(story)
    return pdf_path


def rekap_ringkas(records: list) -> str:
    """Bikin teks ringkasan per nama untuk dikirim sebagai caption/pesan."""
    per_nama = defaultdict(lambda: defaultdict(int))
    for r in records:
        per_nama[r["nama"]][r["status"]] += 1

    lines = ["📊 Ringkasan per orang:\n"]
    for nama in sorted(per_nama):
        d = per_nama[nama]
        lines.append(
            f"• {nama}: "
            f"{d.get('pulang_duluan', 0)} pulang duluan, "
            f"{d.get('normal', 0)} normal, "
            f"{d.get('overtime', 0)} overtime"
        )
    return "\n".join(lines)

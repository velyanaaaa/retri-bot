"""
Modul Import Inventory — Parse file Excel stok harian + cek batas minimum
============================================================================
Dipanggil dari bot.py saat admin kirim file .XLSX ke bot.

Format file yang didukung:
- 1+ "section" dalam satu sheet, tiap section punya baris header sendiri
  (kolom: No/No., Item, Unit, Order/Quantity, Stock, Remark) diikuti baris
  data, dipisahkan section lain oleh baris kosong.
- Kolom Stock bisa berisi:
    - angka biasa: 7, 21, 0
    - koma sebagai desimal: "7,7" -> 7.7
    - angka + satuan tambahan: "25 btl" -> 25
    - kosong / NaN -> dianggap "belum diisi", diabaikan (bukan 0)
"""

import re
import difflib
import pandas as pd


HEADER_ALIASES = {"no", "no.", "item", "unit", "order", "quantity", "stock", "remark"}


def _is_header_row(row) -> bool:
    """Deteksi apakah suatu baris adalah baris header section (bukan data barang)."""
    cells = [str(c).strip().lower() for c in row if pd.notna(c)]
    if not cells:
        return False
    # Header row biasanya punya "item" dan "stock" sebagai salah satu selnya
    return "item" in cells and "stock" in cells


def _parse_stock_value(raw):
    """
    Parse nilai stock yang formatnya bisa macam-macam.
    Return float, atau None kalau kosong/tidak bisa di-parse (dianggap "belum diisi").
    """
    if pd.isna(raw):
        return None
    if isinstance(raw, (int, float)):
        return float(raw)

    text = str(raw).strip()
    if not text:
        return None

    # Ambil angka pertama yang muncul di teks (support koma sebagai desimal)
    # Contoh: "25 btl" -> "25", "7,7" -> "7,7" -> 7.7
    match = re.search(r"[\d]+(?:[.,]\d+)?", text)
    if not match:
        return None

    num_str = match.group(0).replace(",", ".")
    try:
        return float(num_str)
    except ValueError:
        return None


def parse_inventory_xlsx(file_bytes: bytes):
    """
    Parse file Excel stok harian (bisa berisi banyak section dalam satu sheet).
    Return list of dict: [{"nama": ..., "unit": ..., "stock": float|None, "remark": ...}, ...]
    Baris tanpa nama item, atau baris header section, diabaikan.
    """
    import io
    df = pd.read_excel(io.BytesIO(file_bytes), sheet_name=0, header=None)

    hasil = []
    current_cols = None  # posisi kolom: {"item": idx, "unit": idx, "stock": idx, "remark": idx}

    for _, row in df.iterrows():
        values = row.tolist()

        if _is_header_row(values):
            # Update posisi kolom berdasarkan header section ini
            current_cols = {}
            for idx, cell in enumerate(values):
                if pd.isna(cell):
                    continue
                key = str(cell).strip().lower()
                if key in ("item",):
                    current_cols["item"] = idx
                elif key in ("unit",):
                    current_cols["unit"] = idx
                elif key in ("stock",):
                    current_cols["stock"] = idx
                elif key in ("remark",):
                    current_cols["remark"] = idx
            continue

        if current_cols is None or "item" not in current_cols:
            continue  # belum ketemu header section, skip baris ini

        nama_raw = values[current_cols["item"]] if current_cols["item"] < len(values) else None
        if pd.isna(nama_raw) or not str(nama_raw).strip():
            continue  # baris kosong / bukan baris barang

        nama = str(nama_raw).strip()
        unit = ""
        if "unit" in current_cols and current_cols["unit"] < len(values):
            u = values[current_cols["unit"]]
            unit = str(u).strip() if pd.notna(u) else ""

        stock = None
        if "stock" in current_cols and current_cols["stock"] < len(values):
            stock = _parse_stock_value(values[current_cols["stock"]])

        remark = ""
        if "remark" in current_cols and current_cols["remark"] < len(values):
            r = values[current_cols["remark"]]
            remark = str(r).strip() if pd.notna(r) else ""

        hasil.append({
            "nama": nama,
            "unit": unit,
            "stock": stock,
            "remark": remark,
        })

    return hasil


def normalisasi_nama(nama: str) -> str:
    """Normalisasi nama barang untuk pencocokan: lowercase, strip spasi berlebih."""
    return re.sub(r"\s+", " ", nama.strip().lower())


def cocokkan_nama_barang(nama_baru: str, daftar_nama_lama: list, ambang_batas: float = 0.82):
    """
    Cari nama barang di daftar_nama_lama yang paling mirip dengan nama_baru
    (fuzzy matching, untuk menangani typo/kapitalisasi beda antar file harian).
    Return nama_lama yang cocok, atau None kalau tidak ada yang cukup mirip.
    """
    norm_baru = normalisasi_nama(nama_baru)
    norm_lama_map = {normalisasi_nama(n): n for n in daftar_nama_lama}

    # 1. Exact match dulu (setelah normalisasi)
    if norm_baru in norm_lama_map:
        return norm_lama_map[norm_baru]

    # 2. Fuzzy match
    kandidat = difflib.get_close_matches(
        norm_baru, list(norm_lama_map.keys()), n=1, cutoff=ambang_batas
    )
    if kandidat:
        return norm_lama_map[kandidat[0]]

    return None

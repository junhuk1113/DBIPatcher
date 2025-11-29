import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import zstandard as zstd

GLYPH_W = 16
GLYPH_H = 16
BYTES_PER_ROW = 2
BYTES_PER_GLYPH = GLYPH_H * BYTES_PER_ROW
EXPECTED_SIZE = 0x10000 * BYTES_PER_GLYPH  # 65,536 glyphs * 32 bytes
MAGIC = b"\x28\xB5\x2F\xFD"

FONT_DIR = Path("font")

# Supported font ranges
HANGUL_SYLLABLES = [(0xAC00, 0xD7A4)]                                     # Hangul (가-힣)
JAPANESE_KANA = [(0x3040, 0x309F), (0x30A0, 0x30FF), (0x31F0, 0x31FF)]    # Hiragana, Katakana, Katakana Phonetic Extensions
CJK_UNIFIED_IDEOGRAPHS = [(0x4E00, 0x9FFF)]                               # CJK Unified Ideographs
LATIN_BASIC = [(0x0041, 0x005B), (0x0061, 0x007B)]                        # Basic Latin (A–Z, a–z)
LATIN_ACCENTED = LATIN_BASIC + [(0x00C0, 0x00FF)]                         # Latin-1 Accented Characters (À–ÿ)
LATIN_EXT_A = LATIN_ACCENTED + [(0x0100, 0x017F)]                         # Latin Extended-A
CYRILLIC = [(0x0400, 0x04FF)]                                             # Cyrillic characters
DIGITS = [(0x0030, 0x003A)]                                               # Digits 0–9

FONT_RANGES = {
    "ko": HANGUL_SYLLABLES,
    "ja": JAPANESE_KANA + CJK_UNIFIED_IDEOGRAPHS,
    "en": LATIN_BASIC,
    "fr": LATIN_ACCENTED,
    "frCA": LATIN_ACCENTED,
    "de": LATIN_ACCENTED,
    "it": LATIN_ACCENTED,
    "nl": LATIN_ACCENTED,
    "es": LATIN_ACCENTED,
    "es419": LATIN_ACCENTED,
    "pt": LATIN_ACCENTED,
    "ptBR": LATIN_ACCENTED,
    "pl": LATIN_EXT_A,
    "ru": CYRILLIC,
    "ua": CYRILLIC,
}

def load_config():
    cfg = {"font_num": False}

    try:
        with open("config.txt", "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if "=" not in line:
                    continue
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip().lower()

                if key == "font_num":
                    cfg["font_num"] = (val == "true")
    except:
        print("[WARN] config.txt not found → using default settings")

    return cfg

def pick_font():
    files = list(FONT_DIR.glob("*.ttf")) + list(FONT_DIR.glob("*.otf"))
    if not files:
        print("[ERROR] TTF/OTF Not found.")
        sys.exit(1)
    return files[0]

def find_font_bundle(raw):
    positions = []
    p = 0
    while True:
        i = raw.find(MAGIC, p)
        if i < 0:
            break
        positions.append(i)
        p = i + 1

    d = zstd.ZstdDecompressor()
    for pos in positions:
        try:
            dec = d.decompress(raw[pos:], max_output_size=EXPECTED_SIZE)
            if len(dec) == EXPECTED_SIZE:
                nxt = [x for x in positions if x > pos]
                limit = nxt[0] - pos if nxt else len(raw) - pos
                return pos, bytearray(dec), limit
        except:
            pass

    print("[FONT] No valid font bundle found in NRO.")
    sys.exit(1)

def rasterize_char(ft, ch):
    img = Image.new("L", (GLYPH_W, GLYPH_H), 0)
    draw = ImageDraw.Draw(img)
    ascent, descent = ft.getmetrics()

    try:
        w = int(round(ft.getlength(ch)))
    except:
        w = 8

    x = max(0, (GLYPH_W - w) // 2)
    y = (GLYPH_H - (ascent + descent)) // 2 + ascent
    draw.text((x, y - ascent), ch, fill=255, font=ft)

    bitmap = []
    for cy in range(GLYPH_H):
        row = []
        for cx in range(GLYPH_W):
            row.append(img.getpixel((cx, cy)) > 128)
        bitmap.append(row)
    return bitmap

def main():
    if len(sys.argv) < 3:
        print("Usage: font_patch.py <lang> <path_to_dbi_nro>")
        sys.exit(1)

    lang = sys.argv[1]
    nro_path = Path(sys.argv[2])
    cfg = load_config()

    if lang not in FONT_RANGES:
        print(f"[FONT] Language '{lang}' has no font range → SKIP")
        sys.exit(0)

    raw = nro_path.read_bytes()
    offset, bundle, limit = find_font_bundle(raw)

    print(f"[FONT] Using font ranges for '{lang}'")
    print(f"[FONT] Patching file: {nro_path}")

    ranges = list(FONT_RANGES[lang])
    if cfg["font_num"]:
        print("[FONT] font_num=true → adding digits")
        ranges += DIGITS

    font_path = pick_font()
    ft = ImageFont.truetype(str(font_path), 16)

    for (start, end) in ranges:
        for cp in range(start, end):
            bitmap = rasterize_char(ft, chr(cp))
            off = cp * BYTES_PER_GLYPH

            for r in range(GLYPH_H):
                row = bitmap[r]
                v = 0
                for bit, on in enumerate(row):
                    if on:
                        v |= (1 << (15 - bit))
                bundle[off + r*2] = v & 0xFF
                bundle[off + r*2 + 1] = (v >> 8) & 0xFF

    comp = zstd.ZstdCompressor(level=22).compress(bundle)
    if len(comp) > limit:
        print("[ERROR] Compressed bundle too large!!")
        sys.exit(1)

    raw = bytearray(raw)
    raw[offset:offset+len(comp)] = comp
    nro_path.write_bytes(raw)

    print("[FONT] Font patch complete.")

if __name__ == "__main__":
    main()

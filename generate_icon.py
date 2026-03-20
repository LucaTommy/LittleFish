"""Generate Little Fish .ico file from pixel art — no external dependencies."""

import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).parent


def make_fish_rgba(size: int) -> bytes:
    """Generate an RGBA pixel buffer of the fish face at given size."""
    # Work at internal 32x32 grid, then scale to requested size
    grid = [[0] * 32 for _ in range(32)]  # 0=transparent
    colors = {}

    def put(x, y, color_id):
        if 0 <= x < 32 and 0 <= y < 32:
            grid[y][x] = color_id

    # Define a palette
    TRANS = 0
    BORDER = 1    # #5BA8C8
    BODY = 2      # #7EC8E3
    LIGHT = 3     # #A8D8EA
    SHADOW = 4    # #4A9BB8
    EYE_OUT = 5   # #2C3E50
    EYE_WHITE = 6 # #FFFFFF
    PUPIL = 7     # #1A1A2E
    MOUTH = 8     # #2C3E50

    palette = {
        TRANS:     (0, 0, 0, 0),
        BORDER:    (91, 168, 200, 255),
        BODY:      (126, 200, 227, 255),
        LIGHT:     (168, 216, 234, 255),
        SHADOW:    (74, 155, 184, 255),
        EYE_OUT:   (44, 62, 80, 255),
        EYE_WHITE: (255, 255, 255, 255),
        PUPIL:     (26, 26, 46, 255),
        MOUTH:     (44, 62, 80, 255),
    }

    B = 4  # body pad

    # Body border (rounded rect 4,4 to 27,27)
    for x in range(B + 1, B + 23):
        put(x, B, BORDER)
        put(x, B + 23, BORDER)
    for y in range(B + 1, B + 23):
        put(B, y, BORDER)
        put(B + 23, y, BORDER)
    # Corners
    put(B + 1, B, BORDER); put(B, B + 1, BORDER)
    put(B + 22, B, BORDER); put(B + 23, B + 1, BORDER)
    put(B, B + 22, BORDER); put(B + 1, B + 23, BORDER)
    put(B + 23, B + 22, BORDER); put(B + 22, B + 23, BORDER)

    # Body fill
    for y in range(B + 1, B + 23):
        for x in range(B + 1, B + 23):
            put(x, y, BODY)

    # Top highlight
    for x in range(B + 3, B + 21):
        put(x, B + 1, LIGHT)
    # Left highlight
    for y in range(B + 3, B + 20):
        put(B + 1, y, LIGHT)
    # Bottom shadow
    for x in range(B + 3, B + 21):
        put(x, B + 22, SHADOW)
    # Right shadow
    for y in range(B + 3, B + 20):
        put(B + 23 - 1, y, SHADOW)

    # LEFT EYE: rect at (9, 11) size 4x5
    lex, ley = B + 5, B + 7
    for dy in range(5):
        for dx in range(4):
            put(lex + dx, ley + dy, EYE_OUT)
    for dy in range(1, 4):
        for dx in range(1, 3):
            put(lex + dx, ley + dy, EYE_WHITE)
    # Pupil 2x2 at (10, 13)
    put(lex + 1, ley + 2, PUPIL)
    put(lex + 2, ley + 2, PUPIL)
    put(lex + 1, ley + 3, PUPIL)
    put(lex + 2, ley + 3, PUPIL)

    # RIGHT EYE: rect at (19, 11) size 4x5
    rex, rey = B + 15, B + 7
    for dy in range(5):
        for dx in range(4):
            put(rex + dx, rey + dy, EYE_OUT)
    for dy in range(1, 4):
        for dx in range(1, 3):
            put(rex + dx, rey + dy, EYE_WHITE)
    put(rex + 1, rey + 2, PUPIL)
    put(rex + 2, rey + 2, PUPIL)
    put(rex + 1, rey + 3, PUPIL)
    put(rex + 2, rey + 3, PUPIL)

    # MOUTH - smile curve
    my = B + 17
    cx = 16
    put(cx - 3, my, MOUTH)
    put(cx - 2, my + 1, MOUTH)
    put(cx - 1, my + 1, MOUTH)
    put(cx, my + 1, MOUTH)
    put(cx + 1, my + 1, MOUTH)
    put(cx + 2, my, MOUTH)

    # Scale to target size
    scale = size / 32
    rgba = bytearray(size * size * 4)
    for py in range(size):
        for px in range(size):
            src_x = int(px / scale)
            src_y = int(py / scale)
            src_x = min(src_x, 31)
            src_y = min(src_y, 31)
            cid = grid[src_y][src_x]
            r, g, b, a = palette.get(cid, (0, 0, 0, 0))
            idx = (py * size + px) * 4
            rgba[idx] = r
            rgba[idx + 1] = g
            rgba[idx + 2] = b
            rgba[idx + 3] = a
    return bytes(rgba)


def make_png(size: int) -> bytes:
    """Create a minimal PNG from RGBA data."""
    rgba = make_fish_rgba(size)
    width = height = size

    def make_chunk(chunk_type, data):
        c = chunk_type + data
        crc = struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
        return struct.pack(">I", len(data)) + c + crc

    # PNG signature
    sig = b'\x89PNG\r\n\x1a\n'
    # IHDR
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)  # 8-bit RGBA
    ihdr = make_chunk(b'IHDR', ihdr_data)
    # IDAT — filter each row with "None" filter (0)
    raw = bytearray()
    for y in range(height):
        raw.append(0)  # filter byte
        row_start = y * width * 4
        raw.extend(rgba[row_start:row_start + width * 4])
    compressed = zlib.compress(bytes(raw), 9)
    idat = make_chunk(b'IDAT', compressed)
    # IEND
    iend = make_chunk(b'IEND', b'')

    return sig + ihdr + idat + iend


def make_ico(sizes=(16, 32, 48, 256)) -> bytes:
    """Create a .ico file with multiple sizes."""
    images = []
    for s in sizes:
        png_data = make_png(s)
        images.append((s, png_data))

    # ICO header: 2 bytes reserved, 2 bytes type (1=icon), 2 bytes count
    num = len(images)
    header = struct.pack("<HHH", 0, 1, num)

    # Directory entries (16 bytes each), then image data
    dir_size = 6 + num * 16
    offset = dir_size
    directory = bytearray()
    data_blobs = bytearray()

    for size, png_data in images:
        w = 0 if size >= 256 else size
        h = 0 if size >= 256 else size
        entry = struct.pack("<BBBBHHII",
                            w,           # width (0 = 256)
                            h,           # height (0 = 256)
                            0,           # color count
                            0,           # reserved
                            1,           # color planes
                            32,          # bits per pixel
                            len(png_data),  # size of image data
                            offset)      # offset from beginning of file
        directory.extend(entry)
        data_blobs.extend(png_data)
        offset += len(png_data)

    return header + bytes(directory) + bytes(data_blobs)


if __name__ == "__main__":
    # Generate the .ico file
    ico_data = make_ico()
    ico_path = ROOT / "littlefish.ico"
    ico_path.write_bytes(ico_data)
    print(f"Generated {ico_path} ({len(ico_data)} bytes)")

    # Also generate individual PNGs for reference
    for s in [16, 32, 48]:
        png_path = ROOT / f"littlefish_{s}.png"
        png_path.write_bytes(make_png(s))
        print(f"Generated {png_path}")

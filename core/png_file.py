"""Minimal 8-bit RGBA PNG writer, used as the staging format handed to texconv.

Why not TGA any more
--------------------
This replaces the TGA staging this pipeline used to write, which was cheaper
(no deflate) but had one fatal property: **an image whose alpha channel is
uniformly zero comes back from texconv as fully opaque.**  Measured on a 16x16
patch -- all-zero alpha read back as 255/255/255, while a plane with a *single*
non-zero pixel (1, 10, 128, anything) round-trips exactly.  PNG does not have the
problem.

That is not an edge case, it is what a "0-neutral" quantity looks like: DMC5's
BaseMetalMap.A is metallic and defaults to 0, so a composed ALBM with no
metallic input staged an all-zero alpha plane and shipped A=1.0 -- every texture
silently fully metallic, with nothing logged.  Any slot whose alpha should be
zero has the same fate (EmissiveMap.A, ATOS-E.A, and a user's own all-black
metallic map, which comes back as all-metal).

The earlier note on this trade-off -- a zlib pass "spent entirely on a handoff" --
was right about the cost and wrong about the risk.  Level 1 deflate keeps it to a
fraction of a second even at 4K, and the file is created and consumed inside one
call, so its size never matters.

Why not DDS, which would skip texconv's decode entirely
-------------------------------------------------------
``slot_resolver.write_slot_tex`` dispatches on the source extension, and a
``.dds`` source takes the *passthrough* branch -- straight to ``dds_to_tex``, no
compression.  Staging as DDS would therefore silently ship uncompressed RGBA8
textures to the game: right pixels, no error, several times the size.

Colour metadata is deliberately absent (no sRGB/gAMA/cHRM), so WIC treats the
pixels as having no colour space of their own and
``texconv_native._sanitize_png_color_metadata`` degrades to the no-op it already
returns for a PNG carrying none -- the "Blender tags its PNGs sRGB and DirectXTex
believes it" hazard cannot arise from a file we write ourselves.
"""

import struct
import zlib

_SIGNATURE = b'\x89PNG\r\n\x1a\n'

#: width, height, bit depth 8, colour type 6 (RGBA), deflate, adaptive filtering,
#: no interlace.
_IHDR = struct.Struct('>IIBBBBB')


def _chunk(ctype, payload):
    return (struct.pack('>I', len(payload)) + ctype + payload
            + struct.pack('>I', zlib.crc32(ctype + payload) & 0xFFFFFFFF))


def write_png_rgba8(filepath, arr, compress_level=1):
    """Write an ``(h, w, 4)`` float32 RGBA array in 0..1 as an 8-bit PNG.

    Row order is the same one the TGA staging used, i.e. **row 0 is the image's
    bottom** (Blender's own pixel order, which is what every caller here hands
    over).  PNG stores the top row first, so the flip happens here rather than at
    each call site -- a caller that already flipped keeps doing exactly what it
    did, and one that never did needs no change.

    Quantisation matches Blender's float->byte rule
    (``unit_float_to_uchar_clamp``: clamp, then ``v * 255 + 0.5`` truncated), so
    a buffer routed through here lands on the same bytes it would have had going
    through ``Image.save()``.
    """
    import numpy as np

    h, w = arr.shape[:2]
    quantised = (np.clip(arr, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
    top_down = np.ascontiguousarray(quantised[::-1])

    # One filter byte per scanline (0 = None; the buffer only has to survive one
    # hop to texconv, and filtering would cost more than the compression saves).
    filtered = np.zeros((h, w * 4 + 1), dtype=np.uint8)
    filtered[:, 1:] = top_down.reshape(h, w * 4)

    with open(filepath, 'wb') as f:
        f.write(_SIGNATURE)
        f.write(_chunk(b'IHDR', _IHDR.pack(w, h, 8, 6, 0, 0, 0)))
        f.write(_chunk(b'IDAT', zlib.compress(filtered.tobytes(), compress_level)))
        f.write(_chunk(b'IEND', b''))

    return filepath

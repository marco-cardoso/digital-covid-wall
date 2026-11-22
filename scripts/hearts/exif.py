"""Take the GPS position out of a JPEG's EXIF, without re-encoding the picture.

The camera writes where each photo was taken as a GPS block inside the EXIF header. This removes that block
in place: its entry leaves the first directory, and its bytes (and the values it points at) are zeroed. The
header keeps its size and every other offset stays valid, so the pixels, the other EXIF tags (time, camera,
exposure), the XMP and everything after them are byte-for-byte what the camera wrote.
"""
import struct

GPS_POINTER = 0x8825
# bytes in one value of each TIFF field type
TYPE_SIZE = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8}


def _remove_gps(tiff):
    """Remove the GPS block from a TIFF header (the EXIF payload) in place. True if there was one."""
    order = {b'II': '<', b'MM': '>'}.get(bytes(tiff[:2]))
    if order is None:
        return False

    def u16(at):
        return struct.unpack_from(order + 'H', tiff, at)[0]

    def u32(at):
        return struct.unpack_from(order + 'I', tiff, at)[0]

    def inside(start, size):
        if start < 0 or start + size > len(tiff):
            raise ValueError('EXIF offsets point outside the header')

    ifd0 = u32(4)
    inside(ifd0, 2)
    count = u16(ifd0)
    first = ifd0 + 2
    inside(first, 12 * count + 4)
    entry = next((first + 12 * k for k in range(count) if u16(first + 12 * k) == GPS_POINTER), None)
    if entry is None:
        return False

    gps = u32(entry + 8)
    inside(gps, 2)
    n = u16(gps)
    inside(gps, 2 + 12 * n + 4)
    for j in range(n):
        e = gps + 2 + 12 * j
        size = TYPE_SIZE.get(u16(e + 2), 1) * u32(e + 4)
        if size > 4:                                     # longer values live elsewhere in the header
            offset = u32(e + 8)
            inside(offset, size)
            tiff[offset:offset + size] = bytes(size)
    tiff[gps:gps + 2 + 12 * n + 4] = bytes(2 + 12 * n + 4)

    # Take the entry out of the first directory: later entries move up, the pointer to the next directory
    # follows them, and the 12 bytes that freed up are cleared.
    end = first + 12 * count
    following = bytes(tiff[end:end + 4])
    tiff[entry:end - 12] = tiff[entry + 12:end]
    tiff[end - 12:end - 8] = following
    tiff[end - 8:end + 4] = bytes(12)
    struct.pack_into(order + 'H', tiff, ifd0, count - 1)
    return True


def strip_gps(jpeg):
    """The JPEG (bytes) without the GPS block in its EXIF; the same bytes if it has none."""
    if jpeg[:2] != b'\xff\xd8':
        raise ValueError('not a JPEG')
    i = 2
    while i + 4 <= len(jpeg) and jpeg[i] == 0xFF:
        marker = jpeg[i + 1]
        if marker == 0xDA:                               # the picture itself starts here
            break
        length = struct.unpack('>H', jpeg[i + 2:i + 4])[0]
        if marker == 0xE1 and jpeg[i + 4:i + 10] == b'Exif\x00\x00':
            tiff = bytearray(jpeg[i + 10:i + 2 + length])
            if not _remove_gps(tiff):
                return jpeg
            return jpeg[:i + 10] + bytes(tiff) + jpeg[i + 2 + length:]
        i += 2 + length
    return jpeg

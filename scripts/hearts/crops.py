"""Model-ready crops of one heart: a colour version and a high-contrast ink version."""
import cv2
import numpy as np

PAD = 0.08                 # margin around the heart's box, as a share of its longer side
REACH = 0.12               # writing often spills over the edge: keep this much around the heart at full strength
FADE = 0.6                 # further out, blend this far toward white so neighbouring hearts don't compete
MIN_LONG = 768             # small hearts are enlarged to this longer side ...
MAX_LONG = 1024            # ... and big ones reduced to this (about 1k vision tokens on most models)
JPEG_QUALITY = 90


def padded_box(heart, shape):
    p = int(PAD * max(heart.w, heart.h))
    x0, y0 = max(0, heart.x - p), max(0, heart.y - p)
    x1, y1 = min(shape[1], heart.x + heart.w + p), min(shape[0], heart.y + heart.h + p)
    return x0, y0, x1, y1


def focus_mask(heart, box):
    """1 on the heart and just around it, falling to 0 further out, over the padded box."""
    x0, y0, x1, y1 = box
    m = np.zeros((y1 - y0, x1 - x0), np.uint8)
    m[heart.y - y0:heart.y - y0 + heart.h, heart.x - x0:heart.x - x0 + heart.w] = heart.mask
    r = max(3, int(REACH * max(heart.w, heart.h)))
    m = cv2.dilate(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1)))
    return cv2.GaussianBlur(m, (0, 0), r / 3).astype(np.float32) / 255


def fit(img):
    long = max(img.shape[:2])
    target = min(max(long, MIN_LONG), MAX_LONG)
    if target == long:
        return img
    s = target / long
    size = (round(img.shape[1] * s), round(img.shape[0] * s))
    return cv2.resize(img, size, interpolation=cv2.INTER_CUBIC if s > 1 else cv2.INTER_AREA)


def prepare(full, heart):
    """(colour BGR, enhanced grey, padded box) for one heart of a full-resolution photo."""
    box = padded_box(heart, full.shape)
    x0, y0, x1, y1 = box
    crop = full[y0:y1, x0:x1]
    keep = focus_mask(heart, box)
    keep = keep + (1 - keep) * (1 - FADE)              # outside the focus: 1 - FADE of the original

    # Colour: local contrast on lightness only, so the paint keeps its colour.
    lab = cv2.cvtColor(crop, cv2.COLOR_BGR2LAB)
    lab[:, :, 0] = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4)).apply(lab[:, :, 0])
    colour = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR).astype(np.float32)
    colour = colour * keep[..., None] + 255 * (1 - keep[..., None])

    # Enhanced: in the red channel the paint turns near-white and pen stays dark.
    red = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4)).apply(crop[:, :, 2]).astype(np.float32)
    enhanced = red * keep + 255 * (1 - keep)

    return fit(colour.clip(0, 255).astype(np.uint8)), fit(enhanced.clip(0, 255).astype(np.uint8)), box


def save(path_stem, colour, enhanced):
    """Write <stem>.jpg and <stem>_enh.jpg; return their file names."""
    cv2.imwrite(path_stem + '.jpg', colour, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
    cv2.imwrite(path_stem + '_enh.jpg', enhanced, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
    return path_stem + '.jpg', path_stem + '_enh.jpg'

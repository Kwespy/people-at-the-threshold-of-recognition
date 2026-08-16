from PIL import Image, ImageDraw
import numpy as np
import math


ANGLES = {
    "C": 15,
    "M": 75,
    "Y": 0,
    "K": 45
}


def halftone_channel_highres(channel_img, angle, cell_size, dot_scale, aa_scale):
    """
    Genera el tramado en resolución aumentada y luego lo reduce.
    Esto mantiene mucha mejor definición de puntos y bordes.
    """
    w, h = channel_img.size

    scale = max(1, int(aa_scale))
    cell_hr = max(1, int(round(cell_size * scale)))

    # canal ampliado
    channel_hr = channel_img.resize(
        (w * scale, h * scale),
        Image.Resampling.LANCZOS
    )

    hr_w, hr_h = channel_hr.size

    margin = cell_hr * 4

    padded = Image.new("L", (hr_w + 2 * margin, hr_h + 2 * margin), 0)
    padded.paste(channel_hr, (margin, margin))

    rotated = padded.rotate(
        angle,
        expand=True,
        resample=Image.Resampling.BICUBIC
    )

    rw, rh = rotated.size
    arr = np.asarray(rotated, dtype=np.float32) / 255.0

    screen = Image.new("L", (rw, rh), 255)
    draw = ImageDraw.Draw(screen)

    for y in range(0, rh, cell_hr):
        for x in range(0, rw, cell_hr):
            block = arr[y:y + cell_hr, x:x + cell_hr]

            if block.size == 0:
                continue

            ink = float(block.mean())

            # radio del punto
            radius = (cell_hr / 2.0) * math.sqrt(ink) * dot_scale

            if radius < 0.4:
                continue

            cx = x + block.shape[1] / 2.0
            cy = y + block.shape[0] / 2.0

            draw.ellipse(
                (cx - radius, cy - radius, cx + radius, cy + radius),
                fill=0
            )

    unrot = screen.rotate(
        -angle,
        expand=True,
        resample=Image.Resampling.BICUBIC
    )

    uw, uh = unrot.size
    crop_w = hr_w + 2 * margin
    crop_h = hr_h + 2 * margin
    left = (uw - crop_w) // 2
    top = (uh - crop_h) // 2

    cropped = unrot.crop(
        (
            left + margin,
            top + margin,
            left + margin + hr_w,
            top + margin + hr_h
        )
    )

    # volver a tamaño original con mejor remuestreo
    return cropped.resize((w, h), Image.Resampling.LANCZOS)


def apply(image: Image.Image, params: dict, legibility: float = 0.25, seed: int | None = None) -> Image.Image:
    img = image.convert("RGB")
    orig_w, orig_h = img.size

    cell_size = int(params.get("cell_size", 14))
    dot_scale = float(params.get("dot_scale", 1.1))

    # NUEVO: anti-aliasing interno
    aa_scale = int(params.get("aa_scale", 3))

    cmyk = img.convert("CMYK")
    c, m, y, k = cmyk.split()

    c_screen = halftone_channel_highres(c, ANGLES["C"], cell_size, dot_scale, aa_scale)
    m_screen = halftone_channel_highres(m, ANGLES["M"], cell_size, dot_scale, aa_scale)
    y_screen = halftone_channel_highres(y, ANGLES["Y"], cell_size, dot_scale, aa_scale)
    k_screen = halftone_channel_highres(k, ANGLES["K"], cell_size, dot_scale, aa_scale)

    C = 1.0 - (np.asarray(c_screen, dtype=np.float32) / 255.0)
    M = 1.0 - (np.asarray(m_screen, dtype=np.float32) / 255.0)
    Y = 1.0 - (np.asarray(y_screen, dtype=np.float32) / 255.0)
    K = 1.0 - (np.asarray(k_screen, dtype=np.float32) / 255.0)

    R = 255.0 * (1.0 - C) * (1.0 - K)
    G = 255.0 * (1.0 - M) * (1.0 - K)
    B = 255.0 * (1.0 - Y) * (1.0 - K)

    result = np.dstack([R, G, B]).clip(0, 255).astype(np.uint8)

    # NO resize final innecesario: ya sale en la resolución original
    return Image.fromarray(result, mode="RGB")
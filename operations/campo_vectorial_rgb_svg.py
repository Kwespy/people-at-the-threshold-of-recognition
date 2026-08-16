from PIL import Image, ImageOps, ImageColor
import numpy as np
import cv2
from math import cos, sin, pi
from typing import Optional


ANG_R = 0.0
ANG_G = 2.0 * pi / 3.0
ANG_B = 4.0 * pi / 3.0

VR = np.array([cos(ANG_R), sin(ANG_R)], dtype=np.float32)
VG = np.array([cos(ANG_G), sin(ANG_G)], dtype=np.float32)
VB = np.array([cos(ANG_B), sin(ANG_B)], dtype=np.float32)


def apply(
    image: Image.Image,
    params: dict,
    legibility: float = 0.25,
    seed: Optional[int] = None
) -> Image.Image:

    img = ImageOps.exif_transpose(image).convert("RGB")
    arr = np.asarray(img, dtype=np.float32)

    ancho, alto = img.size

    muestreo = max(1, int(params.get("MUESTREO", 18)))
    longitud_min = float(params.get("LONGITUD_MIN", 12.0))
    longitud_max = float(params.get("LONGITUD_MAX", 28.0))
    grosor_min = float(params.get("GROSOR_MIN", 1.0))
    grosor_max = float(params.get("GROSOR_MAX", 4.0))
    modo_color = str(params.get("MODO_COLOR", "original")).lower()
    fondo = str(params.get("FONDO", "white"))
    opacidad = int(np.clip(params.get("OPACIDAD", 190), 0, 255))
    escala = float(params.get("ESCALA_SALIDA", 1.0))
    antialias = bool(params.get("ANTIALIAS", False))

    # Misma regla de tamaño que el script original.
    out_w = max(1, int(ancho * escala))
    out_h = max(1, int(alto * escala))

    # Muestreo.
    sample = arr[::muestreo, ::muestreo]

    r = sample[..., 0]
    g = sample[..., 1]
    b = sample[..., 2]

    suma = r + g + b + 1e-6

    pr = r / suma
    pg = g / suma
    pb = b / suma

    vx = pr * VR[0] + pg * VG[0] + pb * VB[0]
    vy = pr * VR[1] + pg * VG[1] + pb * VB[1]

    magnitud = np.sqrt(vx * vx + vy * vy)
    valid = magnitud >= 1e-6

    vx = np.divide(
        vx,
        magnitud,
        out=np.zeros_like(vx),
        where=valid
    )

    vy = np.divide(
        vy,
        magnitud,
        out=np.zeros_like(vy),
        where=valid
    )

    brillo = (
        0.2126 * r
        + 0.7152 * g
        + 0.0722 * b
    ) / 255.0

    longitud = (
        longitud_min
        + brillo * (longitud_max - longitud_min)
    )

    sat = (
        np.maximum.reduce([r, g, b])
        - np.minimum.reduce([r, g, b])
    ) / 255.0

    grosor = np.rint(
        (
            grosor_min
            + sat * (grosor_max - grosor_min)
        )
        * escala
    ).astype(np.int32)

    grosor = np.maximum(
        grosor,
        1
    )

    ys = np.arange(
        0,
        alto,
        muestreo,
        dtype=np.float32
    )

    xs = np.arange(
        0,
        ancho,
        muestreo,
        dtype=np.float32
    )

    xx, yy = np.meshgrid(xs, ys)

    cx = xx * escala
    cy = yy * escala

    half = longitud * 0.5 * escala

    dx = vx * half
    dy = vy * half

    x1 = np.rint(cx - dx).astype(np.int32)
    y1 = np.rint(cy - dy).astype(np.int32)
    x2 = np.rint(cx + dx).astype(np.int32)
    y2 = np.rint(cy + dy).astype(np.int32)

    # Fondo RGB.
    bg = ImageColor.getrgb(fondo)

    canvas = np.empty(
        (out_h, out_w, 3),
        dtype=np.uint8
    )

    canvas[:] = np.array(
        bg,
        dtype=np.uint8
    )

    # IMPORTANTE:
    # En el script original las líneas se escribían en RGBA,
    # pero al final convert("RGB") eliminaba el canal alpha.
    # Por eso NO debemos mezclar el color con el fondo blanco.
    if modo_color == "original":
        colors = np.clip(
            sample,
            0,
            255
        ).astype(np.uint8)
    else:
        colors = np.zeros_like(
            sample,
            dtype=np.uint8
        )

    mask = valid.ravel()

    p1x = x1.ravel()[mask]
    p1y = y1.ravel()[mask]
    p2x = x2.ravel()[mask]
    p2y = y2.ravel()[mask]
    widths = grosor.ravel()[mask]
    cols = colors.reshape(-1, 3)[mask]

    line_type = (
        cv2.LINE_AA
        if antialias
        else cv2.LINE_8
    )

    for ax, ay, bx, by, width, color in zip(
        p1x,
        p1y,
        p2x,
        p2y,
        widths,
        cols
    ):
        cv2.line(
            canvas,
            (int(ax), int(ay)),
            (int(bx), int(by)),
            (
                int(color[0]),
                int(color[1]),
                int(color[2])
            ),
            int(width),
            lineType=line_type
        )

    return Image.fromarray(
        canvas,
        mode="RGB"
    )

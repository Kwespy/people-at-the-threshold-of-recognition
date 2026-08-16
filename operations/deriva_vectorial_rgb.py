from PIL import Image
import numpy as np

ANG_R = 0.0
ANG_G = 2.0 * np.pi / 3.0
ANG_B = 4.0 * np.pi / 3.0


def apply(image: Image.Image, params: dict, legibility: float = 0.25, seed: int | None = None) -> Image.Image:
    img = image.convert("RGB")
    ancho_original, alto_original = img.size

    DISTANCIA_MAX = float(params.get("DISTANCIA_MAX", 18))
    PASOS = int(params.get("PASOS", 7))
    CURVATURA_MAX = float(params.get("CURVATURA_MAX", 1.6))
    FUERZA_NEUTROS = float(params.get("FUERZA_NEUTROS", 1.15))
    PESO_ORIGINAL = float(params.get("PESO_ORIGINAL", 0.08))
    ESCALA_PROCESO = float(params.get("ESCALA_PROCESO", 0.65))

    if ESCALA_PROCESO != 1.0:
        nuevo_ancho = max(1, int(ancho_original * ESCALA_PROCESO))
        nuevo_alto = max(1, int(alto_original * ESCALA_PROCESO))
        img = img.resize((nuevo_ancho, nuevo_alto), Image.Resampling.LANCZOS)

    arr = np.asarray(img, dtype=np.float32)
    alto, ancho, _ = arr.shape

    r = arr[:, :, 0]
    g = arr[:, :, 1]
    b = arr[:, :, 2]
    suma = r + g + b + 1e-6

    pr = r / suma
    pg = g / suma
    pb = b / suma

    vx = pr * np.cos(ANG_R) + pg * np.cos(ANG_G) + pb * np.cos(ANG_B)
    vy = pr * np.sin(ANG_R) + pg * np.sin(ANG_G) + pb * np.sin(ANG_B)

    magnitud = np.sqrt(vx * vx + vy * vy)
    vx = vx / np.maximum(magnitud, 1e-6)
    vy = vy / np.maximum(magnitud, 1e-6)

    px = -vy
    py = vx

    brillo = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0
    distancia = (0.22 + 0.78 * brillo) * DISTANCIA_MAX * (1.08 - legibility)

    max_rgb = np.max(arr, axis=2)
    min_rgb = np.min(arr, axis=2)
    saturacion = (max_rgb - min_rgb) / 255.0
    actividad = FUERZA_NEUTROS + (1.0 - FUERZA_NEUTROS) * saturacion
    signo_curva = (pr - pb)
    curvatura = signo_curva * actividad * CURVATURA_MAX * (1.1 - legibility)

    yy, xx = np.indices((alto, ancho))
    acumulado = arr * PESO_ORIGINAL
    pesos = np.full((alto, ancho), PESO_ORIGINAL, dtype=np.float32)

    for paso in range(1, PASOS + 1):
        t = paso / PASOS
        avance_x = vx * distancia * t
        avance_y = vy * distancia * t
        offset_curva = np.sin(np.pi * t) * curvatura * DISTANCIA_MAX * 0.35
        curva_x = px * offset_curva
        curva_y = py * offset_curva
        nx = np.rint(xx + avance_x + curva_x).astype(np.int32)
        ny = np.rint(yy + avance_y + curva_y).astype(np.int32)
        valido = (nx >= 0) & (nx < ancho) & (ny >= 0) & (ny < alto)
        ox = xx[valido]
        oy = yy[valido]
        dxv = nx[valido]
        dyv = ny[valido]
        alpha = 0.30 + 0.70 * t
        np.add.at(acumulado, (dyv, dxv), arr[oy, ox] * alpha)
        np.add.at(pesos, (dyv, dxv), alpha)

    resultado = acumulado / np.maximum(pesos[:, :, None], 1e-6)
    resultado = np.clip(resultado, 0, 255).astype(np.uint8)
    salida = Image.fromarray(resultado)

    if ESCALA_PROCESO != 1.0:
        salida = salida.resize((ancho_original, alto_original), Image.Resampling.LANCZOS)
    return salida

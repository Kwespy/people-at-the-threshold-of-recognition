from PIL import Image, ImageOps
import numpy as np
import cv2


def apply(image: Image.Image, params: dict, legibility: float = 0.25, seed: int | None = None) -> Image.Image:
    img_pil = ImageOps.exif_transpose(image).convert("RGB")
    original = np.array(img_pil, dtype=np.uint8)
    ancho_original, alto_original = img_pil.size

    ANCHO_PROCESO = int(params.get("ANCHO_PROCESO", 1200))
    SUAVIZADO = float(params.get("SUAVIZADO", 3.0))
    BINS_RGB = int(params.get("BINS_RGB", 12))
    TAMANO_MINIMO = int(params.get("TAMANO_MINIMO", 80))
    SATURACION = float(params.get("SATURACION", 0.9))
    INTENSIDAD = float(params.get("INTENSIDAD", 0.65))

    if ancho_original > ANCHO_PROCESO:
        escala = ANCHO_PROCESO / ancho_original
        ancho = ANCHO_PROCESO
        alto = int(alto_original * escala)
        img = cv2.resize(original, (ancho, alto), interpolation=cv2.INTER_AREA)
    else:
        img = original.copy()
        alto, ancho = img.shape[:2]

    blur = cv2.GaussianBlur(img, (0, 0), sigmaX=SUAVIZADO, sigmaY=SUAVIZADO)
    f = blur.astype(np.float32)
    suma = f.sum(axis=2) + 1e-6
    r = f[:, :, 0] / suma
    g = f[:, :, 1] / suma
    b = f[:, :, 2] / suma
    rq = np.clip(np.floor(r * BINS_RGB).astype(np.int32), 0, BINS_RGB - 1)
    gq = np.clip(np.floor(g * BINS_RGB).astype(np.int32), 0, BINS_RGB - 1)
    bq = np.clip(np.floor(b * BINS_RGB).astype(np.int32), 0, BINS_RGB - 1)
    labels_rgb = rq + BINS_RGB * gq + (BINS_RGB ** 2) * bq

    resultado = img.astype(np.float32).copy()
    familias = np.unique(labels_rgb)
    for familia in familias:
        ys, xs = np.where(labels_rgb == familia)
        if len(xs) < TAMANO_MINIMO:
            continue
        x0, x1 = xs.min(), xs.max() + 1
        y0, y1 = ys.min(), ys.max() + 1
        mascara = (labels_rgb[y0:y1, x0:x1] == familia).astype(np.uint8)
        cantidad, componentes, stats, _ = cv2.connectedComponentsWithStats(mascara, connectivity=8)
        for grupo in range(1, cantidad):
            tamano = stats[grupo, cv2.CC_STAT_AREA]
            if tamano < TAMANO_MINIMO:
                continue
            region = componentes == grupo
            yy, xx = np.where(region)
            yy, xx = yy + y0, xx + x0
            colores = img[yy, xx].astype(np.float32)
            color_medio = colores.mean(axis=0)
            porcentajes = np.array([r[yy, xx].mean(), g[yy, xx].mean(), b[yy, xx].mean()], dtype=np.float32)
            dominante = int(np.argmax(porcentajes))
            ordenados = np.sort(porcentajes)
            dominancia = ordenados[-1] - ordenados[-2]
            color_nuevo = color_medio.copy()
            fuerza = np.clip(SATURACION * (0.30 + dominancia * 3.0) * (1.05 - legibility), 0.0, 1.0)
            color_nuevo[dominante] += (255 - color_nuevo[dominante]) * fuerza
            for canal in range(3):
                if canal != dominante:
                    color_nuevo[canal] *= (1.0 - 0.30 * fuerza)
            mezcla = INTENSIDAD
            resultado[yy, xx] = resultado[yy, xx] * (1.0 - mezcla) + color_nuevo * mezcla

    resultado = np.clip(resultado, 0, 255).astype(np.uint8)
    salida = Image.fromarray(resultado)
    if ancho_original != salida.size[0] or alto_original != salida.size[1]:
        salida = salida.resize((ancho_original, alto_original), Image.Resampling.LANCZOS)
    return salida

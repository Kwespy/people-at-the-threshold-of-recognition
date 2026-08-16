# ============================================================
# BORDER TRANSIT — CONFIGURACIÓN GENERAL
# Aquí vas a poder cambiar los parámetros sin tocar
# el código interno de cada operación.
# ============================================================


# ------------------------------------------------------------
# POOL
# ------------------------------------------------------------

POOL_SIZE = 60

# Cada 3 imágenes:
# 2 operaciones individuales + 1 mezcla
DISPLAY_PATTERN = ["single", "single", "mix"]

# Las imágenes MIX usarán aleatoriamente 2 o 3 operaciones
MIX_OPERATION_COUNT_OPTIONS = [2, 3]


# ------------------------------------------------------------
# CALIDAD DE SALIDA
# ------------------------------------------------------------

IMAGE_FORMAT = "WEBP"

# 0–100
# 95 = alta calidad pero mucho más rápido/liviano que PNG
IMAGE_QUALITY = 95


# ------------------------------------------------------------
# OPERACIONES
# ------------------------------------------------------------
# Aquí puedes modificar los parámetros cuando quieras.
#
# enabled = permite usar esa operación en el pool
# order   = orden cuando varias operaciones se combinan
# params  = parámetros propios de la operación
# ------------------------------------------------------------

OPERATIONS = {

    # ========================================================
    # 1. DERIVA VECTORIAL RGB
    # ========================================================

    "deriva_vectorial_rgb": {

        "enabled": True,
        "order": 6,

        "params": {

            "DISTANCIA_MAX": 88,

            "PASOS": 7,

            "CURVATURA_MAX": 2.6,

            "FUERZA_NEUTROS": 2.15,

            "PESO_ORIGINAL": 0.10,

            "ESCALA_PROCESO": 1.0,
        },
    },


    # ========================================================
    # 2. SATURACIÓN POR VECINDAD RGB
    # ========================================================

    "saturacion_vecindad_rgb": {

        "enabled": True,
        "order": 20,

        "params": {

            "ANCHO_PROCESO": 1200,

            "SUAVIZADO": 3.0,

            "BINS_RGB": 12,

            "TAMANO_MINIMO": 80,

            "SATURACION": 0.9,

            "UNIFICACION": 0.75,

            "INTENSIDAD": 0.65,
        },
    },


    # ========================================================
    # 3. RECONSTRUCCIÓN POR PARCHES
    # ========================================================

    "reconstruccion_parches": {

        "enabled": True,
        "order": 200,

        "params": {

            "TAM_PARCHE": 5,

            "TOP_K": 25,

            "DIST_MIN_PARCHES": 90,

            "USAR_COLOR": True,
        },
    },


    # ========================================================
    # 4. CAMPO VECTORIAL RGB
    # ========================================================

    "campo_vectorial_rgb_svg": {

        "enabled": True,
        "order": 40,

        "params": {

            "MUESTREO": 1,
            "LONGITUD_MIN": 82.0,

            "LONGITUD_MAX": 98.0,

            "GROSOR_MIN": 1.0,

            "GROSOR_MAX": 4.0,

            "MODO_COLOR": "original",

            "FONDO": "white",

            "OPACIDAD": 90,

            "ESCALA_SALIDA": 1.0,
        },
    },


    # ========================================================
    # 5. RETÍCULA CMYK
    # ========================================================

    "cmyk_reticula": {

        "enabled": False,
        "order": 40,

        "params": {

            "cell_size": 8,

            "dot_scale": 0.8,
        },
    },


    # ========================================================
    # 6. MATRIZ DE COLOR
    # ========================================================

   "matriz_color": {

    "enabled": True,
    "order": 30,

    "params": {

        "COLS": 172,

        "NUM_COLORS": 102,

        "STRENGTH": 1.45,

        "REMAP_MODE": "CHAOTIC",
        "REMAP_CHAOS": 0.78,
        "REMAP_MAX_SHIFT": 18,
        "REMAP_PRESERVE_FIRST": 0,
        "REMAP_ROTATIONS": 4,
        "REMAP_SEED": 0,
    },
},

}
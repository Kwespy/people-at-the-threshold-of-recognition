from pathlib import Path
from datetime import datetime, timezone
from PIL import Image, ImageOps

import hashlib
import json
import shutil


# ============================================================
# BORDER TRANSIT — POOL MANAGER
# ============================================================
#
# Este archivo NO busca imágenes.
#
# Su única función es recibir imágenes provenientes
# de cualquier scanner y añadirlas al corpus común.
#
#
# EJEMPLO:
#
# scan_turkish_coastguard.py
#               ↓
# scan_polish_border.py
#               ↓
# scan_frontex.py
#               ↓
#        add_to_pool(...)
#               ↓
#         originals/
#         pool.json
#
#
# Las operaciones algorítmicas NO cambian.
#
# ============================================================


ROOT = Path(__file__).resolve().parent

POOL_FILE = ROOT / "pool.json"

ORIGINALS_DIR = ROOT / "originals"

ORIGINALS_DIR.mkdir(exist_ok=True)


# ============================================================
# CONFIG
# ============================================================

# Normalizamos las imágenes que entran al pool.
#
# El archivo descargado por cada scanner permanece intacto
# dentro de su propia carpeta.
#
# originals/ recibe una COPIA normalizada.

POOL_FORMAT = "WEBP"

POOL_QUALITY = 95


# ============================================================
# CARGAR POOL
# ============================================================

def load_pool():

    if not POOL_FILE.exists():
        return []


    try:

        data = json.loads(
            POOL_FILE.read_text(
                encoding="utf-8"
            )
        )


        if isinstance(data, list):
            return data


    except Exception as e:

        print(
            f"⚠ No pude leer pool.json: {e}"
        )


    return []


# ============================================================
# GUARDAR POOL
# ============================================================

def save_pool(pool):

    POOL_FILE.write_text(

        json.dumps(
            pool,
            ensure_ascii=False,
            indent=2
        ),

        encoding="utf-8"
    )


# ============================================================
# ID SIGUIENTE
# ============================================================

def next_id(pool):

    numeros = []


    for item in pool:

        try:

            numeros.append(
                int(item.get("id"))
            )

        except Exception:
            pass


    if not numeros:
        return "0001"


    return (
        f"{max(numeros) + 1:04d}"
    )


# ============================================================
# SOURCE KEY
# ============================================================

def create_source_key(metadata):

    # --------------------------------------------------------
    # Evita volver a introducir la misma imagen cuando
    # ejecutamos un scanner varias veces.
    # --------------------------------------------------------

    pieces = [

        metadata.get(
            "institution",
            ""
        ),

        metadata.get(
            "source_page",
            ""
        ),

        metadata.get(
            "image_url",
            ""
        ),

        metadata.get(
            "source_id",
            ""
        ),

        str(
            metadata.get(
                "timecode",
                ""
            )
        ),
    ]


    text = "|".join(
        str(x)
        for x in pieces
    )


    return hashlib.sha256(
        text.encode("utf-8")
    ).hexdigest()


# ============================================================
# ¿YA EXISTE?
# ============================================================

def already_exists(
    pool,
    source_key
):

    for item in pool:

        if (
            item.get("source_key")
            ==
            source_key
        ):

            return True


    return False


# ============================================================
# NORMALIZAR IMAGEN
# ============================================================

def normalize_image(
    source_path,
    output_path
):

    image = Image.open(
        source_path
    )


    image = ImageOps.exif_transpose(
        image
    )


    # transparencia → fondo blanco

    if image.mode in (
        "RGBA",
        "LA"
    ):

        background = Image.new(
            "RGB",
            image.size,
            "white"
        )


        alpha = image.getchannel(
            "A"
        )


        background.paste(
            image.convert("RGB"),
            mask=alpha
        )


        image = background


    else:

        image = image.convert(
            "RGB"
        )


    width, height = image.size


    image.save(

        output_path,

        format=POOL_FORMAT,

        quality=POOL_QUALITY,

        method=6
    )


    return (
        width,
        height
    )


# ============================================================
# AÑADIR AL POOL
# ============================================================

def add_to_pool(
    image_path,
    metadata
):

    image_path = Path(
        image_path
    )


    if not image_path.exists():

        print(
            f"✕ No existe: "
            f"{image_path}"
        )

        return None


    pool = load_pool()


    # ========================================================
    # DEDUPLICACIÓN
    # ========================================================

    source_key = create_source_key(
        metadata
    )


    if already_exists(
        pool,
        source_key
    ):

        print(
            "    ↳ ya estaba en pool"
        )

        return None


    # ========================================================
    # ID
    # ========================================================

    item_id = next_id(
        pool
    )


    filename = (
        f"{item_id}.webp"
    )


    output_path = (
        ORIGINALS_DIR
        /
        filename
    )


    # ========================================================
    # COPIA NORMALIZADA
    # ========================================================

    try:

        width, height = (
            normalize_image(
                image_path,
                output_path
            )
        )


    except Exception as e:

        print(
            f"✕ No pude normalizar "
            f"{image_path.name}: {e}"
        )

        return None


    # ========================================================
    # RECORD
    #
    # Dejamos varios alias de filename/path para mantener
    # compatibilidad con distintas versiones del generador.
    # ========================================================

    record = {

        # ----------------------------------------------------
        # IDENTIDAD
        # ----------------------------------------------------

        "id":
            item_id,

        "file":
            filename,

        "filename":
            filename,

        "original":
            f"originals/{filename}",


        # ----------------------------------------------------
        # ADQUISICIÓN
        # ----------------------------------------------------

        "source_key":
            source_key,

        "source":
            metadata.get(
                "source",
                "institutional_scan"
            ),

        "scanner":
            metadata.get(
                "scanner"
            ),

        "institution":
            metadata.get(
                "institution"
            ),

        "source_type":
            metadata.get(
                "source_type"
            ),

        "source_page":
            metadata.get(
                "source_page"
            ),

        "image_url":
            metadata.get(
                "image_url"
            ),

        "source_id":
            metadata.get(
                "source_id"
            ),


        # ----------------------------------------------------
        # DOCUMENTACIÓN
        # ----------------------------------------------------

        "title":
            metadata.get(
                "title"
            ),

        "date":
            metadata.get(
                "date"
            ),

        "location":
            metadata.get(
                "location"
            ),

        "border":
            metadata.get(
                "border"
            ),

        "from":
            metadata.get(
                "from"
            ),

        "to":
            metadata.get(
                "to"
            ),

        "route_name":
            metadata.get(
                "route_name"
            ),

        "route_documented":
            metadata.get(
                "route_documented",
                False
            ),


        # ----------------------------------------------------
        # APARATO / SISTEMA
        # ----------------------------------------------------

        "apparatus":
            metadata.get(
                "apparatus"
            ),

        "device":
            metadata.get(
                "device"
            ),

        "documented_devices":
            metadata.get(
                "documented_devices",
                []
            ),

        "image_device":
            metadata.get(
                "image_device",
                "unknown"
            ),


        # ----------------------------------------------------
        # FRAME DE VIDEO SI CORRESPONDE
        # ----------------------------------------------------

        "timecode":
            metadata.get(
                "timecode"
            ),


        # ----------------------------------------------------
        # IMAGEN
        # ----------------------------------------------------

        "width":
            width,

        "height":
            height,


        # ----------------------------------------------------
        # ESTADO
        # ----------------------------------------------------

        "status":
            "active",

        "added_at_utc":
            datetime.now(
                timezone.utc
            ).isoformat(),
    }


    pool.append(
        record
    )


    save_pool(
        pool
    )


    print(
        f"    → POOL {item_id}"
    )


    return record


# ============================================================
# ESTADO DEL POOL
# ============================================================

def pool_status():

    pool = load_pool()


    print(
        "\n"
        +
        "=" * 60
    )

    print(
        "BORDER TRANSIT — POOL"
    )

    print(
        "=" * 60
    )


    print(
        f"\nImágenes: {len(pool)}"
    )


    counts = {}


    for item in pool:

        institution = (
            item.get(
                "institution"
            )
            or
            "UNKNOWN"
        )


        counts[institution] = (
            counts.get(
                institution,
                0
            )
            +
            1
        )


    print(
        "\nPor fuente:"
    )


    for name, count in sorted(
        counts.items()
    ):

        print(
            f"  {count:02d}  {name}"
        )


    print()


# ============================================================
# EJECUTAR SOLO
# ============================================================

if __name__ == "__main__":

    pool_status()
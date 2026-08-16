from pathlib import Path
from datetime import datetime, timezone

from PIL import Image, ImageOps

import hashlib
import json
import random
import traceback


# ============================================================
# BORDER TRANSIT — GENERATE POOL
# ============================================================
#
# ENTRADA
#
# pool.json
# originals/
#
#        ↓
#
# patrón:
#
# single
# single
# mix
# single
# single
# mix
# ...
#
#        ↓
#
# operations/
#
#        ↓
#
# rendered/
# manifest.json
#
#
# IMPORTANTE:
#
# Este archivo NO sabe cómo fueron adquiridas las imágenes.
#
# Turkish Coast Guard
# Frontex
# Polish Border Guard
# HCG
# ...
#
# Todo eso ya fue resuelto por los scanners +
# pool_manager.py.
#
# ============================================================


# ============================================================
# IMPORTAR CONFIG
# ============================================================

from config import (
    POOL_SIZE,
    DISPLAY_PATTERN,
    MIX_OPERATION_COUNT_OPTIONS,
    IMAGE_FORMAT,
    IMAGE_QUALITY,
    OPERATIONS,
)


# ============================================================
# IMPORTAR OPERACIONES
# ============================================================

from operations import REGISTRY


# ============================================================
# PATHS
# ============================================================

ROOT = Path(__file__).resolve().parent

POOL_FILE = ROOT / "pool.json"

ORIGINALS_DIR = ROOT / "originals"

RENDERED_DIR = ROOT / "rendered"

MANIFEST_FILE = ROOT / "manifest.json"


RENDERED_DIR.mkdir(
    exist_ok=True
)


# ============================================================
# CONFIG DEL GENERADOR
# ============================================================

# Control general del nivel de legibilidad.
#
# Cada operación ya acepta este argumento.
#
# 0.25 es también el default definido en tus módulos.

LEGIBILITY = 0.25


# Seed general.
#
# No significa que todas las imágenes tengan el mismo
# resultado.
#
# El seed individual también incorpora el ID de la imagen.

MASTER_SEED = 260815


# Limpiar rendered/ antes de generar.
#
# True:
# elimina únicamente archivos generados previamente
# dentro de rendered/.
#
# NO toca originals/.

CLEAR_RENDERED_BEFORE_GENERATING = True


# ============================================================
# LOAD POOL
# ============================================================

def load_pool():

    if not POOL_FILE.exists():

        raise FileNotFoundError(
            "No existe pool.json"
        )


    data = json.loads(
        POOL_FILE.read_text(
            encoding="utf-8"
        )
    )


    if not isinstance(
        data,
        list
    ):

        raise ValueError(
            "pool.json debe contener una lista."
        )


    return data


# ============================================================
# ENABLED OPERATIONS
# ============================================================

def get_enabled_operations():

    enabled = []


    for name, config in (
        OPERATIONS.items()
    ):

        if not config.get(
            "enabled",
            True
        ):

            continue


        if name not in REGISTRY:

            print(
                f"⚠ Operación '{name}' "
                f"está en config.py "
                f"pero no en operations.REGISTRY"
            )

            continue


        enabled.append(
            {
                "name":
                    name,

                "order":
                    config.get(
                        "order",
                        999
                    ),

                "params":
                    config.get(
                        "params",
                        {}
                    ),
            }
        )


    enabled.sort(
        key=lambda x: x[
            "order"
        ]
    )


    return enabled


# ============================================================
# STABLE SEED
# ============================================================

def make_seed(
    item_id,
    position
):

    text = (
        f"{MASTER_SEED}|"
        f"{item_id}|"
        f"{position}"
    )


    digest = hashlib.sha256(
        text.encode(
            "utf-8"
        )
    ).hexdigest()


    return int(
        digest[:12],
        16
    )


# ============================================================
# RESOLVE ORIGINAL PATH
# ============================================================

def resolve_original_path(
    item
):

    # ========================================================
    # Nuevo pool_manager
    # ========================================================

    possible = [

        item.get(
            "original"
        ),

        item.get(
            "file"
        ),

        item.get(
            "filename"
        ),
    ]


    for value in possible:

        if not value:
            continue


        path = Path(
            value
        )


        # -----------------------------------------
        # path relativo completo:
        # originals/0001.webp
        # -----------------------------------------

        if not path.is_absolute():

            candidate = (
                ROOT
                /
                path
            )


            if candidate.exists():

                return candidate


        # -----------------------------------------
        # filename:
        # 0001.webp
        # -----------------------------------------

        candidate = (
            ORIGINALS_DIR
            /
            path.name
        )


        if candidate.exists():

            return candidate


    # ========================================================
    # Fallback por ID
    # ========================================================

    item_id = str(
        item.get(
            "id",
            ""
        )
    )


    extensions = [

        ".webp",
        ".jpg",
        ".jpeg",
        ".png",
    ]


    for ext in extensions:

        candidate = (
            ORIGINALS_DIR
            /
            f"{item_id}{ext}"
        )


        if candidate.exists():

            return candidate


    raise FileNotFoundError(
        f"No encontré original "
        f"para ID {item_id}"
    )


# ============================================================
# CLEAR RENDERED
# ============================================================

def clear_rendered():

    if not CLEAR_RENDERED_BEFORE_GENERATING:
        return


    if not RENDERED_DIR.exists():
        return


    for path in (
        RENDERED_DIR.iterdir()
    ):

        if not path.is_file():
            continue


        if path.suffix.lower() in {

            ".webp",
            ".jpg",
            ".jpeg",
            ".png",

        }:

            try:

                path.unlink()

            except Exception as e:

                print(
                    f"⚠ No pude borrar "
                    f"{path.name}: {e}"
                )


# ============================================================
# NORMALIZE IMAGE
# ============================================================

def normalize_input_image(
    path
):

    image = Image.open(
        path
    )


    image = ImageOps.exif_transpose(
        image
    )


    if image.mode != "RGB":

        image = image.convert(
            "RGB"
        )


    return image


# ============================================================
# SINGLE OPERATION SELECTION
# ============================================================

def choose_single_operation(
    single_index,
    enabled_operations
):

    # Rotación estable.
    #
    # Esto hace que las operaciones aparezcan
    # aproximadamente con la misma frecuencia.

    index = (
        single_index
        %
        len(
            enabled_operations
        )
    )


    return [
        enabled_operations[
            index
        ]
    ]


# ============================================================
# MIX SELECTION
# ============================================================

def choose_mix_operations(
    enabled_operations,
    seed
):

    rng = random.Random(
        seed
    )


    possible_counts = [

        int(x)

        for x
        in MIX_OPERATION_COUNT_OPTIONS

        if int(x) > 0

    ]


    if not possible_counts:

        possible_counts = [
            2
        ]


    requested_count = (
        rng.choice(
            possible_counts
        )
    )


    count = min(
        requested_count,
        len(
            enabled_operations
        )
    )


    selected = rng.sample(
        enabled_operations,
        count
    )


    # ========================================================
    # La selección puede ser aleatoria,
    # pero el ORDEN de aplicación respeta config.py.
    # ========================================================

    selected.sort(
        key=lambda x: x[
            "order"
        ]
    )


    return selected


# ============================================================
# DETERMINE MODE
# ============================================================

def get_display_mode(
    position
):

    if not DISPLAY_PATTERN:

        return "single"


    index = (
        position
        %
        len(
            DISPLAY_PATTERN
        )
    )


    mode = (
        DISPLAY_PATTERN[
            index
        ]
    )


    if mode not in {
        "single",
        "mix",
    }:

        return "single"


    return mode


# ============================================================
# APPLY ONE OPERATION
# ============================================================

def apply_operation(
    image,
    operation,
    seed
):

    name = operation[
        "name"
    ]


    params = operation[
        "params"
    ]


    function = REGISTRY[
        name
    ]


    result = function(

        image,

        params,

        legibility=LEGIBILITY,

        seed=seed
    )


    if result is None:

        raise RuntimeError(
            f"{name} devolvió None"
        )


    if not isinstance(
        result,
        Image.Image
    ):

        raise TypeError(
            f"{name} no devolvió "
            f"un PIL.Image.Image"
        )


    if result.mode != "RGB":

        result = result.convert(
            "RGB"
        )


    return result


# ============================================================
# APPLY OPERATION SEQUENCE
# ============================================================

def apply_operations(
    image,
    operations,
    base_seed
):

    current = image


    operation_records = []


    for step, operation in enumerate(
        operations,
        start=1
    ):

        operation_seed = (
            base_seed
            +
            step * 1009
        )


        name = operation[
            "name"
        ]


        print(
            f"      [{step}/"
            f"{len(operations)}] "
            f"{name}"
        )


        before_size = (
            current.size
        )


        current = apply_operation(

            current,

            operation,

            operation_seed
        )


        after_size = (
            current.size
        )


        operation_records.append(
            {

                "step":
                    step,

                "name":
                    name,

                "order":
                    operation[
                        "order"
                    ],

                "seed":
                    operation_seed,

                "legibility":
                    LEGIBILITY,

                "params":
                    operation[
                        "params"
                    ],

                "input_size":
                    list(
                        before_size
                    ),

                "output_size":
                    list(
                        after_size
                    ),
            }
        )


    return (
        current,
        operation_records
    )


# ============================================================
# OUTPUT EXTENSION
# ============================================================

def get_output_extension():

    format_upper = (
        IMAGE_FORMAT
        .upper()
    )


    mapping = {

        "WEBP":
            ".webp",

        "PNG":
            ".png",

        "JPEG":
            ".jpg",

        "JPG":
            ".jpg",
    }


    return mapping.get(
        format_upper,
        ".webp"
    )


# ============================================================
# SAVE IMAGE
# ============================================================

def save_image(
    image,
    path
):

    format_upper = (
        IMAGE_FORMAT
        .upper()
    )


    if format_upper == "WEBP":

        image.save(

            path,

            format="WEBP",

            quality=IMAGE_QUALITY,

            method=6
        )


    elif format_upper in {
        "JPEG",
        "JPG",
    }:

        image.save(

            path,

            format="JPEG",

            quality=IMAGE_QUALITY,

            optimize=True
        )


    elif format_upper == "PNG":

        image.save(

            path,

            format="PNG",

            optimize=True
        )


    else:

        image.save(
            path
        )


# ============================================================
# PROCESS ONE POOL ITEM
# ============================================================

def process_item(
    item,
    position,
    single_index,
    enabled_operations
):

    item_id = str(
        item.get(
            "id",
            f"{position + 1:04d}"
        )
    )


    original_path = (
        resolve_original_path(
            item
        )
    )


    mode = get_display_mode(
        position
    )


    seed = make_seed(
        item_id,
        position
    )


    # ========================================================
    # CHOOSE OPERATIONS
    # ========================================================

    if mode == "mix":

        selected = (
            choose_mix_operations(
                enabled_operations,
                seed
            )
        )


    else:

        selected = (
            choose_single_operation(
                single_index,
                enabled_operations
            )
        )


        single_index += 1


    names = [

        operation[
            "name"
        ]

        for operation
        in selected
    ]


    # ========================================================
    # PRINT
    # ========================================================

    print(
        "\n"
        +
        "-" * 72
    )


    print(
        f"{item_id} / "
        f"{mode.upper()}"
    )


    print(
        f"ORIGINAL / "
        f"{original_path.name}"
    )


    print(
        "OPERATIONS / "
        +
        " → ".join(
            names
        )
    )


    # ========================================================
    # LOAD
    # ========================================================

    image = normalize_input_image(
        original_path
    )


    original_size = (
        image.size
    )


    # ========================================================
    # TRANSFORM
    # ========================================================

    result, operation_records = (
        apply_operations(

            image,

            selected,

            seed
        )
    )


    # ========================================================
    # OUTPUT
    # ========================================================

    extension = (
        get_output_extension()
    )


    output_filename = (
        f"{item_id}"
        f"{extension}"
    )


    output_path = (
        RENDERED_DIR
        /
        output_filename
    )


    save_image(
        result,
        output_path
    )


    print(
        f"OUTPUT / "
        f"{output_filename}"
    )


    # ========================================================
    # MANIFEST RECORD
    #
    # Conservamos TODA la metadata del scanner/pool.
    # ========================================================

    record = dict(
        item
    )


    record.update(
        {

            "display_index":
                position + 1,

            "display_mode":
                mode,

            "original_file":
                str(
                    original_path.relative_to(
                        ROOT
                    )
                ),

            "rendered_file":
                str(
                    output_path.relative_to(
                        ROOT
                    )
                ),

            "original_width":
                original_size[0],

            "original_height":
                original_size[1],

            "rendered_width":
                result.size[0],

            "rendered_height":
                result.size[1],

            "operations":
                operation_records,

            "operation_names":
                names,

            "generator_seed":
                seed,

            "generated_at_utc":
                datetime.now(
                    timezone.utc
                ).isoformat(),

            "render_status":
                "ok",
        }
    )


    return (
        record,
        single_index
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print(
        "\n"
        +
        "=" * 72
    )


    print(
        "BORDER TRANSIT — "
        "GENERATE POOL"
    )


    print(
        "=" * 72
    )


    # ========================================================
    # LOAD
    # ========================================================

    pool = load_pool()


    if not pool:

        print(
            "\nPOOL VACÍO."
        )

        return


    enabled_operations = (
        get_enabled_operations()
    )


    if not enabled_operations:

        raise RuntimeError(
            "No hay operaciones "
            "habilitadas."
        )


    # ========================================================
    # LIMIT
    #
    # POOL_SIZE es máximo, no requisito.
    #
    # Con POOL_SIZE = 60 y 8 imágenes,
    # procesaremos 8.
    # ========================================================

    items = pool[
        :POOL_SIZE
    ]


    print(
        f"\nPool disponible: "
        f"{len(pool)}"
    )


    print(
        f"Procesaremos: "
        f"{len(items)}"
    )


    print(
        f"POOL_SIZE máximo: "
        f"{POOL_SIZE}"
    )


    print(
        "\nPatrón: "
        +
        " → ".join(
            DISPLAY_PATTERN
        )
    )


    print(
        "\nOperaciones habilitadas:"
    )


    for operation in (
        enabled_operations
    ):

        print(
            f"  {operation['order']:02d} "
            f"{operation['name']}"
        )


    # ========================================================
    # CLEAN
    # ========================================================

    clear_rendered()


    # ========================================================
    # GENERATE
    # ========================================================

    manifest = []

    failures = []

    single_index = 0


    for position, item in enumerate(
        items
    ):

        try:

            (
                record,
                single_index

            ) = process_item(

                item,

                position,

                single_index,

                enabled_operations
            )


            manifest.append(
                record
            )


        except Exception as e:

            item_id = str(
                item.get(
                    "id",
                    position + 1
                )
            )


            print(
                "\n"
                f"✕ ERROR EN {item_id}"
            )


            print(
                f"  {type(e).__name__}: "
                f"{e}"
            )


            failures.append(
                {

                    "id":
                        item_id,

                    "error_type":
                        type(e).__name__,

                    "error":
                        str(e),

                    "traceback":
                        traceback.format_exc(),
                }
            )


    # ========================================================
    # SAVE MANIFEST
    # ========================================================

    manifest_document = {

        "project":
            "Border Transit",

        "generated_at_utc":
            datetime.now(
                timezone.utc
            ).isoformat(),

        "pool_count":
            len(pool),

        "rendered_count":
            len(manifest),

        "failed_count":
            len(failures),

        "display_pattern":
            DISPLAY_PATTERN,

        "legibility":
            LEGIBILITY,

        "image_format":
            IMAGE_FORMAT,

        "image_quality":
            IMAGE_QUALITY,

        "items":
            manifest,

        "failures":
            failures,
    }


    MANIFEST_FILE.write_text(

        json.dumps(
            manifest_document,
            ensure_ascii=False,
            indent=2
        ),

        encoding="utf-8"
    )


    # ========================================================
    # SUMMARY
    # ========================================================

    print(
        "\n"
        +
        "=" * 72
    )


    print(
        "GENERACIÓN TERMINADA"
    )


    print(
        "=" * 72
    )


    print(
        f"\nOriginales: "
        f"{len(items)}"
    )


    print(
        f"Renderizados: "
        f"{len(manifest)}"
    )


    print(
        f"Errores: "
        f"{len(failures)}"
    )


    print(
        "\nSalida:"
    )


    print(
        "  rendered/"
    )


    print(
        "  manifest.json"
    )


    if failures:

        print(
            "\nHubo errores."
        )

        print(
            "Están documentados "
            "al final de manifest.json."
        )


    else:

        print(
            "\n✓ Pipeline completo funcionando."
        )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    main()
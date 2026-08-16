from pathlib import Path
from datetime import datetime, timezone

from flask import (
    Flask,
    jsonify,
    send_from_directory,
)

from PIL import Image, ImageOps

import json
import random
import secrets
import threading
import queue
import time


from config import (
    DISPLAY_PATTERN,
    MIX_OPERATION_COUNT_OPTIONS,
    IMAGE_FORMAT,
    IMAGE_QUALITY,
    OPERATIONS,
)

from operations import REGISTRY


# ============================================================
# BORDER TRANSIT — LIVE GENERATIVE SERVER
# ============================================================
#
# SISTEMA:
#
# rendered/
#     ↓
# buffer inmediato para la web
#
# al mismo tiempo:
#
# originals/
#     ↓
# operaciones Python
#     ↓
# single
# single
# mix
#     ↓
# live_rendered/
#     ↓
# cola preparada para la web
#
# ============================================================


# ============================================================
# PATHS
# ============================================================

ROOT = Path(__file__).resolve().parent

POOL_FILE = ROOT / "pool.json"

MANIFEST_FILE = ROOT / "manifest.json"

ORIGINALS_DIR = ROOT / "originals"

LIVE_RENDERED_DIR = (
    ROOT
    /
    "live_rendered"
)

LIVE_RENDERED_DIR.mkdir(
    exist_ok=True
)


# ============================================================
# CONFIG
# ============================================================

LEGIBILITY = 0.25


# Número de imágenes LIVE que intentamos
# mantener preparadas en todo momento.

LIVE_BUFFER_SIZE = 4


# Máximo de archivos live guardados en disco.

MAX_LIVE_FILES = 100


# ============================================================
# FLASK
# ============================================================

app = Flask(
    __name__,
    static_folder=None
)


# ============================================================
# GENERATOR STATE
# ============================================================

state_lock = threading.Lock()

display_counter = 0

single_counter = 0

last_source_id = None


# ============================================================
# LIVE QUEUE
# ============================================================

live_queue = queue.Queue(
    maxsize=LIVE_BUFFER_SIZE
)

worker_started = False

worker_lock = threading.Lock()


# ============================================================
# LOAD POOL
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


        if isinstance(
            data,
            list
        ):

            return [

                item

                for item in data

                if item.get(
                    "status",
                    "active"
                )
                !=
                "deleted"

            ]


    except Exception as e:

        print(
            f"POOL ERROR / {e}"
        )


    return []


# ============================================================
# BOOTSTRAP
#
# Imágenes YA renderizadas.
#
# Solo utilizamos imágenes cuyo ID todavía
# exista en pool.json.
#
# Así, si borraste una imagen del pool,
# no reaparece accidentalmente.
# ============================================================

def load_bootstrap_items():

    if not MANIFEST_FILE.exists():

        return []


    try:

        data = json.loads(
            MANIFEST_FILE.read_text(
                encoding="utf-8"
            )
        )


        if isinstance(
            data,
            dict
        ):

            items = data.get(
                "items",
                []
            )


        elif isinstance(
            data,
            list
        ):

            items = data


        else:

            return []


        # ====================================================
        # IDS QUE SIGUEN VIVOS EN EL POOL
        # ====================================================

        pool = load_pool()


        active_ids = {

            str(
                item.get(
                    "id"
                )
            )

            for item in pool

        }


        result = []


        for item in items:

            item_id = str(
                item.get(
                    "id"
                )
            )


            if (
                item_id
                not in
                active_ids
            ):

                continue


            rendered_file = (
                item.get(
                    "rendered_file"
                )
            )


            if not rendered_file:

                continue


            disk_path = (

                ROOT
                /
                rendered_file.lstrip(
                    "/"
                )

            )


            if not disk_path.exists():

                continue


            copy = dict(
                item
            )


            copy[
                "rendered_file"
            ] = (

                "/"
                +
                rendered_file.lstrip(
                    "/"
                )

            )


            copy[
                "live"
            ] = False


            result.append(
                copy
            )


        random.shuffle(
            result
        )


        return result


    except Exception as e:

        print(
            f"MANIFEST ERROR / {e}"
        )


        return []


# ============================================================
# ENABLED OPERATIONS
# ============================================================

def enabled_operations():

    result = []


    for name, config in (
        OPERATIONS.items()
    ):

        if not config.get(
            "enabled",
            True
        ):

            continue


        if name not in REGISTRY:

            continue


        result.append({

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
        })


    result.sort(
        key=lambda x:
            x[
                "order"
            ]
    )


    return result


# ============================================================
# RESOLVE ORIGINAL
# ============================================================

def resolve_original(
    item
):

    possibilities = [

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


    for value in possibilities:

        if not value:

            continue


        path = Path(
            value
        )


        candidate = (
            ROOT
            /
            path
        )


        if candidate.exists():

            return candidate


        candidate = (

            ORIGINALS_DIR
            /
            path.name

        )


        if candidate.exists():

            return candidate


    item_id = str(
        item.get(
            "id",
            ""
        )
    )


    for extension in [

        ".webp",
        ".jpg",
        ".jpeg",
        ".png",

    ]:

        candidate = (

            ORIGINALS_DIR
            /
            (
                item_id
                +
                extension
            )

        )


        if candidate.exists():

            return candidate


    return None


# ============================================================
# VALID POOL ITEMS
# ============================================================

def valid_pool_items():

    pool = load_pool()

    result = []


    for item in pool:

        path = resolve_original(
            item
        )


        if path:

            result.append(
                (
                    item,
                    path
                )
            )


    return result


# ============================================================
# RANDOM SOURCE
# ============================================================

def choose_source():

    global last_source_id


    items = valid_pool_items()


    if not items:

        raise RuntimeError(
            "No hay imágenes válidas en el pool."
        )


    alternatives = [

        pair

        for pair in items

        if str(
            pair[0].get(
                "id"
            )
        )
        !=
        str(
            last_source_id
        )

    ]


    if alternatives:

        selected = random.choice(
            alternatives
        )

    else:

        selected = random.choice(
            items
        )


    item, path = selected


    last_source_id = (
        item.get(
            "id"
        )
    )


    return (
        item,
        path
    )


# ============================================================
# DISPLAY MODE
#
# single
# single
# mix
# ============================================================

def next_mode():

    global display_counter


    if not DISPLAY_PATTERN:

        return "single"


    mode = DISPLAY_PATTERN[

        display_counter
        %
        len(
            DISPLAY_PATTERN
        )

    ]


    display_counter += 1


    if mode not in {
        "single",
        "mix",
    }:

        return "single"


    return mode


# ============================================================
# SINGLE
# ============================================================

def choose_single(
    operations
):

    global single_counter


    operation = operations[

        single_counter
        %
        len(
            operations
        )

    ]


    single_counter += 1


    return [
        operation
    ]


# ============================================================
# MIX
# ============================================================

def choose_mix(
    operations
):

    counts = [

        int(x)

        for x in
        MIX_OPERATION_COUNT_OPTIONS

        if int(x) > 0

    ]


    if not counts:

        counts = [
            2
        ]


    count = random.choice(
        counts
    )


    count = min(
        count,
        len(
            operations
        )
    )


    selected = random.sample(
        operations,
        count
    )


    selected.sort(
        key=lambda x:
            x[
                "order"
            ]
    )


    return selected


# ============================================================
# LOAD IMAGE
# ============================================================

def load_image(
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
# APPLY OPERATIONS
# ============================================================

def apply_operations(
    image,
    selected,
    base_seed
):

    current = image

    names = []


    for index, operation in enumerate(
        selected,
        start=1
    ):

        name = operation[
            "name"
        ]


        function = REGISTRY[
            name
        ]


        operation_seed = (

            base_seed

            +

            index
            *
            1009

        )


        print(
            f"    OP / {name}"
        )


        current = function(

            current,

            operation[
                "params"
            ],

            legibility=
                LEGIBILITY,

            seed=
                operation_seed
        )


        if current is None:

            raise RuntimeError(
                f"{name} devolvió None"
            )


        if current.mode != "RGB":

            current = current.convert(
                "RGB"
            )


        names.append(
            name
        )


    return (
        current,
        names
    )


# ============================================================
# FILE FORMAT
# ============================================================

def output_extension():

    format_upper = (
        IMAGE_FORMAT.upper()
    )


    if format_upper == "PNG":

        return ".png"


    if format_upper in {
        "JPG",
        "JPEG",
    }:

        return ".jpg"


    return ".webp"


# ============================================================
# SAVE
# ============================================================

def save_render(
    image,
    output
):

    format_upper = (
        IMAGE_FORMAT.upper()
    )


    if format_upper == "WEBP":

        image.save(

            output,

            format="WEBP",

            quality=IMAGE_QUALITY,

            method=6

        )


    elif format_upper == "PNG":

        image.save(

            output,

            format="PNG",

            optimize=True

        )


    else:

        image.save(

            output,

            format="JPEG",

            quality=IMAGE_QUALITY,

            optimize=True

        )


# ============================================================
# CLEAN LIVE CACHE
# ============================================================

def cleanup_live_cache():

    files = [

        path

        for path in
        LIVE_RENDERED_DIR.iterdir()

        if path.is_file()

    ]


    if (
        len(files)
        <=
        MAX_LIVE_FILES
    ):

        return


    files.sort(

        key=lambda path:
            path.stat().st_mtime

    )


    remove_count = (

        len(files)
        -
        MAX_LIVE_FILES

    )


    for path in files[
        :remove_count
    ]:

        try:

            path.unlink()

        except Exception:

            pass


# ============================================================
# GENERATE ONE
# ============================================================

def generate_one():

    global state_lock


    with state_lock:

        # ====================================================
        # SOURCE
        # ====================================================

        item, original_path = (
            choose_source()
        )


        # ====================================================
        # OPERATIONS
        # ====================================================

        operations = (
            enabled_operations()
        )


        if not operations:

            raise RuntimeError(
                "No hay operaciones habilitadas."
            )


        mode = next_mode()


        if mode == "mix":

            selected = choose_mix(
                operations
            )

        else:

            selected = choose_single(
                operations
            )


        # ====================================================
        # NUEVO SEED
        # ====================================================

        seed = secrets.randbits(
            31
        )


        print(
            "\n"
            +
            "=" * 60
        )


        print(
            f"LIVE / "
            f"{mode.upper()}"
        )


        print(
            f"SOURCE / "
            f"{item.get('id')}"
        )


        # ====================================================
        # TRANSFORM
        # ====================================================

        image = load_image(
            original_path
        )


        result, operation_names = (
            apply_operations(

                image,

                selected,

                seed

            )
        )


        # ====================================================
        # UNIQUE OUTPUT
        # ====================================================

        token = secrets.token_hex(
            6
        )


        filename = (

            datetime.now(
                timezone.utc
            )
            .strftime(
                "%Y%m%d_%H%M%S_%f"
            )

            +

            "_"

            +

            token

            +

            output_extension()

        )


        output_path = (

            LIVE_RENDERED_DIR
            /
            filename

        )


        save_render(

            result,

            output_path

        )


        cleanup_live_cache()


        # ====================================================
        # RESPONSE
        # ====================================================

        response = dict(
            item
        )


        response.update({

            "live":
                True,

            "live_mode":
                mode,

            "live_operations":
                operation_names,

            "live_seed":
                seed,

            "rendered_file":
                (
                    "/live_rendered/"
                    +
                    filename
                ),

            "generated_at_utc":
                datetime.now(
                    timezone.utc
                ).isoformat(),

        })


        print(
            f"OUTPUT / {filename}"
        )


        return response


# ============================================================
# BACKGROUND GENERATOR
#
# Este proceso corre TODO EL TIEMPO.
#
# Cuando la cola tiene menos de 4 imágenes,
# fabrica otra.
# ============================================================

def live_worker():

    print(
        "\nLIVE WORKER / STARTED"
    )


    while True:

        try:

            # =================================================
            # Si la cola está llena, esperamos.
            # =================================================

            if live_queue.full():

                time.sleep(
                    0.25
                )

                continue


            print(

                "\nLIVE BUFFER / "
                f"{live_queue.qsize()}"
                f"/{LIVE_BUFFER_SIZE}"

            )


            # =================================================
            # GENERATE
            # =================================================

            item = generate_one()


            live_queue.put(
                item
            )


            print(

                "LIVE READY / "
                f"{live_queue.qsize()}"
                f"/{LIVE_BUFFER_SIZE}"

            )


        except Exception as e:

            print(
                f"LIVE WORKER ERROR / {e}"
            )


            time.sleep(
                1
            )


# ============================================================
# START WORKER
# ============================================================

def start_worker():

    global worker_started


    with worker_lock:

        if worker_started:

            return


        worker_started = True


        thread = threading.Thread(

            target=live_worker,

            daemon=True,

            name="border-transit-live-worker"

        )


        thread.start()


# ============================================================
# ROUTES
# ============================================================

@app.route("/")
def root():

    return send_from_directory(

        ROOT,

        "index.html"

    )


# ============================================================
# BOOTSTRAP
# ============================================================

@app.route(
    "/api/bootstrap"
)
def api_bootstrap():

    items = (
        load_bootstrap_items()
    )


    return jsonify({

        "ok":
            True,

        "items":
            items,

        "count":
            len(
                items
            ),

    })


# ============================================================
# TAKE LIVE IMAGE
#
# Nunca bloquea.
#
# Si todavía no existe:
#
# ready = false
#
# y la web continúa usando rendered/.
# ============================================================

@app.route(
    "/api/live-next"
)
def api_live_next():

    try:

        item = (
            live_queue
            .get_nowait()
        )


        return jsonify({

            "ok":
                True,

            "ready":
                True,

            "item":
                item,

            "buffer_remaining":
                live_queue.qsize(),

        })


    except queue.Empty:

        return jsonify({

            "ok":
                True,

            "ready":
                False,

            "item":
                None,

            "buffer_remaining":
                0,

        })


# ============================================================
# STATUS
# ============================================================

@app.route(
    "/api/live-status"
)
def api_live_status():

    return jsonify({

        "ok":
            True,

        "ready":
            live_queue.qsize(),

        "target":
            LIVE_BUFFER_SIZE,

    })


# ============================================================
# LIVE FILES
# ============================================================

@app.route(
    "/live_rendered/<path:filename>"
)
def live_rendered(
    filename
):

    return send_from_directory(

        LIVE_RENDERED_DIR,

        filename

    )


# ============================================================
# STATIC FILES
#
# rendered/
# originals/
# etc.
# ============================================================

@app.route(
    "/<path:filename>"
)
def static_file(
    filename
):

    return send_from_directory(

        ROOT,

        filename

    )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    print(
        "\n"
        +
        "=" * 60
    )


    print(
        "BORDER TRANSIT — LIVE MODE"
    )


    print(
        "=" * 60
    )


    # ========================================================
    # MUY IMPORTANTE:
    #
    # EMPEZAMOS A RENDERIZAR ANTES INCLUSO
    # DE QUE EL NAVEGADOR ENTRE A LA WEB.
    # ========================================================

    start_worker()


    print(
        "\nhttp://localhost:8000"
    )


    app.run(

        host="127.0.0.1",

        port=8000,

        debug=False,

        threaded=True,

    )
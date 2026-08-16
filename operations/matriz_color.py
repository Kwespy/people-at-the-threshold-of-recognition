from PIL import Image, ImageOps
import numpy as np
import cv2
from typing import Optional


# ============================================================
# MATRIZ COLOR — HIGH RES / FAST / CHAOTIC
#
# Analiza la estructura cromática en baja resolución,
# pero aplica el desplazamiento a la imagen ORIGINAL.
#
# - mantiene dimensiones originales
# - mantiene textura y detalle
# - análisis rápido
# - remapeo ajustable desde config
# ============================================================


DEFAULT_REMAP = {
    1: 8, 8: 1,
    2: 9, 9: 2,
    3: 10, 10: 3,
    4: 11, 11: 4,
}


def average_grid_image(img, cols, rows=None):

    img = ImageOps.exif_transpose(
        img
    ).convert("RGB")

    w, h = img.size

    if rows is None:
        rows = max(
            1,
            round(cols * h / w)
        )

    small = img.resize(
        (cols, rows),
        Image.Resampling.BOX
    )

    return small, rows


def quantize_to_palette(
    img,
    num_colors=64
):

    num_colors = max(
        2,
        min(
            int(num_colors),
            256
        )
    )

    q = img.quantize(
        colors=num_colors,
        method=Image.Quantize.MEDIANCUT
    )

    palette = q.getpalette()

    idx = np.asarray(
        q,
        dtype=np.uint8
    )

    used_count = max(
        int(idx.max()) + 1,
        1
    )

    colors = np.array(
        [
            [
                palette[i * 3],
                palette[i * 3 + 1],
                palette[i * 3 + 2]
            ]
            for i in range(used_count)
        ],
        dtype=np.uint8
    )

    return idx, colors


def sanitize_remap(
    remap,
    num_colors
):

    clean = {
        i: i
        for i in range(num_colors)
    }

    for old_val, new_val in remap.items():

        try:
            old_i = int(old_val) - 1
            new_i = int(new_val) - 1
        except Exception:
            continue

        if (
            0 <= old_i < num_colors
            and
            0 <= new_i < num_colors
        ):
            clean[old_i] = new_i

    return clean


def build_semi_chaotic_remap(
    num_colors,
    chaos=0.24,
    max_shift=7,
    seed=0,
    preserve_first=0,
    rotations=1
):

    num_colors = max(
        1,
        int(num_colors)
    )

    chaos = float(
        np.clip(
            chaos,
            0.0,
            1.0
        )
    )

    max_shift = max(
        1,
        int(max_shift)
    )

    preserve_first = max(
        0,
        min(
            int(preserve_first),
            num_colors - 1
        )
    )

    rotations = max(
        0,
        int(rotations)
    )

    rng = np.random.default_rng(
        int(seed)
    )

    perm = np.arange(
        num_colors,
        dtype=np.int32
    )

    eligible = np.arange(
        preserve_first,
        num_colors,
        dtype=np.int32
    )

    if len(eligible) <= 1:

        return {
            i: i
            for i in range(num_colors)
        }


    # --------------------------------------------------------
    # LOCAL SWAPS
    # --------------------------------------------------------

    swap_count = max(
        1,
        int(
            len(eligible)
            *
            chaos
            *
            0.65
        )
    )

    for _ in range(swap_count):

        i = int(
            rng.choice(
                eligible
            )
        )

        low = max(
            preserve_first,
            i - max_shift
        )

        high = min(
            num_colors - 1,
            i + max_shift
        )

        if high <= low:
            continue

        j = int(
            rng.integers(
                low,
                high + 1
            )
        )

        if j == i:
            continue

        perm[i], perm[j] = (
            perm[j],
            perm[i]
        )


    # --------------------------------------------------------
    # SMALL BLOCK ROTATIONS
    # --------------------------------------------------------

    for _ in range(rotations):

        available = (
            num_colors
            -
            preserve_first
        )

        if available < 3:
            break

        block_size = min(
            available,
            int(
                rng.integers(
                    3,
                    min(8, available) + 1
                )
            )
        )

        max_start = (
            num_colors
            -
            block_size
        )

        start = int(
            rng.integers(
                preserve_first,
                max_start + 1
            )
        )

        direction = int(
            rng.choice(
                [-1, 1]
            )
        )

        perm[
            start:start + block_size
        ] = np.roll(
            perm[
                start:start + block_size
            ],
            direction
        )


    return {
        i: int(perm[i])
        for i in range(num_colors)
    }


def get_effective_remap(
    num_colors,
    params,
    seed=None
):

    mode = str(
        params.get(
            "REMAP_MODE",
            "CHAOTIC"
        )
    ).upper()


    if mode == "DEFAULT":

        return sanitize_remap(
            DEFAULT_REMAP,
            num_colors
        )


    remap_seed = int(
        params.get(
            "REMAP_SEED",
            seed
            if seed is not None
            else 0
        )
    )


    return build_semi_chaotic_remap(

        num_colors=num_colors,

        chaos=float(
            params.get(
                "REMAP_CHAOS",
                0.24
            )
        ),

        max_shift=int(
            params.get(
                "REMAP_MAX_SHIFT",
                7
            )
        ),

        seed=remap_seed,

        preserve_first=int(
            params.get(
                "REMAP_PRESERVE_FIRST",
                0
            )
        ),

        rotations=int(
            params.get(
                "REMAP_ROTATIONS",
                1
            )
        )
    )


def remap_indices(
    idx,
    remap
):

    lut = np.arange(
        256,
        dtype=np.uint8
    )

    for old_i, new_i in remap.items():

        if (
            0 <= old_i < 256
            and
            0 <= new_i < 256
        ):
            lut[old_i] = new_i

    return lut[idx]


def apply_color_remap_highres(
    original,
    idx,
    idx2,
    colors,
    strength=1.0
):

    original = ImageOps.exif_transpose(
        original
    ).convert("RGB")

    original_arr = np.asarray(
        original,
        dtype=np.float32
    )

    h, w = original_arr.shape[:2]


    # --------------------------------------------------------
    # SOLO construimos el DELTA pequeño.
    # No creamos dos mapas RGB gigantes.
    # --------------------------------------------------------

    source_small = colors[
        idx
    ].astype(
        np.float32
    )

    target_small = colors[
        idx2
    ].astype(
        np.float32
    )

    delta_small = (
        target_small
        -
        source_small
    )


    # --------------------------------------------------------
    # Expandir únicamente el desplazamiento cromático.
    # El original nunca se reduce.
    # --------------------------------------------------------

    delta_full = cv2.resize(

        delta_small,

        (w, h),

        interpolation=cv2.INTER_NEAREST

    )


    if strength != 1.0:

        delta_full *= float(
            strength
        )


    result = (
        original_arr
        +
        delta_full
    )


    result = np.clip(
        result,
        0,
        255
    ).astype(
        np.uint8
    )


    return Image.fromarray(
        result,
        mode="RGB"
    )


def apply(
    image: Image.Image,
    params: dict,
    legibility: float = 0.25,
    seed: Optional[int] = None
) -> Image.Image:


    cols = int(
        params.get(
            "COLS",
            96
        )
    )


    num_colors = int(
        params.get(
            "NUM_COLORS",
            64
        )
    )


    strength = float(
        params.get(
            "STRENGTH",
            1.0
        )
    )


    small, _ = average_grid_image(
        image,
        cols,
        None
    )


    idx, colors = quantize_to_palette(
        small,
        num_colors=num_colors
    )


    actual_colors = len(
        colors
    )


    remap = get_effective_remap(
        num_colors=actual_colors,
        params=params,
        seed=seed
    )


    idx2 = remap_indices(
        idx,
        remap
    )


    # CORREGIDO:
    # la función recibe "original", no "image".
    result = apply_color_remap_highres(

        original=image,

        idx=idx,

        idx2=idx2,

        colors=colors,

        strength=strength

    )


    return result

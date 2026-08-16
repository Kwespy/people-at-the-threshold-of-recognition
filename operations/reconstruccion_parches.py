from PIL import Image, ImageOps
import numpy as np
import cv2
from typing import Optional


# ============================================================
# RECONSTRUCCION PARCHES — STRONGER DISORDER
#
# MISMO CONCEPTO:
# - la imagen se reconstruye parche por parche
# - cada posición sigue siendo una celda del mosaico
# - cada celda recibe un parche DONANTE de la misma imagen
#
# NO CAMBIA A OTRA OPERACIÓN.
# NO HAY "SWAP" GLOBAL DE POSICIONES COMO SISTEMA APARTE.
#
# LO QUE SÍ CAMBIA:
# - los donantes se eligen de forma mucho más desordenada
# - parches más pequeños
# - más distancia espacial
# - mayor sesgo hacia vecinos menos cercanos dentro de la
#   búsqueda visual
#
# CALIDAD:
# - resolución final intacta
# - se copian píxeles originales completos
# ============================================================


# ============================================================
# PATCH GRID
# ============================================================

def build_patch_views(
    img,
    patch_size
):

    h, w = img.shape[:2]

    h2 = h - (h % patch_size)
    w2 = w - (w % patch_size)

    if h2 < patch_size or w2 < patch_size:
        raise ValueError(
            f"TAM_PARCHE={patch_size} demasiado grande para {w}x{h}"
        )

    cropped = np.ascontiguousarray(
        img[:h2, :w2]
    )

    ny = h2 // patch_size
    nx = w2 // patch_size

    patches = (
        cropped
        .reshape(
            ny,
            patch_size,
            nx,
            patch_size,
            3
        )
        .transpose(
            0, 2, 1, 3, 4
        )
    )

    patches_flat = patches.reshape(
        ny * nx,
        patch_size,
        patch_size,
        3
    )

    return cropped, patches_flat, ny, nx


# ============================================================
# FAST DESCRIPTORS
# ============================================================

def fast_descriptors(
    cropped,
    ny,
    nx,
    descriptor_grid=4,
    use_color=True
):
    """
    Descriptor rápido.
    Solo afecta la búsqueda del parche donante,
    no la resolución final.
    """

    descriptor_grid = max(
        2,
        int(descriptor_grid)
    )

    mini_w = nx * descriptor_grid
    mini_h = ny * descriptor_grid

    mini_image = cv2.resize(
        cropped,
        (mini_w, mini_h),
        interpolation=cv2.INTER_AREA
    )

    if use_color:

        mini_patches = (
            mini_image
            .reshape(
                ny,
                descriptor_grid,
                nx,
                descriptor_grid,
                3
            )
            .transpose(
                0, 2, 1, 3, 4
            )
            .reshape(
                ny * nx,
                descriptor_grid,
                descriptor_grid,
                3
            )
            .astype(
                np.float32,
                copy=False
            )
        )

        mean = mini_patches.mean(
            axis=(1, 2)
        )

        std = mini_patches.std(
            axis=(1, 2)
        )

        texture = mini_patches.reshape(
            ny * nx,
            -1
        )

    else:

        gray = cv2.cvtColor(
            mini_image,
            cv2.COLOR_BGR2GRAY
        )

        mini_patches = (
            gray
            .reshape(
                ny,
                descriptor_grid,
                nx,
                descriptor_grid
            )
            .transpose(
                0, 2, 1, 3
            )
            .reshape(
                ny * nx,
                descriptor_grid,
                descriptor_grid
            )
            .astype(
                np.float32,
                copy=False
            )
        )

        mean = mini_patches.mean(
            axis=(1, 2)
        )[:, None]

        std = mini_patches.std(
            axis=(1, 2)
        )[:, None]

        texture = mini_patches.reshape(
            ny * nx,
            -1
        )

    descriptors = np.concatenate(
        [mean, std, texture],
        axis=1
    )

    col_mean = descriptors.mean(
        axis=0,
        keepdims=True
    )

    col_std = descriptors.std(
        axis=0,
        keepdims=True
    )

    descriptors = (
        descriptors - col_mean
    ) / (
        col_std + 1e-6
    )

    return np.ascontiguousarray(
        descriptors,
        dtype=np.float32
    )


# ============================================================
# DONOR BANK
# ============================================================

def make_candidate_bank(
    n,
    max_candidates
):
    """
    Banco representativo de donantes.
    """

    max_candidates = max(
        64,
        int(max_candidates)
    )

    if n <= max_candidates:
        return np.arange(
            n,
            dtype=np.int32
        )

    return np.unique(
        np.linspace(
            0,
            n - 1,
            max_candidates,
            dtype=np.int32
        )
    )


# ============================================================
# FLANN SEARCH
# ============================================================

def flann_search_bank(
    descriptors,
    bank_ids,
    search_k,
    trees,
    checks
):

    bank_desc = np.ascontiguousarray(
        descriptors[bank_ids],
        dtype=np.float32
    )

    query_desc = np.ascontiguousarray(
        descriptors,
        dtype=np.float32
    )

    k = max(
        2,
        min(
            int(search_k),
            len(bank_ids)
        )
    )

    flann = cv2.flann_Index(
        bank_desc,
        {
            "algorithm": 1,   # KDTree
            "trees": max(
                1,
                int(trees)
            )
        }
    )

    local_indices, _ = flann.knnSearch(
        query_desc,
        k,
        params={
            "checks": max(
                1,
                int(checks)
            )
        }
    )

    global_indices = bank_ids[
        local_indices
    ]

    return global_indices.astype(
        np.int32,
        copy=False
    )


# ============================================================
# MUCH MORE DISORDERED CHOICE
# ============================================================

def choose_candidates_strong_disorder(
    neighbors,
    ny,
    nx,
    min_distance,
    min_pick_rank,
    max_pick_rank,
    far_bias,
    chaos,
    rng
):
    """
    Mantiene el concepto de reconstrucción por parches,
    pero fuerza una elección mucho más desordenada del donante.

    Estrategia:
    - descarta el propio parche
    - descarta donantes demasiado cercanos espacialmente
    - evita escoger los primeros vecinos "demasiado obvios"
    - privilegia vecinos más lejanos DENTRO del universo similar
    """

    n = neighbors.shape[0]

    ids = np.arange(
        n,
        dtype=np.int32
    )

    own_y = ids // nx
    own_x = ids % nx

    neigh_y = neighbors // nx
    neigh_x = neighbors % nx

    dx = np.abs(
        neigh_x - own_x[:, None]
    )

    dy = np.abs(
        neigh_y - own_y[:, None]
    )

    valid = (
        neighbors != ids[:, None]
    )

    if min_distance > 0:
        too_close = (
            (dx < min_distance)
            &
            (dy < min_distance)
        )
        valid &= ~too_close

    # Ranking solo entre válidos, respetando el orden FLANN.
    valid_ranks = np.cumsum(
        valid,
        axis=1
    )

    min_pick_rank = max(
        1,
        int(min_pick_rank)
    )

    max_pick_rank = max(
        min_pick_rank,
        int(max_pick_rank)
    )

    main_window = (
        valid
        &
        (valid_ranks >= min_pick_rank)
        &
        (valid_ranks <= max_pick_rank)
    )

    # Fallback por si una fila queda sin candidatos
    fallback_window = valid.copy()

    final_mask = main_window.copy()

    no_main = ~main_window.any(
        axis=1
    )

    final_mask[no_main] = fallback_window[
        no_main
    ]

    # --------------------------------------------------------
    # Pesos:
    # - cuanto más alto el rank, más peso
    # - far_bias empuja a elegir más lejos dentro de la ventana
    # - chaos aumenta ese sesgo
    # --------------------------------------------------------

    rank_values = np.where(
        final_mask,
        valid_ranks,
        0
    ).astype(np.float32)

    # normalización aproximada dentro de la ventana
    norm = (
        rank_values
        - float(min_pick_rank)
        + 1.0
    )

    norm = np.maximum(
        norm,
        1.0
    )

    exponent = 2.0 + 5.0 * float(
        np.clip(chaos, 0.0, 1.0)
    )

    bias = 1.0 + 6.0 * float(
        np.clip(far_bias, 0.0, 1.0)
    )

    weights = np.where(
        final_mask,
        np.power(norm, exponent) * bias,
        0.0
    )

    # ruido multiplicativo para evitar regularidad
    noise = 0.65 + 0.70 * rng.random(
        weights.shape
    )

    scores = weights * noise

    selected_column = np.argmax(
        scores,
        axis=1
    )

    chosen = neighbors[
        ids,
        selected_column
    ].copy()

    no_valid = ~final_mask.any(
        axis=1
    )

    chosen[no_valid] = ids[
        no_valid
    ]

    return chosen


# ============================================================
# RECONSTRUCT FULL RES
# ============================================================

def reconstruct_full_resolution(
    original,
    patches_flat,
    chosen,
    ny,
    nx,
    patch_size
):

    output = original.copy()

    h2 = ny * patch_size
    w2 = nx * patch_size

    selected = patches_flat[
        chosen
    ]

    reconstructed = (
        selected
        .reshape(
            ny,
            nx,
            patch_size,
            patch_size,
            3
        )
        .transpose(
            0,
            2,
            1,
            3,
            4
        )
        .reshape(
            h2,
            w2,
            3
        )
    )

    output[:h2, :w2] = reconstructed

    return output


# ============================================================
# APPLY
# ============================================================

def apply(
    image: Image.Image,
    params: dict,
    legibility: float = 0.25,
    seed: Optional[int] = None
) -> Image.Image:

    rng = np.random.default_rng(
        seed
    )

    pil_rgb = ImageOps.exif_transpose(
        image
    ).convert("RGB")

    bgr = cv2.cvtColor(
        np.asarray(pil_rgb),
        cv2.COLOR_RGB2BGR
    )

    bgr = np.ascontiguousarray(
        bgr
    )

    # ========================================================
    # PARAMS PRINCIPALES
    # ========================================================

    TAM_PARCHE = int(
        params.get(
            "TAM_PARCHE",
            16
        )
    )

    USAR_COLOR = bool(
        params.get(
            "USAR_COLOR",
            True
        )
    )

    DIST_MIN_PARCHES = int(
        params.get(
            "DIST_MIN_PARCHES",
            4
        )
    )

    # ========================================================
    # VELOCIDAD
    # ========================================================

    DESCRIPTOR_GRID = int(
        params.get(
            "DESCRIPTOR_GRID",
            4
        )
    )

    MAX_CANDIDATES = int(
        params.get(
            "MAX_CANDIDATES",
            2048
        )
    )

    FLANN_TREES = int(
        params.get(
            "FLANN_TREES",
            2
        )
    )

    FLANN_CHECKS = int(
        params.get(
            "FLANN_CHECKS",
            16
        )
    )

    SEARCH_K = int(
        params.get(
            "SEARCH_K",
            96
        )
    )

    # ========================================================
    # DESORDEN
    # ========================================================

    MIN_PICK_RANK = int(
        params.get(
            "MIN_PICK_RANK",
            10
        )
    )

    MAX_PICK_RANK = int(
        params.get(
            "MAX_PICK_RANK",
            56
        )
    )

    FAR_BIAS = float(
        params.get(
            "FAR_BIAS",
            0.88
        )
    )

    CHAOS = float(
        params.get(
            "CHAOS",
            0.94
        )
    )

    # ========================================================
    # PATCH VIEWS
    # ========================================================

    cropped, patches_flat, ny, nx = build_patch_views(
        bgr,
        TAM_PARCHE
    )

    n = ny * nx

    if n <= 1:
        return pil_rgb.copy()

    # ========================================================
    # DESCRIPTORS
    # ========================================================

    descriptors = fast_descriptors(
        cropped,
        ny,
        nx,
        descriptor_grid=DESCRIPTOR_GRID,
        use_color=USAR_COLOR
    )

    # ========================================================
    # DONOR BANK
    # ========================================================

    bank_ids = make_candidate_bank(
        n,
        MAX_CANDIDATES
    )

    # ========================================================
    # FLANN
    # ========================================================

    neighbors = flann_search_bank(
        descriptors,
        bank_ids,
        search_k=SEARCH_K,
        trees=FLANN_TREES,
        checks=FLANN_CHECKS
    )

    # ========================================================
    # MUCH MORE DISORDERED DONOR CHOICE
    # ========================================================

    chosen = choose_candidates_strong_disorder(
        neighbors=neighbors,
        ny=ny,
        nx=nx,
        min_distance=DIST_MIN_PARCHES,
        min_pick_rank=MIN_PICK_RANK,
        max_pick_rank=MAX_PICK_RANK,
        far_bias=FAR_BIAS,
        chaos=CHAOS,
        rng=rng
    )

    # ========================================================
    # FULL RES OUTPUT
    # ========================================================

    output = reconstruct_full_resolution(
        original=bgr,
        patches_flat=patches_flat,
        chosen=chosen,
        ny=ny,
        nx=nx,
        patch_size=TAM_PARCHE
    )

    rgb = cv2.cvtColor(
        output,
        cv2.COLOR_BGR2RGB
    )

    return Image.fromarray(rgb)
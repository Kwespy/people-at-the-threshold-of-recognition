from .deriva_vectorial_rgb import apply as deriva_vectorial_rgb
from .saturacion_vecindad_rgb import apply as saturacion_vecindad_rgb
from .reconstruccion_parches import apply as reconstruccion_parches
from .campo_vectorial_rgb_svg import apply as campo_vectorial_rgb_svg
from .cmyk_reticula import apply as cmyk_reticula
from .matriz_color import apply as matriz_color


REGISTRY = {
    "deriva_vectorial_rgb": deriva_vectorial_rgb,
    "saturacion_vecindad_rgb": saturacion_vecindad_rgb,
    "reconstruccion_parches": reconstruccion_parches,
    "campo_vectorial_rgb_svg": campo_vectorial_rgb_svg,
    "cmyk_reticula": cmyk_reticula,
    "matriz_color": matriz_color,
}
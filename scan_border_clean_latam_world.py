#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
scan_border_clean_latam_world.py

Scanner estricto para encontrar imágenes de personas cruzando fronteras.

CRITERIOS:
- Máximo 6 frames por video.
- Prioriza cámaras fijas, CCTV, sistemas remotos, térmicos y vigilancia continua.
- Rechaza bodycam, drone, handheld, aerial, prensa/noticiarios/reportajes.
- Rechaza frames con alto riesgo de logos, lower-thirds, franjas o texto superpuesto.
- Diversifica por país y permite excluir países ya muy representados.
- Detecta personas con YOLO.
- Favorece cámara estable/no operada directamente durante la captura.

IMPORTANTE:
La ausencia de movimiento y la metadata son indicadores, no prueba histórica absoluta
de autonomía. Revisa source_page + capture_hits antes de incorporar al corpus final.

ENTORNO RECOMENDADO:
    source ".venv-scan/bin/activate"

EJEMPLO:
    python scan_border_clean_latam_world.py \
      --results-per-query 30 \
      --max-videos 180 \
      --sample-seconds 0.8 \
      --max-per-country 2 \
      --avoid-countries "poland,latvia"

SALIDA:
    border_clean_latam_world_scan_YYYYMMDD_HHMMSS/
        frames/
        contact_sheets/
        candidates.csv
        candidates.jsonl
        videos.jsonl
        rejected.jsonl
        run_config.json
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import tempfile
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import cv2
import numpy as np
import requests
from bs4 import BeautifulSoup
from ultralytics import YOLO
import yt_dlp


# ============================================================
# FUENTES / BÚSQUEDAS
# ============================================================

OFFICIAL_SEED_PAGES = [
    # LATINOAMÉRICA — fuentes revisadas antes de construir este scan.
    "https://www.gob.pe/institucion/migraciones/noticias/746781-migraciones-activa-drone-y-camara-de-reconocimiento-facial-para-contribuir-a-labor-de-seguridad-en-la-frontera",
    "https://www.gob.pe/institucion/mininter/noticias/753617-policia-nacional-y-migraciones-fortalecen-seguridad-y-control-migratorio-en-frontera-sur",
    "https://portal.sat.gob.gt/portal/programa-miad/sistemas-de-video-vigilancia-cctv/",
    "https://www.gov.br/gsi/pt-br/centrais-de-conteudo/apoio/videos/colecao-de-videos-para-editorias/sistema-integrado-de-monitoramento-de-fronteiras-sisfron-2013-exercito-brasileiro",
    "https://www.senafront.gob.pa/",

    # OTROS CONTINENTES — fuentes oficiales revisadas.
    "https://www.gov.za/news/media-statements/minister-leon-schreiber-launches-cutting-edge-technology-bma-improve-border",
    "https://mup.gov.hr/vijesti/granica-s-bih-najsuvremenijom-je-tehnikom-pod-stalnim-nadzorom-283614/283614",
    "https://www.pib.gov.in/PressReleasePage.aspx?PRID=2110805&lang=2&reg=48",
    "https://www.prd.go.th/th/content/category/detail/id/3219/iid/425177",
    "https://www.defence.gov.au/news-events/news/2022-11-18/new-surveillance-weapon-launched",
]

# Nada de Polonia ni Latvia. No hay seeds de esos países y además se bloquean
# por metadata aunque aparezcan accidentalmente en una búsqueda global.
ABSOLUTE_EXCLUDE_COUNTRIES = {"poland", "latvia"}

# Videos directos de la versión anterior fueron quitados para evitar sesgo hacia
# Europa del Este. Este scan descubre material nuevo desde cero.
DIRECT_VIDEO_SEEDS = []

SEARCH_QUERIES = [
    # ========================================================
    # LATINOAMÉRICA — PRIORIDAD ALTA
    # ========================================================

    # Perú / Chile / Bolivia
    'Peru Chile border thermal camera migrants raw footage',
    'Peru Migraciones drone infrared border migrants raw video',
    'Tacna frontera dron visión infrarroja migrantes grabación',
    'Tacna cámara térmica frontera migrantes sin logo',
    'Tumbes frontera dron infrarrojo migrantes grabación',
    'Chile Bolivia border thermal camera migrants raw footage',
    'Colchane cámara térmica Ejército migrantes grabación',
    'Chile frontera cámara nocturna migrantes termal',
    'Peru Bolivia border surveillance camera migrants',

    # Guatemala / México / Belice / El Salvador
    'Guatemala El Salvador border CCTV Pedro de Alvarado camera',
    'Guatemala SAT CCTV border live camera Pedro de Alvarado',
    'Mexico Guatemala border fixed surveillance camera migrants',
    'Mexico Guatemala border CCTV migrants raw footage',
    'Suchiate border security camera migrants raw video',
    'Mexico southern border thermal camera migrants night vision',
    'Belize Mexico border surveillance camera migrants',
    'Guatemala Belize border security camera migrants',

    # Panamá / Colombia / Darién
    'Panama Colombia Darien surveillance camera migrants raw footage',
    'SENAFRONT Darien drone surveillance migrants raw video',
    'SENAFRONT thermal camera Darien migrants',
    'Darien night vision border surveillance migrants',
    'Panama border fixed camera migrants Colombia',
    'Colombia Panama border surveillance camera migrants Darien',

    # República Dominicana / Haití
    'Dominican Republic Haiti border surveillance camera migrants raw footage',
    'CESFRONT security camera Haiti border migrants',
    'Ejercito Republica Dominicana drone haitianos frontera raw footage',
    'Rio Masacre drone migrants raw footage Dominican army',
    'Dajabon CCTV frontera Haiti migrantes camera',
    'Dominican Haiti border thermal camera night vision migrants',

    # Brasil / Paraguay / Argentina / Uruguay
    'SISFRON border camera people raw footage Brazil',
    'SISFRON câmera longo alcance fronteira vídeo',
    'SISFRON câmera termal fronteira pessoas',
    'Brazil Paraguay border thermal camera people raw footage',
    'Brazil Bolivia border surveillance camera people',
    'Brazil Venezuela border surveillance camera migrants',
    'Argentina Paraguay border thermal camera crossing people',
    'Argentina Bolivia border night vision camera migrants',
    'Gendarmeria Argentina thermal camera border migrants raw video',
    'Triple frontera camera termica cruce personas raw footage',
    'Uruguay Brazil border CCTV people crossing',

    # Colombia / Venezuela / Ecuador
    'Colombia Venezuela border CCTV migrants raw footage',
    'Colombia Venezuela border thermal camera migrants',
    'Cucuta border security camera migrants raw video',
    'Ecuador Colombia border surveillance camera migrants',
    'Ecuador Peru border CCTV migrants crossing',

    # Caribe / Centroamérica adicionales
    'Costa Rica Panama border surveillance camera migrants',
    'Costa Rica Nicaragua border CCTV migrants crossing',
    'Honduras Guatemala border surveillance camera migrants',
    'Honduras Nicaragua border CCTV migrants',
    'Nicaragua Costa Rica border surveillance camera migrants',

    # ========================================================
    # NORTEAMÉRICA
    # ========================================================
    'CBP Remote Video Surveillance System migrants raw footage',
    'CBP RVSS border migrants camera raw video',
    'CBP Integrated Fixed Tower migrants raw footage',
    'autonomous surveillance tower migrants border raw footage',
    'Mexico United States border fixed thermal camera migrants raw footage',
    'Canada US border fixed surveillance camera people crossing',

    # ========================================================
    # EUROPA — SIN POLONIA NI LATVIA
    # ========================================================
    'Croatia Bosnia stationary thermal camera migrants raw footage',
    'Croatia Bosnia border day night surveillance camera migrants',
    'Hungary Serbia border thermal camera migrants raw footage',
    'Serbia Hungary border CCTV migrants raw footage',
    'Greece Turkey Evros fixed thermal camera migrants raw footage',
    'Evros night vision surveillance migrants raw footage',
    'Spain Morocco Ceuta fixed surveillance camera migrants raw footage',
    'Melilla border CCTV migrants raw footage',
    'Calais thermal detection camera migrants raw footage',
    'English Channel thermal camera migrants raw footage',
    'Finland Russia border fixed surveillance camera people raw footage',
    'Estonia Russia border surveillance camera people raw footage',

    # ========================================================
    # ÁFRICA
    # ========================================================
    'South Africa Zimbabwe border thermal drone migrants raw footage',
    'South Africa BMA night vision drone border raw footage',
    'South Africa Mozambique border surveillance camera people',
    'Morocco Algeria border thermal camera migrants raw footage',
    'Morocco Spain border surveillance night vision migrants raw footage',
    'Tunisia Libya border surveillance camera migrants',
    'Kenya Somalia border surveillance thermal camera people',

    # ========================================================
    # ASIA
    # ========================================================
    'India Bangladesh CIBMS CCTV thermal border crossing raw footage',
    'India Bangladesh border night vision camera people raw footage',
    'India Pakistan border thermal camera crossing raw footage',
    'Thailand Myanmar border CCTV crossing people raw footage',
    'Thailand Cambodia electronic fence CCTV border footage',
    'Turkey Syria border thermal surveillance camera people raw footage',
    'Korea DMZ fixed surveillance camera people raw footage',

    # ========================================================
    # OCEANÍA / PACÍFICO
    # ========================================================
    'Australia maritime border autonomous surveillance raw footage',
    'Australia Bluebottle unmanned surveillance vessel camera footage',
    'Australian Border Force thermal surveillance boat raw footage',
    'Solomon Islands border surveillance drone raw footage',

    # ========================================================
    # BÚSQUEDAS POR TIPO DE APARATO
    # Se buscan varias familias; luego metadata + análisis visual decide.
    # ========================================================
    'border security camera migrants raw footage no commentary',
    'fixed border CCTV people crossing raw footage',
    'thermal border surveillance people raw footage',
    'night vision border surveillance migrants raw footage',
    'infrared border camera migrants raw footage',
    'continuous bodycam border migrants raw footage official',
    'body worn camera border crossing migrants raw footage official',
    'autonomous drone border surveillance migrants raw footage',
    'unmanned drone border surveillance people raw footage',
    'motion triggered border camera people crossing',
    'unattended trail camera border people crossing',
]


# ============================================================
# PATRONES DE CAPTURA / RECHAZO
# ============================================================

AUTOMATIC_PATTERNS = [
    # Captura fija / automática / remota: máxima prioridad
    (r"remote video surveillance system", 14),
    (r"\brvss\b", 14),
    (r"integrated fixed tower", 14),
    (r"autonomous surveillance tower", 14),
    (r"fixed surveillance camera", 12),
    (r"stationary surveillance", 11),
    (r"fixed camera", 9),
    (r"unattended camera", 12),
    (r"motion[- ]triggered", 11),
    (r"camera trap", 11),
    (r"automatic border surveillance", 12),
    (r"automated border surveillance", 12),
    (r"continuous surveillance", 10),
    (r"continuous recording", 9),
    (r"\bcctv\b", 10),
    (r"surveillance camera", 8),
    (r"surveillance system", 7),
    (r"monitoring system", 6),
    (r"electronic fence", 9),
    (r"electronic barrier", 9),

    # Thermal / IR / night vision
    (r"thermal camera", 8),
    (r"thermal imaging", 8),
    (r"thermal detection", 8),
    (r"infrared camera", 8),
    (r"infra-red camera", 8),
    (r"night vision", 8),
    (r"\bflir\b", 8),
    (r"ir sensor", 7),

    # Drone: solo gana puntos fuertes cuando el texto indica uso autónomo,
    # surveillance continuo, thermal/AI o sistema remoto.
    (r"autonomous drone", 10),
    (r"unmanned surveillance", 10),
    (r"uncrewed surveillance", 10),
    (r"drone.*thermal", 8),
    (r"drone.*night vision", 8),
    (r"drone.*artificial intelligence", 9),
    (r"drone.*\bai\b", 7),
    (r"drone surveillance", 5),

    # Bodycam: se permite como captura continua, pero con peso menor.
    (r"continuous bodycam", 7),
    (r"body[- ]worn camera", 5),
    (r"body camera", 5),

    # Español / portugués
    (r"videovigilancia", 9),
    (r"cámara fija", 11),
    (r"camara fija", 11),
    (r"cámara de vigilancia", 9),
    (r"camara de vigilancia", 9),
    (r"cámara térmica", 8),
    (r"camara termica", 8),
    (r"visión nocturna", 8),
    (r"vision nocturna", 8),
    (r"visión infrarroja", 8),
    (r"vision infrarroja", 8),
    (r"vigilancia continua", 10),
    (r"vigilancia remota", 9),
    (r"monitoramento de fronteiras", 9),
    (r"câmera de longo alcance", 9),
    (r"camera de longo alcance", 9),
    (r"visão termal", 8),
    (r"visao termal", 8),
]

HARD_REJECT_PATTERNS = [
    # Captura claramente editorial/manual que no sirve para este corpus.
    (r"handheld", "handheld"),
    (r"hand[- ]held", "handheld"),
    (r"selfie", "selfie"),
    (r"phone footage", "phone"),
    (r"cellphone footage", "phone"),

    # Mediación periodística / TV. Esto elimina una gran parte del material
    # que normalmente introduce logos, zócalos y lower thirds.
    (r"\bnews\b", "news"),
    (r"noticias", "news"),
    (r"newscast", "news"),
    (r"reportaje", "news"),
    (r"reporter", "news"),
    (r"breaking", "news"),
    (r"live update", "news"),
    (r"reuters", "news"),
    (r"associated press", "news"),
    (r"\bafp\b", "news"),
    (r"\bcnn\b", "news"),
    (r"\bbbc\b", "news"),
    (r"fox news", "news"),
    (r"sky news", "news"),
    (r"euronews", "news"),
    (r"dw news", "news"),
    (r"al jazeera", "news"),
    (r"france 24", "news"),
    (r"usa today", "news"),
    (r"newsnation", "news"),
    (r"telemundo", "news"),
    (r"univision", "news"),
    (r"tvperu", "news"),
    (r"t13", "news"),
    (r"mega noticias", "news"),
    (r"chv noticias", "news"),
    (r"24 horas", "news"),
    (r"diario libre", "news"),
    (r"cdn 37", "news"),
    (r"visionrdn", "news"),
    (r"\bpress\b", "press"),
    (r"journalist", "press"),
    (r"broadcast", "broadcast"),
    (r"television", "broadcast"),
    (r"commentary", "commentary"),
    (r"reaction", "commentary"),
]


BORDER_PATTERNS = [
    r"\bborder\b", r"\bfrontier\b", r"boundary", r"crossing",
    r"migrant", r"refugee", r"asylum", r"granica", r"pasien",
    r"frontera", r"σύνορ", r"migration",
]

OFFICIAL_UPLOADER_HINTS = [
    "vsat",
    "valstybės sienos apsaugos tarnyba",
    "straż graniczna",
    "straz graniczna",
    "border guard",
    "customs and border protection",
    "border patrol",
    "frontex",
    "guardia civil",
    "policía",
    "police",
    "government",
    "ministry",
]

COUNTRY_HINTS = {
    # LATINOAMÉRICA
    "mexico": ["mexico", "méxico", "mexican", "tijuana", "ciudad juarez", "juárez", "suchiate"],
    "guatemala": ["guatemala", "guatemalan", "pedro de alvarado", "tecun uman", "tecún umán"],
    "belize": ["belize", "belice"],
    "el_salvador": ["el salvador", "salvadoran", "la hachadura"],
    "honduras": ["honduras", "honduran"],
    "nicaragua": ["nicaragua", "nicaraguan"],
    "costa_rica": ["costa rica", "costa rican"],
    "panama": ["panama", "panamá", "darien", "darién", "senafront"],
    "colombia": ["colombia", "colombian", "cucuta", "cúcuta"],
    "venezuela": ["venezuela", "venezuelan"],
    "ecuador": ["ecuador", "ecuadorian"],
    "peru": ["peru", "perú", "peruvian", "tacna", "tumbes", "migraciones peru"],
    "bolivia": ["bolivia", "bolivian", "pisiga", "desaguadero"],
    "chile": ["chile", "chilean", "colchane", "chacalluta", "arica"],
    "argentina": ["argentina", "argentine", "gendarmeria", "gendarmería"],
    "paraguay": ["paraguay", "paraguayan"],
    "uruguay": ["uruguay", "uruguayan"],
    "brazil": ["brazil", "brasil", "brazilian", "sisfron", "exército brasileiro", "exercito brasileiro"],
    "dominican_republic": ["dominican republic", "república dominicana", "republica dominicana", "dajabon", "dajabón", "cesfront"],
    "haiti": ["haiti", "haití", "haitian", "masacre river", "río masacre", "rio masacre"],

    # NORTEAMÉRICA
    "usa": ["united states", "u.s.", "usa", "cbp", "border patrol", "customs and border protection", "rio grande"],
    "canada": ["canada", "canadian"],

    # EUROPA
    "lithuania": ["lithuania", "lithuanian", "lietuva", "vsat", "lietuvos"],
    "belarus": ["belarus", "belarusian", "baltarus"],
    "poland": ["poland", "polish", "polska", "straż graniczna", "straz graniczna"],
    "latvia": ["latvia", "latvian", "latvija"],
    "greece": ["greece", "greek", "evros", "aegean", "ελλάδα", "εβρος"],
    "turkey": ["turkey", "turkish", "türkiye", "turkiye"],
    "spain": ["spain", "spanish", "ceuta", "melilla", "españa", "espana"],
    "france": ["france", "french", "calais"],
    "uk": ["united kingdom", "britain", "british", "english channel", "dover", "border force"],
    "finland": ["finland", "finnish", "suomi"],
    "estonia": ["estonia", "estonian", "eesti"],
    "hungary": ["hungary", "hungarian"],
    "croatia": ["croatia", "croatian", "hrvatska"],
    "serbia": ["serbia", "serbian", "srbija"],
    "bosnia": ["bosnia", "bosnian"],

    # ÁFRICA
    "south_africa": ["south africa", "south african", "border management authority", "bma"],
    "zimbabwe": ["zimbabwe", "zimbabwean", "beitbridge", "beit bridge"],
    "mozambique": ["mozambique", "mozambican"],
    "morocco": ["morocco", "moroccan", "marruecos"],
    "algeria": ["algeria", "algerian"],
    "tunisia": ["tunisia", "tunisian"],
    "libya": ["libya", "libyan"],
    "kenya": ["kenya", "kenyan"],
    "somalia": ["somalia", "somali"],

    # ASIA
    "india": ["india", "indian", "bsf", "cibms"],
    "bangladesh": ["bangladesh", "bangladeshi"],
    "pakistan": ["pakistan", "pakistani"],
    "thailand": ["thailand", "thai", "aranyaprathet"],
    "myanmar": ["myanmar", "burma", "burmese"],
    "cambodia": ["cambodia", "cambodian"],
    "korea": ["korea", "korean", "dmz"],

    # OCEANÍA
    "australia": ["australia", "australian", "border force", "operation resolute", "bluebottle"],
    "solomon_islands": ["solomon islands", "solomon island", "rsipf"],
}

LATAM_COUNTRIES = {
    "mexico", "guatemala", "belize", "el_salvador", "honduras", "nicaragua",
    "costa_rica", "panama", "colombia", "venezuela", "ecuador", "peru", "bolivia",
    "chile", "argentina", "paraguay", "uruguay", "brazil", "dominican_republic", "haiti"
}

LOW_PRIORITY_COUNTRIES = {"lithuania", "belarus", "usa", "greece"}

CONTINENT_BY_COUNTRY = {
    **{c: "latin_america" for c in LATAM_COUNTRIES},
    "usa": "north_america", "canada": "north_america",
    "lithuania": "europe", "belarus": "europe", "poland": "europe", "latvia": "europe",
    "greece": "europe", "turkey": "europe_asia", "spain": "europe", "france": "europe",
    "uk": "europe", "finland": "europe", "estonia": "europe", "hungary": "europe",
    "croatia": "europe", "serbia": "europe", "bosnia": "europe",
    "south_africa": "africa", "zimbabwe": "africa", "mozambique": "africa",
    "morocco": "africa", "algeria": "africa", "tunisia": "africa", "libya": "africa",
    "kenya": "africa", "somalia": "africa",
    "india": "asia", "bangladesh": "asia", "pakistan": "asia", "thailand": "asia",
    "myanmar": "asia", "cambodia": "asia", "korea": "asia",
    "australia": "oceania", "solomon_islands": "oceania",
}


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150 Safari/537.36"
)

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": USER_AGENT})


# ============================================================
# DATOS
# ============================================================

@dataclass
class VideoCandidate:
    url: str
    title: str = ""
    description: str = ""
    uploader: str = ""
    source_page: str = ""
    duration: Optional[float] = None
    capture_score: int = 0
    capture_hits: str = ""
    border_score: int = 0
    official_score: int = 0
    country: str = "unknown"
    reason: str = ""


@dataclass
class FrameCandidate:
    video_url: str
    source_page: str
    title: str
    uploader: str
    country: str
    capture_score: int
    capture_hits: str
    timestamp_seconds: float
    person_count: int
    person_conf_max: float
    person_conf_mean: float
    person_area_max: float
    sharpness: float
    camera_motion_norm: float
    overlay_penalty: float
    total_score: float
    frame_path: str = ""


# ============================================================
# UTILIDADES
# ============================================================

def norm_text(*parts: Any) -> str:
    return " ".join(str(x or "") for x in parts).lower()


def stable_id(text: str, n: int = 12) -> str:
    return hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()[:n]


def write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def ydl_opts_base() -> Dict[str, Any]:
    return {
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": True,
        "noplaylist": True,
        "socket_timeout": 20,
        "retries": 3,
        "fragment_retries": 3,
        "http_headers": {"User-Agent": USER_AGENT},
    }


def search_youtube(query: str, n: int) -> List[str]:
    opts = ydl_opts_base()
    opts.update({"extract_flat": True, "skip_download": True})
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"ytsearch{n}:{query}", download=False)

    out = []
    if not info:
        return out

    for entry in info.get("entries") or []:
        if not entry:
            continue
        vid = entry.get("id")
        url = entry.get("webpage_url") or entry.get("url")
        if url and str(url).startswith("http"):
            out.append(str(url))
        elif vid:
            out.append(f"https://www.youtube.com/watch?v={vid}")

    return list(dict.fromkeys(out))


def get_metadata(url: str) -> Optional[Dict[str, Any]]:
    opts = ydl_opts_base()
    opts["skip_download"] = True
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception:
        return None

    if not info:
        return None

    if info.get("_type") == "playlist":
        entries = [e for e in (info.get("entries") or []) if e]
        if not entries:
            return None
        info = entries[0]

    return info


def extract_video_links_from_page(url: str) -> Tuple[List[str], str]:
    try:
        r = SESSION.get(url, timeout=20)
        r.raise_for_status()
    except Exception:
        return [], ""

    soup = BeautifulSoup(r.text, "html.parser")
    page_text = soup.get_text(" ", strip=True)
    links = []

    for tag in soup.find_all(["a", "iframe", "source", "video"]):
        raw = tag.get("href") or tag.get("src") or tag.get("data-src")
        if not raw:
            continue

        full = urljoin(url, raw)
        low = full.lower()

        if "youtube.com/embed/" in low:
            vid = full.split("youtube.com/embed/", 1)[1].split("?", 1)[0].split("/", 1)[0]
            full = f"https://www.youtube.com/watch?v={vid}"

        if (
            "youtube.com/watch" in full
            or "youtu.be/" in full
            or low.endswith((".mp4", ".webm", ".mov", ".m4v"))
        ):
            links.append(full)

    return list(dict.fromkeys(links)), page_text


def score_capture(text: str) -> Tuple[int, List[str]]:
    score = 0
    hits = []
    for pattern, value in AUTOMATIC_PATTERNS:
        if re.search(pattern, text, flags=re.I):
            score += value
            hits.append(f"{pattern}:{value:+d}")
    return score, hits


def hard_reject(text: str) -> str:
    for pattern, reason in HARD_REJECT_PATTERNS:
        if re.search(pattern, text, flags=re.I):
            return reason
    return ""


def score_border(text: str) -> int:
    return sum(1 for p in BORDER_PATTERNS if re.search(p, text, flags=re.I))


def score_official(uploader: str, source_page: str) -> int:
    score = 0
    low = norm_text(uploader, source_page)
    if any(h in low for h in OFFICIAL_UPLOADER_HINTS):
        score += 4

    host = urlparse(source_page).netloc.lower()
    if host.endswith(".gov") or ".gov." in host or "lrv.lt" in host or "gov.pl" in host:
        score += 4

    return score


def infer_country(text: str) -> str:
    low = text.lower()
    scores = []
    for country, hints in COUNTRY_HINTS.items():
        n = sum(1 for hint in hints if hint in low)
        if n:
            scores.append((n, country))
    if not scores:
        return "unknown"
    scores.sort(reverse=True)
    return scores[0][1]


def build_candidate(url: str, source_page: str = "", page_text: str = "") -> Optional[VideoCandidate]:
    info = get_metadata(url)
    if not info:
        return None

    title = str(info.get("title") or "")
    desc = str(info.get("description") or "")
    uploader = str(info.get("uploader") or info.get("channel") or "")
    webpage_url = str(info.get("webpage_url") or url)
    duration = info.get("duration")

    text = norm_text(title, desc, uploader, source_page, page_text, webpage_url)
    capture_score, hits = score_capture(text)
    border_score = score_border(text)
    country = infer_country(text)

    return VideoCandidate(
        url=webpage_url,
        title=title,
        description=desc[:4000],
        uploader=uploader,
        source_page=source_page,
        duration=float(duration) if isinstance(duration, (int, float)) else None,
        capture_score=capture_score,
        capture_hits=" | ".join(hits),
        border_score=border_score,
        official_score=score_official(uploader, source_page),
        country=country,
    )


def accept_candidate(c: VideoCandidate, max_duration: float) -> Tuple[bool, str]:
    if c.country in ABSOLUTE_EXCLUDE_COUNTRIES:
        return False, f"excluded country: {c.country}"

    raw = norm_text(c.title, c.description, c.uploader, c.source_page, c.url)
    # Segunda barrera por si la inferencia de país falla.
    if re.search(r"\bpoland\b|\bpolish\b|\bpolska\b|straż graniczna|straz graniczna", raw, flags=re.I):
        return False, "excluded country: poland"
    if re.search(r"\blatvia\b|\blatvian\b|\blatvija\b", raw, flags=re.I):
        return False, "excluded country: latvia"

    if c.duration and c.duration > max_duration:
        return False, "too long"

    text = norm_text(c.title, c.description, c.uploader, c.source_page)
    rejection = hard_reject(text)
    if rejection:
        return False, f"hard reject: {rejection}"

    if c.border_score < 1:
        return False, "weak border evidence"

    # Estricto: no basta con decir "thermal camera" una sola vez.
    # Exigimos evidencia más fuerte de sistema de vigilancia.
    if c.capture_score < 7:
        return False, f"weak unattended evidence ({c.capture_score})"

    return True, "accepted"


def diversify(
    candidates: List[VideoCandidate],
    max_per_country: int,
    avoid_countries: List[str],
    max_videos: int,
) -> List[VideoCandidate]:
    """
    Prioridad:
    1) Latinoamérica.
    2) Países no usados/saturados.
    3) Diversidad continental.
    4) Evidencia de captura no-editorial y cámara/sistema técnico.

    Polonia y Latvia quedan bloqueadas siempre.
    """
    avoid = {x.strip().lower() for x in avoid_countries if x.strip()}
    avoid |= ABSOLUTE_EXCLUDE_COUNTRIES

    def rank(c: VideoCandidate):
        latam = 1 if c.country in LATAM_COUNTRIES else 0
        low_priority = 1 if c.country in LOW_PRIORITY_COUNTRIES else 0
        known = 1 if c.country != "unknown" else 0
        return (
            latam,
            -low_priority,
            known,
            c.capture_score,
            c.official_score,
            c.border_score,
        )

    ranked = sorted(candidates, key=rank, reverse=True)
    chosen: List[VideoCandidate] = []
    country_counts: Dict[str, int] = {}
    continent_counts: Dict[str, int] = {}

    # Primera pasada: diversidad fuerte. LATAM puede tener un video extra por país.
    for c in ranked:
        if c.country in avoid:
            continue

        continent = CONTINENT_BY_COUNTRY.get(c.country, "unknown")
        limit = max_per_country + (1 if c.country in LATAM_COUNTRIES else 0)
        if c.country == "unknown":
            limit = 1

        if country_counts.get(c.country, 0) >= limit:
            continue

        # Evita que un solo continente monopolice. LATAM tiene cuota más alta.
        continent_cap = max(6, max_videos // 2) if continent == "latin_america" else max(3, max_videos // 6)
        if continent_counts.get(continent, 0) >= continent_cap:
            continue

        chosen.append(c)
        country_counts[c.country] = country_counts.get(c.country, 0) + 1
        continent_counts[continent] = continent_counts.get(continent, 0) + 1

        if len(chosen) >= max_videos:
            break

    # Segunda pasada: rellena sin romper límite por país, si faltan resultados.
    if len(chosen) < max_videos:
        for c in ranked:
            if c in chosen or c.country in avoid:
                continue
            limit = max_per_country + (1 if c.country in LATAM_COUNTRIES else 0)
            if c.country == "unknown":
                limit = 1
            if country_counts.get(c.country, 0) >= limit:
                continue
            chosen.append(c)
            country_counts[c.country] = country_counts.get(c.country, 0) + 1
            if len(chosen) >= max_videos:
                break

    return chosen


# ============================================================
# VIDEO
# ============================================================

def download_video(c: VideoCandidate, temp_dir: Path, max_height: int) -> Optional[Path]:
    prefix = stable_id(c.url)
    outtmpl = str(temp_dir / f"{prefix}_%(id)s.%(ext)s")

    opts = ydl_opts_base()
    opts.update({
        "format": (
            f"bestvideo[height<={max_height}][ext=mp4]/"
            f"best[height<={max_height}][ext=mp4]/"
            f"bestvideo[height<={max_height}]/best[height<={max_height}]"
        ),
        "outtmpl": outtmpl,
        "restrictfilenames": True,
        "nopart": True,
        "overwrites": True,
    })

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(c.url, download=True)
            if not info:
                return None

            paths = []
            for x in info.get("requested_downloads") or []:
                fp = x.get("filepath")
                if fp:
                    paths.append(Path(fp))

            fp = info.get("filepath") or info.get("_filename")
            if fp:
                paths.append(Path(fp))

        for p in paths:
            if p.exists():
                return p

        matches = sorted(
            temp_dir.glob(prefix + "_*"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        return matches[0] if matches else None

    except Exception:
        return None


# ============================================================
# ANÁLISIS VISUAL
# ============================================================

def sharpness(frame: np.ndarray) -> float:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def dhash(frame: np.ndarray, size: int = 8) -> int:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    small = cv2.resize(gray, (size + 1, size), interpolation=cv2.INTER_AREA)
    diff = small[:, 1:] > small[:, :-1]

    v = 0
    for bit in diff.flatten():
        v = (v << 1) | int(bit)
    return v


def hamming(a: int, b: int) -> int:
    return int((a ^ b).bit_count())


def detect_people(model: YOLO, frame: np.ndarray, conf: float):
    result = model.predict(
        source=frame,
        classes=[0],
        conf=conf,
        verbose=False,
        imgsz=960,
    )[0]

    boxes = result.boxes
    if boxes is None or len(boxes) == 0:
        return 0, 0.0, 0.0, 0.0

    confs = boxes.conf.detach().cpu().numpy().astype(float)
    xyxy = boxes.xyxy.detach().cpu().numpy().astype(float)

    h, w = frame.shape[:2]
    total = max(float(h * w), 1.0)

    areas = []
    for x1, y1, x2, y2 in xyxy:
        areas.append(
            max(0.0, x2 - x1) * max(0.0, y2 - y1) / total
        )

    return (
        len(confs),
        float(np.max(confs)),
        float(np.mean(confs)),
        float(max(areas) if areas else 0.0),
    )


def camera_motion_norm(prev_frame: Optional[np.ndarray], frame: np.ndarray) -> float:
    if prev_frame is None:
        return 0.0

    def prep(img):
        h, w = img.shape[:2]
        if w > 640:
            s = 640.0 / w
            img = cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
        return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    a = prep(prev_frame)
    b = prep(frame)

    pts = cv2.goodFeaturesToTrack(
        a,
        maxCorners=250,
        qualityLevel=0.01,
        minDistance=12,
        blockSize=7,
    )

    if pts is None or len(pts) < 15:
        return 0.0

    nxt, status, _ = cv2.calcOpticalFlowPyrLK(
        a,
        b,
        pts,
        None,
        winSize=(21, 21),
        maxLevel=3,
        criteria=(
            cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT,
            30,
            0.01,
        ),
    )

    if nxt is None or status is None:
        return 0.0

    good_a = pts[status.flatten() == 1].reshape(-1, 2)
    good_b = nxt[status.flatten() == 1].reshape(-1, 2)

    if len(good_a) < 12:
        return 0.0

    displacement = np.linalg.norm(good_b - good_a, axis=1)
    median_px = float(np.median(displacement))

    h, w = a.shape[:2]
    return median_px / max(math.hypot(w, h), 1.0)


def text_like_density(region: np.ndarray) -> float:
    if region.size == 0:
        return 0.0

    gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 80, 180)

    # Une trazos de letras en líneas.
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (11, 3))
    merged = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel)

    num, _, stats, _ = cv2.connectedComponentsWithStats(merged, 8)

    area_total = float(region.shape[0] * region.shape[1])
    suspect = 0.0

    for i in range(1, num):
        _, _, w, h, area = stats[i]
        if area < 12 or h <= 1:
            continue

        aspect = w / h
        if 1.7 < aspect < 30 and h < region.shape[0] * 0.45:
            suspect += area

    return suspect / max(area_total, 1.0)


def _solid_rectangles_penalty(region: np.ndarray, full_frame_area: float, corner: bool = False) -> float:
    """
    Detecta bloques gráficos muy planos.

    Idea central: si una región relativamente grande está compuesta por píxeles
    casi idénticos y forma un bloque rectangular compacto, es muy probable que sea
    un logo, zócalo, etiqueta o franja añadida al video.

    Se usa color cuantizado + componentes conectados + varianza real del color para
    evitar confundir fácilmente cielo/terreno con un rectángulo gráfico perfecto.
    """
    if region.size == 0:
        return 0.0

    h, w = region.shape[:2]
    if h < 8 or w < 8:
        return 0.0

    # Reduce coste, manteniendo estructura gráfica.
    scale = min(1.0, 360.0 / max(w, 1))
    work = region
    if scale < 1.0:
        work = cv2.resize(region, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

    # Cuantiza suavemente a pasos de 8 para agrupar colores casi iguales.
    q = (work // 8).astype(np.uint8)
    flat = q.reshape(-1, 3)
    colors, counts = np.unique(flat, axis=0, return_counts=True)
    if len(counts) == 0:
        return 0.0

    order = np.argsort(counts)[::-1][:4]
    penalty = 0.0

    for idx in order:
        frac = float(counts[idx]) / float(len(flat))
        # Un color debe dominar una parte apreciable de la zona.
        if frac < (0.10 if corner else 0.18):
            continue

        col = colors[idx]
        mask = np.all(q == col, axis=2).astype(np.uint8) * 255
        mask = cv2.morphologyEx(
            mask,
            cv2.MORPH_CLOSE,
            cv2.getStructuringElement(cv2.MORPH_RECT, (5, 3)),
        )

        num, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
        for i in range(1, num):
            x, y, ww, hh, area = stats[i]
            if ww < 10 or hh < 5:
                continue

            bbox_area = float(max(ww * hh, 1))
            fill = float(area) / bbox_area
            region_fraction = float(area) / float(max(mask.shape[0] * mask.shape[1], 1))
            frame_fraction = region_fraction * (region.size / 3.0) / max(full_frame_area, 1.0)
            aspect = ww / max(hh, 1)

            # Si el mismo tono ocupa casi toda la zona, normalmente es fondo real
            # (cielo, noche, thermal/IR negro) y no un logo. Las barras completas
            # se detectan aparte con _letterbox_or_banner_penalty().
            covers_zone = (
                x <= 2 and y <= 2
                and x + ww >= mask.shape[1] - 2
                and y + hh >= mask.shape[0] - 2
            )
            if region_fraction > 0.72 or covers_zone:
                continue

            # Logos pequeños en esquina: umbral menor. Franjas: área mayor.
            min_frame_frac = 0.0035 if corner else 0.010
            if frame_fraction < min_frame_frac:
                continue
            if fill < 0.78:
                continue
            if aspect < 1.25 and not corner:
                continue

            # Verifica que el bloque sea realmente plano en el RGB original.
            # Mapear bbox al tamaño original de region.
            inv = 1.0 / scale
            ox1 = max(0, int(x * inv))
            oy1 = max(0, int(y * inv))
            ox2 = min(region.shape[1], int((x + ww) * inv))
            oy2 = min(region.shape[0], int((y + hh) * inv))
            patch = region[oy1:oy2, ox1:ox2]
            if patch.size == 0:
                continue

            channel_std = np.std(patch.reshape(-1, 3), axis=0)
            mean_std = float(np.mean(channel_std))

            # Gráfico/overlay suele tener varianza de color muy baja.
            if mean_std <= 10.0:
                penalty += 2.5 if corner else 3.5
            elif mean_std <= 16.0 and fill > 0.90:
                penalty += 1.5

    return penalty


def _letterbox_or_banner_penalty(region: np.ndarray) -> float:
    if region.size == 0:
        return 0.0
    gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
    row_std = np.std(gray, axis=1)
    row_mean = np.mean(gray, axis=1)

    very_flat = row_std < 6.0
    extreme = (row_mean < 24.0) | (row_mean > 232.0)
    ratio = float(np.mean(very_flat & extreme))

    if ratio > 0.45:
        return 4.0
    if ratio > 0.25:
        return 2.5
    if ratio > 0.12:
        return 1.0
    return 0.0


def overlay_penalty(frame: np.ndarray) -> float:
    """
    Filtro MUY estricto de imagen limpia.

    Rechaza probable:
    - logo / watermark de esquina
    - texto sobreimpreso
    - lower third / bajada
    - barra superior o inferior
    - letterbox editorial
    - bloques grandes de píxeles casi iguales con geometría rectangular

    Importante: no recorta ni borra marcas. Descarta el frame completo.
    """
    h, w = frame.shape[:2]
    full_area = float(max(h * w, 1))

    zones = {
        "top": frame[:max(1, int(h * 0.20)), :],
        "bottom": frame[int(h * 0.74):, :],
        "left": frame[:, :max(1, int(w * 0.16))],
        "right": frame[:, int(w * 0.84):],
        "tl": frame[:int(h * 0.28), :int(w * 0.28)],
        "tr": frame[:int(h * 0.28), int(w * 0.72):],
        "bl": frame[int(h * 0.72):, :int(w * 0.32)],
        "br": frame[int(h * 0.72):, int(w * 0.68):],
    }

    penalty = 0.0

    # Thermal/night-vision suelen tener grandes zonas negras casi uniformes.
    # No deben confundirse con letterbox. El detector de logos/texto sigue activo.
    gray_full = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    hsv_full = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    dark_scene = float(np.mean(gray_full < 60)) > 0.62
    low_saturation_scene = float(np.mean(hsv_full[:, :, 1] < 35)) > 0.72
    thermal_like_scene = dark_scene and low_saturation_scene

    # 1) Texto / lower thirds / rótulos.
    for key in ("top", "bottom"):
        d = text_like_density(zones[key])
        if d > 0.008:
            penalty += 1.4
        if d > 0.018:
            penalty += 1.8
        if d > 0.035:
            penalty += 2.0

        if not thermal_like_scene:
            penalty += _letterbox_or_banner_penalty(zones[key])
        penalty += _solid_rectangles_penalty(zones[key], full_area, corner=False)

    # 2) Logos/watermarks en las cuatro esquinas.
    for key in ("tl", "tr", "bl", "br"):
        d = text_like_density(zones[key])
        if d > 0.008:
            penalty += 1.2
        if d > 0.018:
            penalty += 1.6

        penalty += _solid_rectangles_penalty(zones[key], full_area, corner=True)

    # 3) Marcas verticales o sidebars.
    for key in ("left", "right"):
        penalty += 0.7 * _solid_rectangles_penalty(zones[key], full_area, corner=False)

    return penalty


def frame_score(
    people: int,
    conf_max: float,
    conf_mean: float,
    area_max: float,
    sharp: float,
    motion: float,
    capture_score: int,
    official_score: int,
    overlay: float,
) -> float:

    # Favorece cámara estable.
    if motion <= 0.0025:
        stability = 2.0
    elif motion <= 0.005:
        stability = 1.0
    elif motion <= 0.008:
        stability = 0.0
    else:
        stability = -2.0

    return (
        min(math.log1p(people) * 1.8, 4.0)
        + conf_max * 2.5
        + conf_mean * 1.2
        + min(math.sqrt(max(area_max, 0.0)) * 7.5, 2.5)
        + min(math.log1p(max(sharp, 0.0)) / 2.8, 2.6)
        + stability
        + min(capture_score, 20) * 0.30
        + min(official_score, 8) * 0.20
        - overlay * 3.0
    )


def scan_video(
    video_path: Path,
    c: VideoCandidate,
    model: YOLO,
    args: argparse.Namespace,
    frames_dir: Path,
) -> List[FrameCandidate]:

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return []

    fps = float(cap.get(cv2.CAP_PROP_FPS) or 25.0)
    count_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)

    duration = (
        count_frames / fps
        if fps > 0 and count_frames > 0
        else 0.0
    )

    if duration > 0:
        times = np.arange(
            0.0,
            duration,
            max(args.sample_seconds, 0.25),
            dtype=float,
        ).tolist()

        if len(times) > args.max_sampled_frames:
            ids = np.linspace(
                0,
                len(times) - 1,
                args.max_sampled_frames,
            ).astype(int)
            times = [times[i] for i in ids]
    else:
        times = [
            i * args.sample_seconds
            for i in range(args.max_sampled_frames)
        ]

    candidates = []
    hashes = []
    prev = None

    for t in times:
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
        ok, frame = cap.read()

        if not ok or frame is None:
            continue

        overlay = overlay_penalty(frame)

        # Muy estricto: si parece tener texto/logo/banner, fuera.
        if overlay > args.max_overlay_penalty:
            prev = frame
            continue

        people, cmax, cmean, area = detect_people(
            model,
            frame,
            args.min_person_conf,
        )

        if people < 1 or area < args.min_person_area:
            prev = frame
            continue

        motion = camera_motion_norm(prev, frame)
        prev = frame

        # Una cámara que se desplaza mucho tiene más riesgo de haber sido operada.
        if motion > args.max_camera_motion:
            continue

        ph = dhash(frame)
        if any(hamming(ph, old) <= 5 for old in hashes):
            continue
        hashes.append(ph)

        sh = sharpness(frame)

        total = frame_score(
            people,
            cmax,
            cmean,
            area,
            sh,
            motion,
            c.capture_score,
            c.official_score,
            overlay,
        )

        row = FrameCandidate(
            video_url=c.url,
            source_page=c.source_page,
            title=c.title,
            uploader=c.uploader,
            country=c.country,
            capture_score=c.capture_score,
            capture_hits=c.capture_hits,
            timestamp_seconds=float(t),
            person_count=people,
            person_conf_max=cmax,
            person_conf_mean=cmean,
            person_area_max=area,
            sharpness=sh,
            camera_motion_norm=motion,
            overlay_penalty=overlay,
            total_score=total,
        )

        candidates.append((row, frame.copy()))

    cap.release()

    candidates.sort(
        key=lambda x: x[0].total_score,
        reverse=True,
    )

    # EXACTAMENTE máximo 6 por video.
    candidates = candidates[:args.max_frames_per_video]

    output = []
    vid = stable_id(c.url, 10)

    for rank, (row, frame) in enumerate(candidates, 1):
        filename = (
            f"{c.country}_{vid}_"
            f"r{rank:02d}_"
            f"t{row.timestamp_seconds:08.2f}_"
            f"p{row.person_count:02d}_"
            f"s{row.total_score:05.2f}.png"
        )

        path = frames_dir / filename
        cv2.imwrite(
            str(path),
            frame,
            [cv2.IMWRITE_PNG_COMPRESSION, 2],
        )

        row.frame_path = str(path)
        output.append(row)

    return output


# ============================================================
# CONTACT SHEETS
# ============================================================

def make_contact_sheet(rows: List[FrameCandidate], out: Path) -> None:
    rows = [
        r for r in rows
        if r.frame_path and Path(r.frame_path).exists()
    ]

    if not rows:
        return

    tw, th = 420, 260
    label_h = 62
    cols = 3
    thumbs = []

    for r in rows:
        img = cv2.imread(r.frame_path)
        if img is None:
            continue

        h, w = img.shape[:2]
        scale = min(tw / w, th / h)
        rw = max(1, int(w * scale))
        rh = max(1, int(h * scale))

        resized = cv2.resize(
            img,
            (rw, rh),
            interpolation=cv2.INTER_AREA,
        )

        canvas = np.zeros(
            (th + label_h, tw, 3),
            dtype=np.uint8,
        )

        x = (tw - rw) // 2
        y = (th - rh) // 2
        canvas[y:y+rh, x:x+rw] = resized

        line1 = (
            f"{r.country} | people {r.person_count} | "
            f"score {r.total_score:.2f}"
        )
        line2 = (
            f"motion {r.camera_motion_norm:.4f} | "
            f"overlay {r.overlay_penalty:.2f} | "
            f"t {r.timestamp_seconds:.1f}s"
        )

        cv2.putText(
            canvas,
            line1,
            (8, th + 22),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.43,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )

        cv2.putText(
            canvas,
            line2,
            (8, th + 46),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.40,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )

        thumbs.append(canvas)

    if not thumbs:
        return

    nrows = math.ceil(len(thumbs) / cols)

    sheet = np.zeros(
        (nrows * (th + label_h), cols * tw, 3),
        dtype=np.uint8,
    )

    for i, thumb in enumerate(thumbs):
        rr = i // cols
        cc = i % cols

        y = rr * (th + label_h)
        x = cc * tw

        sheet[
            y:y + th + label_h,
            x:x + tw
        ] = thumb

    cv2.imwrite(
        str(out),
        sheet,
        [cv2.IMWRITE_JPEG_QUALITY, 94],
    )


# ============================================================
# MAIN
# ============================================================

def parse_args():
    p = argparse.ArgumentParser()

    p.add_argument("--results-per-query", type=int, default=30)
    p.add_argument("--max-videos", type=int, default=180)
    p.add_argument("--max-duration", type=float, default=1800)
    p.add_argument("--sample-seconds", type=float, default=0.8)
    p.add_argument("--max-sampled-frames", type=int, default=1200)

    # Pedido del usuario.
    p.add_argument("--max-frames-per-video", type=int, default=6)

    p.add_argument("--min-person-conf", type=float, default=0.28)
    p.add_argument("--min-person-area", type=float, default=0.0012)

    # Estricto para estabilidad y overlays.
    p.add_argument("--max-camera-motion", type=float, default=0.008)
    p.add_argument("--max-overlay-penalty", type=float, default=0.55)

    # Diversidad geográfica.
    p.add_argument("--max-per-country", type=int, default=2)
    p.add_argument(
        "--avoid-countries",
        default="poland,latvia",
        help='Países a excluir. Poland y Latvia siempre se excluyen.',
    )

    p.add_argument("--max-height", type=int, default=1080)
    p.add_argument("--model", default="yolo11n.pt")
    p.add_argument("--output", default="")

    return p.parse_args()


def save_csv(path: Path, rows: List[FrameCandidate]) -> None:
    fields = list(FrameCandidate.__dataclass_fields__.keys())

    with path.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()

        for row in rows:
            w.writerow(asdict(row))


def main():
    args = parse_args()

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    out_dir = Path(
        args.output
        or f"border_clean_latam_world_scan_{stamp}"
    ).resolve()

    frames_dir = out_dir / "frames"
    sheets_dir = out_dir / "contact_sheets"

    frames_dir.mkdir(parents=True, exist_ok=True)
    sheets_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / "run_config.json").write_text(
        json.dumps(
            vars(args),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print("=" * 78)
    print("BORDER CLEAN LATAM + WORLD SCAN")
    print("=" * 78)
    print("OUTPUT              /", out_dir)
    print("MAX FRAMES / VIDEO  /", args.max_frames_per_video)
    print("MAX / COUNTRY       /", args.max_per_country)
    print("MAX OVERLAY PENALTY /", args.max_overlay_penalty)
    print("MAX CAMERA MOTION   /", args.max_camera_motion)
    print()

    model = YOLO(args.model)

    discovered: Dict[str, Tuple[str, str]] = {}

    for url in DIRECT_VIDEO_SEEDS:
        discovered[url] = ("direct_seed", "")

    print("[1/5] OFFICIAL PAGES")

    for page in OFFICIAL_SEED_PAGES:
        print(" PAGE /", page)
        links, page_text = extract_video_links_from_page(page)

        for url in links:
            discovered.setdefault(
                url,
                (page, page_text),
            )

    print("\n[2/5] YOUTUBE SEARCH")

    for i, query in enumerate(SEARCH_QUERIES, 1):
        print(
            f" Q {i:02d}/{len(SEARCH_QUERIES):02d} / {query}"
        )

        try:
            urls = search_youtube(
                query,
                args.results_per_query,
            )
        except Exception as exc:
            print("   SEARCH ERROR /", exc)
            continue

        for url in urls:
            discovered.setdefault(
                url,
                (f"ytsearch:{query}", query),
            )

    print("DISCOVERED /", len(discovered))

    print("\n[3/5] METADATA FILTER")

    accepted_all = []
    rejected = []
    seen = set()

    for i, (url, origin) in enumerate(
        discovered.items(),
        1,
    ):
        print(
            f" META {i:04d}/{len(discovered):04d} / {url}"
        )

        c = build_candidate(
            url,
            source_page=origin[0],
            page_text=origin[1],
        )

        if not c:
            rejected.append({
                "url": url,
                "reason": "metadata unavailable",
            })
            continue

        if c.url in seen:
            continue
        seen.add(c.url)

        ok, reason = accept_candidate(
            c,
            args.max_duration,
        )

        c.reason = reason

        if not ok:
            rejected.append(asdict(c))
            continue

        accepted_all.append(c)

        print(
            f"   ACCEPT / "
            f"{c.country} / "
            f"capture={c.capture_score} / "
            f"{c.title[:80]}"
        )

    avoid = [
        x.strip().lower()
        for x in args.avoid_countries.split(",")
        if x.strip()
    ]

    accepted = diversify(
        accepted_all,
        max_per_country=args.max_per_country,
        avoid_countries=avoid,
        max_videos=args.max_videos,
    )

    write_jsonl(
        out_dir / "videos.jsonl",
        [asdict(c) for c in accepted],
    )

    write_jsonl(
        out_dir / "rejected.jsonl",
        rejected,
    )

    counts: Dict[str, int] = {}
    for c in accepted:
        counts[c.country] = counts.get(c.country, 0) + 1

    print("\nCOUNTRY DISTRIBUTION")
    for country, n in sorted(
        counts.items(),
        key=lambda x: (-x[1], x[0]),
    ):
        print(f" {country:20s} / {n}")

    print("\nVIDEOS TO SCAN /", len(accepted))

    print("\n[4/5] DOWNLOAD + CLEAN FRAME SCAN")

    all_frames = []

    with tempfile.TemporaryDirectory(
        prefix="unattended_clean_scan_"
    ) as tmp:

        temp_dir = Path(tmp)

        for i, c in enumerate(accepted, 1):
            print("\n" + "-" * 78)
            print(
                f"VIDEO {i}/{len(accepted)} / "
                f"{c.country} / {c.title}"
            )
            print("URL     /", c.url)
            print("CAPTURE /", c.capture_score)
            print("EVIDENCE/", c.capture_hits)

            vp = download_video(
                c,
                temp_dir,
                args.max_height,
            )

            if not vp:
                print("DOWNLOAD FAILED")
                continue

            try:
                print(
                    "FILE /",
                    vp.name,
                    "/",
                    f"{vp.stat().st_size / 1024 / 1024:.1f} MB",
                )
            except Exception:
                pass

            rows = scan_video(
                vp,
                c,
                model,
                args,
                frames_dir,
            )

            print(
                f"CLEAN FRAMES / "
                f"{len(rows)} "
                f"(max {args.max_frames_per_video})"
            )

            all_frames.extend(rows)

            try:
                vp.unlink(missing_ok=True)
            except Exception:
                pass

    print("\n[5/5] FINAL RANKING")

    all_frames.sort(
        key=lambda r: r.total_score,
        reverse=True,
    )

    save_csv(
        out_dir / "candidates.csv",
        all_frames,
    )

    write_jsonl(
        out_dir / "candidates.jsonl",
        [asdict(r) for r in all_frames],
    )

    for start in range(0, len(all_frames), 18):
        batch = all_frames[start:start + 18]

        make_contact_sheet(
            batch,
            sheets_dir
            / f"ranking_{start+1:04d}_{start+len(batch):04d}.jpg",
        )

    print("\n" + "=" * 78)
    print("DONE")
    print("=" * 78)
    print("VIDEOS /", len(accepted))
    print("FRAMES /", len(all_frames))
    print("OUTPUT /", out_dir)
    print("FRAMES /", frames_dir)
    print("SHEETS /", sheets_dir)
    print()
    print("IMPORTANTE:")
    print(
        "La metadata + estabilidad visual ayudan a seleccionar cámaras "
        "no operadas directamente durante la captura, pero no constituyen "
        "prueba histórica absoluta. Revisa source_page + capture_hits."
    )


if __name__ == "__main__":
    main()

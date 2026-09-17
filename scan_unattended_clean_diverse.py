#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
scan_unattended_clean_diverse.py

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
    python scan_unattended_clean_diverse.py \
      --results-per-query 30 \
      --max-videos 180 \
      --sample-seconds 0.8 \
      --max-per-country 2 \
      --avoid-countries "lithuania,poland,belarus,usa,greece"

SALIDA:
    unattended_clean_diverse_scan_YYYYMMDD_HHMMSS/
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
    "https://vsat.lrv.lt/lt/naujienos/",
    "https://www.gov.pl/web/border/video",
]

DIRECT_VIDEO_SEEDS = [
    "https://www.youtube.com/watch?v=nt_jWHYY8nY",
    "https://www.youtube.com/watch?v=kyV0O0Xt7Cg",
    "https://www.youtube.com/watch?v=ELnTwwWCmbc",
    "https://www.youtube.com/watch?v=aNWgvdOjNzU",
    "https://www.youtube.com/watch?v=XXjqNidOI6s",
    "https://youtu.be/xCt5fVnsJOY",
]

SEARCH_QUERIES = [
    # Bálticos / Este
    'Latvia automated border surveillance camera migrants',
    'Latvia Belarus border surveillance camera migrants',
    'Estonia border surveillance camera migrants',
    'Finland Russia border surveillance camera migrants',
    'Lithuania Belarus "vaizdo stebėjimo sistema" migrantai',
    'Poland Belarus "monitoring granicy" migranci',

    # Balcanes / Mediterráneo
    'Croatia Bosnia fixed border surveillance camera migrants',
    'Serbia Hungary border CCTV migrants crossing',
    'Hungary Serbia thermal border surveillance migrants',
    'North Macedonia Greece border surveillance camera migrants',
    'Slovenia Croatia border CCTV migrants',
    'Evros fixed surveillance camera migrants',
    'Ceuta fixed border surveillance camera migrants',
    'Melilla CCTV border migrants crossing',
    'Mediterranean fixed thermal surveillance migrants coast',

    # Europa occidental
    'Calais fixed surveillance camera migrants crossing',
    'English Channel fixed thermal surveillance migrants',
    'France Italy border CCTV migrants crossing',

    # América
    '"Remote Video Surveillance System" migrants border',
    '"RVSS" migrants border crossing',
    'Canada US border fixed surveillance camera migrants',
    'Mexico Guatemala border CCTV migrants crossing',
    'Dominican Republic Haiti border surveillance camera migrants',

    # África
    'South Africa Zimbabwe border CCTV migrants crossing',
    'South Africa Mozambique border surveillance camera migrants',
    'Morocco Algeria border surveillance camera migrants',

    # Asia
    'India Bangladesh border surveillance camera migrants',
    'India Pakistan border CCTV crossing people',
    'Korea DMZ fixed surveillance camera people crossing',

    # Genéricas estrictas
    '"fixed surveillance camera" border migrants',
    '"border CCTV" migrants crossing',
    '"automatic border surveillance" migrants',
    '"automated border surveillance" migrants',
    '"continuous surveillance" border migrants camera',
    '"thermal surveillance camera" border migrants',
    '"electronic barrier" border camera migrants',
    '"unattended camera" border migrants',
]


# ============================================================
# PATRONES DE CAPTURA / RECHAZO
# ============================================================

AUTOMATIC_PATTERNS = [
    (r"remote video surveillance system", 12),
    (r"\brvss\b", 12),
    (r"fixed surveillance camera", 10),
    (r"fixed camera", 7),
    (r"unattended camera", 10),
    (r"automatic border surveillance", 10),
    (r"automated border surveillance", 10),
    (r"continuous surveillance", 8),
    (r"continuous recording", 8),
    (r"\bcctv\b", 8),
    (r"surveillance camera", 7),
    (r"surveillance system", 6),
    (r"monitoring system", 5),
    (r"electronic barrier", 9),
    (r"thermal camera", 5),
    (r"infrared camera", 5),
    (r"infra-red camera", 5),
    (r"motion[- ]triggered", 9),
    (r"camera trap", 9),

    # Lituano / polaco / español / griego
    (r"vaizdo stebėjimo sistema", 11),
    (r"sienos stebėjimo sistema", 11),
    (r"stebėjimo kamer", 8),
    (r"monitoring granicy", 8),
    (r"system monitoringu", 8),
    (r"bariera elektroniczna", 9),
    (r"videovigilancia", 7),
    (r"cámara fija", 9),
    (r"cámara térmica", 5),
    (r"κάμερα επιτήρησης", 7),
    (r"θερμική κάμερα", 5),
]

HARD_REJECT_PATTERNS = [
    # captura operada manualmente
    (r"body[- ]worn", "bodycam"),
    (r"\bbodycam\b", "bodycam"),
    (r"body camera", "bodycam"),
    (r"handheld", "handheld"),
    (r"hand[- ]held", "handheld"),
    (r"\bdrone\b", "drone"),
    (r"\buav\b", "drone"),
    (r"helicopter", "helicopter"),
    (r"aerial footage", "aerial"),
    (r"aircraft", "aircraft"),
    (r"dashcam", "dashcam"),

    # mediación periodística / gráfica
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
    (r"\bpress\b", "press"),
    (r"journalist", "press"),
    (r"broadcast", "broadcast"),
    (r"television", "broadcast"),
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
    "lithuania": ["lithuania", "lithuanian", "lietuva", "vsat", "lietuvos"],
    "belarus": ["belarus", "belarusian", "baltarus"],
    "poland": ["poland", "polish", "polska", "straż graniczna", "straz graniczna"],
    "greece": ["greece", "greek", "evros", "aegean", "ελλάδα", "εβρος"],
    "turkey": ["turkey", "turkish", "türkiye", "turkiye"],
    "spain": ["spain", "spanish", "ceuta", "melilla", "españa", "espana"],
    "morocco": ["morocco", "moroccan", "marruecos"],
    "usa": ["united states", "u.s.", "usa", "cbp", "border patrol", "customs and border protection", "rio grande"],
    "mexico": ["mexico", "mexican", "tijuana", "ciudad juarez", "juárez"],
    "canada": ["canada", "canadian"],
    "latvia": ["latvia", "latvian", "latvija"],
    "estonia": ["estonia", "estonian", "eesti"],
    "finland": ["finland", "finnish", "suomi"],
    "hungary": ["hungary", "hungarian"],
    "croatia": ["croatia", "croatian", "hrvatska"],
    "serbia": ["serbia", "serbian", "srbija"],
    "bosnia": ["bosnia", "bosnian"],
    "slovenia": ["slovenia", "slovenian"],
    "north_macedonia": ["north macedonia", "macedonia", "fyrom"],
    "italy": ["italy", "italian", "lampedusa", "sicily", "sicilia", "italia"],
    "france": ["france", "french", "calais"],
    "uk": ["united kingdom", "britain", "british", "english channel", "dover"],
    "south_africa": ["south africa", "south african"],
    "zimbabwe": ["zimbabwe", "zimbabwean"],
    "mozambique": ["mozambique", "mozambican"],
    "india": ["india", "indian"],
    "bangladesh": ["bangladesh", "bangladeshi"],
    "pakistan": ["pakistan", "pakistani"],
    "korea": ["korea", "korean", "dmz"],
    "dominican_republic": ["dominican republic", "república dominicana", "republica dominicana"],
    "haiti": ["haiti", "haitian"],
    "guatemala": ["guatemala", "guatemalan"],
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

    avoid = {x.strip().lower() for x in avoid_countries if x.strip()}
    ranked = sorted(
        candidates,
        key=lambda c: (
            c.country not in avoid,
            c.capture_score,
            c.official_score,
            c.border_score,
        ),
        reverse=True,
    )

    chosen = []
    counts: Dict[str, int] = {}

    for c in ranked:
        if c.country in avoid:
            continue

        limit = max_per_country
        # unknown se limita aún más para evitar que una mala inferencia domine.
        if c.country == "unknown":
            limit = max(1, min(max_per_country, 2))

        if counts.get(c.country, 0) >= limit:
            continue

        chosen.append(c)
        counts[c.country] = counts.get(c.country, 0) + 1

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


def overlay_penalty(frame: np.ndarray) -> float:
    """
    Filtro visual conservador para:
    - lower thirds
    - franjas
    - texto sobreimpreso
    - logos en esquinas
    - banners de TV

    No elimina marcas incrustadas: DESCARTA el frame completo.
    """
    h, w = frame.shape[:2]

    zones = {
        "top": frame[:max(1, int(h * 0.18)), :],
        "bottom": frame[int(h * 0.76):, :],
        "tl": frame[:int(h * 0.24), :int(w * 0.25)],
        "tr": frame[:int(h * 0.24), int(w * 0.75):],
        "bl": frame[int(h * 0.76):, :int(w * 0.30)],
        "br": frame[int(h * 0.76):, int(w * 0.70):],
    }

    penalty = 0.0

    # Texto típico de TV en bandas superior/inferior.
    for key in ("top", "bottom"):
        d = text_like_density(zones[key])
        if d > 0.010:
            penalty += 1.5
        if d > 0.025:
            penalty += 1.5

        reg = zones[key]
        gray = cv2.cvtColor(reg, cv2.COLOR_BGR2GRAY)

        # Filas demasiado uniformes = banner/franja.
        row_std = np.std(gray, axis=1)
        uniform = float(np.mean(row_std < 10))
        if uniform > 0.35:
            penalty += 1.5

    # Logos / texto en esquinas.
    for key in ("tl", "tr", "bl", "br"):
        d = text_like_density(zones[key])
        if d > 0.012:
            penalty += 1.0
        if d > 0.025:
            penalty += 1.0

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
    p.add_argument("--max-overlay-penalty", type=float, default=0.9)

    # Diversidad geográfica.
    p.add_argument("--max-per-country", type=int, default=2)
    p.add_argument(
        "--avoid-countries",
        default="",
        help='Ej: "lithuania,poland,belarus,usa,greece"',
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
        or f"unattended_clean_diverse_scan_{stamp}"
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
    print("UNATTENDED CLEAN + DIVERSE BORDER SCAN")
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

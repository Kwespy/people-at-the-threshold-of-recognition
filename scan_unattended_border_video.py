#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scan_unattended_border_video.py

Escáner exhaustivo de videos de frontera para encontrar frames con personas,
priorizando capturas remotas, fijas, continuas, automáticas, activadas por sensor
o de vigilancia.

NO asume que drone/bodycam = captura automática. En modo estricto esos materiales
se inspeccionan, pero solo pasan si la metadata aporta evidencia adicional de
captura automática/continua/remota/fija.

Instalación:
    python3 -m pip install -U yt-dlp ultralytics opencv-python requests beautifulsoup4 numpy

Uso normal:
    python3 scan_unattended_border_video.py

Modo muy exhaustivo:
    python3 scan_unattended_border_video.py --results-per-query 30 --max-videos 220 --sample-seconds 0.8 --max-frames-per-video 16

Para permitir fuentes de régimen incierto:
    python3 scan_unattended_border_video.py --allow-uncertain
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import shutil
import tempfile
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urljoin, urlparse

import cv2
import numpy as np
import requests
from bs4 import BeautifulSoup
from ultralytics import YOLO
import yt_dlp

# ============================================================
# FUENTES / SEEDS
# ============================================================

OFFICIAL_SEED_PAGES = [
    "https://vsat.lrv.lt/lt/naujienos/",
    "https://vsat.lrv.lt/lt/naujienos/treciadieni-i-lietuva-neileistas-rekordinis-migrantu-skaicius-buta-ir-iki-siol-nematytu-vaizdu-video-foto-S4p/",
    "https://vsat.lrv.lt/lt/naujienos/kabeliu-pasienieciai-cepkeliu-pelkeje-sulaike-12-migrantu-is-burundzio-video-ypT/",
    "https://vsat.lrv.lt/lt/naujienos/is-baltarusijos-isibrovusius-migrantus-pasienieciai-persekiojo-zeme-ir-is-oro-video-EPO/",
    "https://vsat.lrv.lt/lt/naujienos/vsat-pareigunu-operacija-sulaikyta-migrantu-grupe-suimta-dalis-sio-nusikaltimo-organizatoriu-video/",
    "https://vsat.lrv.lt/lt/naujienos/18-migrantu-i-lietuva-ropojo-is-baltarusijos-iskastu-urvu-video-foto-dnL/",
    "https://vsat.lrv.lt/lt/naujienos/nakti-i-lietuva-is-baltarusijos-brovesi-beveik-keturios-desimtys-migrantu-ne-vienam-nepavyko-foto-video-3Q1",
    "https://vsat.lrv.lt/lt/naujienos/pirmadieni-i-lietuva-is-baltarusijos-nepateko-39-neteiseti-migrantai-video-y27/",
    "https://vsat.lrv.lt/lt/naujienos/kabeliu-pasienieciai-neleido-is-baltarusijos-isibrauti-9-neteisetiems-migrantams-video-lDl/",
    "https://vsat.lrv.lt/lt/naujienos/treciadieni-pasienieciai-neisileido-pussimcio-sausuma-ir-vandeniu-besibrovusiu-migrantu-foto-video/",
    "https://vsat.lrv.lt/lt/naujienos/sestadieni-i-lietuva-brovesi-didziausias-siemet-migrantu-burys-visus-isgaude-pasienieciai-video-iLh/",
    "https://vsat.lrv.lt/lt/naujienos/treciadieni-vsat-uzkirto-kelia-is-baltarusijos-neteisetai-patekti-35-migrantams-video/",
    "https://www.gov.pl/web/border/video",
    "https://www.dvidshub.net/video/930845/woman-dies-after-fall-international-border-fence-near-otay-mesa-port-entry",
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
    '"vaizdo stebėjimo sistema" migrantai VSAT',
    '"sienos stebėjimo sistema" migrantai',
    'VSAT migrantai kamera Baltarusija',
    'VSAT migrantai termovizorius',
    'Lithuania Belarus border surveillance camera migrants',
    'Lithuania border thermal camera migrants',
    '"Straż Graniczna" monitoring migranci granica',
    '"Straż Graniczna" kamera termowizyjna migranci',
    'Poland Belarus border surveillance camera migrants',
    'Polish Border Guard thermal camera migrants',
    'Polish border electronic barrier camera migrants',
    '"Remote Video Surveillance System" migrants border',
    '"RVSS" border migrants camera',
    'CBP surveillance camera migrants border',
    'CBP thermal camera migrants border',
    'Border Patrol surveillance camera migrants',
    'autonomous surveillance tower migrants border',
    'border surveillance tower migrants camera',
    'border thermal surveillance migrants CBP',
    'Frontex border surveillance thermal camera migrants',
    'Frontex surveillance camera migrants border',
    'EU border thermal camera migrants surveillance',
    'Belarus border surveillance camera migrants',
    'maritime surveillance thermal camera migrants border',
    'coast guard thermal camera migrants sea surveillance',
    'Mediterranean migrants thermal camera surveillance',
    'Aegean migrants thermal camera coast guard',
    'Guardia Civil cámara térmica frontera migrantes',
    'vigilancia frontera cámara térmica migrantes Ceuta',
    'vigilancia frontera cámara térmica migrantes Melilla',
    'Evros border thermal camera migrants surveillance',
    'Έβρος θερμική κάμερα μετανάστες σύνορα',
    'Εβρος κάμερα επιτήρησης μετανάστες',
    '"border surveillance camera" migrants crossing',
    '"border CCTV" migrants crossing',
    '"thermal camera" migrants border crossing',
    '"fixed surveillance camera" border migrants',
    '"continuous surveillance" border migrants camera',
    '"motion triggered" border camera migrants',
    # Se buscan también estos, pero son penalizados si no hay evidencia de automatización.
    'border drone migrants surveillance footage',
    'border bodycam migrants footage',
    'border helicopter thermal migrants footage',
]

STRONG_AUTOMATIC_PATTERNS = [
    (r"remote video surveillance system", 8), (r"\brvss\b", 8),
    (r"autonomous surveillance tower", 8), (r"autonomous tower", 7),
    (r"motion[- ]trigger", 7), (r"camera trap", 6), (r"trail camera", 6),
    (r"unattended camera", 7), (r"unattended surveillance", 7),
    (r"continuous recording", 6), (r"continuous surveillance", 6),
    (r"round[- ]the[- ]clock surveillance", 6), (r"24/7 surveillance", 6),
    (r"fixed surveillance camera", 6), (r"fixed camera", 5), (r"\bcctv\b", 5),
    (r"electronic barrier", 6), (r"automated border surveillance", 8),
    (r"automatic border surveillance", 8), (r"sensor[- ]based", 5),
    (r"vaizdo stebėjimo sistema", 9), (r"sienos stebėjimo sistema", 9),
    (r"stebėjimo sistema", 6), (r"stebėjimo kamer", 6), (r"kameromis", 3),
    (r"bariera elektroniczna", 7), (r"monitoring granicy", 6),
    (r"system monitoringu", 6), (r"kam(?:era|ery) termowizyjn", 5),
    (r"videovigilancia", 6), (r"cámara fija", 5), (r"cámara térmica", 4),
    (r"sistema de vigilancia", 4), (r"vigilancia continua", 6),
    (r"κάμερα επιτήρησης", 5), (r"θερμική κάμερα", 4),
]

SUPPORTIVE_PATTERNS = [
    (r"surveillance system", 4), (r"surveillance camera", 4),
    (r"monitoring system", 3), (r"remote surveillance", 4),
    (r"remote camera", 3), (r"thermal camera", 3), (r"infrared camera", 3),
    (r"machine vision", 5), (r"computer vision", 4),
    (r"detection system", 3), (r"sensor", 2), (r"border monitoring", 3),
]

MANUAL_RISK_PATTERNS = [
    (r"body[- ]worn", -7), (r"\bbodycam\b", -7), (r"body camera", -7),
    (r"handheld", -7), (r"hand[- ]held", -7),
    (r"press photographer", -8), (r"photojournalist", -8), (r"journalist", -5),
    (r"\bb-roll\b", -3), (r"\bdrone\b", -4), (r"\buav\b", -3),
    (r"helicopter", -5), (r"aircraft", -3), (r"aerial footage", -3),
]

BORDER_PATTERNS = [
    r"\bborder\b", r"frontier", r"migrant", r"refugee", r"crossing", r"belarus",
    r"mexico", r"evros", r"ceuta", r"melilla", r"granica", r"sien", r"pasien",
    r"frontera", r"σύνορ",
]

OFFICIAL_DOMAIN_HINTS = [
    "vsat.lrv.lt", "gov.pl", "cbp.gov", "dhs.gov", "dvidshub.net",
    "frontex.europa.eu", "rs.gov.lv",
]

OFFICIAL_UPLOADER_HINTS = [
    "valstybės sienos apsaugos tarnyba", "vsat", "straż graniczna", "border guard",
    "customs and border protection", "u.s. customs and border protection",
    "homeland security", "frontex", "government",
]

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/150 Safari/537.36"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": USER_AGENT})

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
    accepted: bool = False
    reason: str = ""

@dataclass
class FrameCandidate:
    video_url: str
    source_page: str
    title: str
    uploader: str
    capture_score: int
    capture_hits: str
    timestamp_seconds: float
    person_count: int
    person_conf_max: float
    person_conf_mean: float
    person_area_max: float
    sharpness: float
    camera_motion_norm: float
    static_camera_bonus: float
    total_score: float
    frame_path: str = ""


def norm_text(*parts: Any) -> str:
    return " ".join(str(p or "") for p in parts).lower()


def stable_id(text: str, n: int = 12) -> str:
    return hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()[:n]


def write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def append_jsonl(path: Path, row: Dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def score_patterns(text: str, patterns: Sequence[Tuple[str, int]]) -> Tuple[int, List[str]]:
    score, hits = 0, []
    for pattern, value in patterns:
        if re.search(pattern, text, flags=re.I):
            score += value
            hits.append(f"{pattern}:{value:+d}")
    return score, hits


def classify_capture(text: str) -> Tuple[int, List[str]]:
    a, h1 = score_patterns(text, STRONG_AUTOMATIC_PATTERNS)
    b, h2 = score_patterns(text, SUPPORTIVE_PATTERNS)
    c, h3 = score_patterns(text, MANUAL_RISK_PATTERNS)
    return a + b + c, h1 + h2 + h3


def border_relevance(text: str) -> int:
    return sum(bool(re.search(p, text, flags=re.I)) for p in BORDER_PATTERNS)


def official_score(url: str, uploader: str = "") -> int:
    score = 0
    host = urlparse(url).netloc.lower()
    if any(h in host for h in OFFICIAL_DOMAIN_HINTS):
        score += 4
    u = uploader.lower()
    if any(h in u for h in OFFICIAL_UPLOADER_HINTS):
        score += 3
    return score


def is_videoish_url(url: str) -> bool:
    low = url.lower()
    return (
        "youtube.com/watch" in low or "youtu.be/" in low or "youtube.com/embed/" in low
        or "vimeo.com/" in low or "dvidshub.net/video/" in low
        or low.endswith((".mp4", ".webm", ".mov", ".m4v"))
    )


def canonicalize_video_url(url: str) -> str:
    if "youtube.com/embed/" in url:
        vid = url.split("youtube.com/embed/", 1)[1].split("?", 1)[0].split("/", 1)[0]
        return f"https://www.youtube.com/watch?v={vid}"
    return url


def extract_video_links_from_page(url: str, timeout: int = 20) -> Tuple[List[str], str]:
    try:
        r = SESSION.get(url, timeout=timeout)
        r.raise_for_status()
    except Exception as exc:
        print(f"  WEB ERROR / {url} / {exc}")
        return [], ""

    soup = BeautifulSoup(r.text, "html.parser")
    text = soup.get_text(" ", strip=True)
    links = []
    for tag in soup.find_all(["a", "iframe", "source", "video"]):
        raw = tag.get("href") or tag.get("src") or tag.get("data-src")
        if raw:
            full = canonicalize_video_url(urljoin(url, raw))
            if is_videoish_url(full):
                links.append(full)

    for match in re.findall(
        r'https?://(?:www\.)?(?:youtube\.com/watch\?v=[\w-]+|youtu\.be/[\w-]+|[^\s"\'<>]+\.mp4(?:\?[^\s"\'<>]*)?)',
        r.text, flags=re.I,
    ):
        links.append(canonicalize_video_url(match))

    return list(dict.fromkeys(links)), text


def crawl_vsat_news(max_pages: int = 120) -> List[Tuple[str, str]]:
    root = "https://vsat.lrv.lt/lt/naujienos/"
    queue, seen, relevant = [root], set(), []
    while queue and len(seen) < max_pages:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        try:
            r = SESSION.get(url, timeout=18)
            if not r.ok:
                continue
        except Exception:
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        text = soup.get_text(" ", strip=True)
        low = text.lower()
        if url != root and any(k in low for k in ["migrant", "sienos stebėjimo", "vaizdo stebėjimo", "kamer"]) and any(k in low for k in ["video", "youtube", "vaizdo įraš"]):
            relevant.append((url, text))
        for a in soup.find_all("a", href=True):
            full = urljoin(url, a["href"]).split("#", 1)[0]
            if urlparse(full).netloc.lower() == "vsat.lrv.lt" and "/lt/naujienos/" in full and full not in seen and full not in queue:
                queue.append(full)
    return relevant


def ydl_opts() -> Dict[str, Any]:
    return {
        "quiet": True, "no_warnings": True, "ignoreerrors": True, "noplaylist": True,
        "socket_timeout": 25, "retries": 3, "fragment_retries": 3,
        "http_headers": {"User-Agent": USER_AGENT},
    }


def search_youtube(query: str, n: int) -> List[str]:
    opts = ydl_opts()
    opts.update({"extract_flat": True, "skip_download": True})
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"ytsearch{n}:{query}", download=False)
    urls = []
    for e in (info or {}).get("entries") or []:
        if not e:
            continue
        u, vid = e.get("url") or e.get("webpage_url"), e.get("id")
        if u and str(u).startswith("http"):
            urls.append(str(u))
        elif vid:
            urls.append(f"https://www.youtube.com/watch?v={vid}")
    return list(dict.fromkeys(urls))


def get_video_metadata(url: str) -> Optional[Dict[str, Any]]:
    opts = ydl_opts(); opts.update({"skip_download": True})
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception:
        return None
    if not info:
        return None
    if info.get("_type") == "playlist":
        entries = [x for x in (info.get("entries") or []) if x]
        return entries[0] if entries else None
    return info


def build_candidate(url: str, source_page: str = "", page_text: str = "") -> Optional[VideoCandidate]:
    info = get_video_metadata(url)
    if not info:
        return None
    title = str(info.get("title") or "")
    desc = str(info.get("description") or "")
    uploader = str(info.get("uploader") or info.get("channel") or "")
    webpage = str(info.get("webpage_url") or url)
    duration = info.get("duration")
    text = norm_text(title, desc, uploader, source_page, page_text, webpage)
    cscore, hits = classify_capture(text)
    return VideoCandidate(
        url=webpage, title=title, description=desc[:4000], uploader=uploader,
        source_page=source_page,
        duration=float(duration) if isinstance(duration, (int, float)) else None,
        capture_score=cscore, capture_hits=" | ".join(hits),
        border_score=border_relevance(text),
        official_score=max(official_score(webpage, uploader), official_score(source_page, uploader)),
    )


def accept_candidate(c: VideoCandidate, allow_uncertain: bool, max_duration: float) -> Tuple[bool, str]:
    if c.duration and c.duration > max_duration:
        return False, "video demasiado largo"
    if c.border_score < 1:
        return False, "relevancia fronteriza débil"
    effective = c.capture_score + min(c.official_score, 3)
    if allow_uncertain:
        return (effective >= 1, "uncertain mode" if effective >= 1 else "capture score bajo")
    if c.capture_score < 3:
        return False, f"sin evidencia fuerte de captura no dirigida ({c.capture_score})"
    low = norm_text(c.title, c.description, c.capture_hits)
    if re.search(r"body[- ]worn|bodycam|body camera|handheld|hand[- ]held", low, flags=re.I) and c.capture_score < 8:
        return False, "riesgo de cámara manual/bodycam"
    if re.search(r"\bdrone\b|\buav\b|helicopter|aircraft|aerial footage", low, flags=re.I) and c.capture_score < 6:
        return False, "drone/aéreo sin evidencia suficiente de automatización"
    return True, "accepted strict"


def download_video(c: VideoCandidate, temp_dir: Path, max_height: int) -> Optional[Path]:
    prefix = stable_id(c.url)
    opts = ydl_opts()
    opts.update({
        "format": f"bestvideo[height<={max_height}][ext=mp4]/best[height<={max_height}][ext=mp4]/bestvideo[height<={max_height}]/best[height<={max_height}]",
        "outtmpl": str(temp_dir / f"{prefix}_%(id)s.%(ext)s"),
        "restrictfilenames": True, "nopart": True, "overwrites": True,
    })
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.extract_info(c.url, download=True)
    except Exception as exc:
        print(f"    DOWNLOAD ERROR / {exc}")
        return None
    matches = sorted(temp_dir.glob(prefix + "_*"), key=lambda p: p.stat().st_mtime, reverse=True)
    return matches[0] if matches else None


def sharpness(frame: np.ndarray) -> float:
    return float(cv2.Laplacian(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var())


def camera_motion_norm(a: np.ndarray, b: np.ndarray) -> float:
    h, w = b.shape[:2]
    scale = 640.0 / w if w > 640 else 1.0
    def prep(img):
        if scale != 1.0:
            img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    ga, gb = prep(a), prep(b)
    pts = cv2.goodFeaturesToTrack(ga, maxCorners=250, qualityLevel=0.01, minDistance=12, blockSize=7)
    if pts is None or len(pts) < 15:
        return 0.02
    nxt, status, _ = cv2.calcOpticalFlowPyrLK(ga, gb, pts, None, winSize=(21,21), maxLevel=3)
    if nxt is None or status is None:
        return 0.02
    x = pts[status.flatten() == 1].reshape(-1, 2)
    y = nxt[status.flatten() == 1].reshape(-1, 2)
    if len(x) < 12:
        return 0.02
    med = float(np.median(np.linalg.norm(y - x, axis=1)))
    hh, ww = ga.shape[:2]
    return med / max(math.hypot(ww, hh), 1.0)


def dhash(frame: np.ndarray, size: int = 8) -> int:
    g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    r = cv2.resize(g, (size + 1, size), interpolation=cv2.INTER_AREA)
    diff = r[:, 1:] > r[:, :-1]
    value = 0
    for bit in diff.flatten():
        value = (value << 1) | int(bit)
    return value


def hamming(a: int, b: int) -> int:
    return int((a ^ b).bit_count())


def detect_people(model: YOLO, frame: np.ndarray, conf: float) -> Tuple[int, float, float, float]:
    result = model.predict(source=frame, classes=[0], conf=conf, verbose=False, imgsz=960)[0]
    boxes = result.boxes
    if boxes is None or len(boxes) == 0:
        return 0, 0.0, 0.0, 0.0
    confs = boxes.conf.detach().cpu().numpy().astype(float)
    xyxy = boxes.xyxy.detach().cpu().numpy().astype(float)
    h, w = frame.shape[:2]; total = float(max(h*w, 1))
    areas = [max(0, x2-x1)*max(0, y2-y1)/total for x1,y1,x2,y2 in xyxy]
    return len(confs), float(np.max(confs)), float(np.mean(confs)), float(max(areas))


def total_score(count, cmax, cmean, area, sh, motion, capture_score, official):
    if motion <= 0.0015: static = 3.0
    elif motion <= 0.003: static = 2.0
    elif motion <= 0.006: static = 0.8
    else: static = 0.0
    score = (
        min(math.log1p(count)*1.8, 4.0) + cmax*2.5 + cmean*1.5
        + min(math.sqrt(max(area,0))*8.0, 2.5)
        + min(math.log1p(max(sh,0))/2.5, 3.0) + static
        + min(max(capture_score,0),12)*0.35 + min(official,6)*0.25
    )
    return score, static


def scan_video(video_path: Path, c: VideoCandidate, model: YOLO, args, frames_dir: Path) -> List[FrameCandidate]:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return []
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 25.0)
    nframes = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    duration = nframes / fps if fps > 0 and nframes > 0 else 0
    if duration > 0:
        times = np.arange(0, duration, max(args.sample_seconds, 0.25), dtype=float).tolist()
        if len(times) > args.max_sampled_frames:
            idx = np.linspace(0, len(times)-1, args.max_sampled_frames).astype(int)
            times = [times[i] for i in idx]
    else:
        times = [i*args.sample_seconds for i in range(args.max_sampled_frames)]

    found, prev, hashes = [], None, []
    for i, t in enumerate(times, 1):
        cap.set(cv2.CAP_PROP_POS_MSEC, t*1000.0)
        ok, frame = cap.read()
        if not ok or frame is None:
            continue
        count, cmax, cmean, area = detect_people(model, frame, args.min_person_conf)
        motion = camera_motion_norm(prev, frame) if prev is not None else 0.02
        prev = frame.copy()
        if count < 1 or area < args.min_person_area:
            continue
        ph = dhash(frame)
        if any(hamming(ph, old) <= 5 for old in hashes):
            continue
        hashes.append(ph)
        sh = sharpness(frame)
        score, static = total_score(count, cmax, cmean, area, sh, motion, c.capture_score, c.official_score)
        row = FrameCandidate(
            video_url=c.url, source_page=c.source_page, title=c.title, uploader=c.uploader,
            capture_score=c.capture_score, capture_hits=c.capture_hits,
            timestamp_seconds=float(t), person_count=count, person_conf_max=cmax,
            person_conf_mean=cmean, person_area_max=area, sharpness=sh,
            camera_motion_norm=motion, static_camera_bonus=static, total_score=score,
        )
        found.append((row, frame.copy()))
        if i % 50 == 0:
            print(f"      sampled {i}/{len(times)}")
    cap.release()

    found.sort(key=lambda x: x[0].total_score, reverse=True)
    out = []
    vid = stable_id(c.url, 10)
    for rank, (row, frame) in enumerate(found[:args.max_frames_per_video], 1):
        name = f"{vid}_r{rank:02d}_t{row.timestamp_seconds:08.2f}_p{row.person_count:02d}_s{row.total_score:05.2f}.png"
        path = frames_dir / name
        cv2.imwrite(str(path), frame, [cv2.IMWRITE_PNG_COMPRESSION, 2])
        row.frame_path = str(path)
        out.append(row)
    return out


def make_contact_sheet(rows: List[FrameCandidate], path: Path, cols: int = 4) -> None:
    rows = [r for r in rows if r.frame_path and Path(r.frame_path).exists()]
    if not rows: return
    tw, th, lh = 420, 270, 55
    thumbs = []
    for r in rows:
        img = cv2.imread(r.frame_path)
        if img is None: continue
        h,w = img.shape[:2]; s = min(tw/w, th/h); rw,rh = int(w*s), int(h*s)
        resized = cv2.resize(img, (rw,rh), interpolation=cv2.INTER_AREA)
        canvas = np.zeros((th+lh, tw, 3), dtype=np.uint8)
        x,y=(tw-rw)//2,(th-rh)//2; canvas[y:y+rh,x:x+rw]=resized
        cv2.putText(canvas, f"score {r.total_score:.2f} | people {r.person_count} | t {r.timestamp_seconds:.1f}s", (8,th+20), cv2.FONT_HERSHEY_SIMPLEX, .43, (255,255,255), 1, cv2.LINE_AA)
        cv2.putText(canvas, f"capture {r.capture_score} | motion {r.camera_motion_norm:.4f}", (8,th+42), cv2.FONT_HERSHEY_SIMPLEX, .43, (255,255,255), 1, cv2.LINE_AA)
        thumbs.append(canvas)
    nrows = math.ceil(len(thumbs)/cols)
    sheet = np.zeros((nrows*(th+lh), cols*tw, 3), dtype=np.uint8)
    for i, thumb in enumerate(thumbs):
        rr,cc = divmod(i, cols); y=rr*(th+lh); x=cc*tw
        sheet[y:y+th+lh, x:x+tw]=thumb
    cv2.imwrite(str(path), sheet, [cv2.IMWRITE_JPEG_QUALITY, 94])


def save_csv(path: Path, rows: List[FrameCandidate]) -> None:
    fields = list(FrameCandidate.__dataclass_fields__.keys())
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader()
        for r in rows: w.writerow(asdict(r))


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--results-per-query", type=int, default=18)
    p.add_argument("--max-videos", type=int, default=140)
    p.add_argument("--max-duration", type=float, default=1800.0)
    p.add_argument("--sample-seconds", type=float, default=1.1)
    p.add_argument("--max-sampled-frames", type=int, default=1200)
    p.add_argument("--max-frames-per-video", type=int, default=12)
    p.add_argument("--min-person-conf", type=float, default=0.28)
    p.add_argument("--min-person-area", type=float, default=0.0012)
    p.add_argument("--max-height", type=int, default=1080)
    p.add_argument("--allow-uncertain", action="store_true")
    p.add_argument("--keep-videos", action="store_true")
    p.add_argument("--crawl-vsat-pages", type=int, default=120)
    p.add_argument("--model", default="yolo11n.pt")
    p.add_argument("--output", default="")
    return p.parse_args()


def main():
    args = parse_args()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = Path(args.output or f"unattended_border_video_scan_{stamp}").resolve()
    frames_dir, videos_dir, sheets_dir = out/"frames", out/"videos", out/"contact_sheets"
    for d in [out, frames_dir, videos_dir, sheets_dir]: d.mkdir(parents=True, exist_ok=True)
    (out/"run_config.json").write_text(json.dumps(vars(args), ensure_ascii=False, indent=2), encoding="utf-8")

    print("="*78)
    print("UNATTENDED BORDER VIDEO SCAN")
    print("="*78)
    print("OUTPUT /", out)
    print("STRICT /", not args.allow_uncertain)
    print("MODEL  /", args.model)
    model = YOLO(args.model)

    discovered: Dict[str, Dict[str,str]] = {}
    for u in DIRECT_VIDEO_SEEDS:
        discovered.setdefault(u, {"source_page":"DIRECT_OFFICIAL_SEED", "page_text":""})

    print("\n[1/5] OFFICIAL PAGES")
    for page in OFFICIAL_SEED_PAGES:
        print(" PAGE /", page)
        links, text = extract_video_links_from_page(page)
        for u in links: discovered.setdefault(u, {"source_page":page, "page_text":text})

    print("\n VSAT DEEP CRAWL")
    vsat_pages = crawl_vsat_news(args.crawl_vsat_pages)
    print(" VSAT relevant pages /", len(vsat_pages))
    for page, text in vsat_pages:
        links, _ = extract_video_links_from_page(page)
        for u in links: discovered.setdefault(u, {"source_page":page, "page_text":text})

    print("\n[2/5] YOUTUBE SEARCH")
    for i,q in enumerate(SEARCH_QUERIES,1):
        print(f" Q {i:02d}/{len(SEARCH_QUERIES)} / {q}")
        try: urls = search_youtube(q, args.results_per_query)
        except Exception as exc:
            print("   SEARCH ERROR /", exc); continue
        for u in urls: discovered.setdefault(u, {"source_page":f"ytsearch:{q}", "page_text":q})
    print("DISCOVERED /", len(discovered))

    print("\n[3/5] METADATA FILTER")
    accepted, rejected, seen = [], [], set()
    for i,(url,origin) in enumerate(discovered.items(),1):
        if len(accepted) >= args.max_videos: break
        print(f" META {i:04d}/{len(discovered):04d} / {url}")
        c = build_candidate(url, origin.get("source_page",""), origin.get("page_text",""))
        if not c:
            rejected.append({"url":url,"reason":"metadata unavailable"}); continue
        if c.url in seen: continue
        seen.add(c.url)
        ok, reason = accept_candidate(c, args.allow_uncertain, args.max_duration)
        c.accepted, c.reason = ok, reason
        if ok:
            accepted.append(c)
            print(f"   ACCEPT / capture={c.capture_score:+d} official={c.official_score} / {c.title[:90]}")
        else:
            rejected.append(asdict(c))
    accepted.sort(key=lambda x:(x.capture_score,x.official_score,x.border_score), reverse=True)
    write_jsonl(out/"videos.jsonl", [asdict(x) for x in accepted])
    write_jsonl(out/"rejected.jsonl", rejected)
    print("VIDEOS TO SCAN /", len(accepted))

    print("\n[4/5] DOWNLOAD + FRAME SCAN")
    all_frames = []
    with tempfile.TemporaryDirectory(prefix="border_video_scan_") as td:
        temp = Path(td)
        for i,c in enumerate(accepted,1):
            print("\n"+"-"*78)
            print(f"VIDEO {i}/{len(accepted)} / {c.title}")
            print("URL /", c.url)
            print("CAPTURE /", c.capture_score, "/", c.capture_hits[:280])
            vp = download_video(c, temp, args.max_height)
            if not vp:
                append_jsonl(out/"rejected.jsonl", {**asdict(c),"reason":"download failed"}); continue
            print(f"FILE / {vp.name} / {vp.stat().st_size/1024/1024:.1f} MB")
            rows = scan_video(vp, c, model, args, frames_dir)
            print("SELECTED FRAMES /", len(rows))
            all_frames.extend(rows)
            if args.keep_videos:
                try: shutil.copy2(vp, videos_dir/vp.name)
                except Exception as exc: print("KEEP ERROR /", exc)
            try: vp.unlink(missing_ok=True)
            except Exception: pass

    print("\n[5/5] FINAL RANKING")
    all_frames.sort(key=lambda x:x.total_score, reverse=True)
    save_csv(out/"candidates.csv", all_frames)
    write_jsonl(out/"candidates.jsonl", [asdict(x) for x in all_frames])
    for start in range(0,len(all_frames),24):
        batch=all_frames[start:start+24]
        make_contact_sheet(batch, sheets_dir/f"ranking_{start+1:04d}_{start+len(batch):04d}.jpg")

    print("\n"+"="*78)
    print("DONE")
    print("Videos accepted /", len(accepted))
    print("Frames /", len(all_frames))
    print("OUTPUT /", out)
    print("CSV /", out/"candidates.csv")
    print("SHEETS /", sheets_dir)
    print("\nIMPORTANT: capture_score es una ayuda de selección, no una prueba histórica.")
    print("Revisa source_page + capture_hits antes de incorporar un frame al corpus final.")

if __name__ == "__main__":
    main()

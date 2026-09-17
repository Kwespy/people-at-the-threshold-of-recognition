#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
recover_deleted_frames.py

Recupera los frames borrados de un resultado previo de
scan_unattended_border_video.py SIN repetir las búsquedas ni volver a pasar YOLO.

Usa candidates.jsonl como "mapa":
- cada fila ya contiene video_url
- timestamp_seconds
- nombre/ruta original del frame
- metadata y score

El script:
1. lee candidates.jsonl
2. agrupa por video
3. vuelve a descargar cada video
4. extrae SOLO los timestamps que habían sido seleccionados
5. guarda los frames con los mismos nombres
6. reconstruye candidates.csv / candidates.jsonl y contact_sheets

Uso:
    python recover_deleted_frames.py "/ruta/al/unattended_border_video_scan_XXXXXXXX_XXXXXX"

Ejemplo:
    python recover_deleted_frames.py unattended_border_video_scan_20260819_120548
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import tempfile
from collections import defaultdict
from pathlib import Path

import cv2

import scan_unattended_border_video as scanner


def load_jsonl(path: Path):
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows):
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def make_video_candidate(row):
    """
    Construye el objeto mínimo requerido por scanner.download_video().
    """
    kwargs = {}
    for field_name, field_def in scanner.VideoCandidate.__dataclass_fields__.items():
        if field_name in row:
            kwargs[field_name] = row[field_name]
        else:
            # Defaults simples compatibles con la dataclass del scanner.
            if field_name in {"url", "webpage_url"}:
                kwargs[field_name] = row.get("video_url", "")
            elif field_name == "source_page":
                kwargs[field_name] = row.get("source_page", "")
            elif field_name == "title":
                kwargs[field_name] = row.get("title", "")
            elif field_name == "uploader":
                kwargs[field_name] = row.get("uploader", "")
            elif field_name == "capture_score":
                kwargs[field_name] = int(row.get("capture_score", 0) or 0)
            elif field_name == "capture_hits":
                kwargs[field_name] = row.get("capture_hits", "")
            elif field_name == "official_score":
                kwargs[field_name] = int(row.get("official_score", 0) or 0)
            elif field_name == "border_score":
                kwargs[field_name] = int(row.get("border_score", 0) or 0)
            elif field_name == "description":
                kwargs[field_name] = ""
            elif field_name == "duration":
                kwargs[field_name] = None
            elif field_name in {"accepted", "accepted_by_metadata"}:
                kwargs[field_name] = True
            elif field_name == "reason":
                kwargs[field_name] = "recovery from candidates.jsonl"
            else:
                # Por si cambia ligeramente la dataclass.
                try:
                    kwargs[field_name] = field_def.default
                except Exception:
                    kwargs[field_name] = None

    return scanner.VideoCandidate(**kwargs)


def seek_and_read(cap, timestamp_seconds: float):
    """
    Intenta posicionar por milisegundos. Si falla, prueba por frame index.
    """
    cap.set(cv2.CAP_PROP_POS_MSEC, float(timestamp_seconds) * 1000.0)
    ok, frame = cap.read()
    if ok and frame is not None:
        return frame

    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    if fps > 0:
        index = int(round(float(timestamp_seconds) * fps))
        cap.set(cv2.CAP_PROP_POS_FRAMES, index)
        ok, frame = cap.read()
        if ok and frame is not None:
            return frame

    return None


def frame_filename_from_row(row, index: int):
    old = str(row.get("frame_path") or "").strip()
    if old:
        name = Path(old).name
        if name:
            return name

    # Fallback si frame_path no está.
    ts = float(row.get("timestamp_seconds", 0.0) or 0.0)
    score = float(row.get("total_score", 0.0) or 0.0)
    people = int(row.get("person_count", 0) or 0)
    return f"recovered_{index:06d}_t{ts:08.2f}_p{people:02d}_s{score:05.2f}.png"


def rebuild_outputs(scan_dir: Path, rows):
    # Reescribir JSONL con rutas recuperadas.
    write_jsonl(scan_dir / "candidates.jsonl", rows)

    # CSV conservando todas las claves presentes.
    fieldnames = []
    seen = set()
    for row in rows:
        for k in row.keys():
            if k not in seen:
                seen.add(k)
                fieldnames.append(k)

    with (scan_dir / "candidates.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for row in rows:
            w.writerow(row)

    # Reconstruir contact sheets usando FrameCandidate cuando sea posible.
    sheets_dir = scan_dir / "contact_sheets"
    sheets_dir.mkdir(parents=True, exist_ok=True)

    # Limpiar hojas antiguas para no mezclar.
    for old in sheets_dir.glob("ranking_*.jpg"):
        try:
            old.unlink()
        except Exception:
            pass

    frame_objects = []
    fields = scanner.FrameCandidate.__dataclass_fields__

    for row in rows:
        kwargs = {}
        for name, field_def in fields.items():
            if name in row:
                kwargs[name] = row[name]
            else:
                if name == "frame_path":
                    kwargs[name] = row.get("frame_path", "")
                elif name in {
                    "video_url", "source_page", "title", "uploader",
                    "capture_hits"
                }:
                    kwargs[name] = row.get(name, "")
                else:
                    kwargs[name] = row.get(name, 0)

        try:
            frame_objects.append(scanner.FrameCandidate(**kwargs))
        except Exception:
            pass

    frame_objects.sort(
        key=lambda x: float(getattr(x, "total_score", 0.0) or 0.0),
        reverse=True
    )

    for start in range(0, len(frame_objects), 24):
        batch = frame_objects[start:start + 24]
        scanner.make_contact_sheet(
            batch,
            sheets_dir / f"ranking_{start+1:04d}_{start+len(batch):04d}.jpg"
        )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "scan_dir",
        help="Carpeta del scan que contiene candidates.jsonl"
    )
    ap.add_argument(
        "--max-height",
        type=int,
        default=None,
        help="Altura máxima de descarga. Si se omite, usa run_config.json o 1080."
    )
    args = ap.parse_args()

    scan_dir = Path(args.scan_dir).expanduser().resolve()
    candidates_path = scan_dir / "candidates.jsonl"
    run_config_path = scan_dir / "run_config.json"
    frames_dir = scan_dir / "frames"

    if not candidates_path.exists():
        raise SystemExit(
            f"\nERROR: no existe:\n  {candidates_path}\n\n"
            "Necesito candidates.jsonl del scan original para recuperar exactamente "
            "los frames seleccionados."
        )

    frames_dir.mkdir(parents=True, exist_ok=True)

    run_config = {}
    if run_config_path.exists():
        try:
            run_config = json.loads(run_config_path.read_text(encoding="utf-8"))
        except Exception:
            run_config = {}

    max_height = (
        args.max_height
        if args.max_height is not None
        else int(run_config.get("max_height", 1080) or 1080)
    )

    rows = load_jsonl(candidates_path)

    if not rows:
        raise SystemExit(
            "\nERROR: candidates.jsonl está vacío. "
            "En ese caso no se pueden reconstruir los timestamps exactos desde este scan."
        )

    by_video = defaultdict(list)
    for i, row in enumerate(rows):
        url = str(row.get("video_url") or "").strip()
        if not url:
            continue
        by_video[url].append((i, row))

    print("=" * 78)
    print("RECOVER DELETED FRAMES")
    print("=" * 78)
    print("SCAN DIR       /", scan_dir)
    print("FRAMES TO MAKE /", len(rows))
    print("VIDEOS         /", len(by_video))
    print("MAX HEIGHT     /", max_height)
    print()
    print("No repite búsquedas. No vuelve a correr YOLO.")
    print("Solo descarga cada video y extrae los timestamps ya seleccionados.")
    print()

    recovered = 0
    failed = 0
    failed_rows = []

    with tempfile.TemporaryDirectory(prefix="recover_border_frames_") as td:
        temp_dir = Path(td)

        for vi, (url, group) in enumerate(by_video.items(), 1):
            first_row = group[0][1]
            candidate = make_video_candidate(first_row)

            print("-" * 78)
            print(f"VIDEO {vi}/{len(by_video)}")
            print("URL   /", url)
            print("FRAMES/", len(group))

            video_path = scanner.download_video(
                candidate,
                temp_dir,
                max_height
            )

            if not video_path or not Path(video_path).exists():
                print("ERROR / download failed")
                for idx, row in group:
                    failed += 1
                    failed_rows.append({
                        "video_url": url,
                        "timestamp_seconds": row.get("timestamp_seconds"),
                        "reason": "download failed",
                    })
                continue

            cap = cv2.VideoCapture(str(video_path))
            if not cap.isOpened():
                print("ERROR / cannot open downloaded video")
                for idx, row in group:
                    failed += 1
                    failed_rows.append({
                        "video_url": url,
                        "timestamp_seconds": row.get("timestamp_seconds"),
                        "reason": "cannot open video",
                    })
                try:
                    Path(video_path).unlink(missing_ok=True)
                except Exception:
                    pass
                continue

            for local_n, (idx, row) in enumerate(group, 1):
                ts = float(row.get("timestamp_seconds", 0.0) or 0.0)
                frame = seek_and_read(cap, ts)

                if frame is None:
                    print(f"  FAIL / t={ts:.2f}s")
                    failed += 1
                    failed_rows.append({
                        "video_url": url,
                        "timestamp_seconds": ts,
                        "reason": "frame seek failed",
                    })
                    continue

                filename = frame_filename_from_row(row, idx)
                dest = frames_dir / filename

                ok = cv2.imwrite(
                    str(dest),
                    frame,
                    [cv2.IMWRITE_PNG_COMPRESSION, 2]
                )

                if not ok:
                    print(f"  FAIL / write {filename}")
                    failed += 1
                    failed_rows.append({
                        "video_url": url,
                        "timestamp_seconds": ts,
                        "reason": "write failed",
                    })
                    continue

                row["frame_path"] = str(dest)
                recovered += 1
                print(f"  OK   / {filename} / t={ts:.2f}s")

            cap.release()

            try:
                Path(video_path).unlink(missing_ok=True)
            except Exception:
                pass

    rebuild_outputs(scan_dir, rows)

    if failed_rows:
        write_jsonl(scan_dir / "recovery_failed.jsonl", failed_rows)

    print()
    print("=" * 78)
    print("RECOVERY DONE")
    print("=" * 78)
    print("RECOVERED /", recovered)
    print("FAILED    /", failed)
    print("FRAMES    /", frames_dir)
    print("SHEETS    /", scan_dir / "contact_sheets")
    if failed:
        print("FAILED LOG/", scan_dir / "recovery_failed.jsonl")


if __name__ == "__main__":
    main()

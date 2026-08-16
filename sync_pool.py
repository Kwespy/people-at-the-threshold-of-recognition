from pathlib import Path
import argparse
import hashlib
import json
import shutil
from datetime import datetime


ROOT = Path(__file__).resolve().parent

POOL_FILE = ROOT / "pool.json"
ORIGINALS_DIR = ROOT / "originals"
METADATA_DIR = ROOT / "metadata"
BACKUP_DIR = ROOT / "pool_backups"

IMAGE_EXTS = {
    ".webp",
    ".jpg",
    ".jpeg",
    ".png",
    ".tif",
    ".tiff",
}


def load_json(path):
    try:
        return json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )
    except Exception:
        return None


def save_json(path, data):
    path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    path.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )


def sha256(path):
    h = hashlib.sha256()

    with path.open("rb") as f:
        while True:
            chunk = f.read(
                1024 * 1024
            )

            if not chunk:
                break

            h.update(chunk)

    return h.hexdigest()


def basename(value):
    if not value:
        return None

    try:
        return Path(
            str(value)
        ).name
    except Exception:
        return None


def normalize_pool(data):
    if isinstance(data, list):
        return data

    if (
        isinstance(data, dict)
        and
        isinstance(
            data.get("items"),
            list
        )
    ):
        return data["items"]

    raise ValueError(
        "pool.json debe ser una lista "
        "o un objeto con una lista 'items'."
    )


def pool_names(item):
    names = set()

    item_id = item.get("id")

    if item_id is not None:
        names.add(
            str(item_id)
        )

    for key in (
        "original",
        "original_file",
        "filename",
        "file",
        "local_file",
        "raw_file",
        "candidate_file",
    ):
        value = item.get(key)

        name = basename(value)

        if name:
            names.add(name)
            names.add(
                Path(name).stem
            )

    return names


def metadata_score(
    data,
    old_name,
    old_stem
):
    if not isinstance(
        data,
        dict
    ):
        return 0

    score = 0

    for key in (
        "original",
        "original_file",
        "filename",
        "file",
        "local_file",
        "raw_file",
        "candidate_file",
        "source_file",
        "source_filename",
    ):
        value = data.get(key)

        name = basename(value)

        if not name:
            continue

        if name == old_name:
            score += 100

        if Path(name).stem == old_stem:
            score += 60

    for key in (
        "candidate_id",
        "source_id",
        "id",
    ):
        value = data.get(key)

        if (
            value is not None
            and
            str(value) == old_stem
        ):
            score += 50

    return score


def find_metadata(
    old_name,
    old_stem
):
    if not METADATA_DIR.exists():
        return {}

    direct_candidates = [
        METADATA_DIR
        / f"{old_stem}.json",
        METADATA_DIR
        / f"{old_name}.json",
    ]

    for path in direct_candidates:
        if path.exists():
            data = load_json(path)

            if isinstance(
                data,
                dict
            ):
                return data

    best = None
    best_score = 0

    for path in METADATA_DIR.rglob(
        "*.json"
    ):
        if path.name == "index.json":
            continue

        data = load_json(path)

        score = metadata_score(
            data,
            old_name,
            old_stem
        )

        if score > best_score:
            best = data
            best_score = score

    if (
        best is not None
        and
        best_score > 0
    ):
        return best

    return {}


def update_item(
    item,
    new_id,
    new_name,
    old_name=None
):
    item = dict(item)

    if (
        old_name
        and
        old_name != new_name
        and
        not item.get(
            "source_filename"
        )
    ):
        item[
            "source_filename"
        ] = old_name

    item["id"] = new_id
    item["original"] = (
        f"originals/{new_name}"
    )
    item["original_file"] = (
        f"originals/{new_name}"
    )

    return item


def write_metadata_snapshot(
    item,
    new_id,
    new_name,
    file_path
):
    data = dict(item)

    data["id"] = new_id
    data["original"] = (
        f"originals/{new_name}"
    )
    data["original_file"] = (
        f"originals/{new_name}"
    )
    data["original_sha256"] = sha256(
        file_path
    )

    save_json(
        METADATA_DIR
        / f"{new_id}.json",
        data
    )


def numeric_value(value):
    try:
        text = str(value)

        if text.isdigit():
            return int(text)
    except Exception:
        pass

    return None


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--apply",
        action="store_true",
        help="Renombra archivos y actualiza pool.json."
    )

    args = parser.parse_args()

    if not POOL_FILE.exists():
        raise SystemExit(
            "ERROR: no existe pool.json"
        )

    if not ORIGINALS_DIR.exists():
        raise SystemExit(
            "ERROR: no existe originals/"
        )

    raw_pool = load_json(
        POOL_FILE
    )

    pool = normalize_pool(
        raw_pool
    )

    originals = sorted(
        [
            p
            for p in ORIGINALS_DIR.iterdir()
            if (
                p.is_file()
                and
                p.suffix.lower()
                in IMAGE_EXTS
            )
        ],
        key=lambda p: p.name.lower()
    )

    existing_numeric = {
        int(p.stem)
        for p in originals
        if p.stem.isdigit()
    }

    for item in pool:
        value = numeric_value(
            item.get("id")
        )

        if value is not None:
            existing_numeric.add(
                value
            )

    next_id = (
        max(
            existing_numeric,
            default=0
        )
        +
        1
    )

    entry_by_name = {}

    for item in pool:
        for name in pool_names(
            item
        ):
            entry_by_name.setdefault(
                name,
                item
            )

    plan = []

    used_ids = set(
        existing_numeric
    )

    for original in originals:
        old_name = original.name
        old_stem = original.stem

        matching_item = (
            entry_by_name.get(
                old_name
            )
            or
            entry_by_name.get(
                old_stem
            )
        )

        if old_stem.isdigit():
            value = int(
                old_stem
            )

            width = max(
                4,
                len(old_stem)
            )

            new_id = str(
                value
            ).zfill(
                width
            )

            new_name = (
                new_id
                +
                original.suffix.lower()
            )

        else:
            while next_id in used_ids:
                next_id += 1

            new_id = str(
                next_id
            ).zfill(4)

            new_name = (
                new_id
                +
                original.suffix.lower()
            )

            used_ids.add(
                next_id
            )

            next_id += 1

        plan.append(
            {
                "path": original,
                "old_name": old_name,
                "old_stem": old_stem,
                "new_id": new_id,
                "new_name": new_name,
                "item": matching_item,
            }
        )

    target_names = [
        row["new_name"]
        for row in plan
    ]

    if len(target_names) != len(
        set(target_names)
    ):
        raise SystemExit(
            "ERROR: el plan produciría nombres duplicados."
        )

    print()
    print(
        "=" * 68
    )
    print(
        "BORDER TRANSIT — FULL POOL SYNC"
    )
    print(
        "=" * 68
    )

    print(
        f"\nOriginals encontrados: {len(originals)}"
    )

    print(
        f"Pool actual: {len(pool)}"
    )

    rename_count = 0
    add_count = 0

    print(
        "\nPLAN:"
    )

    for row in plan:
        if (
            row["old_name"]
            !=
            row["new_name"]
        ):
            rename_count += 1

            print(
                "  RENAME "
                f"{row['old_name']} "
                "→ "
                f"{row['new_name']}"
            )

        if row["item"] is None:
            add_count += 1

            print(
                "  ADD    "
                f"{row['new_id']} "
                f"/ {row['old_name']}"
            )

    print(
        f"\nRenombres: {rename_count}"
    )
    print(
        f"Nuevas entradas pool: {add_count}"
    )

    if not args.apply:
        print()
        print(
            "DRY RUN / no se modificó nada."
        )
        print(
            "Si está bien:"
        )
        print(
            "  python sync_pool.py --apply"
        )
        return

    BACKUP_DIR.mkdir(
        exist_ok=True
    )

    timestamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )

    backup = (
        BACKUP_DIR
        /
        f"pool_{timestamp}.json"
    )

    shutil.copy2(
        POOL_FILE,
        backup
    )

    print(
        f"\nBACKUP / {backup.name}"
    )

    temporary = []

    for index, row in enumerate(
        plan
    ):
        source = row["path"]

        if source.name == row["new_name"]:
            row["final_path"] = source
            continue

        temp = (
            ORIGINALS_DIR
            /
            (
                f".__sync_tmp_{index:05d}"
                +
                source.suffix.lower()
            )
        )

        source.rename(
            temp
        )

        temporary.append(
            (
                row,
                temp
            )
        )

    for row, temp in temporary:
        target = (
            ORIGINALS_DIR
            /
            row["new_name"]
        )

        if target.exists():
            raise RuntimeError(
                f"Colisión inesperada: {target.name}"
            )

        temp.rename(
            target
        )

        row["final_path"] = target

    new_pool = []

    for row in plan:
        item = row["item"]

        if item is None:
            metadata = find_metadata(
                row["old_name"],
                row["old_stem"]
            )

            item = dict(
                metadata
            )

            item.setdefault(
                "project",
                "BORDER TRANSIT"
            )

            item.setdefault(
                "sync_status",
                "added_from_originals"
            )

        item = update_item(
            item,
            row["new_id"],
            row["new_name"],
            old_name=row["old_name"]
        )

        new_pool.append(
            item
        )

        write_metadata_snapshot(
            item,
            row["new_id"],
            row["new_name"],
            row["final_path"]
        )

    def sort_key(item):
        value = numeric_value(
            item.get("id")
        )

        return (
            value
            if value is not None
            else 10**12
        )

    new_pool.sort(
        key=sort_key
    )

    save_json(
        POOL_FILE,
        new_pool
    )

    print()
    print(
        "=" * 68
    )
    print(
        "SINCRONIZACIÓN TERMINADA"
    )
    print(
        "=" * 68
    )

    print(
        f"\nOriginals: {len(plan)}"
    )
    print(
        f"Pool actual: {len(new_pool)}"
    )
    print(
        f"Renombrados: {rename_count}"
    )
    print(
        f"Agregados: {add_count}"
    )

    print()
    print(
        "Ahora ejecuta:"
    )
    print(
        "  python generate_pool.py"
    )


if __name__ == "__main__":
    main()

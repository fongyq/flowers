#!/usr/bin/env python3
"""
根据 flower/top_flower_list.txt 与 flower/top_plant_list.txt 抓取维基数据，
覆盖 flower/plants.json / plants.embedded.js；配图写入 flower/image/。

运行（仓库根目录）:
  python3 flower/scripts/fetch_from_top_lists.py
  python3 flower/scripts/fetch_from_top_lists.py --limit 20   # 试跑
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import fetch_plants as fp

FLOWER_DIR = fp.FLOWER_DIR
IMAGE_DIR = fp.IMAGE_DIR
ZH_API = fp.ZH_API


def load_name_lines(path: Path) -> list[str]:
    out: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s:
            out.append(s)
    return out


def merged_ordered_names(flower_path: Path, plant_path: Path) -> list[str]:
    seen: set[str] = set()
    order: list[str] = []
    for src in (load_name_lines(flower_path), load_name_lines(plant_path)):
        for n in src:
            if n not in seen:
                seen.add(n)
                order.append(n)
    return order


def sci_for_json(wd: dict | None) -> str:
    if not wd:
        return ""
    s = (wd.get("p225") or "").strip()
    if not s:
        return ""
    s = re.sub(r"\s+", " ", s)
    if fp.contains_cjk(s):
        return ""
    return s


def opensearch_first_title(query: str) -> str:
    """中文维基 opensearch，返回首个主名字空间标题。"""
    q = (query or "").strip()
    if not q:
        return ""
    data = fp.api_get(
        ZH_API,
        {
            "action": "opensearch",
            "format": "json",
            "search": q,
            "limit": 8,
            "namespace": "0",
        },
    )
    if not isinstance(data, list) or len(data) < 2:
        return ""
    titles = data[1]
    if not isinstance(titles, list):
        return ""
    for t in titles:
        if not t or not isinstance(t, str):
            continue
        t = t.strip()
        if t.startswith(("Category:", "Template:", "Wikipedia:", "Help:", "File:")):
            continue
        return t
    return ""


def clear_image_dir() -> None:
    if not IMAGE_DIR.is_dir():
        return
    for p in IMAGE_DIR.iterdir():
        if p.is_file():
            p.unlink()


def image_basename(plant_id: int, slot: int, ext: str, stem_width: int) -> str:
    w = max(3, stem_width)
    stem = format(plant_id, f"0{w}d")
    if slot <= 0:
        return f"{stem}{ext}"
    return f"{stem}-{slot + 1}{ext}"


def download_plant_image(plant_id: int, url: str, stem_width: int) -> str:
    if not url or not url.startswith("http"):
        return ""
    candidates = [url]
    alt = fp.wikimedia_thumb_to_original(url)
    if alt != url:
        candidates.append(alt)
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    for i, u in enumerate(candidates):
        try:
            data = fp.download_bytes(u)
            ext = fp.guess_image_ext(data, u)
            fname = image_basename(plant_id, 0, ext, stem_width)
            dest = IMAGE_DIR / fname
            dest.write_bytes(data)
            return f"image/{fname}"
        except urllib.error.HTTPError as ex:
            if i < len(candidates) - 1:
                continue
            print(f"  id={plant_id} image HTTP {ex.code}", file=sys.stderr)
        except Exception as ex:
            print(f"  id={plant_id} image: {ex}", file=sys.stderr)
            break
    return ""


def resolve_all_pages(names: list[str]) -> tuple[dict[str, dict], list[str]]:
    """nameZh（清单原样） -> 维基解析行；missing 为仍无条目的名称。"""
    name_to_page: dict[str, dict] = {}
    batch_size = 25
    missing_round1: list[str] = []

    for i in range(0, len(names), batch_size):
        batch = names[i : i + batch_size]
        by_t, norm, red = fp.fetch_batch_zh(batch)
        for nm in batch:
            key = fp.final_title(nm, norm, red)
            row = by_t.get(key)
            if row:
                name_to_page[nm] = dict(row)
            else:
                missing_round1.append(nm)
        time.sleep(0.35)

    # opensearch 后按标题去重批量拉取（同一标题可对应多个清单名）
    name_resolved: dict[str, str] = {}  # nameZh -> 维基条目标题
    for nm in missing_round1:
        alt = opensearch_first_title(nm)
        time.sleep(0.12)
        if alt:
            name_resolved[nm] = alt

    uniq_titles = list(dict.fromkeys(name_resolved.values()))
    title_to_row: dict[str, dict] = {}
    for i in range(0, len(uniq_titles), batch_size):
        batch = uniq_titles[i : i + batch_size]
        by_t, norm, red = fp.fetch_batch_zh(batch)
        for t in batch:
            key = fp.final_title(t, norm, red)
            row = by_t.get(key)
            if row:
                title_to_row[t] = dict(row)
        time.sleep(0.35)

    for nm, wt in name_resolved.items():
        if nm in name_to_page:
            continue
        r = title_to_row.get(wt)
        if r:
            name_to_page[nm] = dict(r)

    still = [n for n in names if n not in name_to_page]
    return name_to_page, still


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="最多处理条数（0=全部）")
    ap.add_argument(
        "--flower-list",
        type=Path,
        default=FLOWER_DIR / "top_flower_list.txt",
    )
    ap.add_argument(
        "--plant-list",
        type=Path,
        default=FLOWER_DIR / "top_plant_list.txt",
    )
    ap.add_argument("--out", type=Path, default=FLOWER_DIR / "plants.json")
    args = ap.parse_args()

    flower_path = args.flower_list.resolve()
    plant_path = args.plant_list.resolve()
    if not flower_path.is_file():
        print("Missing", flower_path, file=sys.stderr)
        return 1
    if not plant_path.is_file():
        print("Missing", plant_path, file=sys.stderr)
        return 1

    names = merged_ordered_names(flower_path, plant_path)
    if args.limit > 0:
        names = names[: args.limit]

    print("Resolving", len(names), "titles …", file=sys.stderr)
    name_to_page, still_missing = resolve_all_pages(names)
    if still_missing:
        print("No wiki page:", len(still_missing), file=sys.stderr)

    qids = [
        name_to_page[k]["wikibase_item"]
        for k in name_to_page
        if name_to_page[k].get("wikibase_item")
    ]
    wd_map = fp.fetch_wikidata_map(qids)

    ordered: list[dict] = []
    for nm in names:
        p = name_to_page.get(nm)
        if not p:
            ordered.append(
                {
                    "id": len(ordered),
                    "nameZh": nm,
                    "nameEn": "",
                    "nameSci": "",
                    "desc": "",
                    "image": "",
                    "wiki": "",
                }
            )
            continue
        qid = (p.get("wikibase_item") or "").strip()
        wd = wd_map.get(qid)
        ne = fp.colloquial_english_from_wikidata(p, wd)
        ne = fp.pretty_english_common(re.sub(r"\s+", " ", (ne or "").strip()))
        ns = sci_for_json(wd)
        img_url = (p.get("image") or "").strip()
        ordered.append(
            {
                "id": len(ordered),
                "nameZh": nm,
                "nameEn": ne,
                "nameSci": ns,
                "desc": "",
                "image": img_url,
                "wiki": p.get("wiki") or "",
            }
        )

    max_pid = max((r["id"] for r in ordered), default=0)
    stem_w = fp.image_stem_width(max_pid)

    print("Clearing", IMAGE_DIR, "…", file=sys.stderr)
    clear_image_dir()

    fail_lines: list[str] = []
    print("Downloading images …", file=sys.stderr)
    for row in ordered:
        pid = row["id"]
        url = (row.get("image") or "").strip()
        if not url:
            row["image"] = ""
            fail_lines.append(f"{pid}\t{row['nameZh']}")
            time.sleep(0.02)
            continue
        path = download_plant_image(pid, url, stem_w)
        if path:
            row["image"] = path
        else:
            row["image"] = ""
            fail_lines.append(f"{pid}\t{row['nameZh']}")
        time.sleep(1.05)

    fail_path = FLOWER_DIR / "fail_plants.txt"
    fail_path.write_text("\n".join(fail_lines) + ("\n" if fail_lines else ""), encoding="utf-8")

    payload = {
        "source": (
            "物种列表：用户整理的 top_flower_list.txt + top_plant_list.txt；"
            "学名/英文名：维基数据（P225、P1843、标签等）。desc 留空。"
            "配图来自维基共享资源，已缓存至 image/；无图或下载失败见 fail_plants.txt（id 与中文名）。"
        ),
        "attribution": "https://zh.wikipedia.org | https://creativecommons.org/licenses/by-sa/4.0/deed.zh",
        "fetched": time.strftime("%Y-%m-%d"),
        "plants": ordered,
    }

    out_path = args.out.resolve()
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    emb_path = out_path.with_name("plants.embedded.js")
    emb_path.write_text(
        "/* Generated by fetch_from_top_lists.py — keep in sync with plants.json */\n"
        "window.__PLANTS_PAYLOAD__ = "
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        + ";\n",
    )

    print("Wrote", out_path, "—", len(ordered), "plants")
    print("Wrote", emb_path)
    print("fail_plants.txt —", len(fail_lines), "lines")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

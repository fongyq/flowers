#!/usr/bin/env python3
"""
从中文维基百科分类采集约 2000 条植物（花卉类优先 1000 + 草本/乔木/灌木等 1000），
结合维基数据补全英文名与学名（保留杂交 ×），desc 置空，配图下载到 flower/image/（4 位编号）。

用法（在仓库根目录）:
  python3 flower/scripts/fetch_plants_bulk.py
  python3 flower/scripts/fetch_plants_bulk.py --limit 80          # 试跑条数
  python3 flower/scripts/fetch_plants_bulk.py --flower 500 --other 500  # 自定义配额

说明:
  - 「最常见」由多个高流量分类的成员顺序近似，非严格 PV 排序；可自行改分类表。
  - 下载较慢且易受 429 限流；失败条目中文名写入 flower/fail_download.txt，JSON 中 image 为空。
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
USER_AGENT = fp.USER_AGENT

# 花卉 / 观赏向（先凑满 flower_quota，去重）
FLOWER_CATEGORIES: list[str] = [
    "花卉",
    "观赏植物",
    "球根花卉",
    "多年生草本花卉",
    "蔷薇属",
    "菊属",
    "兰科",
    "杜鹃花属",
    "杜鹃花科",
    "仙人掌科",
    "景天科",
    "凤梨科",
    "天门冬科",
    "鸢尾属",
    "百合属",
    "郁金香属",
    "水仙属",
    "蔷薇科",
    "苦苣苔科",
    "木犀科",
    "茜草科",
    "牻牛儿苗科",
    "芭蕉科",
    "秋海棠科",
    "天南星科",
    "花烛属",
    "猪笼草属",
    "兰属",
    "石斛属",
    "蝴蝶兰属",
    "仙客来属",
    "报春花科",
    "凤仙花属",
    "锦葵科",
    "朱槿属",
    "山茶科",
    "山茶属",
    "大戟科",
    "荷花",
    "睡莲科",
    "菖蒲属",
    "康乃馨",
]

# 草本、乔木、灌木等（排除已在花卉集合中的标题）
OTHER_CATEGORIES: list[str] = [
    "乔木",
    "灌木",
    "草本植物",
    "竹亚科",
    "棕榈科",
    "松科",
    "柏科",
    "杨柳科",
    "豆科",
    "禾本科",
    "蕨类植物门",
    "苔藓植物门",
    "伞形科",
    "十字花科",
    "茄科",
    "葫芦科",
    "芸香科",
    "葡萄科",
    "无患子科",
    "桑科",
    "荨麻科",
    "蓼科",
    "苋科",
    "唇形科",
    "菊科",
    "桔梗科",
    "石蒜科",
    "百合科",
    "泽泻科",
    "鸭跖草科",
    "莎草科",
    "樟科",
    "壳斗科",
    "桦木科",
    "胡桃科",
    "漆树科",
    "槭树科",
    "杜鹃花目",
    "天门冬目",
    "天门冬科",
    "龙舌兰属",
    "苏铁科",
    "银杏",
    "红豆杉科",
]

_TITLE_SKIP = re.compile(
    r"(列表|年表|索引|统计|消歧义|消歧義|^\d|^[A-Za-z]{1,3}$)"
)


def title_ok(title: str) -> bool:
    if not title or len(title) < 2:
        return False
    if ":" in title:
        return False
    if _TITLE_SKIP.search(title):
        return False
    return True


def display_title(page_title: str) -> str:
    return (page_title or "").replace("_", " ").strip()


def fetch_category_pages(cmtitle: str, max_fetch: int) -> list[str]:
    """cmtitle 如 Category:花卉"""
    out: list[str] = []
    cmcontinue: str | None = None
    while len(out) < max_fetch:
        params: dict[str, str] = {
            "action": "query",
            "format": "json",
            "list": "categorymembers",
            "cmtitle": cmtitle,
            "cmnamespace": "0",
            "cmtype": "page",
            "cmlimit": "500",
        }
        if cmcontinue:
            params["cmcontinue"] = cmcontinue
        data = fp.api_get(ZH_API, params)
        q = data.get("query", {})
        for m in q.get("categorymembers", []):
            t = (m.get("title") or "").strip()
            if title_ok(t):
                out.append(t)
                if len(out) >= max_fetch:
                    break
        cmcontinue = (data.get("continue") or {}).get("cmcontinue")
        if not cmcontinue:
            break
        time.sleep(0.2)
    return out


def collect_from_categories(
    categories: list[str],
    target: int,
    banned: set[str],
    per_cat_cap: int = 800,
) -> list[str]:
    seen = set(banned)
    ordered: list[str] = []
    for cat in categories:
        if len(ordered) >= target:
            break
        cmt = cat if cat.startswith("Category:") else f"Category:{cat}"
        need = min(per_cat_cap, target - len(ordered) + 200)
        try:
            pages = fetch_category_pages(cmt, max_fetch=need)
        except Exception as ex:
            print(f"  category skip {cmt}: {ex}", file=sys.stderr)
            time.sleep(1.0)
            continue
        for t in pages:
            if t in seen:
                continue
            seen.add(t)
            ordered.append(t)
            if len(ordered) >= target:
                break
        time.sleep(0.25)
    return ordered


def sci_for_json(wd: dict | None) -> str:
    """保留 Wikidata P225 原文（含 × 杂交符号），仅压缩空白。"""
    if not wd:
        return ""
    s = (wd.get("p225") or "").strip()
    if not s:
        return ""
    s = re.sub(r"\s+", " ", s)
    if fp.contains_cjk(s):
        return ""
    return s


def image_basename_bulk(plant_id: int, slot: int, ext: str) -> str:
    if slot <= 0:
        return f"{plant_id:04d}{ext}"
    return f"{plant_id:04d}-{slot + 1}{ext}"


def download_plant_image(plant_id: int, url: str) -> str:
    """成功返回 image/XXXX.jpg；失败返回空字符串。"""
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
            fname = image_basename_bulk(plant_id, 0, ext)
            dest = IMAGE_DIR / fname
            dest.write_bytes(data)
            return f"image/{fname}"
        except urllib.error.HTTPError as ex:
            if i < len(candidates) - 1:
                print(f"  id={plant_id} HTTP {ex.code}, try alternate …", file=sys.stderr)
                continue
            print(f"  id={plant_id} image HTTP {ex.code}", file=sys.stderr)
        except Exception as ex:
            print(f"  id={plant_id} image: {ex}", file=sys.stderr)
            break
    return ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--flower", type=int, default=1000, help="花卉向条数上限")
    ap.add_argument("--other", type=int, default=1000, help="其他植物条数上限")
    ap.add_argument("--limit", type=int, default=0, help="总条数上限（试跑，0 表示不截断）")
    ap.add_argument("--out", type=str, default=str(FLOWER_DIR / "plants.json"))
    args = ap.parse_args()

    flower_n = max(0, args.flower)
    other_n = max(0, args.other)
    total_target = flower_n + other_n
    if args.limit > 0:
        total_target = min(total_target, args.limit)

    print("Collecting flower-like titles …", file=sys.stderr)
    flower_titles = collect_from_categories(FLOWER_CATEGORIES, flower_n, set())
    print(f"  flower titles: {len(flower_titles)}", file=sys.stderr)

    ban = set(flower_titles)
    print("Collecting other plant titles …", file=sys.stderr)
    other_titles = collect_from_categories(OTHER_CATEGORIES, other_n, ban)
    print(f"  other titles: {len(other_titles)}", file=sys.stderr)

    all_titles = flower_titles + other_titles
    if args.limit > 0:
        all_titles = all_titles[: args.limit]

    if not all_titles:
        print("No titles collected; check categories / network.", file=sys.stderr)
        return 1

    merged: dict[str, dict] = {}
    batch_size = 25
    for i in range(0, len(all_titles), batch_size):
        batch = all_titles[i : i + batch_size]
        by_t, norm, red = fp.fetch_batch_zh(batch)
        for t in batch:
            key = fp.final_title(t, norm, red)
            row = by_t.get(key)
            if row:
                merged[display_title(t)] = dict(row)
        time.sleep(0.35)

    qids = [merged[k]["wikibase_item"] for k in merged if merged[k].get("wikibase_item")]
    wd_map = fp.fetch_wikidata_map(qids)

    ordered: list[dict] = []
    missing: list[str] = []
    for wiki_title in all_titles:
        name_zh = display_title(wiki_title)
        p = merged.get(name_zh)
        if not p:
            missing.append(name_zh)
            continue
        qid = p.get("wikibase_item") or ""
        wd = wd_map.get(qid)
        ne = fp.colloquial_english_from_wikidata(p, wd)
        ne = fp.pretty_english_common(re.sub(r"\s+", " ", (ne or "").strip()))
        ns = sci_for_json(wd)
        img_url = (p.get("image") or "").strip()
        ordered.append(
            {
                "id": len(ordered),
                "nameZh": name_zh,
                "nameEn": ne,
                "nameSci": ns,
                "desc": "",
                "image": img_url,
                "wiki": p["wiki"],
            }
        )

    fail_names: list[str] = []
    print("Downloading images …", file=sys.stderr)
    for row in ordered:
        pid = row["id"]
        url = (row.get("image") or "").strip()
        if not url:
            row["image"] = ""
            fail_names.append(row["nameZh"])
            time.sleep(0.05)
            continue
        path = download_plant_image(pid, url)
        if path:
            row["image"] = path
        else:
            row["image"] = ""
            fail_names.append(row["nameZh"])
        time.sleep(1.05)

    fail_path = FLOWER_DIR / "fail_download.txt"
    fail_path.write_text("\n".join(fail_names) + ("\n" if fail_names else ""), encoding="utf-8")

    payload = {
        "source": (
            "物种列表：中文维基百科分类成员；学名/英文名：维基数据（P225、P1843、标签等）。"
            "desc 留空供自定义。配图来自维基共享资源，已缓存至 image/；失败项见 fail_download.txt。"
        ),
        "attribution": "https://zh.wikipedia.org | https://creativecommons.org/licenses/by-sa/4.0/deed.zh",
        "fetched": time.strftime("%Y-%m-%d"),
        "plants": ordered,
    }

    out_path = Path(args.out)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    emb_path = out_path.with_name("plants.embedded.js")
    emb_path.write_text(
        "/* Generated by fetch_plants_bulk.py — keep in sync with plants.json */\n"
        "window.__PLANTS_PAYLOAD__ = "
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        + ";\n",
        encoding="utf-8",
    )

    print("Wrote", out_path, "—", len(ordered), "plants")
    print("Wrote", emb_path)
    print("fail_download.txt —", len(fail_names), "names")
    if missing:
        print("Missing wiki pages:", len(missing), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""
重试 flower/fail_plants.txt 中的配图：重新拉取中文维基缩略图并下载到 flower/image/，
更新 plants.json / plants.embedded.js，并重写 fail_plants.txt（仍为无图或下载失败的 id\\t中文名）。

第三轮兜底：Wikidata P18（主图）→ 维基共享资源 File 搜索（学名 / 英文名）。

仓库根目录运行:
  python3 flower/scripts/retry_fail_plants_images.py
  python3 flower/scripts/retry_fail_plants_images.py --no-p18-commons
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import fetch_plants as fp
import fetch_from_top_lists as fl

FLOWER_DIR = fp.FLOWER_DIR
FAIL_PATH = FLOWER_DIR / "fail_plants.txt"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"


def wiki_url_to_title(url: str) -> str:
    if not url or "/wiki/" not in url:
        return ""
    path = url.split("/wiki/", 1)[-1].split("#")[0].split("?")[0]
    return urllib.parse.unquote(path).replace("_", " ").strip()


def parse_fail_file(path: Path) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s:
            continue
        if "\t" in s:
            a, b = s.split("\t", 1)
        else:
            parts = s.split(None, 1)
            if len(parts) < 2:
                continue
            a, b = parts[0], parts[1]
        try:
            out.append((int(a.strip()), b.strip()))
        except ValueError:
            print("skip line:", repr(s), file=sys.stderr)
    return out


def fetch_thumbs_for_titles(titles: list[str]) -> dict[str, str]:
    """请求标题 -> 缩略图 URL（可能为空）。"""
    uniq = [t for t in dict.fromkeys(titles) if t]
    out: dict[str, str] = {}
    batch_size = 25
    for i in range(0, len(uniq), batch_size):
        batch = uniq[i : i + batch_size]
        by_t, norm, red = fp.fetch_batch_zh(batch)
        for req in batch:
            key = fp.final_title(req, norm, red)
            p = by_t.get(key)
            thumb = ((p or {}).get("image") or "").strip()
            out[req] = thumb
        time.sleep(0.35)
    return out


def pick_thumb_for_row(
    row: dict,
    thumbs: dict[str, str],
) -> str:
    wiki = (row.get("wiki") or "").strip()
    name = (row.get("nameZh") or "").strip()
    for t in (wiki_url_to_title(wiki), name):
        if t and thumbs.get(t):
            return thumbs[t]
    return ""


def extract_p18(entity: dict) -> str:
    preferred = ""
    normal = ""
    for c in (entity.get("claims") or {}).get("P18", []):
        sn = c.get("mainsnak", {})
        if sn.get("snaktype") != "value":
            continue
        val = sn.get("datavalue", {}).get("value")
        if not isinstance(val, str) or not val.strip():
            continue
        rank = c.get("rank", "normal")
        if rank == "preferred":
            preferred = val.strip()
        elif not normal:
            normal = val.strip()
    return preferred or normal


def zh_titles_to_qids(titles: list[str]) -> dict[str, str]:
    """中文条目标题 -> Wikidata Q 号（与请求串一致作 key）。"""
    out: dict[str, str] = {}
    uniq = [t for t in dict.fromkeys(titles) if t]
    batch_size = 48
    for i in range(0, len(uniq), batch_size):
        batch = uniq[i : i + batch_size]
        data = fp.api_get(
            fp.ZH_API,
            {
                "action": "query",
                "format": "json",
                "titles": "|".join(batch),
                "prop": "pageprops",
                "ppprop": "wikibase_item",
                "redirects": "1",
            },
        )
        q = data.get("query", {})
        normalized = {n["from"]: n["to"] for n in (q.get("normalized") or [])}
        redir = {r["from"]: r["to"] for r in (q.get("redirects") or [])}
        title_to_qid: dict[str, str] = {}
        for _pid, page in (q.get("pages") or {}).items():
            if int(page.get("pageid", 0)) < 0:
                continue
            t = page.get("title") or ""
            qid = ((page.get("pageprops") or {}).get("wikibase_item") or "").strip()
            title_to_qid[t] = qid
        for req in batch:
            ft = fp.final_title(req, normalized, redir)
            out[req] = (title_to_qid.get(ft) or "").strip()
        time.sleep(0.25)
    return out


def commons_imageinfo_url(file_title: str) -> str:
    """File: 全名或仅文件名 -> imageinfo thumburl（约宽 900）。"""
    ft = (file_title or "").strip()
    if not ft:
        return ""
    if not ft.startswith("File:"):
        ft = f"File:{ft}"
    data = fp.api_get(
        COMMONS_API,
        {
            "action": "query",
            "format": "json",
            "titles": ft,
            "prop": "imageinfo",
            "iiprop": "url",
            "iiurlwidth": "900",
        },
    )
    for _pid, page in (data.get("query") or {}).get("pages", {}).items():
        if int(page.get("pageid", 0)) < 0:
            continue
        ii = (page.get("imageinfo") or [{}])[0]
        u = (ii.get("thumburl") or ii.get("url") or "").strip()
        return u
    return ""


def fetch_p18_urls_for_qids(qids: list[str]) -> dict[str, str]:
    """Q 号 -> 可下载图片 URL（Commons imageinfo）。"""
    uniq = [q for q in dict.fromkeys(qids) if q.startswith("Q")]
    out: dict[str, str] = {}
    for i in range(0, len(uniq), 45):
        batch = uniq[i : i + 45]
        data = fp.api_get(
            fp.WD_API,
            {
                "action": "wbgetentities",
                "format": "json",
                "ids": "|".join(batch),
                "props": "claims",
            },
        )
        for qid, ent in (data.get("entities") or {}).items():
            if ent.get("missing") or ent.get("redirect"):
                continue
            fn = extract_p18(ent)
            if not fn:
                continue
            url = commons_imageinfo_url(fn)
            if url:
                out[qid] = url
        time.sleep(0.35)
    return out


def row_zh_title_priority(row: dict, row_alt: dict[int, str]) -> list[str]:
    out: list[str] = []
    wt = wiki_url_to_title((row.get("wiki") or "").strip())
    if wt:
        out.append(wt)
    aid = row_alt.get(int(row["id"]))
    if aid:
        out.append(aid)
    zn = (row.get("nameZh") or "").strip()
    if zn:
        out.append(zn)
    return out


def first_qid_for_row(
    row: dict,
    row_alt: dict[int, str],
    title_to_qid: dict[str, str],
) -> str:
    for t in row_zh_title_priority(row, row_alt):
        qid = (title_to_qid.get(t) or "").strip()
        if qid.startswith("Q"):
            return qid
    return ""


def commons_search_queries(row: dict) -> list[str]:
    """用于共享资源搜索的查询（优先拉丁学名、英文俗名；皆无则用中文名）。"""
    q: list[str] = []
    sci = (row.get("nameSci") or "").strip()
    if sci and not fp.contains_cjk(sci):
        q.append(sci)
    en = (row.get("nameEn") or "").strip()
    if en and not fp.contains_cjk(en):
        q.append(en)
    if not q:
        zn = (row.get("nameZh") or "").strip()
        if zn:
            q.append(zn)
    return list(dict.fromkeys(q))


def commons_search_first_image_url(query: str) -> str:
    if not query or len(query.strip()) < 2:
        return ""
    data = fp.api_get(
        COMMONS_API,
        {
            "action": "query",
            "format": "json",
            "generator": "search",
            "gsrsearch": query.strip(),
            "gsrnamespace": "6",
            "gsrlimit": "5",
            "prop": "imageinfo",
            "iiprop": "url",
            "iiurlwidth": "900",
        },
    )
    pages = (data.get("query") or {}).get("pages") or {}
    for p in pages.values():
        if int(p.get("ns", 0)) != 6:
            continue
        ii = (p.get("imageinfo") or [{}])[0]
        u = (ii.get("thumburl") or ii.get("url") or "").strip()
        if u:
            return u
    return ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fail-file", type=Path, default=FAIL_PATH)
    ap.add_argument("--json", type=Path, default=FLOWER_DIR / "plants.json")
    ap.add_argument(
        "--sleep",
        type=float,
        default=1.05,
        help="每次成功下载后的间隔（秒），减轻 429",
    )
    ap.add_argument(
        "--no-p18-commons",
        action="store_true",
        help="关闭 Wikidata P18 与共享资源搜索兜底",
    )
    args = ap.parse_args()

    fail_path = args.fail_file.resolve()
    json_path = args.json.resolve()
    if not fail_path.is_file():
        print("Missing", fail_path, file=sys.stderr)
        return 1
    data = json.loads(json_path.read_text(encoding="utf-8"))
    plants: list[dict] = data.get("plants") or []
    by_id = {int(r["id"]): r for r in plants}

    pairs = parse_fail_file(fail_path)
    retry_rows: list[dict] = []
    for pid, name_hint in pairs:
        r = by_id.get(pid)
        if not r:
            print("unknown id", pid, file=sys.stderr)
            continue
        if (r.get("nameZh") or "").strip() != name_hint:
            print(
                f"warn id={pid}: fail file name {name_hint!r} != json {r.get('nameZh')!r}",
                file=sys.stderr,
            )
        if (r.get("image") or "").strip():
            print(f"skip id={pid} (already has image)", file=sys.stderr)
            continue
        retry_rows.append(r)

    if not retry_rows:
        print("Nothing to retry.", file=sys.stderr)
        return 0

    max_pid = max(int(r["id"]) for r in plants)
    stem_w = fp.image_stem_width(max_pid)

    # 第一轮：维基链接标题 + 中文名
    titles_round1: list[str] = []
    for r in retry_rows:
        wt = wiki_url_to_title((r.get("wiki") or "").strip())
        name = (r.get("nameZh") or "").strip()
        if wt:
            titles_round1.append(wt)
        if name:
            titles_round1.append(name)
    thumbs: dict[str, str] = fetch_thumbs_for_titles(titles_round1)

    # 第二轮：仍无缩略图的用 opensearch（每行只搜一次，标题批量拉缩略图）
    need_search = [r for r in retry_rows if not pick_thumb_for_row(r, thumbs)]
    row_alt: dict[int, str] = {}
    alt_titles: list[str] = []
    for r in need_search:
        alt = fl.opensearch_first_title((r.get("nameZh") or "").strip())
        time.sleep(0.12)
        if alt:
            row_alt[int(r["id"])] = alt
            alt_titles.append(alt)
    thumbs.update(fetch_thumbs_for_titles(alt_titles))

    def thumb_url_for_row(r: dict) -> str:
        u = pick_thumb_for_row(r, thumbs)
        if u:
            return u
        alt = row_alt.get(int(r["id"]))
        if alt:
            return (thumbs.get(alt) or "").strip()
        return ""

    title_to_qid: dict[str, str] = {}
    qid_to_p18_url: dict[str, str] = {}
    if not args.no_p18_commons:
        zht: list[str] = []
        for r in retry_rows:
            zht.extend(row_zh_title_priority(r, row_alt))
        title_to_qid = zh_titles_to_qids(list(dict.fromkeys(zht)))
        qs_u = list(
            dict.fromkeys(
                q
                for q in (
                    first_qid_for_row(r, row_alt, title_to_qid) for r in retry_rows
                )
                if q.startswith("Q")
            )
        )
        qid_to_p18_url = fetch_p18_urls_for_qids(qs_u)
        print(
            f"P18 prefetch: {len(qid_to_p18_url)}/{len(qs_u)} Wikidata items with Commons image.",
            file=sys.stderr,
        )

    emb_path = json_path.with_name("plants.embedded.js")

    def persist() -> int:
        json_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        emb_path.write_text(
            "/* Generated — keep in sync with plants.json */\n"
            "window.__PLANTS_PAYLOAD__ = "
            + json.dumps(data, ensure_ascii=False, separators=(",", ":"))
            + ";\n",
            encoding="utf-8",
        )
        still_lines: list[str] = []
        for row in plants:
            if not (row.get("image") or "").strip():
                still_lines.append(f"{int(row['id'])}\t{row.get('nameZh', '')}")
        fail_path.write_text(
            "\n".join(still_lines) + ("\n" if still_lines else ""),
            encoding="utf-8",
        )
        return len(still_lines)

    print(f"Retrying {len(retry_rows)} plants (stem width {stem_w}) …", file=sys.stderr)
    ok = 0
    for r in retry_rows:
        pid = int(r["id"])
        tried_urls: set[str] = set()

        def try_download(url: str, label: str) -> bool:
            nonlocal ok
            if not url or url in tried_urls:
                return False
            tried_urls.add(url)
            path = fl.download_plant_image(pid, url, stem_w)
            if path:
                r["image"] = path
                ok += 1
                print(f"  id={pid} ok -> {path} ({label})", file=sys.stderr)
                return True
            return False

        done = False
        u_zh = thumb_url_for_row(r)
        if u_zh:
            done = try_download(u_zh, "zh-thumb")

        if not done and not args.no_p18_commons:
            qid = first_qid_for_row(r, row_alt, title_to_qid)
            u_p18 = (qid_to_p18_url.get(qid) or "").strip() if qid else ""
            if u_p18:
                done = try_download(u_p18, "P18")

        if not done and not args.no_p18_commons:
            for cq in commons_search_queries(r):
                u_c = commons_search_first_image_url(cq)
                time.sleep(0.3)
                if u_c and try_download(u_c, "Commons"):
                    done = True
                    break

        if not done:
            if not tried_urls:
                print(f"  id={pid} no image URL", file=sys.stderr)
            else:
                print(
                    f"  id={pid} download failed ({len(tried_urls)} URL(s) tried)",
                    file=sys.stderr,
                )

        persist()
        time.sleep(max(0.0, args.sleep))

    n_fail = persist()
    print(f"Downloaded {ok}/{len(retry_rows)}. fail_plants.txt -> {n_fail} lines.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

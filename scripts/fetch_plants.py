#!/usr/bin/env python3
"""
Fetch plant data from Chinese Wikipedia + Wikidata.
Run from repo root: python3 flower/scripts/fetch_plants.py
Outputs: flower/plants.json, flower/plants.embedded.js, flower/image/*（配图缓存）。
plants.json 中 image 可为逗号分隔多图 URL/路径；第 1 张存为 image/NNN.ext，其余为 image/NNN-2.ext 等。

Each entry: (卡片显示名, 中文维基条目名)
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ZH_API = "https://zh.wikipedia.org/w/api.php"
WD_API = "https://www.wikidata.org/w/api.php"
# 维基媒体要求 UA 可识别用途；请把邮箱改成你自己的，便于被封禁时联系
USER_AGENT = (
    "FlowerPlantGallery/1.0 (personal static plant gallery; "
    "+https://github.com/) Python/3 urllib"
)

# 100 × (显示中文名, 中文维基条目名)
ENTRIES: list[tuple[str, str]] = [
    ("月季", "大花香水月季"),
    ("蔷薇", "蔷薇"),
    ("杜鹃花", "杜鹃花"),
    ("茉莉花", "茉莉花"),
    ("栀子花", "栀子花"),
    ("桂花", "桂花"),
    ("兰科", "兰科"),
    ("百合属", "百合属"),
    ("郁金香", "郁金香"),
    ("风信子", "风信子"),
    ("绣球花", "绣球花"),
    ("牡丹", "牡丹"),
    ("芍药属", "芍药属"),
    ("海棠", "海棠"),
    ("樱花", "樱花"),
    ("桃花", "桃花"),
    ("梅花", "梅花"),
    ("莲", "莲"),
    ("睡莲", "睡莲"),
    ("石竹", "石竹"),
    ("三色堇", "三色堇"),
    ("碧冬茄", "碧冬茄"),
    ("天竺葵", "天竺葵"),
    ("薰衣草", "薰衣草"),
    ("迷迭香", "迷迭香"),
    ("薄荷", "薄荷"),
    ("鼠尾草属", "鼠尾草属"),
    ("紫苏", "紫苏"),
    ("罗勒", "罗勒"),
    ("蕨类植物", "蕨类植物"),
    ("苔藓植物门", "苔藓植物门"),
    ("绿萝", "绿萝"),
    ("龟背竹", "龟背竹"),
    ("虎尾兰", "虎尾兰"),
    ("吊兰", "吊兰"),
    ("文竹", "文竹"),
    ("瓜栗", "瓜栗"),
    ("印度榕", "印度榕"),
    ("琴叶榕", "琴叶榕"),
    ("向日葵", "向日葵"),
    ("菊花", "菊花"),
    ("香石竹", "香石竹"),
    ("玫瑰", "玫瑰"),
    ("水仙属", "水仙属"),
    ("蝴蝶兰", "蝴蝶兰"),
    ("石斛兰", "石斛属"),
    ("君子兰", "君子兰"),
    ("仙客来", "仙客来"),
    ("长寿花", "长寿花"),
    ("蟹爪兰", "蟹爪兰"),
    ("非洲紫罗兰", "非洲堇"),
    ("一叶兰", "蜘蛛抱蛋"),
    ("花叶万年青", "花叶万年青"),
    ("南美天胡荽", "南美天胡荽"),
    ("多肉植物", "多肉植物"),
    ("仙人掌", "仙人掌"),
    ("芦荟", "芦荟"),
    ("常春藤", "常春藤"),
    ("白鹤芋", "白鹤芋"),
    ("火鹤花", "火鹤花"),
    ("果子蔓", "果子蔓"),
    ("牵牛花", "牵牛花"),
    ("鸢尾属", "鸢尾属"),
    ("铃兰", "铃兰"),
    ("玉簪", "玉簪"),
    ("蜀葵", "蜀葵"),
    ("虞美人", "虞美人 (植物)"),
    ("波斯菊", "秋英"),
    ("大丽花", "大丽花"),
    ("马蹄莲", "马蹄莲"),
    ("朱顶红", "朱顶红"),
    ("黄花风铃木", "金风铃"),  # 中文维基无「黄花风铃木」条目，内容在「金风铃」
    ("紫荆", "紫荆"),
    ("木槿", "木槿"),
    ("夹竹桃", "夹竹桃"),
    ("鸡蛋花", "鸡蛋花"),
    ("玉兰", "玉兰"),
    ("紫藤", "紫藤"),
    ("迎春花", "迎春花"),
    ("连翘", "连翘"),
    ("紫丁香", "紫丁香"),
    ("含笑花", "含笑花"),
    ("昙花", "昙花"),
    ("虎刺梅", "虎刺梅"),
    ("龙舌兰属", "龙舌兰属"),
    ("鹤望兰", "鹤望兰"),
    ("猪笼草", "猪笼草"),
    ("捕蝇草", "捕蠅草"),  # 维基标题用繁体「蠅」
    ("含羞草", "含羞草"),
    ("白三叶草", "白三叶草"),
    ("苜蓿", "苜蓿"),
    ("蒲公英", "蒲公英"),
    ("狗尾草", "狗尾草"),
    ("文心兰", "文心蘭"),
    ("大花蕙兰", "大花蕙兰"),
    ("建兰", "建兰"),
    ("春兰", "春兰"),
    ("银柳", "银柳"),
    ("蜡梅", "蜡梅"),
    ("山茶花", "山茶花"),
]

# 卡片展示用英文俗名（首字母经 pretty_english_common 格式化为标题大小写）
COMMON_NAME_EN: dict[str, str] = {
    "月季": "China rose",
    "蔷薇": "Multiflora rose",
    "杜鹃花": "Azalea",
    "茉莉花": "Arabian jasmine",
    "栀子花": "Gardenia",
    "桂花": "Sweet osmanthus",
    "兰科": "Orchid family",
    "百合属": "True lily",
    "郁金香": "Tulip",
    "风信子": "Hyacinth",
    "绣球花": "Bigleaf hydrangea",
    "牡丹": "Tree peony",
    "芍药属": "Peony",
    "海棠": "Crabapple",
    "樱花": "Cherry blossom",
    "桃花": "Peach blossom",
    "梅花": "Plum blossom",
    "莲": "Lotus",
    "睡莲": "Water lily",
    "石竹": "Carnation",
    "三色堇": "Pansy",
    "碧冬茄": "Petunia",
    "天竺葵": "Geranium",
    "薰衣草": "Lavender",
    "迷迭香": "Rosemary",
    "薄荷": "Mint",
    "鼠尾草属": "Sage",
    "紫苏": "Perilla",
    "罗勒": "Basil",
    "蕨类植物": "Fern",
    "苔藓植物门": "Moss",
    "绿萝": "Pothos",
    "龟背竹": "Swiss cheese plant",
    "虎尾兰": "Snake plant",
    "吊兰": "Spider plant",
    "文竹": "Asparagus fern",
    "瓜栗": "Money tree",
    "印度榕": "Indian rubber tree",
    "琴叶榕": "Fiddle-leaf fig",
    "向日葵": "Sunflower",
    "菊花": "Chrysanthemum",
    "香石竹": "Carnation",
    "玫瑰": "Rose",
    "水仙属": "Daffodil",
    "蝴蝶兰": "Moth orchid",
    "石斛兰": "Dendrobium orchid",
    "君子兰": "Bush lily",
    "仙客来": "Cyclamen",
    "长寿花": "Flaming Katy",
    "蟹爪兰": "Thanksgiving cactus",
    "非洲紫罗兰": "African violet",
    "一叶兰": "Cast-iron plant",
    "花叶万年青": "Dumb cane",
    "南美天胡荽": "Whorled pennywort",
    "多肉植物": "Succulent",
    "仙人掌": "Cactus",
    "芦荟": "Aloe vera",
    "常春藤": "Ivy",
    "白鹤芋": "Peace lily",
    "火鹤花": "Flamingo flower",
    "果子蔓": "Scarlet star",
    "牵牛花": "Morning glory",
    "鸢尾属": "Iris",
    "铃兰": "Lily of the valley",
    "玉簪": "Plantain lily",
    "蜀葵": "Hollyhock",
    "虞美人": "Corn poppy",
    "波斯菊": "Cosmos",
    "大丽花": "Dahlia",
    "马蹄莲": "Calla lily",
    "朱顶红": "Amaryllis",
    "黄花风铃木": "Golden trumpet tree",
    "紫荆": "Chinese redbud",
    "木槿": "Rose of Sharon",
    "夹竹桃": "Oleander",
    "鸡蛋花": "Frangipani",
    "玉兰": "Yulan magnolia",
    "紫藤": "Wisteria",
    "迎春花": "Winter jasmine",
    "连翘": "Forsythia",
    "紫丁香": "Lilac",
    "含笑花": "Banana shrub",
    "昙花": "Queen of the night",
    "虎刺梅": "Crown of thorns",
    "龙舌兰属": "Century plant",
    "鹤望兰": "Bird of paradise",
    "猪笼草": "Tropical pitcher plant",
    "捕蝇草": "Venus flytrap",
    "含羞草": "Sensitive plant",
    "白三叶草": "White clover",
    "苜蓿": "Alfalfa",
    "蒲公英": "Dandelion",
    "狗尾草": "Green foxtail",
    "文心兰": "Dancing-lady orchid",
    "大花蕙兰": "Cymbidium orchid",
    "建兰": "Rock orchid",
    "春兰": "Spring orchid",
    "银柳": "Pussy willow",
    "蜡梅": "Wintersweet",
    "山茶花": "Camellia",
}

# 少数条目缺拉丁学名时补齐（英文俗名已由 COMMON_NAME_EN 覆盖）
SCI_FALLBACK: dict[str, str] = {
    "南美天胡荽": "Hydrocotyle verticillata",
    "果子蔓": "Guzmania lingulata",
    "黄花风铃木": "Tabebuia chrysantha",
    "捕蝇草": "Dionaea muscipula",
}

IMAGE_FALLBACK: dict[str, str] = {
    "月季": "https://upload.wikimedia.org/wikipedia/commons/thumb/3/32/Divlja_ruza_cvijet_270508.jpg/960px-Divlja_ruza_cvijet_270508.jpg",
    # 旧 Tabebuia/Dionaea 缩略图在 Commons 上已失效，改用仍存在的文件
    "黄花风铃木": "https://upload.wikimedia.org/wikipedia/commons/thumb/1/18/Handroanthus_chrysanthus.jpg/960px-Handroanthus_chrysanthus.jpg",
    "捕蝇草": "https://upload.wikimedia.org/wikipedia/commons/thumb/3/37/Venus_Flytrap_showing_trigger_hairs.jpg/960px-Venus_Flytrap_showing_trigger_hairs.jpg",
    "果子蔓": "https://upload.wikimedia.org/wikipedia/commons/8/84/Bromeliaceae03.jpg",
}

_CJK_RE = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff\uac00-\ud7af]")

SCRIPT_DIR = Path(__file__).resolve().parent
FLOWER_DIR = SCRIPT_DIR.parent
IMAGE_DIR = FLOWER_DIR / "image"


def download_bytes(url: str) -> bytes:
    """带 429 退避重试（维基共享对过快请求会限流）。"""
    for attempt in range(5):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 4:
                wait = min(90, 6 * (2**attempt))
                print(f"  HTTP 429, sleep {wait}s …", file=sys.stderr)
                time.sleep(wait)
                continue
            raise
    raise AssertionError("unreachable")


def wikimedia_thumb_to_original(url: str) -> str:
    """commons/thumb/a/ab/file.jpg/800px-file.jpg → commons/a/ab/file.jpg"""
    marker = "/wikipedia/commons/thumb/"
    if marker not in url:
        return url
    pre, _, rest = url.partition(marker)
    parts = rest.split("/")
    if len(parts) < 4:
        return url
    orig_path = "/".join(parts[:-1])
    return f"{pre}/wikipedia/commons/{orig_path}"


def guess_image_ext(data: bytes, url: str) -> str:
    if len(data) >= 3 and data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if len(data) >= 8 and data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    lu = url.split("?")[0].lower()
    for ext, out in ((".jpeg", ".jpg"), (".jpg", ".jpg"), (".png", ".png"), (".webp", ".webp")):
        if lu.endswith(ext):
            return out
    return ".jpg"


def image_stem_width(max_plant_id: int) -> int:
    """本地文件名数字位数：至少 3（兼容 000.jpg），id≥1000 时用 4 位。"""
    return max(3, len(str(max(max_plant_id, 0))))


def _image_basename_for_slot(plant_id: int, slot: int, ext: str, stem_width: int = 3) -> str:
    """第 0 张为 0071.jpg（宽度由 stem_width 决定），其余为 0071-2.jpg …"""
    w = max(3, stem_width)
    stem = format(plant_id, f"0{w}d")
    if slot <= 0:
        return f"{stem}{ext}"
    return f"{stem}-{slot + 1}{ext}"


def cache_image_to_disk(
    plant_id: int, url: str, slot: int = 0, *, stem_width: int = 3
) -> str:
    """下载到 flower/image/，返回相对路径 image/xxx.ext；失败则退回原始 URL。slot 用于同一 id 多图文件名。"""
    if not url or not url.startswith("http"):
        return url
    candidates = [url]
    alt = wikimedia_thumb_to_original(url)
    if alt != url:
        candidates.append(alt)
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    for i, u in enumerate(candidates):
        try:
            data = download_bytes(u)
            ext = guess_image_ext(data, u)
            fname = _image_basename_for_slot(plant_id, slot, ext, stem_width)
            dest = IMAGE_DIR / fname
            dest.write_bytes(data)
            return f"image/{fname}"
        except urllib.error.HTTPError as ex:
            if i < len(candidates) - 1:
                print(f"  id={plant_id} HTTP {ex.code}, try alternate URL …", file=sys.stderr)
                continue
            print(f"Image download failed id={plant_id}: {ex}", file=sys.stderr)
        except Exception as ex:
            print(f"Image download failed id={plant_id}: {ex}", file=sys.stderr)
            break
    return url


def cache_image_field(
    plant_id: int, image_field: str, *, stem_width: int = 3
) -> str:
    """image 可为逗号分隔多 URL；依次下载，非 http 段原样保留。"""
    parts = [p.strip() for p in (image_field or "").split(",") if p.strip()]
    if not parts:
        return ""
    out: list[str] = []
    for slot, part in enumerate(parts):
        if part.startswith("http"):
            out.append(cache_image_to_disk(plant_id, part, slot, stem_width=stem_width))
            time.sleep(1.05)
        else:
            out.append(part)
    return ",".join(out)


def contains_cjk(s: str) -> bool:
    return bool(s and _CJK_RE.search(s))


def api_get(url: str, params: dict) -> dict:
    q = urllib.parse.urlencode(params, safe="|")
    req = urllib.request.Request(
        f"{url}?{q}",
        headers={"User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read().decode("utf-8"))


def clean_extract(text: str, max_len: int = 400) -> str:
    if not text:
        return ""
    t = re.sub(r"\s+", " ", text).strip()
    if len(t) <= max_len:
        return t
    cut = t[: max_len - 1]
    if "。" in cut:
        cut = cut[: cut.rfind("。") + 1]
    elif "，" in cut:
        cut = cut[: cut.rfind("，")] + "…"
    else:
        cut = cut + "…"
    return cut


def clean_scientific_name(raw: str) -> str:
    """去掉杂交符号 ×/x、合并多余空格。"""
    if not raw:
        return ""
    t = raw.strip()
    for ch in ("\u00d7", "\u2715", "\u2a2f"):
        t = t.replace(ch, " ")
    t = re.sub(r"\s+[xX]\s+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"[，,。．;；、]+$", "", t).strip()
    return t


def parse_scientific_from_extract(desc: str) -> str:
    if not desc:
        return ""
    m = re.search(r"[學学]名[：:]\s*([^，。；、\n]+)", desc)
    if not m:
        return ""
    raw = m.group(1).strip()
    raw = raw.split("（")[0].split("(")[0].strip()
    if contains_cjk(raw):
        m2 = re.match(r"^([A-Za-z][A-Za-z0-9_.\s·()-]+)", raw)
        return m2.group(1).strip() if m2 else ""
    return raw


def extract_p225(entity: dict) -> str:
    claims = entity.get("claims", {})
    p225 = claims.get("P225", [])
    preferred = ""
    normal = ""
    for c in p225:
        sn = c.get("mainsnak", {})
        if sn.get("snaktype") != "value":
            continue
        val = sn.get("datavalue", {}).get("value")
        if not isinstance(val, str) or not val:
            continue
        rank = c.get("rank", "normal")
        if rank == "preferred":
            preferred = val
        elif not normal:
            normal = val
    return preferred or normal


def extract_en_label(entity: dict) -> str:
    return (entity.get("labels", {}).get("en", {}) or {}).get("value", "") or ""


def extract_enwiki_title(entity: dict) -> str:
    t = (entity.get("sitelinks", {}).get("enwiki", {}) or {}).get("title", "") or ""
    return t.replace("_", " ") if t else ""


def extract_p1843_en(entity: dict) -> list[str]:
    """Wikidata P1843 taxon common name，仅取英语。"""
    out: list[tuple[int, str]] = []
    rank_order = {"preferred": 0, "normal": 1, "deprecated": 9}
    for c in (entity.get("claims") or {}).get("P1843", []):
        sn = c.get("mainsnak", {})
        if sn.get("snaktype") != "value":
            continue
        dv = sn.get("datavalue", {})
        if dv.get("type") != "monolingualtext":
            continue
        val = dv.get("value") or {}
        if val.get("language") != "en":
            continue
        text = (val.get("text") or "").strip()
        if not text:
            continue
        rk = rank_order.get(c.get("rank", "normal"), 5)
        out.append((rk, text))
    out.sort(key=lambda x: x[0])
    return [t[1] for t in out]


def extract_aliases_en(entity: dict) -> list[str]:
    als = (entity.get("aliases") or {}).get("en", [])
    if not isinstance(als, list):
        return []
    return [a["value"].strip() for a in als if isinstance(a, dict) and (a.get("value") or "").strip()]


def looks_like_latin_binomial(s: str) -> bool:
    """粗判双名法学名（属大写 + 种小写），用于过滤非俗名。"""
    s = clean_scientific_name(s)
    parts = [p for p in s.split() if p]
    if len(parts) < 2:
        return False
    g, sp = parts[0], parts[1]
    if re.match(r"^[A-Z][a-zA-Z0-9-]*$", g) and re.match(r"^[a-z][a-z0-9-]*$", sp):
        return True
    return False


def pretty_english_common(s: str) -> str:
    """英文俗名标题大小写：Rose, Venus Flytrap, Lily of the Valley。"""
    s = re.sub(r"\s+", " ", (s or "").strip())
    if not s:
        return s
    small = {"and", "or", "of", "the", "in", "for", "a", "an", "to", "at", "by", "on"}
    words = s.split()
    res: list[str] = []

    def cap_word(w: str) -> str:
        if not w:
            return w
        return "-".join(
            (p[:1].upper() + p[1:].lower()) if len(p) > 1 else p.upper()
            for p in w.split("-")
            if p
        )

    for i, w in enumerate(words):
        low = w.lower()
        if 0 < i < len(words) - 1 and low in small:
            res.append(low)
        else:
            res.append(cap_word(w))
    return " ".join(res)


def fetch_wikidata_map(qids: list[str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    uniq = [q for q in dict.fromkeys(qids) if q]
    for i in range(0, len(uniq), 45):
        batch = uniq[i : i + 45]
        data = api_get(
            WD_API,
            {
                "action": "wbgetentities",
                "format": "json",
                "ids": "|".join(batch),
                "props": "labels|aliases|claims|sitelinks",
                "languages": "en",
            },
        )
        for qid, ent in (data.get("entities") or {}).items():
            if ent.get("missing") or ent.get("redirect"):
                continue
            out[qid] = {
                "label_en": extract_en_label(ent).strip(),
                "enwiki_title": extract_enwiki_title(ent).strip(),
                "p225": extract_p225(ent).strip(),
                "p1843_en": extract_p1843_en(ent),
                "aliases_en": extract_aliases_en(ent),
            }
        time.sleep(0.35)
    return out


def fetch_batch_zh(titles: list[str]) -> tuple[dict[str, dict], dict[str, str], dict[str, str]]:
    data = api_get(
        ZH_API,
        {
            "action": "query",
            "format": "json",
            "redirects": "1",
            "titles": "|".join(titles),
            "prop": "extracts|pageimages|langlinks|info|pageprops",
            "exintro": "1",
            "explaintext": "1",
            "piprop": "thumbnail",
            "pithumbsize": "900",
            "ppprop": "wikibase_item",
            "lllang": "en",
            "lllimit": "1",
            "inprop": "url",
        },
    )
    q = data.get("query", {})
    pages_raw = q.get("pages", {})
    normalized: dict[str, str] = {}
    for n in q.get("normalized") or []:
        normalized[n.get("from", "")] = n.get("to", "")
    redirect: dict[str, str] = {}
    for r in q.get("redirects") or []:
        redirect[r.get("from", "")] = r.get("to", "")

    pages_by_title: dict[str, dict] = {}
    for _pid, p in pages_raw.items():
        if int(p.get("pageid", 0)) < 0:
            continue
        title_zh = p.get("title") or ""
        ext = clean_extract(p.get("extract") or "")
        thumb = (p.get("thumbnail") or {}).get("source")
        wiki_url = p.get("fullurl") or f"https://zh.wikipedia.org/wiki/{urllib.parse.quote(title_zh.replace(' ', '_'))}"
        en = ""
        for ll in p.get("langlinks") or []:
            if ll.get("lang") == "en":
                en = (ll.get("*") or "").replace("_", " ")
                break
        pp = p.get("pageprops") or {}
        wb = (pp.get("wikibase_item") or "").strip()
        pages_by_title[title_zh] = {
            "titleZh": title_zh,
            "titleEn": en,
            "desc": ext,
            "image": thumb,
            "wiki": wiki_url,
            "wikibase_item": wb,
        }
    return pages_by_title, normalized, redirect


def final_title(requested: str, normalized: dict[str, str], redirect: dict[str, str]) -> str:
    t = normalized.get(requested, requested)
    seen = set()
    while t in redirect and t not in seen:
        seen.add(t)
        t = redirect[t]
    return t


def colloquial_english_from_wikidata(p: dict, wd: dict | None) -> str:
    """无手工俗名表时的后备：P1843 英文俗名 → 非学名别名 → 维基标题（过滤学名形态）。"""
    wd = wd or {}
    for t in wd.get("p1843_en") or []:
        if t and not contains_cjk(t):
            return t
    for t in wd.get("aliases_en") or []:
        if not t or contains_cjk(t):
            continue
        if looks_like_latin_binomial(t):
            continue
        return t
    wiki = (wd.get("enwiki_title") or "").strip()
    if wiki and not contains_cjk(wiki) and not looks_like_latin_binomial(wiki):
        return wiki
    ll = (p.get("titleEn") or "").strip()
    if ll and not contains_cjk(ll) and not looks_like_latin_binomial(ll):
        return ll
    label = (wd.get("label_en") or "").strip()
    if label and not contains_cjk(label) and not looks_like_latin_binomial(label):
        return label
    for s in (wiki, ll, label):
        if s and not contains_cjk(s):
            return s
    return ""


def compose_scientific_name(p: dict, wd: dict | None) -> str:
    wd = wd or {}
    sci = clean_scientific_name(wd.get("p225") or "")
    if sci and not contains_cjk(sci):
        return sci
    parsed = clean_scientific_name(parse_scientific_from_extract(p.get("desc", "")))
    if parsed and not contains_cjk(parsed):
        return parsed
    sci2 = clean_scientific_name(wd.get("p225") or "")
    return sci2


def retry_remote_images_only() -> int:
    """仅把 JSON 里仍为 http(s) 的配图下载到 image/，并写回 json 与 embedded。"""
    out_path = Path(sys.argv[2]) if len(sys.argv) > 2 else FLOWER_DIR / "plants.json"
    data = json.loads(out_path.read_text(encoding="utf-8"))
    plants = data.get("plants") or []
    n = 0
    max_pid = max((int(r.get("id", 0)) for r in plants), default=0)
    stem_w = image_stem_width(max_pid)
    for row in plants:
        raw = (row.get("image") or "").strip()
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        if not any(p.startswith("http") for p in parts):
            continue
        pid = int(row.get("id", 0))
        row["image"] = cache_image_field(pid, raw, stem_width=stem_w)
        n += 1
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    emb = out_path.with_name("plants.embedded.js")
    emb.write_text(
        "/* Generated by flower/scripts/fetch_plants.py — keep in sync with plants.json */\n"
        "window.__PLANTS_PAYLOAD__ = "
        + json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        + ";\n",
        encoding="utf-8",
    )
    print("Retry finished; updated", n, "remote URLs ->", out_path, emb)
    return 0


def main() -> int:
    if len(ENTRIES) != 100:
        print("Expected 100 entries, got", len(ENTRIES), file=sys.stderr)
        return 1

    merged: dict[str, dict] = {}
    batch_size = 25
    for i in range(0, len(ENTRIES), batch_size):
        slice_e = ENTRIES[i : i + batch_size]
        batch_wikis = [w for _, w in slice_e]
        by_t, norm, red = fetch_batch_zh(batch_wikis)
        for name, wiki in slice_e:
            key = final_title(wiki, norm, red)
            row = by_t.get(key)
            if row:
                merged[name] = dict(row)
        time.sleep(0.35)

    qids = [merged[k]["wikibase_item"] for k in merged if merged[k].get("wikibase_item")]
    wd_map = fetch_wikidata_map(qids)

    ordered: list[dict] = []
    missing: list[str] = []
    for name, _wiki in ENTRIES:
        p = merged.get(name)
        if not p:
            missing.append(name)
            continue
        qid = p.get("wikibase_item") or ""
        wd = wd_map.get(qid)
        img = p["image"] or IMAGE_FALLBACK.get(name)
        ne = (COMMON_NAME_EN.get(name) or "").strip()
        if not ne:
            ne = colloquial_english_from_wikidata(p, wd)
        ne = pretty_english_common(re.sub(r"\s+", " ", (ne or "").strip()))
        ns = compose_scientific_name(p, wd)
        if not ns:
            ns = SCI_FALLBACK.get(name, "")
        ordered.append(
            {
                "id": len(ordered),
                "nameZh": name,
                "nameEn": ne,
                "nameSci": ns,
                "desc": "",
                "image": img,
                "wiki": p["wiki"],
            }
        )

    max_pid = max((int(r["id"]) for r in ordered), default=0)
    stem_w = image_stem_width(max_pid)
    print("Downloading images to", IMAGE_DIR, "...")
    for row in ordered:
        pid = row["id"]
        row["image"] = cache_image_field(pid, row.get("image") or "", stem_width=stem_w)

    payload = {
        "source": "文本与学名来源：中文维基百科 / 维基数据（CC BY-SA 等，见许可链接）。配图已缓存至本站 image/ 目录，原始文件多在维基共享资源。",
        "attribution": "https://zh.wikipedia.org | https://creativecommons.org/licenses/by-sa/4.0/deed.zh",
        "fetched": time.strftime("%Y-%m-%d"),
        "plants": ordered,
    }

    out_path = sys.argv[1] if len(sys.argv) > 1 else "flower/plants.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    emb_path = Path(out_path).with_name("plants.embedded.js")
    js = (
        "/* Generated by flower/scripts/fetch_plants.py — keep in sync with plants.json */\n"
        "window.__PLANTS_PAYLOAD__ = "
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        + ";\n"
    )
    with open(emb_path, "w", encoding="utf-8") as f:
        f.write(js)

    print("Wrote", out_path, "—", len(ordered), "plants")
    print("Wrote", emb_path)
    if missing:
        print("Missing titles:", ", ".join(missing), file=sys.stderr)
    no_img = [p["nameZh"] for p in ordered if not p.get("image")]
    if no_img:
        print("No thumbnail:", len(no_img), file=sys.stderr)
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--retry-images":
        raise SystemExit(retry_remote_images_only())
    raise SystemExit(main())

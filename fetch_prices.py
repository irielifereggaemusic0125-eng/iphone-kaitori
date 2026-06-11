#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
iPhone 17 シリーズ 買取価格取得スクリプト
取得元: ルデヤ / 森森買取 / 海映(海峡通信・モバイル一番)

出力:
  data/prices.json   … 最新の比較データ(HTMLが読む)
  data/history.json  … 価格推移の履歴(実行ごとに追記)

使い方:
  python3 fetch_prices.py
cron 例 (毎朝7時):
  0 7 * * * cd /path/to/app && /usr/bin/python3 fetch_prices.py >> log.txt 2>&1
"""

import requests
import re
import json
import os
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup

JST = timezone(timedelta(hours=9))
UA = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
}
TIMEOUT = 25
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

# ===== Apple 定価(税込・SIMフリー) 2025年9月発売時点 =====
# キー: (model, capacity)
LIST_PRICES = {
    ("iPhone 17 Pro Max", "256GB"): 194800,
    ("iPhone 17 Pro Max", "512GB"): 229800,
    ("iPhone 17 Pro Max", "1TB"):   264800,
    ("iPhone 17 Pro Max", "2TB"):   329800,
    ("iPhone 17 Pro", "256GB"):     179800,
    ("iPhone 17 Pro", "512GB"):     214800,
    ("iPhone 17 Pro", "1TB"):       249800,
    ("iPhone 17", "256GB"):         129800,
    ("iPhone 17", "512GB"):         164800,
    ("iPhone Air", "256GB"):        159800,
    ("iPhone Air", "512GB"):        194800,
    ("iPhone Air", "1TB"):          229800,
}

# モデル正規化(表記ゆれ吸収)
def normalize_model(text):
    t = text.replace("　", " ")
    t = re.sub(r"\s+", " ", t)
    # ProMax / Pro Max
    if re.search(r"17\s*Pro\s*Max", t, re.I) or "ProMax" in t.replace(" ", ""):
        return "iPhone 17 Pro Max"
    if re.search(r"17\s*Pro", t, re.I):
        return "iPhone 17 Pro"
    if re.search(r"17\s*Air|iPhone\s*Air", t, re.I):
        return "iPhone Air"
    if re.search(r"iPhone\s*17e", t, re.I):
        return "iPhone 17e"
    if re.search(r"iPhone\s*17", t, re.I):
        return "iPhone 17"
    return None

def normalize_capacity(text):
    m = re.search(r"(256GB|512GB|1TB|2TB|128GB)", text.replace(" ", ""))
    return m.group(1) if m else None

def normalize_color(text):
    # カラー表記を統一
    colors = {
        "シルバー": "シルバー", "銀": "シルバー",
        "ディープブルー": "ディープブルー", "青": "ディープブルー",
        "コズミックオレンジ": "コズミックオレンジ", "橙": "コズミックオレンジ", "オレンジ": "コズミックオレンジ",
        "ブラック": "ブラック", "ホワイト": "ホワイト", "ミストブルー": "ミストブルー",
        "セージ": "セージ", "ラベンダー": "ラベンダー",
        "スカイブルー": "スカイブルー", "クラウドホワイト": "クラウドホワイト",
        "ライトゴールド": "ライトゴールド", "スペースブラック": "スペースブラック",
    }
    for k, v in colors.items():
        if k in text:
            return v
    return ""

def to_int(price_str):
    digits = re.sub(r"[^\d]", "", price_str)
    return int(digits) if digits else None


# ============ 1) ルデヤ ============
RUDEYA_URLS = {
    "iPhone 17 Pro Max": "https://kaitori-rudeya.com/category/detail/220",
    "iPhone 17 Pro":     "https://kaitori-rudeya.com/category/detail/219",
}

def fetch_rudeya():
    results = []
    for model, url in RUDEYA_URLS.items():
        try:
            r = requests.get(url, headers=UA, timeout=TIMEOUT)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "lxml")
            for card in soup.select("article.pgrid-card"):
                name_el = card.select_one("a.product-card-name-link")
                price_el = card.select_one("span.product-card-price-value")
                if not name_el or not price_el:
                    continue
                txt = name_el.get_text(" ", strip=True)
                # 新品/未開封のみ対象
                cond_el = card.select_one("span.product-card-cond-badge")
                cond = (cond_el.get_text(strip=True) if cond_el else "")
                if "新品" not in cond and "未開封" not in txt:
                    continue
                cap = normalize_capacity(txt)
                if not cap:
                    continue
                color = normalize_color(txt)
                price_txt = price_el.get_text(" ", strip=True)
                price = to_int(price_txt)
                if not price or price < 10000:
                    continue
                results.append({
                    "shop": "ルデヤ",
                    "model": model,
                    "capacity": cap,
                    "color": color,
                    "price": price,
                })
        except Exception as e:
            print(f"[ルデヤ] {model} 取得失敗: {e}")
    return results


# ============ 2) 森森買取 ============
def fetch_morimori():
    results = []
    url = "https://www.morimori-kaitori.jp/search/iphone17?page=1&price-list=true"
    try:
        r = requests.get(url, headers=UA, timeout=TIMEOUT)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")
        for row in soup.select("table.price-list tr"):
            cells = [c.get_text(" ", strip=True) for c in row.find_all(["td", "th"])]
            if len(cells) < 7:
                continue
            name = cells[4]  # 商品名
            type_col = cells[3]  # 新品/中古
            price_str = cells[6]  # 通常買取価格
            model = normalize_model(name)
            cap = normalize_capacity(name)
            if not model or not cap:
                continue
            # 新品(未開封)のみ対象
            if "新品" not in type_col and "未開封" not in name:
                continue
            price = to_int(price_str)
            if not price or price < 10000:
                continue
            results.append({
                "shop": "森森",
                "model": model,
                "capacity": cap,
                "color": normalize_color(name),
                "price": price,
            })
    except Exception as e:
        print(f"[森森] 取得失敗: {e}")
    return results


# ============ 3) 海映(海峡通信/モバイル一番) ============
def fetch_kaiei():
    results = []
    url = "https://www.mobile-ichiban.com/"
    try:
        r = requests.get(url, headers=UA, timeout=TIMEOUT)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")
        for card in soup.select("div.card"):
            txt = card.get_text(" ", strip=True)
            if "iPhone 17" not in txt and "iPhone17" not in txt:
                continue
            if "未開封" not in txt and "新品" not in txt:
                continue
            name = txt.split("カラー")[0]
            model = normalize_model(name)
            cap = normalize_capacity(name)
            if not model or not cap:
                continue
            m = re.search(r"([\d,]+)円", txt)
            if not m:
                continue
            price = to_int(m.group(1))
            if not price or price < 10000:
                continue
            results.append({
                "shop": "海映",
                "model": model,
                "capacity": cap,
                "color": "",  # 海映は新品でカラー別価格を出さない
                "price": price,
            })
    except Exception as e:
        print(f"[海映] 取得失敗: {e}")
    return results


# ============ 集計 ============
# 取得対象を限定(機種, 容量)
TARGETS = {
    ("iPhone 17 Pro Max", "256GB"),
    ("iPhone 17 Pro", "256GB"),
}

def build_dataset(all_rows):
    """
    (model, capacity) ごとに 3店舗の価格をまとめる。
    カラー差は同一機種内の最高値を採用(各店の代表値)。
    """
    grouped = {}
    color_grouped = {}   # (model, capacity, color) -> {shop: price}
    for row in all_rows:
        key = (row["model"], row["capacity"])
        if key not in TARGETS:
            continue
        grouped.setdefault(key, {"ルデヤ": None, "森森": None})
        shop = row["shop"]
        cur = grouped[key][shop]
        if cur is None or row["price"] > cur:
            grouped[key][shop] = row["price"]
        # ---- カラー別 ----
        color = (row.get("color") or "").strip() or "（色指定なし）"
        ckey = (row["model"], row["capacity"], color)
        color_grouped.setdefault(ckey, {"ルデヤ": None, "森森": None})
        ccur = color_grouped[ckey][shop]
        if ccur is None or row["price"] > ccur:
            color_grouped[ckey][shop] = row["price"]

    items = []
    for (model, cap), shops in grouped.items():
        list_price = LIST_PRICES.get((model, cap))
        shop_prices = {k: v for k, v in shops.items() if v is not None}
        best = max(shop_prices.values()) if shop_prices else None
        best_shop = None
        if best is not None:
            best_shop = [k for k, v in shop_prices.items() if v == best][0]
        diff = (best - list_price) if (best is not None and list_price) else None

        # ---- カラー別の内訳を組み立て ----
        colors = []
        for (m, c, color), cshops in color_grouped.items():
            if m != model or c != cap:
                continue
            cprices = {k: v for k, v in cshops.items() if v is not None}
            cbest = max(cprices.values()) if cprices else None
            cbest_shop = ([k for k, v in cprices.items() if v == cbest][0]
                          if cbest is not None else None)
            cdiff = (cbest - list_price) if (cbest is not None and list_price) else None
            colors.append({
                "color": color,
                "shops": cshops,          # {"ルデヤ":x,"森森":y}
                "best_price": cbest,
                "best_shop": cbest_shop,
                "diff": cdiff,
            })
        colors.sort(key=lambda x: -(x["best_price"] or 0))

        items.append({
            "model": model,
            "capacity": cap,
            "list_price": list_price,
            "shops": shops,           # {"ルデヤ":x,"森森":y,"海映":z}
            "best_price": best,
            "best_shop": best_shop,
            "diff": diff,             # 買取最高値 - 定価 (マイナスなら定価割れ)
            "colors": colors,         # カラー別内訳
        })

    # モデル→容量の表示順
    model_order = {"iPhone 17 Pro Max": 0, "iPhone 17 Pro": 1, "iPhone Air": 2,
                   "iPhone 17": 3, "iPhone 17e": 4}
    cap_order = {"256GB": 0, "512GB": 1, "1TB": 2, "2TB": 3, "128GB": -1}
    items.sort(key=lambda x: (model_order.get(x["model"], 9),
                              cap_order.get(x["capacity"], 9)))
    return items


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    now = datetime.now(JST)
    ts = now.strftime("%Y-%m-%d %H:%M")
    date_key = now.strftime("%Y-%m-%d")

    print(f"=== 取得開始 {ts} ===")
    rows = []
    rows += fetch_rudeya();   print(f"ルデヤ: {len([r for r in rows if r['shop']=='ルデヤ'])}件")
    rows += fetch_morimori(); print(f"森森:   {len([r for r in rows if r['shop']=='森森'])}件")

    items = build_dataset(rows)

    # ----- 0件フェイルセーフ -----
    # CI(GitHub Actions)環境では買取サイトがdatacenter IPをブロックし全shop 0件になることがある。
    # その場合に空itemsで上書きデプロイすると表示アプリが死ぬため、既存の前回データを保持する。
    prices_path = os.path.join(DATA_DIR, "prices.json")
    stale = False
    if not items and os.path.exists(prices_path):
        try:
            with open(prices_path, encoding="utf-8") as f:
                prev = json.load(f)
            if prev.get("items"):
                items = prev["items"]
                stale = True
                print(f"⚠️ 今回0件 → 前回データ({prev.get('updated_at')}・{len(items)}機種)を保持")
        except Exception:
            pass

    dataset = {
        "updated_at": ts,
        "source": ["ルデヤ", "森森"],
        "items": items,
    }
    if stale:
        dataset["stale"] = True
        dataset["note"] = "今回の取得が0件のため前回データを表示中"
    with open(prices_path, "w", encoding="utf-8") as f:
        json.dump(dataset, f, ensure_ascii=False, indent=2)

    # ----- 履歴(推移)を追記 -----
    if stale:
        print("（stale=前回値保持のため履歴追記はスキップ）")
        print(f"=== 完了: {len(items)}機種を出力(前回値) ===")
        return
    hist_path = os.path.join(DATA_DIR, "history.json")
    if os.path.exists(hist_path):
        with open(hist_path, encoding="utf-8") as f:
            history = json.load(f)
    else:
        history = {}

    for it in items:
        key = f"{it['model']}|{it['capacity']}"
        history.setdefault(key, [])
        # 同日データは上書き(1日1レコード)
        history[key] = [h for h in history[key] if h["date"] != date_key]
        history[key].append({
            "date": date_key,
            "ルデヤ": it["shops"]["ルデヤ"],
            "森森": it["shops"]["森森"],
            "best": it["best_price"],
        })
        history[key].sort(key=lambda h: h["date"])
        # 直近180日だけ保持
        history[key] = history[key][-180:]

    with open(hist_path, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

    print(f"=== 完了: {len(items)}機種を出力 ===")
    for it in items:
        print(f"  {it['model']} {it['capacity']}: "
              f"ル={it['shops']['ルデヤ']} 森={it['shops']['森森']} "
              f"→ 最高 {it['best_price']} ({it['best_shop']})")


if __name__ == "__main__":
    main()

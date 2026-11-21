#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""开奖数据抓取脚本（快乐8 / 双色球 / 大乐透）——多源版

数据源（已逐项实测，见 README「数据源」一节）：
  1) 500 彩票网静态 XML  https://kaijiang.500.com/static/info/kaijiang/xml/{kl8|ssq|dlt}/list.xml
     —— 全彩种、全历史，开奖后约 20~30 分钟即更新，速度最快（主源）
  2) 中国福彩网官方接口  https://www.cwl.gov.cn  （快乐8 / 双色球）
  3) 中国体彩网官方接口  https://webapi.sporttery.cn （大乐透）

为什么不用浏览器直连：
  福彩官方与 500 彩票网都不返回 Access-Control-Allow-Origin，静态页面跨域拿不到；
  体彩官方返回 ACAO:*，所以页面里大乐透可以浏览器直连（见 data.js 的 LIVE 配置）。
  福彩两个彩种只能由本脚本（本地或 GitHub Actions）抓好后写进 data/*.json。

输出：data/kl8.json / data/ssq.json / data/dlt.json（同时输出 data/*.js 供 file:// 打开使用）

用法：
  python tools/fetch_data.py                # 抓取并写入 data/
  python tools/fetch_data.py --keep 200     # 最多保留 200 期
  python tools/fetch_data.py --retry 3      # 数据偏旧时自动等待重试（默认 2 次）
"""
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
CST = timezone(timedelta(hours=8))

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# 每个彩种的数据源，按优先级排列（越靠前越快）
SOURCES = {
    "kl8": ["x500", "cwl"],
    "ssq": ["x500", "cwl"],
    "dlt": ["x500", "sporttery"],
}

# 数据新鲜度容忍天数（超过则视为“本应更新但没更新”）
STALE_DAYS = {"kl8": 1, "ssq": 3, "dlt": 3}

SOURCE_LABEL = {
    "x500": "500彩票网",
    "cwl": "中国福彩网",
    "sporttery": "中国体彩网",
}


# ---------------------------------------------------------------- 基础请求

def http_get(url, referer=None, timeout=25, retries=3, nocache=True):
    """带重试 + 缓存穿透的 GET。nocache 时追加时间戳参数，避免命中 CDN 旧缓存。"""
    if nocache:
        url += ("&" if "?" in url else "?") + "_t=%d" % int(time.time() * 1000)
    headers = {
        "User-Agent": UA,
        "Accept": "application/json, text/plain, text/xml, */*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    if referer:
        headers["Referer"] = referer
    last_err = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", "replace")
        except Exception as e:  # noqa: BLE001
            last_err = e
            if i < retries - 1:
                time.sleep(1.5 * (i + 1))
    raise RuntimeError("请求失败 %s -> %s" % (url, last_err))


# ---------------------------------------------------------------- 期号归一化

def norm_period(game, period):
    """统一成能跨源比较的期号：双色球 5 位（26133）-> 7 位（2026133）。"""
    digits = re.sub(r"\D", "", str(period or ""))
    if not digits:
        return ""
    if game == "ssq" and len(digits) == 5:
        return "20" + digits
    return digits


# ---------------------------------------------------------------- 各数据源

def fetch_x500(game):
    """500 彩票网静态 XML —— 全历史一次性拿到，最新一期更新最快。"""
    url = "https://kaijiang.500.com/static/info/kaijiang/xml/%s/list.xml" % game
    text = http_get(url, referer="https://kaijiang.500.com/", timeout=25)

    rows = re.findall(
        r'<row\s+expect="([^"]+)"\s+opencode="([^"]+)"\s+opentime="([^"]*)"', text
    )
    out = []
    for expect, opencode, opentime in rows:
        period = norm_period(game, expect)
        if not period:
            continue
        date = opentime.split(" ")[0] if opentime else ""
        if game == "kl8":
            nums = [int(x) for x in opencode.split(",") if x.strip().isdigit()]
            extra = []
            if len(nums) < 15:
                continue
        else:
            front, _, back = opencode.partition("|")
            nums = [int(x) for x in front.split(",") if x.strip().isdigit()]
            extra = [int(x) for x in back.split(",") if x.strip().isdigit()]
            need = 6 if game == "ssq" else 5
            if len(nums) < need:
                continue
        out.append({
            "period": period,
            "date": date,
            "nums": sorted(nums),
            "extra": sorted(extra),
        })
    return out


def fetch_cwl(game):
    """中国福彩网官方接口：快乐8 / 双色球。"""
    name = "kl8" if game == "kl8" else "ssq"
    referer = "https://www.cwl.gov.cn/ygkj/wqkjgg/%s/" % name
    url = (
        "https://www.cwl.gov.cn/cwl_admin/front/cwlkj/search/kjxx/findDrawNotice"
        "?name=%s&issueCount=100&pageNo=1&pageSize=100&systemType=PC" % name
    )
    payload = json.loads(http_get(url, referer=referer, timeout=25))
    out = []
    for r in payload.get("result") or []:
        period = norm_period(game, r.get("code", ""))
        date = str(r.get("date", "")).split("(")[0].strip()
        reds = [int(x) for x in str(r.get("red", "")).split(",") if str(x).strip().isdigit()]
        blues = [int(x) for x in str(r.get("blue", "")).split(",") if str(x).strip().isdigit()]
        if not period:
            continue
        if game == "kl8":
            nums, extra = sorted(reds), []
            if len(nums) < 15:
                continue
        else:
            nums, extra = sorted(reds), blues[:1]
            if len(nums) < 6:
                continue
        out.append({"period": period, "date": date, "nums": nums, "extra": extra})
    return out


def fetch_sporttery(_game="dlt"):
    """中国体彩网官方接口：大乐透（gameNo=85）。"""
    url = (
        "https://webapi.sporttery.cn/gateway/lottery/getHistoryPageListV1.qry"
        "?gameNo=85&provinceId=0&pageSize=100&isVerify=1&pageNo=1"
    )
    payload = json.loads(
        http_get(url, referer="https://static.sporttery.cn/", timeout=25)
    )
    rows = (payload.get("value") or {}).get("list") or []
    out = []
    for r in rows:
        period = norm_period("dlt", r.get("lotteryDrawNum", ""))
        parts = str(r.get("lotteryDrawResult", "")).split()
        nums = sorted(int(x) for x in parts[:5] if x.isdigit())
        extra = sorted(int(x) for x in parts[5:7] if x.isdigit())
        if not period or len(nums) < 5:
            continue
        out.append({
            "period": period,
            "date": str(r.get("lotteryDrawTime", "")).strip(),
            "nums": nums,
            "extra": extra,
        })
    return out


FETCHERS = {"x500": fetch_x500, "cwl": fetch_cwl, "sporttery": fetch_sporttery}


# ---------------------------------------------------------------- 合并 / 落盘

def pkey(d):
    digits = re.sub(r"\D", "", str(d.get("period", "")))
    return (len(digits), digits)


def merge(old, new_list, keep):
    bucket = {}
    for d in old or []:
        if d.get("period"):
            bucket[re.sub(r"\D", "", str(d["period"]))] = d
    for d in new_list or []:
        if d.get("period"):
            bucket[re.sub(r"\D", "", str(d["period"]))] = d
    return sorted(bucket.values(), key=pkey, reverse=True)[:keep]


def load_old(path):
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f).get("draws") or []
    except Exception:  # noqa: BLE001
        return []


def write_game(game, draws, source, ok, note=""):
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, "%s.json" % game)
    if not draws:
        print("  %-4s -> 抓取失败，且无历史文件" % game)
        return False
    payload = {
        "game": game,
        "updated": datetime.now(CST).isoformat(timespec="seconds"),
        "latest": draws[0]["period"],
        "latestDate": draws[0].get("date", ""),
        "count": len(draws),
        "source": source,
        "ok": bool(ok),
        "draws": draws,
    }
    if note:
        payload["note"] = note
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    # JS 版本：页面用 <script> 加载，双击打开 html（file://）也能读到数据
    js_path = os.path.join(DATA_DIR, "%s.js" % game)
    with open(js_path, "w", encoding="utf-8", newline="\n") as f:
        f.write("window.__LOTTERY_DATA__ = window.__LOTTERY_DATA__ || {};\n")
        f.write("window.__LOTTERY_DATA__['%s'] = " % game)
        json.dump(payload, f, ensure_ascii=False)
        f.write(";\n")
    return True


def is_stale(game, latest_date):
    if not latest_date:
        return True
    try:
        d = datetime.strptime(latest_date[:10], "%Y-%m-%d").date()
    except ValueError:
        return True
    return d < (datetime.now(CST).date() - timedelta(days=STALE_DAYS[game]))


def fetch_one_game(game, keep):
    """依次尝试各数据源并合并；返回 (新数据行, 最新一期来源, 是否成功, 备注)"""
    merged_new = []
    newest = None
    errors = []
    for src in SOURCES[game]:
        if src == "cwl" and game not in ("kl8", "ssq"):
            continue
        if src == "sporttery" and game != "dlt":
            continue
        try:
            rows = FETCHERS[src](game)
        except Exception as e:  # noqa: BLE001
            errors.append("%s: %s" % (src, str(e)[:80]))
            print("    x %-10s %s" % (src, str(e)[:70]))
            continue
        if not rows:
            errors.append("%s: 无数据" % src)
            print("    x %-10s 无数据" % src)
            continue
        rows.sort(key=pkey, reverse=True)
        merged_new.extend(rows)
        print("    + %-10s 最新 %s（%s）共 %d 期"
              % (src, rows[0]["period"], rows[0]["date"], len(rows)))
        if newest is None or pkey(rows[0]) > newest[0]:
            newest = (pkey(rows[0]), src)

    return merged_new, (newest[1] if newest else ""), bool(merged_new), "; ".join(errors)


def main():
    keep = 200
    retry = 2
    if "--keep" in sys.argv:
        keep = int(sys.argv[sys.argv.index("--keep") + 1])
    if "--retry" in sys.argv:
        retry = int(sys.argv[sys.argv.index("--retry") + 1])

    print("开始抓取开奖数据（多源）...")
    games = ["kl8", "ssq", "dlt"]
    results = {}

    for attempt in range(retry + 1):
        todo = [g for g in games if g not in results or results[g]["stale"]]
        if not todo:
            break
        if attempt:
            print("\n第 %d 次重试（数据偏旧）：%s" % (attempt, "、".join(todo)))
            time.sleep(60)
        for game in todo:
            path = os.path.join(DATA_DIR, "%s.json" % game)
            old = load_old(path)
            print("  [%s]" % game)
            new_rows, src, ok, note = fetch_one_game(game, keep)
            if not ok:
                latest = old[0]["period"] if old else "-"
                print("  %-4s -> 全部数据源失败，保留原文件（最新 %s）" % (game, latest))
                results[game] = {"latest": latest, "stale": True, "ok": False}
                continue
            draws = merge(old, new_rows, keep)
            latest, latest_date = draws[0]["period"], draws[0].get("date", "")
            stale = is_stale(game, latest_date)
            write_game(game, draws, SOURCE_LABEL.get(src, src), True, note)
            print("  %-4s -> %s（%s）共 %d 期  %s"
                  % (game, latest, latest_date, len(draws), "偏旧" if stale else "OK"))
            results[game] = {"latest": latest, "stale": stale, "ok": True}

    print("\n汇总：")
    bad = []
    for game in games:
        r = results.get(game) or {"latest": "-", "stale": True, "ok": False}
        print("  %-4s 最新 %-9s %s" % (game, r["latest"], "可能未更新" if r["stale"] else "OK"))
        if not r["ok"] or r["stale"]:
            bad.append(game)
    return 0 if not bad else 2


if __name__ == "__main__":
    sys.exit(main())

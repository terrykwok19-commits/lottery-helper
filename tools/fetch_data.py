#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""开奖数据抓取脚本（快乐8 / 双色球 / 大乐透）

数据源（只用官方接口，避免第三方接口停更）：
  快乐8、双色球 -> 中国福彩网  https://www.cwl.gov.cn
  大乐透        -> 中国体彩网  https://webapi.sporttery.cn

输出：data/kl8.json / data/ssq.json / data/dlt.json
页面（Klb.html / Ssq.html / Dlt.html）优先读这些同源静态文件，
所以只要本脚本跑过（本地或 GitHub Actions），打开页面看到的就是最新开奖。

用法：
  python tools/fetch_data.py            # 抓取并写入 data/
  python tools/fetch_data.py --keep 200 # 最多保留 200 期
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
CST = timezone(timedelta(hours=8))

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def http_get(url, referer=None, timeout=25, retries=3):
    headers = {"User-Agent": UA, "Accept": "application/json, text/plain, */*"}
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
    raise RuntimeError(f"请求失败 {url} -> {last_err}")


def fetch_cwl(name, count, referer):
    """中国福彩网：name = kl8 / ssq"""
    url = (
        "https://www.cwl.gov.cn/cwl_admin/front/cwlkj/search/kjxx/findDrawNotice"
        f"?name={name}&issueCount={count}&pageNo=1&pageSize={count}&systemType=PC"
    )
    payload = json.loads(http_get(url, referer=referer))
    rows = payload.get("result") or []
    out = []
    for r in rows:
        period = str(r.get("code", "")).strip()
        date = str(r.get("date", "")).split("(")[0].strip()
        reds = [int(x) for x in str(r.get("red", "")).split(",") if str(x).strip().isdigit()]
        blues = [int(x) for x in str(r.get("blue", "")).split(",") if str(x).strip().isdigit()]
        if not period or len(reds) < 5:
            continue
        if name == "kl8":
            nums, extra = sorted(reds), []
        else:
            nums, extra = sorted(reds), blues[:1]
        out.append({"period": period, "date": date, "nums": nums, "extra": extra})
    return out


def fetch_dlt(count):
    """中国体彩网 大乐透，gameNo=85"""
    url = (
        "https://webapi.sporttery.cn/gateway/lottery/getHistoryPageListV1.qry"
        f"?gameNo=85&provinceId=0&pageSize={count}&isVerify=1&pageNo=1"
    )
    payload = json.loads(http_get(url, referer="https://static.sporttery.cn/"))
    rows = (payload.get("value") or {}).get("list") or []
    out = []
    for r in rows:
        period = str(r.get("lotteryDrawNum", "")).strip()
        date = str(r.get("lotteryDrawTime", "")).strip()
        parts = str(r.get("lotteryDrawResult", "")).split()
        nums = sorted(int(x) for x in parts[:5] if x.isdigit())
        extra = sorted(int(x) for x in parts[5:7] if x.isdigit())
        if not period or len(nums) < 5:
            continue
        out.append({"period": period, "date": date, "nums": nums, "extra": extra})
    return out


def merge(old, new, keep):
    """按期号合并，新数据覆盖同期的旧数据，按最新在前排序"""
    bucket = {}
    for d in (old or []):
        bucket[str(d["period"])] = d
    for d in (new or []):
        bucket[str(d["period"])] = d

    def key(d):
        digits = "".join(ch for ch in str(d["period"]) if ch.isdigit())
        return (len(digits), digits)

    draws = sorted(bucket.values(), key=key, reverse=True)
    return draws[:keep]


def load_old(path):
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f).get("draws") or []
    except Exception:  # noqa: BLE001
        return []


def write_game(game, draws, source):
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, f"{game}.json")
    if draws:
        payload = {
            "game": game,
            "updated": datetime.now(CST).isoformat(timespec="seconds"),
            "latest": draws[0]["period"],
            "latestDate": draws[0].get("date", ""),
            "count": len(draws),
            "source": source,
            "draws": draws,
        }
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)
        # 同时输出一份 JS 版本：页面用 <script> 加载，直接双击打开 html（file://）
        # 也能读到数据，不受 fetch 的同源策略限制
        js_path = os.path.join(DATA_DIR, f"{game}.js")
        with open(js_path, "w", encoding="utf-8", newline="\n") as f:
            f.write("window.__LOTTERY_DATA__ = window.__LOTTERY_DATA__ || {};\n")
            f.write(f"window.__LOTTERY_DATA__['{game}'] = ")
            json.dump(payload, f, ensure_ascii=False)
            f.write(";\n")
        print(f"  {game:4s} -> {payload['latest']} ({payload['latestDate']}) 共 {len(draws)} 期")
        return True
    # 抓取失败时不动原文件，避免把页面数据清空
    if os.path.exists(path):
        print(f"  {game:4s} -> 抓取失败，保留原有文件")
    else:
        print(f"  {game:4s} -> 抓取失败，且无历史文件")
    return False


def main():
    keep = 200
    if "--keep" in sys.argv:
        keep = int(sys.argv[sys.argv.index("--keep") + 1])

    print("开始抓取开奖数据 ...")
    jobs = [
        ("kl8", lambda: fetch_cwl("kl8", 100, "https://www.cwl.gov.cn/ygkj/wqkjgg/kl8/"),
         "中国福彩网 cwl.gov.cn"),
        ("ssq", lambda: fetch_cwl("ssq", 100, "https://www.cwl.gov.cn/ygkj/wqkjgg/ssq/"),
         "中国福彩网 cwl.gov.cn"),
        ("dlt", lambda: fetch_dlt(100), "中国体彩网 sporttery.cn"),
    ]

    ok = 0
    for game, fn, source in jobs:
        path = os.path.join(DATA_DIR, f"{game}.json")
        old = load_old(path)
        try:
            new = fn()
        except Exception as e:  # noqa: BLE001
            print(f"  {game:4s} -> 抓取异常: {e}")
            new = []
        if write_game(game, merge(old, new, keep), source):
            ok += 1
            if old and new:
                old_latest = old[0]["period"] if old else "-"
                if str(new[0]["period"]) > str(old_latest):
                    print(f"       新增期号: {new[0]['period']}")

    print(f"完成：{ok}/{len(jobs)} 个彩种已更新")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""FEATURE_MAP.md ←→ 程式碼 雙向對帳。

為什麼存在(2026-09-16)：我們的檢查一直是「掃描器說綠」，掃描器看不見的東西
(功能被改名、選取器被換掉、新功能沒人登記) 可以在線上活很久。這支把
FEATURE_MAP.md 當成**獨立宣告的契約**，逐項回到 docs/ 的原始碼驗證。

刻意的設計:地圖是手寫的、判準讀的是程式碼 ⇒ 兩者不同源，才可能紅。
(歷史坑 `宣稱與判準同源永不紅`)

方向一(地圖→程式碼)：地圖寫的選取器/函式/端點/狀態，程式碼裡必須真的有。
方向二(程式碼→地圖)：docs/js/ 下每個 .js 至少要被一個 F-區塊認領，否則新功能
                      可以整檔上線而沒有任何人知道要怎麼驗它。
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAP = ROOT / "FEATURE_MAP.md"
FIELDS = ["入口", "路徑", "檔案", "選取器", "函式", "端點", "狀態", "驗收"]
EMPTY = {"(無)", "（無）", "-", ""}

fails, warns = [], []


def fail(fid, msg):
    fails.append(f"{fid}: {msg}")


def parse():
    """把 FEATURE_MAP.md 切成 [(fid, title, {field: raw})]。"""
    blocks, cur = [], None
    for line in MAP.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^###\s+(F-\d+)\s+(.*)$", line.strip())
        if m:
            cur = (m.group(1), m.group(2).strip(), {})
            blocks.append(cur)
            continue
        if cur is None:
            continue
        m = re.match(r"^-\s*([一-鿿]{2,3}):\s*(.*)$", line.strip())
        if m and m.group(1) in FIELDS:
            cur[2][m.group(1)] = m.group(2).strip()
        elif cur[2] and line.strip().startswith(" ") is False and line.strip() and not line.startswith("-"):
            pass
    return blocks


def toks(raw):
    if raw is None or raw.strip() in EMPTY:
        return []
    return [t for t in raw.split() if t.strip() not in EMPTY]


def load(paths, fid):
    """讀出這個 feature 宣告的檔案內容;檔案不存在就是硬錯。"""
    blob, ok = "", []
    for p in paths:
        f = ROOT / p
        if not f.exists():
            fail(fid, f"宣告的檔案不存在: {p}")
            continue
        blob += f.read_text(encoding="utf-8", errors="ignore") + "\n"
        ok.append(p)
    return blob, ok


def has_id(blob, i):
    return any(re.search(p, blob) for p in (
        rf'\sid="{re.escape(i)}"', rf"\sid='{re.escape(i)}'",
        rf'getElementById\(\s*["\']{re.escape(i)}["\']',
        rf'querySelector(?:All)?\(\s*["\']#{re.escape(i)}\b',
        rf'\$\(\s*["\']#{re.escape(i)}["\']',
    ))


def has_fn(blob, n):
    return any(re.search(p, blob) for p in (
        rf"function\s+{re.escape(n)}\s*\(",
        rf"\b{re.escape(n)}\s*[=:]\s*(?:async\s*)?function\b",
        rf"\b(?:const|let|var)\s+{re.escape(n)}\s*=\s*(?:async\s*)?\(",
        rf"\b{re.escape(n)}\s*=\s*(?:async\s*)?\([^)]*\)\s*=>",
    ))


def main():
    if not MAP.exists():
        print("FEATURE_MAP.md 不存在"); return 2
    blocks = parse()
    if not blocks:
        print("FEATURE_MAP.md 解析不到任何 F- 區塊 —— 格式壞了"); return 2

    claimed_files = set()
    for fid, title, f in blocks:
        for need in ("檔案", "選取器", "函式", "端點", "狀態", "驗收"):
            if need not in f:
                fail(fid, f"缺欄位「{need}」")
        if f.get("驗收", "").strip() in EMPTY:
            fail(fid, "「驗收」不得為空 —— 沒寫怎麼驗，等於沒有這條")

        paths = [p.rstrip(",") for p in toks(f.get("檔案"))]
        blob, okpaths = load(paths, fid)
        claimed_files.update(okpaths)
        if not blob:
            continue

        for sel in toks(f.get("選取器")):
            if not sel.startswith("#"):
                fail(fid, f"選取器只接受 #id 形式: {sel}"); continue
            if not has_id(blob, sel[1:]):
                fail(fid, f"選取器 {sel} 在 {okpaths} 都找不到 —— 被改名或被刪了")

        for fn in toks(f.get("函式")):
            if not has_fn(blob, fn):
                fail(fid, f"函式 {fn}() 在 {okpaths} 找不到定義")

        for ep in toks(f.get("端點")):
            if ep not in blob:
                fail(fid, f"端點 {ep} 在 {okpaths} 找不到")

        for key in toks(f.get("狀態")):
            if key not in blob:
                fail(fid, f"localStorage key {key} 在 {okpaths} 找不到")

    # 方向二：docs/js/ 下每支 .js 都要有人認領
    for js in sorted((ROOT / "docs" / "js").glob("*.js")):
        rel = str(js.relative_to(ROOT))
        if rel not in claimed_files:
            fails.append(f"COVERAGE: {rel} 沒有任何 F- 區塊認領 —— "
                         f"新功能上線必須在 FEATURE_MAP.md 加一條")

    # 參考資訊:地圖沒收錄的頂層函式(只提醒，不擋)
    for js in sorted((ROOT / "docs" / "js").glob("*.js")):
        src = js.read_text(encoding="utf-8", errors="ignore")
        defined = {m for m in re.findall(r"(?:^|\n)\s*(?:async\s+)?function\s+([A-Za-z0-9_]+)", src)
                   if not m.startswith("_")}
        mapped = set()
        for _, _, f in blocks:
            mapped.update(toks(f.get("函式")))
        miss = sorted(defined - mapped)
        if miss:
            warns.append(f"{js.name}: 地圖未收錄 {len(miss)} 個函式 — {', '.join(miss[:8])}"
                         + ("…" if len(miss) > 8 else ""))

    print(f"FEATURE_MAP lint — {len(blocks)} 個功能區塊, "
          f"{len(claimed_files)} 個檔案被認領")
    for w in warns:
        print(f"  · {w}")
    if fails:
        print(f"\n❌ {len(fails)} 項不符:")
        for x in fails:
            print(f"  - {x}")
        return 1
    print("\n✅ 地圖與程式碼一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())

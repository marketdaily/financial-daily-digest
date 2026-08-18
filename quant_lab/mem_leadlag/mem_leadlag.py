#!/usr/bin/env python3
"""美股記憶體族群 -> 台股記憶體族群 lead-lag(v0:方法論驗證版,只跑三組配對)。

老闆 2026-08-18 交辦:「美股對記憶體關聯廠商的評價方式是否能連動台股的記憶體關聯廠商,
它們之間的相關或有時間序列的落後」。

本檔回答的是【價格傳導】那一半(估值倍數傳導見 pe_probe.py 的資料可行性勘查)。

要誠實回答,必須同時擋掉四個坑:
  1. 時區對齊:美股 D 日收盤 ~04:00 TW(D+1),在台股 E 日 09:00 開盤前才算「知道」。
     只配「嚴格早於 E 的最新美股日 D」→ 無看未來。用 leadlag.align_by_prior(唯一正確版)。
  2. 除權息:台股配息大,裸 close-to-close 會出現假跳空。用 adjclose 還原(含 open)。
  3. 開盤跳空:就算真有領先,資訊多半在【開盤跳空】就反映完了。必須把
     gap(前收→開盤)與 open->close(開盤後)拆開 —— 只有後者是「知道之後還吃得到」的。
  4. ★族群共同因子:美股記憶體股與台股記憶體股同時被整個半導體循環推動。
     不控制它,量到的「傳導」大半是 SOX 對兩邊的共同驅動。
     → 把 leadlag 的 contemp 槽當【共同因子控制】用,餵同一 D 日的 ^SOX 隔夜。
     ⚠ 因此本研究的 verdict 要這樣讀:
         real_lead                → 個股帶有【超出族群】的領先資訊
         no_lead_contemporaneous  → 領先是族群因子造成的假象(非時段重疊)
     輸出層已改標籤,避免沿用 leadlag 原本的重疊語意。

不下單、不寄信。純量測。
"""
import os
import sys
import json
import datetime as dt

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache")
# insert(1) 而非 0:避免遮蔽 stdlib/測試用 path(lesson lib_path_shadow)
sys.path.insert(1, os.path.join(HERE, "..", "market_forecast"))
sys.path.insert(1, os.path.expanduser("~/autonomous/capabilities/lead_lag"))

from adr_lead_lag import fetch, build, ols          # noqa: E402  單一真源,不手刻第二份
from leadlag import align_by_prior, estimate_lead_lag  # noqa: E402

SECTOR = ("^SOX", "sox", 1000)        # 族群共同因子

# (美股 driver, 台股 target, 說明) —— v0 只驗三條產業線各一組
# ⚠ Yahoo 後綴坑:上市(TWSE)= .TW,上櫃(TPEx)= .TWO。群聯 8299 與旺矽 6223 都是上櫃,
#   用 .TW 會拿到 HTTP 404(不是空資料,是直接 404)。鋪滿全族群時每檔都要先驗後綴。
PAIRS = [
    ("SNDK", "sndk", 250,  "8299.TWO", "tw8299", 1000, "NAND/控制器", "SanDisk → 群聯"),
    ("MU",   "mu",   1000, "2408.TW",  "tw2408", 1000, "DRAM/HBM",    "Micron → 南亞科"),
    ("FORM", "form", 1000, "6223.TWO", "tw6223", 1000, "測試/探針卡",  "FormFactor → 旺矽"),
]

# 本研究的 verdict 標籤(contemp 槽在此是族群因子,非時段重疊)
VERDICT_ZH = {
    "real_lead": "真領先(超出族群因子)",
    "weak": "弱(僅單邊閘通過)",
    "no_lead": "無領先",
    "no_lead_contemporaneous": "無領先——是族群因子造成的假象",
    "confounded_inconclusive": "與族群高度共線,無法分離(不下結論)",
    "insufficient_n": "樣本不足",
}


def overnight(dates, px):
    """美股 D 日隔夜報酬 % = adjclose_D / adjclose_{前一美股日} - 1。"""
    out = {}
    for i in range(1, len(dates)):
        d, p = dates[i], dates[i - 1]
        out[d] = (px[d][1] / px[p][1] - 1) * 100
    return out


def tw_pieces(dates, px):
    """台股 E 日三段報酬 %:gap(前收→開)、oc(開→收)、cc(前收→收)。"""
    gap, oc, cc = {}, {}, {}
    for i in range(1, len(dates)):
        E, P = dates[i], dates[i - 1]
        o_e, c_e = px[E]
        c_p = px[P][1]
        gap[E] = (o_e / c_p - 1) * 100
        oc[E] = (c_e / o_e - 1) * 100
        cc[E] = (c_e / c_p - 1) * 100
    return gap, oc, cc


def load(sym, cache, min_rows, force):
    arr = fetch(sym, cache, force, min_rows=min_rows, out_dir=CACHE)
    return build(arr)


def run_pair(us_sym, us_cache, us_min, tw_sym, tw_cache, tw_min,
             line, label, sox_on, force):
    us_dates, us_px = load(us_sym, us_cache, us_min, force)
    tw_dates, tw_px = load(tw_sym, tw_cache, tw_min, force)

    us_on = overnight(us_dates, us_px)
    gap, oc, cc = tw_pieces(tw_dates, tw_px)

    # 只留兩邊都算得出報酬、且族群因子當天也有值的日期
    us_ok = sorted(d for d in us_dates if d in us_on and d in sox_on)
    tw_ok = sorted(d for d in tw_dates if d in gap)

    idx = align_by_prior(us_ok, tw_ok)   # [(target_idx, driver_idx)] 嚴格 D < E
    if not idx:
        return None

    Es = [tw_ok[t] for t, _ in idx]
    Ds = [us_ok[d] for _, d in idx]
    x = np.array([us_on[d] for d in Ds])        # driver:美股隔夜
    s_ = np.array([sox_on[d] for d in Ds])       # 共同因子:同一 D 日 SOX 隔夜
    g = np.array([gap[E] for E in Es])
    i_c = np.array([oc[E] for E in Es])
    c_c = np.array([cc[E] for E in Es])
    n = len(idx)
    years = (Es[-1] - Es[0]).days / 365.25

    # ---- 自測①:無看未來硬斷言。driver 日必須嚴格早於 target 日,一筆都不准違反。 ----
    bad = [(D, E) for D, E in zip(Ds, Es) if not (D < E)]
    if bad:
        sys.exit(f"FATAL 看未來: {len(bad)} 筆 driver 日未嚴格早於 target 日,例 {bad[:3]}")
    # 最大間隔守衛:配到太久以前的 driver(長假)會稀釋訊號,列出來讓人看見而非默默吃掉
    gaps = [(E - D).days for D, E in zip(Ds, Es)]
    res_align = {"max_gap_days": int(max(gaps)), "mean_gap_days": round(float(np.mean(gaps)), 2)}

    res = {
        "align": res_align,
        "pair": label, "line": line, "us": us_sym, "tw": tw_sym,
        "n": n, "start": Es[0].isoformat(), "end": Es[-1].isoformat(),
        "years": round(years, 2),
        "us_rows": len(us_dates), "tw_rows": len(tw_dates),
    }

    # --- 裸相關(這就是「看起來很像有連動」的那個數字,故意先報出來當對照) ---
    res["naive_corr_gap"] = round(float(np.corrcoef(x, g)[0, 1]), 3)
    res["naive_corr_oc"] = round(float(np.corrcoef(x, i_c)[0, 1]), 3)
    res["corr_driver_sector"] = round(float(np.corrcoef(x, s_)[0, 1]), 3)

    # --- gap 拆解:傳導有幾成是在開盤那一瞬間就吃掉的 ---
    rg, ri, rc = ols(x, g), ols(x, i_c), ols(x, c_c)
    res["beta_gap"], res["r2_gap"] = round(rg["b"], 3), round(rg["r2"], 4)
    res["beta_oc"], res["r2_oc"] = round(ri["b"], 3), round(ri["r2"], 4)
    res["beta_cc"] = round(rc["b"], 3)
    res["gap_capture_pct"] = round(rg["b"] / rc["b"] * 100, 1) if rc["b"] else None

    # --- 誠實 lead-lag:控制族群因子後,個股還剩多少 ---
    res["gap_raw"] = estimate_lead_lag(x, g)
    res["gap_ctrl"] = estimate_lead_lag(x, g, contemp=s_)
    res["oc_raw"] = estimate_lead_lag(x, i_c)
    res["oc_ctrl"] = estimate_lead_lag(x, i_c, contemp=s_)   # ← 可交易性的那一個

    # ---- 自測②:洗牌虛無對照(打亂 driver 時序,target 與共同因子不動)。 ----
    # 在【這份真實資料】上量偽陽率,而不是靠合成資料的理論值。
    rng = np.random.default_rng(20260818)
    fp = {"real_lead": 0, "stat_sig": 0, "trials": 300}
    for _ in range(fp["trials"]):
        xs = rng.permutation(x)
        rr = estimate_lead_lag(xs, g, contemp=s_)
        if rr["verdict"] == "real_lead":
            fp["real_lead"] += 1
        if rr["stat_sig"]:
            fp["stat_sig"] += 1
    fp["real_lead_pct"] = round(fp["real_lead"] / fp["trials"] * 100, 1)
    fp["stat_sig_pct"] = round(fp["stat_sig"] / fp["trials"] * 100, 1)
    res["shuffle_null"] = fp

    # --- 分期穩定度 ---
    eras = [(2000, 2007), (2008, 2014), (2015, 2019), (2020, 2022), (2023, 2024), (2025, 2026)]
    res["eras"] = []
    for lo, hi in eras:
        m = np.array([lo <= E.year <= hi for E in Es])
        k = int(m.sum())
        if k < 60:
            res["eras"].append({"era": f"{lo}-{hi}", "n": k, "skip": True})
            continue
        eg, eo = ols(x[m], g[m]), ols(x[m], i_c[m])
        res["eras"].append({
            "era": f"{lo}-{hi}", "n": k, "skip": False,
            "beta_gap": round(eg["b"], 3), "r2_gap": round(eg["r2"], 4),
            "beta_oc": round(eo["b"], 3), "r2_oc": round(eo["r2"], 4),
            "oc_mean": round(float(i_c[m].mean()), 4),
        })
    return res


def fmt(r):
    L = []
    A = L.append
    A("=" * 92)
    A(f"{r['pair']}   [{r['line']}]   {r['us']} -> {r['tw']}")
    A("=" * 92)
    A(f"對齊筆數 N={r['n']}   期間 {r['start']} ~ {r['end']}  ({r['years']} 年)"
      f"   原始列數 US={r['us_rows']} TW={r['tw_rows']}")
    A("")
    A("--- (0) 裸相關:先看「看起來有多連動」 ---")
    A(f"  corr(美股隔夜, 台股開盤跳空) = {r['naive_corr_gap']:+.3f}")
    A(f"  corr(美股隔夜, 台股開盤後)   = {r['naive_corr_oc']:+.3f}")
    A(f"  corr(美股個股, ^SOX)         = {r['corr_driver_sector']:+.3f}   ← 共同因子有多強")
    A("")
    A("--- (1) 傳導拆解:有幾成在開盤那一瞬間就吃掉了 ---")
    A(f"  beta 開盤跳空 = {r['beta_gap']:+.3f}  (R2={r['r2_gap']:.4f})")
    A(f"  beta 開盤後   = {r['beta_oc']:+.3f}  (R2={r['r2_oc']:.4f})")
    gc = r["gap_capture_pct"]
    if gc is not None:
        A(f"  ★ 跳空吃掉 {gc:.0f}% 的總傳導,開盤後只剩 {100 - gc:.0f}%")
    A("")
    A("--- (2) 誠實判決:控制族群因子(^SOX)前後 ---")
    for tag, raw, ctrl in [("開盤跳空", r["gap_raw"], r["gap_ctrl"]),
                           ("開盤後(可交易)", r["oc_raw"], r["oc_ctrl"])]:
        A(f"  [{tag}]")
        A(f"    未控制 : beta={raw['beta']:+.4f} t={raw['tstat']:+.2f} "
          f"方向命中={raw['sign_hit'] * 100:.1f}% "
          f"[{raw['sign_lo'] * 100:.1f},{raw['sign_hi'] * 100:.1f}] "
          f"→ {VERDICT_ZH.get(raw['verdict'], raw['verdict'])}")
        A(f"    控制後 : beta={ctrl['beta']:+.4f} t={ctrl['tstat']:+.2f} "
          f"rho(個股,SOX)={ctrl.get('rho_driver_contemp', float('nan')):+.2f} "
          f"→ ★ {VERDICT_ZH.get(ctrl['verdict'], ctrl['verdict'])}")
        if ctrl.get("small_sample"):
            A(f"      ⚠ n={ctrl['n']}<150:stat_sig/weak 的偽陽偏高,只有 real_lead 可單獨採信")
        for note in ctrl.get("notes", []):
            A(f"      · {note}")
    A("")
    a = r["align"]; f = r["shuffle_null"]
    A("--- (2.5) 自測:這些數字可不可信 ---")
    A(f"  無看未來斷言:全部 {r['n']} 筆 driver 日均嚴格早於 target 日 ✓"
      f"(平均間隔 {a['mean_gap_days']} 天,最長 {a['max_gap_days']} 天)")
    A(f"  洗牌虛無對照({f['trials']} 次打亂 driver 時序):"
      f"判 real_lead {f['real_lead_pct']}% / 判 stat_sig {f['stat_sig_pct']}%")
    A(f"    → real_lead 閘在這份資料上的偽陽率 {f['real_lead_pct']}%"
      f"{'(符合設計,可採信)' if f['real_lead_pct'] <= 5 else '(偏高,結論要打折)'}")
    A("")
    A("--- (3) 分期穩定度 ---")
    A(f"  {'期間':<12}{'n':>6}{'beta_gap':>11}{'R2_gap':>9}{'beta_oc':>10}{'R2_oc':>9}{'oc均值':>10}")
    for e in r["eras"]:
        if e["skip"]:
            A(f"  {e['era']:<12}{e['n']:>6}   (樣本不足,略)")
        else:
            A(f"  {e['era']:<12}{e['n']:>6}{e['beta_gap']:>11.3f}{e['r2_gap']:>9.4f}"
              f"{e['beta_oc']:>10.3f}{e['r2_oc']:>9.4f}{e['oc_mean']:>9.3f}%")
    A("")
    return "\n".join(L)


def main():
    force = "--refetch" in sys.argv
    print("抓取中(Yahoo v8 日線,已還原除權息)...", flush=True)
    sox_dates, sox_px = load(SECTOR[0], SECTOR[1], SECTOR[2], force)
    sox_on = overnight(sox_dates, sox_px)
    print(f"  族群因子 ^SOX: {len(sox_dates)} 列\n", flush=True)

    results = []
    for (us, uc, um, tw, tc, tm, line, label) in PAIRS:
        r = run_pair(us, uc, um, tw, tc, tm, line, label, sox_on, force)
        if r:
            results.append(r)
            print(fmt(r), flush=True)

    n_tests = len(results) * 2
    print("=" * 92)
    print("多重檢定誠實聲明")
    print("=" * 92)
    print(f"  本次共跑 {n_tests} 個獨立檢定({len(results)} 組配對 × 開盤跳空/開盤後 2 個標的)。")
    print(f"  在 95% 門檻下,即使全部都沒有真實 edge,期望仍會出現 {0.05 * n_tests:.1f} 個「顯著」。")
    print("  → 單一個顯著結果不構成證據;要看的是 real_lead 是否集中在同一條產業線且分期穩定。")
    print("  → 鋪滿全族群(約 20 組)前,這個數字會變成 40,屆時必須改用 surrogate null 校正,")
    print("     而不是靠 Bonferroni(lesson:多重檢定校正救不了有偏的估計量)。")
    print("=" * 92)

    out = os.path.join(HERE, "results_v0.json")
    with open(out, "w") as f:
        json.dump({"generated": dt.datetime.now().isoformat(timespec="seconds"),
                   "sector_factor": SECTOR[0], "n_tests": n_tests,
                   "results": results}, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nJSON 已寫入 {out}")


if __name__ == "__main__":
    main()

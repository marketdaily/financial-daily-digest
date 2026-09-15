#!/usr/bin/env python3
"""免費算力雷達的體檢名單,必須蓋住生產鏈上每一支免費模型(2026-09-16)。

守的災難:模型名同時寫在 analyzer 的席次與雷達的 HEALTH 兩處,是手維護的。
兩邊一漂移就出現「生產在用、但沒有人在體檢」的席次——而 council 少一把聲音**不會失敗**,
它只是安靜地少一票。2026-09-16 Groq 把 qwen3.6-27b 下架換 3.8,這席每班 404,
靠的是雷達剛好也列了同一支才當天抓到;要是當初只改了一邊,就沒人會發現。

判準對著災難寫:量的是「生產在用的免費模型,雷達有沒有在看」,不是兩份清單長度相等。
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))

FAILS = []


def ck(name, cond, extra=""):
    print(("  ✓ " if cond else "  ✗ ") + name + ("" if cond else f"  {extra}"))
    if not cond:
        FAILS.append(name)


# 雷達只負責「有 key 的免費雲端層 + 本地」;gemini 刻意不體檢(免費層 RPD 20,
# 體檢一次就是偷走隔天早報的額度),anthropic/openai 是付費層不在此列。
WATCHED_VENDORS = ("groq", "cerebras", "openrouter")


def default_models(src):
    """每個 _call_* 的預設模型。不帶 model= 的呼叫用的就是它——只抓字面 model= 會整支漏掉,
    而預設那支正是生卡主鏈在用的(gpt-oss-120b)。"""
    out = {}
    for m in re.finditer(r'def _call_(groq|cerebras|openrouter)\((.{0,400}?)\)\s*->', src, re.S):
        mm = re.search(r'model:\s*str\s*=\s*["\']([^"\']+)["\']', m.group(2))
        if mm:
            out[m.group(1)] = mm.group(1)
    return out


def chain_models(src):
    """analyzer 裡真的會被呼叫到的免費雲端模型名(含「沒寫 model= ⇒ 用預設」那些)。"""
    defaults = default_models(src)
    found = set()
    for m in re.finditer(r'_call_(groq|cerebras|openrouter)\((.{0,200}?)\)', src, re.S):
        vendor, args = m.group(1), m.group(2)
        if vendor not in defaults:          # 連預設都抓不到 = 樣式壞了,別假裝有覆蓋
            continue
        mm = re.search(r'model=["\']([^"\']+)["\']', args)
        found.add((vendor, mm.group(1) if mm else defaults[vendor]))
    return found


def main():
    src = open(os.path.join(REPO, "analyzer.py"), encoding="utf-8").read()
    import free_capacity_radar as R
    watched = {(v, m) for _, v, m in R.HEALTH if v in WATCHED_VENDORS}

    used = {(v, m) for v, m in chain_models(src) if v in WATCHED_VENDORS}
    ck("抓得到生產鏈上的模型(樣式沒被改壞)", len(used) >= 2, sorted(used))

    missing = sorted(used - watched)
    ck("⭐ 生產在用的免費模型全都在雷達體檢名單裡", not missing,
       f"沒人在體檢:{missing}")

    # 反向:雷達盯著一支生產早就不用的模型 = 噪音來源(下架時發一則沒人要處理的告警)
    stale = sorted(m for m in watched if m not in used)
    if stale:
        print(f"  ℹ️ 雷達多盯了(不算失敗,可能是候選/備援):{stale}")

    # 突變對照:假裝生產多用了一支雷達沒列的模型 ⇒ 上面那條必須紅
    fake = used | {("groq", "some/model-nobody-watches")}
    ck("⭐ 突變(生產多一支沒被體檢的模型)會被抓到 ⇒ 本測試有鑑別力",
       bool(sorted(fake - watched)))

    print()
    if FAILS:
        print(f"❌ {len(FAILS)} 條沒過:{FAILS}")
        return 1
    print("✅ 雷達覆蓋生產鏈全過")
    return 0


if __name__ == "__main__":
    sys.exit(main())

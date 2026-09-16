#!/usr/bin/env python3
"""skill 三處登記對帳(R-22 硬化,2026-09-16)。

老闆 2026-08-23 親令:「你自己要知道什麼時候要用」——新能力落地必須同步改路由層,
`description / CATALOG / GOVERNANCE / 強制路徑` 四處沒改 = 那個能力對那類任務等於不存在。
這條一直只是散文(L5),所以一直在漏。這支把它變成可執行的檢查(L2)。

四項檢查:
  A. 每個 skill 目錄都要出現在 CATALOG.md
  B. 每個 skill 目錄都要出現在 GOVERNANCE.md
  C. CATALOG/GOVERNANCE 提到但目錄不存在的 = 幽靈條目(改名或刪檔沒同步)
  D. 每個 SKILL.md 都要有非空的 frontmatter description(那是自動觸發用的路由器)

退役的 skill 不刪檔,description 標 [DEPRECATED],仍需登記 ⇒ 不豁免 A/B。

用法: python3 scripts/skill_registry_lint.py [--strict]
  預設只對「A/B 缺登記」與「D 缺 description」判 fail;
  --strict 連幽靈條目也判 fail。
"""
import argparse
import json
import re
import sys
from pathlib import Path

SKILLS = (Path.home() / ".claude/plugins/marketplaces/delvin-custom"
          / "plugins/delvin-tools/skills")


def _frontmatter(path):
    """讀 SKILL.md 的 YAML frontmatter。

    ⚠️ 2026-09-16:第一版只用 `^description:\\s*(.+)$` 讀同一行,於是把 5 支用 YAML
    區塊語法(`description: >` / `description: |`,內容在下面幾行)的 skill 誤判成
    「缺 description」,並據此對老闆宣稱「這 5 支永遠不會被自動觸發」——完全是假的。
    掃描器把「我讀不到」寫成「它不存在」,是我們反覆踩的同一款坑。
    """
    txt = path.read_text(encoding="utf-8", errors="ignore")
    if not txt.startswith("---"):
        return {}
    end = txt.find("\n---", 3)
    block = txt[3:end if end > 0 else 4000]
    out, key, buf = {}, None, []
    for line in block.splitlines():
        m = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if m and not line.startswith((" ", "\t")):
            if key:
                out[key] = " ".join(buf).strip()
            key, val = m.group(1), m.group(2).strip()
            buf = [] if val in (">", "|", ">-", "|-", "") else [val.strip('"\'')]
        elif key and line.startswith((" ", "\t")):
            buf.append(line.strip())
    if key:
        out[key] = " ".join(buf).strip()
    return out

def named(text):
    """抓出文件裡以 `backtick` 或裸字提及的 skill 名。"""
    return set(re.findall(r"`([a-z0-9][a-z0-9\-]{2,})`", text))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--write-baseline", action="store_true",
                    help="把當下的未登記清單寫成基線,之後只擋新增的違規")
    a = ap.parse_args()
    base_f = Path(__file__).resolve().parent.parent / "state" / "skill_registry_baseline.json"

    if not SKILLS.exists():
        print(f"skills 目錄不存在: {SKILLS}"); return 2
    cat_f, gov_f = SKILLS / "CATALOG.md", SKILLS / "GOVERNANCE.md"
    for f in (cat_f, gov_f):
        if not f.exists():
            print(f"缺少 {f.name}"); return 2

    cat_raw = cat_f.read_text(encoding="utf-8", errors="ignore")
    gov_raw = gov_f.read_text(encoding="utf-8", errors="ignore")
    cat, gov = named(cat_raw), named(gov_raw)

    dirs = sorted(d.name for d in SKILLS.iterdir()
                  if d.is_dir() and (d / "SKILL.md").exists())

    miss_cat = [s for s in dirs if s not in cat and s not in cat_raw]
    miss_gov = [s for s in dirs if s not in gov and s not in gov_raw]
    have = set(dirs)
    ghosts = sorted((cat | gov) - have - {"skills", "delvin-tools"})
    ghosts = [g for g in ghosts if (SKILLS / g).exists() is False and "-" in g]

    no_desc, name_mismatch = [], []
    for s in dirs:
        fm = _frontmatter(SKILLS / s / "SKILL.md")
        if len(fm.get("description", "")) < 20:
            no_desc.append(s)
        nm = fm.get("name", "")
        if nm and nm != s:
            name_mismatch.append((s, nm))

    print(f"skill 登記對帳 — {len(dirs)} 個 skill 目錄")
    print(f"  CATALOG 已登記 {len(dirs)-len(miss_cat)}/{len(dirs)}"
          f" · GOVERNANCE 已登記 {len(dirs)-len(miss_gov)}/{len(dirs)}"
          f" · 有 description {len(dirs)-len(no_desc)}/{len(dirs)}")

    # 棘輪:既有欠債記進基線,只擋「新增」的違規。
    # 直接掛硬閘會是一盞永遠紅的燈,而紅久了人就學會消音(歷史坑:守衛誤告會教人用樣板消音)。
    if a.write_baseline:
        base_f.parent.mkdir(parents=True, exist_ok=True)
        base_f.write_text(json.dumps(
            {"miss_gov": sorted(miss_gov), "miss_cat": sorted(miss_cat),
             "no_desc": sorted(no_desc)}, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n📌 基線已寫入 {base_f.relative_to(base_f.parent.parent)} "
              f"(gov {len(miss_gov)} / cat {len(miss_cat)} / desc {len(no_desc)})")
        print("   基線內的欠債仍要還,但不再擋 CI;新增的違規會紅。")
        return 0
    base = {"miss_gov": [], "miss_cat": [], "no_desc": []}
    if base_f.exists():
        base = json.loads(base_f.read_text(encoding="utf-8"))
        n_old = len(miss_gov) + len(miss_cat) + len(no_desc)
        miss_gov = [s for s in miss_gov if s not in base.get("miss_gov", [])]
        miss_cat = [s for s in miss_cat if s not in base.get("miss_cat", [])]
        no_desc = [s for s in no_desc if s not in base.get("no_desc", [])]
        debt = n_old - (len(miss_gov) + len(miss_cat) + len(no_desc))
        if debt:
            print(f"  （基線內既有欠債 {debt} 筆，不擋 CI，見 state/skill_registry_baseline.json）")

    bad = False
    if miss_cat:
        bad = True
        print(f"\n❌ CATALOG.md 沒登記（{len(miss_cat)}）:")
        for s in miss_cat: print(f"  - {s}")
    if miss_gov:
        bad = True
        print(f"\n❌ GOVERNANCE.md 沒歸群（{len(miss_gov)}）:")
        for s in miss_gov: print(f"  - {s}")
    if no_desc:
        bad = True
        print(f"\n❌ SKILL.md 缺 description 或過短（{len(no_desc)}）"
              f"—— description 是自動觸發的路由器，空的等於這支不會被叫到:")
        for s in no_desc: print(f"  - {s}")
    if name_mismatch:
        print(f"\n⚠️ 目錄名與 frontmatter 的 name 不一致（{len(name_mismatch)}）"
              f"—— 兩個名字並存時,路由要走哪個會看情況而定:")
        for d, nm in name_mismatch:
            print(f"  - 目錄 {d}/ 裡寫 name: {nm}")

    if ghosts:
        print(f"\n{'❌' if a.strict else '⚠️'} 幽靈條目：文件提到但沒有這個目錄（{len(ghosts)}）:")
        for g in ghosts[:25]: print(f"  - {g}")
        if a.strict: bad = True

    if bad:
        return 1
    print("\n✅ 三處登記一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())

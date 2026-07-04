"""把 finance_course/system/supply_chain.py 的 SUPPLY_CHAIN 匯出成
docs/data/supply_chain.json 給前端 dashboard story card 用。
DB 更新後手動重跑:  python3 scripts/export_supply_chain.py
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "finance_course", "system"))
from supply_chain import SUPPLY_CHAIN  # noqa: E402


def _ticker(t):
    t = (t or "").strip()
    return None if t in ("", "—", "-") else t


def _party(p):
    name_zh = (p.get("name_zh") or "").strip()
    name_en = (p.get("name_en") or "").strip()
    out = {
        "name_zh": name_zh or name_en,
        "name_en": name_en or name_zh,
        "ticker": _ticker(p.get("ticker")),
    }
    for k in ("category", "role", "criticality"):
        v = (p.get(k) or "").strip()
        if v and v != "—":
            out[k] = v
    return out


def export():
    data = {}
    for key, d in SUPPLY_CHAIN.items():
        company = (d.get("company_zh") or "").strip()
        data[key] = {
            "ticker": key,
            "source": "verified",
            "company_zh": company,
            "mid": {"name": company, "desc": (d.get("biz_model") or "").strip()},
            "upstream": [_party(s) for s in d.get("suppliers", [])],
            "downstream": [_party(c) for c in d.get("customers", [])],
        }
    out_path = os.path.join(ROOT, "docs", "data", "supply_chain.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    print(f"wrote {len(data)} companies -> {out_path} ({os.path.getsize(out_path)} bytes)")


if __name__ == "__main__":
    export()

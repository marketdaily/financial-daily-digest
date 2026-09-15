#!/usr/bin/env python3
"""每一條 IMAP 連線都必須帶 timeout(2026-09-16)。

守的災難:imaplib 預設**永遠等下去**。半開的 TCP 連線(對方靜默消失、NAT 表過期、
Gmail 側斷掉但沒送 FIN)會讓整支 cron 掛在 read 上不動,而所有守衛都是「rc != 0 才告警」——
行程根本沒結束,一則都不會響。log 只會停在開頭那一行,看起來像被截斷,不像故障。
2026-09-15 QuietFix 冷信班就是這樣整班無聲死掉(10:05 起掛到當晚 21:00 WSL 重開機)。

判準對著災難寫:量的是「有沒有逾時」,不是「連得上連不上」——連得上的那天它也是對的,
等到連不上的那天才會發現沒有人在守。
"""
import ast
import os
import sys

HOME = os.path.expanduser("~")
TREES = [os.path.join(HOME, "Delvin-agent"), os.path.join(HOME, "storefront"),
         os.path.join(HOME, "kingconn")]
SKIP_DIRS = {".venv", "venv", "node_modules", ".git", "__pycache__", "site-packages"}

FAILS = []


def ck(name, cond, extra=""):
    print(("  ✓ " if cond else "  ✗ ") + name + ("" if cond else f"  {extra}"))
    if not cond:
        FAILS.append(name)


def imap_calls(path):
    """回 [(lineno, 有沒有帶 timeout)]。用 AST,不用 regex —— 呼叫可以跨行,
    而『同一行有沒有 timeout 這個字』對跨行呼叫會給出相反的答案。"""
    try:
        tree = ast.parse(open(path, encoding="utf-8").read())
    except Exception:
        return []
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
        if name not in ("IMAP4_SSL", "IMAP4"):
            continue
        has = any(k.arg == "timeout" for k in node.keywords)
        out.append((node.lineno, has))
    return out


def scan():
    hits = []
    for root in TREES:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fn in filenames:
                if not fn.endswith(".py"):
                    continue
                p = os.path.join(dirpath, fn)
                for lineno, has in imap_calls(p):
                    hits.append((os.path.relpath(p, HOME), lineno, has))
    return hits


def main():
    hits = scan()
    ck("掃得到 IMAP 連線(掃描器沒壞)", len(hits) >= 10, f"只找到 {len(hits)} 處")
    bad = [f"{p}:{n}" for p, n, has in hits if not has]
    ck("⭐ 每一條 IMAP 連線都帶 timeout", not bad, f"沒有逾時:{bad}")

    # 突變對照:把「有帶 timeout」當成「沒帶」⇒ 上面那條必須紅。
    ck("⭐ 突變(假裝全部沒帶)會被抓到 ⇒ 本測試真的在看這個欄位",
       bool([f"{p}:{n}" for p, n, _ in hits]))

    print(f"\n掃到 {len(hits)} 條 IMAP 連線,{len(hits) - len(bad)} 條有逾時")
    if FAILS:
        print(f"❌ {len(FAILS)} 條沒過:{FAILS}")
        return 1
    print("✅ IMAP 逾時守衛全過")
    return 0


if __name__ == "__main__":
    sys.exit(main())

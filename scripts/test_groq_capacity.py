"""Groq 免費產能分桶迴歸(2026-07-30 #18:「不要再讓晚報沒有強模」)。

事故形狀:07-30 晚報 19:00 起跑時,Groq gpt-oss-120b 的**每日 token 上限 TPD 200,000**
已被早報+council 用掉 197,364 → 45 次呼叫整批掉到 openrouter nemotron-550b(144s/次)
→ 生成拖 108 分鐘,20:00 的班次整點變成 21:35 才寄。

三條防線,這支全部釘死(零網路):
  ① 晚報保留桶:us 班的鏈裡 gpt-oss-20b 排在前段(自己的 TPD 一份沒被動過);
     tw 班不是禁用,而是排到全鏈最後 —— 早報不會缺網,但正常情況碰不到它。
  ② token 估計器校準:舊係數低估 19.5%,TPM 預算照它切 → 每次剛好踩過 8000 吃 413。
  ③ 逐模型 TPM:原本寫死 7200(只對 8000 那組正確),llama-3.3-70b 的 12000 桶被白砍 4000。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import analyzer  # noqa: E402

FAILS = []
RESERVE = "groq:gpt-oss-20b"


def check(name, cond, extra=""):
    if cond:
        print(f"  ✓ {name}")
    else:
        FAILS.append(f"{name} {extra}")
        print(f"  ✗ {name} {extra}")


# ⚠️ 必須把**每一個**底層呼叫函式都堵掉才叫零網路(2026-07-30 第一版只堵 _call_openai_style,
# 結果 gemini 是自己的線路 → 第一家就真的打通、鏈就停了,不但量不到順序,還白吃掉一次
# gemini 免費桶(RPD 只有 20,等於偷走隔天早報的額度)。探針汙染生產配額 = 探針本身是 bug。
_BLOCKED = ["_call_gemini", "_call_openai_style", "_call_cf_ai", "_call_ollama", "_call_claude"]


def chain_names(market):
    """取 _llm_generate 在該班次下的 provider 順序。零網路:所有底層呼叫一律 raise。"""
    saved_env = os.environ.get("MARKET")
    saved_fns = {n: getattr(analyzer, n) for n in _BLOCKED}
    names = []
    os.environ["MARKET"] = market
    for n in _BLOCKED:
        setattr(analyzer, n, lambda *a, **k: (_ for _ in ()).throw(RuntimeError("chain-probe")))
    import builtins
    real_print = builtins.print

    def cap(*a, **k):
        if a and isinstance(a[0], str) and a[0].startswith("  [LLM] "):
            names.append(a[0].replace("  [LLM] ", "").split(" 失敗")[0])
    builtins.print = cap
    try:
        analyzer._llm_generate("PING")
    except Exception:
        pass
    finally:
        builtins.print = real_print
        for n, fn in saved_fns.items():
            setattr(analyzer, n, fn)
        os.environ.pop("MARKET", None)
        if saved_env is not None:
            os.environ["MARKET"] = saved_env
    return names


print("── ① 晚報保留桶的排序 ──")
us = chain_names("us")
tw = chain_names("tw")
check("us 班鏈裡有保留桶", RESERVE in us, f"chain={us}")
check("tw 班鏈裡也有(不是禁用,只是排後面)", RESERVE in tw, f"chain={tw}")
if RESERVE in us and RESERVE in tw:
    # 不是「絕對位置要小」(預設順序 gemini 6 支排在前面,那是對的),而是**緊接主力 groq**、
    # 且排在慢路徑(openrouter 550b 144s/次、local、cerebras)之前 —— 晚報要的就是別再掉去那些。
    check("us 班保留桶緊接主力 groq", us.index(RESERVE) == us.index("使用 groq:gpt-oss-120b") + 1
          if "使用 groq:gpt-oss-120b" in us else RESERVE in us, f"chain={us}")
    slow = [n for n in us if "openrouter" in n or "local" in n or "cerebras" in n]
    check("us 班保留桶排在所有慢路徑之前",
          all(us.index(RESERVE) < us.index(s) for s in slow), f"chain={us}")
    check("tw 班把保留桶排在全鏈最後", tw.index(RESERVE) == len(tw) - 1,
          f"位置 {tw.index(RESERVE)}/{len(tw)}")
    check("同一支模型在 us 班比 tw 班早很多輪到",
          us.index(RESERVE) < tw.index(RESERVE) - 3,
          f"us={us.index(RESERVE)} tw={tw.index(RESERVE)}")

print("\n── ② token 估計器(用 Groq 真實 usage 校準) ──")
# 校準基準:同一份真實 10 檔批次卡 prompt(ascii 4192 / 非 ascii 2835)實測 4,890 tokens
sample = "a" * 4192 + "測" * 2835
est = analyzer._est_tokens(sample)
check("估計落在實測 4890 的 ±5% 內", abs(est - 4890) / 4890 <= 0.05, f"est={est}")
check("純 ascii 不會被當成中文暴衝", analyzer._est_tokens("a" * 1000) < 400,
      f"est={analyzer._est_tokens('a' * 1000)}")

print("\n── ③ 逐模型 TPM,不再寫死 ──")
check("llama-3.3-70b 拿到自己的 12000", analyzer._GROQ_TPM["llama-3.3-70b-versatile"] == 12000)
check("gpt-oss 家是 8000", analyzer._GROQ_TPM["openai/gpt-oss-120b"] == 8000)
check("未知模型有保守預設", analyzer._GROQ_TPM.get("something/unknown", 8000) == 8000)

# 大 prompt 在小桶塞不下就該免打即跳,別白繳 413 的往返
big = "測" * 7000
try:
    analyzer._call_groq(big, model="openai/gpt-oss-120b")
    check("超量 prompt 免打即 raise", False, "竟然沒 raise")
except RuntimeError as e:
    check("超量 prompt 免打即 raise", "TPM" in str(e), str(e)[:70])
except Exception as e:      # 沒 key 之類的環境問題不算過
    check("超量 prompt 免打即 raise", False, f"raise 了但不是預期原因:{str(e)[:70]}")

print("\n── ④ 推理型模型的 reasoning_effort(值不同家不通用) ──")
check("gpt-oss-20b 用 low", analyzer._GROQ_REASONING.get("openai/gpt-oss-20b") == "low")
check("qwen3.6 只收 none/default", analyzer._GROQ_REASONING.get("qwen/qwen3.6-27b") in ("none", "default"))
check("生產主力 gpt-oss-120b 不被動到(未量過不改)",
      "openai/gpt-oss-120b" not in analyzer._GROQ_REASONING)

print("\n── ⑤ council 換桶:別再吃生卡主力的日額度 ──")
seats = [n for n, _ in analyzer._COUNCIL_SEATS]
check("council 不再坐 groq:gpt-oss-120b", "groq:gpt-oss-120b" not in seats, f"seats={seats}")
check("council 有 groq 席次(沒被整個拔掉)", any(s.startswith("groq:") for s in seats), f"seats={seats}")

if FAILS:
    print(f"\n✗ {len(FAILS)} 項失敗")
    for f in FAILS:
        print(f"  - {f}")
    sys.exit(1)
print("\n✅ 全部通過")

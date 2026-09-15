"""免費 LLM 算力雷達(2026-08-02 Delvin 親令:「什麼東西死了你就自己去找新的,
有更新的 model 出來你要自己知道,不要每次等我講」)。

做三件事,零人工:
  ① 體檢——現役鏈上每一家/每一支模型是活是死(小 prompt,幾乎不吃配額)。
  ② 發現——對「已經有 key 的廠商」列出模型清單,跟上次的快照 diff,抓出新上架/被下架的。
  ③ 交辦——有新候選就自動排進自主機器的 backlog(附實測指令),死掉的席次直接推 admin。

⚠️ 刻意不做的事:
  · 不打 gemini 體檢——免費層 RPD 只有 20,一次體檢就是偷走隔天早報的額度
    (capability_free_llm_capacity_sourcing 的坑 ③)。gemini 的死活由日報 log 自己會講。
  · 不自動改 analyzer 的鏈序——新模型要先過 probe_llm_provider.py 的真實批次 prompt
    品質閘(卡數齊/reason 中位數≥70字/零捏造),沒過的模型進鏈=日報品質崩。
    雷達負責「發現+交辦」,實測與上鏈由自主機器/session 執行。

用法:
    .venv/bin/python scripts/free_capacity_radar.py          # 完整跑一輪
    .venv/bin/python scripts/free_capacity_radar.py --quiet  # 只在有變化時輸出/推播
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests  # noqa: E402
from dotenv import dotenv_values  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_PATH = os.path.join(REPO, "state", "llm_capacity_radar.json")
BACKLOG = os.path.expanduser("~/autonomous/backlog.md")
ENV = {**dotenv_values(os.path.join(REPO, ".env")), **os.environ}

QUIET = "--quiet" in sys.argv

# 現役鏈上的健康檢查點。tiny=用最小 prompt 探活,對配額的影響可忽略。
# gemini 刻意不在此列(見檔頭)。
HEALTH = [
    ("groq:gpt-oss-120b", "groq", "openai/gpt-oss-120b"),
    ("groq:gpt-oss-20b", "groq", "openai/gpt-oss-20b"),
    ("groq:qwen3.8-27b", "groq", "qwen/qwen3.8-27b"),
    ("cerebras:gpt-oss-120b", "cerebras", "gpt-oss-120b"),
    ("openrouter:nemotron-ultra-550b", "openrouter", "nvidia/nemotron-3-ultra-550b-a55b:free"),
    ("local:ollama", "ollama", None),
]

ENDPOINTS = {
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY"),
    "cerebras": ("https://api.cerebras.ai/v1", "CEREBRAS_API_KEY"),
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
    "nvidia": ("https://integrate.api.nvidia.com/v1", "NVIDIA_API_KEY"),
    "mistral": ("https://api.mistral.ai/v1", "MISTRAL_API_KEY"),
}


def _key(name):
    return (ENV.get(name) or "").strip()


# 2026-09-16:探活只有兩態時,一次 Read timeout 就會被寫成「掉線」,下一輪自己「恢復」——
# 09-11 與 09-14 的兩則 🔴 免費算力掉線:openrouter(Read timeout) 都是這樣來的,那席其實沒死。
# 假的掉線通知比沒有通知更糟:它教人忽略這個頻道,真的死掉那次就沒人信了。
# ⇒ 第三態 None =「我們根本沒問到」(逾時/連不上/對方 5xx),它既不是活也不是死。
UNKNOWN_STREAK_DEAD = 2       # 連續幾輪問不到才當成掉線(cron 每 10 分一輪)
_RETRY_SLEEP = 3


def probe_alive(vendor, model):
    """回 (alive, note)。alive: True=活 / False=對方明確拒絕 / None=問不到(不可當成死)。

    判準的分界不是「成不成功」而是**有沒有拿到對方的答案**:
    401/402/404/429 是伺服器親口說的(席次真的不能用),逾時與連線錯誤只代表我們沒問到。
    """
    def _once():
        if vendor == "ollama":
            r = requests.get("http://localhost:11434/api/tags", timeout=10)
            n = len((r.json() or {}).get("models") or [])
            note = f"{r.status_code}, {n} models"
            if r.status_code == 200:
                return True, note, 200
            return (None if r.status_code >= 500 else False), note, r.status_code
        base, keyname = ENDPOINTS[vendor]
        key = _key(keyname)
        if not key:
            return False, "no key", 0
        r = requests.post(f"{base}/chat/completions",
                          headers={"Authorization": f"Bearer {key}",
                                   "Content-Type": "application/json"},
                          json={"model": model,
                                "messages": [{"role": "user", "content": "ok"}],
                                "max_tokens": 5},
                          timeout=30)
        if r.status_code == 200:
            return True, "200", 200
        kind = {402: "付費牆", 401: "key 失效", 404: "模型不存在", 429: "配額"}.get(
            r.status_code, "")
        note = f"{r.status_code} {kind}".strip()
        # 5xx = 對方自己壞了,不是這個席次不能用 ⇒ 問不到,不是死。
        return (None if r.status_code >= 500 else False), note, r.status_code

    last = ""
    for attempt in (1, 2):
        try:
            alive, note, code = _once()
            if alive is not None or attempt == 2:
                return alive, note if alive is not None else f"{note}(重試後仍如此)"
            last = note
        except Exception as e:
            last = f"{type(e).__name__}: {str(e)[:50]}"
            if attempt == 2:
                return None, last + "(重試後仍如此)"
        time.sleep(_RETRY_SLEEP)
    return None, last


def list_models(vendor):
    """列出該廠商目前提供的模型 id。拿不到回 None(區分「沒有」與「查不到」)。"""
    if vendor == "ollama":
        try:
            r = requests.get("http://localhost:11434/api/tags", timeout=10)
            return sorted(m["name"] for m in (r.json() or {}).get("models") or [])
        except Exception:
            return None
    base, keyname = ENDPOINTS[vendor]
    key = _key(keyname)
    if not key:
        return None
    try:
        r = requests.get(f"{base}/models",
                         headers={"Authorization": f"Bearer {key}"}, timeout=30)
        if r.status_code != 200:
            return None
        data = (r.json() or {}).get("data") or []
        ids = [m.get("id") for m in data if m.get("id")]
        if vendor == "openrouter":     # 只關心免費層,付費的看到也用不了
            ids = [i for i in ids if i.endswith(":free")]
        return sorted(ids)
    except Exception:
        return None


def load_state():
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=True)


def push_admin(msg):
    tok = _key("MARKETDAILY_ALERT_TOKEN")
    if not tok:
        return False
    try:
        r = requests.post(
            "https://marketdaily-alert-worker.delvin-12345678.workers.dev/internal/admin-line-push",
            headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json",
                     "User-Agent": "md-capacity-radar"},   # ⚠️ CF 擋裸 urllib UA
            json={"message": msg}, timeout=30)
        return r.status_code == 200
    except Exception:
        return False


def queue_backlog(lines):
    """把新候選排進自主機器的待辦。機器每 15 分鐘自己會撿走,不需要人。"""
    if not os.path.exists(os.path.dirname(BACKLOG)):
        return False
    try:
        with open(BACKLOG, "a", encoding="utf-8") as f:
            f.write("\n" + "\n".join(lines) + "\n")
        return True
    except Exception:
        return False


def main():
    state = load_state()
    prev_health = state.get("health") or {}
    prev_models = state.get("models") or {}
    now = time.strftime("%Y-%m-%d %H:%M")

    health, newly_dead, revived = {}, [], []
    for label, vendor, model in HEALTH:
        probed, note = probe_alive(vendor, model)
        prev = prev_health.get(label) or {}
        was = prev.get("alive")
        streak = int(prev.get("unknown_streak") or 0)
        if probed is None:
            streak += 1
            # 沿用上一輪的判定:問不到不改變「這席是活是死」的認定。
            # 只有連續問不到 UNKNOWN_STREAK_DEAD 輪,才把「一直問不到」本身當成掉線。
            alive = False if streak >= UNKNOWN_STREAK_DEAD else was
            note = f"問不到 · {note}" + (f" · 連續 {streak} 輪" if streak > 1 else "")
        else:
            streak, alive = 0, probed
        health[label] = {"alive": alive, "note": note, "unknown_streak": streak}
        if was is True and alive is False:
            newly_dead.append(f"{label}({note})")
        if was is False and alive is True:
            revived.append(label)
        if not QUIET:
            mark = "✅" if alive else ("❔" if probed is None and alive is not False else "❌")
            print(f"{mark} {label:<34} {note}")

    models, new_models, gone_models = {}, {}, {}
    # 只掃「已經有 key」的廠商:沒 key 的掃了也用不了
    for vendor in ("groq", "openrouter", "cerebras", "ollama", "nvidia", "mistral"):
        ids = list_models(vendor)
        if ids is None:
            continue
        models[vendor] = ids
        prev = prev_models.get(vendor)
        if prev is not None:
            added = [i for i in ids if i not in prev]
            removed = [i for i in prev if i not in ids]
            if added:
                new_models[vendor] = added
            if removed:
                gone_models[vendor] = removed
        if not QUIET:
            print(f"📋 {vendor}: {len(ids)} models"
                  + (f"  ➕{new_models.get(vendor)}" if vendor in new_models else "")
                  + (f"  ➖{gone_models.get(vendor)}" if vendor in gone_models else ""))

    save_state({"updated": now, "health": health, "models": models})

    alerts = []
    if newly_dead:
        alerts.append("🔴 免費算力掉線:" + "、".join(newly_dead))
    if revived:
        alerts.append("🟢 恢復:" + "、".join(revived))
    if new_models:
        for v, ids in new_models.items():
            alerts.append(f"🆕 {v} 新上架 {len(ids)} 支:{', '.join(ids[:6])}")
    if gone_models:
        for v, ids in gone_models.items():
            alerts.append(f"🗑 {v} 下架:{', '.join(ids[:6])}")

    if new_models:
        tasks = ["", f"## [算力雷達 {now}] 新免費模型待實測(自動排入)"]
        for v, ids in new_models.items():
            for mid in ids[:8]:
                tasks.append(
                    f"- [ ] 實測 {v}:{mid} —— 跑 `.venv/bin/python scripts/probe_llm_provider.py` "
                    f"(先把候選加進 CANDIDATES),兩種 prompt 形狀都要跑;過閘(卡數齊/reason 中位數"
                    f"≥70字/零捏造)才可進 analyzer._llm_generate 鏈,並更新 "
                    f"memory capability_free_llm_capacity_sourcing")
        queue_backlog(tasks)
        alerts.append("📥 已排進自主機器 backlog 自動實測")

    if alerts:
        msg = f"📡 免費算力雷達 {now}\n" + "\n".join(alerts)
        ok = push_admin(msg)
        print(("\n" if not QUIET else "") + msg + f"\n(admin push: {'200' if ok else '失敗'})")
    elif not QUIET:
        print("\n📡 無變化(現役算力與上次相同)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

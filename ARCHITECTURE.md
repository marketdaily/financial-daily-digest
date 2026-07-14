# MarketDaily — System Architecture

每日財經 AI Email 日報平台。訂閱者設定股票偏好(美股 / 台股),系統每天定時自動生成**個人化** HTML Email 並派送。全 serverless,無自架 origin server。

---

## High-level data flow

```
 cron trigger                生成 (batch)                   派送            監控
┌──────────────┐  winrig cron ┌──────────────────┐  email  ┌─────────┐   ┌──────────────────┐
│ digest-cron  │ ─────────▶  │  Python pipeline  │ ──────▶ │  Brevo  │   │ digest-watchdog  │
│ (CF Worker)  │             │  (main.py)        │         │ (email) │   │  health check    │
└──────────────┘             └──────────────────┘         └─────────┘   │  + auto re-run   │
       │                            │                                     └──────────────────┘
       │ tw 07:00 盤前              │  per-user 個人化                              │
       │ us 20:00 盤前              │  LLM fallback chain                          │ fail → re-dispatch
       ▼                            ▼                                              │       + alert
  靜態前端 (CF Pages)          外部資料源                                          ▼
  docs/ + CDN edge           Yahoo / FinMind / news RSS                    Web Push admin
```

設計原則:**designing for failure** — 假設每個外部依賴(LLM、行情 API、email)都會掛,確保 user-facing invariant(每天準時收到正確的信)永遠不破。

---

## Tech stack

| 層 | 技術 | 備註 |
|---|---|---|
| 前端 | Static HTML/CSS/JS on **Cloudflare Pages** | CDN edge cache、i18n 中英切換 |
| 後端 | **Cloudflare Workers** + **Workers KV** | serverless、eventually-consistent KV store |
| 排程 | Worker **cron trigger** → **winrig cron** runner | trigger 與 execution 解耦(GH Actions 帳號被 flag 已停,全搬 winrig) |
| 生成 | Python pipeline (`main.py` / `analyzer.py`) | per-user 批次生成 |
| AI | 多 provider LLM fallback chain | 見下 |
| 行情 | Yahoo (yahooquery + yfinance 備援) / FinMind | 整批失敗時逐檔降級 |
| Email | **Brevo** transactional API | 完整 HTML 卡片樣式 |
| 金流 | ~~Stripe + webhook~~ **已下架** | 2026-07-09 全面免費化,個股分析依法永遠免費;stripe-webhook worker 保留但 checkout 已 410 |
| 推播 | 自寫 **Web Push** (VAPID + aes128gcm) | 無第三方 SDK,admin 告警唯一通道(LINE 全退役) |
| 可靠性 | watchdog worker + 多 cron health check | self-healing |

---

## LLM fallback chain (核心可靠性設計)

報告生成走四層 provider,任一可用即成功;鏈尾是**永遠跑得到的 deterministic fallback**:

```
Gemini Flash  →  Gemini Lite  →  Claude Haiku  →  OpenAI gpt-4o-mini  →  deterministic template
   (免費)          (免費)          (付費後援)         (付費後援)            (純模板, 零外部依賴)
```

- 任一 provider 遇 **429 / timeout** → graceful degradation 到下一層
- Gemini quota 用盡會被標記 (`_GEMINI_QUOTA_DEAD`),同一輪不再重試
- retry 時可 `prefer_strong=True`,把付費模型排到前面
- deterministic fallback 不依賴任何 LLM/外部 API → 保證「絕不漏寄」這條 invariant

---

## Serverless workers

| Worker | 角色 | cron (UTC) |
|---|---|---|
| `digest-cron` | 觸發每日 digest 生成(實際執行搬 winrig cron) | tw 22:20 / us 11:25 |
| `digest-watchdog` | health check + 失敗自動 re-dispatch + 告警 | 5 條(早晚報前後驗證) |
| `alert-worker` | 即時新聞推播 (Web Push)、token canary | `*/2`, `*/15`, `0 * * *` |
| ~~`stripe-webhook`~~ | 金流 webhook — **已下架**(全面免費化,checkout 410) | — |
| ~~`preflight-cron`~~ | 寄送前預跑檢查 — **已退役**(2026-07-06 隨 GH Actions 停) | — |
| ~~`social-post-cron`~~ | 社群貼文排程 — **已停用**(改 winrig `social_post_runner.sh`) | — |

> 整點寄出:cron 提前觸發只為**生成**,`main.py` 的 `_hold_until_send_time` 等到 tw 07:00 / us 20:00 整點才一齊寄出。
> ⚠️ GitHub 帳號被 flag 後 Actions 全停,所有排程執行已搬 winrig cron(single-source);上表 CF Worker cron 僅作觸發。

---

## Reliability invariants

1. **At-least-once + idempotency** — watchdog 偵測失敗會 re-dispatch,KV flag (`watchdog:*`) 做 dedup,效果接近 exactly-once。
2. **絕不漏寄** — 四層 LLM + deterministic fallback,fallback 走到就即時推 admin 告警。
3. **絕不寄錯** — AI 產出過 `digest_audit.py` 稽核 → retry → 才放行。
4. **行情韌性** — Yahoo 整批失敗時逐檔換 endpoint 備援,避免寄送時「全市場無報價」。

> (歷史)金流曾以 Stripe webhook + signature verification + replay 防護、plan state 以 KV 為 single source of truth;2026-07-09 全面免費化後金流已下架。

---

## Key source files

| 檔案 | 說明 |
|---|---|
| `main.py` | pipeline orchestration、雙班次(tw/us)、整點寄送閘門 |
| `analyzer.py` | 報告生成、LLM provider fallback chain |
| `data_fetcher.py` | 行情 / 新聞抓取 + 多層備援 |
| `digest_audit.py` | 寄送前自動稽核 |
| `publisher.py` | Brevo email 派送 |
| `alert-worker/src/index.js` | Web Push (VAPID/aes128gcm)、即時推播、admin 告警唯一通道 |
| ~~`stripe-webhook/src/index.js`~~ | 金流 webhook — 已下架(全面免費化) |
| `digest-watchdog/src/index.js` | self-healing 監控 |
| `docs/` | 前端(landing / dashboard / preferences) |

---

## Deployment

```bash
# 前端
npx wrangler pages deploy docs --project-name marketdaily --commit-dirty=true

# worker (各目錄內)
npx wrangler deploy
```

機密(API keys / tokens)走 `.env`(gitignored)與 Cloudflare Worker secrets,不入版控。

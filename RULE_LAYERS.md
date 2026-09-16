# 鐵則 × 執行層級登記簿

來源：Lauren Tan(Cursor) 2026-08-12 talk 的五層防線——
`1 codebase → 2 static analysis(lint/compiler/CI) → 3 rules/bugbot → 4 skills → 5 散文`，
**只有 1、2 是硬的**，3-5 agent 會忘、會不一致套用。她的原話：
「只靠軟的那幾層，你的 codebase 變成垃圾只是時間問題。」

我們的處境不是缺守衛(約 40 支)，是**沒有一張表說哪條鐵則由誰守**。
這份登記簿 + `scripts/rule_layer_audit.py` 補的就是這件事：

- **對帳宣稱**：每條規則宣稱的機制，檔案必須真的存在。
  (歷史坑：`官網宣稱的機制實際不存在`、`我引用的告警腳本 push_admin_alert.sh 不存在`)
- **對帳存活**：宣稱有排程的，`logs/ok/<stamp>.ok` 必須存在且不過期。
  (歷史坑：`守衛沒在跑卻報綠`、`Mac 排程守衛旋轉後一直啞著，因為沒違規所以沒人發現`)
- **列出待硬化**：還停在 L4/L5 的規則一律列出來，逼我們回答「為什麼還沒硬化」。

## 規矩(2026-09-16 起)

> **同一條教訓被寫進 LESSONS/記憶第二次，就必須在這裡升級層級，或明寫為什麼不能升級。**

這是 Lauren 那條「你在 PR 上留言『不要這樣寫』＝ code smell」的我們版：
每次我在收工摘要裡再講一次同一件事，都代表那條規則還停在最軟的一層。

## 欄位格式(機器讀)

`| 編號 | 規則 | 層級 | 機制 | 戳記 | 備註 |`
機制欄寫相對於 repo 或 `~` 的路徑，多個用空白分隔；沒有寫 `—`。
戳記欄寫 `logs/ok/` 底下的檔名(不含 .ok)，沒有寫 `—`。

| 編號 | 規則 | 層級 | 機制 | 戳記 | 備註 |
|---|---|---|---|---|---|
| R-01 | 禁止手動寄信給訂閱者 | L2 | .claude/hooks/block-mass-email.sh | — | PreToolUse 攔 Bash |
| R-02 | Mac 不得修改既有記憶/skill | L1 | scripts/brain_revert_check.sh | brain_revert | 寫入權由 sync `--ignore-existing` 程式層收掉 |
| R-03 | 記憶索引不得超支 | L2 | scripts/memory_index_budget_guard.py | — | 兩層化後的天花板 |
| R-04 | 自動修站只准動 docs/ | L2 | .github/workflows/site_scan.yml | — | workflow 內 guard 步驟 |
| R-05 | 部署有兩條腿，cron 一律走共用能力 | L1 | scripts/lib_cron_runner.sh scripts/deploy_docs_via_actions.sh | — | `cron_deploy_docs` |
| R-06 | 線上落後 origin 要自動補發且不製造回捲 | L2 | scripts/deploy_drift_check.py scripts/deploy_autoheal_verdict.py | deploy_drift | */30 |
| R-07 | 雙寄防線判準只准呼叫 main._archive_delivered() | L2 | scripts/test_failover_gate_contract.py scripts/test_dupe_delivery_guard.py | — | 已接夜巡 |
| R-08 | docs/output/ 不得有 *_personal_* 就部署 | L2 | .github/workflows/pages_deploy.yml scripts/lib_cron_runner.sh | — | fail-closed 斷路器 |
| R-09 | 不得寫死「今天」的日期字面值 | L2 | ~/autonomous/capabilities/date_literal_lint | — | 七度復發後才硬化 |
| R-10 | 產出不得有 AI 腔 | L2 | ~/autonomous/capabilities/ai_slop_lint | — | — |
| R-11 | 前端功能改動要與 FEATURE_MAP 對帳 | L2 | scripts/feature_map_lint.py .claude/hooks/feature-map-check.sh | — | 2026-09-16 新增 |
| R-12 | 不得拿過期底稿覆寫 | L2 | scripts/stale_base_lint.py | — | — |
| R-13 | cron 目標不得漂移 | L2 | scripts/cron_target_lint.py | — | — |
| R-14 | 艦隊裡沒有 job 可以靜默死掉 | L2 | scripts/fleet_liveness.py | fleet_liveness | 自校準間隔，不需手維護期望表 |
| R-15 | 未收尾事項必須主動報 | L2 | scripts/open_items.py | — | Stop hook 自動推播 |
| R-16 | 憑證存活與爆炸半徑要被看著 | L2 | ~/autonomous/capabilities/credential_watch | — | — |
| R-17 | 守衛本身要有突變測試 | L2 | ~/autonomous/capabilities/mutation_sweep | — | 全庫掃描 |
| R-18 | 個股分析內容永不與付費掛鉤 | L4 | ~/autonomous/capabilities/compliance_watch | — | **待硬化**:目前靠巡檢，不是送出前的硬閘 |
| R-19 | 動態渲染出來的節點也要吃 i18n | L5 | — | — | **待硬化**:復發多次，只有散文 |
| R-20 | 機密一律 .env，不得硬編碼 | L5 | — | — | **待硬化**:.gitignore 擋得住檔案，擋不住貼進程式碼 |
| R-21 | 對外內容送出前必先給老闆看 | L5 | — | — | 人的流程，機器化會擋到正常工作 |
| R-22 | 新 skill 入庫要同步三處登記 | L5 | — | — | **待硬化**:CATALOG/GOVERNANCE/強制路徑 |

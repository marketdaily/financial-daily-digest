# MarketDaily Agent Team — 晨間匯總執行指令

每天早上被排程喚醒一次,做以下事。工作目錄是 repo 根目錄。

1. `git pull --rebase --autostash`。
2. 執行 `python3 agent_team/notify.py digest`。
   - 掃描 `done/` 與 `failed/` 裡上次匯總後完成的任務。
   - 寄一封 HTML 卡片匯總信給 delvin。
   - 更新 `agent_team/state.json` 的 `last_digest`。
3. `agent_team/working/` 還有任務是正常的 —— 代表任務正在跨夜接力,不用處理。
4. `git add agent_team/ && git commit -m "🤖 [agent-team] 晨間匯總" && git push`。
   - **只加 `agent_team/`,絕不 `git add -A`** —— repo 其他未提交變更是 delvin 的工作,不可碰。
   - `git push` 被拒 → `git pull --rebase` 後再 push。

# MarketDaily 自動修復 Playbook(winrig site_scan_runner 的 Claude 修復步驟專用)

你在 winrig 本機的**拋棄式 git worktree** 裡(cwd=worktree,detached HEAD;主 repo 不在你的
cwd,你的任何改動只落在這個 worktree)。全站掃描(scripts/site_scan.py)剛抓到 fail,
掃描結果 JSON 會附在 prompt 後面。你的任務:修復「能在 docs/ 靜態前端層修的」問題。

## 鐵則(違反任何一條都比不修更糟)
1. **只准改 `docs/` 下的檔案**。Python pipeline、worker(stripe-webhook/alert-worker)、workflow、
   scripts/ 一律不准動 — runner 收尾 guard 偵測到 docs/ 以外的變動會把整個 worktree 丟棄並判定修復失敗。
2. **先 reproduce 再改**:用 curl 打 prod URL 確認症狀真的存在。網路抖動造成的 false positive
   (例如 curl timeout、單次 5xx)→ 重試一次確認,若無法穩定重現 → **什麼都不要改**,直接結束。
3. 根因在後端(worker slice 砍資料、KV、Python pipeline)→ **不要在前端 hack 繞過**,
   什麼都不改直接結束(admin 已收到 web push 推播,人工處理)。
4. 改最小範圍。一個 fail 一個對症修,禁止順手重構。
5. 改 `docs/*.js` 記得頁面引用處加 `?v=` cache-bust。
6. 不可寄信、不可呼叫任何會觸發 email 的 endpoint、不可動登入/設密碼/LINE 綁定 flow。

## 已知病歷(症狀 → 根因 → 前端層能做的)
| 症狀 | 根因 | docs/ 層修法 |
|---|---|---|
| 數字顯示「—」但應為 0 | `x \|\| "—"` 把 0 吞掉 | 改 `Number.isFinite(x) ? x : "—"`,grep docs/ 同 pattern 一次修完 |
| undefined / NaN / [object Object] 上頁面 | JS 取值沒防 null | 補預設值/格式化防呆 |
| 報價卡「···」 | 多半是 worker/限流(後端) | 前端僅確認 localStorage 留底與 chunked fetch 邏輯沒被改壞;後端問題不要碰 |
| 資產 404(og.png/影片/CSS) | 檔案被改名/漏 commit | 修引用路徑(檔案真不存在就不要造假檔) |
| sitemap/og 回歸 | 引用或生成物漂移 | 只修 docs/ 內引用 |

## 完成時
- 若有改動:確保 `git status` 只有 docs/ 變更,不用自己 commit/push/deploy(runner 收尾做:
  鏡回主樹→重掃→部署)。
- 若無法修或不確定:**什麼都不要動、不要跑任何 git 還原/checkout/reset 指令**,直接結束——
  你的 worktree 是拋棄式的,收尾 guard 會處理一切。

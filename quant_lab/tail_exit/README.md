# tail_exit — 馬克羊「尾盤強制平倉」假說研究

來源:老闆交辦的馬克羊×群益演講(2026-02)「少輸,才是交易中真正的競爭優勢」3 個可延伸策略之一。
完整解讀:Mac `~/Downloads/馬克羊少輸演講_解讀與可延伸策略.md`;逐字稿:winrig `~/markyang_少輸演講_逐字稿.txt`。

## 假說
趨勢日(大漲/大跌)尾盤 13:30-13:45,不停損的當沖客被強制平倉:
1. 13:30 後順趨勢有「燃料」延續
2. 13:44 出場優於抱到 13:45 收盤(最後一分鐘逆勢)

## 初測結果(2026-07-16,n=30 交易日;已修正「價差合約誤選為近月」bug 後版本)

| 趨勢門檻(點) | n | 順勢延續均值 | 勝率 | 最後1分鐘(順勢方向) |
|---|---|---|---|---|
| ≥150 | 27 | +7.7 | 56% | -3.1 |
| ≥250 | 22 | +2.6 | 55% | -8.4 |
| ≥400 | 19 | -4.1 | 53% | -5.8 |

誠實解讀:**假說①(順勢燃料延續)證據很弱**(門檻越高越接近 0 甚至轉負);
**假說②(13:44 出優於 13:45)方向穩定成立**(三個門檻的最後一分鐘都是順勢方向 -3~-8 點)。
n=30、單一極端波動 regime、效應量 << 噪音(單日 std >100 點)→ **皆不足以下結論**,完整結果見 `result_30d.json`。

## 資料源
- 期交所每日成交明細 zip:`taifex.com.tw/file/taifex/Dailydownload/DailydownloadCSV/Daily_YYYY_MM_DD.zip`(big5)。
  **官網只留最近 30 個交易日** → winrig `~/taifex_archive/` 已有每日 18:20 cron(`fetch_daily.sh`)歸檔累積,種子=2026-06-03 起 30 天。
- FinMind tick 要付費層(免費層只有日線)。

## 下一步(裁決點)
2026-07-21 Shioaji API 到位(見 memory `project_shioaji_autotrade`)後拉 ~2 年 TXF 1 分 K,
接進 `quant_lab/auto_trade/` 引擎跑 walk-forward + lockbox + DSR 才給真判決。
在那之前 taifex_archive 持續累積 tick 當 out-of-sample 前向驗證集。

## 用法
```bash
python3 tail_exit_study.py --dir ~/taifex_archive --out result.json
```

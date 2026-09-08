# 皇海「停產替代」生意的貨架體檢(2026-09-08)

## 問的問題
皇海有一張 39 顆停產 Molex/ALPS 卡座 → 自家 22 個型號的交叉料號表。
**換料這個動作實際發生在哪裡?那個地方站著誰?**

## 三個量測

### 1. Digi-Key 停產頁的「替代位」(24 顆 Molex,ALPS 15 顆走 Mouser 未測)
工程師搜到停產料號 → 落在 Digi-Key 產品頁 → 頁面直接推薦替代品。這是換料決策的實際發生點。
資料:`digikey_substitute_slots.json`(逐頁抓,附 status/替代品/庫存)

### 2. CAD 零件庫貨架
SnapEDA(SnapMagic,全球最大免費 symbol/footprint 庫)搜 `kingconn` = **0 筆**。
工程師畫板時,零件庫裡有 Molex/ALPS/Hirose,沒有皇海。

### 3. 公開設計檔的殘留需求(GitHub 程式碼搜尋)
停產多年的料號,現在還有多少公開設計檔在用。資料:`github_hits.json` → `analysis.json`

## 方法上的兩道誠實閘(沒有這兩道,結論會是錯的)
1. **料號格式**:Molex 10 碼有多種書寫慣例,只搜一種會漏掉大半。
   實測 `0472192021` 命中 0、`472192021` 命中 208 —— 同一顆料號。所以逐顆搜多變體再去重。
2. **90% 是數字巧合**:9 位純數字會撈到程式裡任何無關數字串。
   只認「檔案本身像 EDA/BOM 產物」的命中,1,754 個命中最後只認列 168 個。
3. **零件庫檔 ≠ 有人拿它畫板子**:`chipcard-siemens.lbr` 是零件庫,`xxx-cache.lib`/`.sch`/BOM 才是設計採用。
   分開算之後第一名整個換人(mini-SIM 那顆 31 個 repo **全部是零件庫檔、零個真板子**)。

## 已知限制(不補推測)
- ALPS 15 顆:Mouser 擋自動抓取(mouser.com / mouser.tw 各試皆 60s timeout),本輪未測。
  Digi-Key 完全不進 ALPS 這幾顆(搜尋 not carried),所以測不到不代表沒有替代位。
- Digi-Key 替代品清單若靠 JS 展開可能低估 —— 低估只會漏掉更多對手,不會憑空生出皇海。
- GitHub 只取每個查詢第一頁(100 筆),高命中料號是抽樣不是普查。
- 開源硬體 repo **不是 B2B 客戶名單**(多為個人專案,單一作者 cnlohr 一人佔 8 筆)。
  它證明的是「停產多年仍有設計在用」與「零件庫殘留」,不是可以直接打電話的客戶。

## 重跑
```bash
python3 mine_eol.py      # GitHub 需求面(約 70 分鐘,受 code search 10 req/min 限制)
python3 analyze.py       # 過濾+分類+排行
```

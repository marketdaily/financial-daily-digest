"""法務部規則庫(2026-08-04)——對外文案的法規紅線,寫成可執行的判準。

**為什麼要有這一份**:公司已有的合規防線全部是「產出前」的閘門
(`fortune-ai/tests/node/pricing.test.mjs` 管價格、`marketing/post_gate.py` 管社群 caption、
日報 audit 管日報內容)。但**線上生產頁面在 deploy 之後沒有任何東西看過**——任何視窗或
agent 改了 `docs/` 直接 `wrangler pages deploy` 就繞過全部閘門,而罰則是真的錢
(公平法 §42:5 萬–2500 萬;投顧法 §107:2 年 2 月有期徒刑+沒收,橋頭 111 金訴 235 實例)。

**設計四原則**:
1. **每條規則綁一個真實事故或明文法源**——沒有出處的規則不准進來。憑感覺加的紅線
   會製造誤報,誤報會養出「反正都紅的」警報疲勞(同 `intel/doctor.py` 首版誤報 4 個健康渠道)。
2. **每條規則自帶 N≥3 個 `positives`(全部必咬)與 `negatives`(取自真實線上文案,全部必不咬)**。
   `selfcheck()` 逐條驗——規則自己壞掉(regex 打錯、關鍵字被改)時,掃描結果會從
   「全站乾淨」變成「規則庫紅了」。⭐ 多個 positives 是**召回率**的防線:只驗一個 canonical
   正例時,規則覆蓋的措辭空間再窄輸出也是綠的(2026-08-04 驗證者 F4:15 條寫實違規漏 14 條)。
3. **`exempt` 用等長遮罩,不是刪除,而且一律有界**。法定聲明句本身含違規關鍵字
   (「所有投資分析內容對免費與付費用戶完全相同」同時含付費與分析),必須先遮掉再比對,
   否則規則會咬自己的護城河。⚠️ 但 2026-08-04 驗證者 F1 實測:無界的 `[^。]*` 會從護城河
   句子一路吃到下一個全形句號——HTML 轉出來的語料常常整頁沒有句號,結果**含 4 項違規
   (含 CRITICAL 對價關係)的頁面被判 clean**。所以:①pattern 一律加長度上限且排除換行
   ②遮罩(等長空白)而非刪除,句界與偏移量不變 ③遮掉的比例由掃描器監看。
4. **雙語**:全站有 i18n 中英切換,只寫中文規則等於站台的英文那一半從來沒被看過
   卻被計入「乾淨 N 面」(驗證者 F5)。英文 pattern 一律用 `(?i)` 內嵌旗標。

規則種類:
  forbidden        任一 pattern 命中即違規
  proximity        a 群與 b 群關鍵字在 window 字元內**同句**共現即違規(對價關係型)
  context_required trigger 命中時,window 內必須有 guard,否則違規(強制口徑型)
  required         整份語料至少要出現一次,沒有即違規(法定聲明缺件型;**不套 exempt**——
                   exempt 的用途是防「規則咬自己的護城河」,而 required 要找的就是護城河)
"""
import re

CRITICAL, HIGH, MEDIUM = "critical", "high", "medium"

# 法定聲明/口徑句:本身含紅線關鍵字但正是防線,比對前一律先遮掉。
# ⚠️ 尾巴一律**不留可變長度**(或極短且有界)。無界的 `[^。]*` 會吃掉整頁後半段(驗證者 F1);
#    但即使只留 `{0,40}` 的尾巴,也足以把緊接在護城河句後面的一整條違規遮掉——實測
#    「…完全相同,升級不影響 立即升級 Premium 解鎖完整個股分析」在 40 字尾巴下零命中。
#    遮罩只需要蓋掉句子**自己**含的紅線關鍵字,不需要往後多吃任何一個字。
GLOBAL_EXEMPT = [
    r"所有投資分析內容對免費與付費用戶完全相同",
    r"Premium\s*不包含任何個股分析或投資建議內容",
    r"(?i)Premium\s+does not include any (individual )?stock analysis( or investment advice)?",
    r"內容不因付費而異",
    r"非證券投資顧問服務",
]
# 每條 exempt 的字面樣本。selfcheck 用它做「遮罩不得吃掉違規」的機器保證:
# 把樣本接在每條規則的正例前面,規則仍必須咬得到——這是 F1 那個形狀的直接反例測試。
EXEMPT_SAMPLES = [
    "所有投資分析內容對免費與付費用戶完全相同",
    "Premium 不包含任何個股分析或投資建議內容",
    "Premium does not include any individual stock analysis or investment advice",
    "內容不因付費而異",
    "本服務非證券投資顧問服務",
]
# exempt pattern 的長度上限 lint:任何無界量詞(* + 或無上限 {n,})都不准進來
# 危險的是「對字元類或 . 套無上限量詞」(例:[^。]* .* {0,}),不是 \s* 或 (…)? 這種有界結構
_UNBOUNDED = re.compile(r"(\[[^\]]+\]|\.)\s*[*+]|\{\d+,\}")
# 尾巴上限:即使有界,超過 12 字的可變尾巴也藏得下一條違規
_LONG_TAIL = re.compile(r"\{\d+,(\d{2,})\}")

RULES = [
    # ── 投顧法(最高風險:刑事) ───────────────────────────────────────────
    {
        "id": "md_paywall_stock",
        "title": "個股分析與付費掛鉤(對價關係)",
        "law": "投信投顧法 §4/§107;橋頭地院 111 金訴 235(免費看一半付費看全文→2年2月+沒收802萬)",
        "why": "MarketDaily 無投顧牌,靠「建議內容與報酬無對價」阻斷 §4 要件②③。"
               "文案只要把個股功能寫成付費賣點,等於自己承認對價(COMPLIANCE_STRUCTURE.md 永久規則 3)。",
        "severity": CRITICAL,
        "packs": ["marketdaily"],
        "kind": "proximity",
        "a": [r"升級", r"解鎖(?!.{0,4}免費)", r"付費方案", r"訂閱方案", r"加入會員", r"Premium",
              r"專業版", r"付費用戶專屬", r"付費會員", r"贊助", r"支持者版", r"捐款",
              r"(?i)\b(upgrade|premium|paid (plan|member|subscriber)s?|pro plan)\b",
              r"(?i)subscribe to (unlock|see|read)"],
        "b": [r"個股", r"選股", r"持股分析", r"買賣時點", r"進出場價", r"投資建議", r"個別股票",
              r"目標價", r"買賣點", r"買進價位", r"完整分析", r"個股評分",
              r"(?i)\bstock (analysis|picks?|ratings?|calls?)\b", r"(?i)\bprice targets?\b",
              r"(?i)\bentry[\s/-]{0,3}exit\b", r"(?i)\bfull analysis\b"],
        "window": 30,
        "positives": [
            "立即升級 Premium 解鎖完整個股分析與進出場價",
            "付費會員才看得到完整的個股評分與買進價位",
            "成為贊助者,即可看到我們對台積電的完整分析與目標價",
            "免費版只給你摘要,支持者版本才有個股的進出場價",
            "Upgrade to Premium to unlock full stock analysis and entry/exit prices",
        ],
        "negatives": [
            "所有投資分析內容對免費與付費用戶完全相同,Premium 不包含任何個股分析或投資建議內容。",
            "個股分析全部免費開放,不需信用卡。升級與否不影響你看到的任何內容。",
            # 反向語序也要驗:付費字眼在前、個股字眼在後但分屬兩句(句界要兩個方向都咬得住)
            "歡迎升級成為支持者。個股分析與進出場價一律免費開放。",
            # 真實線上英文文案(2026-08-04 取自 docs/index.html):不可誤咬
            "Free for a limited time; subscribe now and stay free forever when paid plans return.",
            "Enter the code a friend gave you — unlock the daily briefing free.",
            "TW stocks at 7AM, US stocks at 8PM — with a buy / hold / sell call for each stock.",
        ],
    },
    {
        "id": "md_analysis_teaser",
        "title": "個股內容分層遮蔽(摘要版/完整版)",
        "law": "投信投顧法 §4;COMPLIANCE_STRUCTURE.md 永久規則 4",
        "why": "橋頭案的可罰型態就是「免費看一半、付費看全文」。個股內容的免費必須完整,"
               "不得遮蔽段落或分成摘要版/完整版。",
        "severity": CRITICAL,
        "packs": ["marketdaily"],
        "kind": "forbidden",
        "patterns": [r"完整版[^。\n]{0,12}(需|請|才|要)?\s*(付費|訂閱|升級|贊助)",
                     r"(付費|訂閱|升級|贊助)[^。\n]{0,12}(看|讀|解鎖)\s*完整",
                     r"僅顯示部分[^。\n]{0,10}(分析|建議|內容)",
                     r"(其餘|其他)內容[^。\n]{0,10}(需|請|才|要)?\s*(付費|訂閱|升級|成為贊助|成為支持)",
                     r"閱讀全文[^。\n]{0,8}(付費|訂閱|升級)",
                     r"(?i)(read|see) the full [a-z ]{0,16}(analysis|report)[^.\n]{0,20}(subscrib|upgrad|paid)"],
        "positives": [
            "本段僅顯示部分分析,付費後看完整內容",
            "這一段先給你看前三行,其餘內容需成為贊助者",
            "免費版只給摘要,完整版需訂閱",
            "Read the full analysis — upgrade to see it all",
        ],
        "negatives": ["完整版日報每天早上 7 點寄出,全部免費。", "訂閱後每天收到完整內容,不需付費。",
                      "Subscribe free to get the full daily briefing."],
    },
    # ── 全面免費化口徑(2026-07-09 用戶指令) ────────────────────────────
    {
        "id": "md_future_charge_wording",
        "title": "「恢復收費」缺既有訂戶保障口徑",
        "law": "2026-07-09 Delvin 親令(全面免費化+早鳥口徑);投顧法連動",
        "why": "唯一對外口徑=「限時免費+早鳥鎖定」。單獨出現「恢復收費」而沒有"
               "「既有用戶永久保留免費」這半句,就變成「現在免費、以後分析要付錢」——"
               "那正是把分析內容與付費連結的暗示。",
        "severity": HIGH,
        "packs": ["marketdaily"],
        "kind": "context_required",
        # ⚠️ 只抓**陳述句**。「Will you charge later?」是 FAQ 的問句標題,不是宣稱;
        #    把問句當 trigger 會讓保障承諾(在答案裡,常隔 200+ 字)永遠落在視窗外(2026-08-04 首跑校準)。
        "trigger": r"(?i)恢復收費|開始收費|\b(start charging|paid plans (will )?return)\b",
        # guard 抓的是「有沒有給既有訂戶的保障承諾」這個**語意**,不是特定兩個字。
        # 2026-08-04 兩次校準:①vs-chatgpt footer 寫「永久保留免費使用權」沒有「早鳥」二字
        # ②terms.html 寫「在此之前註冊的用戶保留免費使用權」連「永久」也沒有——兩者實質全合規。
        "guard": (r"(?i)早鳥|(永久)?保留[^。\n]{0,6}免費|仍(然)?(永久)?免費|不受影響|"
                  r"既有用戶[^。\n]{0,8}免費|之前註冊[^。\n]{0,10}免費|"
                  r"(stay free forever|free forever|early[- ]?(bird|subscriber)s?|"
                  r"keep[^.\n]{0,30}free|free access (forever|permanently)|remain(s)? free|"
                  r"registered before[^.\n]{0,40}keep)"),
        # 英文一句話比中文長得多:terms.html 的保障承諾距 trigger 約 100 字元
        "window": 160,
        "positives": [
            "本服務將於下季恢復收費,請把握時間。",
            "我們預計明年開始收費,屆時所有功能將調整為付費制。",
            "We will start charging next quarter for all features.",
        ],
        "negatives": [
            "未來會恢復收費,但現在訂閱的早鳥用戶永久保留免費使用權——恢復收費只影響之後的新用戶。",
            "現在訂閱的早鳥用戶,未來恢復收費後仍永久免費。",
            "完全免費,不需信用卡;現在訂閱,未來恢復收費後永久保留免費使用權。",
            "未來若恢復收費,會提前公告,且在此之前註冊的用戶保留免費使用權。",
            "Free for a limited time; subscribe now and stay free forever when paid plans return.",
            # 2026-08-04 生產首跑補校準:五個頁面的真實英文文案(全部實質合規)
            "Subscribe now and keep full free access forever, even after paid plans return.",
            "If paid plans return in the future, early-bird subscribers keep free access permanently.",
            "Paid plans will return, but early subscribers keep full free access forever — future pricing only affects new users.",
            "If paid plans return in the future, we'll announce it in advance, and users who registered before then keep free access.",
        ],
    },
    {
        "id": "md_price_tag",
        "title": "MarketDaily 出現我方訂閱收費價",
        "law": "2026-07-09 全面免費化(Stripe 金流已下架);公平法 §21(標價與實收不符)",
        "why": "全站零收費,任何我方方案月費/年費數字都是錯的(可能是舊 pricing 卡片復活)。"
               "競品價格(ChatGPT Plus NT$640/月)是比較不是我方標價,不在此列。",
        "severity": HIGH,
        "packs": ["marketdaily"],
        "kind": "proximity",
        "a": [r"我們的方案", r"訂閱方案", r"Premium\s*方案", r"支持者方案", r"升級費用", r"本方案",
              r"方案\s*[A-Z]\b", r"訂閱費", r"會員費"],
        "b": [r"NT\$\s*[1-9]\d*", r"US\$\s*[1-9]\d*", r"每月\s*[1-9]\d*\s*元",
              r"每年\s*[1-9]\d*\s*元", r"[1-9]\d*\s*元\s*/\s*(月|年)"],
        "window": 40,
        "positives": [
            "訂閱方案 NT$299 起,隨時可取消",
            "方案 A 每月 299 元,方案 B 每年 2990 元",
            "支持者方案 NT$149,支持我們繼續做下去",
        ],
        "negatives": [
            "ChatGPT Plus US$20/月 ≈ NT$640。MarketDaily 目前完全免費。",
            "現在全功能限時免費開放 NT$0,不需信用卡。",
            "所有方案統一上限 80 檔,與付費無關。",
        ],
    },
    {
        "id": "md_pro_plan_name",
        "title": "已下架方案名稱復活(Pro/專業版)",
        "law": "project_marketdaily_payments(只剩 Premium,不可再提 Pro);全面免費化",
        "why": "「Pro 方案」是更早期的名稱,任何頁面再出現代表舊模板/舊文案被復原,"
               "同一次復原通常會把付費閘門文案一起帶回來。",
        "severity": MEDIUM,
        "packs": ["marketdaily"],
        "kind": "forbidden",
        "patterns": [r"Pro\s*方案", r"專業版方案", r"升級\s*(成|到|為)?\s*Pro\b", r"Pro\s*會員",
                     r"(?i)\bupgrade to pro\b"],
        "positives": ["升級到 Pro 享有更多功能", "Pro 方案每月 299 元", "成為 Pro 會員解鎖更多"],
        "negatives": ["ui-pro.js 是共用 UI 強化層。", "MarketDaily Pro Max 這個詞我們沒有用過。"],
    },
    # ── 內容誠實(法務部檢查表 §2) ──────────────────────────────────────
    {
        "id": "md_fabricated_stats",
        "title": "行銷頁硬編未經查證的數字",
        "law": "公平法 §21(不實廣告);project_blog_seo_fabricated_numbers、"
               "social_posts 地雷(「75+ 來源」「勝率 75.5%」)",
        "why": "戰績數字唯一合法來源=公版可查證的對帳表(track-record)。行銷頁上寫死一個"
               "勝率或來源數,等於對績效做無法舉證的表示;2026-05-26 那批 caption 就是這樣出包。",
        "severity": HIGH,
        "packs": ["marketdaily_marketing"],
        "kind": "forbidden",
        "patterns": [r"(勝率|命中率|準確率|正確率)\s*(高達|達|約)?\s*\d{1,3}(\.\d+)?\s*(%|成)",
                     r"\d{2,}\s*\+?\s*(個|種)?\s*(資料)?來源",
                     r"(已有|超過|突破)\s*\d{3,}\s*(位|名)?\s*(訂閱|用戶|讀者|人)",
                     r"(已幫助|服務(了|過)?)\s*(超過)?\s*\d{3,}\s*(人|位|名)",
                     r"(?i)\b(win[- ]rate|accuracy)\s*(of\s*)?\d{1,3}(\.\d+)?\s*%"],
        "positives": [
            "我們整合 75+ 來源,勝率高達 75.5%,已有 3000 位訂閱者",
            "命中率高達 8 成,已幫助超過 500 人",
            "Our win-rate of 88.8% speaks for itself",
        ],
        "negatives": [
            "方向勝率與避坑勝率全部公開,逐筆可對照紀錄表。",
            "勝率不等於獲利。一個 80% 的東西也可能虧錢。",
            "沒有任何人能保證勝率,我們把錯的也列出來。",
        ],
    },
    {
        "id": "md_fake_testimonial",
        "title": "假見證/捏造用戶",
        "law": "公平法 §21;《薦證廣告處理原則》;project_fake_testimonials_removed",
        "why": "2026 年清過一次假見證(含捏造訂戶「Jason」)。見證頁現行立場是誠實留白,"
               "任何具名感言復活都代表舊素材被還原。",
        "severity": HIGH,
        "packs": ["marketdaily"],
        "kind": "forbidden",
        "patterns": [
            r"「[^」]{8,}」\s*[—–\-]{1,2}\s*[A-Za-z一-龥]{0,4}?(先生|小姐|女士|工程師|老師|投資人)",
            r"[一-龥]{1,4}(先生|小姐|女士)\s*[:：]\s*「[^」]{8,}」",
            r"(真實|用戶|訂閱者)見證\s*[:：]\s*「",
        ],
        "positives": [
            "「用了三個月,報酬率翻倍」——陳先生",
            "陳先生:「用了三個月,報酬率翻倍,強力推薦」",
            "用戶見證:「這是我看過最好的日報」",
        ],
        "negatives": [
            "MarketDaily 目前訂閱者還很少,尚未累積到可公開分享的用戶見證——我們選擇誠實留白。",
            "我聲明本見證為個人真實使用體驗,沒有收受任何形式報酬以換取本見證。",
        ],
    },
    {
        "id": "md_disclaimer_missing",
        "title": "法定聲明層缺件",
        "law": "COMPLIANCE_STRUCTURE.md 第三層(聲明層)",
        "why": "日報與主要頁面 footer 必須一致聲明「AI 生成之一般性資訊整理、非投顧服務、"
               "投資有風險自行判斷」。模板改版把 footer 弄掉時沒有任何東西會叫。",
        "severity": HIGH,
        "packs": ["marketdaily_disclaimer"],
        "kind": "required",
        # ⚠️ 門檻不能低到「一句『示意圖僅供參考』就讓整個聲明層過關」(驗證者 F8b)。
        #    「僅供參考」必須與投資/風險字樣同句共現才算數。
        "patterns": [r"不構成投資建議", r"非證券投資顧問", r"投資[^。\n]{0,6}風險[^。\n]{0,10}自行",
                     r"僅供參考[^。\n]{0,20}(投資|風險)", r"(投資|風險)[^。\n]{0,20}僅供參考",
                     r"(?i)not (investment|financial) advice"],
        "positives": ["本站僅提供產品說明。", "圖表為示意圖,僅供參考。", "This is a product page."],
        "negatives": [
            "以上內容由 AI 整理,僅供參考,不構成投資建議,投資有風險請自行判斷。",
            "本服務非證券投資顧問服務。",
            "General information only — not investment advice.",
        ],
    },
    # ── 命書(公平法,有真金流) ─────────────────────────────────────────
    {
        "id": "ms_scarcity_wording",
        "title": "無計數依據的稀缺/急迫話術、劃線價別名",
        "law": "公平法 §21(§42 罰 5 萬–2500 萬)、§25;"
               "《公平會對於公平交易法第二十一條案件之處理原則》;公處字第098101號(華碩)",
        "why": "「僅剩 N 名」「最後一天」若無真實計數依據即屬引人錯誤;"
               "「原價/市價」是對過去售價的斷言,舉證責任在我們。",
        "severity": HIGH,
        "packs": ["mingshu"],
        "kind": "forbidden",
        "patterns": [r"原價", r"市價", r"市售價", r"僅剩\s*\d+", r"名額有限", r"最後一天",
                     r"錯過不再", r"即將漲價", r"限量\s*\d*\s*(名|份|組)", r"售完為止",
                     r"手刀", r"手速", r"只到今(晚|天)", r"倒數\s*\d+\s*(小時|分鐘)"],
        "positives": [
            "原價 NT$815,結緣價 NT$480,名額有限售完為止",
            "特價只到今晚十二點,手速要快",
            "市價 NT$815,今日結緣價 NT$480",
        ],
        "negatives": [
            "定價 NT$249。特惠結束後恢復定價。",
            "2026/09/01 起 NT$249,現在下單為上線特惠價。",
            "本檔特惠至 8 月 31 日止,截止時刻全站一致。",
        ],
    },
    {
        "id": "ms_medical_claim",
        "title": "命理服務做療效/保證性宣稱",
        "law": "公平法 §21;醫療法 §86(非醫療機構不得為醫療廣告)",
        "why": "命理內容一旦寫成「保證改運/治好/一定會」即為不實或誇大表示;"
               "碰到健康字眼還會踩醫療廣告。",
        "severity": HIGH,
        "packs": ["mingshu"],
        "kind": "forbidden",
        "patterns": [r"保證\s*(改運|轉運|靈驗|準確|發財|成功)", r"百分之百\s*(準|靈)",
                     r"(治好|根治|療效|藥到病除)", r"一定會\s*(發財|中|成功|懷孕|好轉)",
                     r"保證[^。\n]{0,10}(一飛沖天|飛黃騰達|翻身|逆轉)", r"絕對\s*(準確|靈驗|準)"],
        "positives": [
            "保證改運,百分之百準,一定會發財",
            "本命盤解讀保證讓你事業一飛沖天,絕對準確",
            "這帖能根治你的爛桃花,藥到病除",
        ],
        "negatives": [
            "命理為傳統文化參考,結果因人而異,不構成醫療、法律或投資建議。",
            "我們不做任何保證,只把盤面誠實講清楚。",
        ],
    },
]

_COMPILED = {}


def _compile(pat):
    if pat not in _COMPILED:
        _COMPILED[pat] = re.compile(pat)
    return _COMPILED[pat]


def strip_exempt(text, rule=None):
    """把法定聲明句換成**等長空白遮罩**(不是刪除)。回傳 (masked_text, masked_chars)。

    ⭐ 等長是關鍵:刪除會讓句界與偏移量整個位移,證據片段抓錯位置;更糟的是無界 pattern
    刪一大段之後,後面真正的違規就永遠不在語料裡了(2026-08-04 驗證者 F1 的形狀)。
    `required` 類規則刻意不套(它要找的就是護城河本身)。
    """
    masked = 0
    pats = list(GLOBAL_EXEMPT) + list((rule or {}).get("exempt", []))
    for pat in pats:
        def _mask(m):
            nonlocal masked
            masked += len(m.group(0))
            return " " * len(m.group(0))
        text = _compile(pat).sub(_mask, text)
    return text, masked


_SENT_BREAK = "。！？!?\n\r｜|;；"


def _sentence_start(text, pos):
    for i in range(pos - 1, -1, -1):
        if text[i] in _SENT_BREAK:
            return i + 1
    return 0


def _sentence_end(text, pos):
    for i in range(pos, len(text)):
        if text[i] in _SENT_BREAK:
            return i
    return len(text)


def _snippet(text, start, end, pad=35):
    s = max(0, start - pad)
    e = min(len(text), end + pad)
    return re.sub(r"\s+", " ", text[s:e]).strip()


def check_rule(rule, text):
    """回傳 findings(list[dict])。空 list=這條規則在這份語料上乾淨。"""
    kind = rule["kind"]
    # required 規則找的就是法定聲明句本身,套 exempt 會把它遮掉再抱怨它不見(驗證者 F8a)
    body = text if kind == "required" else strip_exempt(text, rule)[0]
    out = []
    if kind == "forbidden":
        for pat in rule["patterns"]:
            for m in _compile(pat).finditer(body):
                out.append({"pattern": pat, "evidence": _snippet(body, m.start(), m.end())})
                break  # 同一條 pattern 只報一次,不然一頁 42 次「見證」會刷爆報告
    elif kind == "proximity":
        # ⚠️ 視窗**不得跨句**。對價關係是「同一句話裡把付費與個股綁在一起」;
        #    跨句共現是誤報大宗——實測負例「個股分析全部免費開放。升級與否不影響你看到的
        #    任何內容。」兩個關鍵字距離只有 20 字,但分屬兩句、語意完全相反(2026-08-04 校準)。
        for pa in rule["a"]:
            for ma in _compile(pa).finditer(body):
                lo = max(_sentence_start(body, ma.start()), ma.start() - rule["window"])
                hi = min(_sentence_end(body, ma.end()), ma.end() + rule["window"])
                seg = body[lo:hi]
                for pb in rule["b"]:
                    if _compile(pb).search(seg):
                        out.append({"pattern": f"{pa} ×{rule['window']}字內同句× {pb}",
                                    "evidence": _snippet(body, ma.start(), ma.end())})
                        return out
    elif kind == "context_required":
        g = _compile(rule["guard"])
        for m in _compile(rule["trigger"]).finditer(body):
            lo = max(0, m.start() - rule["window"])
            hi = min(len(body), m.end() + rule["window"])
            if not g.search(body[lo:hi]):
                out.append({"pattern": f"{rule['trigger'][:30]} 缺保障口徑(±{rule['window']}字)",
                            "evidence": _snippet(body, m.start(), m.end(), pad=60)})
                return out
    elif kind == "required":
        if not any(_compile(p).search(body) for p in rule["patterns"]):
            out.append({"pattern": "以上皆未出現:" + " | ".join(rule["patterns"][:3]) + " …",
                        "evidence": "(整份語料找不到任何法定聲明字樣)"})
    else:
        raise ValueError(f"未知規則種類 {kind}(規則 {rule['id']})")
    return out


def selfcheck():
    """逐條驗規則自己還活著。回傳 (ok: bool, problems: list[str])。

    ⭐ 這是整份規則庫最重要的一段:沒有它,一個 regex 打錯字就會讓該條規則從此永遠
    零命中,而輸出長得跟「全站乾淨」一模一樣。掃描器每次跑都會先呼叫它。
    """
    problems = []
    seen = set()
    for pat in GLOBAL_EXEMPT:
        if _UNBOUNDED.search(pat):
            problems.append(f"GLOBAL_EXEMPT 有無界量詞(會吃掉整頁語料):{pat}")
        long_tail = _LONG_TAIL.search(pat)
        if long_tail and int(long_tail.group(1)) > 12:
            problems.append(f"GLOBAL_EXEMPT 尾巴 {long_tail.group(0)} 太長(藏得下一條違規):{pat}")
        try:
            re.compile(pat)
        except Exception as e:
            problems.append(f"GLOBAL_EXEMPT 壞掉 {pat}:{e!r}")
    # 每條樣本都必須真的被自己的 pattern 遮到(否則護城河句會咬自己)
    for sample in EXEMPT_SAMPLES:
        if strip_exempt(sample)[1] == 0:
            problems.append(f"GLOBAL_EXEMPT 樣本沒有被任何 pattern 遮到(白名單與文案漂移):{sample[:30]}")
    for r in RULES:
        rid = r["id"]
        if rid in seen:
            problems.append(f"{rid}: 規則 id 重複")
        seen.add(rid)
        for field in ("title", "law", "why", "severity", "packs", "kind", "positives", "negatives"):
            if not r.get(field):
                problems.append(f"{rid}: 缺欄位 {field}")
        if r.get("severity") not in (CRITICAL, HIGH, MEDIUM):
            problems.append(f"{rid}: severity 非法 {r.get('severity')!r}")
        pos = r.get("positives") or []
        if len(pos) < 3:
            problems.append(f"{rid}: positives 只有 {len(pos)} 個(召回率無防線,至少 3 個不同措辭)")
        for p in pos:
            try:
                if not check_rule(r, p):
                    problems.append(f"{rid}: 正例沒有被咬到(規則已死或措辭沒覆蓋):{p[:40]}")
            except Exception as e:
                problems.append(f"{rid}: 正例比對爆炸 {e!r}")
            # ⭐ F1 的直接反例:護城河句貼在違規正前面時,遮罩不可以把違規一起吃掉。
            #    required 類找的就是護城河本身,不適用(它不套 exempt)。
            if r["kind"] != "required":
                for sample in EXEMPT_SAMPLES:
                    probe = f"{sample},{p}"
                    try:
                        if not check_rule(r, probe):
                            problems.append(f"{rid}: 法定聲明句遮罩吃掉了緊接其後的違規"
                                            f"(exempt 尾巴太貪心):{probe[:50]}")
                            break
                    except Exception as e:
                        problems.append(f"{rid}: exempt 遮罩探針爆炸 {e!r}")
                        break
        for neg in r.get("negatives", []):
            try:
                hits = check_rule(r, neg)
            except Exception as e:
                problems.append(f"{rid}: 負例比對爆炸 {e!r}")
                continue
            if hits:
                problems.append(f"{rid}: 真實文案負例被誤咬 → {hits[0]['evidence'][:60]}")
    return (not problems), problems


def rules_for(packs, exclude=()):
    packs = set(packs)
    return [r for r in RULES if (packs & set(r["packs"])) and r["id"] not in set(exclude)]

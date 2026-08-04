"""法務部規則庫(2026-08-04)——對外文案的法規紅線,寫成可執行的判準。

**為什麼要有這一份**:公司已有的合規防線全部是「產出前」的閘門
(`fortune-ai/tests/node/pricing.test.mjs` 管價格、`marketing/post_gate.py` 管社群 caption、
日報 audit 管日報內容)。但**線上生產頁面在 deploy 之後沒有任何東西看過**——任何視窗或
agent 改了 `docs/` 直接 `wrangler pages deploy` 就繞過全部閘門,而罰則是真的錢
(公平法 §42:5 萬–2500 萬;投顧法 §107:2 年 2 月有期徒刑+沒收,橋頭 111 金訴 235 實例)。

**設計三原則**:
1. **每條規則綁一個真實事故或明文法源**——沒有出處的規則不准進來。憑感覺加的紅線
   會製造誤報,誤報會養出「反正都紅的」警報疲勞,最後連真的違規也沒人看
   (同 `intel/doctor.py` 首版誤報 4 個健康渠道的教訓)。
2. **每條規則自帶 `positive`(必須咬)與 `negatives`(取自真實線上文案,必須不咬)**。
   `selfcheck()` 會逐條驗——**規則自己壞掉(regex 打錯、關鍵字被改)時,掃描結果會從
   「全站乾淨」變成「規則庫紅了」**。這是 2026-08-04 突變 harness 學到的通則:
   「零覆蓋率」與「全數通過」在輸出上長得一樣的地方,一定要有命中計數器。
3. **`exempt` 先行**——法定聲明句本身就含違規關鍵字(例:「所有投資分析內容對免費與
   付費用戶完全相同」同時含「付費」與「分析」)。這些句子是**防線本身**,必須先從語料
   移除再比對,否則規則會咬自己的護城河。

規則種類:
  forbidden        任一 pattern 命中即違規
  proximity        a 群與 b 群關鍵字在 window 字元內共現即違規(對價關係型)
  context_required trigger 命中時,window 內必須有 guard,否則違規(強制口徑型)
  required         整份語料至少要出現一次,沒有即違規(法定聲明缺件型)
"""
import re

CRITICAL, HIGH, MEDIUM = "critical", "high", "medium"

# 法定聲明/口徑句:本身含紅線關鍵字但正是防線,比對前一律先挖掉。
# ⚠️ 只准放「我們自己寫死、且有法規理由必須這樣寫」的句子,不准拿來消音真違規。
GLOBAL_EXEMPT = [
    r"所有投資分析內容對免費與付費用戶完全相同[^。]*",
    r"Premium\s*不包含任何個股分析或投資建議內容",
    r"內容不因付費而異",
    r"非證券投資顧問服務",
]

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
        "a": [r"升級", r"解鎖", r"付費方案", r"訂閱方案", r"加入會員", r"Premium", r"專業版", r"付費用戶專屬"],
        "b": [r"個股", r"選股", r"持股分析", r"買賣時點", r"進出場價", r"投資建議", r"個別股票"],
        "window": 30,
        "positive": "立即升級 Premium 解鎖完整個股分析與進出場價",
        "negatives": [
            "所有投資分析內容對免費與付費用戶完全相同,Premium 不包含任何個股分析或投資建議內容。",
            "個股分析全部免費開放,不需信用卡。升級與否不影響你看到的任何內容。",
            # 反向語序也要驗:付費字眼在前、個股字眼在後但分屬兩句(句界要兩個方向都咬得住)
            "歡迎升級成為支持者。個股分析與進出場價一律免費開放。",
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
        "patterns": [r"完整版[^。]{0,12}(需|請)?(付費|訂閱|升級)", r"(付費|訂閱|升級)[^。]{0,12}看完整",
                     r"僅顯示部分[^。]{0,10}(分析|建議)", r"閱讀全文[^。]{0,8}(付費|訂閱)"],
        "positive": "本段僅顯示部分分析,付費後看完整內容",
        "negatives": ["完整版日報每天早上 7 點寄出,全部免費。", "訂閱後每天收到完整內容,不需付費。"],
    },
    # ── 全面免費化口徑(2026-07-09 用戶指令) ────────────────────────────
    {
        "id": "md_future_charge_wording",
        "title": "「恢復收費」缺早鳥保障口徑",
        "law": "2026-07-09 Delvin 親令(全面免費化+早鳥口徑);投顧法連動",
        "why": "唯一對外口徑=「限時免費+早鳥鎖定」。單獨出現「恢復收費」而沒有"
               "「早鳥永久保留免費」這半句,就變成「現在免費、以後分析要付錢」——"
               "那正是把分析內容與付費連結的暗示。",
        "severity": HIGH,
        "packs": ["marketdaily"],
        "kind": "context_required",
        "trigger": r"恢復收費",
        # guard 要抓的是「有沒有給既有訂戶的保障承諾」這個**語意**,不是「早鳥」這兩個字。
        # 2026-08-04 首跑校準:vs-chatgpt.html footer 寫「現在訂閱,未來恢復收費後永久保留
        # 免費使用權」——實質完全合規卻沒有「早鳥」二字,只認關鍵字會製造誤報。
        "guard": r"早鳥|永久保留免費|永久免費|仍永久免費|不受影響",
        "window": 80,
        "positive": "本服務將於下季恢復收費,請把握時間。",
        "negatives": [
            "未來會恢復收費,但現在訂閱的早鳥用戶永久保留免費使用權——恢復收費只影響之後的新用戶。",
            "現在訂閱的早鳥用戶,未來恢復收費後仍永久免費。",
            "完全免費,不需信用卡;現在訂閱,未來恢復收費後永久保留免費使用權。",
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
        "a": [r"我們的方案", r"訂閱方案", r"Premium\s*方案", r"支持者方案", r"升級費用", r"本方案"],
        "b": [r"NT\$\s*[1-9]\d*", r"US\$\s*[1-9]\d*", r"每月\s*[1-9]\d*\s*元", r"[1-9]\d*\s*元\s*/\s*月"],
        "window": 40,
        "positive": "訂閱方案 NT$299 起,隨時可取消",
        "negatives": [
            "ChatGPT Plus US$20/月 ≈ NT$640。MarketDaily 目前完全免費。",
            "現在全功能限時免費開放 NT$0,不需信用卡。",
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
        "patterns": [r"Pro\s*方案", r"專業版方案", r"升級\s*(成|到|為)?\s*Pro\b", r"Pro\s*會員"],
        "positive": "升級到 Pro 享有更多功能",
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
        "patterns": [r"勝率\s*(高達|達)?\s*\d{1,3}(\.\d+)?\s*%", r"\d{2,}\s*\+?\s*(個|種)?\s*(資料)?來源",
                     r"已有\s*\d{3,}\s*(位|名)\s*(訂閱|用戶|讀者)"],
        "positive": "我們整合 75+ 來源,勝率高達 75.5%,已有 3000 位訂閱者",
        "negatives": [
            "方向勝率與避坑勝率全部公開,逐筆可對照紀錄表。",
            "勝率不等於獲利。一個 80% 的東西也可能虧錢。",
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
        "patterns": [r"「[^」]{8,}」\s*[—–\-]{1,2}\s*[A-Za-z一-龥]{0,4}?(先生|小姐|女士|工程師|老師|投資人)",
                     r"(真實|用戶|訂閱者)見證\s*[:：]\s*「"],
        "positive": "「用了三個月,報酬率翻倍」——陳先生",
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
        "patterns": [r"不構成投資建議", r"非證券投資顧問", r"投資[^。]{0,6}風險[^。]{0,10}自行", r"僅供參考"],
        "positive": "本站僅提供產品說明。",   # 沒有任何聲明字樣 → 必須咬
        "negatives": ["以上內容由 AI 整理,僅供參考,不構成投資建議,投資有風險請自行判斷。"],
    },
    # ── 命書(公平法,有真金流) ─────────────────────────────────────────
    {
        "id": "ms_scarcity_wording",
        "title": "無計數依據的稀缺/急迫話術",
        "law": "公平法 §21(§42 罰 5 萬–2500 萬)、§25;"
               "《公平會對於公平交易法第二十一條案件之處理原則》",
        "why": "「僅剩 N 名」「最後一天」若無真實計數依據即屬引人錯誤;"
               "「原價」是對過去售價的斷言,舉證責任在我們(公處字 098101 華碩案)。",
        "severity": HIGH,
        "packs": ["mingshu"],
        "kind": "forbidden",
        "patterns": [r"原價", r"僅剩\s*\d+", r"名額有限", r"最後一天", r"錯過不再",
                     r"即將漲價", r"限量\s*\d*\s*(名|份|組)", r"售完為止", r"手刀"],
        "positive": "原價 NT$815,結緣價 NT$480,名額有限售完為止",
        "negatives": [
            "定價 NT$249。特惠結束後恢復定價。",
            "2026/09/01 起 NT$249,現在下單為上線特惠價。",
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
                     r"(治好|根治|療效|藥到病除)", r"一定會\s*(發財|中|成功|懷孕)"],
        "positive": "保證改運,百分之百準,一定會發財",
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


def _strip_exempt(text, rule):
    for pat in GLOBAL_EXEMPT + list(rule.get("exempt", [])):
        text = _compile(pat).sub(" ", text)
    return text


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
    body = _strip_exempt(text, rule)
    kind = rule["kind"]
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
                    mb = _compile(pb).search(seg)
                    if mb:
                        out.append({"pattern": f"{pa} ×{rule['window']}字內× {pb}",
                                    "evidence": _snippet(body, ma.start(), ma.end())})
                        return out
    elif kind == "context_required":
        g = _compile(rule["guard"])
        for m in _compile(rule["trigger"]).finditer(body):
            lo = max(0, m.start() - rule["window"])
            hi = min(len(body), m.end() + rule["window"])
            if not g.search(body[lo:hi]):
                out.append({"pattern": f"{rule['trigger']} 缺 {rule['guard']}(±{rule['window']}字)",
                            "evidence": _snippet(body, m.start(), m.end(), pad=60)})
                return out
    elif kind == "required":
        if not any(_compile(p).search(body) for p in rule["patterns"]):
            out.append({"pattern": "以上皆未出現:" + " | ".join(rule["patterns"]),
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
    for r in RULES:
        rid = r["id"]
        if rid in seen:
            problems.append(f"{rid}: 規則 id 重複")
        seen.add(rid)
        for field in ("title", "law", "why", "severity", "packs", "kind", "positive", "negatives"):
            if not r.get(field):
                problems.append(f"{rid}: 缺欄位 {field}")
        if r.get("severity") not in (CRITICAL, HIGH, MEDIUM):
            problems.append(f"{rid}: severity 非法 {r.get('severity')!r}")
        try:
            if not check_rule(r, r["positive"]):
                problems.append(f"{rid}: positive 正例沒有被咬到(規則已死)")
        except Exception as e:  # regex 壞掉
            problems.append(f"{rid}: positive 比對爆炸 {e!r}")
        for neg in r.get("negatives", []):
            try:
                hits = check_rule(r, neg)
            except Exception as e:
                problems.append(f"{rid}: negative 比對爆炸 {e!r}")
                continue
            if hits:
                problems.append(f"{rid}: 真實文案負例被誤咬 → {hits[0]['evidence'][:60]}")
    return (not problems), problems


def rules_for(packs, exclude=()):
    packs = set(packs)
    return [r for r in RULES if (packs & set(r["packs"])) and r["id"] not in set(exclude)]

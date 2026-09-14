"""newsroom 自測。

每條測試都對著「災難」寫,不是對著「變化」寫:
問的是「這個閘門擋不住時會發生什麼壞事」,不是「輸出有沒有變」。
"""
import json
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from marketing.newsroom import gates, rank, draft as D, sources, formats  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(f"  {'✅' if cond else '❌'} {name}" + (f" — {detail}" if not cond and detail else ""))
    if not cond:
        FAILS.append(name)


FACTS = {"title": "OpenAI rules out IPO this year",
         "summary": "Sam Altman said the company will not file in 2026.",
         "source_url": "https://example.com/a", "source_name": "CNBC",
         "also_reported_by": ["Engadget"], "lane": "money", "hours_old": 3,
         "article_excerpt": "Altman said an IPO is not planned for this year."}


def good_draft():
    d = {"headline": "OpenAI rules out an IPO this year",
         "caption": "OpenAI says it will not go public this year.",
         "threads_caption": "OpenAI 說今年不會上市。",
         "source_url": FACTS["source_url"]}
    return D.decorate(d, FACTS)


print("== 閘門必須放行乾淨稿 ==")
ok, why = gates.check(good_draft(), FACTS, D.BRAND)
check("乾淨稿放行", ok, str(why))

print("== 閘門必須擋住這些(擋不住就會真的出事) ==")
d = good_draft(); d["caption"] = d["caption"].replace("this year", "and 42,000 employees left")
ok, why = gates.check(d, FACTS, D.BRAND)
check("捏造數字被擋", not ok and any("沒有的數字" in w for w in why), str(why))

d = good_draft(); d["caption"] += "\n\nGreat time to buy now."
ok, why = gates.check(d, FACTS, D.BRAND)
check("操作字眼被擋", not ok and any("禁詞" in w for w in why), str(why))

d = good_draft(); d["source_url"] = "https://evil.example/made-up"
ok, why = gates.check(d, FACTS, D.BRAND)
check("模型自己換來源被擋", not ok and any("source_url" in w for w in why), str(why))

d = good_draft(); d["caption"] += "\n\nvia @some_random_person"
ok, why = gates.check(d, FACTS, D.BRAND)
check("白名單外的 @handle 被擋", not ok and any("白名單" in w for w in why), str(why))

scandal = {**FACTS, "title": "OpenAI sued over copyright", "summary": "A lawsuit was filed."}
d = {"headline": "h", "caption": "c", "threads_caption": "t", "source_url": FACTS["source_url"]}
d = D.decorate(d, scandal); d["caption"] += " @openai"
ok, why = gates.check(d, scandal, D.BRAND)
check("醜聞題材不得 tag 當事人", not ok and any("負面題材" in w for w in why), str(why))

d = good_draft(); d["caption"] = d["caption"].replace(f"@{D.BRAND['handle']}", "us")
ok, why = gates.check(d, FACTS, D.BRAND)
check("少了品牌 CTA 被擋", not ok and any("CTA" in w for w in why), str(why))

d = good_draft(); d["threads_caption"] = "x " + "#tag " * 5
ok, why = gates.check(d, FACTS, D.BRAND)
check("Threads 版塞滿 hashtag 被擋", not ok and any("threads_caption hashtag" in w for w in why), str(why))

d = good_draft(); d["caption"] = "x" * 2400 + f" @{D.BRAND['handle']} #a #b #c"
ok, why = gates.check(d, FACTS, D.BRAND)
check("超長被擋", not ok and any("超長" in w for w in why), str(why))

print("== Threads 串 ==")
def _chain(segs, facts=FACTS):
    d = {"headline": "h", "caption": "c", "threads_caption": "中文說明。",
         "source_url": facts["source_url"], "threads_chain": list(segs)}
    return D.decorate(d, facts)

_c = _chain(["鉤子這一句", "第二件事", "第三件事,你怎麼看?"])
ok, why = gates.check(_c, FACTS, D.BRAND)
check("乾淨的串放行", ok, str(why))
check("handle 自動補在最後一段且只有一次",
      _c["threads_chain"][-1].endswith(f"@{D.BRAND['handle']}")
      and "\n".join(_c["threads_chain"]).count(f"@{D.BRAND['handle']}") == 1)

_c = _chain(["只有一段"])
ok, why = gates.check(_c, FACTS, D.BRAND)
check("單段不成串被擋", not ok and any("段數" in w for w in why), str(why))

_c = _chain(["甲", "乙", "丙"]); _c["threads_chain"][0] += f" @{D.BRAND['handle']}"
ok, why = gates.check(_c, FACTS, D.BRAND)
check("每段都掛 handle(在自己串裡洗名字)被擋",
      not ok and any("handle 出現" in w for w in why), str(why))

_c = _chain(["甲", "乙", "丙 #ai #tech"])
ok, why = gates.check(_c, FACTS, D.BRAND)
check("串裡塞 hashtag 被擋", not ok and any("不該有 hashtag" in w for w in why), str(why))

_c = _chain(["甲", "文" * 520, "丙"])
ok, why = gates.check(_c, FACTS, D.BRAND)
check("串的單段超長被擋", not ok and any("超長" in w for w in why), str(why))

_c = _chain(["甲", "營收跳到 4,200 台", "丙"])
ok, why = gates.check(_c, FACTS, D.BRAND)
check("串裡的捏造數字一樣被擋(閘門不能只看 caption)",
      not ok and any("threads_chain" in w and "沒有的數字" in w for w in why), str(why))

_c = _chain(["甲", "看這裡 https://spam.example/x", "丙"])
ok, why = gates.check(_c, FACTS, D.BRAND)
check("串裡夾帶外部網址被擋", not ok and any("以外的網址" in w for w in why), str(why))

_lfx = formats.listicle_facts("t") if False else None
print("== 中文閘(Threads 是中文,IG 是英文) ==")
_B = dict(D.BRAND)
def _zh(seg_list, cap_zh="這是一段正常的中文說明。"):
    d = {"headline": "h", "caption": "c", "threads_caption": cap_zh,
         "source_url": FACTS["source_url"], "threads_chain": list(seg_list)}
    return D.decorate(d, FACTS)

_ok, _why = gates.check(_zh(["第一段鉤子。", "第二段說明。", "第三段收尾,你怎麼看？"]), FACTS, _B)
check("乾淨的繁體中文串放行", _ok, str(_why))

_ok, _why = gates.check(_zh(["这是简体字。", "第二段。", "第三段？"]), FACTS, _B)
check("簡體字被擋", not _ok and any("簡體字" in w for w in _why), str(_why))

_ok, _why = gates.check(_zh(["這個視頻很好看。", "第二段。", "第三段？"]), FACTS, _B)
check("⭐用繁體字寫的中國用語「視頻」被擋(簡繁檢查看不見這種)",
      not _ok and any("中國用語" in w and "視頻" in w for w in _why), str(_why))

_ok, _why = gates.check(_zh(["這顆芯片用了新的算法。", "第二段。", "第三段？"]), FACTS, _B)
check("「芯片」「算法」兩個中國用語都被點名",
      not _ok and sum(1 for w in _why if "中國用語" in w) >= 2, str(_why))

_ok, _why = gates.check(_zh(["首先我們來看這件事。", "第二段。", "第三段？"]), FACTS, _B)
check("書面語起手式「首先」被擋", not _ok and any("起手式" in w for w in _why), str(_why))

_ok, _why = gates.check(_zh(["This is English.", "第二段。", "第三段？"]), FACTS, _B)
check("該中文的欄位整段是英文被擋", not _ok and any("沒有中文字" in w for w in _why), str(_why))

_en = dict(_B); _en["lang"] = {"threads": "en"}
_ok, _why = gates.check(_zh(["首先 this is English 視頻", "b", "c？"]), FACTS, _en)
check("Threads 設定成英文時不跑中文閘(語言是設定不是硬編)",
      _ok or not any(("中國用語" in w or "起手式" in w) for w in _why), str(_why))

_ok, _why = gates.check(_zh(["第一段。", "第二段。", "第三段？"],
                            cap_zh="這個軟件不錯。"), FACTS, _B)
check("threads_caption 也要過中文閘(不能只守串)",
      not _ok and any("threads_caption" in w and "中國用語" in w for w in _why), str(_why))

check("台灣正當用法不該被誤殺(程序正義/雲端/後台/裡面)",
      not gates.check_chinese("法律程序、雲端服務、後台、裡面都是台灣正當用法。", "x"),
      str(gates.check_chinese("法律程序、雲端服務、後台、裡面都是台灣正當用法。", "x")))

print("== 是不是新聞閘(這是世界新聞帳號,不是 AI 帳號) ==")
check("通訊社的國際新聞放行",
      rank.is_news({"title": "Six dead, 130 missing after Indonesian ferry capsizes", "wire": True}))
check("通訊社的評論也要擋(feed 會混評論)",
      not rank.is_news({"title": "Opinion: why the ferry disaster was avoidable", "wire": True}))
check("教學型內容被擋(老闆點名:不要介紹 AI 是什麼)",
      not rank.is_news({"title": "How to use ChatGPT to plan your week", "wire": False}))
check("清單型內容被擋",
      not rank.is_news({"title": "7 best AI tools you should try", "wire": False}))
check("服務性問句標題被擋(非通訊社)",
      not rank.is_news({"title": "Should you buy a heat pump this winter?", "wire": False}))
check("科技新聞仍是新聞(AI 是一條線不是禁區)",
      rank.is_news({"title": "OpenAI rules out IPO this year", "wire": False}))

print("== 題材線分類 ==")
check("災難進 breaking",
      rank.classify({"title": "Six dead, 130 missing after ferry capsizes", "summary": ""})[0] == "breaking")
check("選舉進 politics",
      rank.classify({"title": "Election in Sweden Is Too Close to Call", "summary": ""})[0] == "politics")
check("⭐短關鍵字要字邊界:Britain 裡的 ai 不該讓政治新聞掉進 tech 線",
      rank.classify({"title": "Britain said it would again review the plan", "summary": ""})[0] != "tech",
      rank.classify({"title": "Britain said it would again review the plan", "summary": ""})[0])
check("真的 AI 新聞才進 tech",
      rank.classify({"title": "OpenAI launches new AI model", "summary": ""})[0] == "tech")

print("== 加速度:蹭流量看的是還在不在加速,不是有多少家報 ==")
_hot = {"confluence": 5, "age_h": 0.3}
_cold = {"confluence": 6, "age_h": 22.0}
check("五家在 18 分鐘內發,排在六家但 22 小時前的前面",
      rank.velocity(_hot) > rank.velocity(_cold),
      f"hot={rank.velocity(_hot):.1f} cold={rank.velocity(_cold):.1f}")
check("剛發布不會讓速度爆掉(0.5h 下限)",
      rank.velocity({"confluence": 1, "age_h": 0.0}) <= 2.0)

print("== 聚類:同一則不同寫法要合併 ==")
import datetime  # noqa: E402
now = datetime.datetime.now(datetime.timezone.utc)


class _FakeFeed:
    pass


ks1 = sources._keyset("OpenAI rules out IPO this year as Altman warns AI is moving too fast")
ks2 = sources._keyset("Sam Altman says OpenAI won't file for IPO this year")
inter = len(ks1 & ks2)
smaller = min(len(ks1), len(ks2))
check("IPO 兩種寫法會被判為同一則", inter >= 3 and inter / smaller >= 0.5,
      f"inter={inter} smaller={smaller}")
ks3 = sources._keyset("Google DeepMind releases a weather forecasting model")
inter2 = len(ks1 & ks3)
check("不相干的兩則不會被硬湊在一起", not (inter2 >= 3 and inter2 / min(len(ks1), len(ks3)) >= 0.5),
      f"inter={inter2}")

print("== 品牌字串沒有硬編在程式裡(改名只改 brand.json) ==")
src = "".join((ROOT := pathlib.Path(__file__).resolve().parent).joinpath(f).read_text()
              for f in ("rank.py", "gates.py", "run.py", "sources.py"))
check("rank/gates/run/sources 不含硬編品牌名", "marketdaily" not in src.lower(),
      "有檔案硬編了品牌名,改名會漏掉")

print("== 回歸:decorate 不准覆寫 source_url(覆寫會讓第一道閘永遠空轉) ==")
_d = D.decorate({"headline": "h", "caption": "c", "threads_caption": "中文說明。",
                 "source_url": "https://model-made-this-up.example"}, FACTS)
check("模型給的錯網址不會被 decorate 安靜換掉",
      _d["source_url"] == "https://model-made-this-up.example", _d.get("source_url"))
_ok, _why = gates.check(_d, FACTS, D.BRAND)
check("走完整 decorate→gate 流程仍擋得住換來源",
      not _ok and any("source_url" in w for w in _why), str(_why))
_d2 = D.decorate({"headline": "h", "caption": "c", "threads_caption": "中文說明。"}, FACTS)
check("模型沒給 source_url 時由程式補上", _d2["source_url"] == FACTS["source_url"])
_d3 = D.decorate({"headline": "h", "caption": "read more at https://spam.example/x",
                  "threads_caption": "中文說明。"}, FACTS)
_ok, _why = gates.check(_d3, FACTS, D.BRAND)
check("文案內文夾帶外部網址被擋", not _ok and any("以外的網址" in w for w in _why), str(_why))

print("== 清單型沒有外部來源,模型不准自己生一個網址 ==")
lf = formats.listicle_facts("prompts for x")
ld = {"headline": "h", "caption": "c", "threads_caption": "中文說明。", "source_url": None}
ld = D.decorate(ld, lf)
ok, why = gates.check(ld, lf, D.BRAND)
check("清單型無來源可放行", ok, str(why))
ld2 = D.decorate({"headline": "h", "caption": "c", "threads_caption": "中文說明。",
                  "source_url": "https://made-up.example"}, lf)
ok, why = gates.check(ld2, lf, D.BRAND)
check("清單型模型自己生網址被擋", not ok and any("source_url" in w for w in why), str(why))
_lg = D.decorate({"headline": "h", "caption": "Keep each answer under 60 words.",
                  "threads_caption": "每個回答限 60 字。", "items": [{"title": "a", "body": "in 3 bullets"}]}, lf)
_ok, _why = gates.check(_lg, lf, D.BRAND)
check("清單型的指令數字(60 字/3 點)不該被當成捏造數字", _ok, str(_why))
_lb = D.decorate({"headline": "h", "caption": "This saves 87% of your time.",
                  "threads_caption": "中文說明。"}, lf)
_ok, _why = gates.check(_lb, lf, D.BRAND)
check("清單型的統計型宣稱(87%)被擋", not ok if False else (not _ok and any("統計型" in w for w in _why)), str(_why))
_lb2 = D.decorate({"headline": "h", "caption": "c", "threads_caption": "中文說明。",
                   "items": [{"title": "a", "body": "studies show this works"}]}, lf)
_ok, _why = gates.check(_lb2, lf, D.BRAND)
check("清單項目裡的「研究顯示」被擋", not _ok and any("統計型" in w for w in _why), str(_why))
_ns = D.decorate({"headline": "h", "caption": "It rose 87% last quarter.",
                  "threads_caption": "中文說明。"}, FACTS)
_ok, _why = gates.check(_ns, FACTS, D.BRAND)
check("有來源的貼文仍走數字溯源閘(87 不在 facts)",
      not _ok and any("沒有的數字" in w for w in _why), str(_why))
check("清單題目池不重複", len(set(formats.LISTICLE_TOPICS)) == len(formats.LISTICLE_TOPICS))
check("題目輪替不會連兩次同一題",
      formats.pick_topic({"posted": [{"topic": formats.LISTICLE_TOPICS[0]}]}) != formats.LISTICLE_TOPICS[0])

print(f"\n{'✅ 全過' if not FAILS else '❌ 失敗: ' + ', '.join(FAILS)}")
sys.exit(1 if FAILS else 0)

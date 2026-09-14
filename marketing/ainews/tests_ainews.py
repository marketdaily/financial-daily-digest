"""ainews 自測。

每條測試都對著「災難」寫,不是對著「變化」寫:
問的是「這個閘門擋不住時會發生什麼壞事」,不是「輸出有沒有變」。
"""
import json
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from marketing.ainews import gates, rank, draft as D, sources  # noqa: E402

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
         "threads_caption": "OpenAI says no IPO this year.",
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

print("== 相關性閘 ==")
check("通用源的非 AI 新聞被濾掉",
      not rank.is_ai_relevant({"title": "Woman died of measles complications",
                               "summary": "coroner says", "ai_only": False}))
check("ai_only 源夾帶的非 AI 新聞也被濾掉(不准信任來源標籤)",
      not rank.is_ai_relevant({"title": "MIT spinout turns plastic waste into building materials",
                               "summary": "resilient materials", "ai_only": True}))
check("真的 AI 新聞放行",
      rank.is_ai_relevant({"title": "OpenAI launches a new reasoning model",
                           "summary": "", "ai_only": False}))
check("said/air 不該被當成 ai",
      not rank.is_ai_relevant({"title": "He said the air was clean", "summary": "", "ai_only": False}))

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
_d = D.decorate({"headline": "h", "caption": "c", "threads_caption": "t",
                 "source_url": "https://model-made-this-up.example"}, FACTS)
check("模型給的錯網址不會被 decorate 安靜換掉",
      _d["source_url"] == "https://model-made-this-up.example", _d.get("source_url"))
_ok, _why = gates.check(_d, FACTS, D.BRAND)
check("走完整 decorate→gate 流程仍擋得住換來源",
      not _ok and any("source_url" in w for w in _why), str(_why))
_d2 = D.decorate({"headline": "h", "caption": "c", "threads_caption": "t"}, FACTS)
check("模型沒給 source_url 時由程式補上", _d2["source_url"] == FACTS["source_url"])
_d3 = D.decorate({"headline": "h", "caption": "read more at https://spam.example/x",
                  "threads_caption": "t"}, FACTS)
_ok, _why = gates.check(_d3, FACTS, D.BRAND)
check("文案內文夾帶外部網址被擋", not _ok and any("以外的網址" in w for w in _why), str(_why))

print("== 清單型沒有外部來源,模型不准自己生一個網址 ==")
from marketing.ainews import formats  # noqa: E402
lf = formats.listicle_facts("prompts for x")
ld = {"headline": "h", "caption": "c", "threads_caption": "t", "source_url": None}
ld = D.decorate(ld, lf)
ok, why = gates.check(ld, lf, D.BRAND)
check("清單型無來源可放行", ok, str(why))
ld2 = D.decorate({"headline": "h", "caption": "c", "threads_caption": "t",
                  "source_url": "https://made-up.example"}, lf)
ok, why = gates.check(ld2, lf, D.BRAND)
check("清單型模型自己生網址被擋", not ok and any("source_url" in w for w in why), str(why))
_lg = D.decorate({"headline": "h", "caption": "Keep each answer under 60 words.",
                  "threads_caption": "t", "items": [{"title": "a", "body": "in 3 bullets"}]}, lf)
_ok, _why = gates.check(_lg, lf, D.BRAND)
check("清單型的指令數字(60 字/3 點)不該被當成捏造數字", _ok, str(_why))
_lb = D.decorate({"headline": "h", "caption": "This saves 87% of your time.",
                  "threads_caption": "t"}, lf)
_ok, _why = gates.check(_lb, lf, D.BRAND)
check("清單型的統計型宣稱(87%)被擋", not ok if False else (not _ok and any("統計型" in w for w in _why)), str(_why))
_lb2 = D.decorate({"headline": "h", "caption": "c", "threads_caption": "t",
                   "items": [{"title": "a", "body": "studies show this works"}]}, lf)
_ok, _why = gates.check(_lb2, lf, D.BRAND)
check("清單項目裡的「研究顯示」被擋", not _ok and any("統計型" in w for w in _why), str(_why))
_ns = D.decorate({"headline": "h", "caption": "It rose 87% last quarter.",
                  "threads_caption": "t"}, FACTS)
_ok, _why = gates.check(_ns, FACTS, D.BRAND)
check("有來源的貼文仍走數字溯源閘(87 不在 facts)",
      not _ok and any("沒有的數字" in w for w in _why), str(_why))
check("清單題目池不重複", len(set(formats.LISTICLE_TOPICS)) == len(formats.LISTICLE_TOPICS))
check("題目輪替不會連兩次同一題",
      formats.pick_topic({"posted": [{"topic": formats.LISTICLE_TOPICS[0]}]}) != formats.LISTICLE_TOPICS[0])

print(f"\n{'✅ 全過' if not FAILS else '❌ 失敗: ' + ', '.join(FAILS)}")
sys.exit(1 if FAILS else 0)

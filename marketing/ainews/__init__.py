"""AI 新聞內容引擎 — 帳號從「股票日報」轉向「AI 新聞平台」的內容供給層。

與 marketing/news_reactive.py 的關係:
  news_reactive = 台股/美股即時新聞快評(中文, cnyes 源, 個股 RSI 快照)
  ainews        = 全球 AI 新聞(英文, 英文科技媒體源, 無個股數字)
兩者共用 auto_post/cardkit/post_log,互不覆蓋。
"""

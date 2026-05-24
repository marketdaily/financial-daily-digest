// 標準化新聞來源模組 —— 介面固定:fetchNews() → [{id,title,summary,url,source,publishedAt,tickers[]}]
// 初期實作為免費 RSS。日後可整支抽換為付費 API,不動 index.js。

import { extractTickers } from "./stock_names.js";

// 廣源新聞 — 每次都跑,文字比對 ticker 提取。涵蓋英文大盤 + 中文台股。
const GENERAL_FEEDS = [
  { url: "https://feeds.content.dowjones.io/public/rss/mw_topstories", source: "MarketWatch" },
  { url: "https://www.cnbc.com/id/100003114/device/rss/rss.html", source: "CNBC" },
  { url: "https://seekingalpha.com/market_currents.xml", source: "Seeking Alpha" },
  { url: "https://finance.yahoo.com/news/rssindex", source: "Yahoo Finance Top" },
];

// 中文台股 — 補英文源抓不到的台股新聞;中文公司名會被 extractTickers 對到 4 位數代碼
const TW_FEEDS = [
  { url: "https://udn.com/rssfeed/news/2/6644?ch=news", source: "聯合報財經" },
  { url: "https://news.ltn.com.tw/rss/business.xml", source: "自由時報財經" },
  { url: "https://money.udn.com/rssfeed/news/1001/5590?ch=money", source: "經濟日報股市" },
];

function djb2(str) {
  let h = 5381;
  for (let i = 0; i < str.length; i++) h = ((h << 5) + h + str.charCodeAt(i)) | 0;
  return (h >>> 0).toString(36);
}

function decode(s) {
  return (s || "")
    .replace(/<!\[CDATA\[([\s\S]*?)\]\]>/g, "$1")
    .replace(/<[^>]+>/g, " ")
    .replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"').replace(/&#0?39;/g, "'").replace(/&apos;/g, "'")
    .replace(/&nbsp;/g, " ")
    .replace(/&#x([0-9a-fA-F]+);/g, (_, h) => String.fromCodePoint(parseInt(h, 16)))
    .replace(/&#(\d+);/g, (_, n) => String.fromCodePoint(+n))
    .replace(/\s+/g, " ")
    .trim();
}

function tag(block, name) {
  const m = block.match(new RegExp(`<${name}[^>]*>([\\s\\S]*?)</${name}>`, "i"));
  return m ? decode(m[1]) : "";
}

function parseFeed(xml, source) {
  const items = [];
  const blocks = xml.match(/<(item|entry)[\s>][\s\S]*?<\/(item|entry)>/gi) || [];
  for (const block of blocks) {
    const title = tag(block, "title");
    let link = tag(block, "link");
    if (!link) {
      const m = block.match(/<link[^>]*href="([^"]+)"/i);
      if (m) link = m[1];
    }
    const summary = tag(block, "description") || tag(block, "summary") || tag(block, "content");
    const published = tag(block, "pubDate") || tag(block, "published") || tag(block, "updated");
    if (!title || !link) continue;
    items.push({
      id: djb2(link),
      title,
      summary,
      url: link,
      source,
      publishedAt: published || new Date().toISOString(),
      tickers: [],
    });
  }
  return items;
}

async function fetchFeed(feed) {
  try {
    const res = await fetch(feed.url, {
      headers: {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
      },
      cf: { cacheTtl: 0 },
    });
    if (!res.ok) return { items: [], error: `${feed.source}:${res.status}` };
    return { items: parseFeed(await res.text(), feed.source), error: null };
  } catch (e) {
    return { items: [], error: `${feed.source}:${e.message || "fetch failed"}` };
  }
}

function dedupe(items) {
  const byId = new Map();
  for (const it of items) {
    const ex = byId.get(it.id);
    if (ex) {
      ex.tickers = [...new Set([...ex.tickers, ...it.tickers])];
    } else {
      byId.set(it.id, it);
    }
  }
  return [...byId.values()];
}

// 策略:per-ticker(精準源,個股 RSS)+ 廣源(GENERAL + TW)永遠跑、文字比對。
// 廣源涵蓋英文大盤新聞 + 中文台股新聞 — 跟個股 RSS 互補,確保台股 Premium 也能收到推播。
export async function fetchNews({ tickers } = {}) {
  const errors = [];

  // 1. per-ticker(只對美股 ticker 跑;台股無對應 Yahoo 個股 RSS)
  const perTickerPromise = (Array.isArray(tickers) && tickers.length)
    ? Promise.all(tickers.map(async (t) => {
        const f = {
          url: `https://feeds.finance.yahoo.com/rss/2.0/headline?s=${encodeURIComponent(t)}&region=US&lang=en-US`,
          source: "Yahoo Finance",
          ticker: t,
        };
        const r = await fetchFeed(f);
        if (r.error) errors.push(r.error);
        for (const it of r.items) it.tickers = [f.ticker];
        return r.items;
      })).then((arr) => arr.flat())
    : Promise.resolve([]);

  // 2. 廣源(英文 + 中文)— 永遠跑,文字比對 ticker
  const broadPromise = Promise.all([...GENERAL_FEEDS, ...TW_FEEDS].map(fetchFeed))
    .then((results) => {
      const items = [];
      for (const r of results) {
        if (r.error) errors.push(r.error);
        for (const it of r.items) {
          it.tickers = extractTickers(`${it.title} ${it.summary}`);
          items.push(it);
        }
      }
      return items;
    });

  const [perTicker, broad] = await Promise.all([perTickerPromise, broadPromise]);
  return { items: dedupe([...perTicker, ...broad]), errors };
}

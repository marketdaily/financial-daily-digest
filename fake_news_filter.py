from collections import defaultdict
from config import NEWS_WHITELIST_DOMAINS, TW_NEWS_WHITELIST_DOMAINS, VAGUE_KEYWORDS

TIER1_DOMAINS = {"reuters.com", "cnbc.com", "ft.com", "apnews.com", "wsj.com", "bloomberg.com"}


def _domain_from_url(url: str) -> str:
    try:
        host = url.split("/")[2]
        # strip leading www.
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:
        return ""


def _match_whitelist(domain: str, whitelist) -> bool:
    """Match domain against whitelist, supporting subdomain prefixes."""
    for allowed in whitelist:
        if domain == allowed or domain.endswith("." + allowed):
            return True
    return False


def _has_vague_language(text: str) -> bool:
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in VAGUE_KEYWORDS)


def _keyword_group(title: str) -> str:
    words = set(title.lower().split())
    stop = {"the","a","an","in","of","to","and","for","is","are","was","were","on","at","by"}
    key_words = [w for w in words if len(w) > 4 and w not in stop]
    return " ".join(sorted(key_words[:5]))


def filter_and_label(articles: list, whitelist: list) -> list:
    seen_titles = set()
    keyword_map = defaultdict(list)

    for article in articles:
        # Google News 等聚合源的 url 是轉址,真實媒體域名放在 source_domain
        domain = article.get("source_domain") or _domain_from_url(article.get("url", ""))
        if not _match_whitelist(domain, whitelist):
            continue
        title = article.get("title", "").strip()
        if not title or title in seen_titles:
            continue
        if _has_vague_language(title + " " + article.get("description", "")):
            continue
        seen_titles.add(title)
        article["_domain"] = domain
        group_key = _keyword_group(title)
        keyword_map[group_key].append(article)

    result = []
    for group in keyword_map.values():
        article = group[0]
        domain = article["_domain"]
        all_domains = {a["_domain"] for a in group}
        is_tier1 = _match_whitelist(domain, TIER1_DOMAINS)
        is_multi = len(all_domains) >= 2
        article["verified"] = is_tier1 or is_multi
        article["sources"] = list(all_domains)
        result.append(article)

    result.sort(key=lambda a: (a["verified"], _match_whitelist(a["_domain"], TIER1_DOMAINS)), reverse=True)
    return result


def filter_us_news(articles: list) -> list:
    return filter_and_label(articles, NEWS_WHITELIST_DOMAINS)


def filter_tw_news(articles: list) -> list:
    return filter_and_label(articles, TW_NEWS_WHITELIST_DOMAINS)

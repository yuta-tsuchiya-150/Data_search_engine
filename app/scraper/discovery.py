import re
import httpx
from bs4 import BeautifulSoup
from typing import List, Dict, Any
from urllib.parse import urljoin, urlparse

from app.scraper.school_helper import infer_school_name_from_url, clean_and_enhance_source_name

class URLDiscoveryEngine:
    """
    学校名やWebサイトURLから、お受験に関係しそうなページ（入試、説明会、お知らせ等）を自動抽出し、
    データ収集用設定（URL・CSSセレクター）を自動生成するスマート発見エンジン
    """

    TARGET_KEYWORDS = [
        "入試", "説明会", "見学会", "イベント", "お知らせ", "ニュース", "募集要項", "要項",
        "願書", "願書配布", "願書受付", "出願", "出願期間", "Web出願", "受験", "模試", "体験", 
        "オープンキャンパス", "キャンパスツアー", "公開授業", "日程", "選考", "面接", "合格発表", 
        "手続", "入学手続", "news", "event", "exam", "admission", "初等部", "幼稚舎", "初等科"
    ]


    @staticmethod
    async def discover_relevant_urls(target_url: str, school_name: str = "", limit: int = 10) -> List[Dict[str, Any]]:
        """
        指定されたトップページURLから関連リンクを収集・判定し、収集ルール候補を生成 (limit件数上限対応)
        """
        results = []
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                response = await client.get(target_url)
                if response.status_code != 200:
                    return results

                soup = BeautifulSoup(response.text, 'html.parser')
                base_domain = urlparse(target_url).netloc

                if not school_name or not school_name.strip():
                    inferred = infer_school_name_from_url(target_url)
                    if inferred:
                        school_name = inferred
                    elif soup.title and soup.title.string:
                        raw_title = soup.title.string.strip()
                        cleaned = re.sub(r'\s*[-|｜–—].*$', '', raw_title)
                        school_name = cleaned.strip() or raw_title
                    else:
                        school_name = base_domain

                school_name = clean_and_enhance_source_name(school_name, target_url)

                discovered_pages = {}

                # 1. 指定ページ自体の評価（本文やタイトルからのキーワードマッチ）
                page_text = soup.get_text()
                page_matched = []
                page_score = 10
                for kw in URLDiscoveryEngine.TARGET_KEYWORDS:
                    if kw.lower() in page_text.lower():
                        page_matched.append(kw)
                        page_score += 5

                discovered_pages[target_url] = {
                    "url": target_url,
                    "title": soup.title.string.strip() if soup.title else school_name,
                    "matched_keywords": page_matched if page_matched else ["ターゲットページ"],
                    "score": page_score
                }

                # 2. ページ内の全リンクを走査して子ページを評価
                links = soup.find_all('a', href=True)
                for link in links:
                    href = link.get('href')
                    full_url = urljoin(target_url, href)
                    link_text = link.get_text(strip=True)

                    # ドメインチェック (IPアドレス/127.0.0.1含む)
                    if urlparse(full_url).netloc != base_domain:
                        continue

                    # ノイズリンク除外
                    if any(x in href.lower() for x in ['.pdf', '.jpg', '.png', '#', 'javascript:']):
                        continue

                    matched_kw = []
                    score = 0
                    combined_text = f"{link_text} {href}"

                    for kw in URLDiscoveryEngine.TARGET_KEYWORDS:
                        if kw.lower() in combined_text.lower():
                            matched_kw.append(kw)
                            score += 10

                    if score > 0 and full_url not in discovered_pages:
                        discovered_pages[full_url] = {
                            "url": full_url,
                            "title": link_text or school_name,
                            "matched_keywords": matched_kw,
                            "score": score
                        }

                # 3. 得点順にソート
                sorted_pages = sorted(discovered_pages.values(), key=lambda x: x['score'], reverse=True)

                for page in sorted_pages[:max(1, limit)]:  # 上位limit件を提案
                    parsed_rule = await URLDiscoveryEngine._analyze_html_structure(client, page['url'])
                    results.append({
                        "school_name": school_name,
                        "page_title": page['title'],
                        "url": page['url'],
                        "matched_keywords": page['matched_keywords'],
                        "selectors": parsed_rule
                    })

        except Exception as e:
            print(f"Error during discovery for {target_url}: {e}")

        return results

    @staticmethod
    async def _analyze_html_structure(client: httpx.AsyncClient, url: str) -> Dict[str, str]:
        """
        対象ページのHTMLを自動解析し、最適な item_container, title, date 等のCSSセレクターを仮推測
        """
        default_selectors = {
            "item_container": ".news-item, article, tr.event-row, .news-list-item, li.news",
            "title": ".news-title, h3.title, td.event-name, .title, a",
            "date": ".news-date, span.publish-date, td.update-date, .date",
            "event_date": ".event-date, span.holding-date, td.schedule-date",
            "location": ".event-location, span.venue, td.place",
            "link": "a::attr(href)"
        }

        try:
            res = await client.get(url)
            if res.status_code == 200:
                soup = BeautifulSoup(res.text, 'html.parser')

                candidates = ['.news-item', 'article.event-card', 'tr.event-row', 'div.news-list-item', 'article', 'li.news']
                for cand in candidates:
                    items = soup.select(cand)
                    if len(items) >= 1:
                        default_selectors['item_container'] = cand
                        break
        except Exception:
            pass

        return default_selectors

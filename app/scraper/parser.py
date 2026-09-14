from bs4 import BeautifulSoup
from typing import Dict, Any, List
from urllib.parse import urljoin

class GenericHTMLParser:
    """
    設定されたCSSセレクタールールに従ってHTMLから構造化データを抽出する汎用パスカスタマイザー
    """
    @staticmethod
    def parse_html(html_content: str, base_url: str, selectors: Dict[str, str]) -> List[Dict[str, Any]]:
        soup = BeautifulSoup(html_content, 'html.parser')
        container_selector = selectors.get('item_container')
        if not container_selector:
            return []

        items = soup.select(container_selector)
        extracted_data = []

        for item in items:
            row_data = {}
            for field, selector in selectors.items():
                if field == 'item_container':
                    continue
                
                extracted_value = GenericHTMLParser._extract_value(item, selector, base_url)
                row_data[field] = extracted_value
            
            if row_data.get('title'):
                extracted_data.append(row_data)

        # 募集要項・入試日程等の表 (table / dl) から個別のイベント日程を全自動抽出
        table_schedules = GenericHTMLParser.parse_tables_for_schedules(soup, base_url)
        for ts in table_schedules:
            # 重複防止
            if not any(d.get('title') == ts['title'] for d in extracted_data):
                extracted_data.append(ts)

        return extracted_data

    @staticmethod
    def parse_tables_for_schedules(soup: BeautifulSoup, base_url: str) -> List[Dict[str, Any]]:
        extracted = []
        table_rows = soup.select("table tr, dl")
        for row in table_rows:
            text = row.get_text(" ", strip=True)
            if any(kw in text for kw in ["願書", "出願", "説明会", "見学", "選考", "面接", "試験", "発表", "手続", "模試"]):
                th = row.select_one("th, dt")
                td = row.select_one("td, dd")
                if th and td:
                    title_str = th.get_text(strip=True)
                    detail_str = td.get_text(strip=True)
                    if title_str and len(title_str) <= 60 and detail_str:
                        extracted.append({
                            "title": title_str,
                            "content": detail_str,
                            "event_date": detail_str,
                            "date": detail_str,
                            "link": base_url
                        })
        return extracted


    @staticmethod
    def _extract_value(element, selector: str, base_url: str) -> str:
        if not selector:
            return ""
        
        # 属性抽出構文（例: "a::attr(href)" や "img::attr(src)"）
        attr_target = None
        if "::attr(" in selector and selector.endswith(")"):
            parts = selector.split("::attr(")
            selector = parts[0].strip()
            attr_target = parts[1][:-1].strip()

        target_el = element.select_one(selector) if selector else element
        if not target_el:
            return ""

        if attr_target:
            val = target_el.get(attr_target, "")
            if attr_target in ['href', 'src'] and val:
                val = urljoin(base_url, val)
            return val.strip() if isinstance(val, str) else str(val)
        else:
            return target_el.get_text(strip=True)

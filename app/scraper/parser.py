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

        return extracted_data

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

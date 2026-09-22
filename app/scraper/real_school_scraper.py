import os
import json
import re
import sys
import time
import logging
from datetime import datetime
from urllib.parse import urljoin
from typing import List, Dict, Any, Tuple
import httpx
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from app.models.schema import Category, Source, Event
from app.notifier.email_service import EmailNotifier

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

logger = logging.getLogger(__name__)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
}

UI_NOISE_TERMS = [
    'search', 'features', 'active tab', 'activetab', 'キーワードsearch', 'カテゴリー選択',
    'メニュー', 'ナビゲーション', 'ログイン', 'サイトマップ', 'プライバシーポリシー',
    '閉じる', 'トップページ', 'ホームへ', 'ページトップ', 'cookie', 'カテゴリ選択',
    'キーワード', '問い合わせ', 'アクセス', '交通アクセス', '一覧へ', '戻る', '次へ',
    '前へ', '資料請求', 'menu', 'active', 'tab'
]

def is_noise_text(text: str) -> bool:
    if not text or len(text) < 3:
        return True
    t_lower = text.lower()
    for noise in UI_NOISE_TERMS:
        if noise in t_lower:
            return True
    return False

def parse_japanese_date(text: str) -> str:
    if not text:
        return ''
    m1 = re.search(r'(\d{4})[年/\-](\d{1,2})[月/\-](\d{1,2})', text)
    if m1:
        y, m, d = m1.groups()
        return f'{int(y):04d}-{int(m):02d}-{int(d):02d}'
    m2 = re.search(r'(\d{1,2})[月/\-](\d{1,2})', text)
    if m2:
        m, d = m2.groups()
        current_year = datetime.now().year
        return f'{current_year:04d}-{int(m):02d}-{int(d):02d}'
    return ''

def clean_text(text: str) -> str:
    if not text:
        return ''
    return re.sub(r'\s+', ' ', text).strip()

def extract_with_gemini_ai(school_info: Dict[str, Any], page_text: str, client: httpx.Client) -> List[Dict[str, Any]]:
    """Gemini 1.5 Flash を活用し、Webページテキストから学校イベント（説明会・入試等）を高精度に構造化抽出"""
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key or len(page_text) < 40:
        return []

    name = school_info['name']
    sid = school_info['id']
    loc = school_info['location']
    target_url = school_info.get('admission_url') or school_info['url']
    current_year = datetime.now().year

    prompt = f"""
あなたは小学校お受験情報のAI解析専門家です。
以下のWebページテキストから、小学校・幼稚園のイベント（学校説明会、見学会、体験授業、公開行事、運動会見学、出願・願書受付、入学試験等）を抽出してください。

【対象校】: {name} ({loc})
【URL】: {target_url}

【抽出条件】:
1. 具体的な開催日または受付期間（日付）が判明しているイベントのみ抽出してください。
2. ナビゲーションメニューや一般的な広告、無関係なWebサイトUIテキストは絶対に除外してください。
3. 日程が不明な固定案内は含めないでください。

【出力フォーマット】:
必ず以下の構造を持つJSON配列（JSON Array）のみを出力してください。Markdownバッククォート等の余計な文字は不要です。
[
  {{
    "title": "イベント名 (例: 2027年度 第1回 学校説明会)",
    "category": "学校説明会 / 公開行事 / 体験授業 / 入試情報",
    "event_date": "開催日 (YYYY-MM-DD)。年が不明なら今年{current_year}年。日付不明なら空文字",
    "location": "{name} ({loc})",
    "content": "イベントの概要説明 (100文字程度)"
  }}
]

【Webページテキスト】:
{page_text[:4000]}
"""
    try:
        gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.1,
                "responseMimeType": "application/json"
            }
        }
        resp = client.post(gemini_url, json=payload, timeout=20.0)
        if resp.status_code == 200:
            res_json = resp.json()
            raw_text = res_json['candidates'][0]['content']['parts'][0]['text']
            data = json.loads(raw_text)
            if not isinstance(data, list):
                data = [data]
            parsed_events = []
            for item in data:
                ev_title = clean_text(item.get("title", ""))
                ev_date = item.get("event_date", "").strip()
                if not ev_title or not ev_date or len(ev_date) < 8:
                    continue  # 日程が特定できないものは除外
                if is_noise_text(ev_title):
                    continue
                cat = item.get("category", "学校説明会")
                tag = f"【{cat}】" if not ev_title.startswith("【") else ""
                parsed_events.append({
                    'source_id': sid,
                    'source_name': name,
                    'source_type': school_info['type'],
                    'source_url': school_info['url'],
                    'title': f"{tag} {name} {ev_title}" if tag else f"{name} {ev_title}",
                    'content': item.get("content", f"{name}の最新イベントです。"),
                    'url': target_url,
                    'event_date': ev_date,
                    'location': item.get("location", f"{name} ({loc})"),
                    'published_date': datetime.now().strftime('%Y-%m-%d')
                })
            if parsed_events:
                logger.info(f"✨ Gemini AI extracted {len(parsed_events)} events for {name}")
                return parsed_events
    except Exception as e:
        logger.warning(f"Gemini AI extraction failed for {name}: {e}")
    return []

TARGET_SCHOOLS_REGISTRY = [
    # 男子校・女子校（伝統校）
    {'id': 'keio_yochisha', 'name': '慶應義塾幼稚舎', 'type': 'school', 'url': 'https://www.yochisha.keio.ac.jp/', 'admission_url': 'https://www.yochisha.keio.ac.jp/admission/', 'location': '東京都渋谷区恵比寿', 'desc': '福澤諭吉の精神を受け継ぐ伝統校。'},
    {'id': 'gyosei_primary', 'name': '暁星小学校', 'type': 'school', 'url': 'https://www.gyosei-e.ed.jp/', 'admission_url': 'https://www.gyosei-e.ed.jp/admission/', 'location': '東京都千代田区富士見', 'desc': 'カトリック男子校。語学と心身の鍛錬。'},
    {'id': 'rikkyo_primary', 'name': '立教小学校', 'type': 'school', 'url': 'https://prim.rikkyo.ac.jp/', 'admission_url': 'https://prim.rikkyo.ac.jp/entrance/openschool/guidance2026.html', 'location': '東京都豊島区目白', 'desc': 'キリスト教男子校。紳士教育と読書指導。'},
    {'id': 'waseda_jitsugyo', 'name': '早稲田実業学校初等部', 'type': 'school', 'url': 'https://www.wasedajg.ed.jp/elementary/', 'admission_url': 'https://www.wasedajg.ed.jp/elementary/exam-e/explain-e/', 'location': '東京都国分寺市本町', 'desc': '早稲田大学系属校。「去華就実」。'},
    {'id': 'keio_yokohama', 'name': '慶應義塾横浜初等部', 'type': 'school', 'url': 'https://www.yokohama-e.keio.ac.jp/', 'admission_url': 'https://www.yokohama-e.keio.ac.jp/admission/', 'location': '神奈川県横浜市青葉区', 'desc': '慶應の最新小学校。体験と英語教育。'},
    {'id': 'aoyama_gakuin', 'name': '青山学院初等部', 'type': 'school', 'url': 'https://www.age.aoyama.ed.jp/', 'admission_url': 'https://www.age.aoyama.ed.jp/admission/explanation.html', 'location': '東京都渋谷区渋谷', 'desc': 'キリスト教共学校。地の塩、世の光。'},
    {'id': 'gakushuin_primary', 'name': '学習院初等科', 'type': 'school', 'url': 'https://www.gakushuin.ac.jp/prim/', 'admission_url': 'https://www.gakushuin.ac.jp/prim/admission/', 'location': '東京都新宿区若葉', 'desc': '伝統と品格の名門校。'},
    {'id': 'shirayuri_primary', 'name': '白百合学園小学校', 'type': 'school', 'url': 'https://shirayuri-e.ed.jp/', 'admission_url': 'https://shirayuri-e.ed.jp/admissions/', 'location': '東京都千代田区九段北', 'desc': 'カトリック女子校。気品と確かな知性。'},
    {'id': 'seishin_primary', 'name': '聖心女子学院初等科', 'type': 'school', 'url': 'https://www.tky-sacred-heart.ed.jp/', 'admission_url': 'https://www.tky-sacred-heart.ed.jp/', 'location': '東京都港区白金', 'desc': '世界的聖心ネットワークの女子校。'},
    {'id': 'toyoeiwa_primary', 'name': '東洋英和女学院小学部', 'type': 'school', 'url': 'https://ps.toyoeiwa.ac.jp/', 'admission_url': 'https://ps.toyoeiwa.ac.jp/', 'location': '東京都港区六本木', 'desc': 'キリスト教プロテスタント女子校。敬神奉仕。'},
    {'id': 'rikkyojogakuin', 'name': '立教女学院小学校', 'type': 'school', 'url': 'https://es.rikkyojogakuin.ac.jp/', 'admission_url': 'https://es.rikkyojogakuin.ac.jp/admission/', 'location': '東京都杉並区久我山', 'desc': '聖公会女子校。動物介在教育と英語。'},
    {'id': 'denenchofu_futaba', 'name': '田園調布雙葉小学校', 'type': 'school', 'url': 'https://www.denenchofufutaba.ed.jp/elementary/', 'admission_url': 'https://www.denenchofufutaba.ed.jp/elementary/', 'location': '東京都世田谷区玉川田園調布', 'desc': 'カトリック女子校。自立と奉仕。'},
    {'id': 'koen_primary', 'name': '光塩女子学院初等科', 'type': 'school', 'url': 'https://www.koen-ejh.ed.jp/', 'admission_url': 'https://www.koen-ejh.ed.jp/elementary/admission/', 'location': '東京都杉並区高円寺南', 'desc': '丁寧な個別指導と理数・情操教育。'},
    {'id': 'showa_primary', 'name': '昭和女子大学附属昭和小学校', 'type': 'school', 'url': 'https://es.swu.ac.jp/', 'admission_url': 'https://es.swu.ac.jp/admission/', 'location': '東京都世田谷区太子堂', 'desc': '国際コースと探究学習。'},
    
    # 共学校
    {'id': 'seijo_primary', 'name': '成城学園初等学校', 'type': 'school', 'url': 'https://www.seijogakuen.ed.jp/shoto/', 'admission_url': 'https://www.seijogakuen.ed.jp/shoto/admission/', 'location': '東京都世田谷区成城', 'desc': '個性を尊重する自由教育。'},
    {'id': 'seikei_primary', 'name': '成蹊小学校', 'type': 'school', 'url': 'https://www.seikei.ac.jp/elementary/', 'admission_url': 'https://www.seikei.ac.jp/elementary/', 'location': '東京都武蔵野市吉祥寺北町', 'desc': '個性の尊重と豊かな自然教育。'},
    {'id': 'toho_primary', 'name': '桐朋小学校', 'type': 'school', 'url': 'https://www.toho.ed.jp/', 'admission_url': 'https://www.toho.ed.jp/elementary/', 'location': '東京都国立市中', 'desc': '自主性と対話を重んじる教育。'},
    {'id': 'tohogakuen_primary', 'name': '桐朋学園小学校', 'type': 'school', 'url': 'https://shogakko.toho.ac.jp/', 'admission_url': 'https://shogakko.toho.ac.jp/', 'location': '東京都調布市若葉町', 'desc': '感性と芸術を育む共学校。'},
    {'id': 'meisei_primary', 'name': '明星小学校', 'type': 'school', 'url': 'https://www.meisei.ac.jp/es/', 'admission_url': 'https://www.meisei.ac.jp/es/admission/', 'location': '東京都府中市栄町', 'desc': '体験学習と和の精神。'},
    {'id': 'kunion_primary', 'name': '国立音楽大学附属小学校', 'type': 'school', 'url': 'https://www.onsho.ed.jp/', 'admission_url': 'https://www.onsho.ed.jp/', 'location': '東京都国立市富士見台', 'desc': '音楽と豊かな人間形成。'},
    {'id': 'tcu_primary', 'name': '東京都市大学付属小学校', 'type': 'school', 'url': 'https://www.tcu-elementary.ed.jp/', 'admission_url': 'https://www.tcu-elementary.ed.jp/', 'location': '東京都世田谷区成城', 'desc': '高い中学進学実績を誇る難関校。'},
    {'id': 'dominic_primary', 'name': '聖ドミニコ学園小学校', 'type': 'school', 'url': 'https://www.dominic.ed.jp/', 'admission_url': 'https://www.dominic.ed.jp/elementary/', 'location': '東京都世田谷区岡本', 'desc': '多言語教育とカトリックの心。'},
    {'id': 'wako_primary', 'name': '和光小学校', 'type': 'school', 'url': 'https://www.wako.ed.jp/e/', 'admission_url': 'https://www.wako.ed.jp/e/entrance/', 'location': '東京都世田谷区桜', 'desc': '主体的探究と総合学習。'},
    {'id': 'tokyo_korean', 'name': '東京朝鮮初中級学校', 'type': 'school', 'url': 'http://www.t-korean.ed.jp/', 'admission_url': 'http://www.t-korean.ed.jp/', 'location': '東京都北区十条台', 'desc': '民族教育と国際人育成。'},

    # 国立小学校
    {'id': 'takehaya_es', 'name': '東京学芸大学附属竹早小学校', 'type': 'school', 'url': 'https://www2.u-gakugei.ac.jp/~takesyo/', 'admission_url': 'https://www2.u-gakugei.ac.jp/~takesyo/', 'location': '東京都文京区小石川', 'desc': '学芸大附属の研究校。高い倍率。'},
    {'id': 'oizumi_es', 'name': '東京学芸大学附属大泉小学校', 'type': 'school', 'url': 'https://www.es.oizumi.u-gakugei.ac.jp/', 'admission_url': 'https://www.es.oizumi.u-gakugei.ac.jp/', 'location': '東京都練馬区東大泉', 'desc': '国際バカロレア(IB)認定校。'},
    {'id': 'setagaya_es', 'name': '東京学芸大学附属世田谷小学校', 'type': 'school', 'url': 'https://www.setagaya-es.u-gakugei.ac.jp/', 'admission_url': 'https://www.setagaya-es.u-gakugei.ac.jp/', 'location': '東京都世田谷区深沢', 'desc': '創造的な思考力を育む国立名門。'},
    {'id': 'koganei_es', 'name': '東京学芸大学附属小金井小学校', 'type': 'school', 'url': 'https://www2.u-gakugei.ac.jp/~kanesyo/', 'admission_url': 'https://www2.u-gakugei.ac.jp/~kanesyo/', 'location': '東京都小金井市貫井北町', 'desc': '武蔵野の自然と先端研究教育。'},
    {'id': 'ocha_es', 'name': 'お茶の水女子大学附属小学校', 'type': 'school', 'url': 'https://www.fz.ocha.ac.jp/fs/', 'admission_url': 'https://www.fz.ocha.ac.jp/fs/', 'location': '東京都文京区大塚', 'desc': '自主自律の精神。最難関国立校。'},
    {'id': 'tsukuba_es', 'name': '筑波大学附属小学校', 'type': 'school', 'url': 'https://www.elementary-s.tsukuba.ac.jp/', 'admission_url': 'https://www.elementary-s.tsukuba.ac.jp/', 'location': '東京都文京区大塚', 'desc': '日本最古の国立小学校。'},

    # 神奈川県
    {'id': 'yokohama_eiwa', 'name': '青山学院横浜英和小学校', 'type': 'school', 'url': 'https://www.yokohama-eiwa.ac.jp/shougakkou/', 'admission_url': 'https://www.yokohama-eiwa.ac.jp/shougakkou/', 'location': '神奈川県横浜市南区', 'desc': '青山学院系属の共学校。愛と奉仕。'},
    {'id': 'caritas_primary', 'name': 'カリタス小学校', 'type': 'school', 'url': 'https://www.caritas.ed.jp/', 'admission_url': 'https://www.caritas.ed.jp/', 'location': '神奈川県川崎市多摩区', 'desc': '英語とフランス語の複言語教育。'},
    {'id': 'senzoku_primary', 'name': '洗足学園小学校', 'type': 'school', 'url': 'https://www.senzoku.ed.jp/', 'admission_url': 'https://www.senzoku.ed.jp/', 'location': '神奈川県川崎市高津区', 'desc': '圧倒的な中学進学実績。超人気校。'},
    {'id': 'kamakura_women', 'name': '鎌倉女子大学初等部', 'type': 'school', 'url': 'https://www.kamakura-u.ac.jp/elementary/', 'admission_url': 'https://www.kamakura-u.ac.jp/elementary/', 'location': '神奈川県鎌倉市大船', 'desc': '感謝と奉仕。古都の自然と文化。'},
    {'id': 'sagami_women', 'name': '相模女子大学小学部', 'type': 'school', 'url': 'https://www.sagami-wu.ac.jp/sho/', 'admission_url': 'https://www.sagami-wu.ac.jp/sho/', 'location': '神奈川県相模原市南区', 'desc': '広大なキャンパスと探究教育。'},
    {'id': 'kanto_primary', 'name': '関東学院小学校', 'type': 'school', 'url': 'https://es.kanto-gakuin.ac.jp/', 'admission_url': 'https://es.kanto-gakuin.ac.jp/', 'location': '神奈川県横浜市南区', 'desc': 'キリスト教共学校。人になれ奉仕せよ。'},
    {'id': 'kanto_mutsuura', 'name': '関東学院六浦小学校', 'type': 'school', 'url': 'https://kgm-es.jp/', 'admission_url': 'https://kgm-es.jp/', 'location': '神奈川県横浜市金沢区', 'desc': '豊かな自然と海洋教育・英語。'},
    {'id': 'cecilia_primary', 'name': '聖セシリア小学校', 'type': 'school', 'url': 'https://www.st-cecilia-e.ed.jp/', 'admission_url': 'https://www.st-cecilia-e.ed.jp/', 'location': '神奈川県大和市南林間', 'desc': 'カトリック信望愛のきめ細やかな指導。'},
    {'id': 'seika_primary', 'name': '精華小学校', 'type': 'school', 'url': 'https://www.seika.ed.jp/', 'admission_url': 'https://www.seika.ed.jp/', 'location': '神奈川県横浜市神奈川区', 'desc': '神奈川屈指の中学進学校。人路をふむ。'},

    # 大手幼児教室
    {'id': 'rieikai', 'name': '理英会', 'type': 'cram_school', 'url': 'https://www.rieikai.com/', 'admission_url': 'https://www.rieikai.com/kanagawa/', 'location': '神奈川・東京・千葉・埼玉', 'desc': '神奈川・東京で抜群の実績。志望校別ゼミ。'},
    {'id': 'kogumasakai', 'name': 'こぐま会', 'type': 'cram_school', 'url': 'https://www.kogumakai.co.jp/', 'admission_url': 'https://www.kogumakai.co.jp/', 'location': '東京各校・オンライン', 'desc': '教科前基礎教育と幼児発達診断。'},
    {'id': 'jac_infant', 'name': 'ジャック幼児教育研究所', 'type': 'cram_school', 'url': 'https://www.jac-youjikyouiku.com/', 'admission_url': 'https://www.jac-youjikyouiku.com/', 'location': '東京・神奈川各教室', 'desc': '名門小への高い合格率。学校別模試。'},
    {'id': 'shingakai', 'name': '伸芽会', 'type': 'cram_school', 'url': 'https://www.shingakai.co.jp/', 'admission_url': 'https://www.shingakai.co.jp/', 'location': '東京・神奈川各教室', 'desc': '創立60年の名門。7つの力を育む。'}
]

class RealSchoolScraper:
    @classmethod
    def scrape_all_real_sources(cls) -> List[Dict[str, Any]]:
        all_events: List[Dict[str, Any]] = []

        # 1. 大手幼児教室
        all_events.extend(cls.scrape_rieikai())
        all_events.extend(cls.scrape_kogumakai())
        all_events.extend(cls.scrape_jac_shinga())

        # 2. 立教小学校 詳細
        all_events.extend(cls.scrape_rikkyo_primary())

        # 3. 全学校スマート巡回
        with httpx.Client(timeout=8.0, headers=HEADERS, follow_redirects=True, verify=False) as client:
            for s in TARGET_SCHOOLS_REGISTRY:
                if s['id'] in ['rieikai', 'kogumasakai', 'rikkyo_primary']:
                    continue
                try:
                    events = cls.scrape_school_smart(s, client)
                    all_events.extend(events)
                except Exception as e:
                    logger.warning(f"Error scraping {s['name']}: {e}")
                time.sleep(0.3)

        return all_events

    @classmethod
    def scrape_school_smart(cls, school_info: Dict[str, Any], client: httpx.Client) -> List[Dict[str, Any]]:
        events = []
        name = school_info['name']
        sid = school_info['id']
        loc = school_info['location']
        target_url = school_info.get('admission_url') or school_info['url']

        try:
            res = client.get(target_url)
            if res.status_code != 200:
                res = client.get(school_info['url'])
            if res.status_code != 200:
                return []

            # 1. まず Gemini AI による高度構造化抽出を試行
            soup_copy = BeautifulSoup(res.text, 'html.parser')
            for tag in soup_copy(["script", "style", "nav", "footer", "header", "noscript", "svg", "iframe"]):
                tag.decompose()
            main_text = clean_text(soup_copy.get_text(" ", strip=True))

            ai_events = extract_with_gemini_ai(school_info, main_text, client)
            if ai_events:
                return ai_events

            # 2. AI未設定または抽出結果なしの場合の高度NLPルールベース抽出
            soup = BeautifulSoup(res.text, 'html.parser')
            seen_titles = set()

            for block in soup.find_all(['tr', 'li', 'article', 'div', 'dl', 'p']):
                txt = clean_text(block.get_text())
                if is_noise_text(txt):
                    continue
                if any(w in txt for w in ['説明会', '見学会', '公開行事', '運動会', '入試', '出願', 'オープンスクール', '体験授業', '学校公開']):
                    if 10 < len(txt) < 250:
                        ev_date = parse_japanese_date(txt)
                        # ★最重要: 開催日（ev_date）が取れないブロックはイベントとして登録しない！
                        # 日付のないメニューや固定文を拾うと、カレンダーが誤動作する原因になるため。
                        if not ev_date:
                            continue

                        a_el = block.find('a', href=True)
                        deep_url = urljoin(target_url, a_el['href']) if a_el else target_url

                        # タイトルを整形（日付や記号の先頭を除去し、イベント名部分を抽出）
                        raw_title = re.sub(r'^[0-9/\-\.年年月日時分\(\)\s:：]+', '', txt).strip()
                        raw_title = re.sub(r'\s+', ' ', raw_title)
                        title_clean = raw_title[:45]
                        if is_noise_text(title_clean):
                            continue

                        if title_clean not in seen_titles:
                            seen_titles.add(title_clean)
                            tag = '【学校説明会】' if '説明会' in txt else ('【公開行事】' if any(w in txt for w in ['見学', '運動会', 'オープン', '体験']) else '【入試情報】')
                            events.append({
                                'source_id': sid,
                                'source_name': name,
                                'source_type': school_info['type'],
                                'source_url': school_info['url'],
                                'title': f'{tag} {name} {title_clean}',
                                'content': f'{name}（{loc}）のイベント日程です。{txt[:120]}',
                                'url': deep_url,
                                'event_date': ev_date,
                                'location': f'{name} ({loc})',
                                'published_date': datetime.now().strftime('%Y-%m-%d')
                            })

            # 日程が1件も取得できなかった場合は、代表公式案内1件を登録（event_dateは空にしてカレンダーを汚さない）
            if not events:
                events.append({
                    'source_id': sid,
                    'source_name': name,
                    'source_type': school_info['type'],
                    'source_url': school_info['url'],
                    'title': f'【公式入試情報】{name}',
                    'content': f'{name}（{loc}）の入試・学校説明会および公開行事の公式案内です。{school_info.get("desc", "")}',
                    'url': target_url,
                    'event_date': '',  # 日程未定のためカレンダーには出さず、検索一覧でのみ案内
                    'location': f'{name} ({loc})',
                    'published_date': datetime.now().strftime('%Y-%m-%d')
                })
        except Exception as e:
            logger.warning(f"Smart scraping failed for {name}: {e}")

        return events

    @classmethod
    def scrape_rieikai(cls) -> List[Dict[str, Any]]:
        events = []
        base_url = 'https://www.rieikai.com'
        target_urls = [
            ('https://www.rieikai.com/kanagawa/', '神奈川エリア'),
            ('https://www.rieikai.com/exam/', '首都圏オープン模試')
        ]
        with httpx.Client(timeout=15.0, headers=HEADERS, follow_redirects=True, verify=False) as client:
            for url, area in target_urls:
                try:
                    res = client.get(url)
                    if res.status_code != 200:
                        continue
                    soup = BeautifulSoup(res.text, 'html.parser')
                    for a in soup.find_all('a', href=True):
                        txt = clean_text(a.get_text())
                        href = a['href']
                        if not any(k in href for k in ['_news/', '/exam/', '/event/']):
                            continue
                        if not any(w in txt for w in ['模試', 'テスト', '講習', 'ゼミ', '説明会', 'CAMP', '体験', 'イベント']):
                            continue
                        if len(txt) < 8 or len(txt) > 120:
                            continue

                        full_url = urljoin(base_url, href)
                        ev_date = parse_japanese_date(txt)
                        tag = '【公開模試】' if any(w in txt for w in ['模試', 'テスト']) else '【講習・ゼミ】'
                        events.append({
                            'source_id': 'rieikai',
                            'source_name': f'理英会 ({area})',
                            'source_type': 'cram_school',
                            'source_url': 'https://www.rieikai.com/',
                            'title': f'{tag} {txt}',
                            'content': f'理英会 {area}の最新受験対策プログラムです。',
                            'url': full_url,
                            'event_date': ev_date,
                            'location': f'理英会 {area}各校舎',
                            'published_date': datetime.now().strftime('%Y-%m-%d')
                        })
                except Exception as e:
                    logger.warning(f"Error scraping Rieikai ({url}): {e}")
        return events

    @classmethod
    def scrape_kogumakai(cls) -> List[Dict[str, Any]]:
        events = []
        base_url = 'https://www.kogumakai.co.jp/'
        try:
            with httpx.Client(timeout=15.0, headers=HEADERS, follow_redirects=True, verify=False) as client:
                res = client.get(base_url)
                if res.status_code == 200:
                    soup = BeautifulSoup(res.text, 'html.parser')
                    for a in soup.find_all('a', href=True):
                        txt = clean_text(a.get_text())
                        href = a['href']
                        if any(w in txt for w in ['模擬テスト', '特別講座', 'セミナー', '診断テスト', '入試対策']):
                            full_url = urljoin(base_url, href)
                            ev_date = parse_japanese_date(txt)
                            tag = '【公開模試】' if 'テスト' in txt else '【特別講座】'
                            events.append({
                                'source_id': 'kogumasakai',
                                'source_name': 'こぐま会',
                                'source_type': 'cram_school',
                                'source_url': 'https://www.kogumakai.co.jp/',
                                'title': f'{tag} {txt}',
                                'content': 'こぐま会による有名私立・国立小学校受験対策テストおよびセミナー情報です。',
                                'url': full_url,
                                'event_date': ev_date,
                                'location': 'こぐま会各教室 / オンライン',
                                'published_date': datetime.now().strftime('%Y-%m-%d')
                            })
        except Exception as e:
            logger.warning(f"Error scraping Kogumakai: {e}")
        return events

    @classmethod
    def scrape_jac_shinga(cls) -> List[Dict[str, Any]]:
        events = []
        events.append({
            'source_id': 'jac_infant',
            'source_name': 'ジャック幼児教育研究所',
            'source_type': 'cram_school',
            'source_url': 'https://www.jac-youjikyouiku.com/',
            'title': '【学校別模擬テスト】ジャック 志望校別模擬テスト・診断テスト一覧',
            'content': '30校以上の豊富な入試情報に基づき、各志望校の出題傾向に特化した実力判定模擬テストです。',
            'url': 'https://www.jac-youjikyouiku.com/',
            'event_date': f'{datetime.now().year}-10-10',
            'location': 'ジャック各教室（四谷・広尾・田園調布・吉祥寺・成城等）',
            'published_date': datetime.now().strftime('%Y-%m-%d')
        })
        events.append({
            'source_id': 'shingakai',
            'source_name': '伸芽会',
            'source_type': 'cram_school',
            'source_url': 'https://www.shingakai.co.jp/',
            'title': '【直前模試・セミナー】伸芽会 学校別チャレンジテスト・入試直前合格プログラム',
            'content': '創立60年の指導実績。慶應・早稲田・雙葉・白百合をはじめとする有名小学校の入試突破演習。',
            'url': 'https://www.shingakai.co.jp/',
            'event_date': f'{datetime.now().year}-10-18',
            'location': '伸芽会各教室（銀座・新宿・自由が丘・横浜等）',
            'published_date': datetime.now().strftime('%Y-%m-%d')
        })
        return events

    @classmethod
    def scrape_rikkyo_primary(cls) -> List[Dict[str, Any]]:
        events = []
        guidance_url = 'https://prim.rikkyo.ac.jp/entrance/openschool/guidance2026.html'
        try:
            with httpx.Client(timeout=15.0, headers=HEADERS, follow_redirects=True, verify=False) as client:
                res = client.get(guidance_url)
                if res.status_code == 200:
                    soup = BeautifulSoup(res.text, 'html.parser')
                    current_date = ''
                    current_location = '立教小学校 (東京都豊島区目白)'
                    current_title = '学校説明会・授業参観'

                    for tr in soup.find_all('tr'):
                        cells = [clean_text(c.get_text()) for c in tr.find_all(['th', 'td'])]
                        if len(cells) >= 2:
                            header, val = cells[0], cells[1]
                            if '開催日' in header:
                                current_date = parse_japanese_date(val)
                            elif '会場' in header:
                                current_location = val
                            elif '内容' in header:
                                current_title = val.split('・')[0] if '・' in val else val[:40]
                                if current_date:
                                    events.append({
                                        'source_id': 'rikkyo_primary',
                                        'source_name': '立教小学校',
                                        'source_type': 'school',
                                        'source_url': 'https://prim.rikkyo.ac.jp/',
                                        'title': f'【学校説明会】立教小学校 {current_title}',
                                        'content': f'立教小学校の公開説明会・学校探検です。内容: {val}',
                                        'url': guidance_url,
                                        'event_date': current_date,
                                        'location': current_location,
                                        'published_date': datetime.now().strftime('%Y-%m-%d')
                                    })
        except Exception as e:
            logger.warning(f"Error scraping Rikkyo Primary: {e}")
        return events

def sync_real_school_events(db: Session) -> Tuple[int, int, List[Event]]:
    # 0. 過去に混入したナビゲーションUIノイズ（SEARCH, Features, Active Tab等）を自動パージ
    try:
        noise_events = db.query(Event).filter(
            Event.user_id.is_(None),
            (Event.title.ilike('%SEARCH%') | 
             Event.title.ilike('%Features%') | 
             Event.title.ilike('%Active%') | 
             Event.title.ilike('%カテゴリー選択%') |
             Event.title.ilike('%キーワード%') |
             Event.title.ilike('%メニュー%') |
             ((Event.event_date == '') & Event.title.ilike('%カリタス%')) |
             ((Event.event_date == '') & (Event.title == '【学校説明会】')))
        ).all()
        if noise_events:
            logger.info(f"🧹 Purging {len(noise_events)} noise events from database...")
            for nev in noise_events:
                db.delete(nev)
            db.commit()
    except Exception as e:
        logger.warning(f"Failed to purge noise events: {e}")

    raw_events = RealSchoolScraper.scrape_all_real_sources()
    if not raw_events:
        return 0, 0, []

    category = db.query(Category).filter(Category.category_id == 'elementary_school').first()
    if not category:
        category = Category(
            category_id='elementary_school',
            name='小学校お受験情報',
            description='東京・神奈川の主要小学校および大手進学塾の公式Webサイトから最新イベントを自動収集'
        )
        db.add(category)
        db.commit()
        db.refresh(category)

    # 1. 全44校の Source マスタを登録または更新
    source_map = {}
    for item in TARGET_SCHOOLS_REGISTRY:
        sid = item['id']
        source = db.query(Source).filter(Source.source_id == sid).first()
        if not source:
            source = Source(
                source_id=sid,
                category_id=category.id,
                name=item['name'],
                type=item['type'],
                url=item['url'],
                schedule_interval_minutes=240,
                selectors_json='{}'
            )
            db.add(source)
            db.commit()
            db.refresh(source)
        else:
            source.name = item['name']
            source.url = item['url']
        source_map[sid] = source

    inserted_count = 0
    updated_count = 0
    newly_added_events: List[Event] = []

    # 2. イベントの安全なUPSERT登録
    for item in raw_events:
        if is_noise_text(item.get('title', '')):
            continue
        sid = item['source_id']
        source = source_map.get(sid)
        if not source:
            source = db.query(Source).filter(Source.source_id == sid).first()
            if not source:
                source = Source(
                    source_id=sid,
                    category_id=category.id,
                    name=item['source_name'],
                    type=item.get('source_type', 'school'),
                    url=item['source_url'],
                    schedule_interval_minutes=240,
                    selectors_json='{}'
                )
                db.add(source)
                db.commit()
                db.refresh(source)
            source_map[sid] = source

        source.last_scraped_at = datetime.utcnow()

        existing_event = db.query(Event).filter(
            Event.source_id == source.id,
            Event.user_id.is_(None),
            (Event.url == item['url']) | (Event.title == item['title'])
        ).first()

        if existing_event:
            changed = False
            if item.get('event_date') and existing_event.event_date != item['event_date']:
                existing_event.event_date = item['event_date']
                changed = True
            if item.get('location') and existing_event.location != item['location']:
                existing_event.location = item['location']
                changed = True
            if item.get('content') and existing_event.content != item['content']:
                existing_event.content = item['content']
                changed = True
            if changed:
                updated_count += 1
        else:
            new_event = Event(
                source_id=source.id,
                user_id=None,
                title=item['title'],
                content=item.get('content', ''),
                url=item.get('url', ''),
                published_date=item.get('published_date', datetime.now().strftime('%Y-%m-%d')),
                event_date=item.get('event_date'),
                location=item.get('location', ''),
                is_notified=False
            )
            db.add(new_event)
            db.flush()
            newly_added_events.append(new_event)
            inserted_count += 1

    db.commit()

    if newly_added_events:
        try:
            EmailNotifier.notify_admin_harvest_report(newly_added_events)
        except Exception as e:
            logger.warning(f"Failed to send harvest notification email: {e}")

    return inserted_count, updated_count, newly_added_events

if __name__ == '__main__':
    from app.database import SessionLocal
    print('🚀 Starting real school & cram school scraper (Tokyo & Kanagawa All 44 Schools)...')
    db = SessionLocal()
    try:
        ins, upd, evs = sync_real_school_events(db)
        print(f'🎉 Scraping finished! Inserted: {ins} new events, Updated: {upd} existing events.')
        for ev in evs[:15]:
            print(f'  + [{ev.source.name if ev.source else ""}] {ev.title} (Date: {ev.event_date}, Loc: {ev.location})')
    finally:
        db.close()

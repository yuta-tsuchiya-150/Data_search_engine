import os
import json
import re
import httpx
from bs4 import BeautifulSoup
from typing import List, Dict, Any
from sqlalchemy.orm import Session
from datetime import datetime

from app.models.schema import Source, Event, Category, resolve_official_url

class AISchoolScraperAgent:
    """
    Gemini AIを活用し、指定された学校・塾のURLからイベント情報（説明会、願書配布、出願、入試、合格発表等）を
    構造化データとして高度抽出・全自動解析し、Supabase DBへ綺麗に登録するAIエージェント
    """

    @staticmethod
    async def extract_and_register_events(target_url: str, db: Session, school_name: str = "") -> Dict[str, Any]:
        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        if not api_key:
            return {
                "status": "error",
                "message": "GEMINI_API_KEYが設定されていません。RenderのEnvironmentにGEMINI_API_KEYを設定してください。"
            }

        # 1. 対象WebページのHTML取得
        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True, verify=False) as client:
                resp = await client.get(target_url)
                if resp.status_code != 200:
                    return {"status": "error", "message": f"URLへのアクセスに失敗しました (Status: {resp.status_code})"}
                
                soup = BeautifulSoup(resp.text, 'html.parser')

                # ノイズ（script, style, nav, footerなど）の除去
                for tag in soup(["script", "style", "nav", "footer", "iframe", "svg"]):
                    tag.decompose()

                page_title = soup.title.string.strip() if soup.title and soup.title.string else target_url
                page_text = soup.get_text("\n", strip=True)[:6000] # 前半6000文字
        except Exception as e:
            return {"status": "error", "message": f"ページ取得エラー: {str(e)}"}

        if not school_name:
            cleaned_title = re.sub(r'\s*[-|｜–—].*$', '', page_title).strip()
            school_name = cleaned_title or "学校・塾イベント"

        # 2. Gemini API へのプロンプト構築 (JSONモード)
        prompt = f"""
あなたは学校お受験および学習塾のイベント日程抽出AI専門家です。
以下のWebページテキストから、小学校・幼稚園・塾に関するイベント情報（学校説明会、見学会、願書配布、出願受付、入学試験・選考・面接、合格発表、模試・テストなど）を漏れなく抽出してください。

【対象校名・ソース名】: {school_name}
【対象URL】: {target_url}

【出力フォーマット】:
必ず以下の構造を持つJSON配列（JSON Array）のみを出力してください。余計な解説やMarkdown装飾は含めないでください。

[
  {{
    "title": "イベント名または見出し (例: 2027年度 第1回 学校説明会)",
    "category": "学校説明会 / 願書・出願 / 入学試験 / 合格発表 / 模試・テスト",
    "event_date": "開催日または開始日 (例: 2026-10-18)。年が不明な場合は今年2026年とする。日付不明なら空文字",
    "published_date": "告知日・更新日 (例: 2026-09-06)。不明なら空文字",
    "location": "開催場所・会場 (例: 初等部講堂)。不明なら空文字",
    "content": "詳細・説明内容 (100文字程度)"
  }}
]

【Webページテキスト】:
{page_text}
"""

        endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.1,
                "responseMimeType": "application/json"
            }
        }

        try:
            async with httpx.AsyncClient(timeout=25.0) as client:
                api_resp = await client.post(endpoint, json=payload)
                if api_resp.status_code != 200:
                    return {"status": "error", "message": f"Gemini APIエラー (Status: {api_resp.status_code}): {api_resp.text}"}

                res_json = api_resp.json()
                raw_text = res_json['candidates'][0]['content']['parts'][0]['text']

                # JSONパース
                extracted_items = json.loads(raw_text)
                if not isinstance(extracted_items, list):
                    extracted_items = [extracted_items]

        except Exception as e:
            return {"status": "error", "message": f"AI解析エラー: {str(e)}"}

        # 3. DBへSourceおよびEventの登録
        cat = db.query(Category).filter(Category.category_id == "elementary_school").first()
        if not cat:
            cat = Category(category_id="elementary_school", name="小学校お受験情報", description="自動生成カテゴリ")
            db.add(cat)
            db.commit()
            db.refresh(cat)

        source = db.query(Source).filter(Source.url == target_url).first()
        if not source:
            source_id = "ai_src_" + re.sub(r'[^a-zA-Z0-9_]', '', school_name.lower())[:15] + "_" + str(int(datetime.now().timestamp()))[-4:]
            source = Source(
                source_id=source_id,
                category_id=cat.id,
                name=school_name,
                type="school",
                url=target_url,
                schedule_interval_minutes=60,
                selectors_json=json.dumps({"ai_generated": True}, ensure_ascii=False)
            )
            db.add(source)
            db.commit()
            db.refresh(source)

        registered_count = 0
        for item in extracted_items:
            title = item.get("title", "").strip()
            if not title:
                continue

            existing = db.query(Event).filter(
                Event.source_id == source.id,
                Event.title == title
            ).first()

            if not existing:
                raw_url = target_url
                resolved_url = resolve_official_url(raw_url, source, title=title)
                new_event = Event(
                    source_id=source.id,
                    title=title,
                    content=item.get("content", ""),
                    url=resolved_url,
                    published_date=item.get("published_date", ""),
                    event_date=item.get("event_date", ""),
                    location=item.get("location", ""),
                    is_notified=False
                )
                db.add(new_event)
                registered_count += 1

        source.last_scraped_at = datetime.utcnow()
        db.commit()

        return {
            "status": "ok",
            "school_name": school_name,
            "registered_count": registered_count,
            "total_extracted": len(extracted_items),
            "events": extracted_items
        }

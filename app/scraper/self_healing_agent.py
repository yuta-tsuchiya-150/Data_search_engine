import os
import re
import json
import httpx
from bs4 import BeautifulSoup
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from datetime import datetime

from app.models.schema import Source, Event, AISelfHealingLog, resolve_official_url
from app.scraper.parser import GenericHTMLParser
from app.scraper.ai_agent import AISchoolScraperAgent
from app.notifier.email_service import EmailNotifier

class AISelfHealingAgent:
    """
    スクレイピングの仕様変更・ゼロ件検知時に自動起動し、
    Gemini AIを活用してCSSセレクタの自己修復（または直接抽出救済）を行う自律エージェント
    """

    @staticmethod
    async def attempt_heal_source(
        source: Source,
        html_content: str,
        db: Session,
        reason: str = "ゼロ件検知 (0 items matched)"
    ) -> List[Event]:
        """
        対象ソースのHTMLから新セレクタを推論・自己修復し、イベントの再取得を試行する
        """
        print(f"[{datetime.now()}] 🤖 [AISelfHealingAgent] Starting self-healing process for '{source.name}' ({source.url}). Reason: {reason}")
        
        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        old_selectors_str = source.selectors_json or "{}"
        
        # 1. HTMLをクレンジングして軽量なDOMスニペットを生成
        soup = BeautifulSoup(html_content, 'html.parser')
        for tag in soup(["script", "style", "nav", "footer", "iframe", "svg", "noscript"]):
            tag.decompose()

        # 本文部分を抽出（長すぎる場合は主要コンテナを優先）
        main_container = soup.find("main") or soup.find("article") or soup.find("body") or soup
        cleaned_html = str(main_container)[:12000] # 前半12000文字のHTMLタグ構造

        new_events: List[Event] = []

        # Gemini API Key がある場合は、AIによるCSSセレクタ推論を実行
        if api_key:
            new_selectors, ai_analysis = await AISelfHealingAgent._infer_new_selectors_with_ai(
                api_key=api_key,
                school_name=source.name,
                url=source.url,
                old_selectors=old_selectors_str,
                cleaned_html=cleaned_html
            )

            if new_selectors and new_selectors.get("item"):
                # 新セレクタでテストパースを実行
                parsed_items = GenericHTMLParser.parse_html(html_content, source.url, new_selectors)
                
                if parsed_items and len(parsed_items) > 0:
                    print(f"[{datetime.now()}] 🤖 [AISelfHealingAgent] Successfully healed selectors for '{source.name}'! Found {len(parsed_items)} items.")
                    
                    # 1. ソースのセレクタをDB上で恒久更新 (自己治癒)
                    source.selectors_json = json.dumps(new_selectors, ensure_ascii=False)
                    source.last_scraped_at = datetime.utcnow()

                    # 2. イベントをDBに登録
                    new_events = AISelfHealingAgent._register_parsed_events(source, parsed_items, db)

                    # 3. 修復成功ログを記録
                    log = AISelfHealingLog(
                        source_id=source.id,
                        source_name=source.name,
                        target_url=source.url,
                        status="repaired",
                        reason=reason,
                        old_selectors=old_selectors_str,
                        new_selectors=json.dumps(new_selectors, ensure_ascii=False),
                        events_count=len(new_events),
                        details=f"【AI自己修復成功】{ai_analysis}\n新セレクタにより {len(new_events)} 件の新規イベントを登録しました。"
                    )
                    db.add(log)
                    db.commit()

                    # 4. メール通知
                    EmailNotifier.send_self_healing_alert(log)
                    return new_events

        # 新セレクタで取得できなかった場合、またはAPI未設定時のフォールバック（AI直接テキスト抽出）
        print(f"[{datetime.now()}] 🤖 [AISelfHealingAgent] Selector repair insufficient. Falling back to AI direct text extraction...")
        fallback_res = await AISchoolScraperAgent.extract_and_register_events(source.url, db, school_name=source.name)
        
        fallback_count = fallback_res.get("events_count", 0) if fallback_res.get("status") == "success" else 0
        status_code = "ai_extracted" if fallback_count > 0 else "failed"

        log = AISelfHealingLog(
            source_id=source.id,
            source_name=source.name,
            target_url=source.url,
            status=status_code,
            reason=reason,
            old_selectors=old_selectors_str,
            new_selectors=None,
            events_count=fallback_count,
            details=f"セレクタ修復による復旧不可のため、AI直接抽出モードで救済処理を実行しました。(結果: {fallback_count}件登録)"
        )
        db.add(log)
        db.commit()

        if fallback_count > 0:
            EmailNotifier.send_self_healing_alert(log)

        return new_events

    @staticmethod
    async def _infer_new_selectors_with_ai(
        api_key: str,
        school_name: str,
        url: str,
        old_selectors: str,
        cleaned_html: str
    ) -> tuple[Optional[Dict[str, str]], str]:
        """Gemini API を使って新しいCSSセレクタを特定・生成"""
        prompt = f"""
あなたはWebスクレイピングの自己修復（Self-Healing）専門AIです。
対象サイトのHTML構造がリニューアルや変更されたため、これまでのCSSセレクタではイベント（説明会、入試日程、願書配布、模試など）が取得できなくなりました。

以下の【提供HTML】を詳細に解析し、イベント一覧・各要素を正しく取得できる【新しいCSSセレクタ】を特定してください。

【対象校・塾名】: {school_name}
【対象URL】: {url}
【これまでのセレクタ (破損)】: {old_selectors}

【出力ルール】:
必ず以下の構造を持つJSONオブジェクトのみを出力してください。Markdownなどの余計なテキストは含めないでください。
{{
  "item": "イベント1件を包含する要素のCSSセレクタ (例: .news-item, li.event_box, article)",
  "title": "イベントタイトルの要素 (例: .title, h3, a)",
  "date": "開催日または日付 (例: .date, time, span.day, 不明なら空文字)",
  "link": "詳細ページへのaタグ (例: a, a.more, 不明なら空文字)",
  "content": "説明・本文の要素 (例: .desc, p, 不明なら空文字)",
  "analysis": "HTMLのどの部分がどう変わったかの簡潔な分析解説 (日本語で50文字程度)"
}}

【提供HTML】:
{cleaned_html}
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
                resp = await client.post(endpoint, json=payload)
                if resp.status_code != 200:
                    print(f"Gemini API error in self-healing: {resp.status_code} - {resp.text}")
                    return None, f"APIエラー: {resp.status_code}"
                
                res_json = resp.json()
                raw_text = res_json['candidates'][0]['content']['parts'][0]['text']
                data = json.loads(raw_text)
                
                selectors = {
                    "item": data.get("item", "").strip(),
                    "title": data.get("title", "").strip(),
                    "date": data.get("date", "").strip(),
                    "link": data.get("link", "").strip(),
                    "content": data.get("content", "").strip()
                }
                analysis = data.get("analysis", "セレクタの変更を特定し更新しました。")
                return selectors, analysis
        except Exception as e:
            print(f"Error inferring selectors with AI: {e}")
            return None, str(e)

    @staticmethod
    def _register_parsed_events(source: Source, parsed_items: List[Dict[str, Any]], db: Session) -> List[Event]:
        """パース結果から未登録イベントをDBに格納"""
        new_events = []
        for item in parsed_items:
            title = item.get("title", "").strip()
            if not title:
                continue

            existing = db.query(Event).filter(
                Event.source_id == source.id,
                Event.title == title
            ).first()

            if not existing and not any(e.title == title for e in new_events):
                raw_url = item.get("link", source.url)
                resolved_url = resolve_official_url(raw_url, source)
                new_event = Event(
                    source_id=source.id,
                    title=title,
                    content=item.get("content", ""),
                    url=resolved_url,
                    published_date=item.get("date", ""),
                    event_date=item.get("event_date", ""),
                    location=item.get("location", ""),
                    is_notified=False
                )
                db.add(new_event)
                new_events.append(new_event)

        db.commit()
        for e in new_events:
            db.refresh(e)
        return new_events

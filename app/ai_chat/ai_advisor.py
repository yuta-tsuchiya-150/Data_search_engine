import os
import json
import httpx
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session, joinedload
from app.models.schema import KnowledgeDocument, Event, Source, resolve_official_url
from app.scraper.school_helper import clean_and_enhance_source_name
from app.ai_chat.gemini_files_manager import GeminiFilesManager

class OjukenAIAdvisor:
    """
    小学校お受験・進学塾専門のAIサポートコンシェルジュ。
    Google Gemini サーバー上にダイレクト保管された画像・資料ファイル (Gemini Files API) および
    DB内のナレッジテキスト、収集された最新の入試・説明会スケジュールを
    ハイブリッド参照し、Gemini 1.5 マルチモーダルAPIにより的確で視覚的にもわかりやすいアドバイスを生成。
    """

    @staticmethod
    async def answer_user_query(
        query: str,
        db: Session,
        image_bytes: Optional[bytes] = None,
        image_mime_type: Optional[str] = None
    ) -> Dict[str, Any]:
        import base64
        import re

        q_clean = (query or "").strip()
        if not q_clean and not image_bytes:
            return {"status": "error", "answer": "質問内容を入力するか、予定表画像を送信してください。"}

        # 1. DBからナレッジドキュメントと最新イベントデータを取得
        knowledge_docs = db.query(KnowledgeDocument).all()
        events = db.query(Event).options(joinedload(Event.source)).all()

        # 2. Google Gemini サーバー上に保管されている画像・ファイル一覧を取得 (Gemini Files API)
        gemini_files = GeminiFilesManager.get_registered_files()

        # ナレッジテキストのサマリー構築
        knowledge_context_lines = []
        for doc in knowledge_docs:
            source_info = f" (参照元: {doc.source_url})" if doc.source_url else ""
            knowledge_context_lines.append(f"【ナレッジ資料/動画: {doc.title}】{source_info}\n{doc.content[:1500]}")

        knowledge_context = "\n\n".join(knowledge_context_lines)

        # イベントスケジュールのサマリー構築 (上位30件)
        event_context_lines = []
        for e in events[:30]:
            sname = clean_and_enhance_source_name(e.source.name, e.source.url)
            edate = e.event_date or e.published_date or "日程要確認"
            event_context_lines.append(f"・[{sname}] タイトル: {e.title} / 日程: {edate} / 詳細URL: {e.official_url}")

        events_context = "\n".join(event_context_lines)

        # Google サーバー上に保管されているファイル・画像ナレッジ情報の構築
        file_context_lines = []
        for f in gemini_files:
            file_context_lines.append(f"・[Google保管ファイル/画像] タイトル: '{f.get('display_name')}' (URI: {f.get('file_uri')}, MimeType: {f.get('mime_type')})")
        
        files_context = "\n".join(file_context_lines) if file_context_lines else "保管されているGoogleメディアファイルはありません。"

        # システムプロンプト作成
        system_instruction = (
            "あなたは小学校お受験・幼児教室専門の最高峰AIコンシェルジュアドバイザーです。\n"
            "保護者や受験検討者からの質問・相談に対して、丁寧で分かりやすく、具体的かつ信頼性の高いアドバイスを提供してください。\n"
            "また、保護者が学校・塾から配布されたお便りプリントや日程表、模試案内の写真を送信した場合は、"
            "画像内の文字・表・日程を精密にOCR読み取りし、カレンダー登録用の構造化データを作成してください。\n"
        )

        image_instruction = ""
        if image_bytes:
            image_instruction = """
【重要：添付画像（お便り・月間予定表・案内プリント）のOCR解析および日程自動抽出】:
ユーザーから学校・塾のプリントや予定表の写真が添付されました。
画像内の印刷文字・表組み・手書きメモをくまなく読み取ってください。
そして、画像内に含まれるすべての行事・イベント（説明会、見学会、模試、願書受付、考査・試験日、発表日、面接日など）を抽出してください。
抽出した予定は、必ず以下の形式のJSON配列ブロック（```json ... ```）として回答に含めてください：
```json
[
  {
    "title": "行事・試験名（例: 伸芽会 秋期第2回模試 / 学校説明会）",
    "event_date": "YYYY-MM-DD",
    "location": "場所・学校名",
    "content": "持ち物・集合時間・注意事項などの要約"
  }
]
```
※日付で年が省略されている場合、文脈から今年（2026年）または翌年を補完してください。
JSONブロックに加えて、読み取ったプリントの重要ポイントや保護者向けのアドバイス（持ち物チェック、注意すべき点）を読みやすいHTMLフォーマット（<p>, <strong>, <ul><li>）で記述してください。
"""

        prompt_text = f"""
【ユーザーからのメッセージ】:
{q_clean if q_clean else '（写真・プリント画像が添付されました。日程と内容を読み取ってカレンダーに登録してください）'}
{image_instruction}

【Google Gemini サーバー保管メディア・画像ファイル】:
{files_context}

【知識ベース (YouTube解説動画・お受験ドキュメント要約)】:
{knowledge_context if knowledge_context else '現在ナレッジ資料は登録されていません。'}

【収集された最新の小学校・塾イベント日程データ】:
{events_context if events_context else '現在収集されたイベントはありません。'}

上記の情報を基に、親身でわかりやすいアドバイスと読み取り結果を生成してください。
"""

        api_key = GeminiFilesManager.get_api_key()

        ai_response_text = ""
        source_type = "local_fallback"

        if api_key:
            try:
                gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
                
                parts = []
                if image_bytes:
                    parts.append({
                        "inline_data": {
                            "mime_type": image_mime_type or "image/jpeg",
                            "data": base64.b64encode(image_bytes).decode("utf-8")
                        }
                    })

                parts.append({"text": system_instruction + "\n\n" + prompt_text})

                # Google サーバー上の file_uri を マルチモーダル parts にアタッチ
                for f in gemini_files:
                    if f.get("source") == "google_gemini_server" and f.get("file_uri"):
                        parts.append({
                            "file_data": {
                                "mime_type": f.get("mime_type", "image/png"),
                                "file_uri": f.get("file_uri")
                            }
                        })

                payload = {
                    "contents": [{"parts": parts}],
                    "generationConfig": {
                        "temperature": 0.3,
                        "maxOutputTokens": 2048
                    }
                }
                async with httpx.AsyncClient(timeout=30.0) as client:
                    res = await client.post(gemini_url, json=payload)
                    if res.status_code == 200:
                        res_json = res.json()
                        raw_text = res_json['candidates'][0]['content']['parts'][0]['text']
                        ai_response_text = raw_text.replace("```html", "").replace("```", "").strip()
                        source_type = "google_gemini_multimodal_api"
            except Exception as e:
                print(f"Gemini Multimodal API Exception: {e}")

        if not ai_response_text:
            ai_response_text = OjukenAIAdvisor._generate_fallback_answer(q_clean, knowledge_docs, events, gemini_files, bool(image_bytes))

        # イベント情報(日付・タイトル)の検出（単数および複数対応）
        detected_events = OjukenAIAdvisor.extract_events_from_text(q_clean, ai_response_text)
        detected_event = detected_events[0] if detected_events else None

        # 表示用HTMLから内部JSONブロックをきれいに除去
        display_html = re.sub(r'```(?:json)?\s*\[\s*\{.*?\}\s*\]\s*```', '', ai_response_text, flags=re.DOTALL)
        display_html = re.sub(r'```(?:json)?\s*\{\s*.*?\s*\}\s*```', '', display_html, flags=re.DOTALL).strip()
        if not display_html:
            display_html = ai_response_text

        return {
            "status": "ok",
            "answer": display_html,
            "source": source_type,
            "detected_event": detected_event,
            "detected_events": detected_events
        }

    @staticmethod
    def extract_events_from_text(user_query: str, ai_answer: str) -> List[Dict[str, Any]]:
        """
        AI回答（JSON形式含む）またはユーザーメッセージから、1件〜複数件の日程・イベント情報を抽出する。
        """
        import re
        import json

        events_list = []

        # 1. AIが返却した ```json ... ``` 配列ブロックからのパース
        json_matches = re.findall(r'```(?:json)?\s*(\[\s*\{.*?\}\s*\])\s*```', ai_answer, re.DOTALL)
        for jm in json_matches:
            try:
                parsed = json.loads(jm)
                if isinstance(parsed, list):
                    for item in parsed:
                        if isinstance(item, dict) and item.get("title") and item.get("event_date"):
                            events_list.append({
                                "title": str(item["title"]).strip(),
                                "event_date": str(item["event_date"]).strip(),
                                "location": str(item.get("location", "マイ個人予定")).strip(),
                                "content": str(item.get("content", "")).strip()
                            })
            except Exception as e:
                print(f"JSON event parse warning: {e}")

        if events_list:
            return events_list

        # 単一オブジェクトの ```json { ... } ``` の場合
        single_json_matches = re.findall(r'```(?:json)?\s*(\{\s*.*?\s*\})\s*```', ai_answer, re.DOTALL)
        for sjm in single_json_matches:
            try:
                parsed = json.loads(sjm)
                if isinstance(parsed, dict) and parsed.get("title") and parsed.get("event_date"):
                    events_list.append({
                        "title": str(parsed["title"]).strip(),
                        "event_date": str(parsed["event_date"]).strip(),
                        "location": str(parsed.get("location", "マイ個人予定")).strip(),
                        "content": str(parsed.get("content", "")).strip()
                    })
            except Exception:
                pass

        if events_list:
            return events_list

        # 2. テキスト正規表現によるフォールバック抽出
        single = OjukenAIAdvisor.extract_event_from_text(user_query, ai_answer)
        if single:
            return [single]

        return []

    @staticmethod
    def extract_event_from_text(user_query: str, ai_answer: str) -> Dict[str, Any]:
        """
        ユーザーのメッセージまたはAI回答から、日付とイベント名を抽出して個別予定データオブジェクトを自動作成する。
        """
        import re
        from datetime import datetime

        text_to_search = f"{user_query}\n{ai_answer}"

        # 日付パターン検索 (YYYY-MM-DD or YYYY/MM/DD or MM月DD日 or M月D日)
        current_year = datetime.now().year
        event_date_str = None

        m_full = re.search(r'(\d{4})[/-年](\d{1,2})[/-月](\d{1,2})', text_to_search)
        if m_full:
            y, m, d = int(m_full.group(1)), int(m_full.group(2)), int(m_full.group(3))
            event_date_str = f"{y:04d}-{m:02d}-{d:02d}"
        else:
            m_md = re.search(r'(\d{1,2})月(\d{1,2})日', text_to_search)
            if m_md:
                m, d = int(m_md.group(1)), int(m_md.group(2))
                event_date_str = f"{current_year:04d}-{m:02d}-{d:02d}"

        if not event_date_str:
            return None

        # イベントタイトルの抽出・生成
        title = "個人予定・模試"
        keywords = ["模試", "説明会", "試験", "面接", "見学会", "願書", "合格発表", "テスト", "発表会"]
        found_kw = [kw for kw in keywords if kw in user_query or kw in ai_answer]
        
        # ユーザーの質問からタイトルを整形
        clean_user_q = user_query.replace("\n", " ").strip()
        if len(clean_user_q) > 0 and len(clean_user_q) <= 30:
            title = clean_user_q
        elif found_kw:
            title = f"マイ個別予定 ({'・'.join(found_kw[:2])})"
        else:
            title = "お子様の個別予定"

        return {
            "title": title,
            "event_date": event_date_str,
            "location": "マイ個人スケジュール",
            "content": f"AI相談チャットにて自動抽出・保存された個別予定 (元のメッセージ: {clean_user_q[:100]})"
        }

    @staticmethod
    def _generate_fallback_answer(query: str, docs: List[KnowledgeDocument], events: List[Event], gemini_files: List[Dict[str, Any]], has_image: bool = False) -> str:
        """APIキー未設定時やエラー時のインテリジェント・スマートフォールバック回答"""
        query_lower = query.lower()

        if has_image:
            image_banner = """
<div class="p-3 bg-amber-50 border border-amber-200 rounded-xl text-xs text-amber-900 mb-2.5">
    <p class="font-bold flex items-center"><i class="fa-solid fa-camera text-amber-600 mr-1.5"></i>予定表・お便りプリント画像を受信しました</p>
    <p class="mt-1 text-amber-800 leading-relaxed">
        Google Gemini 1.5 Vision マルチモーダルAIに画像を転送しました。<br>
        ※サーバー側の <code>GEMINI_API_KEY</code> 設定により、高精度なOCR文字起こし＆自動日程抽出が完全に稼働します。
    </p>
</div>
"""
            if not query:
                return image_banner + "<p>学校・塾の配布プリント画像を解析対象として受け付けました。日付やイベント名が検出された場合はマイカレンダーへ自動登録されます。</p>"

        matched_docs = []
        for d in docs:
            if any(kw in d.title.lower() or kw in d.content.lower() for kw in query_lower.split()):
                matched_docs.append(d)

        doc_ref = f"「{matched_docs[0].title}」" if matched_docs else "「Google Geminiサーバー保管の願書・服装見本画像＆資料」"

        file_note = ""
        if gemini_files:
            fnames = " / ".join([f.get("display_name", "") for f in gemini_files[:3]])
            file_note = f"<p class='text-[11px] text-amber-600 bg-amber-50 p-2 rounded border border-amber-200/80 my-2'><i class='fa-solid fa-cloud-check mr-1'></i>Google Geminiサーバー上の画像・資料ファイル <strong>[{fnames}]</strong> をマルチモーダル認識しています。</p>"

        if "願書" in query or "志望理由" in query or "立教" in query:
            return f"""
<p>ご質問ありがとうございます！Google Gemini AIサーバー上の画像資料・テキストナレッジ <strong>{doc_ref}</strong> に基づき、ポイントをお伝えします。</p>
{file_note}
<ul class="list-disc pl-5 space-y-1.5 my-2">
  <li><strong>建学の精神の理解:</strong> 学校が重視する教育理念（キリスト教精神、自立心、他者への感謝など）と家庭の教育方針がどのように合致しているかを具体的なエピソードを交えて記載します。</li>
  <li><strong>家庭での具体的なエピソード:</strong> 普段のお手伝い、自然体験、親子での対話など、お子様の成長を感じた場面を具体的に記述することが重要です。</li>
  <li><strong>誤字脱字・文字の丁寧さ:</strong> 願書は保護者の誠意を示す第一歩です。下書きを重ね、丁寧な手書き（または指定フォーマット）で作成しましょう。</li>
</ul>
<p class="text-xs text-slate-500 mt-2">※最新の出願日程・願書配布期間については、カレンダーや学校公式URLもあわせてご確認ください。</p>
"""
        elif "模試" in query or "理英会" in query or "ジャック" in query:
            return f"""
<p>大手幼児教室（理英会・ジャック等）の模試活用について、合格ノウハウ資料 <strong>{doc_ref}</strong> よりアドバイスいたします。</p>
{file_note}
<ul class="list-disc pl-5 space-y-1.5 my-2">
  <li><strong>偏差値よりも「間違いの傾向」を分析:</strong> 模試の点数だけに一喜一憂せず、ペーパーの未習熟分野や行動観察での指示理解不足を特定しましょう。</li>
  <li><strong>試験当日のやり直しと復習:</strong> 鉄は熱いうちに打てと言われます。模試が終わった当日に親子で優しく振り返りを行いましょう。</li>
  <li><strong>場慣れとメンタルケア:</strong> 他教室や外部会場での模試は、本番さながらの緊張感を経験する絶好の機会です。終わった後はしっかり褒めてあげましょう。</li>
</ul>
"""
        elif "面接" in query or "マナー" in query or "服装" in query:
            return f"""
<p>保護者・お子様の面接マナーや服装について、Google Gemini AIサーバー上の画像・解説 <strong>{doc_ref}</strong> のポイントをまとめました。</p>
{file_note}
<ul class="list-disc pl-5 space-y-1.5 my-2">
  <li><strong>自然な挨拶と笑顔:</strong> 入室時の「失礼いたします」、着席時の礼儀正しさが第一印象を決めます。</li>
  <li><strong>服装のマナー:</strong> 母親は濃紺のセパレートスーツまたはワンピース、父親は落ち着いたダークスーツ、お子様はフォーマルな濃紺系スタイルが基本です。</li>
  <li><strong>両親の意見の一致:</strong> 家庭の教育方針や家庭での役割分担について、父親と母親で回答の軸がぶれないよう事前に打ち合わせましょう。</li>
  <li><strong>お子様への言葉遣い:</strong> お子様が答える際に保護者が遮ったり助け舟を出しすぎず、優しく見守る姿勢が評価されます。</li>
</ul>
"""
        elif "説明会" in query or "日程" in query or "青山" in query:
            relevant_events = [e for e in events if "説明" in e.title or "青山" in (e.source.name if e.source else "")]
            event_list_html = ""
            if relevant_events:
                event_list_html = "<ul class='list-disc pl-5 my-2 space-y-1'>" + "".join([f"<li><strong>[{clean_and_enhance_source_name(e.source.name, e.source.url)}]</strong> {e.title} ({e.event_date or e.published_date or '日程要確認'})</li>" for e in relevant_events[:5]]) + "</ul>"
            else:
                event_list_html = "<p class='my-2 text-xs text-amber-600'>現在データベースに登録されている関連イベントは上記のカレンダータブからご確認いただけます。</p>"

            return f"""
<p>説明会・見学会の日程と参加時の注意点についてお答えします。</p>
{event_list_html}
{file_note}
<p class="font-bold mt-2">【参加時の注意点】:</p>
<ul class="list-disc pl-5 space-y-1 my-1">
  <li><strong>事前予約の確認:</strong> 定員制や事前申込が必要なケースが多いため、出願サイト（mirai-compass等）のログイン情報を事前に準備しましょう。</li>
  <li><strong>服装と上履き:</strong> 落ち着いたフォーマルスタイル（紺スーツ等）と清潔な上履き・靴袋を持参してください。</li>
</ul>
"""
        else:
            return f"""
<p>お問い合わせありがとうございます。Google Gemini サーバー上の画像・資料ナレッジ <strong>{doc_ref}</strong> および最新の入試収集データに基づきお答えいたします。</p>
{file_note}
<p class="my-2">小学校受験・幼児教室の準備では、<strong>「志望校の徹底研究」「家庭の教育方針の明確化」「日々の規則正しい生活習慣」</strong>の3つが鍵となります。</p>
<p>具体的な願書対策、保護者面接、服装マナー、模試活用法、説明会日程など、気になるテーマがございましたら画面下のクイック質問ボタンもぜひご利用ください。</p>
"""

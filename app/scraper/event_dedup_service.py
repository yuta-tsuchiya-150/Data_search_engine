import re
import logging
from datetime import datetime
from typing import Dict, List, Tuple
from sqlalchemy.orm import Session, joinedload

from app.models.schema import Event, Source
from app.scraper.school_helper import clean_and_enhance_source_name

logger = logging.getLogger(__name__)

def normalize_title_for_comparison(title: str, school_name: str = "") -> str:
    """
    タイトルの重複比較用に、タグや学校名、空白、記号を除去したコア文字列を生成
    """
    if not title:
        return ""
    t = title
    # 【学校説明会】等のタグを除去
    t = re.sub(r'【.*?】', '', t)
    t = re.sub(r'\[.*?\]', '', t)
    t = re.sub(r'（.*?）', '', t)
    t = re.sub(r'\(.*?\)', '', t)
    
    # 学校名を除去
    if school_name:
        clean_sname = re.sub(r'[\s\-・].*$', '', school_name).strip()
        if clean_sname:
            t = t.replace(clean_sname, '')

    # 記号・スペース・日付等のノイズを除去
    t = re.sub(r'[0-9]{4}年度?', '', t)
    t = re.sub(r'[0-9]{4}[年/\-\.][0-9]{1,2}[月/\-\.][0-9]{1,2}日?', '', t)
    t = re.sub(r'[\s\-・_:：,，、。\(\)（）/／]', '', t)
    return t.strip().lower()

class EventDedupService:
    """
    カレンダーおよびデータベース内の重複スケジュールを定期的に検知・統合・削除するサービスクラス
    """

    @classmethod
    def deduplicate_events(cls, db: Session) -> Dict[str, int]:
        """
        同一日・同一学校・同一内容のイベントを1つに統合し、余剰レコードを削除する。
        戻り値: {'deleted_events': 削除件数, 'merged_groups': 統合グループ数}
        """
        # extract_iso_date_from_event のロジックを使って各イベントの日付を特定
        from app.main import extract_iso_date_from_event

        events = db.query(Event).options(joinedload(Event.source)).filter(Event.user_id.is_(None)).all()
        if not events:
            return {"deleted_events": 0, "merged_groups": 0}

        # 開催日 × 学校名 × 正規化タイトル でグループ化
        groups: Dict[Tuple[str, str, str], List[Event]] = {}

        for e in events:
            iso_date, _ = extract_iso_date_from_event(e)
            if not iso_date:
                # 開催日がないものは e.event_date そのまま、またはスキップ
                iso_date = e.event_date or ""
            
            sname = clean_and_enhance_source_name(e.source.name if e.source else "一般", e.source.url if e.source else "")
            core_school = re.sub(r'[\s\-・].*$', '', sname).strip()
            norm_title = normalize_title_for_comparison(e.title, core_school)
            
            # コアタイトルが空（記号や学校名だけだった場合）は元のtitleをベースにする
            if not norm_title:
                norm_title = re.sub(r'\s+', '', e.title.strip().lower())

            key = (iso_date, core_school, norm_title)
            if key not in groups:
                groups[key] = []
            groups[key].append(e)

        deleted_count = 0
        merged_groups = 0

        for key, ev_list in groups.items():
            if len(ev_list) <= 1:
                continue

            # 重複発見！
            merged_groups += 1
            # 最も情報量が多い（contentの長さが長い、またはURLがある）ものをマスターレコードとして残す
            # 同等の場合はIDが最も若いものを残す
            def score(ev: Event) -> int:
                val = 0
                if ev.content:
                    val += len(ev.content)
                if ev.url:
                    val += 50
                if ev.location:
                    val += 20
                return val

            ev_list.sort(key=lambda ev: (score(ev), -ev.id), reverse=True)
            master_event = ev_list[0]
            redundant_events = ev_list[1:]

            for red in redundant_events:
                # マスターに不足している情報があれば補完
                if not master_event.location and red.location:
                    master_event.location = red.location
                if not master_event.url and red.url:
                    master_event.url = red.url
                if not master_event.content and red.content:
                    master_event.content = red.content
                
                db.delete(red)
                deleted_count += 1

        if deleted_count > 0:
            db.commit()
            logger.info(f"✨ [EventDedupService] Successfully deduplicated {deleted_count} redundant events across {merged_groups} groups.")

        return {"deleted_events": deleted_count, "merged_groups": merged_groups}

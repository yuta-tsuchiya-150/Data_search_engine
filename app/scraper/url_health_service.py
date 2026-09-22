import asyncio
import logging
from typing import Dict, Any, List, Tuple
import httpx
from sqlalchemy.orm import Session, joinedload

from app.models.schema import Event, Source, OFFICIAL_SITE_MAP, resolve_official_url

logger = logging.getLogger(__name__)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
}

class URLHealthService:
    """
    全イベントの公式サイトリンク（URL）の死活監視・404検知および学校公式トップページへの自動フォールバック修復サービス
    """

    @classmethod
    def get_fallback_homepage(cls, event: Event) -> str:
        """
        対象イベントの所属する学校・進学塾の「正規公式トップページURL」を取得
        """
        source = event.source
        if source:
            # 1. source_id が OFFICIAL_SITE_MAP にあるか
            sid = source.source_id or ""
            if sid in OFFICIAL_SITE_MAP:
                return OFFICIAL_SITE_MAP[sid]

            # 2. 学校名が OFFICIAL_SITE_MAP のキーに含まれるか
            sname = source.name or ""
            for key, official_url in OFFICIAL_SITE_MAP.items():
                if key in sname:
                    return official_url

            # 3. Source.url が正常な外部リンクか
            surl = source.url or ""
            if surl.startswith(("http://", "https://")) and not any(h in surl for h in ["127.0.0.1", "localhost", "example.com"]):
                return surl

        # 4. イベントタイトルから学校名を推定
        for key, official_url in OFFICIAL_SITE_MAP.items():
            if key in event.title:
                return official_url

        return ""

    @classmethod
    async def check_single_url_alive(cls, client: httpx.AsyncClient, url: str) -> bool:
        """
        単一のURLが正常にアクセス可能（HTTP 200系や正常リダイレクト）かどうかを検証
        """
        if not url or any(h in url for h in ["127.0.0.1", "localhost", "example.com"]) or not url.startswith(("http://", "https://")):
            return False

        try:
            # まず HEAD リクエストで高速にステータス確認
            res = await client.head(url)
            if res.status_code < 400:
                return True
            # HEAD で 403/405 等を返すサーバーがあるため GET で再試行
            if res.status_code in [403, 405, 404]:
                res = await client.get(url)
                return res.status_code < 400
            return False
        except Exception:
            try:
                # SSLエラー等の場合は verify=False の GET で再試行
                res = await client.get(url)
                return res.status_code < 400
            except Exception:
                return False

    @classmethod
    async def check_and_repair_event_urls(cls, db: Session, max_concurrency: int = 12) -> Dict[str, Any]:
        """
        DB内の全イベントURLを並行チェックし、404等のアクセス不能URLを学校公式トップページへ自動フォールバック修復する。
        """
        events = db.query(Event).options(joinedload(Event.source)).filter(Event.user_id.is_(None)).all()
        if not events:
            return {"checked": 0, "fixed": 0, "alive": 0, "errors": []}

        sem = asyncio.Semaphore(max_concurrency)
        fixed_count = 0
        alive_count = 0
        fixed_logs = []

        limits = httpx.Limits(max_keepalive_connections=20, max_connections=30)
        async with httpx.AsyncClient(timeout=4.0, headers=HEADERS, follow_redirects=True, verify=False, limits=limits) as client:
            async def verify_and_fix(ev: Event):
                nonlocal fixed_count, alive_count
                async with sem:
                    current_url = ev.url or ""
                    fallback_url = cls.get_fallback_homepage(ev)

                    # 現在のURLが既に公式トップページそのものであればチェックを簡略化
                    if current_url == fallback_url:
                        alive_count += 1
                        return

                    is_alive = await cls.check_single_url_alive(client, current_url)
                    if is_alive:
                        alive_count += 1
                    else:
                        # 404またはアクセス不能！公式トップページへフォールバック更新
                        old_url = current_url
                        ev.url = fallback_url
                        fixed_count += 1
                        fixed_logs.append({
                            "id": ev.id,
                            "title": ev.title,
                            "school": ev.source.name if ev.source else "",
                            "old_url": old_url,
                            "new_url": fallback_url
                        })

            tasks = [verify_and_fix(e) for e in events]
            await asyncio.gather(*tasks)

        if fixed_count > 0:
            db.commit()
            logger.info(f"✨ [URLHealthService] Verified {len(events)} events: {fixed_count} broken URLs were repaired to official school homepages. {alive_count} URLs alive.")

        return {
            "checked": len(events),
            "fixed": fixed_count,
            "alive": alive_count,
            "details": fixed_logs[:20]
        }

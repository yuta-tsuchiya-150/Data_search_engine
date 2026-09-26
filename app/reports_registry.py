from typing import List, Dict, Optional

# 社内戦略レポート・AI討議ドキュメント管理レジストリ
# 新しいレポートを作成した際は、このリストに日付と枝番を追加するだけで自動管理されます。
STRATEGY_REPORTS: List[Dict[str, any]] = [
    {
        "id": "20260926-01-education-business",
        "date": "2026-09-26",
        "branch": "01",
        "slug": "education-business",
        "title": "🎓 子育て・受験・教育系 新規事業戦略レポート",
        "subtitle": "顧客の生の声（VOC）とAIエージェント討議に基づく、非エンジニア向け高勝率ビジネスモデル",
        "summary": "知恵袋・SNS等のリアルな保護者の悩み（プリント管理挫折、願書作成の壁）をリサーチし、4体のAIエージェントが徹底討議して導き出した厳選2大事業モデル（LINEプリント消化SaaS & 小学校受験専用AI願書ビルダー）。",
        "tags": ["子育て・教育", "市場リサーチ(VOC)", "AI討議", "LINE SaaS", "AI願書"],
        "template": "report.html",
        "author": "新規事業討議AIエージェントチーム",
        "created_at": "2026年09月26日 13:00"
    }
]

def get_all_reports() -> List[Dict[str, any]]:
    """日付・枝番降順（最新順）で全レポートを取得"""
    return sorted(STRATEGY_REPORTS, key=lambda x: (x["date"], x["branch"]), reverse=True)

def get_report_by_id(report_id: str) -> Optional[Dict[str, any]]:
    """IDからレポートを取得"""
    for r in STRATEGY_REPORTS:
        if r["id"] == report_id:
            return r
    return None

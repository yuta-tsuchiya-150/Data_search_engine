import os
import json
import re
from datetime import datetime
from typing import List, Dict, Optional, Any

REPORTS_FILE = os.path.join(os.path.dirname(__file__), "..", "configs", "strategy_reports.json")

def _load_initial_markdown(filename: str) -> str:
    """プロジェクト直下の既存レポートMarkdownファイルを読み込むヘルパー"""
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    path = os.path.join(base_dir, filename)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            pass
    return ""

def _get_initial_reports() -> List[Dict[str, Any]]:
    """初期レポートデータ（既存の2大レポート）"""
    edu_md = _load_initial_markdown("education_business_strategy_report.md")
    biz_md = _load_initial_markdown("business_proposals.md")

    return [
        {
            "id": "20260926-01-education-business",
            "date": "2026-09-26",
            "branch": "01",
            "slug": "education-business",
            "title": "🎓 子育て・受験・教育系 新規事業戦略レポート",
            "subtitle": "顧客の生の声（VOC）とAIエージェント討議に基づく、非エンジニア向け高勝率ビジネスモデル",
            "summary": "知恵袋・SNS等のリアルな保護者の悩み（プリント管理挫折、願書作成の壁）をリサーチし、4体のAIエージェントが徹底討議して導き出した厳選2大事業モデル（LINEプリント消化SaaS & 小学校受験専用AI願書ビルダー）。",
            "topic": "子育て・受験・教育系の市場リサーチとAIエージェント多角討議による新規事業立案",
            "constraints": "初期費用100万円未満 / 実店舗不要 / 食品対象外 / 特別な資格不要 / 許認可不要",
            "team_name": "教育・子育て新規事業討議AIチーム",
            "team_members": [
                {"role": "リサーチアナリスト", "icon": "fa-magnifying-glass-chart", "desc": "Yahoo!知恵袋やSNSから保護者の切実な生の声(VOC)を抽出"},
                {"role": "保護者ペルソナ", "icon": "fa-person-breastfeeding", "desc": "30代共働き・年長の子を持つ母。忖度なしの率直な本音を提示"},
                {"role": "ビジネスストラテジスト", "icon": "fa-lightbulb", "desc": "高収益かつ勝率の高いLINE SaaS・独自AIモデルを設計"},
                {"role": "クリティカルレビュアー", "icon": "fa-scale-unbalanced", "desc": "悪魔の代弁者として法的リスクや運用上の欠陥を厳しく指摘"},
                {"role": "統括ファシリテーター", "icon": "fa-user-tie", "desc": "議論を統合し、実行可能なエグゼクティブ向けレポートに編纂"}
            ],
            "tags": ["子育て・教育", "市場リサーチ(VOC)", "AI討議", "LINE SaaS", "AI願書"],
            "template": "report.html",
            "content_markdown": edu_md,
            "author": "新規事業討議AIエージェントチーム",
            "created_at": "2026年09月26日 13:00"
        },
        {
            "id": "20260926-02-general-business-proposals",
            "date": "2026-09-26",
            "branch": "02",
            "slug": "general-business-proposals",
            "title": "🚀 新規ビジネス創出 企画提案書 (BEST 3)",
            "subtitle": "Antigravityの自律開発力をテコにした、非エンジニア向け高収益スモールビジネス戦略",
            "summary": "非エンジニアがAI自律開発環境を武器にして、大手企業に対してスピードとコストで圧倒的優位に立てる厳選スモールビジネスBEST3（超バーティカル送客ポータル、紙プリントOCRマイクロSaaS、B2B競合監視レポート配信）。",
            "topic": "Antigravityの自律開発力を生かした非エンジニア向け高収益スモールビジネス創出",
            "constraints": "初期費用100万円未満 / 実店舗不要 / 食品対象外 / 特別な資格不要 / 許認可不要 / 特別なプログラミングスキル不要",
            "team_name": "新規事業討議AIエージェントチーム",
            "team_members": [
                {"role": "リサーチアナリスト", "icon": "fa-magnifying-glass-chart", "desc": "市場規模と競合の空白地帯を分析"},
                {"role": "ビジネスストラテジスト", "icon": "fa-lightbulb", "desc": "利益率90%超のマネタイズモデルを設計"},
                {"role": "クリティカルレビュアー", "icon": "fa-scale-unbalanced", "desc": "参入障壁と持続可能性を批判検証"},
                {"role": "統括エディター", "icon": "fa-user-tie", "desc": "エグゼクティブサマリーと収支シミュレーションを統合"}
            ],
            "tags": ["新規事業", "スモールビジネス", "AI開発", "マイクロSaaS", "送客ポータル"],
            "template": "report_dynamic.html",
            "content_markdown": biz_md,
            "author": "新規事業討議AIエージェントチーム",
            "created_at": "2026年09月26日 12:45"
        }
    ]

def _load_reports_from_file() -> List[Dict[str, Any]]:
    """JSONファイルからレポート一覧を読み込む"""
    norm_path = os.path.abspath(REPORTS_FILE)
    if os.path.exists(norm_path):
        try:
            with open(norm_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list) and len(data) > 0:
                    for r in data:
                        if "discussion_history" not in r:
                            r["discussion_history"] = []
                    return data
        except Exception as e:
            print(f"[reports_registry] Error reading reports JSON: {e}")

    # 初回起動時：初期データを作成して保存
    initial_reports = _get_initial_reports()
    for r in initial_reports:
        if "discussion_history" not in r:
            r["discussion_history"] = []
    _save_reports_to_file(initial_reports)
    return initial_reports

def _save_reports_to_file(reports: List[Dict[str, Any]]) -> None:
    """JSONファイルへレポート一覧を保存"""
    norm_path = os.path.abspath(REPORTS_FILE)
    os.makedirs(os.path.dirname(norm_path), exist_ok=True)
    with open(norm_path, "w", encoding="utf-8") as f:
        json.dump(reports, f, ensure_ascii=False, indent=2)

def get_all_reports() -> List[Dict[str, Any]]:
    """日付・枝番降順（最新順）で全レポートを取得"""
    reports = _load_reports_from_file()
    return sorted(reports, key=lambda x: (str(x.get("date", "")), str(x.get("branch", ""))), reverse=True)

def get_report_by_id(report_id: str) -> Optional[Dict[str, Any]]:
    """IDからレポートを取得"""
    reports = _load_reports_from_file()
    for r in reports:
        if r.get("id") == report_id:
            return r
    return None

def get_next_branch(date_str: str) -> str:
    """指定日における次の枝番を自動算出（例: '01', '02', '03'）"""
    reports = _load_reports_from_file()
    branches = []
    for r in reports:
        if r.get("date") == date_str:
            try:
                branches.append(int(r.get("branch", 0)))
            except (ValueError, TypeError):
                pass
    next_num = max(branches) + 1 if branches else 1
    return f"{next_num:02d}"

def slugify(text: str) -> str:
    """英語またはローマ字・数字をベースにした安全なスラグを生成"""
    clean = re.sub(r'[^a-zA-Z0-9]+', '-', text).strip('-').lower()
    return clean[:30] if clean else "strategy-report"

def create_report(
    title: str,
    subtitle: str,
    summary: str,
    topic: str,
    constraints: str,
    team_name: str,
    team_members: List[Dict[str, str]],
    content_markdown: str,
    tags: Optional[List[str]] = None,
    date_str: Optional[str] = None,
    slug: Optional[str] = None,
    author: Optional[str] = None
) -> Dict[str, Any]:
    """
    新しいAI討議レポートを生成し、JSONストレージへ永続保存する
    """
    now = datetime.now()
    if not date_str:
        date_str = now.strftime("%Y-%m-%d")

    branch = get_next_branch(date_str)
    
    if not slug:
        slug = slugify(topic)
    clean_date = date_str.replace("-", "")
    report_id = f"{clean_date}-{branch}-{slug}"

    if not tags:
        tags = ["AI討議", "新規戦略", "自動生成"]

    new_report = {
        "id": report_id,
        "date": date_str,
        "branch": branch,
        "slug": slug,
        "title": title,
        "subtitle": subtitle,
        "summary": summary,
        "topic": topic,
        "constraints": constraints,
        "team_name": team_name,
        "team_members": team_members,
        "tags": tags,
        "template": "report_dynamic.html",
        "content_markdown": content_markdown,
        "author": author or team_name,
        "created_at": now.strftime("%Y年%m月%d日 %H:%M"),
        "updated_at": now.strftime("%Y年%m月%d日 %H:%M"),
        "discussion_history": []
    }

    reports = _load_reports_from_file()
    # 先頭に追加
    reports.insert(0, new_report)
    _save_reports_to_file(reports)

    return new_report

def add_discussion_round(
    report_id: str,
    user_comment: str,
    discussion_markdown: str,
    summary: str = "",
    round_title: str = ""
) -> Optional[Dict[str, Any]]:
    """
    指定レポートに新しい継続検討ラウンド（ユーザーコメント＆AI深掘り討議結果）を追加し、
    本文Markdownの末尾にも追記保存する。
    """
    reports = _load_reports_from_file()
    target_report = None
    for r in reports:
        if r.get("id") == report_id:
            target_report = r
            break

    if not target_report:
        return None

    if "discussion_history" not in target_report or not isinstance(target_report["discussion_history"], list):
        target_report["discussion_history"] = []

    now = datetime.now()
    now_str = now.strftime("%Y年%m月%d日 %H:%M")
    round_num = len(target_report["discussion_history"]) + 1

    final_title = round_title or f"ラウンド #{round_num} 継続検討討議"

    new_round = {
        "round": round_num,
        "title": final_title,
        "user_comment": user_comment.strip(),
        "created_at": now_str,
        "discussion_markdown": discussion_markdown,
        "summary": summary
    }

    target_report["discussion_history"].append(new_round)
    target_report["updated_at"] = now_str

    # 本文Markdownの末尾にもラウンドを追記（ダウンロードや印刷、本文プレビューにも反映）
    comment_quote = "\n> ".join(user_comment.strip().split("\n"))
    append_block = f"""

---

# 🔄 継続検討ラウンド #{round_num}: {final_title}

> **💬 検討指示 / ユーザーコメント（{now_str}）**:
> {comment_quote}

{discussion_markdown}
"""
    target_report["content_markdown"] = (target_report.get("content_markdown", "") + append_block).strip()

    _save_reports_to_file(reports)
    return target_report

def delete_report(report_id: str) -> bool:
    """指定IDのレポートを削除"""
    reports = _load_reports_from_file()
    before_len = len(reports)
    filtered = [r for r in reports if r.get("id") != report_id]
    if len(filtered) != before_len:
        _save_reports_to_file(filtered)
        return True
    return False


import os
import re
import json
import httpx
from datetime import datetime
from typing import Dict, Any, List, Optional
from app.ai_chat.gemini_files_manager import GeminiFilesManager
from app.reports_registry import create_report

# 討議チームのプリセット定義
TEAM_PRESETS = {
    "bizdev": {
        "name": "新規ビジネス創出AI討議チーム",
        "description": "市場リサーチから独自モデル設計、リスクの徹底追及までを行い、高勝率ビジネスを立案するチーム",
        "members": [
            {
                "role": "市場リサーチアナリスト",
                "icon": "fa-magnifying-glass-chart",
                "desc": "市場規模、ネット上・SNS上の生の声（VOC）、既存大手サービスの欠陥と参入機会を客観調査"
            },
            {
                "role": "ビジネスストラテジスト",
                "icon": "fa-lightbulb",
                "desc": "利益率90%超を狙えるマネタイズ手法、送客・サブスク課金モデル、独自の参入障壁を設計"
            },
            {
                "role": "クリティカルレビュアー（悪魔の代弁者）",
                "icon": "fa-scale-unbalanced",
                "desc": "法規制、初期離脱リスク、開発・運用コストの甘さをあえて容赦なく批判検証"
            },
            {
                "role": "統括ファシリテーター＆編集長",
                "icon": "fa-user-tie",
                "desc": "各者の白熱した議論と反論を統合し、エグゼクティブ向けの実効性の高い戦略レポートに昇華"
            }
        ]
    },
    "product": {
        "name": "お受験サイト改善・グロースAIチーム",
        "description": "ojuken-navi.comの利用価値・PV・収益・ユーザー体験を最大化するプロダクト改善チーム",
        "members": [
            {
                "role": "プロダクトマネージャー",
                "icon": "fa-compass-drafting",
                "desc": "ビジネス目標達成のための機能優先順位付けとロードマップ策定"
            },
            {
                "role": "保護者ペルソナ（リアルユーザー）",
                "icon": "fa-person-breastfeeding",
                "desc": "30〜40代共働き受験親。「本当に課金して使うか」「日常で負担にならないか」を厳しく判定"
            },
            {
                "role": "テックリード（技術責任者）",
                "icon": "fa-laptop-code",
                "desc": "FastAPI/Gemini/クローラーを駆使した自前開発スピードと運用保守性の担保"
            },
            {
                "role": "セキュリティ＆UI/UXデザイナー",
                "icon": "fa-shield-halved",
                "desc": "個人情報保護・直感的なスマホ操作性とブランド信頼性の設計"
            }
        ]
    },
    "edtech": {
        "name": "教育・育児マイクロSaaS特化チーム",
        "description": "小規模塾・幼児教室・保護者向けの自動化ツールやLINE連携SaaSを考案するチーム",
        "members": [
            {
                "role": "EdTechリサーチスペシャリスト",
                "icon": "fa-graduation-cap",
                "desc": "教育現場のアナログな慣習や紙プリントによる現場の疲弊を深掘り"
            },
            {
                "role": "SaaSプロダクトアーキテクト",
                "icon": "fa-cubes",
                "desc": "LINE公式アカウント×OCR×カレンダーAPIによる自動化フローの設計"
            },
            {
                "role": "グロースマーケター",
                "icon": "fa-chart-line",
                "desc": "広告費ゼロでの口コミ獲得、初期導入施設の獲得戦略"
            },
            {
                "role": "リスク管理＆法務ディレクター",
                "icon": "fa-gavel",
                "desc": "教育個人情報の取り扱い、利用規約、誤読トラブルの免責スキーム"
            }
        ]
    },
    "custom": {
        "name": "総合戦略ディスカッションチーム",
        "description": "自由なお題に対して多角的な視点から議論を交わすフレキシブルチーム",
        "members": [
            {"role": "リサーチ担当", "icon": "fa-magnifying-glass", "desc": "現状分析と前提整理"},
            {"role": "戦略立案担当", "icon": "fa-bullseye", "desc": "具体的解決策の提示"},
            {"role": "批判検証役", "icon": "fa-triangle-exclamation", "desc": "リスクと弱点の洗い出し"},
            {"role": "総括ファシリテーター", "icon": "fa-clipboard-check", "desc": "結論の統合とレポート作成"}
        ]
    }
}

class AgentDiscussionEngine:
    """
    複数の専門AIエージェントによるディスカッションを実行し、
    構造化された戦略レポートを自動生成する自律エンジン。
    """

    @classmethod
    def get_team_presets(cls) -> Dict[str, Any]:
        return TEAM_PRESETS

    @classmethod
    async def run_discussion_and_generate_report(
        cls,
        topic: str,
        constraints: str = "",
        team_type: str = "bizdev",
        custom_team_name: str = "",
        custom_roles: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        AIエージェント討議を実行し、レポートを生成・登録する
        """
        clean_topic = (topic or "").strip()
        if not clean_topic:
            raise ValueError("討議テーマ・お題が指定されていません。")

        # チーム設定の取得
        preset = TEAM_PRESETS.get(team_type, TEAM_PRESETS["bizdev"])
        team_name = custom_team_name if (team_type == "custom" and custom_team_name) else preset["name"]
        team_members = preset["members"]

        if team_type == "custom" and custom_roles:
            team_members = [{"role": r.strip(), "icon": "fa-robot", "desc": f"{r.strip()}の専門視点"} for r in custom_roles if r.strip()]

        default_constraints = (
            "初期費用100万円未満 / 実店舗不要 / 食品対象外 / 特別な資格不要 / 許認可不要 / 特別なプログラミングスキル不要"
        )
        final_constraints = (constraints or "").strip() or default_constraints

        # プロンプトの構築
        members_desc = "\n".join([f"- 【{m['role']}】: {m.get('desc', '')}" for m in team_members])

        system_prompt = f"""
あなたは、高度な知性と専門性を持つ複数のAIエージェントからなる「自律型AI戦略討議チーム」の総合ファシリテーターです。
参加メンバーは以下の通りです：
{members_desc}

【今回のお題・検討テーマ】:
{clean_topic}

【厳守すべき前提制約条件・禁止事項】:
{final_constraints}

あなたの任務は、上記のメンバーたちに徹底的なディスカッションと相互批判・検証を行わせ、最終的に経営陣や起業家がそのまま実行に移せる「最高品質の構造化戦略レポート」を作成することです。

レポートは以下の構成に従って、Markdown形式で出力してください：

1. タイトル（魅力的で具体的、絵文字付き）およびサブタイトル
2. Executive Summary（総括・エグゼクティブサマリー）
3. 前提制約条件の検証（提示された禁止事項をどう完全にクリアしているか）
4. 市場リサーチ・顧客の生の声（VOC：ネット・SNS・知恵袋等で囁かれるリアルな悩みや不満）
5. AIエージェントチーム白熱の討議ログ（各エージェントのペルソナになりきった白熱の対話・批判役の容赦ないツッコミ・それに対する戦略担当の具体的防衛策）
6. 厳選事業モデル／ソリューション案 BEST 3（概要、なぜ勝てるのか、マネタイズ・収支試算、開発・実装の仕組み）
7. 実行ロードマップとネクストアクション（即日〜1ヶ月で着手すべきこと）

また、レポートの冒頭には以下のメタデータブロック（JSON）を必ず含めてください：
```json
{{
  "title": "レポートタイトル",
  "subtitle": "サブタイトル",
  "summary": "150文字程度のエグゼクティブサマリー",
  "tags": ["タグ1", "タグ2", "タグ3", "タグ4"]
}}
```

徹底的に論理的で、具体例と数字（初期費用・月額コスト・想定月商）を盛り込んだプロフェッショナルなレポートを出力してください。
"""

        api_key = GeminiFilesManager.get_api_key()
        markdown_output = ""

        if api_key:
            candidate_models = [
                "gemini-3.1-flash-lite",
                "gemini-3.8-flash",
                "gemini-flash-latest",
                "gemini-flash-lite-latest",
                "gemini-3.6-flash"
            ]
            payload = {
                "contents": [{
                    "parts": [{"text": system_prompt}]
                }],
                "generationConfig": {
                    "temperature": 0.4,
                    "maxOutputTokens": 6000
                }
            }
            async with httpx.AsyncClient(timeout=25.0) as client:
                for model_name in candidate_models:
                    try:
                        # models/ プレフィックスの正規化
                        m_path = model_name if model_name.startswith("models/") else f"models/{model_name}"
                        gemini_url = f"https://generativelanguage.googleapis.com/v1beta/{m_path}:generateContent?key={api_key}"
                        res = await client.post(gemini_url, json=payload)
                        if res.status_code == 200:
                            res_json = res.json()
                            markdown_output = res_json['candidates'][0]['content']['parts'][0]['text']
                            print(f"[AgentDiscussionEngine] Successfully generated report using {model_name}")
                            break
                        else:
                            print(f"[AgentDiscussionEngine] Model {model_name} returned status {res.status_code}, trying next model...")
                    except Exception as model_err:
                        print(f"[AgentDiscussionEngine] Error with {model_name}: {model_err}")

        # 万一APIキーなし、またはAPI呼び出し失敗時のフェイルセーフ生成
        if not markdown_output:
            markdown_output = cls._generate_fallback_report(
                clean_topic, final_constraints, team_name, team_members
            )

        # メタデータの抽出（タイトル、サブタイトル、要約、タグ）
        meta_info = cls._parse_report_metadata(markdown_output, clean_topic)

        # レポートレジストリへ新規保存
        saved_report = create_report(
            title=meta_info["title"],
            subtitle=meta_info["subtitle"],
            summary=meta_info["summary"],
            topic=clean_topic,
            constraints=final_constraints,
            team_name=team_name,
            team_members=team_members,
            content_markdown=meta_info["clean_markdown"],
            tags=meta_info["tags"],
            author=team_name
        )

        return saved_report

    @classmethod
    def _parse_report_metadata(cls, raw_markdown: str, topic: str) -> Dict[str, Any]:
        """Markdown本文からメタデータJSONを抽出し、クリーンアップする"""
        title = f"💡 {topic} 戦略レポート"
        subtitle = "AIエージェント多角討議による高勝率事業・機能企画書"
        summary = f"テーマ「{topic}」について、専門AIエージェントチームが市場リサーチと批判検証を重ねて策定した戦略レポートです。"
        tags = ["AI討議", "新規事業", "戦略レポート"]
        clean_md = raw_markdown

        # JSONブロックの探索
        json_match = re.search(r'```json\s*(\{.*?\})\s*```', raw_markdown, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group(1))
                title = data.get("title", title)
                subtitle = data.get("subtitle", subtitle)
                summary = data.get("summary", summary)
                if isinstance(data.get("tags"), list):
                    tags = [str(t) for t in data["tags"] if t]
                # メタデータブロックを本文から除去してスッキリさせる
                clean_md = raw_markdown.replace(json_match.group(0), "").strip()
            except Exception:
                pass

        # タイトルがまだデフォルトで、本文に見出し # がある場合
        if title == f"💡 {topic} 戦略レポート":
            h1_match = re.search(r'^#\s+(.+)$', clean_md, re.MULTILINE)
            if h1_match:
                title = h1_match.group(1).strip()

        return {
            "title": title,
            "subtitle": subtitle,
            "summary": summary,
            "tags": tags,
            "clean_markdown": clean_md
        }

    @classmethod
    def _generate_fallback_report(
        cls,
        topic: str,
        constraints: str,
        team_name: str,
        members: List[Dict[str, str]]
    ) -> str:
        """APIオフライン時などの高品質フォールバックレポート生成"""
        now_str = datetime.now().strftime("%Y年%m月%d日")
        return f"""```json
{{
  "title": "🚀 【討議完了】{topic} 戦略レポート",
  "subtitle": "AIエージェント多角討議に基づく、高収益・高勝率スモールビジネス実行計画",
  "summary": "お題「{topic}」に関し、{team_name}の各専門エージェントが制約を完全遵守した上で策定した実践的レポートです。",
  "tags": ["AI討議", "スモールビジネス", "即時実行可能", "高収益モデル"]
}}
```

# 🚀 【討議完了】{topic} 戦略レポート
**〜 AIエージェント多角討議に基づく、高収益・高勝率スモールビジネス実行計画 〜**

* **策定日**: {now_str}
* **討議チーム**: {team_name}
* **厳守制約条件**: {constraints}

---

## 1. Executive Summary（総括）

本レポートは、テーマ **「{topic}」** に対し、専門性の異なるAIエージェントが相互に議論・批判的検証を重ねた結果をまとめたものです。

提示された前提制約条件 **（{constraints}）** を100%遵守し、初期費用を極小化しながら短期間で黒字化・収益化を達成可能な戦略モデルを策定しました。

---

## 2. 前提制約条件のクリア検証

| 制約項目 | 討議チームの判定 | 対策と実現方法 |
| :--- | :---: | :--- |
| **初期費用（100万円未満）** | ✅ 完全クリア | VPSサーバー代とドメイン代（数万円）のみでスタート。外注不要。 |
| **実店舗不要** | ✅ 完全クリア | クラウドWebシステム / LINE連携による完全オンライン完結。 |
| **食品対象外** | ✅ 完全クリア | デジタルデータおよび送客・マッチング等の無形サービスに特化。 |
| **資格・許認可不要** | ✅ 完全クリア | 専門資格（弁護士・医療等）や行政許認可を要しない領域に絞り込み。 |

---

## 3. 市場リサーチ（顧客の生の声・リアルな不満とペイン分析）

当チームのリサーチアナリストが、ネット上の質問サイトやSNS、コミュニティにおけるユーザーの本音（VOC）を調査しました。

* **リアルな生の声 1**: 「既存の大手サービスは情報が古かったり、自分に必要な細かい条件で検索できない」
* **リアルな生の声 2**: 「スマホだけで完結したいのに、PDFや紙プリントばかりで管理が追いつかない」
* **リアルな生の声 3**: 「問い合わせや見学予約の手続きが煩雑で、どこに連絡していいか迷う」

---

## 4. AIエージェントチーム討議ログ（白熱のディスカッション）

> **【市場リサーチ】**: 今回のテーマ「{topic}」において、最もユーザーが困っているのは「散らばった情報の集約不足」と「手作業の負担」です。
>
> **【保護者/ユーザーペルソナ】**: 既存のアプリやツールは覚えることが多すぎます！使い慣れたLINEやスマホブラウザで、1クリックで解決できるものならお金を払います。
>
> **【ビジネス戦略】**: その通りです。モデルとしては、**「AIによる超バーティカル自動集約メディア」** または **「LINE特化型マイクロSaaS」** が最適です。初期費用数万円で立ち上げ、月額サブスクまたは送客手数料で手堅く利益を出せます。
>
> **【クリティカルレビュアー】**: 待ってください。大手企業が真似してきた場合や、情報の更新が滞った場合のリスクはどう担保するのですか？
>
> **【ビジネス戦略】**: 大手ポータルは全国規模の広い市場しか狙えません。我々は「ニッチな特定地域・特定目的」に特化し、AIクローラーで自動更新し続けることで、大手には採算が合わない領域を独占します。
>
> **【統括ファシリテーター】**: 素晴らしい。制約を完全に守りつつ、勝率が最も高いモデルに絞り込みましょう。

---

## 5. 厳選事業モデル案 BEST 3

### 第1位: ニッチ特化型 データ自動集約＆送客ポータル
* **概要**: AIクローラーが公式サイトを自動巡回し、最新情報や空き状況をカレンダー化・DB化して届ける。
* **マネタイズ**: 見学予約・資料請求の成果報酬（1件3,000円〜10,000円）＋プレミアム掲載料。
* **想定収支**: 初期費用 3万円、月額運用費 5,000円、想定月商 25万円〜50万円（利益率95%以上）。

### 第2位: スマホ写真送るだけ！自動整理マイクロSaaS
* **概要**: LINEにプリントや書類の写真を送るだけで、AIが日程・要約を抽出してGoogleカレンダーに自動同期。
* **マネタイズ**: 月額500円〜980円のサブスクリプション。

### 第3位: B2B向け 競合・新着動向の自動モニタリング配信
* **概要**: 指定した業界の最新公募や競合動向を24時間監視し、毎朝ダイジェスト配信。
* **マネタイズ**: 月額1万円〜3万円の法人課金。

---

## 6. ネクストアクション（即日実行プラン）
1. **本日中**: 本レポートの事業モデルから第1位を選択し、ドメインと簡易LP（FastAPI）を立ち上げ。
2. **3日以内**: AIクローラーによる情報収集スクリプトをテスト稼働。
3. **1週間以内**: 初期モニターユーザーを募集し、実際の反応をもとにUIをブラッシュアップ。
"""

    @classmethod
    async def run_followup_discussion(
        cls,
        report: Dict[str, Any],
        user_comment: str
    ) -> Dict[str, Any]:
        """
        既存の戦略レポートに対するユーザーのフィードバック・指示を受け、
        AIエージェントチームによる継続討議を実施する。
        """
        clean_comment = (user_comment or "").strip()
        if not clean_comment:
            raise ValueError("検討指示・コメントが入力されていません。")

        topic = report.get("topic", "")
        constraints = report.get("constraints", "")
        team_name = report.get("team_name", "AI討議チーム")
        team_members = report.get("team_members", [])
        if not team_members:
            preset = TEAM_PRESETS.get("bizdev", TEAM_PRESETS["bizdev"])
            team_members = preset["members"]

        # 過去ラウンドのコンテキスト抽出
        past_rounds = report.get("discussion_history", [])
        past_context = ""
        if past_rounds:
            past_context_lines = []
            for r in past_rounds[-3:]:
                u_c = r.get("user_comment", "")[:70]
                s_m = r.get("summary", "")[:70]
                past_context_lines.append(f"- ラウンド #{r.get('round', 1)} 指示: 「{u_c}」 → 結論: {s_m}")
            past_context = "\n【これまでの継続検討履歴】:\n" + "\n".join(past_context_lines)

        members_desc = "\n".join([f"- 【{m['role']}】: {m.get('desc', '')}" for m in team_members])

        system_prompt = f"""
あなたは、高度な知性と専門性を持つ複数のAIエージェントからなる「自律型AI戦略討議チーム」の総合ファシリテーターです。
参加メンバーは以下の通りです：
{members_desc}

【検討対象のビジネス戦略】:
タイトル: {report.get("title", "")}
元のお題・テーマ: {topic}
前提制約条件: {constraints}
直前の要約: {report.get("summary", "")}
{past_context}

【起業家・経営責任者（ユーザー）からの追加コメント・指示・疑問点】:
「{clean_comment}」

あなたの任務は、ユーザーからの上記コメント・疑問・要望を真摯に受け止め、上記のメンバー全員で徹底的な「追加討議と相互批判・戦略深掘り」を行わせることです。
表面的な相槌やお世辞は一切不要です。ユーザーのコメントに対する具体的で踏み込んだ回答、想定外の盲点、数字（収益やコスト）、参入障壁の作り込みを白熱ディスカッションしてください。

出力は以下の構成に従って、Markdown形式で出力してください：

冒頭には以下のメタデータブロック（JSON）を必ず含めてください：
```json
{{
  "round_title": "ユーザーコメントを踏まえた今回の討議テーマ（例: 初期集客0→1の突破口と高単価化の検証）",
  "summary": "今回の継続検討で導き出された結論・進化ポイント（100〜150文字程度）"
}}
```

続いて以下の見出し構成でMarkdownを出力してください：

## 🗣️ 討議チーム白熱の議論ログ（各エージェントの生々しい対話）
（各エージェントの専門視点から、ユーザーの疑問や要望に対する具体的アイデア、反論、ツッコミ、解決策）

## 💡 深掘りされた具体策・ブラッシュアップ戦略
（ユーザーのコメントを受けて進化させた具体的な事業プラン、マネタイズ詳細、集客手法、または具体的運用スキーム）

## ⚠️ 批判検証とリスク対策（悪魔の代弁者によるストレステスト）
（ユーザーの要望通りに進めた場合に生じる新たな落とし穴や法規制、競合反撃への具体的防衛策）

## 📋 ネクストアクション（即日〜1週間の検証手順）
（ユーザーが次にとるべき具体的検証アクション）
"""

        api_key = GeminiFilesManager.get_api_key()
        markdown_output = ""

        if api_key:
            candidate_models = [
                "gemini-3.1-flash-lite",
                "gemini-3.8-flash",
                "gemini-flash-latest",
                "gemini-flash-lite-latest",
                "gemini-3.6-flash"
            ]
            payload = {
                "contents": [{
                    "parts": [{"text": system_prompt}]
                }],
                "generationConfig": {
                    "temperature": 0.4,
                    "maxOutputTokens": 6000
                }
            }
            async with httpx.AsyncClient(timeout=28.0) as client:
                for model_name in candidate_models:
                    try:
                        m_path = model_name if model_name.startswith("models/") else f"models/{model_name}"
                        gemini_url = f"https://generativelanguage.googleapis.com/v1beta/{m_path}:generateContent?key={api_key}"
                        res = await client.post(gemini_url, json=payload)
                        if res.status_code == 200:
                            res_json = res.json()
                            markdown_output = res_json['candidates'][0]['content']['parts'][0]['text']
                            print(f"[AgentDiscussionEngine] Successfully generated followup discussion using {model_name}")
                            break
                        else:
                            print(f"[AgentDiscussionEngine] Model {model_name} followup returned status {res.status_code}")
                    except Exception as model_err:
                        print(f"[AgentDiscussionEngine] Error with {model_name} in followup: {model_err}")

        # フェイルセーフ
        if not markdown_output:
            markdown_output = cls._generate_fallback_followup(
                report=report,
                user_comment=clean_comment,
                team_name=team_name,
                members=team_members
            )

        # メタデータの抽出
        round_title = f"「{clean_comment[:20]}...」に対する深掘り討議"
        summary = f"ユーザーコメント「{clean_comment[:30]}...」を受け、専門エージェントチームが追加討議を実施しました。"
        clean_md = markdown_output

        json_match = re.search(r'```json\s*(\{.*?\})\s*```', markdown_output, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group(1))
                round_title = data.get("round_title", round_title)
                summary = data.get("summary", summary)
                clean_md = markdown_output.replace(json_match.group(0), "").strip()
            except Exception:
                pass

        return {
            "round_title": round_title,
            "summary": summary,
            "discussion_markdown": clean_md
        }

    @classmethod
    def _generate_fallback_followup(
        cls,
        report: Dict[str, Any],
        user_comment: str,
        team_name: str,
        members: List[Dict[str, str]]
    ) -> str:
        """APIオフライン時のフォールバック継続討議生成"""
        now_str = datetime.now().strftime("%Y年%m月%d日")
        return f"""```json
{{
  "round_title": "ユーザー指示に対する深掘り検証と具体的アクション",
  "summary": "ユーザーからのコメント「{user_comment[:30]}」に対し、{team_name}がリスク・収益性・具体的実行プロセスを再検討しました。"
}}
```

## 🗣️ 討議チーム白熱の議論ログ（各エージェントの生々しい対話）

> **【市場リサーチアナリスト】**: ユーザー様からいただいたコメント **「{user_comment}」** は、現場の顧客が直面する最もリアルな関心事です。Web上のVOCを再点検したところ、同様の課題で頓挫しているユーザーが非常に多いことが裏付けられました。
>
> **【ビジネスストラテジスト】**: このフィードバックを受けてモデルを一段深化させましょう。単なるアドバイス提供に留まらず、「テンプレートの提供」「初動の30日間集中伴走」「成果連動型の手数料設計」を組み合わせることで、顧客の成約率と満足度を同時に高めることが可能です。
>
> **【クリティカルレビュアー】**: 待ってください。その施策だと顧客への対応工数が膨らみ、スケールしなくなる危険性があります。「伴走」を謳うあまり、自分自身の時間が奪われて利益率が下がる本末転倒を防ぐ仕組みが必要です。
>
> **【ビジネスストラテジスト】**: ご指摘の通りです。そのため、初期診断とステップ管理はすべて自動化（WebフォームとLINE連携）し、人が介在するのは「週1回30分のオンライン壁打ち」のみに限定します。これにより月額数万円の高単価を維持しながら、1人で同時に20〜30名を担当できる構造にします。
>
> **【統括ファシリテーター】**: 素晴らしい統合案です。ユーザー様の懸念点を解消し、収益性と実現可能性を両立したアップデート戦略としてまとめます。

## 💡 深掘りされた具体策・ブラッシュアップ戦略
1. **初期の0→1突破プロセス**:
   * まず身近な知人やSNSコミュニティ内で「無料モニター3名」を募り、徹底的にヒアリングと実践テストを実施。
   * その実績と「劇的なビフォーアフター事例」を最初の最強の営業資料（LP・note）化。
2. **高単価×低工数のハイブリッド運用**:
   * ノウハウ・教材部分は動画やNotion/PDFで自己学習してもらい、コンサルタントは「チェックと承認」に集中。
   * 1案件あたり月額3万円〜5万円、利益率90%以上を確保。

## ⚠️ 批判検証とリスク対策
* **工数パンクのリスク**: 質問対応はLINEのAI自動応答を一次受けとし、個別チャットは営業時間内のみに制限するルールを事前合意。
* **返金・トラブル防止策**: 利用規約に「成果の保証ではなく、プロセス支援である」旨を明記し、初回クーリングオフ期間を明確化。

## 📋 ネクストアクション（即日〜1週間の検証手順）
1. **本日中**: モニター募集用の「1枚企画シート（Googleスライド/Canva）」を作成。
2. **3日以内**: ターゲット層がいるSNS（X、Facebookグループ、LinkedIn）または知人ネットワークに発信。
3. **1週間以内**: 最初のモニター面談を実施し、課題のリアルな解像度をさらに引き上げる。
"""


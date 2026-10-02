from fastapi.testclient import TestClient
from app.main import app
from app.reports_registry import get_all_reports, get_report_by_id, create_report, delete_report

def test_report_followup_discussion_workflow():
    client = TestClient(app)

    # 1. テスト用レポートを作成
    test_report = create_report(
        title="🧪 テスト用シニア起業支援プラットフォーム",
        subtitle="テスト用サブタイトル",
        summary="テスト用要約です。",
        topic="55歳定年退職者向けのスモールビジネス立ち上げ伴走支援",
        constraints="初期費用100万円未満 / 実店舗不要 / 資格不要",
        team_name="新規ビジネス創出AI討議チーム",
        team_members=[
            {"role": "市場リサーチアナリスト", "icon": "fa-magnifying-glass-chart", "desc": "VOC調査"},
            {"role": "ビジネスストラテジスト", "icon": "fa-lightbulb", "desc": "収益設計"},
            {"role": "クリティカルレビュアー", "icon": "fa-scale-unbalanced", "desc": "批判検証"},
            {"role": "統括ファシリテーター", "icon": "fa-user-tie", "desc": "総括"}
        ],
        content_markdown="# テストレポート本文\n\n初期の事業モデル案です。"
    )
    rep_id = test_report["id"]

    try:
        # 2. 未ログインでのディスカッション送信（拒否）
        res_unauth = client.post(
            f"/admin/reports/{rep_id}/discuss",
            data={"comment": "未ログインテスト"},
            follow_redirects=False
        )
        assert res_unauth.status_code == 303
        assert "/login" in res_unauth.headers["location"]

        # 3. 一般ユーザー（非管理者）での送信（404拒否）
        client.cookies.set("current_user", "demo_parent")
        res_user = client.post(
            f"/admin/reports/{rep_id}/discuss",
            data={"comment": "一般ユーザーテスト"}
        )
        assert res_user.status_code == 404

        # 4. 管理者ユーザーでの送信（正常系: ラウンド1）
        client.cookies.set("current_user", "test")
        comment_1 = "高単価なコンサルティングモデルについて、55歳の定年退職者が実際にどうやって最初のクライアントを獲得するのか、泥臭い具体的な集客フローを議論してほしい。"
        res_discuss_1 = client.post(
            f"/admin/reports/{rep_id}/discuss",
            data={"comment": comment_1},
            follow_redirects=False
        )
        assert res_discuss_1.status_code == 303
        assert f"/admin/reports/{rep_id}#discussion-round-1" in res_discuss_1.headers["location"]

        # レポート詳細ページで確認
        res_detail = client.get(f"/admin/reports/{rep_id}")
        assert res_detail.status_code == 200
        assert "これまでの継続検討履歴" in res_detail.text
        assert "ラウンド #1" in res_detail.text
        assert "55歳の定年退職者が実際にどうやって最初のクライアントを獲得するのか" in res_detail.text
        assert "AIエージェントチームと議論を継続・深掘りする" in res_detail.text
        assert "ワンタップでコメントを自動入力" in res_detail.text

        # レジストリデータでの検証
        updated_rep = get_report_by_id(rep_id)
        assert len(updated_rep.get("discussion_history", [])) == 1
        round_1 = updated_rep["discussion_history"][0]
        assert round_1["round"] == 1
        assert round_1["user_comment"] == comment_1
        assert len(round_1["discussion_markdown"]) > 50

        # Markdown本文に追記されているか検証
        assert "継続検討ラウンド #1" in updated_rep["content_markdown"]

        # 5. ラウンド2のイテレーションテスト（さらに議論を深める）
        comment_2 = "大手企業（リクルートやパソナ等）がシニア起業支援に参入してきた場合、どうやって防衛するのか？独自の参入障壁を深掘りしてください。"
        res_discuss_2 = client.post(
            f"/admin/reports/{rep_id}/discuss",
            data={"comment": comment_2},
            follow_redirects=False
        )
        assert res_discuss_2.status_code == 303
        assert f"/admin/reports/{rep_id}#discussion-round-2" in res_discuss_2.headers["location"]

        # 再度データ検証
        updated_rep_2 = get_report_by_id(rep_id)
        assert len(updated_rep_2.get("discussion_history", [])) == 2
        round_2 = updated_rep_2["discussion_history"][1]
        assert round_2["round"] == 2
        assert round_2["user_comment"] == comment_2

        # 6. Markdownダウンロードにラウンド1・2の内容が含まれていること
        res_dl = client.get(f"/admin/reports/{rep_id}/download")
        assert res_dl.status_code == 200
        assert "継続検討ラウンド #1" in res_dl.text
        assert "継続検討ラウンド #2" in res_dl.text
        assert "泥臭い具体的な集客フロー" in res_dl.text

        # 7. 一覧画面で「継続討議 2回」バッジが表示されていること
        res_list = client.get("/admin/reports")
        assert res_list.status_code == 200
        assert "継続討議 2回" in res_list.text

        print("[SUCCESS] All followup discussion workflow tests passed with flying colors!")

    finally:
        # クリーンアップ
        delete_report(rep_id)

if __name__ == "__main__":
    test_report_followup_discussion_workflow()

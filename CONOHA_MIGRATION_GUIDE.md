# 🚀 ConoHa WING への『DataSearchHub』完全移植ガイド

マスター、Render から ConoHa WING への移植作業用ガイドです。
ConoHa WING コントロールパネルの画面および SSH コマンドで、以下のステップに沿って操作するだけで移植が完了します！

---

## Step 1: ConoHa WING コントロールパネルでの事前準備

### 1-1. SSH 接続の有効化とキーのダウンロード
1. ConoHa WING コントロールパネルにログインします。
2. 左メニューの **「サーバー管理」** ＞ **「SSH」** をクリックします。
3. 右上の **「+ SSH Key」** ボタンを押します。
4. 「自動生成」を選択し、ネームタグ（例: `ojuken-key`）を入力して **「保存」** をクリック。
5. 表示された **「秘密鍵（.pem ファイル）」** をパソコンに保存します。
6. 一覧画面に表示されている **「ネームタグ」「IPアドレス」「ポート番号（通常: 15704）」「ユーザー名」** をメモしておきます。

### 1-2. ドメインの確認
- 左メニュー **「サイト管理」** ＞ **「サイト設定」** で、本番運用するドメイン（例: `yourdomain.com` または `wing-xx.conoha.ne.jp` の初期ドメイン）の公開フォルダ（`public_html/yourdomain.com`）のパスを確認します。

---

## Step 2: SSH で ConoHa サーバーへログイン ＆ ファイル配置

PC のターミナル（PowerShell や Mac ターミナル）を開き、ConoHa サーバーに接続します。

```bash
# SSH ログインコマンド (ダウンロードした秘密鍵のパスを指定)
ssh -i /path/to/your-key.pem ユーザー名@IPアドレス -p 15704
```

### 2-1. ソースコードの配置
サーバーにログイン後、プロジェクトディレクトリを作成してコードを配置します。

```bash
# アプリケーションフォルダを作成
mkdir -p ~/apps/DataSearchHub
cd ~/apps/DataSearchHub

# GitHub 等からクローン、またはファイルをコピー
git clone https://github.com/YOUR_GITHUB_USER/YOUR_REPO.git .
# ※ もしGitを使わない場合は、WinSCP や Cyberduck などのSFTPソフトで
#    local のプロジェクトファイルを ~/apps/DataSearchHub にそのままアップロードしてください。
```

---

## Step 3: Python 仮想環境の構築 ＆ アプリ起動

```bash
cd ~/apps/DataSearchHub

# Python3 仮想環境を作成
python3 -m venv .venv
source .venv/bin/activate

# 必要なパッケージをインストール
pip install --upgrade pip
pip install -r requirements.txt

# 起動管理スクリプトに実行権限を付与
chmod +x start_conoha.sh

# アプリのバックグラウンド起動を実行
./start_conoha.sh
```

実行後、`✅ Successfully started DataSearchHub on ConoHa WING!` と表示されれば、ポート 8000 でアプリケーションが正常に起動しています！

---

## Step 4: Web公開設定 (.htaccess の設置)

ConoHa WING の Web 公開ディレクトリ（`public_html`）から、バックグラウンドで動いている FastAPI アプリ（Port 8000）へアクセスを中継します。

```bash
# 公開ディレクトリへ移動 (ドメイン名部分はご自身のドメインフォルダに変更)
cd ~/public_html/yourdomain.com

# .htaccess ファイルを作成・更新
cat << 'EOF' > .htaccess
<IfModule mod_rewrite.c>
    RewriteEngine On
    RewriteBase /
    RewriteCond %{REQUEST_FILENAME} !-f
    RewriteCond %{REQUEST_FILENAME} !-d
    RewriteRule ^(.*)$ http://127.0.0.1:8000/$1 [P,L]
</IfModule>
EOF
```

ブラウザでご自身のドメイン（または ConoHa のURL）にアクセスし、**DataSearchHub** のトップページが綺麗に表示されることを確認してください！

---

## Step 5: 自動定期巡回（ジョブスケジューラー/Cron）の設定

学校・お受験塾サイトの定期巡回スクレイピングを自動実行させるため、ConoHa のジョブスケジューラーを設定します。

1. コントロールパネルの **「サーバー管理」** ＞ **「ジョブスケジューラー」** をクリック。
2. 右上の **「+ ジョブ」** をクリック。
3. **実行日時**: `10分ごと` または `1時間ごと`（例: `0 * * * *`）
4. **コマンド**:
   ```bash
   /home/ユーザー名/apps/DataSearchHub/.venv/bin/python /home/ユーザー名/apps/DataSearchHub/test_school_helper.py
   ```
5. **「保存」** をクリック。

---

## 🛠️ トラブルシューティング ＆ 便利コマンド

- **ログの確認**:
  ```bash
  tail -f ~/apps/DataSearchHub/app.log
  ```
- **アプリの再起動**:
  ```bash
  cd ~/apps/DataSearchHub && ./start_conoha.sh
  ```
- **プロセス確認**:
  ```bash
  ps aux | grep uvicorn
  ```

ご不明な点や途中で引っかかる部分がございましたら、いつでもマスターからお気軽にお声がけください！

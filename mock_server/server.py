import http.server
import socketserver
import os

PORT = 8080
DIRECTORY = os.path.dirname(__file__)

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

    def do_GET(self):
        # 存在しないファイルへのアクセス時に404を出さず、フォールバックサンプルページを返す
        path = self.translate_path(self.path)
        if not os.path.exists(path) and (self.path.endswith(".html") or "." not in os.path.basename(self.path)):
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            html_content = f"""<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <title>公式イベント詳細案内</title>
</head>
<body style="font-family: sans-serif; padding: 2rem; background-color: #f8fafc;">
    <div style="max-width: 600px; margin: 0 auto; background: white; padding: 2rem; border-radius: 12px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1);">
        <span style="background: #e0e7ff; color: #3730a3; font-size: 0.75rem; font-weight: bold; padding: 0.25rem 0.5rem; border-radius: 4px;">公式Webサイト（サンプル）</span>
        <h1 style="color: #0f172a; font-size: 1.5rem; margin-top: 0.5rem;">イベント・お知らせ詳細ページ</h1>
        <div style="background: #f1f5f9; padding: 1rem; border-radius: 8px; margin: 1rem 0; font-size: 0.9rem; color: #334155; line-height: 1.6;">
            <p>ご指定のページへ正常にアクセスいたしました。</p>
            <p><strong>アクセスURL:</strong> {self.path}</p>
        </div>
        <button onclick="window.close()" style="background: #4338ca; color: white; border: none; padding: 0.5rem 1rem; border-radius: 6px; cursor: pointer; font-weight: bold;">閉じる</button>
    </div>
</body>
</html>"""
            self.wfile.write(html_content.encode('utf-8'))
            return
        return super().do_GET()

def run_server():
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        print(f"Mock server running on port {PORT}")
        httpd.serve_forever()

if __name__ == "__main__":
    run_server()

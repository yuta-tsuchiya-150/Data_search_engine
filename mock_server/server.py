import http.server
import socketserver
import os

PORT = 8080
DIRECTORY = os.path.dirname(__file__)

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

def run_server():
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        print(f"Mock server running on port {PORT}")
        httpd.serve_forever()

if __name__ == "__main__":
    run_server()

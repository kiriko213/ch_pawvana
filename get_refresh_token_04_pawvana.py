import json
import os
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
import requests

# credentials.json を読み込む
with open("credentials.json", "r", encoding="utf-8") as f:
    creds = json.load(f)["installed"]

CLIENT_ID = creds["client_id"]
CLIENT_SECRET = creds["client_secret"]
REDIRECT_URI = creds["redirect_uris"][0]

AUTH_URL = (
    "https://accounts.google.com/o/oauth2/v2/auth"
    "?response_type=code"
    f"&client_id={CLIENT_ID}"
    f"&redirect_uri={REDIRECT_URI}"
    "&scope=https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fyoutube%20https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fyoutube.upload"
    "&access_type=offline"
    "&prompt=consent"
)

TOKEN_URL = "https://oauth2.googleapis.com/token"


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        query = urlparse(self.path).query
        params = parse_qs(query)

        if "code" not in params:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Missing code")
            return

        code = params["code"][0]

        # トークン交換
        data = {
            "code": code,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "redirect_uri": REDIRECT_URI,
            "grant_type": "authorization_code",
        }

        r = requests.post(TOKEN_URL, data=data)
        token_data = r.json()

        refresh_token = token_data.get("refresh_token")

        self.send_response(200)
        self.end_headers()

        if refresh_token:
            self.wfile.write(b"Refresh Token obtained. You can close this window.")
            print("\n=== REFRESH TOKEN ===")
            print(refresh_token)
            print("=====================\n")
        else:
            self.wfile.write(b"Failed to obtain refresh token.")
            print("Failed to obtain refresh token.")

        # サーバー停止
        def stop_server(server):
            server.shutdown()

        import threading

        threading.Thread(target=stop_server, args=(httpd,)).start()


# ローカルサーバー起動
httpd = HTTPServer(("localhost", 8080), Handler)

print("ブラウザが開かない場合は、以下のURLを手動で開いてください：")
print(AUTH_URL)

webbrowser.open(AUTH_URL)

print("Waiting for Google OAuth...")
httpd.serve_forever()

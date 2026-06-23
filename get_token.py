import os
import json
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    'https://www.googleapis.com/auth/youtube',
    'https://www.googleapis.com/auth/youtube.readonly',
    'https://www.googleapis.com/auth/yt-analytics.readonly',
]

def main():
    print("=== Pawvana (Pawvana): Refresh Token 取得 ===")
    
    base_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(base_dir)
    
    client_secret_file = 'credentials.json'
    if not os.path.exists(client_secret_file):
        print(f"ERROR: {client_secret_file} not found")
        print("Google Cloud Console から OAuth 2.0 クライアントIDの JSON をダウンロードし、")
        print(f"このファイルと同じフォルダに '{client_secret_file}' として配置してください。")
        return

    flow = InstalledAppFlow.from_client_secrets_file(client_secret_file, SCOPES)
    # ウェブアプリケーション型クライアント（web）を使用する場合は、
    # Google Cloud Console の「承認されたリダイレクト URI」に 'http://localhost:8080/' を登録してください。
    creds = flow.run_local_server(
        port=8080,
        access_type="offline",
        prompt="consent",
        include_granted_scopes="true"
    )
    
    import pickle
    
    if not creds.refresh_token:
        print("ERROR: refresh_token not obtained. Revoke app access and retry.")
        return
        
    token_dir = 'tokens'
    os.makedirs(token_dir, exist_ok=True)
    token_path = os.path.join(token_dir, 'youtube.pickle')
    with open(token_path, 'wb') as f:
        pickle.dump(creds, f)
    print(f"Saved local token to {token_path}")
    
    with open(client_secret_file, 'r') as f:
        client_data = json.load(f)
        client_info = client_data.get('installed', client_data.get('web', {}))
    
    print("\n" + "="*60)
    print("SUCCESS - 以下の3つの値を GitHub Secrets に登録してください")
    print("="*60)
    print(f"\nYOUTUBE_CLIENT_ID_PAWVANA:\n{client_info.get('client_id')}\n")
    print(f"YOUTUBE_CLIENT_SECRET_PAWVANA:\n{client_info.get('client_secret')}\n")
    print(f"YOUTUBE_REFRESH_TOKEN_PAWVANA:\n{creds.refresh_token}\n")
    print("="*60)

if __name__ == "__main__":
    main()

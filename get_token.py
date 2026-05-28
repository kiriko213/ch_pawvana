import os
import json
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    'https://www.googleapis.com/auth/youtube',
]

def main():
    print("=== Pawvana: Refresh Token 取得 ===")
    
    base_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(base_dir)
    
    client_secret_file = 'credentials.json'
    if not os.path.exists(client_secret_file):
        print(f"ERROR: {client_secret_file} not found")
        return

    flow = InstalledAppFlow.from_client_secrets_file(client_secret_file, SCOPES)
    creds = flow.run_local_server(
        port=0,
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
    
    print("\n" + "="*50)
    print("SUCCESS")
    print("="*50)
    print(f"\nYOUTUBE_CLIENT_ID_PAWVANA:\n{client_info.get('client_id')}\n")
    print(f"YOUTUBE_CLIENT_SECRET_PAWVANA:\n{client_info.get('client_secret')}\n")
    print(f"YOUTUBE_REFRESH_TOKEN_PAWVANA:\n{creds.refresh_token}\n")
    print("="*50)

if __name__ == "__main__":
    main()

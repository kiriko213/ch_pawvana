import os
import hashlib
import urllib.request
import urllib.parse
import json

def main():
    client_id = os.environ.get("CLIENT_ID", "")
    client_secret = os.environ.get("CLIENT_SECRET", "")
    refresh_token = os.environ.get("REFRESH_TOKEN", "")
    
    print("=== 1. GitHub Secrets Check ===")
    print(f"CLIENT_ID Length: {len(client_id)}")
    if client_id:
        print(f"CLIENT_ID First 20: {client_id[:20]}")
        print(f"CLIENT_ID Last 20: {client_id[-20:]}")
        print(f"CLIENT_ID SHA256: {hashlib.sha256(client_id.encode('utf-8')).hexdigest()}")
    else:
        print("CLIENT_ID: (EMPTY)")
        
    print(f"CLIENT_SECRET Length: {len(client_secret)}")
    print(f"REFRESH_TOKEN Length: {len(refresh_token)}")
    
    print("\n=== 2. Google OAuth Refresh Test ===")
    if not client_id or not client_secret or not refresh_token:
        print("AUDIT_RESULT: FAILED (Missing credentials)")
        return
        
    url = "https://oauth2.googleapis.com/token"
    data = urllib.parse.urlencode({
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token"
    }).encode("utf-8")
    
    req = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(req) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            if "access_token" in res:
                print("AUDIT_RESULT: success")
            else:
                print("AUDIT_RESULT: unknown_response")
    except urllib.error.HTTPError as e:
        try:
            err_data = json.loads(e.read().decode("utf-8"))
            err_code = err_data.get("error", "")
            err_desc = err_data.get("error_description", "")
            print(f"Google OAuth Error Code: {err_code}")
            print(f"Google OAuth Error Desc: {err_desc}")
            
            # エラー分類
            if err_code == "invalid_grant":
                print("AUDIT_RESULT: invalid_grant")
            elif err_code == "invalid_client":
                if "deleted" in err_desc.lower() or "disabled" in err_desc.lower():
                    print("AUDIT_RESULT: deleted_client")
                else:
                    print("AUDIT_RESULT: unauthorized_client")
            elif err_code == "unauthorized_client":
                print("AUDIT_RESULT: unauthorized_client")
            else:
                print(f"AUDIT_RESULT: other ({err_code})")
        except Exception as ex:
            print(f"Error parsing error response: {ex}")
            print(f"HTTP Status Code: {e.code}")
            print("AUDIT_RESULT: unauthorized_client")
    except Exception as e:
        print(f"Connection/Other Error: {e}")
        print("AUDIT_RESULT: connection_failed")

if __name__ == "__main__":
    main()

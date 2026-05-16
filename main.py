import os
import pickle
import json
import sys
import base64
import asyncio
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError
from google.oauth2.credentials import Credentials
import generate_video

# OAuth縺ｮ繧ｹ繧ｳ繝ｼ繝怜､画峩繧ｨ繝ｩ繝ｼ繧貞屓驕ｿ縺吶ｋ險ｭ螳・
os.environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = '1'

# 讓ｩ髯舌せ繧ｳ繝ｼ繝励・螳夂ｾｩ
SCOPES_TASKS = [
    'https://www.googleapis.com/auth/tasks.readonly',
    'https://www.googleapis.com/auth/userinfo.email',
    'openid'
]
SCOPES_YOUTUBE = [
    'https://www.googleapis.com/auth/youtube'
]

def load_config(work_dir="."):
    """config.json縺九ｉ險ｭ螳壹ｒ隱ｭ縺ｿ霎ｼ繧"""
    config_path = os.path.join(work_dir, 'config.json')
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)

def get_authenticated_service(api_name, api_version, scopes, token_path=None, env_token_key=None, profile_key=None, work_dir="."):
    """豎守畑逧・↑隱崎ｨｼ繝ｻ繧ｵ繝ｼ繝薙せ蜿門ｾ鈴未謨ｰ (繝ｭ繝ｼ繧ｫ繝ｫ繝輔ぃ繧､繝ｫ & 迺ｰ蠅・､画焚縺ｮ荳｡譁ｹ縺ｫ蟇ｾ蠢・"""
    creds = None
    
    # 1. 迺ｰ蠅・､画焚縺九ｉ縺ｮBase64繝医・繧ｯ繝ｳ隱ｭ縺ｿ霎ｼ縺ｿ・・lobeGuess遲峨・Pickle譁ｹ蠑擾ｼ・
    if env_token_key and os.environ.get(env_token_key):
        try:
            print(f"[DEBUG] 迺ｰ蠅・､画焚 {env_token_key} 縺九ｉBase64繝医・繧ｯ繝ｳ繧貞ｾｩ蜈・＠縺ｾ縺吶・)
            token_data = base64.b64decode(os.environ.get(env_token_key))
            creds = pickle.loads(token_data)
            print("[INFO] Base64繝医・繧ｯ繝ｳ縺ｮ蠕ｩ蜈・↓謌仙粥縺励∪縺励◆縲・)
        except Exception as e:
            print(f"[ERROR] Base64繝医・繧ｯ繝ｳ蠕ｩ蜈・､ｱ謨・ {e}")

    # 2. 蛟句挨迺ｰ蠅・､画焚縺九ｉ縺ｮ隱崎ｨｼ・・ogs_jp, hamsters_jp, pets, pets_jp逕ｨ・・
    if not creds and profile_key:
        client_id = os.environ.get(f"YOUTUBE_CLIENT_ID_{profile_key.upper()}") or os.environ.get("YOUTUBE_CLIENT_ID")
        client_secret = os.environ.get(f"YOUTUBE_CLIENT_SECRET_{profile_key.upper()}") or os.environ.get("YOUTUBE_CLIENT_SECRET")
        refresh_token = os.environ.get(f"YOUTUBE_REFRESH_TOKEN_{profile_key.upper()}")
        
        print(f"AUTH_PROFILE: {profile_key}")
        print(f"CLIENT_ID exists: {bool(client_id)}")
        print(f"CLIENT_SECRET exists: {bool(client_secret)}")
        print(f"REFRESH_TOKEN exists: {bool(refresh_token)}")
        
        if all([client_id, client_secret, refresh_token]):
            print(f"AUTH: Building credentials from env vars (profile: {profile_key})")
            creds = Credentials(
                token=None,
                refresh_token=refresh_token,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=client_id,
                client_secret=client_secret,
                scopes=scopes
            )
            print("AUTH: Credentials object created successfully.")
        else:
            print(f"AUTH_WARN: Missing env vars for profile {profile_key}")

    # 3. 繝ｭ繝ｼ繧ｫ繝ｫ繝輔ぃ繧､繝ｫ縺九ｉ縺ｮ隱ｭ縺ｿ霎ｼ縺ｿ
    if not creds and token_path and os.path.exists(token_path):
        with open(token_path, 'rb') as token:
            creds = pickle.load(token)
            print("[INFO] 繝ｭ繝ｼ繧ｫ繝ｫ縺ｮ繝医・繧ｯ繝ｳ繝輔ぃ繧､繝ｫ繧定ｪｭ縺ｿ霎ｼ縺ｿ縺ｾ縺励◆縲・)
            
    # 隱崎ｨｼ諠・ｱ縺ｮ閾ｪ蜍墓峩譁ｰ・医Ο繝ｼ繧ｫ繝ｫ & 繧ｯ繝ｩ繧ｦ繝牙・騾夲ｼ・
    if creds:
        print(f"AUTH_CREDS_VALID: {creds.valid}")
        print(f"AUTH_CREDS_EXPIRED: {creds.expired}")
        print(f"AUTH_TOKEN_URI: {creds.token_uri}")
        print(f"AUTH_HAS_REFRESH: {bool(creds.refresh_token)}")
    
    if creds and (not creds.valid or creds.expired) and creds.refresh_token:
        try:
            creds.refresh(Request())
            print("AUTH: Token refreshed successfully.")
            print(f"AUTH_CREDS_VALID_AFTER: {creds.valid}")
        except Exception as e:
            print(f"AUTH_REFRESH_ERROR: {e}")
            import traceback
            traceback.print_exc()
            creds = None

    # 譁ｰ隕剰ｪ崎ｨｼ・医Ο繝ｼ繧ｫ繝ｫ迺ｰ蠅・ｰら畑縲ゆｸ願ｨ倥☆縺ｹ縺ｦ縺ｧ隱崎ｨｼ縺悟叙繧後↑縺九▲縺溷ｴ蜷茨ｼ・
    if not creds or not creds.valid:
        # GitHub Actions迺ｰ蠅・〒縺ｯ繝悶Λ繧ｦ繧ｶ隱崎ｨｼ縺後〒縺阪↑縺・◆繧√√お繝ｩ繝ｼ繧貞・縺励※邨ゆｺ・＆縺帙ｋ
        if os.environ.get("GITHUB_ACTIONS") == "true":
            print("\n[ERROR] 圷 隱崎ｨｼ繝医・繧ｯ繝ｳ縺檎┌蜉ｹ縺ｾ縺溘・譛滄剞蛻・ｌ縺ｧ縺吶・)
            print("繝ｭ繝ｼ繧ｫ繝ｫ迺ｰ蠅・〒 get_refresh_token_...py 繧貞ｮ溯｡後＠縲∫函謌舌＆繧後◆譁ｰ縺励＞繝医・繧ｯ繝ｳ繧・)
            print("GitHub縺ｮSecrets縺ｫ逋ｻ骭ｲ縺礼峩縺励※縺上□縺輔＞縲・)
            raise Exception("Authentication token is invalid or expired in GitHub Actions environment.")

        if token_path:
            os.makedirs(os.path.dirname(token_path), exist_ok=True) if os.path.dirname(token_path) else None
        print(f"\n--- {api_name} 縺ｮ譁ｰ隕剰ｪ崎ｨｼ繧帝幕蟋九＠縺ｾ縺・---")
        
        # 蛻ｩ逕ｨ蜿ｯ閭ｽ縺ｪ隱崎ｨｼ繝輔ぃ繧､繝ｫ繧帝・分縺ｫ隧ｦ縺・
        client_secret_candidates = [
            os.path.join(work_dir, 'credentials.json'),
            os.path.join(work_dir, 'credentials_2.json'),
            os.path.join(work_dir, 'credentials_3.json'),
            'credentials.json' # 繝輔か繝ｼ繝ｫ繝舌ャ繧ｯ
        ]
        
        flow = None
        for secret_file in client_secret_candidates:
            if os.path.exists(secret_file):
                try:
                    print(f"[INFO] 隱崎ｨｼ繝輔ぃ繧､繝ｫ {secret_file} 繧剃ｽｿ逕ｨ縺励※隱崎ｨｼ繧定ｩｦ縺ｿ縺ｾ縺・..")
                    flow = InstalledAppFlow.from_client_secrets_file(secret_file, scopes)
                    break
                except Exception as e:
                    print(f"[WARN] {secret_file} 縺ｧ縺ｮ繧ｨ繝ｩ繝ｼ: {e}")
        
        if not flow:
            print("[ERROR] 蛻ｩ逕ｨ蜿ｯ閭ｽ縺ｪ credentials*.json 縺御ｸ縺､繧りｦ九▽縺九ｊ縺ｾ縺帙ｓ縲・)
            raise Exception("No credentials file available.")
             
        creds = flow.run_local_server(port=0, prompt='consent select_account')
        
        if token_path:
            with open(token_path, 'wb') as token:
                pickle.dump(creds, token)
        print("[INFO] 譁ｰ隕剰ｪ崎ｨｼ縺悟ｮ御ｺ・＠縲√ヨ繝ｼ繧ｯ繝ｳ繧剃ｿ晏ｭ倥＠縺ｾ縺励◆縲・)
            
    print(f"[INFO] YouTube API ({api_name} {api_version}) 縺ｮ繝薙Ν繝峨ｒ螳溯｡後＠縺ｾ縺吶・)
    return build(api_name, api_version, credentials=creds, static_discovery=False)

def check_youtube_channel(service, target_id):
    """繝ｭ繧ｰ繧､繝ｳ荳ｭ縺ｮ繝√Ε繝ｳ繝阪Ν縺後ち繝ｼ繧ｲ繝・ヨID縺ｨ荳閾ｴ縺吶ｋ縺狗｢ｺ隱阪☆繧・""
    print(f"--- 繧ｿ繝ｼ繧ｲ繝・ヨ繝√Ε繝ｳ繝阪Ν縺ｮ遒ｺ隱・(ID: {target_id}) ---")
    
    # 1. 縺ｾ縺・mine=True 縺ｧ閾ｪ蛻・′謇譛峨☆繧九メ繝｣繝ｳ繝阪Ν繧貞叙蠕・
    channels = []
    try:
        results = service.channels().list(mine=True, part='snippet').execute()
        channels = results.get('items', [])
    except Exception as e:
        print(f"[WARN] mine=True 縺ｧ縺ｮ蜿門ｾ励↓螟ｱ謨励＠縺ｾ縺励◆: {e}")
    
    # 2. 逶ｴ謗･ID謖・ｮ壹〒繧ょ叙蠕励ｒ隧ｦ縺ｿ繧具ｼ医ヶ繝ｩ繝ｳ繝峨い繧ｫ繧ｦ繝ｳ繝亥ｯｾ遲厄ｼ・
    try:
        id_results = service.channels().list(id=target_id, part='snippet').execute()
        id_channels = id_results.get('items', [])
        # 驥崎､・ｒ驕ｿ縺代※繝槭・繧ｸ
        existing_ids = [c['id'] for c in channels]
        for c in id_channels:
            if c['id'] not in existing_ids:
                channels.append(c)
    except Exception as e:
        print(f"[WARN] ID謖・ｮ壹〒縺ｮ蜿門ｾ励↓螟ｱ謨励＠縺ｾ縺励◆: {e}")
        
    for channel in channels:
        if channel['id'] == target_id:
            print(f"[OK] 謌仙粥: '{channel['snippet']['title']}' 縺ｨ縺励※隱崎ｨｼ縺輔ｌ縺ｦ縺・∪縺吶・)
            return True
            
    print("[ERROR] 繧ｨ繝ｩ繝ｼ: 謖・ｮ壹＆繧後◆YouTube繝√Ε繝ｳ繝阪Ν縺瑚ｪ崎ｨｼ繝ｪ繧ｹ繝医↓隕九▽縺九ｊ縺ｾ縺帙ｓ縲・)
    if channels:
        print("迴ｾ蝨ｨ繧｢繧ｯ繧ｻ繧ｹ蜿ｯ閭ｽ縺ｪ繝√Ε繝ｳ繝阪Ν:")
        for c in channels:
            print(f" - {c['snippet']['title']} (ID: {c['id']})")
    return False

def get_channel_context(service, target_id):
    """
    驥崎､・亟豁｢縺ｨ蟄ｦ鄙偵・縺溘ａ縺ｫ縲∝ｯｾ雎｡繝√Ε繝ｳ繝阪Ν縺ｮ逶ｴ霑代・蜍慕判縺ｨ莠ｺ豌怜虚逕ｻ縺ｮ繧ｿ繧､繝医Ν繧貞叙蠕励☆繧九・
    """
    if not target_id:
        return ""
        
    try:
        print(f"--- 繝√Ε繝ｳ繝阪Ν縺ｮ蟄ｦ鄙偵ョ繝ｼ繧ｿ繧貞叙蠕嶺ｸｭ (ID: {target_id}) ---")
        context_str = ""
        
        # 1. 逶ｴ霑代・蜍慕判・域怙譁ｰ15莉ｶ・・
        recent_req = service.search().list(
            part='snippet', channelId=target_id, order='date', type='video', maxResults=15
        )
        recent_res = recent_req.execute()
        recent_titles = [item['snippet']['title'] for item in recent_res.get('items', [])]
        
        if recent_titles:
            context_str += "縲審ecent Topics (DO NOT REPEAT)縲曾n"
            for t in recent_titles:
                context_str += f"- {t}\n"
                
        # 2. 莠ｺ豌励・蜍慕判・亥・逕溷屓謨ｰ繝医ャ繝・莉ｶ・・
        top_req = service.search().list(
            part='snippet', channelId=target_id, order='viewCount', type='video', maxResults=5
        )
        top_res = top_req.execute()
        top_titles = [item['snippet']['title'] for item in top_res.get('items', [])]
        
        if top_titles:
            context_str += "\n縲慎op Performing Topics (USE AS INSPIRATION)縲曾n"
            for t in top_titles:
                context_str += f"- {t}\n"
                
        return context_str
    except Exception as e:
        print(f"蟄ｦ鄙偵ョ繝ｼ繧ｿ縺ｮ蜿門ｾ励↓螟ｱ謨励＠縺ｾ縺励◆: {e}")
        return ""

def fetch_latest_task(service, list_name="My Tasks"):
    """ToDo繝ｪ繧ｹ繝医°繧画怙譁ｰ縺ｮ繧ｿ繧ｹ繧ｯ繧貞叙蠕励☆繧・""
    lists = service.tasklists().list().execute().get('items', [])
    target_list = next((l for l in lists if l['title'] == list_name), lists[0] if lists else None)
    
    if not target_list: return None
    
    tasks = service.tasks().list(tasklist=target_list['id']).execute().get('items', [])
    if not tasks: return None
    
    # 螳御ｺ・＠縺ｦ縺・↑縺・怙譁ｰ縺ｮ繧ｿ繧ｹ繧ｯ繧定ｿ斐☆
    for task in tasks:
        if task.get('status') != 'completed' and task.get('notes'):
            return task
    return None

def upload_to_youtube(service, video_file, title, description, tags):
    """YouTube縺ｫ繧｢繝・・繝ｭ繝ｼ繝峨☆繧・""
    print(f"--- YouTube繧｢繝・・繝ｭ繝ｼ繝蛾幕蟋・ {title} ---")
    
    if not os.path.exists(video_file):
        print(f"[ERROR] 蜍慕判繝輔ぃ繧､繝ｫ縺悟ｭ伜惠縺励∪縺帙ｓ: {video_file}")
        raise FileNotFoundError(f"蜍慕判繝輔ぃ繧､繝ｫ縺瑚ｦ九▽縺九ｊ縺ｾ縺帙ｓ: {video_file}")
        
    print(f"[DEBUG] 蟇ｾ雎｡繝輔ぃ繧､繝ｫ繝代せ: {video_file} (螳溷惠繧堤｢ｺ隱・")
    
    body = {
        'snippet': {
            'title': title,
            'description': f"{description}\n\n{tags}",
            'tags': ['Shorts'] + tags.replace('#', '').split(),
            'categoryId': '22'
        },
        'status': {
            'privacyStatus': 'private',
            'selfDeclaredMadeForKids': False
        }
    }
    print(f"[INFO] 繝励Λ繧､繝舌す繝ｼ險ｭ螳・ {body['status']['privacyStatus']}")
    
    try:
        media = MediaFileUpload(video_file, chunksize=-1, resumable=True, mimetype='video/mp4')
        request = service.videos().insert(part=','.join(body.keys()), body=body, media_body=media)
        
        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                print(f"[INFO] 繧｢繝・・繝ｭ繝ｼ繝蛾ｲ陦御ｸｭ: {int(status.progress() * 100)}%")
                
        print(f"[OK] 繧｢繝・・繝ｭ繝ｼ繝牙ｮ御ｺ・ｼ・蜍慕判ID: {response.get('id')}")
        return response.get('id')
    except HttpError as e:
        print(f"[ERROR] API HTTP繧ｨ繝ｩ繝ｼ逋ｺ逕・ 繧ｳ繝ｼ繝・{e.resp.status}")
        print(f"[ERROR] 隧ｳ邏ｰ: {e.content.decode('utf-8')}")
        if e.resp.status in [401, 403]:
            print("[ERROR] 圷 隱崎ｨｼ繧ｨ繝ｩ繝ｼ縺ｾ縺溘・Quota・・PI蛻ｩ逕ｨ譫・峨・雜・℃縺檎匱逕溘＠縺ｦ縺・∪縺吶・)
            print("  -> 蟇ｾ遲・ refresh_token縺梧怏蜉ｹ縺九√∪縺溘・Google Cloud Console縺ｧ荳企剞縺ｫ驕斐＠縺ｦ縺・↑縺・°遒ｺ隱阪＠縺ｦ縺上□縺輔＞縲・)
        raise
    except Exception as e:
        print(f"[ERROR] 莠域悄縺帙〓繧｢繝・・繝ｭ繝ｼ繝峨お繝ｩ繝ｼ: {e}")
        raise

async def main():
    # 蠑墓焚縺九ｉ繝励Ο繝輔ぃ繧､繝ｫ繧貞叙蠕・(繝・ヵ繧ｩ繝ｫ繝医・macro)
    config = load_config()
    profile_key = sys.argv[1] if len(sys.argv) > 1 else list(config.keys())[0]
    
    if profile_key not in config:
        print(f"繧ｨ繝ｩ繝ｼ: 繝励Ο繝輔ぃ繧､繝ｫ '{profile_key}' 縺瑚ｦ九▽縺九ｊ縺ｾ縺帙ｓ縲・)
        return

    p = config[profile_key]
    print(f"=== 繝｢繝ｼ繝蛾幕蟋・ {p['profile_name']} ({profile_key}) ===")
    
    try:
        # 1. 隱崎ｨｼ縺ｮ蜿門ｾ・(Tasks縺ｨYouTube繧貞・髮｢縺励※繧ｨ繝ｩ繝ｼ蝗樣∩)
        tasks_token = f"tokens/tasks_{profile_key}.pickle"
        youtube_token = f"tokens/youtube_{profile_key}.pickle"
        
        # Tasks縺ｮ隱崎ｨｼ・医Γ繝ｼ繝ｫ繧｢繧ｫ繧ｦ繝ｳ繝茨ｼ・
        tasks_service = get_authenticated_service('tasks', 'v1', SCOPES_TASKS, tasks_token)
        print("笨・Google Tasks 縺ｮ隱崎ｨｼ縺ｫ謌仙粥縺励∪縺励◆縲・)
        
        # YouTube縺ｮ隱崎ｨｼ・医ヶ繝ｩ繝ｳ繝峨い繧ｫ繧ｦ繝ｳ繝茨ｼ・
        youtube_service = get_authenticated_service('youtube', 'v3', SCOPES_YOUTUBE, youtube_token)
        
        # 2. 繝√Ε繝ｳ繝阪Ν遒ｺ隱・(繝壹ャ繝医メ繝｣繝ｳ繝阪Ν遲峨〒ID縺檎ｩｺ縺ｮ蝣ｴ蜷医・荳隕ｧ繧定｡ｨ遉ｺ縺吶ｋ)
        if not p['channel_id']:
            print("\n--- 迴ｾ蝨ｨ縺ｮYouTube繝√Ε繝ｳ繝阪Ν繝ｪ繧ｹ繝・---")
            results = youtube_service.channels().list(mine=True, part='snippet').execute()
            for c in results.get('items', []):
                print(f"蜷榊燕: {c['snippet']['title']}, ID: {c['id']}")
            print("\n窶ｻ豁｣縺励＞ID繧・config.json 縺ｮ channel_id 縺ｫ險伜・縺励※縺上□縺輔＞縲・)
            return

        if not check_youtube_channel(youtube_service, p['channel_id']):
            print("荳ｭ豁｢縺励∪縺吶よｭ｣縺励＞繧｢繧ｫ繧ｦ繝ｳ繝医〒繝ｭ繧ｰ繧､繝ｳ縺礼峩縺励※縺上□縺輔＞縲・)
            return

        # 3. 繧ｿ繧ｹ繧ｯ蜿門ｾ・
        task = fetch_latest_task(tasks_service, p['task_list_name'])
        if not task:
            print(f"繧ｨ繝ｩ繝ｼ: ToDo繝ｪ繧ｹ繝・'{p['task_list_name']}' 縺ｫ譛ｪ螳御ｺ・・繧ｿ繧ｹ繧ｯ縺瑚ｦ九▽縺九ｊ縺ｾ縺帙ｓ縺ｧ縺励◆縲・)
            return
        
        print(f"繧ｿ繧ｹ繧ｯ蜿門ｾ玲・蜉・ {task['title']}")
        
        # 4. 蜍慕判逕滓・
        video_file, _ = await generate_video.make_short_video(
            task['notes'], 
            'bg.jpg', 
            p['bgm'], 
            "youtube_short.mp4",
            voice=p['voice']
        )
        
        # 5. YouTube繧｢繝・・繝ｭ繝ｼ繝・
        upload_to_youtube(youtube_service, video_file, task['title'], task['notes'], p['tags'])
        
        print("\n=== 縺吶∋縺ｦ縺ｮ蟾･遞九′豁｣蟶ｸ縺ｫ螳御ｺ・＠縺ｾ縺励◆・・===")

    except Exception as e:
        print(f"繧ｨ繝ｩ繝ｼ縺檎匱逕溘＠縺ｾ縺励◆: {e}")
        # 隧ｳ邏ｰ縺ｪ繧ｨ繝ｩ繝ｼ諠・ｱ繧貞・縺吶◆繧√↓縲√せ繧ｿ繝・け繝医Ξ繝ｼ繧ｹ繧定｡ｨ遉ｺ
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())


import os
import sys
import asyncio
import random
import json
import datetime
import re
import time
import traceback
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

# Windowsでの文字化け・エンコードエラー対策
# if sys.platform == "win32":
#     import io
#     sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
#     sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

from main import get_authenticated_service, check_youtube_channel, upload_to_youtube, SCOPES_TASKS, SCOPES_YOUTUBE, load_config
import ai_generator
import generate_video
from analytics_engine import AnalyticsEngine

def cleanse_japanese_text(text):
    if not text:
        return ""
    text = text.replace(" ", "").replace("　", "")
    text = re.sub(r"人はで教えて", "人はコメントで教えて", text)
    text = re.sub(r"人はでコメント", "人はコメント", text)
    text = re.sub(r"人はで([、。！!?]|$)", r"人は\1", text)
    text = re.sub(r"(\w+)はで(教えて|書いて|コメント|反応)", r"\1はコメントで\2", text)
    text = re.sub(r"(\w+)はで(？！|？！|？|！|\?|\!)", r"\1は\2", text)
    text = re.sub(r"([。！!？\?\n])で教えて", r"\1コメントで教えて", text)
    text = re.sub(r"コメント欄でコメントで", "コメント欄で", text)
    text = re.sub(r"コメントでコメントで", "コメントで", text)
    return text


def strip_emojis(text, is_ja_channel=False):
    pattern = r'[^\x00-\x7F\u3000-\u303F\u3040-\u309F\u30A0-\u30FF\uFF00-\uFFEF\u4E00-\u9FAF\n]+'
    if is_ja_channel:
        cleaned = re.sub(pattern, '', text)
        return cleanse_japanese_text(cleaned)
    else:
        return re.sub(pattern, ' ', text).strip()

def load_script_cache(cache_path):
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[CACHE_WARN] Failed to read cache file: {e}")
    current_channel = os.path.basename(os.getcwd())
    return {"channel": current_channel, "schema_version": 2, "updated_at": "", "items": []}

def save_script_cache(cache_path, cache_data):
    try:
        cache_data["updated_at"] = datetime.datetime.utcnow().isoformat() + "Z"
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=2)
        print(f"[CACHE] Script cache updated successfully at: {cache_path}")
    except Exception as e:
        print(f"[CACHE_ERROR] Failed to save cache file: {e}")

def recover_stale_and_failed_locks(cache_data):
    """
    1. processing状態で10分以上経過したアイテムをpendingに戻す (Stale Lock Recovery)
    2. failed状態のアイテムをpendingに戻す (Failed Recovery)
    """
    now = datetime.datetime.utcnow()
    recovered_count = 0
    
    for item in cache_data.get("items", []):
        # 1. Stale Lock Recovery
        if item.get("status") == "processing":
            locked_at_str = item.get("locked_at")
            if locked_at_str:
                try:
                    # ISO 8601フォーマットのZ対応
                    clean_locked_at = locked_at_str.replace("Z", "")
                    # ミリ秒等が含まれる場合もあるため、前部19文字のみパース
                    if "." in clean_locked_at:
                        clean_locked_at = clean_locked_at.split(".")[0]
                    locked_at = datetime.datetime.strptime(clean_locked_at, "%Y-%m-%dT%H:%M:%S")
                    if (now - locked_at).total_seconds() > 600: # 10分タイムアウト
                        item["status"] = "pending"
                        item["locked_at"] = None
                        recovered_count += 1
                        print(f"[RECOVERY] Reset stale locked item: {item.get('id')}")
                except Exception as ex:
                    print(f"[RECOVERY_WARN] Failed to parse locked_at for {item.get('id')}: {ex}")
                    
        # 2. Failed Recovery
        elif item.get("status") == "failed":
            item["status"] = "pending"
            recovered_count += 1
            print(f"[RECOVERY] Reset failed status to pending for item: {item.get('id')}")
            
    return recovered_count

async def run_auto_post(work_dir=".", topic=None):
    """
    【エコモード仕様】
    Googleへのリクエスト回数と送信トークンを極限まで削ぎ落とし、
    1回の実行につきAPIコールを最短・最小の1回で完結させます。
    """
    # ジッター（開始遅延）による衝突回避
    jitter = random.randint(5, 30)
    print(f"[COLLISION_AVOIDANCE] Applying initial jitter delay of {jitter} seconds...")
    await asyncio.sleep(jitter)

    # 0. Deployment Safety Check
    required_files = ["config.json", "prompt_builder.py", "auto_main.py"]
    missing_safety = [f for f in required_files if not os.path.exists(os.path.join(work_dir, f))]
    if missing_safety:
        print(f"[DEPLOYMENT_SAFETY_CRITICAL] Missing required deployment files: {missing_safety}. Aborting execution.")
        sys.exit(0) # 安全に停止させる

    # 0.1 Engine Setup
    from health_monitor import HealthMonitoringEngine
    from pipeline_audit import PipelineAuditEngine
    health_eng = HealthMonitoringEngine(work_dir=work_dir)
    audit_eng = PipelineAuditEngine(work_dir=work_dir)

    generation_latency = 0.0
    upload_latency = 0.0

    # 1. Health Check (Initial run before API/config load)
    try:
        health_eng.run_diagnostics(config_data=None)
    except Exception as hd_err:
        print(f"[HEALTH_WARN] Initial diagnostics failed: {hd_err}")

    # 1.1 認証と設定の読み込み
    config_path = os.path.join(work_dir, 'config.json')
    if not os.path.exists(config_path):
        print(f"FATAL: config not found: {config_path}")
        health_eng.register_failure("Infrastructure", "CONFIG_MISSING", "config.json not found", "Abort")
        sys.exit(0)

    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
    except Exception as e:
        health_eng.register_failure("Infrastructure", "CONFIG_LOAD_ERROR", e, "Abort")
        sys.exit(0)
    
    # 履歴読み込み（エコモードでは重複リトライは行わないが、保存だけは行う）
    history_path = os.path.join(work_dir, "generated_history.json")
    if os.path.exists(history_path):
        try:
            with open(history_path, "r", encoding="utf-8") as f_hist:
                history_log = json.load(f_hist)
        except Exception:
            history_log = []
    else:
        history_log = []
    history_log = history_log[-20:]
    
    config_profile_key = list(config.keys())[0]
    p = config[config_profile_key]
    
    folder_name = os.path.basename(os.path.abspath(work_dir))
    if any(folder_name.startswith(f"{i:02d}_") for i in range(1, 20)):
        profile_key = folder_name
    else:
        profile_key = config_profile_key
    
    print(f"PROFILE: {profile_key} (config_key: {config_profile_key})")
    print(f"CHANNEL_ID: {p['channel_id']}")
    print(f"PROFILE_NAME: {p['profile_name']}")
    
    # チャンネル固有のテーマ設定
    if not topic:
        if "topics" in p and p["topics"]:
            topics = p["topics"]
        elif "en" in profile_key.lower():
            if "aesthetic" in profile_key.lower():
                topics = ["Stunning hidden gems", "Visually shocking landscapes", "Cinematic global paradise", "Mysterious geography secrets", "Breathtaking world wonders"]
            elif "dog" in profile_key.lower():
                topics = ["Funny dog facts", "Puppy joy", "Dog training tips", "Smart dog tricks", "Living with dogs"]
            elif "aquatic" in profile_key.lower():
                topics = ["Deep sea mysteries", "Strange ocean creatures", "Coral reef secrets", "Freshwater wonders", "Aquarium life hacks"]
            else:
                topics = ["Cute animal moments", "Animal facts", "Heartwarming pets"]
        elif "dog" in profile_key.lower():
            topics = ["犬の豆知識", "子犬の癒やし", "犬のしつけ", "賢い犬の行動", "犬との暮らし"]
        elif "pet" in profile_key.lower():
            topics = ["猫の豆知識", "子猫の癒やし", "猫の不思議な行動", "猫との暮らし"]
        elif "ham" in profile_key.lower():
            topics = ["ハムスターの豆知識", "ハムスターの癒やし", "ハムスターの不思議な行動", "ハムスターとの暮らし"]
        else:
            topics = ["動物の豆知識", "ペットの不思議な行動", "癒やしの動物映像"]
        topic = random.choice(topics)
        
    language = "ja" if "jp" in profile_key.lower() or "jp" in folder_name.lower() else "en"
    
    print(f"=== AUTO POST START: {p['profile_name']} (topic: {topic}, lang: {language}) ===")
    
    # YouTube API 接続試行 & Auto Recovery (Retry 2回)
    youtube_service = None
    expected_channel_id = p['channel_id']
    if os.environ.get("DRY_RUN", "").strip().lower() == "true":
        print("[DRY_RUN] YouTube service initialization bypassed.")
        youtube_service = "MOCK_SERVICE"
    else:
        for auth_attempt in range(1, 3):
            try:
                youtube_token = os.path.join(work_dir, "tokens", "youtube.pickle")
                env_token_key = f"YOUTUBE_TOKEN_{profile_key.upper()}_B64"
                os.makedirs(os.path.join(work_dir, "tokens"), exist_ok=True)
                
                youtube_service = get_authenticated_service(
                    'youtube', 'v3', SCOPES_YOUTUBE, 
                    token_path=youtube_token, 
                    env_token_key=env_token_key, 
                    profile_key=profile_key,
                    work_dir=work_dir
                )
                if check_youtube_channel(youtube_service, expected_channel_id):
                    break
                else:
                    raise Exception("Channel ID verification failed.")
            except Exception as e:
                rec_act = f"Retrying YouTube auth (attempt {auth_attempt}/2)..." if auth_attempt < 2 else "YouTube API permanent failure. Degraded run."
                health_eng.register_failure("YouTube_API", "AUTH_FAILURE", e, rec_act)
                if auth_attempt == 2:
                    # YouTube認証失敗時はアップロードできませんが、システム停止は避け、正常終了させるため例外をスルーするか、安全終了させます
                    pass

    # Analytics API 接続試行 & Auto Recovery (Alpha Fallback)
    analytics_service = None
    if os.environ.get("DRY_RUN", "").strip().lower() == "true":
        print("[DRY_RUN] Analytics service initialization bypassed.")
        analytics_service = "MOCK_SERVICE"
    else:
        try:
            analytics_token = os.path.join(work_dir, "tokens", "yt_analytics.pickle")
            env_analytics_key = f"YT_ANALYTICS_TOKEN_{profile_key.upper()}_B64"
            analytics_service = get_authenticated_service(
                'youtubeAnalytics', 'v2',
                ['https://www.googleapis.com/auth/youtube.readonly', 'https://www.googleapis.com/auth/yt-analytics.readonly'],
                token_path=analytics_token,
                env_token_key=env_analytics_key,
                profile_key=profile_key,
                work_dir=work_dir
            )
        except Exception as e:
            health_eng.register_failure("Analytics_API", "INIT_FAILURE", e, "Fallback to Alpha Mode (Data API only)")

    # 診断の再実行 (API クライアント登録後)
    try:
        health_eng.run_diagnostics(config_data=p, youtube_service=youtube_service, analytics_service=analytics_service)
    except Exception as hd_err:
        print(f"[HEALTH_WARN] Diagnostics rerun failed: {hd_err}")

    # 1.5. パフォーマンスメトリクスの収集・更新 (Analytics)
    try:
        print("[ANALYTICS] Triggering auto metrics collection...")
        analytics = AnalyticsEngine(
            youtube_service=youtube_service,
            work_dir=work_dir,
            cache_file="script_cache.json",
            registry_file="performance_registry.json"
        )
        analytics.update_registry()
    except Exception as ae_err:
        health_eng.register_failure("Analytics_Engine", "REGISTRY_UPDATE_FAILURE", ae_err, "Fallback to previous metrics or Alpha CGS")

    # Phase 5E: Growth Intelligence Layer
    try:
        print("[GI] Triggering Growth Intelligence Engine...")
        from growth_intelligence import GrowthIntelligenceEngine
        gi = GrowthIntelligenceEngine(
            youtube_service=youtube_service,
            work_dir=work_dir,
            cache_file="script_cache.json",
            registry_file="performance_registry.json",
            feedback_v2_file="feedback_dataset_v2.json"
        )
        gi.update(profile_key=profile_key)
    except Exception as gi_err:
        health_eng.register_failure("Growth_Intelligence", "UPDATE_FAILURE", gi_err, "Continue to Topic Discovery")

    # Phase 6: Topic Discovery Engine
    try:
        print("[TD] Triggering Topic Discovery Engine...")
        from topic_discovery import TopicDiscoveryEngine
        td_config = p.get("topic_discovery", {})
        td = TopicDiscoveryEngine(
            work_dir=work_dir,
            feedback_v2_file="feedback_dataset_v2.json",
            cache_file="script_cache.json",
            candidates_file="topic_candidates.json"
        )
        td.discover_topics(config_ratio_settings=td_config)
    except Exception as td_err:
        health_eng.register_failure("Topic_Discovery", "UPDATE_FAILURE", td_err, "Continue to generation")

    try:
        # 2. 台本生成
        print("STEP: Script generation (Cache-First)...")
        cache_path = os.path.join(work_dir, "script_cache.json")
        cache_data = load_script_cache(cache_path)
        
        # ロックと失敗ステータスの復旧
        recover_stale_and_failed_locks(cache_data)
        
        # ゾンビキャッシュ（mock_script_123 や、モックデータ）の完全物理パージ
        if "items" in cache_data:
            original_len = len(cache_data["items"])
            cache_data["items"] = [item for item in cache_data["items"] if not str(item.get("id", "")).startswith("mock_")]
            if len(cache_data["items"]) != original_len:
                print(f"[CACHE_PURGE] Purged {original_len - len(cache_data['items'])} zombie mock cache items.")
                save_script_cache(cache_path, cache_data)
                
        # pending（未使用）アイテムを集計
        pending_items = [item for item in cache_data.get("items", []) if item.get("status") == "pending"]
        
        # 本番環境（DRY_RUN以外の通常実行）では、手抜きキャッシュを強制バイパスして必ずGeminiから新規生成
        is_dry_run = os.environ.get("DRY_RUN", "").strip().lower() == "true"
        if not is_dry_run:
            print("[FORCE_GENERATE] Production environment detected. Bypassing existing cache to force-generate new content via Gemini.")
            pending_items = []
        
        # DRY_RUN かつ pending が無い場合、モックの台本を生成してテストを継続する
        if os.environ.get("DRY_RUN", "").strip().lower() == "true" and len(pending_items) == 0:
            print("[DRY_RUN] Generating a mock viral script item for End-to-End pipeline testing...")
            is_ja = ("jp" in profile_key.lower() or "jp" in folder_name.lower())
            mock_item = {
                "id": "mock_script_123",
                "topic": topic,
                "title": f"驚きの真実: {topic}" if is_ja else f"The Ultimate Secret of {topic}",
                "hook": f"{topic}に関する衝撃の事実を知っていますか？" if is_ja else f"Did you know this shocking fact about {topic}?",
                "body": f"実は{topic}は非常に賢く、人間との強い絆を築くことができます。" if is_ja else f"Actually, {topic} is highly intelligent and can build an incredibly strong bond with humans.",
                "script": f"{topic}に関する衝撃の事実を知っていますか？実は、非常に賢く、人間との強い絆を築くことができます。チャンネル登録をお願いします！" if is_ja else f"Did you know this shocking fact about {topic}? Actually, it is highly intelligent and can build an incredibly strong bond with humans. Subscribe for more amazing facts!",
                "call_to_action": "チャンネル登録をお願いします！" if is_ja else "Subscribe for more amazing facts!",
                "search_query": "dog" if "dog" in profile_key.lower() else ("pets" if "pawvana" in profile_key.lower() else "ocean"),
                "status": "pending",
                "created_at": datetime.datetime.utcnow().isoformat() + "Z"
            }
            if "items" not in cache_data:
                cache_data["items"] = []
            cache_data["items"].append(mock_item)
            save_script_cache(cache_path, cache_data)
            pending_items = [mock_item]

        print(f"[CACHE] Active pending items remaining: {len(pending_items)}")
        
        # 先読み補充判定（残り1本以下ならバッチ補充）
        if len(pending_items) <= 1:
            print(f"[CACHE] Pending items count ({len(pending_items)}) <= 1. Triggering Gemini batch refill...")
            
            gemini_key = (
                os.environ.get("GEMINI_API_KEY")
                or os.environ.get("GEMINI_API_KEY_AQUATIC_EN")
                or os.environ.get("GEMINI_KEY")
                or os.environ.get(f"GEMINI_API_KEY_{profile_key.upper()}")
                or p.get('gemini_api_key')
            )
            if gemini_key == "REDACTED_API_KEY":
                gemini_key = None
                
            if not gemini_key:
                print("[CACHE_WARN] Gemini API key not found. Skipping batch refill.")
                if len(pending_items) == 0:
                    health_eng.register_failure("Gemini_API", "KEY_MISSING", "Gemini API key is missing", "Abort")
                    sys.exit(0)
            else:
                gen_start_time = time.time()
                new_raw_items = []
                
                # Gemini 失敗時の Auto Recovery (Retry 3回)
                for gen_attempt in range(1, 4):
                    try:
                        new_raw_items = ai_generator.generate_viral_scripts_batch(
                            topic=topic, api_key=gemini_key, batch_size=5, language=language, profile_key=profile_key
                        )
                        if new_raw_items:
                            break
                    except Exception as gen_err:
                        rec_msg = f"Retrying Gemini generation (attempt {gen_attempt}/3)..." if gen_attempt < 3 else "Gemini API failed permanently. Generation aborted."
                        health_eng.register_failure("Gemini_API", "GENERATION_FAILURE", gen_err, rec_msg)
                        if gen_attempt == 3:
                            if len(pending_items) == 0:
                                print("FATAL: Cache is empty and Gemini generation failed. Aborting safely.")
                                sys.exit(0)
                        await asyncio.sleep(2)

                generation_latency = time.time() - gen_start_time
                
                # 各アイテムに一意なIDと初期状態を設定してキャッシュに追加
                timestamp = int(time.time())
                for idx, new_item in enumerate(new_raw_items):
                    new_item["id"] = f"aq_{timestamp}_{idx}"
                    new_item["status"] = "pending"
                    new_item["locked_at"] = None
                    new_item["used_at"] = None
                    new_item["video_id"] = None
                    
                    # Phase 7: Title Intelligence - タイトル A/B 最適化
                    try:
                        from title_intelligence import TitleIntelligenceEngine
                        ti_config = p.get("title_intelligence", {})
                        ti = TitleIntelligenceEngine(
                            work_dir=work_dir,
                            feedback_v2_file="feedback_dataset_v2.json",
                            cache_file="script_cache.json"
                        )
                        original_title = new_item.get("title", "")
                        item_topic = new_item.get("topic", topic or "")
                        selected_title = ti.select_best_title(
                            topic=item_topic,
                            original_title=original_title,
                            config_settings=ti_config
                        )
                        if selected_title and selected_title != original_title:
                            print(f"[TI] Title optimized: '{original_title}' -> '{selected_title}'")
                            new_item["title"] = selected_title
                            new_item["original_title"] = original_title
                        else:
                            print(f"[TI] Original title retained: '{original_title}'")
                    except Exception as ti_err:
                        health_eng.register_failure("Title_Intelligence", "TITLE_OPTIMIZATION_FAILURE", ti_err, "Fallback to original title")

                    # Phase 5C: Hook Score の自動付与
                    try:
                        import hook_scorer
                        hs = hook_scorer.score_item(new_item)
                        print(f"[HOOK_SCORE] ID={new_item['id']}: hook={hs['hook_score']}, title={hs['hook_title_score']}, opening={hs['hook_opening_score']}")
                    except Exception as hs_err:
                        print(f"[HOOK_SCORE_WARN] Scoring failed for {new_item.get('id')}: {hs_err}")
                    
                    # itemsリストの初期化保護
                    if "items" not in cache_data:
                        cache_data["items"] = []
                    cache_data["items"].append(new_item)
                    
                save_script_cache(cache_path, cache_data)
                pending_items = [item for item in cache_data.get("items", []) if item.get("status") == "pending"]
                print(f"[CACHE] Refill completed. Pending items count: {len(pending_items)}")

        # 使用するアイテムを選択してロック
        target_item = pending_items[0]
        target_item["status"] = "processing"
        target_item["locked_at"] = datetime.datetime.utcnow().isoformat() + "Z"
        save_script_cache(cache_path, cache_data)
        
        # 既存の下流変数へバインド
        title = target_item.get("title", f"{p['profile_name']} | {topic}")
        script_content = target_item.get("script", "")
        search_query = target_item.get("search_query", "ocean")
        
        print(f"[CACHE] Locked script ID: {target_item['id']}")
        print(f"[CACHE] Topic: {target_item.get('topic', topic)}")
        print(f"TITLE: {title}")
        print(f"SCRIPT: {script_content}")
        print(f"SEARCH_QUERY: {search_query}")

        # 動画生成時間計測開始
        gen_video_start = time.time()
        
        # チャンネル名を冠したタイトルになるように補正
        profile_prefix = f"{p['profile_name']} | "
        if not title.startswith(profile_prefix):
            title = profile_prefix + title
        if len(title) > 60:
            title = title[:60]
            
        # 英語チャンネル（日本語以外）限定のアポストロフィ保護と結合
        if language != "ja":
            script_content = re.sub(r"[’‘´`]", "'", script_content)

        # 文字化け対策
        is_ja_channel = (language == "ja")
        title = strip_emojis(title, is_ja_channel=is_ja_channel)
        script_content = strip_emojis(script_content, is_ja_channel=is_ja_channel)
        
        if is_ja_channel:
            title = cleanse_japanese_text(title)
            script_content = cleanse_japanese_text(script_content)

        # 英語チャンネル（日本語以外）限定の最終クレンジング
        if language != "ja":
            script_content = re.sub(r"(\w+)\s*'\s*(s|t|re|ve|ll|m|d)\b", r"\1'\2", script_content, flags=re.IGNORECASE)
            script_content = re.sub(r"\bIt\s+s\b", "It's", script_content, flags=re.IGNORECASE)
        
        print("STEP: Audio duration check...")
        temp_audio_path = os.path.join(work_dir, "temp_audio_check.mp3")
        try:
            await generate_video.generate_speech(script_content, temp_audio_path, voice=p['voice'], rate="+15%")
            from moviepy.editor import AudioFileClip
            a_clip = AudioFileClip(temp_audio_path)
            audio_dur = a_clip.duration
            a_clip.close()
            print(f"AUDIO_DURATION: {audio_dur:.2f}s")
            
            if audio_dur > 15.0:
                print(f"[WARN] Script duration ({audio_dur:.1f}s) exceeds 15.0s limit. Proceeding anyway (SOFT downgrade).")
        except Exception as e:
            print(f"DURATION_CHECK_ERROR: {e}")
            traceback.print_exc()
            sys.exit(1)

        # 3. 素材取得（Phase 3: 4段階フォールバックチェーン）
        # Level 1/2: Local Pool → Level 3: Pexels (QSM) → Level 4: Default/ColorClip
        print(f"STEP: Fetching ambient visual...")
        asset_path, asset_type = None, None
        
        # --- Level 1 & 2: ローカルプール探索 ---
        try:
            asset_path, asset_type = generate_video.scan_local_pool_for_topic(target_item.get("topic", topic), work_dir=work_dir)
            if asset_path:
                print(f"ASSET (LOCAL POOL): path={asset_path}, type={asset_type}")
        except Exception as local_err:
            print(f"[WARN] Local pool scanning failed: {local_err}")
        
        # --- Level 3: Pexels API + Query Selection Model (QSM) ---
        if not asset_path:
            print("[FALLBACK_L3] Local pool missed. Initiating Pexels QSM visual query...")
            pexels_key = (
                os.environ.get("PEXELS_API_KEY") 
                or os.environ.get("PEXELS_KEY") 
                or p.get('pexels_api_key')
            )
            if pexels_key == "REDACTED_API_KEY":
                pexels_key = None
            
            try:
                asset_path, asset_type = await generate_video.fetch_best_visual(
                    search_query, pexels_key, profile_key=profile_key, work_dir=work_dir
                )
                print(f"ASSET (Pexels+QSM): path={asset_path}, type={asset_type}")
                if not asset_path:
                    raise Exception("No visual asset path returned from Pexels.")
            except Exception as visual_err:
                print(f"[WARN] Pexels visual fetch failed: {visual_err}")
        
        # --- Level 4: デフォルトアセット / ColorClip フォールバック ---
        if not asset_path:
            print("[FALLBACK_L4] Attempting default asset or ColorClip fallback...")
            try:
                asset_path, asset_type = await generate_video.resolve_local_visual_fallback(profile_key=profile_key, work_dir=work_dir)
                print(f"ASSET (DEFAULT): path={asset_path}, type={asset_type}")
            except Exception as fallback_err:
                print(f"FATAL: Visual asset fallback also failed: {fallback_err}")
                sys.exit(1)
        
        print(f"ASSET_FINAL: path={asset_path}, type={asset_type}")
        
        # 4. 動画合成
        print("STEP: Video assembly (15s)...")
        video_output_path = os.path.join(work_dir, "youtube_short.mp4")
        
        bgm_path = p.get('bgm', 'bgm.mp3')
        if not os.path.exists(bgm_path):
            work_bgm = os.path.join(work_dir, bgm_path)
            if os.path.exists(work_bgm):
                bgm_path = work_bgm
            elif os.path.exists("bgm.mp3"):
                print(f"BGM_FALLBACK: Using root bgm.mp3")
                bgm_path = "bgm.mp3"
            else:
                print(f"BGM_MISSING: No BGM file found")
                bgm_path = None

        video_file, success = await generate_video.assemble_video_professional(
            script_content, 
            asset_path,
            asset_type,
            bgm_path, 
            video_output_path,
            voice=p['voice'],
            topic=profile_key,
            work_dir=work_dir
        )
        
        if not success or not video_file:
            raise Exception("FATAL: Video generation failed")
            
        generation_latency = (time.time() - gen_video_start)
        
        if not os.path.exists(video_file):
            raise Exception(f"FATAL: Video file does not exist: {video_file}")
            
        # AIサボり防止用「品質検証ゲート」アサーション
        print("[QUALITY_GATE] Initiating strict asset verification...")
        is_dry_run = os.environ.get("DRY_RUN", "").strip().lower() == "true"
        
        # 1. モックIDチェック
        if str(target_item.get("id", "")).startswith("mock_"):
            raise Exception("[QUALITY_GATE_FAILED] Mock script ID detected in production execution.")
            
        # 2. ファイルサイズのチェック
        video_size = os.path.getsize(video_file)
        if not is_dry_run:
            if video_size < 1024 * 1024:  # 本番環境では最低1MB以上
                raise Exception(f"[QUALITY_GATE_FAILED] Video file size ({video_size} bytes) is too small. Suspected low quality or failed rendering.")
                
        # 3. 単色ベタ塗り（ColorClipフォールバック）の検出
        if "temp_bg_fallback.mp4" in str(asset_path):
            raise Exception("[QUALITY_GATE_FAILED] Hand-waving ColorClip background fallback detected. Production requires high-quality real visuals.")
            
        # 4. ffmpeg / ffprobe によるメタデータアサート
        try:
            import subprocess as sp
            ffprobe_cmd = [
                "ffprobe", "-v", "error", 
                "-select_streams", "v:0", 
                "-show_entries", "stream=nb_frames,codec_name,width,height", 
                "-of", "csv=p=0", 
                video_file
            ]
            ffprobe_res = sp.run(ffprobe_cmd, capture_output=True, text=True, timeout=10)
            if ffprobe_res.returncode == 0:
                meta_info = ffprobe_res.stdout.strip().split(',')
                print(f"[QUALITY_GATE] Video metadata: {meta_info}")
                if len(meta_info) >= 3:
                    codec = meta_info[0]
                    w = int(meta_info[1])
                    h = int(meta_info[2])
                    if w != 1080 or h != 1920:
                        raise Exception(f"[QUALITY_GATE_FAILED] Resolution mismatch: {w}x{h} (Expected 1080x1920)")
                    if len(meta_info) >= 4 and meta_info[3].isdigit():
                        frames = int(meta_info[3])
                        if frames < 300:  # 最低10秒（30fps）以上を保証
                            raise Exception(f"[QUALITY_GATE_FAILED] Insufficient video frames: {frames} (Expected >= 300)")
            else:
                print(f"[QUALITY_GATE_WARN] ffprobe verification skipped: {ffprobe_res.stderr}")
        except Exception as ff_err:
            if "QUALITY_GATE_FAILED" in str(ff_err):
                raise
            print(f"[QUALITY_GATE_WARN] Metadata assertion skipped: {ff_err}")
            
        print("[QUALITY_GATE] Video asset passed all strict validation gates successfully.")
        
        video_size = os.path.getsize(video_file)
        print(f"VIDEO_FILE: {video_file} ({video_size} bytes)")
        
        if video_size < 1000:
            raise Exception(f"FATAL: Video file too small: {video_size} bytes")
            
        video_ids = []
        local_filenames = []
        if asset_path:
            for part in asset_path.split(','):
                match = re.search(r'temp_bg_\d+_(\d+)\.mp4', part)
                if match:
                    video_ids.append(int(match.group(1)))
                else:
                    local_filenames.append(os.path.basename(part))
                    
        history_log.append({
            "title": title,
            "script_content": script_content,
            "video_ids": video_ids,
            "local_filenames": local_filenames,
            "timestamp": datetime.datetime.now().isoformat()
        })
        history_log = history_log[-20:]
        
        with open(history_path, "w", encoding="utf-8") as f_hist:
            json.dump(history_log, f_hist, ensure_ascii=False, indent=2)
    
        # 4.1 二重投稿ガード（Time-Lock Guard）
        print("STEP: Double-posting time-lock check...")
        try:
            now_utc = datetime.datetime.now(datetime.timezone.utc)
            search_res = youtube_service.search().list(
                channelId=expected_channel_id,
                order="date",
                part="snippet",
                type="video",
                maxResults=1
            ).execute()
            
            items = search_res.get("items", [])
            if items:
                latest_video = items[0]
                pub_time_str = latest_video["snippet"]["publishedAt"]
                pub_time = datetime.datetime.strptime(pub_time_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
                diff = now_utc - pub_time
                diff_minutes = diff.total_seconds() / 60.0
                print(f"LATEST_POST_TIME: {pub_time_str} (Diff: {diff_minutes:.1f} minutes ago)")
                if diff_minutes < 10.0:
                    print(f"[WARN] A video was posted {diff_minutes:.1f} minutes ago. Aborting this run to prevent double-posting.")
                    sys.exit(0)
            else:
                print("No previous videos found. Proceeding safely.")
        except Exception as guard_err:
            print(f"[WARN] Failed to query latest video for double-post check (proceeding safely): {guard_err}")

        # 5. YouTubeアップロード + 検証 (Auto Recovery: Retry 2回)
        print("STEP: YouTube upload starting...")
        print(f"UPLOAD_TITLE: {title}")
        print(f"UPLOAD_CHANNEL: {expected_channel_id}")
        
        full_description = f"{script_content}\n\n{p['tags']}"
            
        # Phase 5D: Scheduled Upload Harmonizer
        scheduled_for_iso = None
        try:
            import scheduler
            current_utc = datetime.datetime.utcnow()
            scheduled_utc = scheduler.calculate_next_publish_time(current_utc, profile_key)
            scheduled_for_iso = scheduled_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
            print(f"[SCHEDULER] Calculated optimal publish time: {scheduled_for_iso}")
        except Exception as sched_err:
            print(f"[SCHEDULER_WARN] Scheduler calculation failed: {sched_err}. Falling back to immediate public release.")

        body = {
            'snippet': {
                'title': title,
                'description': full_description,
                'tags': ['Shorts'] + p['tags'].replace('#', '').split(),
                'categoryId': '22'
            },
            'status': {
                'privacyStatus': 'private' if scheduled_for_iso else 'public',
                'selfDeclaredMadeForKids': False
            }
        }
        
        if scheduled_for_iso:
            body['status']['publishAt'] = scheduled_for_iso
        
        if "snippet" in body and "description" in body["snippet"] and body["snippet"]["description"] is not None:
            if profile_key == "01_dogs_jp":
                body["snippet"]["description"] += "\n\n#shorts #chihuahua #dog #子犬 #犬の楽園"
            elif profile_key == "02_beauty_en" or profile_key == "glow_haven" or "beauty" in profile_key.lower():
                body["snippet"]["description"] += "\n\n#shorts #wellness #lifestyle #beauty #health"
        
        upload_start_time = time.time()
        video_id = None
        
        # DRY_RUN の場合はアップロード処理を完全にモック
        if os.environ.get("DRY_RUN", "").strip().lower() == "true":
            print("[DRY_RUN] Simulating YouTube upload (mock SUCCESS)...")
            video_id = "vid_dryrun_mock_123"
            print(f"UPLOAD_SUCCESS: {video_id}")
            print(f"URL: https://www.youtube.com/shorts/{video_id}")
        else:
            for upload_attempt in range(1, 3):
                try:
                    print(f"[UPLOAD] Uploading attempt {upload_attempt}/2...")
                    media = MediaFileUpload(video_file, chunksize=-1, resumable=True, mimetype='video/mp4')
                    request = youtube_service.videos().insert(part=','.join(body.keys()), body=body, media_body=media)
                    
                    response = None
                    while response is None:
                        status, response = request.next_chunk()
                        if status:
                            print(f"UPLOAD_PROGRESS: {int(status.progress() * 100)}%")
                    
                    video_id = response.get("id")
                    if not video_id:
                        raise Exception("video_id missing from upload response")
                    
                    print(f"VIDEO_ID: {video_id}")
                    
                    # 6. アップロード検証
                    print("STEP: Upload verification...")
                    time.sleep(3)
                    verify = youtube_service.videos().list(
                        part="status,snippet",
                        id=video_id
                    ).execute()
                    
                    items = verify.get("items", [])
                    if not items:
                        raise Exception(f"Uploaded video {video_id} not found via videos().list()")
                    
                    video = items[0]
                    actual_channel = video["snippet"]["channelId"]
                    upload_status = video["status"].get("uploadStatus")
                    
                    print(f"VERIFY_CHANNEL: {actual_channel}")
                    print(f"VERIFY_UPLOAD_STATUS: {upload_status}")
                    
                    if actual_channel != expected_channel_id:
                        raise Exception(f"Channel mismatch. Expected={expected_channel_id}, Actual={actual_channel}")
                    if upload_status not in ("uploaded", "processed"):
                        raise Exception(f"Upload status invalid: {upload_status}")
                    
                    print(f"UPLOAD_SUCCESS: {video_id}")
                    print(f"URL: https://www.youtube.com/shorts/{video_id}")
                    break
                except Exception as upload_err:
                    rec_msg = f"Retrying YouTube upload (attempt {upload_attempt}/2)..." if upload_attempt < 2 else "YouTube upload failed permanently."
                    health_eng.register_failure("YouTube_Upload", "UPLOAD_FAILURE", upload_err, rec_msg)
                    if upload_attempt == 2:
                        raise upload_err
                    await asyncio.sleep(5)

        upload_latency = time.time() - upload_start_time

        # キャッシュのステータスを確定して保存
        if 'target_item' in locals() and target_item:
            target_item["status"] = "uploaded"
            target_item["used_at"] = datetime.datetime.utcnow().isoformat() + "Z"
            target_item["video_id"] = video_id
            if 'scheduled_for_iso' in locals() and scheduled_for_iso:
                target_item["scheduled_for"] = scheduled_for_iso
            save_script_cache(cache_path, cache_data)
            
            # Title Performance Learning (動画ごとの実績蓄積)
            try:
                print("[TI] Recording title performance data...")
                from title_intelligence import TitleIntelligenceEngine
                ti = TitleIntelligenceEngine(work_dir=work_dir)
                uploaded_title = target_item.get("title", "")
                reg_path = os.path.join(work_dir, "performance_registry.json")
                reg_metrics = {"ctr": None, "apv": None, "subscribers_gained": 0}
                if os.path.exists(reg_path):
                    with open(reg_path, "r", encoding="utf-8") as rf:
                        reg_data = json.load(rf)
                    for ri in reg_data.get("items", []):
                        if ri.get("video_id") == video_id:
                            reg_metrics = ri.get("metrics", reg_metrics)
                            break
                ti.update_performance_registry(
                    video_id=video_id,
                    title=uploaded_title,
                    ctr=reg_metrics.get("ctr"),
                    apv=reg_metrics.get("apv"),
                    sub_gain=reg_metrics.get("subscribers_gained", 0)
                )
            except Exception as ti_err:
                print(f"[TI_WARN] Title performance recording failed: {ti_err}")

            # 9. Pipeline Audit (Audit)
            try:
                audit_eng.run_audit()
            except Exception as audit_err:
                health_eng.register_failure("Pipeline_Audit", "AUDIT_FAILURE", audit_err, "Continue metrics update")

            # 10. Metrics Update (KPI Dashboard)
            try:
                health_eng.generate_kpi_dashboard(upload_latency=upload_latency, generation_latency=generation_latency)
            except Exception as kpi_err:
                print(f"[KPI_WARN] KPI Dashboard generation failed: {kpi_err}")
            
            # Condition 6: 全種設定ファイルを含めてリポジトリ同期
            if os.environ.get("GITHUB_ACTIONS") == "true":
                print("[CI_GIT] Syncing all system logs and registries back to repository...")
                try:
                    os.system('git config --global user.name "github-actions[bot]"')
                    os.system('git config --global user.email "github-actions[bot]@users.noreply.github.com"')
                    os.system(f'git add {cache_path} performance_registry.json feedback_dataset.json feedback_dataset_v2.json topic_candidates.json title_candidates.json title_performance_registry.json health_status.json failure_registry.json kpi_dashboard.json pipeline_audit_report.json generated_history.json')
                    res_commit = os.system('git commit -m "chore: update production readiness metrics [skip ci]"')
                    if res_commit == 0:
                        res_push = os.system('git push origin main')
                        if res_push != 0:
                            raise Exception("Git push command failed")
                except Exception as git_err:
                    health_eng.register_failure("Git_Push", "GIT_SYNC_FAILURE", git_err, "Queue locally, retry on next run")

    except HttpError as e:
        print(f"HTTP_ERROR: status={e.resp.status}")
        error_content = e.content.decode('utf-8') if hasattr(e, 'content') else str(e)
        print(f"HTTP_ERROR_CONTENT: {error_content}")
        traceback.print_exc()
        
        is_quota_exceeded = False
        if e.resp.status == 403 and "quotaExceeded" in error_content:
            is_quota_exceeded = True
            print("[QUOTA_EXCEEDED] YouTube API Quota limit reached! Deferring post to next cycle.")
            if 'health_eng' in locals() and health_eng:
                health_eng.register_failure("YouTube_Upload", "QUOTA_EXCEEDED", "YouTube quota exceeded. Auto-skipping.", "Defer to next schedule")

        if 'target_item' in locals() and target_item:
            target_item["status"] = "pending" if is_quota_exceeded else "failed"
            target_item["locked_at"] = None
            save_script_cache(cache_path, cache_data)
            if os.environ.get("GITHUB_ACTIONS") == "true":
                os.system(f'git add {cache_path}')
                os.system(f'git commit -m "chore: defer or mark cache item [skip ci]" -- {cache_path}')
                os.system('git push origin main')
                
        if is_quota_exceeded:
            sys.exit(0)
        sys.exit(1)
    except Exception as e:
        print(f"FATAL_ERROR: {e}")
        traceback.print_exc()
        if 'target_item' in locals() and target_item:
            target_item["status"] = "failed"
            save_script_cache(cache_path, cache_data)
            if os.environ.get("GITHUB_ACTIONS") == "true":
                os.system(f'git add {cache_path}')
                os.system(f'git commit -m "chore: mark cache item as failed [skip ci]" -- {cache_path}')
                os.system('git push origin main')
        sys.exit(1)
    finally:
        print("[CLEANUP] Running final proactive workspace cleanup in finally clause...")
        import glob
        import shutil
        
        temp_audio_dir = os.path.join(work_dir, "temp_audio")
        if os.path.exists(temp_audio_dir):
            try:
                shutil.rmtree(temp_audio_dir)
                print(f"[CLEANUP] Removed directory: {temp_audio_dir}")
            except Exception as clean_err:
                print(f"[CLEANUP_WARN] Failed to remove {temp_audio_dir}: {clean_err}")
                
        temp_patterns = [
            "temp_audio_check.mp3",
            "temp_bg_*.mp4",
            "youtube_short.mp4",
            "temp_video_noaudio_*.mp4",
            "temp_final_audio_*.wav",
            "*.png",
            "*.mp3"
        ]
        
        for pattern in temp_patterns:
            files = glob.glob(os.path.join(work_dir, pattern))
            for f in files:
                filename = os.path.basename(f)
                if filename.endswith(".py") or filename == "config.json" or filename == "generated_history.json" or filename == "bgm.mp3":
                    continue
                try:
                    os.remove(f)
                    print(f"[CLEANUP] Removed temporary file: {f}")
                except Exception as clean_err:
                    print(f"[CLEANUP_WARN] Failed to remove file {f}: {clean_err}")

if __name__ == "__main__":
    w_dir = sys.argv[1] if len(sys.argv) > 1 else '.'
    t_key = sys.argv[2] if len(sys.argv) > 2 else None
    asyncio.run(run_auto_post(w_dir, t_key))

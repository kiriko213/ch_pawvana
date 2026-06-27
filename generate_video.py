import os
import random
import re
import asyncio
import edge_tts
import json
import gtts
from moviepy.editor import VideoFileClip, TextClip, CompositeVideoClip, AudioFileClip, ImageClip, ColorClip, concatenate_videoclips, CompositeAudioClip, vfx, afx
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import numpy as np

# Pillow 10.0.0以降でのANTIALIASエラー対策
if not hasattr(Image, 'ANTIALIAS'):
    Image.ANTIALIAS = Image.LANCZOS

def normalize_english_text(text):
    if not text:
        return ""
    # 1. スマートアポストロフィやバッククォートなどを標準 of 半角アポストロフィに統一
    text = re.sub(r"[’‘´`]", "'", text)
    
    # 2. it ' s -> it's のように、アポストロフィの前後にスペースが入っているケースを物理強制結合
    text = re.sub(r"(\w+)\s*'\s*(s|t|re|ve|ll|m|d)\b", r"\1'\2", text, flags=re.IGNORECASE)
    
    # 3. it s -> it's のように、アポストロフィが完全に半角スペースに化けている、またはアポストロフィが消失してスペースになっているケースを復元
    text = re.sub(r"\bIt\s+s\b", "It's", text, flags=re.IGNORECASE)
    
    pattern = r"\b(it|don|doesn|didn|wasn|weren|haven|hasn|hadn|won|wouldn|shouldn|couldn|aren|isn|can|i|you|he|she|we|they|there|who|what|where|when|why|how|let|that|here|everyone|someone|noone|anybody|somebody|nobody)\s+(s|t|re|ve|ll|m|d)\b"
    text = re.sub(pattern, r"\1'\2", text, flags=re.IGNORECASE)
    
    # 4. 記号の前の不要なスペースを削除 (e.g. "hello !" -> "hello!")
    text = re.sub(r'\s+([!?.,])', r'\1', text)
    
    # 5. 連続するスペースを1つの半角スペースにまとめる
    text = re.sub(r'\s+', ' ', text)
    
    return text.strip()

def cleanse_japanese_text(text):
    if not text:
        return ""
    # すべての半角スペースと全角スペースを物理的に完全消去
    text = text.replace(" ", "").replace("　", "")
    
    # 典型的な絵文字削除跡地や助詞の乱れの補正
    # 1. 「人はで教えてね」 -> 「人はコメントで教えてね」
    text = re.sub(r"人はで教えて", "人はコメントで教えて", text)
    text = re.sub(r"人はでコメント", "人はコメント", text)
    
    # 2. 「人はで」 -> 「人は」
    text = re.sub(r"人はで([、。！!?]|$)", r"人は\1", text)
    # 一般的な「はで」の補正
    text = re.sub(r"(\w+)はで(教えて|書いて|コメント|反応)", r"\1はコメントで\2", text)
    text = re.sub(r"(\w+)はで(？！|？！|？|！|\?|\!)", r"\1は\2", text)
    
    # 3. 文頭や読点後の不要な「で」の補正
    text = re.sub(r"([。！!？\?\n])で教えて", r"\1コメントで教えて", text)
    
    # 4. 重複しやすい表現の整理
    text = re.sub(r"コメント欄でコメントで", "コメント欄で", text)
    text = re.sub(r"コメントでコメントで", "コメントで", text)
    
    return text

def _wrap_text_simple(t, max_w=12, is_ja_channel=True):
    """日本語テキストのみ全角12文字ごとに自動改行を挿入。英語は単語単位の折り返しを create_boxed_text_image に任せるため、そのまま返す。"""
    t = t.replace('\n', '').strip()
    if not is_ja_channel:
        return normalize_english_text(t)
    
    # 日本語テキストのスペース完全排除＆クレンジング補正
    t = cleanse_japanese_text(t)
    
    res = []
    while len(t) > max_w:
        res.append(t[:max_w])
        t = t[max_w:]
    if t:
        res.append(t)
    return '\n'.join(res)

def create_boxed_text_image(text, size=(1080, 1920), fontsize=55, is_ja_channel=True):
    """
    中央の半透明ボックス＋白文字の字幕画像を生成。
    """
    # 英語チャンネル限定：記号やアポストロフィ周辺のスペースを最適化＋物理強制結合
    if not is_ja_channel:
        text = normalize_english_text(text)
        text = re.sub(r"(\w+)\s*'\s*(s|t|re|ve|ll|m|d)\b", r"\1'\2", text, flags=re.IGNORECASE)
        text = re.sub(r"\bIt\s+s\b", "It's", text, flags=re.IGNORECASE)
    else:
        # 日本語チャンネル限定：スペース完全排除＆クレンジング補正
        text = cleanse_japanese_text(text)

    img = Image.new('RGBA', size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    if os.name == 'nt':
        font_path = "C:\\Windows\\Fonts\\meiryo.ttc"
    else:
        # GitHub Actions (Ubuntu) での Noto Sans CJK の一般的なパス
        font_candidates = [
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"
        ]
        font_path = next((p for p in font_candidates if os.path.exists(p)), None)
    
    font = ImageFont.truetype(font_path, fontsize) if font_path and os.path.exists(font_path) else ImageFont.load_default()

    max_width = 800
    lines = []
    clean_text = text.replace("\n", " ").strip()
    if not is_ja_channel:
        clean_text = normalize_english_text(clean_text)
        clean_text = re.sub(r"(\w+)\s*'\s*(s|t|re|ve|ll|m|d)\b", r"\1'\2", clean_text, flags=re.IGNORECASE)
        clean_text = re.sub(r"\bIt\s+s\b", "It's", clean_text, flags=re.IGNORECASE)
    
    import textwrap
    
    if not is_ja_channel:
        # ■ バグ修正1: 英語字幕は textwrap.wrap を用いて安全に分割（Word Wrap）
        lines = textwrap.wrap(clean_text, width=28, break_long_words=False)
        lines = [normalize_english_text(l) for l in lines if l.strip()]
        lines = [re.sub(r"(\w+)\s*'\s*(s|t|re|ve|ll|m|d)\b", r"\1'\2", l, flags=re.IGNORECASE) for l in lines]
        lines = [re.sub(r"\bIt\s+s\b", "It's", l, flags=re.IGNORECASE) for l in lines]
    else:
        # ■ 日本語: 文字単位でピクセル幅を計算して折り返し（従来通り）
        current_line = ""
        for char in clean_text:
            test_line = current_line + char
            if draw.textbbox((0, 0), test_line, font=font)[2] > max_width and current_line:
                lines.append(current_line)
                current_line = char
            else:
                current_line = test_line
        if current_line:
            lines.append(current_line)
    
    line_heights = [draw.textbbox((0, 0), l, font=font)[3] - draw.textbbox((0, 0), l, font=font)[1] for l in lines]
    total_text_height = sum(line_heights) + 25 * (len(lines) - 1)
    box_width = 900
    box_height = total_text_height + 120
    
    box_x = (size[0] - box_width) // 2
    box_y = (size[1] - box_height) // 2
    overlay = Image.new('RGBA', size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    overlay_draw.rounded_rectangle([box_x, box_y, box_x + box_width, box_y + box_height], radius=30, fill=(30, 20, 10, 180))
    img = Image.alpha_composite(img, overlay)
    draw = ImageDraw.Draw(img)
    
    current_y = box_y + 60
    for line in lines:
        w = draw.textbbox((0, 0), line, font=font)[2]
        x = (size[0] - w) // 2
        draw.text((x, current_y), line, font=font, fill=(255, 255, 255))
        current_y += draw.textbbox((0, 0), line, font=font)[3] - draw.textbbox((0, 0), line, font=font)[1] + 25
        
    return img

async def generate_speech(text, output_path, voice="ja-JP-NanamiNeural", rate="+5%"):
    """
    音声合成を行い、ファイルが正しく生成されたかチェックする。
    edge_ttsがGitHub Actionsで403エラーになる場合、gTTSにフォールバックする。
    """
    try:
        communicate = edge_tts.Communicate(text, voice, rate=rate)
        await communicate.save(output_path)
        if not os.path.exists(output_path) or os.path.getsize(output_path) < 100:
            raise Exception("Generated audio file is empty or too small.")
    except Exception as e:
        print(f"edge-tts Error: {e}, falling back to gTTS...")
        try:
            lang = "ja" if "ja-JP" in voice else "en"
            tts = gtts.gTTS(text=text, lang=lang)
            tts.save(output_path)
            if not os.path.exists(output_path) or os.path.getsize(output_path) < 100:
                raise Exception("gTTS output is empty.")
        except Exception as fallback_e:
            print(f"gTTS Fallback Error: {fallback_e}")
            raise

async def fetch_best_visual(query, api_key, profile_key=".", work_dir="."):
    import os
    import glob
    import shutil
    import random
    import requests
    import sys
    import json

    # [PEXELS_DIAG] 関数エントリ診断
    print(f"[PEXELS_DIAG] api_key_present={bool(api_key and api_key.strip())}, query={query}, profile_key={profile_key}")

    # 1. 前回のゴミファイルを削除
    print("[CLEANUP] Purging ALL old assets before processing...")
    old_files = glob.glob(os.path.join(work_dir, "temp_bg_*.mp4")) + \
                glob.glob(os.path.join(work_dir, "youtube_short.mp4")) + \
                glob.glob(os.path.join(work_dir, "temp_video_noaudio_*.mp4")) + \
                glob.glob(os.path.join(work_dir, "temp_final_audio_*.wav"))
                
    for old_file in old_files:
        try:
            os.remove(old_file)
        except Exception:
            pass
            
    temp_audio_dir = os.path.join(work_dir, "temp_audio")
    if os.path.exists(temp_audio_dir):
        try:
            shutil.rmtree(temp_audio_dir)
        except Exception:
            pass
            
    # 0. キャッシュファイルと履歴から使用済みビデオIDをロードして重複をブロック
    used_visual_ids = set()
    cache_path = os.path.join(work_dir, "script_cache.json")
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f_cache:
                cache_data = json.load(f_cache)
                for item in cache_data.get("items", []):
                    # status == 'uploaded' のアイテムから使用済みビデオIDを取得
                    if item.get("status") == "uploaded":
                        v_ids = item.get("video_ids", [])
                        for vid in v_ids:
                            used_visual_ids.add(int(vid))
        except Exception as ex_cache:
            print(f"[PEXELS_GUARD_WARN] Failed to read script_cache.json: {ex_cache}")

    history_path = os.path.join(work_dir, "generated_history.json")
    if os.path.exists(history_path):
        try:
            with open(history_path, "r", encoding="utf-8") as f_hist:
                history_data = json.load(f_hist)
                for entry in history_data:
                    v_ids = entry.get("video_ids", [])
                    for vid in v_ids:
                        used_visual_ids.add(int(vid))
        except Exception as ex_hist:
            print(f"[WARN] Failed to read generated_history.json in fetch_best_visual: {ex_hist}")
    print(f"[PEXELS_GUARD] Loaded recently used visual IDs to avoid: {used_visual_ids}")

    scene_queries = [q.strip() for q in query.split(',')] if ',' in query else [query]
    downloaded_paths = []
    
    # クエリ強制上書き（プロファイルベース・フォルダ名・作業ディレクトリベース）
    combined_ctx = f"{profile_key} {work_dir}".lower()
    
    dog_pool = [
        "shiba inu puppy", "toy poodle cozy indoor", "golden retriever playing fetch", 
        "corgi puppy running lawn", "pomeranian fluffy close up", "french bulldog sleeping", 
        "happy puppy running", "cute puppy head tilt", "dog playing garden", "shiba inu smiling"
    ]
    
    cat_pool = [
        "calico cat playing", "kitty sleeping sunbeam", "cute cat stretching", 
        "fluffy kitten purring", "cat grooming paws", "scottish fold looking up", 
        "playful kitten yarn", "tabby cat napping", "cat sitting window", "british shorthair close up"
    ]
    
    hamster_pool = [
        "cute hamster cozy bedding", "hamster running wheel", "dwarf hamster eating seed", 
        "fluffy hamster sleeping", "hamster stuffing cheeks", "cute hamster exploring", 
        "golden hamster close up", "hamster yawning cuddle", "tiny baby hamster", "hamster playing toy"
    ]
    
    beauty_pool = [
        "wellness lifestyle aesthetic", "skincare close up", "organic cosmetics aesthetic", 
        "relaxing spa aromatherapy", "herbal tea pouring", "morning routine aesthetic", 
        "essential oils dropper", "natural beauty ingredients", "selfcare face massage", 
        "meditation candles glowing"
    ]

    is_overwritten = False
    selected_pool = []
    
    if "dogs_jp" in combined_ctx or "ch_dogs_en" in combined_ctx or "dogs_en" in combined_ctx or "01_dogs_jp" in combined_ctx or "06_dogs" in combined_ctx:
        selected_pool = dog_pool
        is_overwritten = True
    elif "pets_jp" in combined_ctx or "02_pets_jp" in combined_ctx or "pawvana" in combined_ctx:
        selected_pool = cat_pool
        is_overwritten = True
    elif "ham_jp" in combined_ctx or "05_ham_jp" in combined_ctx:
        selected_pool = hamster_pool
        is_overwritten = True
    elif "beauty" in combined_ctx or "glow_haven" in combined_ctx:
        if not ("aesthetic" in combined_ctx or "guess" in combined_ctx):
            selected_pool = beauty_pool
            is_overwritten = True

    if is_overwritten and selected_pool:
        required_count = len(scene_queries)
        if required_count <= len(selected_pool):
            scene_queries = random.sample(selected_pool, required_count)
        else:
            scene_queries = random.choices(selected_pool, k=required_count)

    is_aesthetic = "aesthetic" in profile_key.lower() or "guess" in profile_key.lower()
    required_count = len(scene_queries)

    # 必須・排除キーワードの設定
    required_keywords = []
    exclude_keywords = []

    # config.json の読み込みと動的フィルタ適用 (P0-5)
    config_path = os.path.join(work_dir, "config.json")
    config_forbidden = []
    config_target = None
    profile_cfg = {}
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f_cfg:
                config_data = json.load(f_cfg)
                fallback_key = os.path.basename(os.getcwd())
                profile_cfg = config_data.get(profile_key) or config_data.get(fallback_key) or list(config_data.values())[0]
                config_forbidden = profile_cfg.get("forbidden_animals", [])
                config_target = profile_cfg.get("target_animal")
        except Exception as e_cfg:
            print(f"[WARN] Failed to read config.json in fetch_best_visual: {e_cfg}")

    niche_config = {
        "hamster": {
            "required": ["hamster"],
            "exclude": ["ferret", "rabbit", "rat", "mouse", "guinea pig", "chinchilla", "dog", "cat", "squirrel", "chipmunk"]
        },
        "dog": {
            "required": ["dog", "puppy", "shiba", "poodle", "retriever", "corgi", "pomeranian", "bulldog"],
            "exclude": ["cat", "kitty", "kitten", "hamster", "ferret", "rabbit", "bird"]
        },
        "cat": {
            "required": ["cat", "kitty", "kitten"],
            "exclude": ["dog", "puppy", "hamster", "ferret", "rabbit", "bird"]
        },
        "romance": {
            "required": ["love", "romance", "couple", "relationship", "date", "hug", "kiss", "heart", "marriage", "romantic"],
            "exclude": ["dog", "cat", "hamster", "animal", "pet"]
        },
        "aesthetic": {
            "required": ["landscape", "nature", "scenery", "aesthetic", "mountain", "sea", "ocean", "forest", "sky", "view"],
            "exclude": []
        },
        "lgbtq": {
            "required": ["pride", "lgbt", "rainbow", "love", "couple", "diverse", "celebration"],
            "exclude": []
        },
        "beauty": {
            "required": ["beauty", "skincare", "cosmetic", "spa", "tea", "oil", "massage", "candle", "wellness", "relax"],
            "exclude": []
        },
        "aquatic": {
            "required": ["fish", "marine", "ocean", "sea", "underwater", "aquarium", "reef", "jellyfish", "octopus", "shark", "whale", "turtle"],
            "exclude": ["dog", "dogs", "cat", "cats", "pet", "pets", "puppy", "puppies", "indoor", "living room", "land animal", "human", "person"]
        }
    }

    # config_target や combined_ctx のマッチングから動的に設定
    matched_niche = None
    if config_target:
        matched_niche = niche_config.get(config_target)

    if not matched_niche:
        for k, v in niche_config.items():
            if k in combined_ctx:
                matched_niche = v
                break

    if matched_niche:
        required_keywords = list(matched_niche.get("required", []))
        exclude_keywords = list(matched_niche.get("exclude", []))
        
        # config.json からの動的排除リストのマージ
        for fa in config_forbidden:
            if fa not in exclude_keywords:
                exclude_keywords.append(fa)
            for suffix in ["s", "es", "ies"]:
                derived = f"{fa}{suffix}"
                if fa.endswith("y") and suffix == "ies":
                    derived = fa[:-1] + "ies"
                if derived not in exclude_keywords:
                    exclude_keywords.append(derived)
        if config_target and config_target not in required_keywords:
            required_keywords.append(config_target)

    # Pexelsからの取得試行
    if api_key and api_key != "REDACTED_API_KEY" and api_key.strip():
        import time
        headers = {"Authorization": api_key}
        
        all_videos = []
        seen_ids = set()
        
        # すべてのクエリについて検索を実行し候補をマージ
        for sq in scene_queries:
            search_term = sq
            if config_target == "aquatic":
                # Asset Query Guardrail: 海洋コンテキストを補完 (P0-2)
                add_ctx = ""
                if not any(k in sq.lower() for k in ["underwater", "ocean", "marine", "sea"]):
                    add_ctx = " underwater"
                search_term = f"{sq}{add_ctx}"
            elif is_aesthetic:
                search_term = f"{sq} landscape"
                
            for retry_attempt in range(1, 4):
                try:
                    random_page = random.randint(1, 3)
                    v_url = f"https://api.pexels.com/videos/search?query={search_term}&per_page=30&orientation=portrait&page={random_page}"
                    res = requests.get(v_url, headers=headers, timeout=10)
                    res.raise_for_status()
                    v_data = res.json()
                    videos = v_data.get('videos', [])
                    print(f"[PEXELS_DIAG] query='{search_term}' status={res.status_code} total_results={v_data.get('total_results', 'N/A')} videos_in_page={len(videos)}")
                    
                    for v in videos:
                        v_id = v.get('id')
                        if v_id not in seen_ids:
                            seen_ids.add(v_id)
                            all_videos.append(v)
                    break
                except Exception as api_err:
                    print(f"[PEXELS_WARN] Attempt {retry_attempt}/3 failed for query '{sq}': {api_err}")
                    if retry_attempt < 3:
                        time.sleep(2)
                        
        # Phase 3: ブラックリストのロード
        blacklist_data = _load_blacklist(work_dir)
        
        # プールされた動画をバリデーションする（ブラックリスト + QSM統合）
        valid_candidates = []
        _diag_dup = 0; _diag_bl = 0; _diag_excl = 0; _diag_req = 0; _diag_qsm = 0; _diag_aqua = 0
        for video in all_videos:
            video_id = video.get('id')
            if video_id and int(video_id) in used_visual_ids:
                print(f"[PEXELS_GUARD] Skipping recently used video ID: {video_id}")
                _diag_dup += 1
                continue

            # Phase 3: ブラックリストチェック
            if _is_blacklisted(video, blacklist_data):
                print(f"[BLACKLIST] Rejected video ID: {video_id}")
                _diag_bl += 1
                continue

            video_url = video.get('url', '').lower()
            normalized_url = video_url.replace("-", " ").replace("_", " ")
            video_tags = [t.get('name', '').lower() for t in video.get('tags', [])] if isinstance(video.get('tags'), list) else []
            
            # 排除キーワードのチェック
            is_excluded = False
            for ekw in exclude_keywords:
                if ekw in normalized_url or any(ekw in tag for tag in video_tags):
                    is_excluded = True
                    break
            if is_excluded:
                _diag_excl += 1
                continue
                
            # 必須キーワードのチェック
            if required_keywords:
                has_required = False
                for rkw in required_keywords:
                    if rkw in normalized_url or any(rkw in tag for tag in video_tags):
                        has_required = True
                        break
                if not has_required:
                    _diag_req += 1
                    continue

            # Asset Validation Gate for Aquatic channel
            if config_target == "aquatic":
                marine_score = 0
                marine_keywords = [
                    "ocean", "sea", "underwater", "marine", "aquatic", "fish", "reef", "jellyfish", 
                    "shark", "whale", "water", "dive", "coral", "turtle", "octopus", "squid", "seal", 
                    "sea lion", "dolphin", "kelp", "abyss", "plankton", "depth", "anemone", "aquarium", 
                    "crustacean", "clam", "shell", "stingray", "ray", "shrimp", "krill", "lobster", "crab"
                ]
                terrestrial_keywords = [
                    "dog", "dogs", "cat", "cats", "pet", "pets", "puppy", "puppies", "indoor", "living room",
                    "room", "family", "doggy", "kitten", "hamster", "bird", "forest", "desert", "mountain",
                    "jungle", "home", "bedroom", "kitchen", "sofa", "office", "street", "car", "building",
                    "city", "human", "person", "people", "man", "woman",
                    "pomeranian", "shiba", "poodle", "retriever", "corgi", "bulldog", "terrier", "husky", "chihuahua",
                    "persian", "siamese", "tabby", "calico", "ragdoll", "maine coon",
                    "rabbit", "bunny", "ferret", "guinea pig", "mouse", "rat", "squirrel", "monkey", "horse", "cow", "pig", "sheep",
                    "lion", "tiger", "bear", "deer", "fox", "wolf", "elephant", "giraffe", "zebra", "kangaroo",
                    "carpet", "furniture", "couch", "house", "apartment", "table", "chair", "bed", "floor", "wall", "window"
                ]
                
                # config.json の forbidden_animals を terrestrial_keywords に動的追加 (P0-5)
                for fa in config_forbidden:
                    if fa not in terrestrial_keywords:
                        terrestrial_keywords.append(fa)
                    for suffix in ["s", "es", "ies"]:
                        derived = f"{fa}{suffix}"
                        if fa.endswith("y") and suffix == "ies":
                            derived = fa[:-1] + "ies"
                        if derived not in terrestrial_keywords:
                            terrestrial_keywords.append(derived)
                
                matched_marine = []
                for kw in marine_keywords:
                    if kw in normalized_url or any(kw in tag for tag in video_tags):
                        marine_score += 30
                        matched_marine.append(kw)
                        
                has_terrestrial = False
                for tkw in terrestrial_keywords:
                    if tkw in normalized_url or any(tkw in tag for tag in video_tags):
                        has_terrestrial = True
                        break
                        
                if has_terrestrial:
                    print(f"[VAL_GATE] Video ID {video_id} REJECTED: Contains terrestrial/forbidden keywords in URL: {video_url}")
                    continue
                    
                print(f"[VAL_GATE] Video ID {video_id}: marine_score={marine_score} (matched: {matched_marine}, has_terrestrial={has_terrestrial})")
                
                if marine_score < 60:
                    print(f"[VAL_GATE] Rejected non-marine asset: {video_id} (Score: {marine_score} < 60)")
                    continue
                    
            suitable_files = [f for f in video.get('video_files', []) if f.get('link')]
            if suitable_files:
                # Phase 3: QSMスコアリング
                qsm_score = compute_asset_quality_score(video, search_query=query, video_files=suitable_files)
                if qsm_score >= 60:
                    valid_candidates.append((video, suitable_files, qsm_score))
                    print(f"[QSM] Video ID {video_id}: score={qsm_score} (ACCEPTED)")
                else:
                    print(f"[QSM] Video ID {video_id}: score={qsm_score} (REJECTED, below threshold 60)")
                    _diag_qsm += 1
                
        # QSMスコアの降順でソートし、上位15本を採用
        valid_candidates.sort(key=lambda x: x[2], reverse=True)
        valid_candidates = valid_candidates[:15]
        
        # 必要な本数分、シャッフルされたリストから順に割り当ててダウンロード
        if len(valid_candidates) >= required_count:
            for idx in range(required_count):
                selected_video, selected_files, qsm_score = valid_candidates[idx]
                video_id = selected_video.get('id')
                best_file = selected_files[0]
                dest_path = os.path.join(work_dir, f"temp_bg_{idx}_{video_id}.mp4")
                
                # ダウンロード実行
                for dl_attempt in range(1, 4):
                    try:
                        video_res = requests.get(best_file['link'], timeout=10)
                        video_res.raise_for_status()
                        with open(dest_path, 'wb') as f:
                            f.write(video_res.content)
                        downloaded_paths.append(dest_path)
                        break
                    except Exception as dl_err:
                        print(f"[DOWNLOAD_WARN] Attempt {dl_attempt}/3 failed to download {best_file['link']}: {dl_err}")
                        if dl_attempt < 3:
                            time.sleep(2)

    # 判定チェック：必要本数に1本でも満たない場合は例外を発生させて呼び出し側でフォールバックさせる
    if len(downloaded_paths) < required_count:
        # [PEXELS_DIAG] 失敗原因の分類ログ
        _api_called = bool(api_key and api_key != "REDACTED_API_KEY" and api_key.strip())
        if not _api_called:
            _reason = "api_key_missing"
        elif len(all_videos) == 0:
            _reason = "api_response_0_videos"
        elif len(valid_candidates) == 0:
            _reason = f"all_filtered (dup={_diag_dup} bl={_diag_bl} excl={_diag_excl} req={_diag_req} qsm={_diag_qsm})"
        else:
            _reason = f"download_failed (candidates={len(valid_candidates)} downloaded={len(downloaded_paths)})"
        print(f"[PEXELS_DIAG] FAILURE reason={_reason} required={required_count} all_videos={len(all_videos) if _api_called else 'N/A'} valid={len(valid_candidates) if _api_called else 'N/A'} downloaded={len(downloaded_paths)}")
        raise Exception(f"Insufficient Pexels assets found (downloaded: {len(downloaded_paths)}/{required_count})")
                
    return ",".join(downloaded_paths), "video"

async def resolve_local_visual_fallback(profile_key=".", work_dir="."):
    """
    Pexelsが利用できない場合のフォールバックアセット解決ロジック。
    1. assets/ ディレクトリから profile_key に合致する、あるいは default.mp4 を探す（重複排除・禁止キーワード排除あり）。
    2. なければ、ColorClip を用いて 15秒間のダミー動画ファイル（temp_bg_fallback.mp4）を動的に生成し、それを使用する。
    """
    import os
    import shutil
    import glob
    import json
    from moviepy.editor import ColorClip

    assets_dir = os.path.join(work_dir, "assets")
    fallback_path = os.path.join(work_dir, "temp_bg_fallback.mp4")
    
    # 履歴ファイルおよびキャッシュから使用済みローカルアセットを収集
    used_filenames = set()
    cache_path = os.path.join(work_dir, "script_cache.json")
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f_cache:
                cache_data = json.load(f_cache)
                for item in cache_data.get("items", []):
                    for fn in item.get("local_filenames", []):
                        used_filenames.add(fn)
        except Exception:
            pass

    history_path = os.path.join(work_dir, "generated_history.json")
    if os.path.exists(history_path):
        try:
            with open(history_path, "r", encoding="utf-8") as f_hist:
                history_data = json.load(f_hist)
                for entry in history_data:
                    for fn in entry.get("local_filenames", []):
                        used_filenames.add(fn)
        except Exception:
            pass

    # 1. ローカルアセットプールの探索
    if os.path.exists(assets_dir):
        # 履歴にある使用済みアセットも除外
        mp4_files = [f for f in glob.glob(os.path.join(assets_dir, "*.mp4"))
                     if os.path.basename(f) not in used_filenames]
        if mp4_files:
            # 他チャンネル（dogs, pets等）や、config.jsonの禁止動物ワードが含まれるものを除外するフィルタ
            config_path = os.path.join(work_dir, "config.json")
            forbidden_words = ["dog", "cat", "pet", "puppy", "kitten", "hamster", "bird", "living room", "indoor"]
            if os.path.exists(config_path):
                try:
                    with open(config_path, "r", encoding="utf-8") as f_cfg:
                        config_data = json.load(f_cfg)
                        fallback_key = os.path.basename(os.getcwd())
                        profile_cfg = config_data.get(profile_key) or config_data.get(fallback_key) or list(config_data.values())[0]
                        forbidden_words.extend(profile_cfg.get("forbidden_animals", []))
                except Exception:
                    pass
            
            # 複数形などの派生語も含めて小文字で統一
            filter_words = []
            for fw in forbidden_words:
                fw_l = fw.lower()
                filter_words.append(fw_l)
                filter_words.append(f"{fw_l}s")
                if fw_l.endswith("y"):
                    filter_words.append(f"{fw_l[:-1]}ies")

            valid_files = []
            for f in mp4_files:
                fname = os.path.basename(f).lower()
                normalized_fname = fname.replace("-", " ").replace("_", " ")
                # 自身のプロファイルキーが含まれる場合は最優先（安全）とするが、そうでない場合は他プロファイルの禁止ワードが入っていないかチェック
                if profile_key.lower() in fname:
                    valid_files.append(f)
                    continue
                if any(fw in normalized_fname for fw in filter_words):
                    print(f"[FALLBACK] Skipping banned asset due to forbidden keywords in name: {f}")
                    continue
                # 自身とは異なるチャンネル名（例：dogs, pets, pawvana, romance, lgbtq）が入っているものも排除
                other_channels = ["dogs", "pets", "pawvana", "romance", "lgbtq", "beauty", "glow_haven", "aesthetic"]
                other_channels = [oc for oc in other_channels if oc not in profile_key.lower()]
                if any(oc in fname for oc in other_channels):
                    print(f"[FALLBACK] Skipping other channel asset: {f}")
                    continue
                valid_files.append(f)

            if valid_files:
                selected = next((f for f in valid_files if profile_key.lower() in os.path.basename(f).lower()), valid_files[0])
                print(f"[FALLBACK] Found local asset: {selected}")
                try:
                    shutil.copy(selected, fallback_path)
                    return fallback_path, "video"
                except Exception as e:
                    print(f"[FALLBACK_WARN] Failed to copy local asset {selected}: {e}")

    # 2. 動的な ColorClip 背景の作成 (ColorClipフォールバックの自動救済)
    if os.environ.get("DRY_RUN", "").strip().lower() != "true":
        print("[FALLBACK_FATAL] Real visual asset was not found and ColorClip fallback is forbidden in production.")
        raise Exception("Production execution requires high-quality real visual assets. ColorClip/Hand-waving fallback is forbidden.")

    print("[FALLBACK] No local asset found. Generating dynamic ColorClip video background...")
    try:
        # プロファイルキーから適したカラーテーマを動的に決定
        pk_lower = profile_key.lower() if profile_key else ""
        if "dog" in pk_lower:
            theme_color = (139, 90, 43) # ウォームブラウン
        elif "pawvana" in pk_lower or "pet" in pk_lower:
            theme_color = (180, 160, 120) # マイルドベージュ
        elif "aquatic" in pk_lower or "deep" in pk_lower:
            theme_color = (10, 30, 60) # アクアブルー
        else:
            theme_color = (30, 30, 30) # チャコール
            
        print(f"[FALLBACK] Selected theme color {theme_color} for profile: {profile_key}")
        clip = ColorClip(size=(1080, 1920), color=theme_color, duration=16.5)
        clip.write_videofile(fallback_path, fps=30, codec="libx264", audio=False)
        clip.close()
        print(f"[FALLBACK] ColorClip background generated at: {fallback_path}")
        return fallback_path, "video"
    except Exception as e:
        print(f"[FALLBACK_FATAL] Failed to generate ColorClip background: {e}")
        raise


# ============================================================
# Phase 3: Video Pool Selection & Quality Scoring
# ============================================================

# カテゴリマッピング辞書（トピック/search_queryからビデオプールフォルダへのマッピング）
CATEGORY_MAPPING = {
    "deep_sea":   ["abyss", "trench", "pitch black", "hydrothermal", "submarine", "deep sea", "deep ocean", "anglerfish", "bioluminescent"],
    "reef":       ["coral", "reef", "clownfish", "anemone", "tropical", "barrier reef", "nemo", "parrotfish", "sea fan", "symbiotic"],
    "jellyfish":  ["jellyfish", "jelly", "plankton", "moon jelly", "box jelly", "floating", "translucent"],
    "predator":   ["shark", "piranha", "barracuda", "eel", "moray", "stingray", "orca", "killer whale", "predator", "hunt"],
    "schooling":  ["school of fish", "sardine", "anchovy", "herring", "tuna", "migration", "swarm", "shoal"],
    "freshwater": ["river", "pond", "salmon", "lake", "stream", "creek", "freshwater", "catfish", "bass", "trout", "carp"],
    "macro":      ["nudibranch", "seahorse", "shrimp", "crab", "lobster", "starfish", "sea urchin", "octopus", "squid", "snail", "worm", "microscopic", "tiny"],
    "default":    ["ocean", "sea", "marine", "underwater", "water", "wave", "fish"]
}

def _load_blacklist(work_dir="."):
    """ブラックリストJSONをロードする"""
    bl_path = os.path.join(work_dir, "assets", "assets_blacklist.json")
    if os.path.exists(bl_path):
        try:
            with open(bl_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[BLACKLIST_WARN] Failed to load blacklist: {e}")
    return {"blacklisted_ids": [], "exclusion_tags": []}

def _is_blacklisted(video, blacklist_data):
    """Pexels動画がブラックリストに含まれるかチェック"""
    video_id = video.get("id")
    bl_ids = [item["id"] for item in blacklist_data.get("blacklisted_ids", [])]
    if video_id and int(video_id) in bl_ids:
        return True
    
    exclusion_tags = blacklist_data.get("exclusion_tags", [])
    video_tags = [t.get("name", "").lower() for t in video.get("tags", [])] if isinstance(video.get("tags"), list) else []
    video_url = video.get("url", "").lower()
    
    for etag in exclusion_tags:
        if etag in video_url or any(etag in tag for tag in video_tags):
            return True
    return False

def compute_asset_quality_score(video, search_query="", video_files=None):
    """
    アセット品質スコアリングモデル (QSM) - 改訂版
    Resolution: 20, Tag Match: 30, Exclusion: 30, Motion: 20 = Total 100
    採用しきい値: >= 60
    """
    score = 0
    
    # --- Resolution Score (max 20) ---
    if video_files:
        max_height = max((f.get("height", 0) for f in video_files), default=0)
        if max_height >= 2160:
            score += 20
        elif max_height >= 1080:
            score += 15
        elif max_height >= 720:
            score += 5
        # else: 0
    
    # --- Tag Match Score (max 30) ---
    video_tags = [t.get("name", "").lower() for t in video.get("tags", [])] if isinstance(video.get("tags"), list) else []
    video_url = video.get("url", "").lower()
    query_words = [w.strip().lower() for w in search_query.replace(",", " ").split() if w.strip()]
    
    match_count = 0
    for qw in query_words:
        if qw in video_url or any(qw in tag for tag in video_tags):
            match_count += 1
    
    if match_count >= 3:
        score += 30
    elif match_count >= 2:
        score += 20
    elif match_count >= 1:
        score += 10
    
    # --- Exclusion Score (max 30) ---
    # 人工環境（aquarium, zoo, tank）の減点、人物の減点
    penalty_tags = ["aquarium", "zoo", "tank", "person", "hand", "human", "man", "woman"]
    has_penalty = False
    for ptag in penalty_tags:
        if ptag in video_url or any(ptag in tag for tag in video_tags):
            has_penalty = True
            break
    score += (0 if has_penalty else 30)
    
    # --- Motion Score (max 20) ---
    # 動画の長さが8秒以上であればモーション豊富と判断（静止画/超短動画を排除）
    duration = video.get("duration", 0)
    if duration >= 15:
        score += 20
    elif duration >= 8:
        score += 10
    # else: 0 (短すぎる動画はモーション不足としてペナルティ)
    
    return score

def resolve_category_from_query(search_query, topic=""):
    """search_queryとtopicからビデオプールのカテゴリフォルダ名を解決する"""
    combined = f"{search_query} {topic}".lower()
    
    # defaultは最後に評価するためスキップ
    for category, keywords in CATEGORY_MAPPING.items():
        if category == "default":
            continue
        for kw in keywords:
            if kw in combined:
                return category
    return "default"

def scan_local_pool_for_topic(topic, work_dir="."):
    """
    auto_main.py から同期呼び出しされる Level 1 & 2 ローカルプール探索のエントリポイント。
    """
    used_filenames = set()
    cache_path = os.path.join(work_dir, "script_cache.json")
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f_cache:
                cache_data = json.load(f_cache)
                for item in cache_data.get("items", []):
                    for fn in item.get("local_filenames", []):
                        used_filenames.add(fn)
        except Exception:
            pass

    history_path = os.path.join(work_dir, "generated_history.json")
    if os.path.exists(history_path):
        try:
            with open(history_path, "r", encoding="utf-8") as f_hist:
                history_data = json.load(f_hist)
                for entry in history_data:
                    for fn in entry.get("local_filenames", []):
                        used_filenames.add(fn)
        except Exception:
            pass
    return resolve_video_pool_asset(search_query=topic, topic=topic, work_dir=work_dir, used_filenames=used_filenames)

def resolve_video_pool_asset(search_query, topic="", work_dir=".", used_filenames=None):
    """
    ローカルビデオプールからカテゴリマッチングでアセットを選択する（重複排除・禁止キーワード排除あり）。
    Level 1: 完全カテゴリ一致
    Level 2: 類似カテゴリ一致
    Returns: (asset_path, asset_type) or (None, None) if no local asset available.
    """
    import glob
    import os
    import json
    
    if used_filenames is None:
        used_filenames = set()
    
    pool_base = os.path.join(work_dir, "assets", "video_pool")
    if not os.path.exists(pool_base):
        print("[POOL] Video pool directory does not exist.")
        return None, None
        
    # config.json から禁止動物リストを構築
    config_path = os.path.join(work_dir, "config.json")
    forbidden_words = ["dog", "cat", "pet", "puppy", "puppies", "kitten", "hamster", "bird", "living room", "indoor"]
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f_cfg:
                config_data = json.load(f_cfg)
                fallback_key = os.path.basename(os.getcwd())
                profile_cfg = config_data.get(fallback_key) or list(config_data.values())[0]
                forbidden_words.extend(profile_cfg.get("forbidden_animals", []))
        except Exception:
            pass
            
    # 複数形・表記揺れをマージ
    filter_words = []
    for fw in forbidden_words:
        fw_l = fw.lower()
        if fw_l not in filter_words:
            filter_words.append(fw_l)
        # 複数形などの派生語
        for suffix in ["s", "es", "ies"]:
            derived = f"{fw_l}{suffix}"
            if fw_l.endswith("y") and suffix == "ies":
                derived = fw_l[:-1] + "ies"
            if derived not in filter_words:
                filter_words.append(derived)

    # フィルタリング関数
    def is_safe_asset(fpath):
        fname = os.path.basename(fpath).lower()
        normalized_fname = fname.replace("-", " ").replace("_", " ")
        if any(fw in normalized_fname for fw in filter_words):
            print(f"[POOL_GUARD] Skipping local pool asset due to forbidden keywords in name: {fpath}")
            return False
        return True
    
    # Level 1: 完全カテゴリ一致
    category = resolve_category_from_query(search_query, topic)
    category_dir = os.path.join(pool_base, category)
    
    if os.path.exists(category_dir):
        mp4_files = [f for f in glob.glob(os.path.join(category_dir, "*.mp4")) 
                     if os.path.basename(f) not in used_filenames and is_safe_asset(f)]
        if mp4_files:
            selected = random.choice(mp4_files)
            print(f"[POOL_L1] Exact category match: {category} -> {os.path.basename(selected)}")
            return selected, "video"
    
    # Level 2: 類似カテゴリ一致（全カテゴリを横断検索）
    all_categories = [d for d in os.listdir(pool_base) 
                      if os.path.isdir(os.path.join(pool_base, d)) and d != category]
    random.shuffle(all_categories)
    
    for alt_category in all_categories:
        alt_dir = os.path.join(pool_base, alt_category)
        mp4_files = [f for f in glob.glob(os.path.join(alt_dir, "*.mp4")) 
                     if os.path.basename(f) not in used_filenames and is_safe_asset(f)]
        if mp4_files:
            selected = random.choice(mp4_files)
            print(f"[POOL_L2] Similar category fallback: {alt_category} -> {os.path.basename(selected)}")
            return selected, "video"
    
    print("[POOL] No local pool assets available.")
    return None, None


async def assemble_video_professional(script, asset_path, asset_type, bgm_path, output_filename, voice="ja-JP-NanamiNeural", topic="", work_dir="."):
    import time
    import subprocess as sp
    
    # 徹底的リソース解放用の初期化
    audio_clips = []
    bg_clips = []
    subs = []
    raw_bgs = []
    bg = None
    final_audio_content = None
    final_audio = None
    bgm = None
    composite = None
    temp_video_noaudio = None
    temp_audio_wav = None
    
    try:
        # 日本語チャンネルであるかをチャンネルフォルダ名（work_dir）やトピック名から100%確実に判定
        is_ja_channel = False
        combined_context = f"{voice} {topic} {work_dir} {output_filename}".lower()
        if "jp" in combined_context or "ja-jp" in combined_context or "japanese" in combined_context:
            is_ja_channel = True
        raw_sections = [s.strip() for s in re.split(r'(?<=[。！!？\?\n])', script) if s.strip()]
        if not is_ja_channel:
            raw_sections = [normalize_english_text(s) for s in raw_sections]
            raw_sections = [re.sub(r"(\w+)\s*'\s*(s|t|re|ve|ll|m|d)\b", r"\1'\2", s, flags=re.IGNORECASE) for s in raw_sections]
            raw_sections = [re.sub(r"\bIt\s+s\b", "It's", s, flags=re.IGNORECASE) for s in raw_sections]
        else:
            raw_sections = [cleanse_japanese_text(s) for s in raw_sections]
            
        n = len(raw_sections)
        if n > 2:
            # 強制的に2シーン（前半・後半）に統合する
            if is_ja_channel:
                sections = ["".join(raw_sections[:n//2]), "".join(raw_sections[n//2:])]
            else:
                sections = [" ".join(raw_sections[:n//2]), " ".join(raw_sections[n//2:])]
        elif n == 2:
            sections = raw_sections
        else:
            # 1文しか生成されなかった場合の安全弁
            sections = raw_sections

        if not is_ja_channel:
            sections = [normalize_english_text(s) for s in sections]
            sections = [re.sub(r"(\w+)\s*'\s*(s|t|re|ve|ll|m|d)\b", r"\1'\2", s, flags=re.IGNORECASE) for s in sections]
            sections = [re.sub(r"\bIt\s+s\b", "It's", s, flags=re.IGNORECASE) for s in sections]
        else:
            sections = [cleanse_japanese_text(s) for s in sections]

        temp_dir = os.path.join(work_dir, "temp_audio")
        os.makedirs(temp_dir, exist_ok=True)
        
        PAUSE_DURATION = 0.4  # 各シーン間に挿入する無音の「間（ま）」の長さ（秒）
        curr = 0
        for i, txt in enumerate(sections):
            a_path = os.path.join(temp_dir, f"s_{i}.mp3")
            await generate_speech(txt, a_path, voice=voice)
            clip = AudioFileClip(a_path)
            audio_clips.append(clip.set_start(curr))
            curr += clip.duration
            # 最後のセクション以外は、息継ぎ用の無音ポーズを挿入
            if i < len(sections) - 1:
                curr += PAUSE_DURATION
        
        # ■ バグ修正2(タイムマージン不足): 音声が完全に喋り終わった後、1.5秒の余韻タイムを強制的に追加する
        duration = min(curr + 1.5, 16.5)
        # ■ バグ修正(無音化): CompositeAudioClipにdurationを明示設定
        final_audio_content = CompositeAudioClip(audio_clips).set_duration(duration)
        
        # ■ バグ修正(アスペクト比): 横長・縦長の両方に対応する鉄壁クロップロジック
        TARGET_W, TARGET_H = 1080, 1920
        
        # 複数動画の切り替え処理（シーンリストに合わせて背景クリップを生成）
        if asset_type == "video" and asset_path:
            paths = asset_path.split(',')
            t_start = 0
            for i, txt in enumerate(sections):
                p = paths[i] if i < len(paths) else paths[-1]
                dur = audio_clips[i].duration
                # 動画の表示時間を計算 (最後のクリップは余白時間を含める)
                if i == len(sections) - 1:
                    clip_dur = duration - t_start
                else:
                    clip_dur = dur
                    
                if clip_dur <= 0:
                    break
                    
                raw_bg = VideoFileClip(p).without_audio()
                raw_bgs.append(raw_bg)
                src_w, src_h = raw_bg.size
                scale_w = TARGET_W / src_w
                scale_h = TARGET_H / src_h
                scale = max(scale_w, scale_h)
                new_w, new_h = int(src_w * scale), int(src_h * scale)
                bg_clip = raw_bg.resize((new_w, new_h)).crop(x_center=new_w/2, y_center=new_h/2, width=TARGET_W, height=TARGET_H)
                
                # ループするか切り取る
                bg_clip = bg_clip.fx(vfx.loop, duration=clip_dur) if bg_clip.duration < clip_dur else bg_clip.subclip(0, clip_dur)
                bg_clips.append(bg_clip.set_start(t_start))
                t_start += dur
                
            # 背景クリップを結合
            bg = CompositeVideoClip(bg_clips, size=(TARGET_W, TARGET_H)).set_duration(duration)
        else:
            print("[FATAL_ERROR] Background video assets are missing. ColorClip is strictly PROHIBITED.")
            import sys
            sys.exit(1)

        is_ja_channel = voice.startswith("ja-JP")

        t_curr = 0
        for i, txt in enumerate(sections):
            dur = audio_clips[i].duration
            # 字幕の表示時間も厳密に管理
            if t_curr + dur > duration:
                dur = duration - t_curr
            if dur <= 0: break
            
            wrapped_txt = _wrap_text_simple(txt, is_ja_channel=is_ja_channel)
            img = create_boxed_text_image(wrapped_txt, is_ja_channel=is_ja_channel)
            img_p = os.path.join(temp_dir, f"t_{i}.png")
            img.save(img_p)
            subs.append(ImageClip(img_p).set_start(t_curr).set_duration(dur))
            t_curr += dur

        # ■ バグ修正(無音化): BGM合成時もdurationを明示
        final_audio = final_audio_content
        if bgm_path and os.path.exists(bgm_path):
            try:
                bgm = AudioFileClip(bgm_path).volumex(0.15).fx(afx.audio_loop, duration=duration)
                final_audio = CompositeAudioClip([final_audio_content.volumex(1.0), bgm]).set_duration(duration)
            except Exception as e:
                print(f"BGM loading failed: {e}")

        # ■ 根本修正(無音化バグ): MoviePyのset_audio()を信用しない。
        # 映像と音声を別々に書き出し、ffmpegで物理的にmuxする2パス方式。
        temp_video_noaudio = os.path.join(work_dir, f"temp_video_noaudio_{int(time.time())}.mp4")
        temp_audio_wav = os.path.join(work_dir, f"temp_final_audio_{int(time.time())}.wav")
        
        # PASS 1: 映像のみ（音声なし）を書き出し
        print("[2PASS] Writing video track (no audio)...")
        composite = CompositeVideoClip([bg] + subs, size=(TARGET_W, TARGET_H)).set_duration(duration)
        composite.write_videofile(
            temp_video_noaudio,
            fps=30,
            codec="libx264",
            audio=False,
            ffmpeg_params=["-pix_fmt", "yuv420p"]
        )
        
        # PASS 2: 音声をWAVとして書き出し
        print("[2PASS] Writing audio track (WAV)...")
        final_audio.write_audiofile(temp_audio_wav, fps=44100)
        
        # PASS 3: ffmpegで映像＋音声を物理結合
        print("[2PASS] Muxing video + audio with ffmpeg...")
        ffmpeg_cmd = [
            "ffmpeg", "-y",
            "-i", temp_video_noaudio,
            "-i", temp_audio_wav,
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            "-movflags", "faststart",
            output_filename
        ]
        result = sp.run(ffmpeg_cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            print(f"[2PASS] ffmpeg stderr: {result.stderr[-500:]}")
            raise Exception(f"ffmpeg mux failed with code {result.returncode}")
        
        print(f"[2PASS] Mux complete: {output_filename}")
        
        # 映像ファイルに音声が実在するかプローブで検証
        probe_cmd = ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=codec_name", "-of", "csv=p=0", output_filename]
        probe = sp.run(probe_cmd, capture_output=True, text=True, timeout=10)
        audio_codec_found = probe.stdout.strip()
        print(f"[AUDIO_VERIFY] Audio codec in final mp4: '{audio_codec_found}'")
        if not audio_codec_found:
            raise Exception("FATAL: Final mp4 has NO audio stream after mux!")
        
        return output_filename, True
    except Exception as e:
        print(f"Video assembly failed: {e}")
        import traceback
        traceback.print_exc()
        return None, False
    finally:
        # 徹底的なリソース解放
        print("[CLEANUP] Force closing MoviePy clips and removing temporary render files...")
        if composite:
            try: composite.close()
            except: pass
        if bg:
            try: bg.close()
            except: pass
        for r_bg in raw_bgs:
            try: r_bg.close()
            except: pass
        for s in subs:
            try: s.close()
            except: pass
        if final_audio:
            try: final_audio.close()
            except: pass
        if final_audio_content:
            try: final_audio_content.close()
            except: pass
        for a in audio_clips:
            try: a.close()
            except: pass
        for b_clip in bg_clips:
            try: b_clip.close()
            except: pass
        if bgm:
            try: bgm.close()
            except: pass
            
        # 一時作業用レンダリングファイルの完全クリーンアップ
        for tmp in [temp_video_noaudio, temp_audio_wav]:
            if tmp and os.path.exists(tmp):
                try:
                    os.remove(tmp)
                    print(f"[CLEANUP] Deleted temporary render file: {tmp}")
                except Exception as clean_err:
                    print(f"[CLEANUP_WARN] Failed to delete temporary render file {tmp}: {clean_err}")

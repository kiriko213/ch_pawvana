import os
import time
import google.generativeai as genai
import google.api_core.exceptions

def generate_viral_script(topic="health", channel_context="", api_key=None, feedback=None, language="en", profile_key="", past_titles=None):
    """
    【エコモード仕様】
    Googleへのリクエスト回数と送信トークンを極限まで削ぎ落とし、
    1回の実行につきAPIコールを最短・最小の1回で完結させます。
    """
    if api_key:
        import json
        from google.oauth2 import service_account

        service_account_str = os.environ.get("GEMINI_SERVICE_ACCOUNT")
        credentials = None
        if service_account_str:
            try:
                info = json.loads(service_account_str)
                credentials = service_account.Credentials.from_service_account_info(info)
            except Exception:
                if os.path.exists(service_account_str):
                    try:
                        credentials = service_account.Credentials.from_service_account_file(service_account_str)
                    except Exception:
                        pass
        if credentials:
            genai.configure(credentials=credentials)
        else:
            genai.configure(api_key=api_key)

    model = genai.GenerativeModel('gemini-2.5-flash')

    # エコモード用極短プロンプト（コンテキストを完全排除）
    if language == "ja":
        prompt = f"YouTubeショート動画用として「{topic}」に関するナレーション（100〜150文字程度）を日本語で作成してください。余計な前置きやタイトルは一切省き、ナレーションテキストのみを出力してください。"
    else:
        prompt = f"Write a 15-second narration script for a YouTube Short about '{topic}' in English. Keep it to 18-22 words. Output ONLY the narration text. No titles, no introduction, no emojis, no markdown, and no extra notes."

    print(f"[ECO_MODE] Sending minimal prompt to Gemini...")

    # 429エラー時はリトライせず、即座に例外を発生させる
    try:
        response = model.generate_content(prompt)
    except google.api_core.exceptions.ResourceExhausted as rate_e:
        print("[RATE_LIMIT] 429 ResourceExhausted detected. Immediately aborting without retry.")
        raise rate_e
    except Exception as e:
        print(f"[GENERATION_ERROR] Failed to call Gemini API: {e}")
        raise e

    content = response.text.strip()
    # 余分な改行やクォートを取り除く
    content = content.replace('"', '').replace("'", "").strip()
    
    # タイトルと検索キーワードは、プログラム側の固定テンプレート/ルールで生成
    title = f"Amazing {topic}!"
    
    # Pexelsキーワードのマッピング
    topic_lower = topic.lower()
    profile_lower = profile_key.lower() if profile_key else ""
    if "dog" in profile_lower or "dog" in topic_lower:
        keyword = "dog,puppy"
    elif "pawvana" in profile_lower or "pet" in profile_lower or "pet" in topic_lower:
        keyword = "cute pet,cat,dog"
    elif "deep sea" in topic_lower:
        keyword = "deep sea,ocean"
    elif "strange ocean" in topic_lower or "creatures" in topic_lower:
        keyword = "strange fish,marine life"
    elif "coral reef" in topic_lower:
        keyword = "coral reef,fish"
    elif "freshwater" in topic_lower:
        keyword = "freshwater fish,river"
    elif "aquarium" in topic_lower:
        keyword = "aquarium,jellyfish"
    else:
        keyword = "marine life,ocean"

    print(f"[ECO_MODE] Generated script content: {content}")
    print(f"[ECO_MODE] Generated local title: {title}")
    print(f"[ECO_MODE] Generated local search query: {keyword}")

    return title, content, keyword, None

def clean_script_text(text: str) -> str:
    import re
    if not text:
        return ""
    text = re.sub(r'(\b\w+)\s+(t\b|\btell\b)', r'\1\2', text)
    text = re.sub(r'(\bWha\b)\s+(t\'s)', r"What's", text)
    text = re.sub(r'\*\s*([^*]+)\s*\*', r'*\1*', text)
    text = re.sub(r' {2,}', ' ', text)
    return text.strip()

def _parse_json_response(text):
    # エコモードではJSONパースは行わないが、他からの呼び出しでのエラーを防ぐためにダミーを用意
    return {}

def generate_viral_scripts_batch(topic="health", api_key=None, batch_size=5, language="en", profile_key="", work_dir="."):
    """
    Gemini APIを1回呼び出し、指定されたトピックに関するShorts台本を指定数（デフォルト5本）一括生成します。
    返り値: スクリプトオブジェクトのリスト
    """
    import os
    import json
    import re
    import google.generativeai as genai

    if api_key:
        service_account_str = os.environ.get("GEMINI_SERVICE_ACCOUNT")
        credentials = None
        if service_account_str:
            try:
                info = json.loads(service_account_str)
                from google.oauth2 import service_account
                credentials = service_account.Credentials.from_service_account_info(info)
            except Exception:
                if os.path.exists(service_account_str):
                    try:
                        from google.oauth2 import service_account
                        credentials = service_account.Credentials.from_service_account_file(service_account_str)
                    except Exception:
                        pass
        if credentials:
            genai.configure(credentials=credentials)
        else:
            genai.configure(api_key=api_key)

    # JSONレスポンス出力を強制するための設定
    model = genai.GenerativeModel(
        'gemini-2.5-flash',
        generation_config={"response_mime_type": "application/json"}
    )

    # Dynamically build augmented prompt using performance feedback & diversity guard
    try:
        from prompt_builder import PromptBuilder
        # キャッシュの存在するカレントディレクトリを指定してビルダ初期化
        builder = PromptBuilder(work_dir=".")
        prompt = builder.build_augmented_prompt(topic, language=language, batch_size=batch_size)
    except Exception as pb_err:
        print(f"[PROMPT_BUILDER_WARN] Prompt Builder failed: {pb_err}. Falling back to default prompt.")
        if language == "ja":
            prompt = f"""
            Generate exactly {batch_size} independent YouTube Shorts narration scripts about '{topic}' in Japanese.
            Output MUST be a valid JSON array matching the schema below. No explanation, no markdown backticks, no markdown blocks.

            JSON Schema:
            [
              {{
                "topic": "サブトピック名",
                "title": "動画タイトル (50文字以内)",
                "script": "100文字から150文字程度の日本語ナレーションテキストのみ。余計な前置きや絵文字は一切除外すること。"
              }}
            ]
            """
        else:
            prompt = f"""
            Generate exactly {batch_size} independent YouTube Shorts narration scripts in English.
            Output MUST be a valid JSON array matching the schema below. No explanation, no markdown backticks, no markdown blocks.

            [PAWVANA BRAND DNA]
            Brand: "Fast. Funny. No fluff."
            Purpose: STOP THE SCROLL. Not to educate. Not to inform. To make the viewer think "Wait... what?" in the first 2 seconds.
            Tone: punchy, witty, slightly chaotic. Never dry. Never a lecture.
            Topics: surprising and bizarre facts about BOTH dogs AND cats.
            The batch MUST include both dog and cat topics.

            [MANDATORY 4-PART SCRIPT STRUCTURE]
            Every script MUST follow this structure:
            1. QUESTION (1-3s): Bizarre, punchy opener. Under 10 words. No warm-up.
            2. UNEXPECTED TRUTH (3-7s): The counterintuitive or shocking fact.
            3. TINY EXPLANATION (7-12s): One vivid sentence explaining WHY. No lecturing.
            4. END (12-15s): Punchline or mind-blow that leaves viewer thinking "I didn't know that."

            Good hook examples: "Your cat is actually a liquid." / "Dogs can smell time." / "This sound heals broken bones."
            Bad hooks: "Did you know dogs are amazing?" / "Here is an interesting cat fact."

            JSON Schema:
            [
              {{
                "topic": "Specific sub-topic name",
                "title": "Video title (under 50 chars, must trigger 'Wait...what?' reaction)",
                "script": "15-second narration (35 to 45 words). Follow 4-part structure: Question → Unexpected Truth → Tiny Explanation → End. Short punchy sentences only. No emojis. No quotation marks. No preamble."
              }}
            ]
            """

    print(f"[BATCH_MODE] Requesting {batch_size} scripts from Gemini...")
    try:
        response = model.generate_content(prompt)
        raw_text = response.text.strip()
        
        # Markdownのコードブロック記法 (```json ... ```) が含まれる場合のトリミング保護
        if raw_text.startswith("```"):
            raw_text = re.sub(r'^```(?:json)?\n', '', raw_text)
            raw_text = re.sub(r'\n```$', '', raw_text)
            raw_text = raw_text.strip()
            
        items = json.loads(raw_text)
        if not isinstance(items, list):
            raise ValueError("Gemini response is not a JSON list")

        # --- Concept-duplication validation & Incremental replenishment loop ---
        from concept_guard import extract_concepts, get_uploaded_concepts
        import re as _re

        # 1. 過去のアップロード済みコンセプトの取得
        cache_path = os.path.join(work_dir, "script_cache.json")
        uploaded_concepts = get_uploaded_concepts(cache_path)
        
        seen_batch_concepts = set()
        valid_items = []

        def _normalize_topic(raw):
            t = raw.lower().strip()
            t = _re.sub(r'[^a-z0-9\s]', '', t)
            t = _re.sub(r'\s+', ' ', t).strip()
            return t

        def _topics_are_near_identical(a, b):
            if a == b:
                return True
            words_a = set(a.split())
            words_b = set(b.split())
            if not words_a or not words_b:
                return False
            intersection = words_a & words_b
            smaller = min(len(words_a), len(words_b))
            if smaller > 0 and len(intersection) / smaller >= 0.90:
                return True
            return False

        # 最初の一括生成されたアイテムを検証
        for item in items:
            item_topic = item.get("topic", "")
            item_title = item.get("title", "")
            item_script = item.get("script", "")
            
            # コンセプトの抽出
            item_concepts = set()
            item_concepts.update(extract_concepts(item_topic))
            item_concepts.update(extract_concepts(item_title))
            item_concepts.update(extract_concepts(item_script))
            
            # A. 過去のアップロードとの重複チェック
            overlap_global = item_concepts.intersection(uploaded_concepts)
            if overlap_global:
                print(f"[GENERATION_GUARD] Global overlap detected for '{item_topic}': {overlap_global}. Skipping.")
                continue
                
            # B. 同一バッチ内でのコンセプト重複チェック
            overlap_batch = item_concepts.intersection(seen_batch_concepts)
            if overlap_batch:
                print(f"[GENERATION_GUARD] Batch overlap detected for '{item_topic}': {overlap_batch}. Skipping.")
                continue

            # C. トピックの厳密な類似チェック
            norm_topic = _normalize_topic(item_topic)
            is_near_identical = False
            for prev_item in valid_items:
                prev_norm = _normalize_topic(prev_item.get("topic", ""))
                if _topics_are_near_identical(norm_topic, prev_norm):
                    is_near_identical = True
                    break
            if is_near_identical:
                print(f"[GENERATION_GUARD] Near-identical topic detected for '{item_topic}'. Skipping.")
                continue
            
            # すべてのガードを通過した場合
            valid_items.append(item)
            seen_batch_concepts.update(item_concepts)

        # 不足分がある場合、Gemini APIに対して再生成/補充ループを実行する (最大3回リトライ)
        max_retries = 3
        retry_count = 0
        while len(valid_items) < batch_size and retry_count < max_retries:
            needed_count = batch_size - len(valid_items)
            retry_count += 1
            print(f"[GENERATION_GUARD] Batch incomplete ({len(valid_items)}/{batch_size}). Replenishing {needed_count} items (Attempt {retry_count}/{max_retries})...")
            
            # 禁止する既存コンセプト（過去 + 現在バッチ）の一覧をプロンプト用に結合
            forbidden_list = sorted(list(uploaded_concepts.union(seen_batch_concepts)))
            forbidden_instr = ""
            if forbidden_list:
                forbidden_instr = f"\n[FORBIDDEN CONCEPTS / TOPICS]\nDo NOT generate any scripts related to the following concepts:\n"
                forbidden_instr += "\n".join([f"- {c}" for c in forbidden_list])
                forbidden_instr += "\nFocus on entirely new topics that do not overlap with the forbidden list."

            # リトライ用のプロンプト構築
            retry_prompt = prompt
            str_batch_size = str(batch_size)
            retry_prompt = retry_prompt.replace(f"exactly {str_batch_size} independent", f"exactly {needed_count} independent")
            retry_prompt = retry_prompt.replace(f"正確に{str_batch_size}本", f"正確に{needed_count}本")
            retry_prompt = retry_prompt.replace(f"約{str_batch_size}本", f"約{needed_count}本")
            retry_prompt = retry_prompt.replace(f"of {str_batch_size} scripts", f"of {needed_count} scripts")
            retry_prompt = retry_prompt.replace(f"うち、約{str_batch_size}%", f"うち、約{needed_count}%")
            retry_prompt += "\n" + forbidden_instr
            
            try:
                # 補充リクエストの送信
                response = model.generate_content(retry_prompt)
                raw_text = response.text.strip()
                if raw_text.startswith("```"):
                    raw_text = re.sub(r'^```(?:json)?\n', '', raw_text)
                    raw_text = re.sub(r'\n```$', '', raw_text)
                    raw_text = raw_text.strip()
                
                new_items = json.loads(raw_text)
                if isinstance(new_items, list):
                    for item in new_items:
                        if len(valid_items) >= batch_size:
                            break
                        item_topic = item.get("topic", "")
                        item_title = item.get("title", "")
                        item_script = item.get("script", "")
                        
                        item_concepts = set()
                        item_concepts.update(extract_concepts(item_topic))
                        item_concepts.update(extract_concepts(item_title))
                        item_concepts.update(extract_concepts(item_script))
                        
                        overlap_global = item_concepts.intersection(uploaded_concepts)
                        if overlap_global:
                            print(f"[GENERATION_GUARD] [RETRY] Global overlap for '{item_topic}': {overlap_global}. Skipping.")
                            continue
                            
                        overlap_batch = item_concepts.intersection(seen_batch_concepts)
                        if overlap_batch:
                            print(f"[GENERATION_GUARD] [RETRY] Batch overlap for '{item_topic}': {overlap_batch}. Skipping.")
                            continue

                        norm_topic = _normalize_topic(item_topic)
                        is_near_identical = False
                        for prev_item in valid_items:
                            prev_norm = _normalize_topic(prev_item.get("topic", ""))
                            if _topics_are_near_identical(norm_topic, prev_norm):
                                is_near_identical = True
                                break
                        if is_near_identical:
                            print(f"[GENERATION_GUARD] [RETRY] Near-identical topic for '{item_topic}'. Skipping.")
                            continue

                        # 合格した場合はマージ
                        valid_items.append(item)
                        seen_batch_concepts.update(item_concepts)
            except Exception as retry_err:
                print(f"[GENERATION_GUARD_WARN] Retry attempt {retry_count} failed: {retry_err}")
                
        if len(valid_items) < batch_size:
            print(f"[GENERATION_GUARD_WARN] Could not replenish to full batch size {batch_size}. Proceeding with {len(valid_items)} valid items.")
        else:
            print(f"[GENERATION_GUARD] Successfully established full batch of {batch_size} unique items.")

        # Pexels検索クエリの自動解決をバッチ生成時に行う
        profile_lower = profile_key.lower() if profile_key else ""
        for i, item in enumerate(valid_items):
            item_topic = item.get("topic", topic).lower()
            if "dog" in profile_lower or "dog" in item_topic:
                item["search_query"] = "dog,puppy"
            elif "pawvana" in profile_lower or "pet" in profile_lower or "pet" in item_topic:
                item["search_query"] = "cute pet,cat,dog"
            elif "deep sea" in item_topic:
                item["search_query"] = "deep sea,ocean"
            elif "strange ocean" in item_topic or "creatures" in item_topic:
                item["search_query"] = "strange fish,marine life"
            elif "coral reef" in item_topic:
                item["search_query"] = "coral reef,fish"
            elif "freshwater" in item_topic:
                item["search_query"] = "freshwater fish,river"
            elif "aquarium" in item_topic:
                item["search_query"] = "aquarium,jellyfish"
            else:
                item["search_query"] = "dog"
                
        return items
    except Exception as e:
        print(f"[BATCH_ERROR] Failed to generate/parse batch: {e}")
        raise e


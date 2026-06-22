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

def generate_viral_scripts_batch(topic="health", api_key=None, batch_size=5, language="en", profile_key=""):
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
            Generate exactly {batch_size} independent YouTube Shorts narration scripts about '{topic}' in English.
            Output MUST be a valid JSON array matching the schema below. No explanation, no markdown backticks, no markdown blocks.

            JSON Schema:
            [
              {{
                "topic": "Specific sub-topic name",
                "title": "Video title (under 50 chars)",
                "script": "15-second narration (18 to 22 words, output only the narration text, no emojis, no quotation marks)"
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
            
        # Pexels検索クエリの自動解決をバッチ生成時に行う
        profile_lower = profile_key.lower() if profile_key else ""
        for i, item in enumerate(items):
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
                item["search_query"] = "marine life,ocean"
                
        return items
    except Exception as e:
        print(f"[BATCH_ERROR] Failed to generate/parse batch: {e}")
        raise e


import os
import google.generativeai as genai
import datetime
import re

def generate_viral_script(topic="health", channel_context="", api_key=None, feedback=None, language="en"):
    \"\"\"
    実行役: 動画の台本を生成する。
    \"\"\"
    if api_key:
        genai.configure(api_key=api_key)
    
    model = genai.GenerativeModel('gemini-2.5-flash')
    
    feedback_section = ""
    if feedback:
        feedback_section = f\"\"\"
        === FEEDBACK FROM AUDITOR/SYSTEM (PLEASE FIX THESE POINTS) ===
        {feedback}
        ==============================================================
        \"\"\"
 
    if language == "ja":
        prompt = f\"\"\"
        あなたはプロのYouTubeショート動画プロデューサーです。日本の視聴者向けに。
        以下のトピックについて、15秒のバイラルな台本を作成してください。
        
        トピック: {topic}
        {channel_context}
        
        {feedback_section}
        
        === 構成ルール（Ultra-Tight 15s Golden Ratio） ===
        1. 【0〜3秒：フック】必ず「〜って知ってた？」や「〜と思ってない？」という全角疑問符（？）付きの強力な問いかけから開始すること（語尾を上げるイントネーションを確定させるため）。（例：「猫のひげって飾りじゃないって知ってた？」）
        2. 【3〜12秒：コア】意外な事実や雑学の核心を、短い2つの文（2セクション）でテンポよく伝えること。
        3. 【12〜15秒：結び】必ず「みんなは知ってた？」「コメントで教えてね！」等のコメント誘導、または強い共感文（1文）で締めること。
        
        === 厳守ルール ===
        - 【超重要・総文字数の絶対上限】総文字数は必ず「60文字〜75文字」の間（スペース・改行を除く）に厳密に収めてください。これ以上短い、または長い台本は完全禁止とします（1文字でも超えればエラーとみなします）。
        - 【テロップ細分化（シーン切り替え）】15秒の中でテロップ（文）が「4回〜5回」に細かく分割されるよう、必ず「フック（1文）？＋コア（短い2文）＋結び（1文）！」という合計4文の構成で作成してください。
        - 自然な日本語。絵文字は使用しないこと。
        - 視聴者が賢くなったと感じる「雑学」のトーンにすること。
        
        Title: [バイラルなタイトル]
        Content:
        [強力なフック質問文]？ [意外な事実のコア文1]。 [雑学の納得コア文2]。 [コメント誘導または共感の結び文]！
        PexelsKeyword: [映像検索用の英語キーワード。動物や地理のテーマを必ず含めること]
        \"\"\"
    else:
        prompt = f\"\"\"
        You are a professional YouTube Shorts producer for an English channel.
        Create an extremely fast, high-impact 15-second viral script.
        
        Topic: {topic}
        {channel_context}
        
        {feedback_section}
        
        === STRUCTURE (Ultra-Tight 15s Golden Ratio) ===
        1. [0-3s: Hook] Start with a very short, punchy question ending with a question mark (?).
           - AVOID cliches like "Did you know...?" or "What if I told you...?"
           - USE high-impact, ultra-short hooks instead (e.g., "Ever seen...?", "Think you know this...?", "Doing this?").
        2. [3-12s: Core] Deliver the surprising facts or core insight in exactly two ultra-short, action-oriented sentences. Strip away unnecessary adjectives and adverbs. Keep it under 12 seconds total.
        3. [12-15s: Closing] End with a short, comment-triggering question or strong empathetic call (1 sentence, e.g., "Think so? Comment below!", "What do you think?").
        
        === STRICT RULES ===
        - [STRICT WORD COUNT] Total word count MUST be strictly between 30 to 37 words max to ensure it easily reads within 12-13 seconds. Absolutely NO exceptions (not even a single word over).
        - [SCENE SEGMENTATION (4-5 Cuts)] Ensure the script is written in exactly 4 very short sentences (Hook + 2 Core Sentences + Closing) so that the video caption divides into 4 dynamic text changes, preventing static screens.
        - No emojis. Natural tone.
        
        === OUTPUT FORMAT ===
        Title: [Viral Title]
        Content:
        [Short Hook Question]? [Punchy Core Sentence 1]. [Punchy Core Sentence 2]. [Comment-triggering Closing Sentence]!
        PexelsKeyword: [English keyword for video search. Must include the core theme]
        \"\"\"
    
    try:
        response = model.generate_content(prompt)
        text = response.text
        
        title_match = re.search(r"Title:\\s*(.*)", text)
        title = title_match.group(1).strip() if title_match else f"Insights on {topic}"
        
        content_match = re.search(r"Content:\\s*(.*)", text, re.DOTALL)
        content = content_match.group(1).strip() if content_match else text
        
        keyword_match = re.search(r"PexelsKeyword:\\s*(.*)", text)
        keyword = "animal"
        if keyword_match:
            keyword = keyword_match.group(1).strip()
            content = content.replace(keyword_match.group(0), "").strip()
            
        return title, content, keyword
    except Exception as e:
        print(f"FATAL: Gemini Generation Error: {e}")
        raise

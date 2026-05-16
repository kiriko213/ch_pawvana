import os
import google.generativeai as genai
import datetime
import re

def generate_viral_script(topic="health", channel_context="", api_key=None, feedback=None, language="en"):
    """
    実行役: 動画の台本を生成する。
    """
    if api_key:
        genai.configure(api_key=api_key)
    
    model = genai.GenerativeModel('gemini-flash-latest')
    
    feedback_section = ""
    if feedback:
        feedback_section = f"""
        === FEEDBACK FROM AUDITOR/SYSTEM (PLEASE FIX THESE POINTS) ===
        {feedback}
        ==============================================================
        """

    if language == "ja":
        prompt = f"""
        あなたはプロのYouTubeショート動画プロデューサーです。
        日本の視聴者が「えっ？そうなの？」と驚き、最後まで見てしまう動画の台本を作成してください。
        
        トピック: {topic}
        {channel_context}
        
        {feedback_section}
        
        === 構成ルール（3部構成） ===
        1. 【フック】視聴者が足を止める疑問や意外な事実の提示 (4秒)
        2. 【結論】その理由や意外な結末を一言で (4秒)
        3. 【解説】野生の名残りや生物学的な背景などの納得感ある解説 (7-10秒)
        
        === 厳守ルール ===
        - 【絶対禁止】「フォローしてね」「チャンネル登録して」といった誘導（CTA）は1文字も入れないこと。
        - 文字数: 日本語で70文字〜90文字程度（15秒〜20秒のナレーション分量）。
        - 自然な日本語。絵文字禁止。
        - 視聴者が賢くなったと感じる「雑学」のトーンにすること。
        
        Title: [バイラルなタイトル]
        Content:
        [フック文]。[結論文]。[解説文]。
        PexelsKeyword: [映像検索用の英語キーワード。動物の種類を必ず含めること]
        """
    else:
        prompt = f"""
        You are a professional YouTube Shorts producer.
        Create a viral script that makes viewers stop scrolling with a "Wait, really?" moment.
        
        Topic: {topic}
        {channel_context}
        
        {feedback_section}
        
        === STRUCTURE (3-Part Logic) ===
        1. [Hook] A mystery or a surprising question to stop the scroll (4s).
        2. [Conclusion] The surprising answer or the "why" in one punchy sentence (4s).
        3. [Explanation] Scientific background or biological reason for closure (7-10s).
        
        === STRICT RULES ===
        - [PROHIBITED] NO CTA. Do NOT include "follow us", "subscribe", or "stay tuned".
        - TOTAL DURATION: 15 to 20 seconds.
        - WORD COUNT: 45-55 words max.
        - No emojis. Natural tone.
        
        === OUTPUT FORMAT ===
        Title: [Viral Title]
        Content:
        [Hook sentence]. [Conclusion sentence]. [Explanation sentence].
        PexelsKeyword: [English keyword for video search. Must include the animal type]
        """
    
    try:
        response = model.generate_content(prompt)
        text = response.text
        
        title_match = re.search(r"Title:\s*(.*)", text)
        title = title_match.group(1).strip() if title_match else f"Insights on {topic}"
        
        content_match = re.search(r"Content:\s*(.*)", text, re.DOTALL)
        content = content_match.group(1).strip() if content_match else text
        
        keyword_match = re.search(r"PexelsKeyword:\s*(.*)", text)
        keyword = "dog" # デフォルト値（万が一用）
        if keyword_match:
            keyword = keyword_match.group(1).strip()
            content = content.replace(keyword_match.group(0), "").strip()
            
        return title, content, keyword
    except Exception as e:
        print(f"FATAL: Gemini Generation Error: {e}")
        raise


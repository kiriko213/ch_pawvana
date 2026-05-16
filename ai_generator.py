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
        あなたはプロのYouTubeショート動画プロデューサーです。日本の視聴者向けに。
        以下のトピックについて、15秒のバイラルな台本を作成してください。
        
        トピック: {topic}
        {channel_context}
        
        {feedback_section}
        
        === 厳守ルール ===
        - 合計時間: 15秒以内。
        - 文字数: 日本語で50文字〜60文字以内（絶対に超えないこと）。
        - 言語: 自然な日本語のみ。絵文字は使用しない。
        - 構成: 冒頭フック (3秒) -> 内容 (9秒) -> 結び (3秒)。
        
        Title: [バイラルなタイトル]
        Content:
        [短く、パンチの効いた文章]
        PexelsKeyword: [映像検索用の英語キーワード。絶対にチャンネルのテーマに沿ったものにすること]
        """
    else:
        prompt = f"""
        You are a professional YouTube Shorts producer for an English channel.
        Create a 15-second viral script about the topic below.
        
        Topic: {topic}
        {channel_context}
        
        {feedback_section}
        
        === STRICT RULES ===
        - TOTAL DURATION: MUST BE UNDER 15 SECONDS.
        - WORD COUNT: Aim for 40-45 words max.
        - LANGUAGE: NATURAL ENGLISH only. No emojis.
        - STRUCTURE: Hook (3s) -> Value (9s) -> CTA (3s).
        
        === OUTPUT FORMAT ===
        Title: [Viral Title]
        Content:
        [Short, punchy sentences]
        PexelsKeyword: [English keyword for video search]
        """
    
    try:
        response = model.generate_content(prompt)
        text = response.text
        
        title_match = re.search(r"Title:\s*(.*)", text)
        title = title_match.group(1).strip() if title_match else f"Insights on {topic}"
        
        content_match = re.search(r"Content:\s*(.*)", text, re.DOTALL)
        content = content_match.group(1).strip() if content_match else text
        
        keyword_match = re.search(r"PexelsKeyword:\s*(.*)", text)
        keyword = "dog"
        if keyword_match:
            keyword = keyword_match.group(1).strip()
            content = content.replace(keyword_match.group(0), "").strip()
            
        return title, content, keyword
    except Exception as e:
        print(f"Generation Error: {e}")
        return "Dog Topic", "Short dog insight for you.", "dog"

import os
import requests
import random
import re
import edge_tts
from moviepy.editor import VideoFileClip, TextClip, CompositeVideoClip, AudioFileClip, ImageClip, ColorClip, concatenate_videoclips, CompositeAudioClip, vfx, afx
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import numpy as np

# Pillow 10.0.0以降でのANTIALIASエラー対策
if not hasattr(Image, 'ANTIALIAS'):
    Image.ANTIALIAS = Image.LANCZOS

def normalize_text_for_speech(text, language="ja"):
    """
    ナレーション用にテキストを最適化する。
    - 適切な位置に句読点を挿入して「間」を作る
    - アルファベットの読みをカタカナに変換（誤読防止）
    """
    if language == "ja":
        # 誤読防止
        text = text.replace("VS", "バーサス").replace("vs", "バーサス")
        text = text.replace("AI", "エーアイ")
        # 文末に句点がない場合に補完（間を空けるため）
        if not text.endswith(("。", "！", "？")):
            text += "。"
        # 長い文章に適度な読点を打つ
        text = text.replace("、", "、").replace("  ", " ")
    else:
        text = text.replace("VS", "versus").replace("vs", "versus")
    return text

def create_boxed_text_image(text, size=(1080, 1920), fontsize=60):
    """
    中央に2-3行の読みやすい字幕画像を生成。日本語・英語の両対応。
    """
    img = Image.new('RGBA', size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    if os.name == 'nt':
        font_path = "C:\\Windows\\Fonts\\meiryo.ttc"
    else:
        # Linux (Ubuntu) 環境向けのフォント候補（CJKおよび英字標準）
        font_candidates = [
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        ]
        font_path = next((p for p in font_candidates if os.path.exists(p)), None)
    
    font = ImageFont.truetype(font_path, fontsize) if font_path and os.path.exists(font_path) else ImageFont.load_default()

    # 最大3行程度に収める
    max_width = 850
    
    # 日本語/中国語などの全角文字が含まれるか判定
    is_cjk = any(ord(char) > 0x2000 for char in text)
    
    if is_cjk:
        # 日本語などの文字単位での分割
        words = list(text.strip())
        join_char = ""
    else:
        # 英語などの単語単位での分割
        words = text.strip().split()
        join_char = " "
        
    lines = []
    current_line = ""
    
    for word in words:
        test_line = (current_line + join_char + word).strip() if current_line else word
        if draw.textbbox((0, 0), test_line, font=font)[2] > max_width and current_line:
            lines.append(current_line)
            current_line = word
        else:
            current_line = test_line
    if current_line:
        lines.append(current_line)
    
    # 描画位置の計算
    line_spacing = 30
    total_text_height = sum([draw.textbbox((0, 0), l, font=font)[3] - draw.textbbox((0, 0), l, font=font)[1] for l in lines]) + line_spacing * (len(lines) - 1)
    
    box_width = 950
    box_height = total_text_height + 120
    box_x = (size[0] - box_width) // 2
    box_y = (size[1] - box_height) // 2
    
    overlay = Image.new('RGBA', size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    overlay_draw.rounded_rectangle([box_x, box_y, box_x + box_width, box_y + box_height], radius=40, fill=(0, 0, 0, 160))
    img = Image.alpha_composite(img, overlay)
    draw = ImageDraw.Draw(img)
    
    current_y = box_y + 60
    for line in lines:
        w = draw.textbbox((0, 0), line, font=font)[2]
        x = (size[0] - w) // 2
        draw.text((x, current_y), line, font=font, fill=(255, 255, 255), stroke_width=2, stroke_fill=(0,0,0))
        current_y += draw.textbbox((0, 0), line, font=font)[3] - draw.textbbox((0, 0), line, font=font)[1] + line_spacing
        
    return img

async def generate_speech(text, output_path, voice="ja-JP-NanamiNeural", rate="+10%"):
    """
    edge-ttsを使用して音声を生成する。gTTSは使用しない。
    """
    lang = "ja" if "ja-JP" in voice else "en"
    clean_text = normalize_text_for_speech(text, language=lang)
    
    try:
        communicate = edge_tts.Communicate(clean_text, voice, rate=rate)
        await communicate.save(output_path)
        if not os.path.exists(output_path) or os.path.getsize(output_path) < 100:
            raise Exception("Audio generation failed.")
    except Exception as e:
        print(f"Speech Generation Error: {e}")
        raise

async def fetch_best_visual(query, api_key, target_animal="dog", forbidden_animals=["cat"], work_dir="."):
    """
    対象動物と禁止キーワードを厳格に指定してPexelsから動画を検索する。
    """
    headers = {"Authorization": api_key}
    
    # 除外クエリの作成
    exclude = " ".join([f"-{a}" for a in forbidden_animals])
    
    # 検索クエリの構築
    base_queries = [
        f"{target_animal} {query}",
        target_animal,
        f"cute {target_animal}"
    ]

    queries = [f"{q} {exclude}".strip() for q in base_queries]
    print(f"[DEBUG] Pexels Strict Queries: {queries}")
    
    for q in queries:
        try:
            v_url = f"https://api.pexels.com/videos/search?query={q}&per_page=15&orientation=portrait"
            res = requests.get(v_url, headers=headers)
            res.raise_for_status()
            v_data = res.json()
            if v_data.get('videos'):
                videos = v_data['videos']
                target_video = next((v for v in videos if v['duration'] >= 12), videos[0])
                best_file = [f for f in target_video['video_files'] if f['width'] >= 720][0]
                path = os.path.join(work_dir, "temp_bg.mp4")
                with open(path, 'wb') as f: f.write(requests.get(best_file['link']).content)
                return path, "video"
        except Exception as e:
            print(f"[WARN] Pexels Search Error for '{q}': {e}")
            continue
    return None, None

async def assemble_video_professional(script, asset_path, asset_type, bgm_path, output_filename, voice="ja-JP-NanamiNeural", topic="", work_dir="."):
    raw_sections = [s.strip() for s in re.split(r'[。！!？\?\n]', script) if s.strip()]
    if len(raw_sections) > 3:
        n = len(raw_sections)
        sections = [" ".join(raw_sections[:n//2]), " ".join(raw_sections[n//2:])]
    else:
        sections = raw_sections

    temp_dir = os.path.join(work_dir, "temp_audio")
    os.makedirs(temp_dir, exist_ok=True)
    
    audio_clips = []
    curr = 0
    for i, txt in enumerate(sections):
        a_path = os.path.join(temp_dir, f"s_{i}.mp3")
        await generate_speech(txt, a_path, voice=voice)
        clip = AudioFileClip(a_path)
        audio_clips.append(clip.set_start(curr))
        curr += clip.duration
    
    # 修正：末尾のチラつきを防ぐため、durationを音声の合計時間に厳密に合わせる
    duration = min(curr, 15.0) 
    final_audio_content = CompositeAudioClip(audio_clips)
    
    if asset_type == "video" and asset_path:
        clip = VideoFileClip(asset_path).without_audio()
        
        # 1. 1080x1920 (9:16) に完全に一致するアスペクト比で中央切り抜き（クロップ）
        target_ratio = 1080 / 1920
        clip_ratio = clip.w / clip.h
        
        if clip_ratio > target_ratio:
            # 横幅が広すぎる場合、高さを基準にして幅を削る
            new_w = int(clip.h * target_ratio)
            bg_cropped = clip.crop(x_center=clip.w/2, y_center=clip.h/2, width=new_w, height=clip.h)
        else:
            # 縦が長すぎる場合、幅を基準にして高さを削る
            new_h = int(clip.w / target_ratio)
            bg_cropped = clip.crop(x_center=clip.w/2, y_center=clip.h/2, width=clip.w, height=new_h)
            
        # 2. トリミングした映像を、縦横比を一切歪ませずにジャスト1080x1920にリサイズする
        bg = bg_cropped.resize(newsize=(1080, 1920))
        bg = bg.fx(vfx.loop, duration=duration) if bg.duration < duration else bg.subclip(0, duration)
    else:
        bg = ColorClip(size=(1080, 1920), color=(30, 30, 30)).set_duration(duration)

    subs = []
    t_curr = 0
    for i, txt in enumerate(sections):
        dur = audio_clips[i].duration
        # 字幕の表示時間も厳密に管理
        if t_curr + dur > duration:
            dur = duration - t_curr
        if dur <= 0: break
        
        img = create_boxed_text_image(txt)
        img_p = os.path.join(temp_dir, f"t_{i}.png")
        img.save(img_p)
        subs.append(ImageClip(img_p).set_start(t_curr).set_duration(dur))
        t_curr += dur

    final_audio = final_audio_content
    if bgm_path and os.path.exists(bgm_path):
        try:
            # BGMも動画の長さに合わせる
            bgm = AudioFileClip(bgm_path).volumex(0.15).fx(afx.audio_loop, duration=duration)
            final_audio = CompositeAudioClip([final_audio_content.volumex(1.0), bgm])
        except Exception as e:
            print(f"BGM loading failed: {e}")

    try:
        video = CompositeVideoClip([bg] + subs).set_audio(final_audio).set_duration(duration)
        video.write_videofile(output_filename, fps=30, codec="libx264", audio_codec="aac", ffmpeg_params=["-pix_fmt", "yuv420p", "-movflags", "faststart"])
        
        # クリップの解放 (Windowsでのファイルロック対策)
        video.close()
        if asset_type == "video":
            bg.close()
        for s in subs:
            s.close()
        final_audio.close()
        for a in audio_clips:
            a.close()
            
        return output_filename, True
    except Exception as e:
        print(f"Video assembly failed: {e}")
        return None, False

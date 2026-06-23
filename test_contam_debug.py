import os
import json
import asyncio
import sys
import requests

async def main():
    print("=== Pexels API Diagnostic Test ===")
    
    # 1. Pexels API キーのロード
    config_path = "config.json"
    pexels_key = None
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            config_data = json.load(f)
            cfg = config_data.get("aquatic_en") or list(config_data.values())[0]
            pexels_key = cfg.get("pexels_api_key")
            
    if not pexels_key or pexels_key == "REDACTED_API_KEY":
        pexels_key = os.environ.get("PEXELS_API_KEY") or os.environ.get("PEXELS_KEY")
        
    print(f"Pexels API Key loaded: {bool(pexels_key)}")
    if not pexels_key:
        print("Error: No API key found. Exiting diagnostic.")
        return
        
    # クエリの定義
    queries = [
        "aquarium quarantining new fish",
        "fish quarantine tank"
    ]
    
    headers = {"Authorization": pexels_key}
    
    for query in queries:
        print(f"\n--- API Request for query: '{query}' ---")
        url = f"https://api.pexels.com/videos/search?query={query}&per_page=5"
        try:
            res = requests.get(url, headers=headers, timeout=15)
            res.raise_for_status()
            data = res.json()
            videos = data.get("videos", [])
            print(f"Found {len(videos)} videos.")
            
            for idx, video in enumerate(videos):
                print(f"\nVideo #{idx+1}: ID={video.get('id')}")
                print(f"  Keys available: {list(video.keys())}")
                print(f"  URL: {video.get('url')}")
                print(f"  Tags: {video.get('tags')}")
                print(f"  User: {video.get('user')}")
                # video_files の情報も簡易表示
                files = video.get('video_files', [])
                print(f"  Num video files: {len(files)}")
                if files:
                    print(f"  First video file link: {files[0].get('link')}")
        except Exception as e:
            print(f"Error querying Pexels directly: {e}")

if __name__ == "__main__":
    asyncio.run(main())

import os
import json
import datetime
from googleapiclient.discovery import build

class AnalyticsEngine:
    def __init__(self, youtube_service, work_dir=".", cache_file="script_cache.json", registry_file="performance_registry.json"):
        self.youtube = youtube_service
        self.work_dir = work_dir
        self.cache_path = os.path.join(work_dir, cache_file)
        self.registry_path = os.path.join(work_dir, registry_file)

    def load_script_cache(self):
        if os.path.exists(self.cache_path):
            try:
                with open(self.cache_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"[ANALYTICS_WARN] Failed to read cache file: {e}")
        return {"items": []}

    def load_registry(self):
        if os.path.exists(self.registry_path):
            try:
                with open(self.registry_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"[ANALYTICS_WARN] Failed to read registry file: {e}")
        
        # デフォルト構造
        return {
            "channel": "ch_aquatic_en",
            "updated_at": "",
            "average_views": 0,
            "summary": {
                "total_videos_tracked": 0,
                "top_performing_category": "none",
                "lowest_performing_category": "none"
            },
            "items": []
        }

    def save_registry(self, data):
        try:
            data["updated_at"] = datetime.datetime.utcnow().isoformat() + "Z"
            with open(self.registry_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"[ANALYTICS] Performance registry saved to: {self.registry_path}")
            return True
        except Exception as e:
            print(f"[ANALYTICS_ERROR] Failed to save registry: {e}")
            return False

    def collect_video_ids(self, cache_data):
        """script_cache.json から uploaded 状態かつ video_id が存在する動画を抽出"""
        video_map = {}
        for item in cache_data.get("items", []):
            if item.get("status") == "uploaded" and item.get("video_id"):
                video_map[item["video_id"]] = {
                    "cache_item_id": item.get("id"),
                    "topic": item.get("topic"),
                    "category": item.get("category", "default"),
                    "title": item.get("title", "")
                }
        return video_map

    def fetch_youtube_metrics(self, video_ids):
        """YouTube Data API v3 から統計情報を一括取得 (最大50件バッチ)"""
        if not video_ids:
            return {}

        metrics_results = {}
        # 50件ずつチャンクに分ける
        id_list = list(video_ids)
        chunk_size = 50
        chunks = [id_list[i:i + chunk_size] for i in range(0, len(id_list), chunk_size)]

        for chunk in chunks:
            ids_str = ",".join(chunk)
            try:
                print(f"[ANALYTICS] Requesting metrics for {len(chunk)} videos...")
                request = self.youtube.videos().list(
                    part="statistics",
                    id=ids_str
                )
                response = request.execute()

                for item in response.get("items", []):
                    v_id = item["id"]
                    stats = item.get("statistics", {})
                    metrics_results[v_id] = {
                        "views": int(stats.get("viewCount", 0)),
                        "likes": int(stats.get("likeCount", 0)),
                        "comments": int(stats.get("commentCount", 0)),
                        # 将来拡張用フィールド (Data APIでは直接取れないため初期値null)
                        "retention": None,
                        "ctr": None,
                        "subscribers_gained": None
                    }
            except Exception as e:
                print(f"[ANALYTICS_ERROR] API error during metrics fetch: {e}")
        
        return metrics_results

    def calculate_performance_score_v1(self, metrics, average_views):
        """
        スコアリングエンジン V1 (旧モデル)
        Score = (ViewsScore * 0.5) + (LikeRatioScore * 0.4) + (CommentRatioScore * 0.1)
        """
        views = metrics.get("views", 0)
        likes = metrics.get("likes", 0)
        comments = metrics.get("comments", 0)

        ref_avg = max(100, average_views)
        views_ratio = views / ref_avg
        views_score = min(100.0, views_ratio * 50.0)

        like_ratio = likes / views if views > 0 else 0.0
        like_score = min(100.0, like_ratio * 2000.0)

        comment_ratio = comments / views if views > 0 else 0.0
        comment_score = min(100.0, comment_ratio * 10000.0)

        final_score = (views_score * 0.5) + (like_score * 0.4) + (comment_score * 0.1)
        return round(final_score, 2)

    def calculate_performance_score_v2(self, metrics, average_views, first_tracked_at_str=None):
        """
        スコアリングエンジン V2 (新モデル - Age Decay 導入)
        Score = (ViewsScore * 0.4) + (LikeRatioScore * 0.3) + (CommentRatioScore * 0.2) + (DecayScore * 0.1)
        """
        import math
        views = metrics.get("views", 0)
        likes = metrics.get("likes", 0)
        comments = metrics.get("comments", 0)

        # 1. Views Score (40%)
        ref_avg = max(100, average_views)
        views_ratio = views / ref_avg
        views_score = min(100.0, views_ratio * 50.0)

        # 2. Like Ratio Score (30%)
        like_ratio = likes / views if views > 0 else 0.0
        like_score = min(100.0, like_ratio * 2000.0)

        # 3. Comment Ratio Score (20%)
        comment_ratio = comments / views if views > 0 else 0.0
        comment_score = min(100.0, comment_ratio * 10000.0)

        # 4. Age Decay Score (10%) - 半減期14日
        days_elapsed = 0.0
        if first_tracked_at_str:
            try:
                # ISO 8601 形式のタイムスタンプをパース (Z への対応含む)
                clean_dt = first_tracked_at_str.replace("Z", "")
                if "." in clean_dt:
                    clean_dt = clean_dt.split(".")[0]
                first_tracked = datetime.datetime.strptime(clean_dt, "%Y-%m-%dT%H:%M:%S")
                delta = datetime.datetime.utcnow() - first_tracked
                days_elapsed = max(0.0, delta.total_seconds() / 86400.0)
            except Exception as pe:
                print(f"[ANALYTICS_WARN] Failed to parse first_tracked_at: {pe}")

        # 14日半減期: lambda = ln(2) / 14 = 0.04951
        decay_score = 100.0 * math.exp(-0.04951 * days_elapsed)

        final_score = (views_score * 0.4) + (like_score * 0.3) + (comment_score * 0.2) + (decay_score * 0.1)
        return round(final_score, 2)

    def generate_feedback_dataset(self, registry_data, output_file="feedback_dataset.json"):
        """
        スコア上位/下位トピックを抽出したフィードバックデータセットを出力
        """
        items = registry_data.get("items", [])
        if not items:
            return None

        # スコア順にソート
        sorted_items = sorted(items, key=lambda x: x.get("performance_score", 0.0), reverse=True)

        # Top Performing (上位5件) と Underperforming (下位5件)
        top_count = min(5, len(sorted_items))
        top_items = sorted_items[:top_count]
        
        # 下位5件 (重複を避けるためスライス)
        underperforming_items = []
        if len(sorted_items) > top_count:
            underperforming_count = min(5, len(sorted_items) - top_count)
            underperforming_items = sorted_items[-underperforming_count:]

        feedback_data = {
            "feedback_version": 1,
            "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
            "top_topics": [
                {
                    "topic": x["topic"],
                    "category": x.get("category", "default"),
                    "score": x["performance_score"],
                    "views": x["metrics"]["views"]
                } for x in top_items
            ],
            "underperforming_topics": [
                {
                    "topic": x["topic"],
                    "category": x.get("category", "default"),
                    "score": x["performance_score"],
                    "views": x["metrics"]["views"]
                } for x in underperforming_items
            ]
        }

        feedback_path = os.path.join(self.work_dir, output_file)
        try:
            with open(feedback_path, "w", encoding="utf-8") as f:
                json.dump(feedback_data, f, ensure_ascii=False, indent=2)
            print(f"[ANALYTICS] Feedback dataset generated at: {feedback_path}")
            return feedback_data
        except Exception as e:
            print(f"[ANALYTICS_ERROR] Failed to save feedback dataset: {e}")
            return None

    def update_registry(self):
        """メイン実行エントリポイント"""
        print("[ANALYTICS] Starting analytics registry update...")
        
        # 1. データロード
        cache_data = self.load_script_cache()
        registry_data = self.load_registry()
        
        # 2. 収集対象動画の選定
        video_map = self.collect_video_ids(cache_data)
        if not video_map:
            print("[ANALYTICS] No uploaded videos found in script cache. Skipping update.")
            return False

        # 3. YouTube APIからメトリクス取得
        metrics_results = self.fetch_youtube_metrics(video_map.keys())
        if not metrics_results:
            print("[ANALYTICS_WARN] No metrics retrieved from API. Skipping update.")
            return False

        # 4. 平均値の算出 (スコア用)
        total_views = sum(m["views"] for m in metrics_results.values())
        average_views = total_views / len(metrics_results) if metrics_results else 0
        registry_data["average_views"] = round(average_views, 2)

        # 5. 各アイテムの更新
        updated_items = []
        category_scores = {} # カテゴリ集計用

        for v_id, meta in video_map.items():
            metrics = metrics_results.get(v_id)
            if not metrics:
                continue

            # 既存レジストリ内アイテムの検索
            existing_item = next((x for x in registry_data["items"] if x["video_id"] == v_id), None)
            
            # first_tracked_at の判定
            now_str = datetime.datetime.utcnow().isoformat() + "Z"
            first_tracked = existing_item.get("first_tracked_at", now_str) if existing_item else now_str

            score_v1 = self.calculate_performance_score_v1(metrics, average_views)
            score_v2 = self.calculate_performance_score_v2(metrics, average_views, first_tracked)
            
            # カテゴリのパフォーマンス蓄積 (V2スコアを基準にする)
            cat = meta["category"]
            if cat not in category_scores:
                category_scores[cat] = []
            category_scores[cat].append(score_v2)

            if existing_item:
                existing_item["last_updated_at"] = now_str
                existing_item["metrics"] = metrics
                existing_item["performance_score"] = score_v2
                existing_item["performance_score_v1"] = score_v1
                existing_item["performance_score_v2"] = score_v2
                existing_item["title"] = meta["title"]
                updated_items.append(existing_item)
            else:
                new_item = {
                    "video_id": v_id,
                    "cache_item_id": meta["cache_item_id"],
                    "topic": meta["topic"],
                    "category": cat,
                    "title": meta["title"],
                    "first_tracked_at": now_str,
                    "last_updated_at": now_str,
                    "metrics": metrics,
                    "performance_score": score_v2,
                    "performance_score_v1": score_v1,
                    "performance_score_v2": score_v2
                }
                updated_items.append(new_item)

        registry_data["items"] = updated_items
        registry_data["summary"]["total_videos_tracked"] = len(updated_items)

        # 最良・最悪カテゴリの抽出
        if category_scores:
            avg_cat_scores = {k: sum(v)/len(v) for k, v in category_scores.items()}
            sorted_cats = sorted(avg_cat_scores.items(), key=lambda x: x[1], reverse=True)
            registry_data["summary"]["top_performing_category"] = sorted_cats[0][0]
            registry_data["summary"]["lowest_performing_category"] = sorted_cats[-1][0]

        # 保存
        self.save_registry(registry_data)

        # フィードバックデータセット生成
        self.generate_feedback_dataset(registry_data)
        
        return True

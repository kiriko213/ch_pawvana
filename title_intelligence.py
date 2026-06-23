import os
import json
import datetime
import re
import random

class TitleIntelligenceEngine:
    def __init__(self, work_dir=".", feedback_v2_file="feedback_dataset_v2.json", cache_file="script_cache.json", candidates_file="title_candidates.json", title_registry_file="title_performance_registry.json"):
        self.work_dir = work_dir
        self.feedback_v2_path = os.path.join(work_dir, feedback_v2_file)
        self.cache_path = os.path.join(work_dir, cache_file)
        self.candidates_path = os.path.join(work_dir, candidates_file)
        self.title_registry_path = os.path.join(work_dir, title_registry_file)
        
        self.default_patterns = [
            "The Truth About {Topic}",
            "5 Secrets of {Topic}",
            "{Topic}'s Deepest Secrets",
            "This {Topic} Will Shock You",
            "The Most Dangerous {Topic}"
        ]

    def _load_json(self, path):
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"[TI_WARN] Failed to load JSON {path}: {e}")
        return {}

    def _save_json(self, path, data):
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"[TI_ERROR] Failed to save JSON {path}: {e}")
            return False

    def discover_and_score_titles(self, topic, original_title=None):
        """
        指定されたトピックからタイトル候補群（3件以上）を自動生成し、スコアリングして保存する。
        """
        print(f"[TI] Generating and scoring title candidates for topic: {topic}...")
        feedback_data = self._load_json(self.feedback_v2_path)
        cache_data = self._load_json(self.cache_path)
        
        # 1. 勝ちパターンと履歴タイトルの収集
        winning_patterns = [p.get("pattern") for p in feedback_data.get("winning_title_patterns", []) if p.get("pattern")]
        if not winning_patterns:
            winning_patterns = self.default_patterns
            
        recent_titles = []
        # cache_data から直近のタイトルを収集
        for item in reversed(cache_data.get("items", [])):
            t = item.get("title")
            if t:
                recent_titles.append(t)
            if len(recent_titles) >= 10:
                break
                
        # 2. 候補生成 (Winning Patterns + Original)
        candidates_set = set()
        if original_title:
            candidates_set.add(original_title.strip())
            
        # パターンをトピック名で展開
        topic_clean = topic.strip().title()
        for pat in winning_patterns:
            # プレースホルダーを置換
            # {Topic} や {topic} などを大文字小文字対応で置換
            cand = pat.replace("{Topic}", topic_clean).replace("{topic}", topic_clean)
            cand = re.sub(r'\{Topic\}', topic_clean, cand, flags=re.IGNORECASE)
            candidates_set.add(cand.strip())
            
        # 最低3件の候補を確保するためのフォールバック
        if len(candidates_set) < 3:
            for pat in self.default_patterns:
                cand = pat.replace("{Topic}", topic_clean)
                candidates_set.add(cand.strip())
                if len(candidates_set) >= 3:
                    break
                    
        # 3. スコアリング
        scored_titles = []
        for title in candidates_set:
            score = self.score_title(title, topic, winning_patterns, recent_titles)
            scored_titles.append({
                "title": title,
                "score": score
            })
            
        # ソート
        scored_titles.sort(key=lambda x: x["score"], reverse=True)
        
        # 出力
        output_data = {
            "topic": topic,
            "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
            "titles": scored_titles
        }
        self._save_json(self.candidates_path, output_data)
        print(f"[TI] Saved {len(scored_titles)} title candidates to {self.candidates_path}")
        return scored_titles

    def score_title(self, title, topic, winning_patterns, recent_titles, boost_keywords=None):
        """
        各タイトルのスコアリング
        title_score = pattern_score + curiosity_score + keyword_score + novelty_score (Max: 100)
        """
        # --- 1. pattern_score (最大 30点) ---
        pattern_score = 0.0
        title_lower = title.lower().strip()
        for pat in winning_patterns:
            pat_regex = pat.replace("{Topic}", r'.+').replace("{topic}", r'.+')
            pat_regex = re.sub(r'\{Topic\}', r'.+', pat_regex, flags=re.IGNORECASE)
            try:
                if re.match(r'^' + pat_regex.lower() + r'$', title_lower):
                    pattern_score = 30.0
                    break
            except Exception:
                pass
        # 部分一致の緩いアプローチ
        if pattern_score == 0.0:
            for pat in winning_patterns:
                pat_clean = pat.replace("{Topic}", "").replace("{topic}", "").replace("'", "").strip().lower()
                if pat_clean and pat_clean in title_lower:
                    pattern_score = 15.0
                    break

        # --- 2. curiosity_score (最大 30点) ---
        # 5つの要素：mystery, surprise, hidden truth, danger, rare facts
        curiosity_categories = {
            "mystery": ["secrets", "mystery", "unknown", "hidden", "dark"],
            "surprise": ["shock", "believe", "never", "magic", "unexpected"],
            "hidden truth": ["truth", "exposed", "revealed", "lies"],
            "danger": ["dangerous", "deadly", "killer", "venomous", "attack"],
            "rare facts": ["rare", "facts", "amazing", "bizarre", "weird", "strangest"]
        }
        curiosity_score = 0.0
        for category, words in curiosity_categories.items():
            if any(w in title_lower for w in words):
                curiosity_score += 6.0 # 1つの要素につき +6点 (最大30点)

        # --- 3. keyword_score (最大 20点) ---
        if boost_keywords is None:
            boost_keywords = ["deep sea", "ocean", "shark", "jellyfish", "bioluminescent", "giant", "mysterious"]
        keyword_score = 0.0
        for keyword in boost_keywords:
            if keyword.lower() in title_lower:
                keyword_score += 5.0 # 1キーワードにつき +5点
        keyword_score = min(20.0, keyword_score)

        # --- 4. novelty_score (最大 20点) ---
        novelty_score = 20.0
        if recent_titles:
            for rt in recent_titles:
                rt_lower = rt.lower().strip()
                if title_lower == rt_lower:
                    novelty_score = 0.0
                    break
                # 類似度の簡素な減点 (共通する文字数の比率など)
                elif len(title_lower) > 0:
                    common_chars = set(title_lower).intersection(set(rt_lower))
                    overlap_ratio = len(common_chars) / len(set(title_lower))
                    if overlap_ratio > 0.7:
                        novelty_score = max(5.0, novelty_score - 5.0)

        total_score = round(pattern_score + curiosity_score + keyword_score + novelty_score, 2)
        return total_score

    def select_best_title(self, topic, original_title, config_settings=None):
        """
        候補群の中から最高スコアのタイトルを選択し採用する。
        score_difference < 5 の場合は、最高スコアと次点のいずれかをランダム選択（探索許可）。
        """
        # config から boost_keywords としきい値を取得
        boost_keywords = None
        score_diff_limit = 5.0
        if config_settings:
            boost_keywords = config_settings.get("boost_keywords", boost_keywords)
            score_diff_limit = float(config_settings.get("score_difference_limit", score_diff_limit))

        # 1. 候補を生成しスコアリング
        feedback_data = self._load_json(self.feedback_v2_path)
        winning_patterns = [p.get("pattern") for p in feedback_data.get("winning_title_patterns", []) if p.get("pattern")]
        if not winning_patterns:
            winning_patterns = self.default_patterns

        cache_data = self._load_json(self.cache_path)
        recent_titles = []
        for item in reversed(cache_data.get("items", [])):
            t = item.get("title")
            if t:
                recent_titles.append(t)
            if len(recent_titles) >= 10:
                break

        # 候補収集
        candidates_set = {original_title.strip()}
        topic_clean = topic.strip().title()
        for pat in winning_patterns:
            cand = pat.replace("{Topic}", topic_clean).replace("{topic}", topic_clean)
            cand = re.sub(r'\{Topic\}', topic_clean, cand, flags=re.IGNORECASE)
            candidates_set.add(cand.strip())

        # 最小数確保
        if len(candidates_set) < 3:
            for pat in self.default_patterns:
                cand = pat.replace("{Topic}", topic_clean)
                candidates_set.add(cand.strip())
                if len(candidates_set) >= 3:
                    break

        # スコア算出
        scored_titles = []
        for title in candidates_set:
            score = self.score_title(title, topic, winning_patterns, recent_titles, boost_keywords)
            scored_titles.append({
                "title": title,
                "score": score
            })

        # ソート
        scored_titles.sort(key=lambda x: x["score"], reverse=True)
        
        # タイトル候補ファイル (title_candidates.json) を保存
        output_data = {
            "topic": topic,
            "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
            "titles": scored_titles
        }
        self._save_json(self.candidates_path, output_data)

        # 2. 自動選択 (A/B選定)
        if len(scored_titles) >= 2:
            best = scored_titles[0]
            runner_up = scored_titles[1]
            diff = best["score"] - runner_up["score"]
            print(f"[TI] Best Title: '{best['title']}' ({best['score']}), Runner-up: '{runner_up['title']}' ({runner_up['score']}) (Diff: {diff:.2f})")
            
            if diff < score_diff_limit:
                # ランダム探索を許可
                selected = random.choice([best["title"], runner_up["title"]])
                print(f"[TI] Score diff < {score_diff_limit}. Randomly explored title: '{selected}'")
                return selected
            else:
                print(f"[TI] Selected best title: '{best['title']}'")
                return best["title"]
        else:
            selected = scored_titles[0]["title"] if scored_titles else original_title
            print(f"[TI] Single candidate. Selected title: '{selected}'")
            return selected

    def update_performance_registry(self, video_id, title, ctr, apv, sub_gain):
        """
        投稿後の実績をベースに、タイトルの実績スコアを登録する（学習ループ用）。
        実績スコア = CTR * 10 + APV * 0.5 + sub_gain * 10 (Max: 100)
        """
        print(f"[TI] Recording performance for title: '{title}' (CTR={ctr}%, APV={apv}%, SubGain={sub_gain})...")
        
        # パフォーマンススコア算出
        ctr_val = float(ctr) if ctr is not None else 0.0
        apv_val = float(apv) if apv is not None else 0.0
        sub_gain_val = float(sub_gain) if sub_gain is not None else 0.0
        
        perf_score = round((ctr_val * 10.0) + (apv_val * 0.5) + (sub_gain_val * 10.0), 2)
        perf_score = min(100.0, perf_score)
        
        registry = self._load_json(self.title_registry_path)
        if "items" not in registry:
            registry["items"] = []
            
        # 既存アイテムの上書きまたは新規追加
        existing_item = None
        for item in registry["items"]:
            if item.get("video_id") == video_id:
                existing_item = item
                break
                
        new_entry = {
            "video_id": video_id,
            "title": title,
            "ctr": ctr_val,
            "apv": apv_val,
            "subscribers_gained": int(sub_gain_val),
            "performance_score": perf_score,
            "recorded_at": datetime.datetime.utcnow().isoformat() + "Z"
        }
        
        if existing_item:
            existing_item.update(new_entry)
        else:
            registry["items"].append(new_entry)
            
        # 容量制限（最新50件）
        registry["items"] = registry["items"][-50:]
        self._save_json(self.title_registry_path, registry)
        print(f"[TI] Title performance registered successfully. Performance Score: {perf_score}")
        return perf_score

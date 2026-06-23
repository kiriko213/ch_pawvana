import os
import json
import datetime
import re

class TopicDiscoveryEngine:
    def __init__(self, work_dir=".", feedback_v2_file="feedback_dataset_v2.json", cache_file="script_cache.json", candidates_file="topic_candidates.json"):
        self.work_dir = work_dir
        self.feedback_v2_path = os.path.join(work_dir, feedback_v2_file)
        self.cache_path = os.path.join(work_dir, cache_file)
        self.candidates_path = os.path.join(work_dir, candidates_file)
        
        self.default_seeds = [
            "anglerfish",
            "giant squid",
            "bioluminescence",
            "deep sea creatures",
            "ocean mysteries",
            "jellyfish",
            "sharks",
            "whale facts",
            "mariana trench",
            "underwater volcanoes"
        ]

    def _load_json(self, path):
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"[TD_WARN] Failed to load JSON {path}: {e}")
        return {}

    def discover_topics(self, config_ratio_settings=None):
        """
        Topic Discovery の実行エントリーポイント。
        1. 直近の CGS スコアの平均値を算出し、Exploration Ratio を決定して feedback_dataset_v2.json に書き戻す。
        2. 候補トピックを収集・拡張し、スコアリングする。
        3. 上位候補を topic_candidates.json へ保存する。
        """
        print("[TD] Running Topic Discovery Engine...")
        feedback_data = self._load_json(self.feedback_v2_path)
        cache_data = self._load_json(self.cache_path)
        
        # --- 1. Exploration Ratio (Reinforce / Explore) の動的調整 ---
        registry_path = os.path.join(self.work_dir, "performance_registry.json")
        registry_data = self._load_json(registry_path)
        
        # デフォルト設定
        threshold = 80.0
        r_high, e_high = 50, 50
        r_low, e_low = 80, 20
        
        if config_ratio_settings:
            threshold = config_ratio_settings.get("high_cgs_threshold", threshold)
            r_high = config_ratio_settings.get("reinforce_high_cgs", r_high)
            e_high = config_ratio_settings.get("explore_high_cgs", e_high)
            r_low = config_ratio_settings.get("reinforce_low_cgs", r_low)
            e_low = config_ratio_settings.get("explore_low_cgs", e_low)
            
        recent_cgs_scores = []
        items = registry_data.get("items", [])
        
        # 直近3件の有効な cgs_score を抽出
        for item in reversed(items):
            cgs = item.get("cgs_score")
            # 後方互換性のため performance_score も参照
            if cgs is None:
                cgs = item.get("performance_score")
            if cgs is not None:
                recent_cgs_scores.append(cgs)
            if len(recent_cgs_scores) >= 3:
                break
                
        avg_cgs = sum(recent_cgs_scores) / len(recent_cgs_scores) if recent_cgs_scores else 0.0
        print(f"[TD] Recent CGS Scores: {recent_cgs_scores} (Average: {avg_cgs:.2f})")
        
        if avg_cgs >= threshold:
            reinforce_pct = r_high
            explore_pct = e_high
            adjusted_by = f"high_cgs_average_{avg_cgs:.1f}"
        else:
            reinforce_pct = r_low
            explore_pct = e_low
            adjusted_by = f"low_cgs_average_{avg_cgs:.1f}"
            
        print(f"[TD] Adjusted Exploration Ratio -> Reinforce: {reinforce_pct}%, Explore: {explore_pct}%")
        
        # feedback_dataset_v2.json の比率設定を上書き保存
        if feedback_data:
            if "exploration_ratio" not in feedback_data:
                feedback_data["exploration_ratio"] = {}
            feedback_data["exploration_ratio"]["reinforce_pct"] = reinforce_pct
            feedback_data["exploration_ratio"]["explore_pct"] = explore_pct
            feedback_data["exploration_ratio"]["adjusted_by"] = adjusted_by
            try:
                with open(self.feedback_v2_path, "w", encoding="utf-8") as f:
                    json.dump(feedback_data, f, ensure_ascii=False, indent=2)
                print(f"[TD] Successfully synchronized exploration_ratio inside {self.feedback_v2_path}")
            except Exception as e:
                print(f"[TD_WARN] Failed to save updated exploration ratio in feedback: {e}")
        
        # --- 2. 候補トピック収集 & スコアリング ---
        winning_topics = feedback_data.get("winning_topics", [])
        
        # 最近使用したトピック (重複防止用)
        recent_topics = []
        cache_items = cache_data.get("items", [])
        for item in reversed(cache_items):
            t = item.get("topic")
            if t and t not in recent_topics:
                recent_topics.append(t)
            if len(recent_topics) >= 10:
                break
                
        # 過去すべてのトピック
        past_topics = []
        for item in cache_items:
            t = item.get("topic")
            if t and t not in past_topics:
                past_topics.append(t)
                
        # 候補トピックの展開
        candidates = self._generate_candidates(winning_topics, past_topics)
        
        scored_candidates = []
        for cand in candidates:
            topic_name = cand["topic"]
            category = cand["category"]
            
            # 1. Growth Score (winning_topics との関連性)
            growth_score = self._calculate_growth_score(topic_name, category, winning_topics)
            
            # 2. Novelty Score (最近投稿したトピックとの距離)
            novelty_score = self._calculate_novelty_score(topic_name, recent_topics)
            
            # 3. Diversity Score (同一カテゴリ偏重の抑制、ソート時に動的ペナルティをかけるための初期値)
            diversity_score = 30.0
            
            total_score = round(growth_score + novelty_score + diversity_score, 2)
            
            scored_candidates.append({
                "topic": topic_name,
                "category": category,
                "growth_score": growth_score,
                "novelty_score": novelty_score,
                "diversity_score": diversity_score,
                "score": total_score
            })
            
        # ダイバーシティを適用しソート
        final_candidates = self._apply_diversity_and_sort(scored_candidates)
        
        # --- 3. 保存処理 ---
        output_data = {
            "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
            "top_candidates": [
                {
                    "topic": x["topic"],
                    "score": int(x["score"]),
                    "category": x["category"]
                } for x in final_candidates[:10]
            ]
        }
        
        try:
            with open(self.candidates_path, "w", encoding="utf-8") as f:
                json.dump(output_data, f, ensure_ascii=False, indent=2)
            print(f"[TD] Successfully saved top {len(output_data['top_candidates'])} candidates to {self.candidates_path}")
            return output_data
        except Exception as e:
            print(f"[TD_ERROR] Failed to save {self.candidates_path}: {e}")
            return None

    def _generate_candidates(self, winning_topics, past_topics):
        """
        手動シード、過去トピック、勝ちトピックから組み合わせやテンプレートを利用して候補を自動拡張する。
        """
        base_seeds = list(self.default_seeds)
        
        # 勝ちトピックもシードに追加
        for wt in winning_topics:
            t = wt.get("topic")
            if t and t not in base_seeds:
                base_seeds.append(t)
                
        templates = [
            "{Seed} Secrets",
            "Mysterious {Seed}",
            "The Truth About {Seed}",
            "{Seed} Discovery",
            "How {Seed} Survives",
            "Strange {Seed} Behavior",
            "Deep Sea {Seed}"
        ]
        
        candidates = []
        seen = set()
        
        # 1. シードそのものを候補に追加
        for seed in base_seeds:
            clean_seed = seed.strip()
            if not clean_seed:
                continue
            cat = self._detect_category(clean_seed)
            if clean_seed.lower() not in seen:
                candidates.append({"topic": clean_seed, "category": cat})
                seen.add(clean_seed.lower())
                
        # 2. テンプレート展開によるバリエーション候補
        for seed in self.default_seeds:
            for temp in templates:
                # 重複した表現（例: deep sea deep sea creatures）を防ぐ
                if "deep sea" in seed.lower() and "Deep Sea" in temp:
                    continue
                cand_topic = temp.format(Seed=seed.capitalize())
                cat = self._detect_category(seed)
                if cand_topic.lower() not in seen:
                    candidates.append({"topic": cand_topic, "category": cat})
                    seen.add(cand_topic.lower())
                    
        return candidates

    def _detect_category(self, topic_name):
        topic_lower = topic_name.lower()
        if any(x in topic_lower for x in ["trench", "abyss", "volcano", "mystery", "secrets"]):
            return "geography_mysteries"
        elif any(x in topic_lower for x in ["anglerfish", "squid", "jellyfish", "shark", "whale", "creature", "octopus"]):
            return "marine_life"
        elif any(x in topic_lower for x in ["bioluminescence", "light", "glow"]):
            return "bioluminescence"
        return "default"

    def _calculate_growth_score(self, topic_name, category, winning_topics):
        """
        winning_topics との関連性スコア (Max: 40.0)
        """
        if not winning_topics:
            return 20.0 # 中立値
            
        score = 10.0
        topic_words = set(re.findall(r'\w+', topic_name.lower()))
        
        for wt in winning_topics:
            wt_name = wt.get("topic", "")
            if not wt_name:
                continue
            wt_words = set(re.findall(r'\w+', wt_name.lower()))
            
            # 共通ワードの一致度
            common = topic_words.intersection(wt_words)
            if common:
                # 勝ちトピックの CGS スコアを基準に加算
                wt_cgs = wt.get("cgs", 10.0)
                score += len(common) * (wt_cgs * 0.4)
                
            # 同一カテゴリ一致
            if wt.get("category") == category:
                score += 5.0
                
        return min(40.0, score)

    def _calculate_novelty_score(self, topic_name, recent_topics):
        """
        最近投稿したトピックとの距離 (Max: 30.0)
        重複・類似度が高いほどスコアを下げる。
        """
        if not recent_topics:
            return 30.0
            
        topic_lower = topic_name.lower()
        for i, rt in enumerate(recent_topics):
            rt_lower = rt.lower()
            # 完全一致は Novelty なし
            if topic_lower == rt_lower:
                return 0.0
            # 部分一致ペナルティ
            if rt_lower in topic_lower or topic_lower in rt_lower:
                distance_penalty = (10 - i) * 2.0
                return max(5.0, 30.0 - distance_penalty)
                
        return 30.0

    def _apply_diversity_and_sort(self, scored_candidates):
        """
        カテゴリやキーワードの偏りを抑制しつつソートする。
        同一カテゴリや同一キーワードが上位に集中した場合に diversity_score (Max 30.0) を減少させる。
        """
        # scoreで仮ソート (初期 diversity_score = 30.0)
        scored_candidates.sort(key=lambda x: x["growth_score"] + x["novelty_score"] + x["diversity_score"], reverse=True)
        
        selected = []
        seen_categories = {}
        seen_words = set()
        
        for item in scored_candidates:
            cat = item["category"]
            cat_count = seen_categories.get(cat, 0)
            # 1回重複するごとに -10.0 点
            cat_penalty = cat_count * 10.0
            
            words = set(re.findall(r'\w+', item["topic"].lower()))
            # シード用一般名詞はペナルティ対象から除く（Secrets, Mysteriousなど）
            filter_words = {w for w in words if w not in ["secrets", "mysterious", "truth", "discovery", "how", "survives", "strange", "behavior", "about"]}
            word_overlap = filter_words.intersection(seen_words)
            # 重複単語1つごとに -6.0 点
            word_penalty = len(word_overlap) * 6.0
            
            diversity_score = max(0.0, 30.0 - cat_penalty - word_penalty)
            
            item["diversity_score"] = diversity_score
            item["score"] = round(item["growth_score"] + item["novelty_score"] + item["diversity_score"], 2)
            
            selected.append(item)
            
            # トップ候補のみを偏りの基準とする（上位5件に選ばれた要素を記憶）
            if len(selected) <= 5:
                seen_categories[cat] = seen_categories.get(cat, 0) + 1
                seen_words.update(filter_words)
                
        # 最終スコアで再度ソートして決定
        selected.sort(key=lambda x: x["score"], reverse=True)
        return selected

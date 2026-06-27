import os
import re
import json
import datetime
from collections import Counter
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

class GrowthIntelligenceEngine:
    def __init__(self, youtube_service, work_dir=".", cache_file="script_cache.json", registry_file="performance_registry.json", feedback_v2_file="feedback_dataset_v2.json"):
        self.youtube = youtube_service
        self.work_dir = work_dir
        self.cache_path = os.path.join(work_dir, cache_file)
        self.registry_path = os.path.join(work_dir, registry_file)
        self.feedback_v2_path = os.path.join(work_dir, feedback_v2_file)
        self.analytics_service = None
        self.cgs_mode = "alpha" # Default is alpha (existing API only)

    def initialize_analytics_service(self, profile_key=None):
        """
        YouTube Analytics API v2 サービスを初期化する。
        スコープ不足や認証エラーの場合は例外をキャッチして alpha モードにフォールバックする（キャッシュ保護レイヤー）。
        """
        if os.environ.get("DRY_RUN", "").strip().lower() == "true":
            print("[DRY_RUN] YouTube Analytics API initialization bypassed (MOCK_SERVICE).")
            self.analytics_service = "MOCK_SERVICE"
            self.cgs_mode = "alpha"
            return
            
        try:
            print("[GI_INIT] Initializing YouTube Analytics API Service...")
            SCOPES_ANALYTICS = [
                'https://www.googleapis.com/auth/youtube.readonly',
                'https://www.googleapis.com/auth/yt-analytics.readonly'
            ]
            
            youtube_token = os.path.join(self.work_dir, "tokens", "youtube.pickle")
            env_token_key = f"YOUTUBE_TOKEN_{profile_key.upper()}_B64" if profile_key else None
            
            import sys
            if self.work_dir not in sys.path:
                sys.path.insert(0, self.work_dir)
            from main import get_authenticated_service
            
            self.analytics_service = get_authenticated_service(
                'youtubeAnalytics', 'v2', SCOPES_ANALYTICS,
                token_path=youtube_token,
                env_token_key=env_token_key,
                profile_key=profile_key,
                work_dir=self.work_dir
            )
            print("[GI_INIT] YouTube Analytics API Service initialized successfully.")
            self.cgs_mode = "beta"
        except Exception as e:
            print(f"[GI_INIT_WARN] Failed to initialize YouTube Analytics API: {e}")
            print("[GI_INIT_WARN] Falling back to Phase 5E-Alpha Mode (Data API v3 only).")
            self.analytics_service = None
            self.cgs_mode = "alpha"

    def load_script_cache(self):
        if os.path.exists(self.cache_path):
            try:
                with open(self.cache_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"[GI_WARN] Failed to read cache file: {e}")
        return {"items": []}

    def load_registry(self):
        if os.path.exists(self.registry_path):
            try:
                with open(self.registry_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"[GI_WARN] Failed to read registry file: {e}")
        return {"items": []}

    def save_registry(self, data):
        try:
            with open(self.registry_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"[GI] Performance registry synchronized successfully.")
            return True
        except Exception as e:
            print(f"[GI_ERROR] Failed to save registry: {e}")
            return False

    def fetch_analytics_kpis(self, video_ids):
        """
        YouTube Analytics API v2 から指定動画ID群のKPIを一括取得する。
        """
        if not self.analytics_service or not video_ids:
            return {}
            
        results = {}
        id_list = list(video_ids)
        chunk_size = 50
        chunks = [id_list[i:i + chunk_size] for i in range(0, len(id_list), chunk_size)]
        
        # 取得範囲を設定（2026年以降のデータを安全に対象とする）
        start_date = "2026-01-01"
        end_date = datetime.date.today().isoformat()
        
        for chunk in chunks:
            ids_str = ",".join(chunk)
            try:
                print(f"[GI_ANALYTICS] Requesting Analytics report for {len(chunk)} videos...")
                request = self.analytics_service.reports().query(
                    ids="channel==MINE",
                    startDate=start_date,
                    endDate=end_date,
                    metrics="impressionClickThroughRate,averageViewPercentage,averageViewDuration,subscribersGained",
                    dimensions="video",
                    filters=f"video=={ids_str}"
                )
                response = request.execute()
                
                headers = [h.get("name") for h in response.get("columnHeaders", [])]
                rows = response.get("rows", [])
                
                for row in rows:
                    row_dict = dict(zip(headers, row))
                    v_id = row_dict.get("video")
                    if v_id:
                        results[v_id] = {
                            "ctr": float(row_dict.get("impressionClickThroughRate", 0.0)),
                            "apv": float(row_dict.get("averageViewPercentage", 0.0)),
                            "avd": float(row_dict.get("averageViewDuration", 0.0)),
                            "subscribers_gained": int(row_dict.get("subscribersGained", 0))
                        }
                print(f"[GI_ANALYTICS] Retrieved metrics for {len(results)} videos.")
            except HttpError as e:
                print(f"[GI_ANALYTICS_ERROR] Analytics query failed (HttpError): {e.resp.status} - {e.content.decode('utf-8')}")
            except Exception as e:
                print(f"[GI_ANALYTICS_ERROR] Analytics query failed: {e}")
                
        return results

    def calculate_cgs(self, metrics, perf_score_v2, hook_score):
        """
        Composite Growth Score v2 (CGS v2) 算出モデル
        Beta: Shorts 向け正規化基準
          CTR  → 12% を 100点（Shorts 平均 CTR は 3-8%）
          APV  → 80% を 100点（Shorts は短尺のため高 APV が期待される）
          SubGain → 1人 = 20点（線形加算、上限 100）
        CGS = (CTR_n * 0.30) + (APV_n * 0.30) + (PerfScore_v2 * 0.25)
              + (SubGain_bonus * 0.10) + (HookScore_corr * 0.05)
        """
        # 1. CTR_normalized (12% = 100点, Shorts 最適化)
        ctr = metrics.get("ctr")
        if ctr is not None:
            ctr_n = min(100.0, (ctr / 12.0) * 100.0)
        else:
            ctr_n = 0.0

        # 2. APV_normalized (80% = 100点, Shorts 最適化)
        apv = metrics.get("apv")
        if apv is not None:
            apv_n = min(100.0, (apv / 80.0) * 100.0)
        else:
            apv_n = 0.0

        # 3. Subscribers Gained Bonus (1人 = 20点, max 100)
        sub_gain = metrics.get("subscribers_gained")
        if sub_gain is not None:
            sub_gain_bonus = min(100.0, sub_gain * 20.0)
        else:
            sub_gain_bonus = 0.0

        # 4. Hook Score Correction (max 100)
        hook_score_corr = hook_score if hook_score is not None else 0.0

        # 既存 PerfScore_v2
        perf_score_v2 = perf_score_v2 if perf_score_v2 is not None else 0.0

        if self.cgs_mode == "beta" and ctr is not None and apv is not None:
            cgs = (ctr_n * 0.30) + (apv_n * 0.30) + (perf_score_v2 * 0.25) + (sub_gain_bonus * 0.10) + (hook_score_corr * 0.05)
        else:
            # Alphaモード: Data API v3 + Hook Score のみ
            cgs = (perf_score_v2 * 0.95) + (hook_score_corr * 0.05)

        return round(cgs, 2)

    def update(self, profile_key=None):
        """
        Growth Intelligence Engine 実行エントリポイント
        """
        print("[GI] Starting Growth Intelligence Layer updates...")
        
        # 1. 認証の初期化
        self.initialize_analytics_service(profile_key)
        
        # 2. データのロード
        cache_data = self.load_script_cache()
        registry_data = self.load_registry()
        
        if not registry_data or "items" not in registry_data or not registry_data["items"]:
            print("[GI] Performance registry is empty. Skipping CGS sync.")
            return False
            
        # script_cache.json の動画アイテムと hook_score をマッピング
        cache_items = {item["video_id"]: item for item in cache_data.get("items", []) if item.get("video_id")}
        
        # 3. Analytics KPI の一括収集 (5E-βの場合のみ)
        video_ids = [x["video_id"] for x in registry_data["items"] if x.get("video_id")]
        analytics_metrics = {}
        if self.cgs_mode == "beta":
            analytics_metrics = self.fetch_analytics_kpis(video_ids)
            
        # 4. CGS の算出とレジストリの更新
        for item in registry_data["items"]:
            v_id = item.get("video_id")
            if not v_id:
                continue
                
            # Analytics メトリクスを取得
            metrics = analytics_metrics.get(v_id, {
                "ctr": item["metrics"].get("ctr"),
                "apv": item["metrics"].get("retention"),
                "avd": item["metrics"].get("avd"),
                "subscribers_gained": item["metrics"].get("subscribers_gained")
            })
            
            # レジストリの metrics を更新
            item["metrics"]["ctr"] = metrics.get("ctr")
            item["metrics"]["retention"] = metrics.get("apv")
            item["metrics"]["apv"] = metrics.get("apv")
            item["metrics"]["avd"] = metrics.get("avd")
            item["metrics"]["subscribers_gained"] = metrics.get("subscribers_gained")
            
            # script_cache.json から hook_score をルックアップ
            cache_item = cache_items.get(v_id, {})
            hook_score = cache_item.get("hook_score")
            
            # CGS 算出
            perf_score_v2 = item.get("performance_score_v2", item.get("performance_score", 0.0))
            cgs = self.calculate_cgs(metrics, perf_score_v2, hook_score)
            
            # レジストリに CGS を保存
            item["cgs_score"] = cgs
            item["performance_score"] = cgs
            
        # 保存
        self.save_registry(registry_data)
        
        # 5. feedback_dataset_v2.json の生成
        self.generate_feedback_dataset_v2(registry_data, cache_data)
        return True

    # ═══════════════════════════════════════════════════════════
    # Phase 5E Beta: Pattern Extraction Engine
    # ═══════════════════════════════════════════════════════════

    def extract_winning_title_patterns(self, top_items, cache_items):
        """
        高 CGS 動画のタイトルから頻出する構造パターンをルールベースで抽出する。
        Phase 7: title_performance_registry.json からも高パフォーマンスタイトルを取り込む。
        AI / 外部 API コストゼロ。hook_scorer.py の TITLE_CURIOSITY_PATTERNS を活用。
        """
        try:
            import sys
            if self.work_dir not in sys.path:
                sys.path.insert(0, self.work_dir)
            from hook_scorer import TITLE_CURIOSITY_PATTERNS, POWER_WORDS
        except ImportError:
            print("[GI_PATTERN_WARN] hook_scorer.py not available. Skipping title pattern extraction.")
            return []

        pattern_hits = Counter()
        pattern_examples = {}

        # Phase 7: title_performance_registry.json から高スコアタイトルも抽出対象に加える
        title_registry_path = os.path.join(self.work_dir, "title_performance_registry.json")
        title_registry_items = []
        if os.path.exists(title_registry_path):
            try:
                with open(title_registry_path, "r", encoding="utf-8") as f:
                    tr_data = json.load(f)
                # performance_score 上位5件を抽出
                tr_items = sorted(tr_data.get("items", []), key=lambda x: x.get("performance_score", 0.0), reverse=True)
                title_registry_items = tr_items[:5]
                print(f"[GI_PATTERN] Loaded {len(title_registry_items)} high-performance titles from title_performance_registry.json")
            except Exception as e:
                print(f"[GI_PATTERN_WARN] Failed to load title_performance_registry.json: {e}")

        # 抽出対象: performance_registry の top_items + title_performance_registry の高スコア
        all_title_sources = list(top_items)
        for tr_item in title_registry_items:
            all_title_sources.append({"title": tr_item.get("title", "")})

        for item in all_title_sources:
            title = item.get("title", "")
            if not title:
                continue
            title_lower = title.lower().strip()

            for pat in TITLE_CURIOSITY_PATTERNS:
                match = re.search(pat, title_lower)
                if match:
                    # パターンをテンプレート化
                    template = self._templatize_title(title, pat)
                    pattern_hits[template] += 1
                    if template not in pattern_examples:
                        pattern_examples[template] = title
                    break  # 1タイトルにつき1パターンのみカウント

        # 出現回数順にソートし上位3件を返す
        results = []
        for template, count in pattern_hits.most_common():
            # 永久防止策: {Topic} を含まないパターンは勝ちパターンから除外する
            if "{Topic}" not in template:
                print(f"[GI_PATTERN_GUARD] Skipping invalid winning title pattern without {{Topic}}: '{template}'")
                continue
            results.append({
                "pattern": template,
                "frequency": count,
                "example": pattern_examples.get(template, ""),
                "source": "title_curiosity_patterns"
            })
            if len(results) >= 3:
                break

        print(f"[GI_PATTERN] Extracted {len(results)} winning title patterns.")
        return results

    def _templatize_title(self, title, matched_pattern):
        """
        タイトルを汎用テンプレートに変換する。
        数字 → {Number}, 固有名詞的な海洋生物名/犬関連名詞 → {Topic}
        """
        template = title
        # 数字をプレースホルダに置換
        template = re.sub(r'\d+', '{Number}', template)
        # 既知の名詞（海洋生物および犬）をトピックプレースホルダに置換
        niche_nouns = [
            # Marine (Aquatic)
            "anglerfish", "coral", "jellyfish", "shark", "whale", "octopus",
            "squid", "dolphin", "turtle", "reef", "sponge", "shrimp",
            "crab", "lobster", "stingray", "seal", "mariana", "trench",
            "abyss", "brine", "hadal",
            # Dog (Canine)
            "dog", "dogs", "puppy", "puppies", "canine", "canines", "chihuahua",
            "poodle", "retriever", "corgi", "pomeranian", "bulldog", "shiba",
            "nose", "noses", "bark", "barks", "barking", "tail", "tails", "wag",
            "wagging", "hearing", "ear", "ears", "gaze", "eye", "eyes", "mouth",
            "lick", "licks", "bow", "bows", "communication", "memory", "dream",
            "dreams", "dreaming", "sleep", "sleeping", "intelligence", "brain"
        ]
        for noun in niche_nouns:
            pattern_noun = re.compile(r'\b' + re.escape(noun) + r'\b', re.IGNORECASE)
            if pattern_noun.search(template):
                template = pattern_noun.sub('{Topic}', template)
                break  # 1つだけ置換
        return template

    def extract_winning_hook_patterns(self, top_items, cache_items):
        """
        高 CGS 動画のスクリプト冒頭からフックタイプを分類・抽出する。
        AI / 外部 API コストゼロ。hook_scorer.py の OPENING_HOOK_PATTERNS を活用。
        """
        try:
            import sys
            if self.work_dir not in sys.path:
                sys.path.insert(0, self.work_dir)
            from hook_scorer import OPENING_HOOK_PATTERNS
        except ImportError:
            print("[GI_PATTERN_WARN] hook_scorer.py not available. Skipping hook pattern extraction.")
            return []

        # フックタイプの分類マップ
        hook_type_map = [
            ("questioning",  [r"(?:did\s+you\s+know|have\s+you\s+(?:ever|heard)|do\s+you\s+know|can\s+you\s+(?:guess|imagine|believe))"]),
            ("disruptive",   [r"(?:this\s+\w+\s+(?:can|could|is|has|was)|there'?s\s+a\s+\w+\s+that)"]),
            ("contrast",     [r"(?:it\s+(?:looks?|seems?|appears?)\s+(?:harmless|normal|ordinary|simple|tiny))",
                              r"(?:they\s+(?:look|seem|appear)\s+(?:harmless|normal|ordinary))"]),
            ("imperative",   [r"(?:look\s+at|watch\s+(?:what|this|how)|listen\s+to|imagine|picture\s+this|meet\s+the)"]),
            ("superlative",  [r"(?:the\s+(?:most|deepest|largest|smallest|oldest|rarest|strangest))"]),
            ("number_lead",  [r"(?:\d+\s+\w+\s+(?:can|could|will|are|have))"]),
        ]

        type_hits = Counter()
        type_examples = {}

        for item in top_items:
            v_id = item.get("video_id")
            cache_item = cache_items.get(v_id, {}) if v_id else {}
            script = cache_item.get("script", "")
            if not script:
                continue
            script_lower = script.lower().strip()

            classified = False
            for hook_type, patterns in hook_type_map:
                for pat in patterns:
                    if re.search(pat, script_lower):
                        type_hits[hook_type] += 1
                        if hook_type not in type_examples:
                            # 冒頭の1文を抽出
                            first_sentence = script.split('.')[0].strip() + '.'
                            type_examples[hook_type] = first_sentence
                        classified = True
                        break
                if classified:
                    break

        results = []
        for hook_type, count in type_hits.most_common(3):
            results.append({
                "hook_type": hook_type,
                "frequency": count,
                "example_opening": type_examples.get(hook_type, ""),
                "source": "opening_hook_patterns"
            })

        print(f"[GI_PATTERN] Extracted {len(results)} winning hook patterns.")
        return results

    # ═══════════════════════════════════════════════════════════
    # Feedback Dataset V2 Generation (Beta Enhanced)
    # ═══════════════════════════════════════════════════════════

    def generate_feedback_dataset_v2(self, registry_data, cache_data=None):
        """
        CGS上位/下位のトピックを含む feedback_dataset_v2.json を出力する。
        Beta: winning_title_patterns / winning_hook_patterns の自動抽出を含む。
        """
        items = registry_data.get("items", [])
        if not items:
            return None

        # CGS スコア順にソート
        sorted_items = sorted(items, key=lambda x: x.get("cgs_score", 0.0), reverse=True)

        top_count = min(5, len(sorted_items))
        top_items = sorted_items[:top_count]

        underperforming_items = []
        if len(sorted_items) > top_count:
            underperforming_count = min(5, len(sorted_items) - top_count)
            underperforming_items = sorted_items[-underperforming_count:]

        # script_cache.json のアイテムマップ (パターン抽出用)
        cache_items = {}
        if cache_data:
            cache_items = {item["video_id"]: item for item in cache_data.get("items", []) if item.get("video_id")}

        # Phase 5E Beta: パターン抽出
        winning_title_patterns = self.extract_winning_title_patterns(top_items, cache_items)
        winning_hook_patterns = self.extract_winning_hook_patterns(top_items, cache_items)

        # Growth trend 判定
        growth_trend = self._calculate_growth_trend(sorted_items)

        feedback_v2 = {
          "feedback_version": 2,
          "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
          "channel": registry_data.get("channel", "ch_aquatic_en"),
          "metadata": {
            "total_videos_analyzed": len(items),
            "analytics_api_available": self.cgs_mode == "beta",
            "cgs_mode": self.cgs_mode,
            "data_freshness_hours": 72,
            "pattern_extraction_enabled": True
          },
          "winning_topics": [
            {
              "topic": x["topic"],
              "category": x.get("category", "default"),
              "cgs": x.get("cgs_score", 0.0),
              "ctr": x["metrics"].get("ctr"),
              "apv": x["metrics"].get("apv"),
              "avd": x["metrics"].get("avd"),
              "views": x["metrics"]["views"]
            } for x in top_items
          ],
          "losing_topics": [
            {
              "topic": x["topic"],
              "category": x.get("category", "default"),
              "cgs": x.get("cgs_score", 0.0),
              "ctr": x["metrics"].get("ctr"),
              "apv": x["metrics"].get("apv"),
              "avd": x["metrics"].get("avd"),
              "views": x["metrics"]["views"]
            } for x in underperforming_items
          ],
          "winning_title_patterns": winning_title_patterns,
          "winning_hook_patterns": winning_hook_patterns,
          "toxic_combinations": [],
          "growth_signals": {
            "total_subscribers_gained": sum(x["metrics"].get("subscribers_gained", 0) for x in items if x["metrics"].get("subscribers_gained") is not None),
            "growth_trend": growth_trend
          },
          "exploration_ratio": {
            "reinforce_pct": 70,
            "explore_pct": 30,
            "adjusted_by": "default"
          }
        }

        # Swipe-Away Proxy (APV < 25%) 検出
        for x in sorted_items:
            apv = x["metrics"].get("apv")
            if apv is not None and apv < 25.0:
                feedback_v2["toxic_combinations"].append({
                    "topic_category": x.get("category", "default"),
                    "hook_type": "low_retention_proxy",
                    "reason": "swipe_away_proxy",
                    "avg_apv_proxy": apv,
                    "blacklisted_at": datetime.datetime.utcnow().isoformat() + "Z"
                })

        try:
            with open(self.feedback_v2_path, "w", encoding="utf-8") as f:
                json.dump(feedback_v2, f, ensure_ascii=False, indent=2)
            print(f"[GI] feedback_dataset_v2.json generated successfully at: {self.feedback_v2_path}")
            return feedback_v2
        except Exception as e:
            print(f"[GI_ERROR] Failed to save feedback_dataset_v2: {e}")
            return None

    def _calculate_growth_trend(self, sorted_items):
        """
        直近の CGS スコアの傾向から成長トレンドを判定する。
        """
        if len(sorted_items) < 3:
            return "insufficient_data"

        # 最新3件と最古3件の CGS 平均を比較
        recent_scores = [x.get("cgs_score", 0.0) for x in sorted_items[:3]]
        oldest_scores = [x.get("cgs_score", 0.0) for x in sorted_items[-3:]]

        recent_avg = sum(recent_scores) / len(recent_scores)
        oldest_avg = sum(oldest_scores) / len(oldest_scores) if oldest_scores else 0.0

        if oldest_avg == 0:
            return "stable"

        change_pct = ((recent_avg - oldest_avg) / oldest_avg) * 100.0

        if change_pct > 15.0:
            return "growing"
        elif change_pct < -15.0:
            return "declining"
        else:
            return "stable"

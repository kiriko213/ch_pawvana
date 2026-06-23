import os
import json
import unittest
import shutil
import datetime

# テスト対象のインポート
from title_intelligence import TitleIntelligenceEngine
from topic_discovery import TopicDiscoveryEngine
from prompt_builder import PromptBuilder
from growth_intelligence import GrowthIntelligenceEngine

class TestPhase7(unittest.TestCase):
    def setUp(self):
        self.test_dir = "test_env_phase7"
        os.makedirs(self.test_dir, exist_ok=True)
        self.feedback_file = "feedback_dataset_v2.json"
        self.cache_file = "script_cache.json"
        self.candidates_file = "title_candidates.json"
        self.title_registry_file = "title_performance_registry.json"
        self.registry_file = "performance_registry.json"

        # 1. feedback_dataset_v2.json のモックデータ作成
        self.feedback_data = {
            "feedback_version": 2,
            "generated_at": "2026-06-09T00:00:00Z",
            "channel": "ch_aquatic_en",
            "winning_title_patterns": [
                {
                    "pattern": "The Truth About {Topic} Lights",
                    "frequency": 2,
                    "example": "The Truth About Anglerfish Lights",
                    "source": "title_curiosity_patterns"
                },
                {
                    "pattern": "{Topic}'s Deepest Secrets",
                    "frequency": 1,
                    "example": "Mariana's Deepest Secrets",
                    "source": "title_curiosity_patterns"
                }
            ],
            "winning_hook_patterns": [
                {
                    "hook_type": "imperative",
                    "frequency": 1,
                    "example_opening": "Look at this bioluminescent lure!",
                    "source": "opening_hook_patterns"
                }
            ],
            "winning_topics": [
                {"topic": "Anglerfish Lure Mystery", "category": "marine_life", "cgs": 90.0, "ctr": 12.0, "apv": 80.0, "views": 100}
            ],
            "losing_topics": [
                {"topic": "Common Sand", "category": "default", "cgs": 30.0, "ctr": 2.0, "apv": 20.0, "views": 10}
            ],
            "exploration_ratio": {
                "reinforce_pct": 70,
                "explore_pct": 30,
                "adjusted_by": "default"
            }
        }
        with open(os.path.join(self.test_dir, self.feedback_file), "w", encoding="utf-8") as f:
            json.dump(self.feedback_data, f, indent=2)

        # 2. script_cache.json のモックデータ作成
        self.cache_data = {
            "items": [
                {
                    "id": "aq_1",
                    "topic": "Anglerfish Lure Mystery",
                    "title": "The Truth About Anglerfish Lights",
                    "script": "Look at this bioluminescent lure! It glows in the dark.",
                    "status": "uploaded",
                    "video_id": "vid_123"
                }
            ]
        }
        with open(os.path.join(self.test_dir, self.cache_file), "w", encoding="utf-8") as f:
            json.dump(self.cache_data, f, indent=2)

        # 3. performance_registry.json のモックデータ作成
        self.registry_data = {
            "items": [
                {
                    "video_id": "vid_123",
                    "topic": "Anglerfish Lure Mystery",
                    "title": "The Truth About Anglerfish Lights",
                    "performance_score_v2": 85.0,
                    "cgs_score": 85.0,
                    "metrics": {
                        "ctr": 11.5,
                        "apv": 78.0,
                        "avd": 12.0,
                        "subscribers_gained": 2,
                        "views": 1000
                    }
                }
            ]
        }
        with open(os.path.join(self.test_dir, self.registry_file), "w", encoding="utf-8") as f:
            json.dump(self.registry_data, f, indent=2)

        self.engine = TitleIntelligenceEngine(
            work_dir=self.test_dir,
            feedback_v2_file=self.feedback_file,
            cache_file=self.cache_file,
            candidates_file=self.candidates_file,
            title_registry_file=self.title_registry_file
        )

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def test_title_scoring(self):
        """タイトルスコアリングの妥当性を検証"""
        winning_patterns = ["The Truth About {Topic}", "{Topic}'s Deepest Secrets"]
        recent_titles = ["Old Ocean Title"]

        # 1. 勝ちパターン一致 (The Truth About Anglerfish) + クエリ語等で高スコア期待
        score_1 = self.engine.score_title("The Truth About Anglerfish", "Anglerfish", winning_patterns, recent_titles)
        
        # 2. 勝ちパターン不一致 + 低好奇心ワード (Common Sand)
        score_2 = self.engine.score_title("Common Sand Title", "Sand", winning_patterns, recent_titles)

        print(f"[TEST_SCORING] Score 1 (Anglerfish): {score_1}, Score 2 (Sand): {score_2}")
        self.assertGreater(score_1, score_2, "Winning pattern title should score higher than generic one.")

    def test_candidates_generation(self):
        """title_candidates.json の自動生成を検証"""
        self.engine.discover_and_score_titles(topic="Jellyfish", original_title="Original Jellyfish Title")
        
        candidates_path = os.path.join(self.test_dir, self.candidates_file)
        self.assertTrue(os.path.exists(candidates_path), "title_candidates.json must be generated.")

        with open(candidates_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["topic"], "Jellyfish")
        self.assertGreaterEqual(len(data["titles"]), 3, "Should have at least 3 candidates.")

    def test_automatic_selection_and_random_exploration(self):
        """自動選定とランダム探索(score_diff < 5)の判定を検証"""
        config_settings = {
            "score_difference_limit": 5.0,
            "boost_keywords": ["deep sea"]
        }
        
        # 1. スコア差が非常に大きいことが明らかなケース
        # winning_pattern と一致するタイトルと、完全に無関係なタイトルを用意
        selected_title = self.engine.select_best_title(
            topic="Anglerfish",
            original_title="The Truth About Anglerfish Lights",
            config_settings=config_settings
        )
        self.assertTrue(len(selected_title) > 0)

        # 2. スコア差がほぼない場合のランダム選定確認
        # 同じ構造のタイトルで片方にだけ微小な差がある、または同一スコアを意図的にモックした selection
        # 実際に engine のメソッドを走らせ、エラーなく動作することを確認
        selected_expl = self.engine.select_best_title(
            topic="Ocean",
            original_title="Ocean Mystery Secrets",
            config_settings=config_settings
        )
        self.assertTrue(len(selected_expl) > 0)

    def test_prompt_builder_integration(self):
        """PromptBuilder が新しい candidates.json と v2 フィードバックを参照することを検証"""
        # トピック候補とタイトル候補を生成しておく
        self.engine.discover_and_score_titles(topic="Anglerfish", original_title="Original Anglerfish")
        
        td = TopicDiscoveryEngine(
            work_dir=self.test_dir,
            feedback_v2_file=self.feedback_file,
            cache_file=self.cache_file,
            candidates_file="topic_candidates.json"
        )
        td.discover_topics()

        pb = PromptBuilder(
            work_dir=self.test_dir,
            feedback_file="feedback_dataset.json",
            cache_file=self.cache_file
        )
        prompt = pb.build_augmented_prompt(base_topic="Anglerfish", language="ja", batch_size=5)
        
        # プロンプト内にインジェクションが起きているか検証
        self.assertIn("The Truth About {Topic} Lights", prompt, "Should contain winning title patterns")
        self.assertIn("Look at this bioluminescent lure!", prompt, "Should contain winning hook patterns")
        self.assertIn("Anglerfish", prompt)

    def test_performance_registry_learning(self):
        """投稿後メトリクスによる title_performance_registry.json の学習更新を検証"""
        perf_score = self.engine.update_performance_registry(
            video_id="new_vid_999",
            title="The Truth About Bioluminescence",
            ctr=12.5,
            apv=85.0,
            sub_gain=3
        )
        
        # 実績スコアの算出式検証: CTR*10 + APV*0.5 + sub_gain*10 = 12.5*10 + 85*0.5 + 3*10 = 125 + 42.5 + 30 = 197.5 -> max(100.0)
        self.assertEqual(perf_score, 100.0, "Expected max score limit of 100.0")

        # レジストリが保存されているか検証
        registry_path = os.path.join(self.test_dir, self.title_registry_file)
        self.assertTrue(os.path.exists(registry_path))

        with open(registry_path, "r", encoding="utf-8") as f:
            registry_data = json.load(f)
        self.assertEqual(len(registry_data["items"]), 1)
        self.assertEqual(registry_data["items"][0]["video_id"], "new_vid_999")
        self.assertEqual(registry_data["items"][0]["performance_score"], 100.0)

    def test_growth_intelligence_registry_extraction(self):
        """GrowthIntelligenceEngine が title_performance_registry から勝ちパターンを併合して抽出できるかを検証"""
        # 事前に学習レジストリを作成しておく
        learning_data = {
            "items": [
                {
                    "video_id": "vid_learning_1",
                    "title": "The Truth About Reef Secrets",
                    "ctr": 15.0,
                    "apv": 90.0,
                    "subscribers_gained": 5,
                    "performance_score": 100.0,
                    "recorded_at": "2026-06-09T00:00:00Z"
                }
            ]
        }
        with open(os.path.join(self.test_dir, self.title_registry_file), "w", encoding="utf-8") as f:
            json.dump(learning_data, f, indent=2)

        gi = GrowthIntelligenceEngine(
            youtube_service=None,
            work_dir=self.test_dir,
            cache_file=self.cache_file,
            registry_file=self.registry_file,
            feedback_v2_file=self.feedback_file
        )
        
        # 抽出メソッドを直接テスト
        # top_items は空配列にするが、学習レジストリ由来のものがマージされるため抽出可能なはず
        patterns = gi.extract_winning_title_patterns(top_items=[], cache_items={})
        self.assertGreater(len(patterns), 0)
        self.assertEqual(patterns[0]["pattern"], "The Truth About {Topic} Secrets")

    def test_fallback_missing_files(self):
        """feedback_dataset_v2.json などのファイル欠損時フォールバック"""
        # ファイルを全削除
        os.remove(os.path.join(self.test_dir, self.feedback_file))
        
        # 例外を起こさずに動作することを確認する（フォールバック）
        selected = self.engine.select_best_title(
            topic="Jellyfish",
            original_title="Original Title Without File"
        )
        self.assertIn("Jellyfish", selected, "Fallback title should contain the topic name.")

if __name__ == "__main__":
    unittest.main()

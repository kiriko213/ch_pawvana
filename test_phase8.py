import os
import json
import shutil
import unittest
import sys
from health_monitor import HealthMonitoringEngine
from pipeline_audit import PipelineAuditEngine

class TestPhase8ProductionReadiness(unittest.TestCase):
    def setUp(self):
        self.test_dir = "test_env_phase8"
        os.makedirs(self.test_dir, exist_ok=True)
        
        # テスト用の config.json 作成
        self.config_data = {
            "02_aquatic_en": {
                "channel_id": "UC_TEST_CHANNEL_123",
                "profile_name": "AquaCurious Test",
                "voice": "en-US-Wavenet-C",
                "tags": "#ocean #fish",
                "topic_discovery": {
                    "reinforce_ratio": 0.5,
                    "explore_ratio": 0.5
                },
                "title_intelligence": {
                    "score_difference_limit": 5.0,
                    "boost_keywords": ["secret", "mystery"]
                }
            }
        }
        with open(os.path.join(self.test_dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump(self.config_data, f)

        # テスト用の performance_registry.json 作成
        self.perf_data = {
            "items": [
                {
                    "video_id": "vid_abc123",
                    "cgs_score": 80.0,
                    "metrics": {
                        "views": 1000,
                        "ctr": 5.5,
                        "apv": 45.0,
                        "subscribers_gained": 10
                    }
                }
            ]
        }
        with open(os.path.join(self.test_dir, "performance_registry.json"), "w", encoding="utf-8") as f:
            json.dump(self.perf_data, f)

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def test_health_monitoring_diagnostics(self):
        """
        HealthMonitoringEngine の診断処理と、health_status.json の出力を検証する。
        """
        engine = HealthMonitoringEngine(work_dir=self.test_dir)
        status = engine.run_diagnostics(config_data=self.config_data["02_aquatic_en"])
        
        self.assertIn("status", status)
        self.assertIn("components", status)
        self.assertTrue(os.path.exists(os.path.join(self.test_dir, "health_status.json")))
        
        with open(os.path.join(self.test_dir, "health_status.json"), "r", encoding="utf-8") as f:
            saved = json.load(f)
        self.assertEqual(saved["status"], status["status"])

    def test_failure_registry_writing(self):
        """
        障害情報の登録 (failure_registry.json) と上限（50件）の挙動を検証する。
        """
        engine = HealthMonitoringEngine(work_dir=self.test_dir)
        
        # 1件登録
        res = engine.register_failure(
            component="Gemini_API", 
            error_type="QUOTA_EXHAUSTED", 
            error_message="Resource has been exhausted.", 
            recovery_action="Wait and retry"
        )
        self.assertTrue(res)
        self.assertTrue(os.path.exists(os.path.join(self.test_dir, "failure_registry.json")))
        
        with open(os.path.join(self.test_dir, "failure_registry.json"), "r", encoding="utf-8") as f:
            registry = json.load(f)
        self.assertEqual(len(registry["failures"]), 1)
        self.assertEqual(registry["failures"][0]["component"], "Gemini_API")
        self.assertEqual(registry["failures"][0]["recovery_action"], "Wait and retry")

        # 55件登録して50件上限のクリップを検証
        for i in range(55):
            engine.register_failure("Test_Comp", "Type", f"Msg {i}")
            
        with open(os.path.join(self.test_dir, "failure_registry.json"), "r", encoding="utf-8") as f:
            registry = json.load(f)
        self.assertEqual(len(registry["failures"]), 50)
        self.assertEqual(registry["failures"][-1]["error_message"], "Msg 54")

    def test_pipeline_audit_run(self):
        """
        PipelineAuditEngine による整合性・パフォーマンス監査と pipeline_audit_report.json の出力を検証する。
        """
        # 意図的に必須ファイルを欠損させた状態から開始
        audit = PipelineAuditEngine(work_dir=self.test_dir)
        report = audit.run_audit()
        
        # 必須ファイル config.json はsetUpで作成したが prompt_builder.py 等はないため FAIL/DEGRADED 検出
        self.assertIn(report["audit_status"], ["FAIL", "DEGRADED"])
        self.assertTrue(os.path.exists(os.path.join(self.test_dir, "pipeline_audit_report.json")))
        
        # 必須ファイルをモック作成して再チェック
        for rf in ["prompt_builder.py", "auto_main.py", "generate_video.py"]:
            with open(os.path.join(self.test_dir, rf), "w") as f:
                f.write("# dummy")
                
        report2 = audit.run_audit()
        self.assertEqual(report2["audit_status"], "PASS")

    def test_kpi_dashboard_generation(self):
        """
        KPI dashboard の集計およびダッシュボード更新処理を検証する。
        """
        engine = HealthMonitoringEngine(work_dir=self.test_dir)
        
        # 擬似エラーを登録して、プロダクション品質メトリクスの計算分母を増やす
        engine.register_failure("YouTube_Upload", "FAIL", "Network timeout", "Retry")
        
        kpi = engine.generate_kpi_dashboard(upload_latency=12.5, generation_latency=45.2)
        
        self.assertIsNotNone(kpi)
        self.assertTrue(os.path.exists(os.path.join(self.test_dir, "kpi_dashboard.json")))
        
        self.assertEqual(kpi["kpis"]["uploads"], 1) # performance_registry から
        self.assertEqual(kpi["kpis"]["views"], 1000)
        self.assertEqual(kpi["production_metrics"]["upload_latency_seconds"], 12.5)
        self.assertEqual(kpi["production_metrics"]["generation_latency_seconds"], 45.2)
        
        # views=1000, failures=1 -> total runs=2 -> success rate = 50%
        self.assertEqual(kpi["production_metrics"]["success_rate_percent"], 50.0)

    def test_safe_startup(self):
        """
        必須ファイル欠落時の安全停止ロジックを検証する。
        """
        # テストフォルダ内のファイル構成を確認
        # 必須ファイル：config.json, prompt_builder.py, auto_main.py
        # モックの run_auto_post 起動時に、sys.exit(0) で安全終了するかどうか
        
        # モック auto_main をロードしてテスト実行
        # ここでは sys.path を調整してロード
        sys.path.insert(0, os.path.abspath("."))
        import auto_main
        
        # 必須ファイルの一部を削除 (prompt_builder.py は test_dir に存在しない)
        if os.path.exists(os.path.join(self.test_dir, "prompt_builder.py")):
            os.remove(os.path.join(self.test_dir, "prompt_builder.py"))
            
        with self.assertRaises(SystemExit) as cm:
            # run_auto_post は asyncio で動くので、イベントループ経由で実行
            import asyncio
            asyncio.run(auto_main.run_auto_post(work_dir=self.test_dir))
            
        self.assertEqual(cm.exception.code, 0) # 安全停止 (sys.exit(0)) を期待

if __name__ == "__main__":
    unittest.main()

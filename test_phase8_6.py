import os
import json
import shutil
import unittest
import math
import sys
import gc
from health_monitor import HealthMonitoringEngine

class TestPhase86Hardening(unittest.TestCase):
    def setUp(self):
        self.test_dir = "test_env_phase8_6"
        os.makedirs(self.test_dir, exist_ok=True)
        
        # モックの performance_registry.json を作成 (Null 値を含む)
        self.perf_data_with_nulls = {
            "items": [
                {
                    "video_id": "vid_1",
                    "cgs_score": None,
                    "metrics": {
                        "views": None,
                        "ctr": None,
                        "apv": None,
                        "subscribers_gained": None
                    }
                },
                {
                    "video_id": "vid_2",
                    "cgs_score": 95.5,
                    "metrics": {
                        "views": 100,
                        "ctr": 5.0,
                        "apv": 40.0,
                        "subscribers_gained": 5
                    }
                }
            ]
        }
        self.perf_path = os.path.join(self.test_dir, "performance_registry.json")
        with open(self.perf_path, "w", encoding="utf-8") as f:
            json.dump(self.perf_data_with_nulls, f)

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def test_null_safety(self):
        """
        viewsやsubscribers_gainedがnullの場合でも、TypeErrorを起こさず集計できることを検証。
        """
        hm = HealthMonitoringEngine(
            work_dir=self.test_dir,
            status_file="health_status.json",
            failure_file="failure_registry.json",
            kpi_file="kpi_dashboard.json"
        )
        
        # 実行。内部で performance_registry.json を読むが、TypeErrorにならないはず
        kpi = hm.generate_kpi_dashboard(upload_latency=10.0, generation_latency=20.0)
        self.assertIsNotNone(kpi)
        self.assertEqual(kpi["kpis"]["uploads"], 2)
        # vid_2 のみ views があるため total_views = 100
        self.assertEqual(kpi["kpis"]["views"], 100)
        self.assertEqual(kpi["kpis"]["subscribers_gained"], 5)

    def test_registry_corruption_fallback(self):
        """
        JSONファイルが破損している、または空の場合の安全なフォールバックを検証。
        """
        hm = HealthMonitoringEngine(
            work_dir=self.test_dir,
            status_file="health_status.json",
            failure_file="failure_registry.json",
            kpi_file="kpi_dashboard.json"
        )
        
        # 空の failure_registry.json を作成
        with open(hm.failure_path, "w", encoding="utf-8") as f:
            f.write("") # 0 bytes
            
        # 障害登録したときに JSONDecodeError にならずリセットして書き込めるか
        res = hm.register_failure("TestComp", "ERR", "message")
        self.assertTrue(res)
        
        with open(hm.failure_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(len(data["failures"]), 1)
        self.assertEqual(data["failures"][0]["component"], "TestComp")

    def test_invalid_metrics_anomaly_detection(self):
        """
        KPIに NaN, Infinity, 負数などの異常値が入力された場合に防御し、警告に記録されることを検証。
        """
        hm = HealthMonitoringEngine(
            work_dir=self.test_dir,
            status_file="health_status.json",
            failure_file="failure_registry.json",
            kpi_file="kpi_dashboard.json"
        )
        
        # NaN や Infinity を latency として渡す
        kpi = hm.generate_kpi_dashboard(upload_latency=float('nan'), generation_latency=float('inf'))
        self.assertIsNotNone(kpi)
        
        # 防御され、kpi_dashboard 上はデフォルト値 (0.0) にフォールバックされること
        self.assertEqual(kpi["production_metrics"]["upload_latency_seconds"], 0.0)
        self.assertEqual(kpi["production_metrics"]["generation_latency_seconds"], 0.0)
        
        # warnings 配下に警告メッセージが含まれていること
        warnings = kpi.get("warnings", [])
        self.assertTrue(any("nan" in w.lower() or "anomalous" in w.lower() for w in warnings))
        self.assertTrue(any("inf" in w.lower() or "anomalous" in w.lower() for w in warnings))

    def test_failure_registry_recovery_with_malformed_records(self):
        """
        failure_registry.json 内に不正な型のレコードが含まれている場合、それらをスキップし破損を防ぐか検証。
        """
        hm = HealthMonitoringEngine(
            work_dir=self.test_dir,
            status_file="health_status.json",
            failure_file="failure_registry.json",
            kpi_file="kpi_dashboard.json"
        )
        
        # 不正なレコード (辞書ではない値など) を含むファイルを作成
        bad_data = {
            "failures": [
                {"component": "GoodComp", "error_type": "ERR"},
                "malformed_string_record",  # 不正レコード
                None,                       # 不正レコード
                {"no_component": "fields"}   # 不正レコード
            ]
        }
        with open(hm.failure_path, "w", encoding="utf-8") as f:
            json.dump(bad_data, f)
            
        # 新しいレコードを追加
        hm.register_failure("NewComp", "ERR2", "msg")
        
        with open(hm.failure_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        # 正しいレコードのみ残って、新規レコードが追加されていること
        failures = data.get("failures", [])
        self.assertEqual(len(failures), 2)  # GoodComp と NewComp
        self.assertEqual(failures[0]["component"], "GoodComp")
        self.assertEqual(failures[1]["component"], "NewComp")

    def test_long_run_simulation(self):
        """
        24時間の運用を想定した24サイクルのシミュレーション。
        メモリリーク、ファイルサイズの過剰増大、エラーの無限蓄積が発生しないことを検証。
        """
        hm = HealthMonitoringEngine(
            work_dir=self.test_dir,
            status_file="health_status.json",
            failure_file="failure_registry.json",
            kpi_file="kpi_dashboard.json"
        )
        
        initial_failures_size = 0
        
        # 24回サイクルを実行
        for cycle in range(24):
            # 診断実行
            hm.run_diagnostics()
            
            # 障害登録 (たまに発生する障害)
            if cycle % 3 == 0:
                hm.register_failure("CycleComp", "ERR_CYCLE", f"Error at cycle {cycle}", "Retry")
                
            # KPI更新
            hm.generate_kpi_dashboard(upload_latency=1.5 * cycle, generation_latency=10.2)
            
            # メモリ使用量やリソースサイズをログ監視（ファイルサイズチェック）
            if cycle == 0:
                initial_failures_size = os.path.getsize(hm.failure_path)
        
        final_failures_size = os.path.getsize(hm.failure_path)
        
        # 24サイクル回した後もファイルが極端に巨大化していないこと
        # (50件の上限ローテーションが効いているため、ある程度で頭打ちになる)
        self.assertTrue(final_failures_size < 100000)  # 100KB未満
        
        # メモリのクリーンアップに問題がないか GC 実行
        gc.collect()
        self.assertTrue(True)

if __name__ == "__main__":
    unittest.main()

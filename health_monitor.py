import os
import json
import math
import datetime
import subprocess

class HealthMonitoringEngine:
    def __init__(self, work_dir=".", status_file="health_status.json", failure_file="failure_registry.json", kpi_file="kpi_dashboard.json"):
        self.work_dir = work_dir
        self.status_path = os.path.join(work_dir, status_file)
        self.failure_path = os.path.join(work_dir, failure_file)
        self.kpi_path = os.path.join(work_dir, kpi_file)

    def run_diagnostics(self, config_data=None, youtube_service=None, analytics_service=None):
        """
        システムの各コンポーネントを監視し、health_status.json に状態を書き込む。
        """
        print("[HEALTH] Running system diagnostics...")
        status = {
            "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
            "status": "healthy",
            "components": {}
        }

        # 1. Gemini API Check
        gemini_status = "unknown"
        try:
            api_key = os.environ.get("GEMINI_API_KEY") or (config_data.get("gemini_api_key") if config_data and isinstance(config_data, dict) else None)
        except Exception:
            api_key = None
        if api_key and api_key != "REDACTED_API_KEY":
            gemini_status = "configured"
        else:
            gemini_status = "missing_key"
            status["status"] = "degraded"
        status["components"]["gemini_api"] = {
            "status": "healthy" if gemini_status == "configured" else "error",
            "details": gemini_status
        }

        # 2. YouTube API & Analytics API Check
        yt_status = "healthy" if youtube_service is not None else "missing"
        ana_status = "healthy" if analytics_service is not None else "missing_or_alpha_fallback"
        if yt_status == "missing":
            status["status"] = "degraded"
        
        status["components"]["youtube_api"] = {
            "status": yt_status,
            "details": "YouTube API Client Initialized" if youtube_service else "Missing client"
        }
        status["components"]["analytics_api"] = {
            "status": "healthy" if analytics_service else "alpha_mode",
            "details": "Analytics API Client Initialized" if analytics_service else "Fallback to Data API (Alpha)"
        }

        # 3. Git Push / Command line availability Check
        git_status = "healthy"
        git_details = "Available"
        try:
            res = subprocess.run(["git", "--version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if res.returncode != 0:
                git_status = "error"
                git_details = "git command failed"
        except Exception as e:
            git_status = "error"
            git_details = str(e)
        
        if git_status == "error":
            status["status"] = "degraded"
        status["components"]["git_push"] = {
            "status": git_status,
            "details": git_details
        }

        # 4. JSON read/write Check
        json_status = "healthy"
        json_details = "Read/Write successful"
        test_path = os.path.join(self.work_dir, "temp_health_test.json")
        try:
            with open(test_path, "w", encoding="utf-8") as f:
                json.dump({"test": "ok"}, f)
            with open(test_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("test") != "ok":
                raise ValueError("Data verification failed")
            os.remove(test_path)
        except Exception as e:
            json_status = "error"
            json_details = str(e)
            status["status"] = "unhealthy"
        status["components"]["json_operations"] = {
            "status": json_status,
            "details": json_details
        }

        # 5. Video generation checks (requirements validation)
        vid_status = "healthy"
        vid_details = "Video generation script health"
        try:
            import generate_video
            vid_details = "generate_video module import OK"
        except Exception as e:
            vid_status = "error"
            vid_details = str(e)
            status["status"] = "degraded"
        status["components"]["video_generation"] = {
            "status": vid_status,
            "details": vid_details
        }

        # 全体ステータスの調整
        error_count = sum(1 for c in status["components"].values() if c["status"] == "error")
        if error_count > 0:
            status["status"] = "unhealthy" if error_count >= 2 else "degraded"

        # 保存
        try:
            with open(self.status_path, "w", encoding="utf-8") as f:
                json.dump(status, f, ensure_ascii=False, indent=2)
            print(f"[HEALTH] Diagnostics finished. Status: {status['status']}")
        except Exception as e:
            print(f"[HEALTH_ERROR] Failed to save health status: {e}")

        # 保存後の整合性検証
        try:
            self._validate_health_status()
        except Exception as ve:
            print(f"[HEALTH_WARN] Health status validation failed: {ve}")

        return status

    def _validate_health_status(self):
        """health_status.json の整合性を検証する。"""
        if not os.path.exists(self.status_path):
            raise FileNotFoundError(f"health_status.json not found at {self.status_path}")
        file_size = os.path.getsize(self.status_path)
        if file_size == 0:
            raise ValueError("health_status.json is empty (0 bytes)")
        with open(self.status_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        required_keys = ["timestamp", "status", "components"]
        for key in required_keys:
            if key not in data:
                raise KeyError(f"Missing required field '{key}' in health_status.json")
        if not isinstance(data["components"], dict):
            raise TypeError("'components' field must be a dict")

    def register_failure(self, component, error_type, error_message, recovery_action=""):
        """
        障害情報を failure_registry.json に登録する。
        """
        print(f"[FAILURE_REGISTRY] Registering failure for {component}: {error_type} - {error_message}")
        registry = {"failures": []}
        if os.path.exists(self.failure_path):
            try:
                with open(self.failure_path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                # 構造検証: failures キーが list であることを確認
                if isinstance(raw, dict) and isinstance(raw.get("failures"), list):
                    # 各レコードの型検証 (不正レコードをスキップ)
                    valid_failures = []
                    for rec in raw["failures"]:
                        if isinstance(rec, dict) and "component" in rec:
                            valid_failures.append(rec)
                        else:
                            print(f"[FAILURE_REGISTRY_WARN] Skipping malformed record: {rec}")
                    registry["failures"] = valid_failures
                else:
                    print("[FAILURE_REGISTRY_WARN] Registry structure invalid. Resetting.")
            except (json.JSONDecodeError, Exception) as e:
                print(f"[FAILURE_REGISTRY_WARN] Failed to load failure registry (resetting): {e}")

        new_failure = {
            "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
            "component": str(component) if component else "unknown",
            "error_type": str(error_type) if error_type else "UNKNOWN",
            "error_message": str(error_message) if error_message else "",
            "recovery_action": str(recovery_action) if recovery_action else ""
        }

        if "failures" not in registry or not isinstance(registry["failures"], list):
            registry["failures"] = []
        registry["failures"].append(new_failure)
        
        # 容量制限（最新50件）
        registry["failures"] = registry["failures"][-50:]

        try:
            with open(self.failure_path, "w", encoding="utf-8") as f:
                json.dump(registry, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"[FAILURE_REGISTRY_ERROR] Failed to save failure registry: {e}")
            return False

    def generate_kpi_dashboard(self, upload_latency=0.0, generation_latency=0.0):
        """
        パフォーマンス統計とプロダクション品質メトリクスを元に kpi_dashboard.json を生成する。
        """
        print("[KPI] Generating KPI Dashboard Data...")
        
        # 1. 基礎データの読み込み
        registry_path = os.path.join(self.work_dir, "performance_registry.json")
        feedback_v2_path = os.path.join(self.work_dir, "feedback_dataset_v2.json")
        failures_path = self.failure_path

        total_uploads = 0
        total_views = 0
        sum_ctr = 0.0
        sum_apv = 0.0
        sum_subscribers = 0
        sum_cgs = 0.0
        counted_metrics = 0

        if os.path.exists(registry_path):
            try:
                with open(registry_path, "r", encoding="utf-8") as f:
                    reg = json.load(f)
                items = reg.get("items", [])
                total_uploads = len(items)
                for item in items:
                    metrics = item.get("metrics") or {}
                    total_views += self._safe_num(metrics.get("views"), 0)
                    sum_subscribers += self._safe_num(metrics.get("subscribers_gained"), 0)
                    
                    cgs = self._safe_num(item.get("cgs_score") or item.get("performance_score"), None)
                    if cgs is not None:
                        sum_cgs += cgs
                    
                    ctr = self._safe_num(metrics.get("ctr"), None)
                    apv = self._safe_num(metrics.get("apv"), None)
                    if ctr is not None and apv is not None:
                        sum_ctr += ctr
                        sum_apv += apv
                        counted_metrics += 1
            except Exception as e:
                print(f"[KPI_WARN] Failed to process performance registry for KPI: {e}")

        avg_ctr = round(sum_ctr / counted_metrics, 2) if counted_metrics > 0 else 0.0
        avg_apv = round(sum_apv / counted_metrics, 2) if counted_metrics > 0 else 0.0
        avg_cgs = round(sum_cgs / total_uploads, 2) if total_uploads > 0 else 0.0

        # feedback_dataset_v2.json からの勝ちトピック・勝ちタイトルパターン
        top_topics = []
        if os.path.exists(feedback_v2_path):
            try:
                with open(feedback_v2_path, "r", encoding="utf-8") as f:
                    feedback = json.load(f)
                top_topics = [t.get("topic") for t in feedback.get("winning_topics", []) if t.get("topic")][:3]
            except Exception as e:
                print(f"[KPI_WARN] Failed to read feedback_dataset_v2 for KPI: {e}")

        # title_performance_registry.json からの上位タイトル
        top_titles = []
        title_reg_path = os.path.join(self.work_dir, "title_performance_registry.json")
        if os.path.exists(title_reg_path):
            try:
                with open(title_reg_path, "r", encoding="utf-8") as f:
                    tr = json.load(f)
                items = sorted(tr.get("items", []), key=lambda x: x.get("performance_score", 0.0), reverse=True)
                top_titles = [i.get("title") for i in items if i.get("title")][:3]
            except Exception as e:
                print(f"[KPI_WARN] Failed to read title registry for KPI: {e}")

        # 2. Production Metrics (成功率・エラー率・リトライ率)
        total_failures = 0
        if os.path.exists(failures_path):
            try:
                with open(failures_path, "r", encoding="utf-8") as f:
                    fail_data = json.load(f)
                total_failures = len(fail_data.get("failures", []))
            except Exception as e:
                print(f"[KPI_WARN] Failed to read failure registry for metrics: {e}")

        total_runs = total_uploads + total_failures
        success_rate = round((total_uploads / total_runs) * 100.0, 2) if total_runs > 0 else 100.0
        failure_rate = round((total_failures / total_runs) * 100.0, 2) if total_runs > 0 else 0.0

        # リトライ率の算出 (failure_registry の error_message 等に "Retry" や "retrying" が含まれるものをリトライ回数と仮定)
        retry_count = 0
        if os.path.exists(failures_path):
            try:
                with open(failures_path, "r", encoding="utf-8") as f:
                    fail_data = json.load(f)
                for fail in fail_data.get("failures", []):
                    if "retry" in fail.get("recovery_action", "").lower() or "retry" in fail.get("error_message", "").lower():
                        retry_count += 1
            except Exception:
                pass
        
        retry_rate = round((retry_count / total_runs) * 100.0, 2) if total_runs > 0 else 0.0

        # 異常値検出・防御
        kpi_warnings = []
        all_kpi_values = {
            "total_views": total_views, "sum_subscribers": sum_subscribers,
            "avg_ctr": avg_ctr, "avg_apv": avg_apv, "avg_cgs": avg_cgs,
            "success_rate": success_rate, "failure_rate": failure_rate, "retry_rate": retry_rate,
            "upload_latency": upload_latency, "generation_latency": generation_latency
        }
        for k, v in all_kpi_values.items():
            if v is None:
                kpi_warnings.append(f"{k} is null")
            elif isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                kpi_warnings.append(f"{k} is {v} (anomalous)")
            elif isinstance(v, (int, float)) and v < 0:
                kpi_warnings.append(f"{k} is negative ({v})")
        if kpi_warnings:
            print(f"[KPI_WARN] Anomalous values detected: {kpi_warnings}")

        kpi_dashboard = {
            "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
            "kpis": {
                "uploads": total_uploads,
                "views": self._safe_num(total_views, 0),
                "ctr_average": self._safe_num(avg_ctr, 0.0),
                "apv_average": self._safe_num(avg_apv, 0.0),
                "subscribers_gained": self._safe_num(sum_subscribers, 0),
                "cgs_average": self._safe_num(avg_cgs, 0.0),
                "top_topics": top_topics,
                "top_titles": top_titles
            },
            "production_metrics": {
                "success_rate_percent": self._safe_num(success_rate, 100.0),
                "failure_rate_percent": self._safe_num(failure_rate, 0.0),
                "retry_rate_percent": self._safe_num(retry_rate, 0.0),
                "upload_latency_seconds": round(self._safe_num(upload_latency, 0.0), 2),
                "generation_latency_seconds": round(self._safe_num(generation_latency, 0.0), 2)
            },
            "warnings": kpi_warnings
        }

        try:
            with open(self.kpi_path, "w", encoding="utf-8") as f:
                json.dump(kpi_dashboard, f, ensure_ascii=False, indent=2)
            print(f"[KPI] Successfully generated KPI Dashboard at {self.kpi_path}")
            return kpi_dashboard
        except Exception as e:
            print(f"[KPI_ERROR] Failed to save KPI dashboard: {e}")
            return None

    @staticmethod
    def _safe_num(value, default):
        """None, NaN, Infinity を安全にデフォルト値へ変換するユーティリティ。"""
        if value is None:
            return default
        if isinstance(value, float):
            if math.isnan(value) or math.isinf(value):
                return default
        if isinstance(value, (int, float)):
            return value
        # 文字列等の非数値型はデフォルトにフォールバック
        try:
            return float(value)
        except (ValueError, TypeError):
            return default

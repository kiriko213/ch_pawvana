import os
import json
import datetime

class PipelineAuditEngine:
    def __init__(self, work_dir=".", report_file="pipeline_audit_report.json"):
        self.work_dir = work_dir
        self.report_path = os.path.join(work_dir, report_file)

    def run_audit(self):
        """
        システムの整合性、リソース更新履歴、パフォーマンス推移を監査する。
        """
        print("[AUDIT] Running Pipeline Audit Engine...")
        report = {
            "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
            "audit_status": "PASS",
            "findings": []
        }

        # 1. 必須ファイルの存在確認 (Deployment Safety の一部)
        required_files = ["config.json", "prompt_builder.py", "auto_main.py", "generate_video.py"]
        missing_required = []
        for rf in required_files:
            if not os.path.exists(os.path.join(self.work_dir, rf)):
                missing_required.append(rf)
        
        if missing_required:
            report["audit_status"] = "FAIL"
            report["findings"].append({
                "category": "infrastructure",
                "severity": "CRITICAL",
                "message": f"Missing required system files: {missing_required}"
            })

        # 2. キャッシュの鮮度 (script_cache.json のpending数と最終更新日付)
        cache_path = os.path.join(self.work_dir, "script_cache.json")
        if os.path.exists(cache_path):
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    cache = json.load(f)
                pending = [i for i in cache.get("items", []) if i.get("status") == "pending"]
                if len(pending) == 0:
                    report["findings"].append({
                        "category": "cache",
                        "severity": "WARNING",
                        "message": "Script cache is empty. Next run will force batch refill."
                    })
            except Exception as e:
                report["audit_status"] = "FAIL"
                report["findings"].append({
                    "category": "cache",
                    "severity": "ERROR",
                    "message": f"Failed to parse script_cache.json: {e}"
                })
        else:
            report["findings"].append({
                "category": "cache",
                "severity": "WARNING",
                "message": "script_cache.json not found. A new one will be initialized."
            })

        # 3. エラー登録簿 (failure_registry.json) のチェックと蓄積頻度の算出
        failure_path = os.path.join(self.work_dir, "failure_registry.json")
        recent_failures_count = 0
        if os.path.exists(failure_path):
            try:
                with open(failure_path, "r", encoding="utf-8") as f:
                    failures = json.load(f)
                recent_failures_count = len(failures.get("failures", []))
                if recent_failures_count > 5:
                    report["findings"].append({
                        "category": "stability",
                        "severity": "WARNING",
                        "message": f"High frequency of recorded failures in failure registry ({recent_failures_count} events)."
                    })
            except Exception as e:
                report["findings"].append({
                    "category": "stability",
                    "severity": "ERROR",
                    "message": f"Failed to read failure registry: {e}"
                })

        # 4. パフォーマンス低下 (CTR < 2.0% や APV < 30% のチェック)
        registry_path = os.path.join(self.work_dir, "performance_registry.json")
        if os.path.exists(registry_path):
            try:
                with open(registry_path, "r", encoding="utf-8") as f:
                    reg = json.load(f)
                items = reg.get("items", [])
                if items:
                    latest = items[-1]
                    metrics = latest.get("metrics", {})
                    ctr = metrics.get("ctr")
                    apv = metrics.get("apv")
                    if ctr is not None and ctr < 2.0:
                        report["findings"].append({
                            "category": "performance",
                            "severity": "WARNING",
                            "message": f"Low CTR observed on latest video: {ctr}%"
                        })
                    if apv is not None and apv < 30.0:
                        report["findings"].append({
                            "category": "performance",
                            "severity": "WARNING",
                            "message": f"Low Average Percentage Viewed (APV) on latest video: {apv}%"
                        })
            except Exception as e:
                report["findings"].append({
                    "category": "performance",
                    "severity": "ERROR",
                    "message": f"Failed to audit performance registry: {e}"
                })

        # 全体ステータスの判定
        critical_findings = [f for f in report["findings"] if f.get("severity") == "CRITICAL"]
        error_findings = [f for f in report["findings"] if f.get("severity") == "ERROR"]
        if critical_findings:
            report["audit_status"] = "FAIL"
        elif error_findings:
            report["audit_status"] = "DEGRADED"

        # レポート保存
        try:
            with open(self.report_path, "w", encoding="utf-8") as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
            print(f"[AUDIT] Audit finished. Status: {report['audit_status']}, Findings: {len(report['findings'])}")
        except Exception as e:
            print(f"[AUDIT_ERROR] Failed to save audit report: {e}")

        return report

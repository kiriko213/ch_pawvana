import os
import json

class PromptBuilder:
    def __init__(self, work_dir=".", feedback_file="feedback_dataset.json", cache_file="script_cache.json"):
        self.work_dir = work_dir
        self.feedback_path = os.path.join(work_dir, "feedback_dataset_v2.json")
        self.legacy_feedback_path = os.path.join(work_dir, feedback_file)
        self.cache_path = os.path.join(work_dir, cache_file)

    def load_feedback_dataset(self):
        """
        feedback_dataset_v2.json を優先的にロードし、存在しない場合は legacy な feedback_dataset.json へフォールバックする。
        """
        if os.path.exists(self.feedback_path):
            try:
                with open(self.feedback_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if data.get("feedback_version") == 2:
                        return {
                            "version": 2,
                            "winning_topics": data.get("winning_topics", []),
                            "losing_topics": data.get("losing_topics", []),
                            "winning_title_patterns": data.get("winning_title_patterns", []),
                            "winning_hook_patterns": data.get("winning_hook_patterns", []),
                            "exploration_ratio": data.get("exploration_ratio", {})
                        }
            except Exception as e:
                print(f"[PROMPT_WARN] Failed to read feedback dataset v2: {e}")

        # Fallback to legacy v1
        if os.path.exists(self.legacy_feedback_path):
            try:
                with open(self.legacy_feedback_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return {
                        "version": 1,
                        "winning_topics": [{"topic": t, "score": 80.0} for t in data.get("winning_topics", [])],
                        "losing_topics": [{"topic": t, "score": 20.0} for t in data.get("losing_topics", [])],
                        "winning_title_patterns": [],
                        "winning_hook_patterns": []
                    }
            except Exception as e:
                print(f"[PROMPT_WARN] Failed to read legacy feedback dataset: {e}")

        return {"version": 0, "winning_topics": [], "losing_topics": [], "winning_title_patterns": [], "winning_hook_patterns": []}

    def load_recent_topics(self, limit=10):
        """
        重複防止のため、script_cache.json から最近生成したトピックを読み込む。
        """
        if os.path.exists(self.cache_path):
            try:
                with open(self.cache_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    items = data.get("items", [])
                    topics = []
                    for item in reversed(items):
                        topic = item.get("topic")
                        if topic and topic not in topics:
                            topics.append(topic)
                        if len(topics) >= limit:
                            break
                    return topics
            except Exception as e:
                print(f"[PROMPT_WARN] Failed to read script cache: {e}")
        return []

    def load_topic_candidates(self):
        """
        topic_candidates.json が存在する場合、上位候補を読み込む。
        """
        candidates_path = os.path.join(self.work_dir, "topic_candidates.json")
        if os.path.exists(candidates_path):
            try:
                with open(candidates_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data.get("top_candidates", [])
            except Exception as e:
                print(f"[PROMPT_WARN] Failed to read topic candidates: {e}")
        return []

    def load_title_candidates(self):
        """
        title_candidates.json が存在する場合、上位タイトル候補を読み込む。
        """
        candidates_path = os.path.join(self.work_dir, "title_candidates.json")
        if os.path.exists(candidates_path):
            try:
                with open(candidates_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data.get("titles", [])
            except Exception as e:
                print(f"[PROMPT_WARN] Failed to read title candidates: {e}")
        return []

    def build_augmented_prompt(self, base_topic, language="en", batch_size=5, reinforce_pct=None, explore_pct=None):
        """動的にパフォーマンスフィードバックと探索比率を注入した拡張メタプロンプトの構成"""
        feedback = self.load_feedback_dataset()
        recent_topics = self.load_recent_topics(limit=10)

        # スコアのキー名が V2 (cgs) と V1 (score) で異なるため対応
        top_list = []
        for t in feedback.get("winning_topics", []):
            score = t.get("cgs") if t.get("cgs") is not None else t.get("score", 0.0)
            top_list.append(f"- {t['topic']} (Category: {t.get('category', 'default')}, Score: {score})")

        under_list = []
        for t in feedback.get("losing_topics", []):
            score = t.get("cgs") if t.get("cgs") is not None else t.get("score", 0.0)
            under_list.append(f"- {t['topic']} (Category: {t.get('category', 'default')}, Score: {score})")

        recent_list = [f"- {t}" for t in recent_topics]

        # パターンデータのフォーマット化
        title_patterns = []
        for p in feedback.get("winning_title_patterns", []):
            title_patterns.append(f"- Structure: '{p['pattern']}' (Example: '{p['example']}')")

        hook_patterns = []
        for h in feedback.get("winning_hook_patterns", []):
            hook_patterns.append(f"- Hook Type: '{h['hook_type']}' (Example: '{h['example_opening']}')")

        # トレンド予測・新規テーマ候補の読み込み
        candidates = self.load_topic_candidates()
        candidates_list = []
        for i, c in enumerate(candidates[:3]):
            candidates_list.append(f"{i+1}. {c['topic']} (Score: {c['score']})")

        # 推奨タイトルの読み込み
        title_candidates = self.load_title_candidates()
        title_candidates_list = []
        for i, tc in enumerate(title_candidates[:3]):
            title_candidates_list.append(f"{i+1}. {tc['title']} (Score: {tc['score']})")

        # 探索比率 (Exploration Ratio) の指示テキスト
        if reinforce_pct is None or explore_pct is None:
            ratio = feedback.get("exploration_ratio", {}) if isinstance(feedback, dict) else {}
            reinforce_pct = ratio.get("reinforce_pct", 70)
            explore_pct = ratio.get("explore_pct", 30)

        reinforce_count = int(batch_size * (reinforce_pct / 100.0) + 0.5) # 四捨五入
        explore_count = batch_size - reinforce_count

        lang_instruction = ""
        if language == "ja":
            lang_instruction = f"""
            YouTubeショート動画用の独立した台本を正確に{batch_size}本、日本語で作成してください。
            出力は必ず以下のスキーマに準拠した有効なJSON配列にしてください。説明文やMarkdownのコードブロックは一切含めないでください。

            【適応型学習パラメータ】
            ■ 過去の高評価・好成績トピック (これらを参考にし、同様のフックや切り口を模倣してください):
            {os.linesep.join(top_list) if top_list else "- なし"}

            ■ 過去の低評価・不評トピック (以下のトピックの構成やテーマは避けてください):
            {os.linesep.join(under_list) if under_list else "- なし"}

            ■ トピック重複防止 (以下の最近使用したトピックとはテーマや対象生物が非常に類似したものは絶対に避けてください):
            {os.linesep.join(recent_list) if recent_list else "- なし"}

            【トレンド予測・新規テーマ候補】
            ■ 以下の予測スコアが高いテーマを、新規テーマ探索（Explore）の台本を作成する際の参考にしてください：
            {os.linesep.join(candidates_list) if candidates_list else "- なし（標準の探索ルールを使用）"}

            【推奨タイトル構造・高CTR候補】
            ■ 以下のスコアが高いタイトル候補や構造を参考にし、同様の構造を取り入れてタイトルを作成してください：
            {os.linesep.join(title_candidates_list) if title_candidates_list else "- なし（標準のタイトルルールを使用）"}

            【探索比率 (Exploration Ratio)】
            1. 生成する{batch_size}本のうち、約{reinforce_pct}% ({reinforce_count}本) は、「過去の高評価トピック」の強みや特徴を継承・再現したトピック（Reinforce）にしてください。
            2. 残りの約{explore_pct}% ({explore_count}本) は、「トレンド予測・新規テーマ候補」や、これまでに試したことのない新しいニッチな領域に関するテーマを探索的（Explore）に作成してください。
            """
        else:
            lang_instruction = f"""
            Generate exactly {batch_size} independent YouTube Shorts narration scripts about '{base_topic}' in English.
            Output MUST be a valid JSON array matching the schema below. No explanation, no markdown backticks, no markdown blocks.

            [Context & Adaptive Learning Parameters]
            Here are high-performing topics that generated strong audience engagement previously. Try to emulate their style, angle, or hooks:
            {os.linesep.join(top_list) if top_list else "- None"}

            Here are underperforming topics. AVOID these exact concepts, styles, or categories:
            {os.linesep.join(under_list) if under_list else "- None"}

            [Topic Diversity Guard (Repetition Protection)]
            Do NOT generate scripts that are highly similar to or duplicate the following recently used topics:
            {os.linesep.join(recent_list) if recent_list else "- None"}

            [Emerging Topic Opportunities (Future Success Candidates)]
            Here are predicted high-potential topics. You can explore these concepts for your exploration (Explore) scripts:
            {os.linesep.join(candidates_list) if candidates_list else "- None (Use standard exploration guidelines)"}

            [Recommended Title Structures (High-CTR Candidates)]
            Here are predicted high-performance title options. Try to use or adapt these styles:
            {os.linesep.join(title_candidates_list) if title_candidates_list else "- None (Use standard title guidelines)"}

            [Exploration Ratio Rules]
            1. Approximately {reinforce_pct}% ({reinforce_count} scripts) MUST be reinforced topics (Reinforce), directly inspired by the successful angles/themes of the high-performing topics above.
            2. The remaining {explore_pct}% ({explore_count} scripts) MUST be exploration topics (Explore), exploring completely new categories, species, or ocean phenomena not listed in the Top Topics, and utilizing the Emerging Topic Opportunities above.
            """

        # CTR・フック最適化指令 (Phase 5C & Phase 5E Pattern Injection)
        if language == "ja":
            hook_rules = f"""
            【タイトル＆フック最適化ルール】
            ■ 過去に効果の高かった動画のタイトルパターン (これらを応用してタイトルを構成してください):
            {os.linesep.join(title_patterns) if title_patterns else "- なし（標準 of CTRパターンを使用）"}

            ■ 過去に効果の高かったフックのパターンと例 (これらを参考に強力なフックを構成してください):
            {os.linesep.join(hook_patterns) if hook_patterns else "- なし（標準 of フックパターンを使用）"}

            ■ タイトルは以下のCTRパターンのいずれかを必ず使用すること：
              - 好奇心ギャップ（「この○○が...」「まさか○○が...」）
              - 数字フック（「○○の3つの秘密」「知らなかった5つの事実」）
              - 挑戦型（「ほとんどの人が知らない...」）
              - 暴露型（「○○の真実」「ついに判明した...」）
              - 最上級（「最も○○な...」「世界一○○な...」）
            ■ ナレーションの最初の5〜7語は、視聴者のスクロールを止める強力なフックで始めること：
              - 質問形（「知っていましたか？」「信じられますか？」）
              - 衝撃の事実（「この生物は○○できる...」）
              - 対比（「無害に見えるが...」）
              - 命令形（「見てください...」「想像してください...」）
            """
        else:
            hook_rules = f"""
            [Title & Hook Optimization Rules]
            ■ Winning Title Structures from previous top-performing videos (Use or adapt these structures if applicable):
            {os.linesep.join(title_patterns) if title_patterns else "- None (Use standard CTR patterns below)"}

            ■ Winning Hook Structures from previous top-performing videos (Use these types/examples as inspiration):
            {os.linesep.join(hook_patterns) if hook_patterns else "- None (Use standard hook patterns below)"}

            1. Each title MUST use one of these high-CTR patterns:
               - Curiosity gap: "This X Can..." / "You Won't Believe..."
               - Number hook: "5 Secrets of..." / "3 Facts About..."
               - Challenge: "Most People Don't Know..." / "Nobody Expected..."
               - Revelation: "The Truth About..." / "Finally Revealed..."
               - Superlative: "The Most..." / "The Deepest..." / "The Rarest..."
            2. Each narration script MUST begin with a strong hook in the first 5-7 words:
               - Question: "Did you know that...?"
               - Shocking fact: "This creature can survive..."
               - Contrast: "It looks harmless, but..."
               - Imperative: "Look at this..." / "Imagine..."
            3. Do NOT use generic or bland titles like "Amazing X!" or "Cool Facts".
            """

        schema_instruction = """
        JSON Schema:
        [
          {
            "topic": "Specific sub-topic name",
            "title": "Video title (under 50 chars, MUST use a CTR pattern from the rules above)",
            "script": "15-second narration (18 to 22 words, MUST start with a strong hook, no emojis, no quotation marks)"
          }
        ]
        """

        full_prompt = lang_instruction.strip() + os.linesep + hook_rules.strip() + os.linesep + schema_instruction.strip()
        return full_prompt

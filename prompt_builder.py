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

    def load_recent_topics(self, limit=50):
        """
        重複防止のため、script_cache.json から最近投稿された（uploaded）トピックを読み込む。
        """
        if os.path.exists(self.cache_path):
            try:
                with open(self.cache_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    items = data.get("items", [])
                    topics = []
                    for item in reversed(items):
                        if item.get("status") == "uploaded":
                            topic = item.get("topic")
                            if topic and topic not in topics:
                                topics.append(topic)
                            if len(topics) >= limit:
                                break
                    return topics
            except Exception as e:
                print(f"[PROMPT_WARN] Failed to read script cache for topics: {e}")
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

    def load_posted_video_titles(self, limit=100):
        """
        script_cache.json から status == 'uploaded' のタイトル一覧を取得する。
        """
        if os.path.exists(self.cache_path):
            try:
                with open(self.cache_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    items = data.get("items", [])
                    titles = []
                    for item in reversed(items):
                        if item.get("status") == "uploaded":
                            title = item.get("title")
                            if title and title not in titles:
                                titles.append(title)
                            if len(titles) >= limit:
                                break
                    return titles
            except Exception as e:
                print(f"[PROMPT_WARN] Failed to read script cache for uploaded titles: {e}")
        return []

    def build_augmented_prompt(self, base_topic, language="en", batch_size=5, reinforce_pct=None, explore_pct=None):
        """動的にパフォーマンスフィードバックと探索比率を注入した拡張メタプロンプトの構成"""
        feedback = self.load_feedback_dataset()
        posted_titles = self.load_posted_video_titles(limit=100)
        posted_topics = self.load_recent_topics(limit=50)

        # スコアのキー名が V2 (cgs) と V1 (score) で異なるため対応
        top_list = []
        for t in feedback.get("winning_topics", []):
            score = t.get("cgs") if t.get("cgs") is not None else t.get("score", 0.0)
            top_list.append(f"- {t['topic']} (Category: {t.get('category', 'default')}, Score: {score})")

        under_list = []
        for t in feedback.get("losing_topics", []):
            score = t.get("cgs") if t.get("cgs") is not None else t.get("score", 0.0)
            under_list.append(f"- {t['topic']} (Category: {t.get('category', 'default')}, Score: {score})")

        posted_titles_list = [f"- {t}" for t in posted_titles]

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

            [POSTED_VIDEO_TITLES]
            {os.linesep.join(posted_titles_list) if posted_titles_list else "- なし"}

            [POSTED_TOPIC_HISTORY]
            {os.linesep.join([f"- {tp}" for tp in posted_topics]) if posted_topics else "- なし"}

            [Hard Anti-Repetition Rule]
            The generated batch MUST avoid all concepts already covered by POSTED_VIDEO_TITLES and POSTED_TOPIC_HISTORY.
            Do not generate:
            * alternative wording of the same concept
            * narrower version of the same concept
            * broader version of the same concept
            * different angle of the same concept
            * different title for the same concept

            Example:
            If POSTED_VIDEO_TITLES or POSTED_TOPIC_HISTORY contains a dog tail communication video,
            you must not generate any topic about:
            tail signals,
            tail wagging,
            tail position,
            body-language interpretation using tails,
            or emotional meaning of tail movement.

            If a generated topic is even remotely related to a concept already present in POSTED_VIDEO_TITLES or POSTED_TOPIC_HISTORY,
            choose a completely different canine concept instead.

            Favor concept diversity over title diversity.

            Rule:
            Never generate a topic, title, angle, hook, or concept that is semantically similar to any title in POSTED_VIDEO_TITLES or any topic in POSTED_TOPIC_HISTORY.

            【トレンド予測・新規テーマ候補】
            ■ 以下の予測スコアが高いテーマを、新規テーマ探索（Explore）の台本を作成する際の参考にしてください：
            {os.linesep.join(candidates_list) if candidates_list else "- なし（標準の探索ルールを使用）"}

            【推奨タイトル構造・高CTR候補】
            ■ 以下のスコアが高いタイトル候補や構造を参考にし、同様の構造を取り入れてタイトルを作成してください：
            {os.linesep.join(title_candidates_list) if title_candidates_list else "- なし（標準のタイトルルールを使用）"}

            【探索比率 (Exploration Ratio)】
            1. 生成する{batch_size}本のうち、約{reinforce_pct}% ({reinforce_count}本) は、「過去の高評価トピック」の強みや特徴を継承・再現したトピック（Reinforce）にしてください。
            2. 残りの約{explore_pct}% ({explore_count}本) は、「トレンド予測・新規テーマ候補」や、これまでに試したことのない新しいニッチな領域に関するテーマを探索的（Explore）に作成してください。

            [Mandatory Topic Category Diversity]
            Within a batch of 5 scripts, every script must belong to a different canine knowledge domain.
            Do NOT generate multiple scripts from the same domain.

            Examples of domains:
            * behavior
            * body language
            * training
            * intelligence
            * health
            * nutrition
            * genetics
            * evolution
            * aging
            * sleep
            * vision
            * hearing
            * smell
            * reproduction
            * history of domestication

            Bad batch example:
            tail communication
            ear language
            eye signals
            stress cues
            play invitation
            (all are body-language related)

            Good batch example:
            dog sleep
            dog vision
            dog nutrition
            dog intelligence
            dog aging
            (all different domains)

            If two topics could reasonably be grouped into the same canine concept category, only one may appear in the batch.
            """
        else:
            lang_instruction = f"""
            Generate exactly {batch_size} independent YouTube Shorts narration scripts about '{base_topic}' in English.
            Output MUST be a valid JSON array matching the schema below. No explanation, no markdown backticks, no markdown blocks.

            [CHANNEL CONTENT POLICY - MANDATORY]
            This channel covers GENERIC DOG CONTENT ONLY. You MUST follow these rules strictly:
            ALLOWED topics: dog_facts, dog_behavior, dog_psychology, dog_training, dog_life_hacks, dog_owner_tips, dog_health_facts, dog_communication, dog_intelligence, amazing_dog_abilities.
            FORBIDDEN topics: breed_specific_content, breed_comparisons, golden_retriever_specific, husky_specific, labrador_specific, puppy_specific_storytelling, individual_dog_profiles.
            GOOD title examples: "Why Dogs Tilt Their Heads", "Why Dogs Sniff Everything", "Dog Body Language Secrets", "Amazing Dog Memory Facts", "Dog Owner Mistakes", "Dog Training Secrets".
            BAD title examples: "Golden Retriever Puppy Facts", "Husky Puppy Secrets", "Labrador Puppy Training", "Story About a Specific Dog".
            For the "search_query" field, use ONLY simple generic queries: "dog", "cute dog", "happy dog", "dog playing", "dog running", "dog owner", "dog training". Do NOT use breed-specific search terms.

            [Context & Adaptive Learning Parameters]
            Here are high-performing topics that generated strong audience engagement previously. Try to emulate their style, angle, or hooks:
            {os.linesep.join(top_list) if top_list else "- None"}

            Here are underperforming topics. AVOID these exact concepts, styles, or categories:
            {os.linesep.join(under_list) if under_list else "- None"}

            [POSTED_VIDEO_TITLES]
            {os.linesep.join(posted_titles_list) if posted_titles_list else "- None"}

            [POSTED_TOPIC_HISTORY]
            {os.linesep.join([f"- {tp}" for tp in posted_topics]) if posted_topics else "- None"}

            [Hard Anti-Repetition Rule]
            The generated batch MUST avoid all concepts already covered by POSTED_VIDEO_TITLES and POSTED_TOPIC_HISTORY.
            Do not generate:
            * alternative wording of the same concept
            * narrower version of the same concept
            * broader version of the same concept
            * different angle of the same concept
            * different title for the same concept

            Example:
            If POSTED_VIDEO_TITLES or POSTED_TOPIC_HISTORY contains a dog tail communication video,
            you must not generate any topic about:
            tail signals,
            tail wagging,
            tail position,
            body-language interpretation using tails,
            or emotional meaning of tail movement.

            If a generated topic is even remotely related to a concept already present in POSTED_VIDEO_TITLES or POSTED_TOPIC_HISTORY,
            choose a completely different canine concept instead.

            Favor concept diversity over title diversity.

            Rule:
            Never generate a topic, title, angle, hook, or concept that is semantically similar to any title in POSTED_VIDEO_TITLES or any topic in POSTED_TOPIC_HISTORY.

            [Emerging Topic Opportunities (Future Success Candidates)]
            Here are predicted high-potential topics. You can explore these concepts for your exploration (Explore) scripts:
            {os.linesep.join(candidates_list) if candidates_list else "- None (Use standard exploration guidelines)"}

            [Recommended Title Structures (High-CTR Candidates)]
            Here are predicted high-performance title options. Try to use or adapt these styles:
            {os.linesep.join(title_candidates_list) if title_candidates_list else "- None (Use standard title guidelines)"}

            [Exploration Ratio Rules]
            1. Approximately {reinforce_pct}% ({reinforce_count} scripts) MUST be reinforced topics (Reinforce), directly inspired by the successful angles/themes of the high-performing topics above.
            2. The remaining {explore_pct}% ({explore_count} scripts) MUST be exploration topics (Explore), exploring completely new categories or dog phenomena not listed in the Top Topics, and utilizing the Emerging Topic Opportunities above.

            [Mandatory Topic Category Diversity]
            Within a batch of 5 scripts, every script must belong to a different canine knowledge domain.
            Do NOT generate multiple scripts from the same domain.

            Examples of domains:
            * behavior
            * body language
            * training
            * intelligence
            * health
            * nutrition
            * genetics
            * evolution
            * aging
            * sleep
            * vision
            * hearing
            * smell
            * reproduction
            * history of domestication

            Bad batch example:
            tail communication
            ear language
            eye signals
            stress cues
            play invitation
            (all are body-language related)

            Good batch example:
            dog sleep
            dog vision
            dog nutrition
            dog intelligence
            dog aging
            (all different domains)

            If two topics could reasonably be grouped into the same canine concept category, only one may appear in the batch.

            [BATCH CONCEPT DIVERSITY — MANDATORY]
            THIS IS THE MOST IMPORTANT RULE. VIOLATION WILL CAUSE THE ENTIRE BATCH TO BE REJECTED.
            Every single script in this batch MUST cover a COMPLETELY DIFFERENT core concept. No overlap is allowed.
            Strict rules:
            1. Every script MUST belong to a DIFFERENT category (e.g., one about senses, one about behavior, one about cognition, one about health, one about training).
            2. No two scripts may discuss the SAME dog behavior (e.g., if one is about tail wagging, NO other script may mention tails, wagging, or body language).
            3. No two scripts may discuss the SAME psychological trait (e.g., if one is about memory, NO other script may mention memory, recall, remembering, or episodic memory).
            4. No two scripts may discuss the SAME sensory topic (e.g., if one is about smell, NO other script may mention nose, scent, or sniffing).
            5. No two scripts may discuss the SAME core concept even if worded differently.
            6. Concept family exclusions — if one script covers ANY keyword in a family, NO other script may touch the same family:
               - MEMORY: memory, episodic memory, remember, recall, recognition
               - TAIL: tail, wag, wagging, body language, tail position
               - BARK: bark, barking, vocalization, vocal communication, howl
               - SLEEP: sleep, dreaming, dream, REM, nap
               - SMELL: smell, nose, scent, sniff, olfactory
               - HEARING: hearing, ears, sound, ultrasonic
               - EMOTION: emotion, empathy, love, attachment, bonding
               - INTELLIGENCE: intelligence, IQ, problem solving, cognition
               - TRAINING: training, obedience, commands, tricks
               - HEALTH: health, diet, nutrition, exercise, lifespan
            7. If you are unsure whether two topics overlap, treat them as the SAME concept and pick a different one.
            8. Maximize diversity: aim for the widest possible spread across unrelated dog science areas.
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

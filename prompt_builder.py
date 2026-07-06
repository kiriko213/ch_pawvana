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

            [PAWVANA BRAND DNA — 絶対ルール]
            このチャンネルは「Pawvana」です。教育チャンネルやトリビアチャンネルではありません。
            ブランドDNA: "Fast. Funny. No fluff."（速く、面白く、無駄がない）
            唯一の目的は「視聴者のスクロールを止めること」です。知識は武器であり、エンタメこそが使命です。
            トーン: パンチが効いていて、ウィットに富み、少しカオスであること。退屈で講義のような説明は厳禁です。
            視聴者が最初の2秒で「えっ…何だって？」と思い、最後には「それは知らなかった！」と思うようにしてください。

            [チャンネルコンテンツポリシー — 犬と猫]
            このチャンネルは犬と猫の両方の驚くべき、あるいは風変わりなトピックをカバーします。
            バッチ内には必ず犬と猫の両方のトピックを含めてください（すべて犬、あるいはすべて猫にするのは禁止）。
            タイトルはスクロールを止める力があること。「猫は実は液体！」や「犬はタイムトラベラー！」のような比喩、驚きの能力を表現したタイトルにしてください。
            search_queryフィールドには、対象の動物に合ったシンプルなクエリ（"cat", "cute cat", "dog", "cute dog"など）を設定してください。

            [必須台本構成 — 4部構成フォーマット]
            すべてのスクリプトは必ず以下の構成に従ってください。
            1. 質問 (1-3秒): スクロールを止める短い質問または発言。前置きは一切不要。
            2. 意外な真実 (3-7秒): 直感的ではない、あるいは衝撃的な事実を提示。
            3. 簡単な説明 (7-12秒): その理由を鮮やかな比喩などを使って1〜2文で短く説明。
            4. 結び (12-15秒): 視聴者が「知らなかった」と思うような、あるいは再視聴したくなるようなオチや結び。

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
            生成されるバッチは、POSTED_VIDEO_TITLESおよびPOSTED_TOPIC_HISTORYでカバーされている概念を絶対に避けてください。
            同一コンセプトの言い換えや、異なる角度からのタイトル付けも重複とみなします。少しでも関連している場合は、全く異なる動物のコンセプトを選択してください。タイトルの多様性よりも、コンセプト（概念）の多様性を最優先してください。

            【トレンド予測・新規テーマ候補】
            ■ 以下の予測スコアが高いテーマを、新規テーマ探索（Explore）の台本を作成する際の参考にしてください：
            {os.linesep.join(candidates_list) if candidates_list else "- なし（標準の探索ルールを使用）"}

            【推奨タイトル構造・高CTR候補】
            ■ 以下のスコアが高いタイトル候補や構造を参考にし、同様の構造を取り入れてタイトルを作成してください：
            {os.linesep.join(title_candidates_list) if title_candidates_list else "- なし（標準のタイトルルールを使用）"}

            【探索比率 (Exploration Ratio)】
            1. 生成する{batch_size}本のうち、約{reinforce_pct}% ({reinforce_count}本) は、「過去の高評価トピック」の強みや特徴を継承・再現したトピック（Reinforce）にしてください。
            2. 残りの約{explore_pct}% ({explore_count}本) は、「トレンド予測・新規テーマ候補」や、新しいニッチな領域に関するテーマを探索的（Explore）に作成してください。

            [Mandatory Topic Category Diversity]
            バッチ内の5本のスクリプトは、それぞれ全く異なる動物ドメイン（分野）に属している必要があります。
            同じ分野から複数のスクリプトを生成しないでください。
            ドメインの例：
            * 猫の液状化物理 (cat liquid physics)
            * 犬の時間知覚 (dog time perception)
            * 猫のゴロゴロ音の治癒効果 (cat purr healing)
            * 犬のクシャミの秘密の言葉 (dog sneeze communication)
            * 猫のフェロモン検知 (cat pheromone detection)
            * 犬の感情的な記憶 (dog emotional memory)
            * 猫の夜間視力 (cat night vision)
            * 犬の嗅覚インテリジェンス (dog scent intelligence)
            * 猫の重力無視 (cat gravity defiance)
            * 犬の夢の行動 (dog dream behavior)

            バッチ内に同じコンセプトカテゴリーに分類できるトピックが2つ以上存在することは許されません。
            """
        else:
            lang_instruction = f"""
            Generate exactly {batch_size} independent YouTube Shorts narration scripts about '{base_topic}' in English.
            Output MUST be a valid JSON array matching the schema below. No explanation, no markdown backticks, no markdown blocks.

            [PAWVANA BRAND DNA — ABSOLUTE RULES]
            This channel is called "Pawvana". It is NOT an educational channel. It is NOT a trivia channel.
            Brand identity: "Fast. Funny. No fluff."
            The ONLY purpose of every video is to STOP THE SCROLL. Knowledge is just the weapon — entertainment is the mission.
            Tone: punchy, witty, slightly chaotic. Never dry. Never boring. Never lecture-like.
            If a script sounds like it belongs in a classroom, it has FAILED.
            If a script sounds like a generic "fun facts" compilation, it has FAILED.
            The viewer must think: "Wait... what?" within the first 2 seconds.
            The viewer must think: "I didn't know that." by the end.

            [CHANNEL CONTENT POLICY — DOGS & CATS]
            This channel covers surprising, bizarre, and little-known facts about BOTH dogs AND cats.
            ALLOWED topics: dog behavior mysteries, cat bizarre habits, dog hidden abilities, cat secret senses, dog psychology, cat physics-defying traits, pet survival instincts, animal communication secrets.
            FORBIDDEN topics: breed-specific content, breed comparisons, individual pet profiles, puppy/kitten storytelling, generic "cute" compilations, educational lectures.
            GOOD title examples: "Your Cat is Actually a Liquid!", "Your Dog is a Time Traveler!", "The Secret Language of Dog Sneezes!", "Cat's Secret Pheromone Detector", "What Is This Alien Object?"
            BAD title examples: "Amazing Dog Facts!", "Cute Cat Compilation", "Golden Retriever Training Tips", "5 Things About Cats".
            For the "search_query" field, use simple queries matching the animal: "cat", "cute cat", "funny cat", "cat playing", "dog", "cute dog", "funny dog", "dog playing". Do NOT use breed-specific search terms.

            [MANDATORY SCRIPT STRUCTURE — 4-PART FORMAT]
            Every script MUST follow this exact structure. No exceptions.
            1. QUESTION (first 1-3 seconds): Open with a short, punchy question or statement that makes the viewer stop scrolling and think "Wait... what?". No preamble. No setup. Hit them immediately.
            2. UNEXPECTED TRUTH (3-7 seconds): Deliver the surprising, counterintuitive, or bizarre fact. This must feel like a revelation, not a textbook definition.
            3. TINY EXPLANATION (7-12 seconds): One or two short sentences that explain WHY, using a fun or vivid analogy. Keep it snappy. No lecturing.
            4. END (12-15 seconds): A short closer that leaves the viewer thinking "I didn't know that" or makes them want to rewatch. Can be a punchline, a mind-blow, or a callback to the opening question.

            [WRITING STYLE — MANDATORY]
            - Short sentences. Punchy delivery. No filler words.
            - No preamble. No "Hey guys" or "In today's video". Start with the hook IMMEDIATELY.
            - Write like you're texting a friend something insane you just learned, not reading from an encyclopedia.
            - Every sentence must earn its place. If removing a sentence doesn't hurt the script, that sentence shouldn't exist.
            - Use vivid, concrete language. "Your cat's purr vibrates at the same frequency used to heal broken bones" is better than "Cats have interesting purring abilities".

            [Context & Adaptive Learning Parameters]
            Here are high-performing topics that generated strong audience engagement previously. Emulate their style, angle, and hooks:
            {os.linesep.join(top_list) if top_list else "- None"}

            Here are underperforming topics. AVOID these exact concepts, styles, or categories:
            {os.linesep.join(under_list) if under_list else "- None"}

            [POSTED_VIDEO_TITLES]
            {os.linesep.join(posted_titles_list) if posted_titles_list else "- None"}

            [POSTED_TOPIC_HISTORY]
            {os.linesep.join([f"- {{tp}}" for tp in posted_topics]) if posted_topics else "- None"}

            [Hard Anti-Repetition Rule]
            The generated batch MUST avoid all concepts already covered by POSTED_VIDEO_TITLES and POSTED_TOPIC_HISTORY.
            Do not generate:
            * alternative wording of the same concept
            * narrower or broader version of the same concept
            * different angle of the same concept
            * different title for the same concept

            If a generated topic is even remotely related to a concept already present in POSTED_VIDEO_TITLES or POSTED_TOPIC_HISTORY,
            choose a completely different animal concept instead.

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
            2. The remaining {explore_pct}% ({explore_count} scripts) MUST be exploration topics (Explore), exploring completely new categories or animal phenomena not listed in the Top Topics, and utilizing the Emerging Topic Opportunities above.

            [Mandatory Topic Category Diversity]
            Within a batch of {batch_size} scripts, every script must belong to a different animal knowledge domain.
            Do NOT generate multiple scripts from the same domain.
            The batch MUST include BOTH dog and cat topics (not all-dog or all-cat).

            Examples of domains:
            * cat liquid physics
            * dog time perception
            * cat purr healing
            * dog sneeze communication
            * cat pheromone detection
            * dog emotional memory
            * cat night vision
            * dog scent intelligence
            * cat gravity defiance
            * dog dream behavior

            Bad batch example:
            dog tail communication
            dog ear language
            dog eye signals
            dog stress cues
            dog play invitation
            (all dog, all body-language related)

            Good batch example:
            cat liquid body physics
            dog time perception
            cat purr healing frequency
            dog sneeze secret language
            cat pheromone radar
            (mixed dog/cat, all completely different domains)

            If two topics could reasonably be grouped into the same concept category, only one may appear in the batch.

            [BATCH CONCEPT DIVERSITY — MANDATORY]
            THIS IS THE MOST IMPORTANT RULE. VIOLATION WILL CAUSE THE ENTIRE BATCH TO BE REJECTED.
            Every single script in this batch MUST cover a COMPLETELY DIFFERENT core concept. No overlap is allowed.
            Strict rules:
            1. Every script MUST belong to a DIFFERENT category (e.g., one about senses, one about behavior, one about cognition, one about health, one about physics).
            2. No two scripts may discuss the SAME animal behavior, psychological trait, or sensory topic.
            3. No two scripts may discuss the SAME core concept even if worded differently.
            4. Concept family exclusions — if one script covers ANY keyword in a family, NO other script may touch the same family:
               - PURR: purr, purring, vibration, healing frequency
               - LIQUID: liquid, flexible, squeeze, contortion, fit
               - MEMORY: memory, episodic memory, remember, recall, recognition
               - TAIL: tail, wag, wagging, tail position
               - BARK: bark, barking, vocalization, howl
               - SLEEP: sleep, dreaming, dream, REM, nap
               - SMELL: smell, nose, scent, sniff, olfactory
               - HEARING: hearing, ears, sound, ultrasonic
               - EMOTION: emotion, empathy, love, attachment, bonding
               - VISION: vision, eyes, night vision, pupils, sight
            5. If you are unsure whether two topics overlap, treat them as the SAME concept and pick a different one.
            6. Maximize diversity: aim for the widest possible spread across unrelated animal science areas.
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
            [Title & Hook Optimization Rules — Pawvana Brand]
            ■ Winning Title Structures from previous top-performing videos (Use or adapt these structures if applicable):
            {os.linesep.join(title_patterns) if title_patterns else "- None (Use Pawvana brand patterns below)"}

            ■ Winning Hook Structures from previous top-performing videos (Use these types/examples as inspiration):
            {os.linesep.join(hook_patterns) if hook_patterns else "- None (Use Pawvana brand hooks below)"}

            [TITLE RULES — "Wait...what?" Effect]
            Every title MUST make the viewer stop and double-take. The title alone must create cognitive dissonance.
            Use these Pawvana-proven patterns:
               - Absurd metaphor: "Your Cat is Actually a Liquid!" / "Your Dog is a Time Traveler!"
               - Hidden ability: "Cat's Secret Pheromone Detector" / "The Secret Language of Dog Sneezes!"
               - Alien framing: "What Is This Alien Object?" / "Unlocking the Healing Frequencies of Cat Purrs"
            BANNED title patterns (too generic, no scroll-stop power):
               - "Amazing X!" / "Cool Facts" / "5 Things About..." / "Did You Know?"
               - Any title that could belong to ANY other pet channel is a failure.

            [HOOK RULES — First 2 Seconds]
            The narration MUST open with a question or statement so bizarre that the viewer cannot scroll past.
            The first sentence must be under 10 words. No warm-up. No greeting. No preamble.
            Good hooks (Pawvana style):
               - "Your cat is actually a liquid."
               - "Dogs can smell time."
               - "This sound can heal broken bones."
            Bad hooks (generic, weak):
               - "Did you know that dogs are amazing?"
               - "Here's an interesting fact about cats."
               - "Today we'll learn about..."
            """

        schema_instruction = """
        JSON Schema:
        [
          {
            "topic": "Specific sub-topic name",
            "title": "Video title (under 50 chars, MUST trigger 'Wait...what?' reaction, use Pawvana brand patterns)",
            "script": "15-second narration script (35 to 45 words). MUST follow the 4-part structure: Question (1-3s) → Unexpected Truth (3-7s) → Tiny Explanation (7-12s) → End (12-15s). Short punchy sentences only. No emojis. No quotation marks. No preamble."
          }
        ]
        """

        full_prompt = lang_instruction.strip() + os.linesep + hook_rules.strip() + os.linesep + schema_instruction.strip()
        return full_prompt

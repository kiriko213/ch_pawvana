"""
Phase 5C: Hook Scorer & Curiosity Pattern Library
ローカル処理のみで、生成されたタイトルとスクリプト冒頭のフック品質を定量評価する。
外部 API 呼び出しは一切行わない。
"""
import re

# ═══════════════════════════════════════════════════════════
# Curiosity Pattern Library (静的パターン辞書)
# ═══════════════════════════════════════════════════════════

# CTR向上に寄与するタイトルパターン (正規表現)
TITLE_CURIOSITY_PATTERNS = [
    # Curiosity Gap
    r"(?:this|these)\s+\w+\s+(?:can|could|will|actually)",
    r"you\s+won'?t\s+believe",
    r"what\s+happens\s+(?:when|if|next)",
    r"(?:here'?s|here\s+is)\s+(?:why|how|what)",
    r"the\s+reason\s+(?:why|behind)",
    # Number Hook
    r"\d+\s+(?:secrets?|facts?|reasons?|ways?|things?|signs?)",
    # Challenge / Knowledge Gap
    r"most\s+people\s+(?:don'?t|never|can'?t)",
    r"(?:nobody|no\s+one)\s+(?:knows?|told|expected)",
    r"scientists?\s+(?:can'?t|couldn'?t|don'?t)\s+explain",
    r"can\s+you\s+(?:guess|spot|believe|imagine)",
    # Revelation
    r"(?:the\s+)?truth\s+about",
    r"finally\s+(?:revealed|explained|solved|discovered)",
    r"(?:secret|hidden|mystery|mysterious)\s+(?:of|behind|about)",
    r"(?:discovered|found|caught)\s+(?:in|on|at)",
    # Superlative
    r"(?:most|least|biggest|smallest|deepest|rarest|strangest|deadliest|fastest|oldest)",
]

# パワーワード (タイトル内の存在でスコア加算)
POWER_WORDS = [
    "secret", "hidden", "mystery", "shocking", "incredible", "unbelievable",
    "terrifying", "deadly", "rare", "ancient", "impossible", "bizarre",
    "stunning", "revealed", "discovered", "unknown", "forbidden", "extinct",
    "survive", "dangerous", "powerful", "ultimate", "insane", "mind-blowing",
]

# スクリプト冒頭のフックパターン (正規表現)
OPENING_HOOK_PATTERNS = [
    # Direct Question
    r"^(?:did\s+you\s+know|have\s+you\s+(?:ever|heard)|do\s+you\s+know|can\s+you\s+(?:guess|imagine|believe))",
    # Shocking Fact
    r"^(?:this\s+\w+\s+(?:can|could|is|has|was)|there'?s\s+a\s+\w+\s+that)",
    # Contrast
    r"^(?:it\s+(?:looks?|seems?|appears?)\s+(?:harmless|normal|ordinary|simple|tiny))",
    r"^(?:they\s+(?:look|seem|appear)\s+(?:harmless|normal|ordinary))",
    # Imperative
    r"^(?:look\s+at|watch\s+(?:what|this|how)|listen\s+to|imagine|picture\s+this|meet\s+the)",
    # Superlative Opening
    r"^(?:the\s+(?:most|deepest|largest|smallest|oldest|rarest|strangest))",
    # Number Opening
    r"^(?:\d+\s+\w+\s+(?:can|could|will|are|have))",
]

# フック語 (冒頭7語以内に存在すればスコア加算)
HOOK_WORDS = [
    "secret", "hidden", "mystery", "shocking", "incredible", "deadly",
    "rare", "ancient", "survive", "dangerous", "bizarre", "discovered",
    "impossible", "terrifying", "unknown", "deep", "darkness",
]


# ═══════════════════════════════════════════════════════════
# Scoring Functions
# ═══════════════════════════════════════════════════════════

def score_title(title: str) -> int:
    """
    タイトルの CTR スコアを算出 (0-100)
    - Curiosity Pattern 一致: +40
    - 50文字以内: +20
    - Power Word を含む: +20
    - 数字を含む: +10
    - 疑問符を含む: +10
    """
    if not title:
        return 0

    score = 0
    title_lower = title.lower().strip()

    # 1. Curiosity Pattern 一致 (+40)
    for pattern in TITLE_CURIOSITY_PATTERNS:
        if re.search(pattern, title_lower):
            score += 40
            break  # 複数パターンに一致しても40点まで

    # 2. 50文字以内 (+20)
    if len(title) <= 50:
        score += 20

    # 3. Power Word を含む (+20, 最大1回)
    for pw in POWER_WORDS:
        if pw in title_lower:
            score += 20
            break

    # 4. 数字を含む (+10)
    if re.search(r"\d", title):
        score += 10

    # 5. 疑問符を含む (+10)
    if "?" in title:
        score += 10

    return min(100, score)


def score_opening(script: str) -> int:
    """
    スクリプト冒頭のフック強度スコアを算出 (0-100)
    - Hook Pattern 一致: +30
    - Shocking/Contrast パターン一致: +30 (Hook Patternと重複可)
    - 冒頭7語以内にフック語: +20
    - 感嘆符を含む: +10
    - 命令形で始まる: +10
    """
    if not script:
        return 0

    score = 0
    script_lower = script.lower().strip()
    first_words = " ".join(script_lower.split()[:7])

    # 1. Opening Hook Pattern 一致 (+30)
    pattern_matched = False
    for pattern in OPENING_HOOK_PATTERNS:
        if re.search(pattern, script_lower):
            score += 30
            pattern_matched = True
            break

    # 2. Shocking/Contrast 追加ボーナス (+30)
    # パターンマッチとは別に、冒頭の情報密度を評価
    shocking_patterns = [
        r"(?:can\s+survive|can\s+kill|produces?\s+(?:light|venom|electricity))",
        r"(?:looks?\s+(?:harmless|normal|ordinary),?\s+but)",
        r"(?:no\s+one|nobody|scientists?)\s+(?:knows?|understands?|expected)",
    ]
    for sp in shocking_patterns:
        if re.search(sp, script_lower):
            score += 30
            break

    # 3. 冒頭7語以内にフック語 (+20)
    for hw in HOOK_WORDS:
        if hw in first_words:
            score += 20
            break

    # 4. 感嘆符を含む (+10)
    if "!" in script:
        score += 10

    # 5. 命令形で始まる (+10)
    imperative_starters = ["look", "watch", "listen", "imagine", "picture", "meet", "discover", "explore"]
    first_word = script_lower.split()[0] if script_lower.split() else ""
    if first_word in imperative_starters:
        score += 10

    return min(100, score)


def score_item(item: dict) -> dict:
    """
    キャッシュアイテムに対して hook_score を算出して付与する。
    返り値: hook_score の内訳辞書
    HookScore = (TitleScore * 0.5) + (OpeningScore * 0.5)
    """
    title = item.get("title", "")
    script = item.get("script", "")

    title_score = score_title(title)
    opening_score = score_opening(script)
    
    combined = round((title_score * 0.5) + (opening_score * 0.5), 1)

    result = {
        "hook_score": combined,
        "hook_title_score": title_score,
        "hook_opening_score": opening_score,
    }

    # アイテムに直接付与
    item["hook_score"] = combined
    item["hook_title_score"] = title_score
    item["hook_opening_score"] = opening_score

    return result

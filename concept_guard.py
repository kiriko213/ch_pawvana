import re
import json
import os

CONCEPT_CLUSTERS = {
    "TAIL": ["tail", "tails", "wag", "wagging", "wagged", "tail movement", "tail motion", "tail position", "tail speed"],
    "BARK": ["bark", "barks", "barking", "vocalization", "vocalizations", "howl", "howling", "growl", "growling", "whine", "whining", "vocal communication", "vocal cue", "vocal cues"],
    "SMELL": ["smell", "smells", "smelling", "sniff", "sniffs", "sniffing", "scent", "scents", "nose", "noses", "olfactory"],
    "EARS": ["ear", "ears", "hearing", "sound", "sounds", "acoustic", "listen", "listening"],
    "SLEEP": ["sleep", "sleeping", "sleeps", "dream", "dreams", "dreaming", "rem", "nap", "naps"],
    "MEMORY": ["memory", "memories", "remember", "remembers", "remembering", "recall", "recalls", "recalling", "cognition", "cognitive", "brain", "brains", "intelligence"],
    "EYES": ["eye", "eyes", "gaze", "gazes", "gazing", "stare", "stares", "staring", "vision", "look", "looks", "looking", "eye contact"],
    "EMOTION": ["emotion", "emotions", "empathy", "love", "loves", "loving", "bond", "bonds", "bonding", "grief", "grieving", "sad", "sadness", "happy", "happiness", "feel", "feeling", "feelings", "jealous", "jealousy"],
    "TRAINING": ["train", "training", "command", "commands", "obedience", "reward", "rewards", "reinforcement", "trick", "tricks"],
    "LICK": ["lick", "licks", "licking", "mouth", "mouths", "lip", "lips"],
    "BODY_LANGUAGE": ["body language", "posture", "postures", "gesture", "gestures", "non-verbal", "nonverbal", "signal", "signals", "cue", "cues"]
}

def extract_concepts(text):
    """
    テキストからコンセプトクラスターのセットを抽出する。
    単一単語キーワードはワードリストで高速一致、
    複数単語キーワードはフルテキストの部分文字列照合で検出する。
    """
    if not text:
        return set()
    text_lower = text.lower()
    words = set(re.findall(r'\b\w+\b', text_lower))
    
    concepts = set()
    for cluster_name, keywords in CONCEPT_CLUSTERS.items():
        for kw in keywords:
            if ' ' in kw:
                # 複数単語キーワード: フルテキストの部分文字列として検索
                if kw in text_lower:
                    concepts.add(cluster_name)
                    break
            else:
                # 単一単語キーワード: ワードセットで高速一致
                if kw in words:
                    concepts.add(cluster_name)
                    break
    return concepts

def get_uploaded_concepts(cache_path):
    """
    script_cache.json からすでにアップロードされた全トピック・タイトルのコンセプトクラスターを収集する。
    """
    uploaded_concepts = set()
    if not os.path.exists(cache_path):
        return uploaded_concepts
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            for item in data.get("items", []):
                if item.get("status") == "uploaded":
                    # トピックとタイトルの両方からコンセプトを抽出
                    uploaded_concepts.update(extract_concepts(item.get("topic", "")))
                    uploaded_concepts.update(extract_concepts(item.get("title", "")))
    except Exception as e:
        print(f"[CONCEPT_GUARD_WARN] Failed to load script cache for concepts: {e}")
    return uploaded_concepts

def is_concept_duplicated(text, uploaded_concepts):
    """
    指定されたテキストのコンセプトが、既にアップロード済みのコンセプトと重複しているか判定する。
    """
    text_concepts = extract_concepts(text)
    overlap = text_concepts.intersection(uploaded_concepts)
    if overlap:
        return True, overlap
    return False, set()

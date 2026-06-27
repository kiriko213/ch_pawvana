"""
concept_guard audit & verification script
"""
import sys
import os
import io

# Force UTF-8 output on Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from concept_guard import extract_concepts, get_uploaded_concepts, is_concept_duplicated, CONCEPT_CLUSTERS

# === Simulated uploaded history ===
SIMULATED_UPLOADED_HISTORY = [
    {"topic": "Dog Tail Communication", "title": "The Truth About Dog Tail Communication", "status": "uploaded"},
    {"topic": "Dog Tail Signals", "title": "5 Secrets of Dog Tail Signals", "status": "uploaded"},
    {"topic": "Dog Tail Position Meaning", "title": "Dog Tail Position Meaning", "status": "uploaded"},
]

uploaded_concepts = set()
for item in SIMULATED_UPLOADED_HISTORY:
    uploaded_concepts.update(extract_concepts(item["topic"]))
    uploaded_concepts.update(extract_concepts(item["title"]))

print("=" * 70)
print(f"SIMULATED UPLOADED CONCEPTS: {uploaded_concepts}")
print("=" * 70)

# === MUST-REJECT test cases ===
MUST_REJECT = [
    "Tail Wagging Secrets",
    "The Truth About Tail Movement",
    "Dog Body Language Using Tails",
    "Emotional Meaning Of Tail Motion",
    "Dog tail signals",
    "Why dogs wag their tails",
    "Understanding tail position",
    "Wagging speed meaning",
]

print("\n=== MUST-REJECT TEST CASES ===")
all_rejected = True
for text in MUST_REJECT:
    is_dup, overlap = is_concept_duplicated(text, uploaded_concepts)
    if is_dup:
        print(f"  [REJECTED OK] '{text}' -> blocked by clusters: {overlap}")
    else:
        all_rejected = False
        detected = extract_concepts(text)
        print(f"  [PASSED - BUG] '{text}' -> detected_concepts={detected}, overlap={overlap}")

print(f"\nMust-Reject Verdict: {'ALL REJECTED' if all_rejected else 'SOME PASSED - CONCEPT GUARD HAS GAPS'}")

# === MUST-ALLOW test cases ===
MUST_ALLOW = [
    "Dog Nutrition Myths",
    "How Dogs See Color",
    "Dog Aging Process",
    "Canine Genetics Secrets",
    "Dog Domestication History",
]

print("\n=== MUST-ALLOW TEST CASES ===")
all_allowed = True
for text in MUST_ALLOW:
    is_dup, overlap = is_concept_duplicated(text, uploaded_concepts)
    if not is_dup:
        print(f"  [ALLOWED OK] '{text}'")
    else:
        all_allowed = False
        print(f"  [BLOCKED - BUG] '{text}' -> overlap={overlap}")

print(f"\nMust-Allow Verdict: {'ALL ALLOWED' if all_allowed else 'SOME BLOCKED - OVER-FILTERING'}")

# === CLUSTER COVERAGE AUDIT ===
print("\n=== CLUSTER COVERAGE AUDIT ===")
problem_words = ["movement", "motion", "position", "body language", "wagging speed"]
for word in problem_words:
    concepts = extract_concepts(word)
    has_tail = "TAIL" in concepts
    print(f"  '{word}' -> concepts={concepts}, TAIL detected: {has_tail}")

# Combined case
combo = "Dog Body Language Using Tails"
concepts_combo = extract_concepts(combo)
print(f"\n  Combined: '{combo}' -> concepts={concepts_combo}")

print("\n" + "=" * 70)
if all_rejected and all_allowed:
    print("VERDICT: PASS")
else:
    print("VERDICT: FAIL")
    if not all_rejected:
        print("  REASON: Some tail-related concepts are NOT being rejected")
    if not all_allowed:
        print("  REASON: Some unrelated concepts are being falsely blocked")
print("=" * 70)

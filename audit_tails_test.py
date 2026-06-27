import sys
import os
import io

# Force UTF-8 stdout
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from concept_guard import extract_concepts, is_concept_duplicated

# Simulated Uploaded History (Already published)
# Contains "Dog Tail Communication"
uploaded_concepts = {"TAIL"}

test_titles = [
    "Dog Tail Communication",
    "Dog Tail Signals",
    "Dog Tail Meaning",
    "Dog Tail Movement",
    "Dog Tail Position",
    "Dog Tail Language",
    "Dog Body Language Using Tail",
    "What Your Dog's Tail Reveals",
    "Tail Wagging Secrets",
    "Why Dogs Wag Their Tails"
]

print("=== Simulating concept checks ===")
for title in test_titles:
    detected = extract_concepts(title)
    is_blocked, overlap = is_concept_duplicated(title, uploaded_concepts)
    print(f"Title: {title}")
    print(f"  Detected Concepts: {list(detected)}")
    print(f"  Blocked: {is_blocked} (Overlap: {list(overlap)})")
    print("-" * 50)

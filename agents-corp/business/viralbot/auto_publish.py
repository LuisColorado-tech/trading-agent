"""ViralBot publisher — scheduled content posting."""
import os, sys, json, time
from datetime import datetime, timezone

DRAFTS = "/opt/trading/agents-corp/business/viralbot/drafts"
PUBLISHED = "/opt/trading/agents-corp/business/viralbot/published"
os.makedirs(DRAFTS, exist_ok=True); os.makedirs(PUBLISHED, exist_ok=True)

# Check for pending drafts to auto-publish
drafts = sorted([f for f in os.listdir(DRAFTS) if f.endswith('.json')])
if drafts:
    draft = drafts[0]
    src = os.path.join(DRAFTS, draft); dst = os.path.join(PUBLISHED, draft)
    with open(src) as f: batch = json.load(f)
    print(f"Publishing batch: {draft}")
    total = 0
    for topic, content in batch.get("topics", {}).items():
        thread = content.get("thread", "")
        if thread:
            lines = [l.strip() for l in thread.split('\n') if l.strip() and l[0].isdigit()]
            for line in lines:
                parts = line.split('. ', 1) if '. ' in line else (line[0], line[2:])
                text = parts[1][:277] + "..." if len(parts) > 1 and len(parts[1]) > 280 else (parts[1] if len(parts) > 1 else line)
                total += 1
    os.rename(src, dst)
    print(f"Published {total} tweets from {len(batch['topics'])} topics -> {dst}")
else:
    print("No drafts to publish")

"""ViralBot — Scheduled Content Publisher."""
import os, json
from datetime import datetime, timezone

DRAFTS_DIR = "/opt/agents-corp/business/viralbot/drafts"
PUBLISHED_DIR = "/opt/agents-corp/business/viralbot/published"

def get_pending_drafts():
    drafts = []
    if not os.path.exists(DRAFTS_DIR): return drafts
    for f in sorted(os.listdir(DRAFTS_DIR)):
        if f.endswith('.json'):
            with open(os.path.join(DRAFTS_DIR, f)) as fh:
                drafts.append({"file": f, "data": json.load(fh)})
    return drafts

def approve_and_publish(draft_file: str, selected_topics: list):
    """Move approved content to published queue."""
    os.makedirs(PUBLISHED_DIR, exist_ok=True)
    src = os.path.join(DRAFTS_DIR, draft_file)
    dst = os.path.join(PUBLISHED_DIR, draft_file)
    os.rename(src, dst)
    return {"published": draft_file, "topics": len(selected_topics)}

if __name__ == "__main__":
    pending = get_pending_drafts()
    print(f"Pending drafts: {len(pending)}")
    for d in pending:
        print(f"  {d['file']}: {list(d['data'].keys())}")

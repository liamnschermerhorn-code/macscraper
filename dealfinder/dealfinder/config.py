import os

MODEL = os.environ.get("DEALFINDER_MODEL", "claude-sonnet-5-5")
JUDGE_MODEL = os.environ.get("DEALFINDER_JUDGE_MODEL", MODEL)
ACCESS_CODE = os.environ.get("ACCESS_CODE", "")          # if set, every API call must send it
EBAY_ID = os.environ.get("EBAY_CLIENT_ID", "")
EBAY_SECRET = os.environ.get("EBAY_CLIENT_SECRET", "")
DEMO = os.environ.get("DEALFINDER_DEMO", "") == "1"      # fake listings, no marketplace needed
PER_IP_PER_HOUR = int(os.environ.get("PER_IP_PER_HOUR", "30"))
DAILY_LLM_CALLS = int(os.environ.get("DAILY_LLM_CALLS", "500"))
MAX_LISTINGS_JUDGED = int(os.environ.get("MAX_LISTINGS_JUDGED", "40"))
MAX_CHAT_TURNS = 24

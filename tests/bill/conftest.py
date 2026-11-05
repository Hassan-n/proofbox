import sys
from pathlib import Path

API_DIR = Path(__file__).resolve().parents[2] / "apps" / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

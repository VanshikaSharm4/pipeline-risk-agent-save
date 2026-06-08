import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.rule_engine import score_structured


def test_dev_failed_is_high():
    s = score_structured({"status": "FAILED", "modules": [], "log_signals": [], "flags": []})
    assert s.risk == "High"
    assert s.prob >= 0.9

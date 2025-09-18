import importlib.util
import sys
from pathlib import Path

# Import module directly from file path to avoid path issues
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
MODULE_PATH = ROOT / "quora_scraper.py"
spec = importlib.util.spec_from_file_location("quora_scraper", MODULE_PATH)
qs = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(qs)


def test_normalize_number_basic():
    # Plain integers
    assert qs.QuoraScraper._normalize_number("1") == 1
    assert qs.QuoraScraper._normalize_number("123") == 123
    assert qs.QuoraScraper._normalize_number("1,234") == 1234
    assert qs.QuoraScraper._normalize_number("  987 \n") == 987


def test_normalize_number_mil():
    # Portuguese 'mil' (thousand) notation
    assert qs.QuoraScraper._normalize_number("14 mil") == 14000
    assert qs.QuoraScraper._normalize_number("14,7 mil") == 14700
    assert qs.QuoraScraper._normalize_number("14.7 mil") == 14700


def test_resolve_profile_url_precedence():
    default = qs.DEFAULT_PROFILE_URL
    # 1) CLI wins
    assert qs.resolve_profile_url("cli", "env", default) == "cli"
    # 2) Env wins when no CLI
    assert qs.resolve_profile_url(None, "env", default) == "env"
    # 3) Default when neither
    assert qs.resolve_profile_url(None, None, default) == default

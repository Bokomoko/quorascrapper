import re

from quorascrapper.selectors import PROFILE_STATS_XPATHS

DEFAULT_PROFILE_URL = (
    "https://pt.quora.com/profile/Jo%C3%A3o-Eurico-de-Aguiar-Lima/answers"
)


def resolve_profile_url(
    cli_arg: str | None,
    env_url: str | None,
    default_url: str = DEFAULT_PROFILE_URL,
) -> str:
    return cli_arg or env_url or default_url


def normalize_number(txt: str | None) -> int | None:
    if not txt:
        return None
    txt = txt.replace("\u00a0", " ").strip()
    mil_match = re.match(r"([0-9]+)[\.,]?([0-9]+)?\s*mil", txt, re.IGNORECASE)
    if mil_match:
        whole = int(mil_match.group(1))
        frac = mil_match.group(2)
        return whole * 1000 + (
            int(frac) * (1000 // (10 ** len(frac))) if frac else 0
        )
    txt = txt.replace(",", "")
    digits = re.findall(r"\d+", txt)
    if digits:
        try:
            return int("".join(digits))
        except Exception:
            return None
    return None


def extract_profile_stats(driver, By) -> dict:
    stats: dict = {}
    for key, xp in PROFILE_STATS_XPATHS.items():
        if key not in ("answers", "questions", "following", "followers"):
            continue
        try:
            elem = driver.find_element(By.XPATH, xp)
            stats[key] = normalize_number(elem.text.strip())
        except Exception:
            stats[key] = None

    if stats.get("answers") is None or stats.get("questions") is None:
        try:
            meta_desc = driver.find_element(
                By.XPATH, "//meta[@property='og:description']"
            )
            content = meta_desc.get_attribute("content") or ""
            answers_match = re.search(
                r"(\d+[\.,]?\d*(?:\s*mil)?)\s+respostas", content, re.IGNORECASE
            )
            questions_match = re.search(
                r"(\d+[\.,]?\d*(?:\s*mil)?)\s+perguntas", content, re.IGNORECASE
            )
            if stats.get("answers") is None and answers_match:
                stats["answers"] = normalize_number(answers_match.group(1))
            if stats.get("questions") is None and questions_match:
                stats["questions"] = normalize_number(questions_match.group(1))
        except Exception:
            pass

    for drop_key in ("followers", "following"):
        stats.pop(drop_key, None)
    return stats


def compute_answer_limit(stats: dict, max_results: int) -> int:
    answers_total = stats.get("answers")
    if answers_total and isinstance(answers_total, int):
        return min(answers_total, max_results)
    return max_results

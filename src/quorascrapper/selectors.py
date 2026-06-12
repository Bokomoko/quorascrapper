"""Semantic XPath selectors for Quora scraping."""

ANSWER_BLOCK_XPATHS = [
    "//article[.//a[contains(@href,'/answer/')]]",
]

ANSWER_ANCHOR_XPATH = " | ".join(
    [
        "//a[contains(@href,'/answer/')]",
        "//a[contains(translate(@href,'ANSWER','answer'),'/answer/')]",
        "//a[@data-ntiid and contains(@href,'/answer/')]",
    ]
)

QUESTION_TEXT_XPATHS = [
    ".//a[contains(@href,'/question/')][1]",
    ".//div[./a[contains(@href,'/answer/')]]/preceding-sibling::div[1]//span[contains(@class,'q-text')][1]",
    ".//span[contains(@class,'q-text')][1]",
]

ANSWER_TEXT_XPATHS = [
    ".//div[contains(@class,'q-text') and not(.//button)][not(ancestor::aside)]",
]

ANSWER_LINK_XPATHS = [
    ".//a[contains(@href,'/answer/')][1]",
]

PROFILE_STATS_XPATHS = {
    "followers": "//div[contains(text(),'seguidores')]/preceding::div[1]",
    "following": "//div[contains(text(),'seguindo')]/preceding::div[1]",
    "answers": "//div[contains(text(),'respostas')]/preceding::div[1]",
    "questions": "//div[contains(text(),'perguntas')]/preceding::div[1]",
}

INITIAL_ANSWER_WAIT_SECONDS = 15

LOGIN_WALL_MARKERS = (
    "log in",
    "sign in",
    "login",
    "entrar",
    "iniciar sessão",
)

CLOUDFLARE_MARKERS = ("just a moment",)

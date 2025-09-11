"""Selector constants for Quora scraping.

We avoid brittle auto-generated class names by:
1. Targeting semantic attributes (href patterns like '/answer/' and '/question/')
2. Using XPath relationships (question link preceding answer content)
3. Providing multiple fallbacks per element (primary then secondary)

The scraper code should iterate through ANSWER_BLOCK_XPATHS until it finds matches.
"""

# XPaths for locating each answer block container (prefer article)
ANSWER_BLOCK_XPATHS = [
    "//article[.//a[contains(@href,'/answer/')]]",
]

# Refined question text selectors inside a block. Order matters.
QUESTION_TEXT_XPATHS = [
    # Anchor to the question page (preferred)
    ".//a[contains(@href,'/question/')][1]",
    # Heading style spans/divs that often contain the question text above answer
    ".//div[./a[contains(@href,'/answer/')]]/preceding-sibling::div[1]//span[contains(@class,'q-text')][1]",
    ".//span[contains(@class,'q-text')][1]",
]

# Refined answer text: capture rich text container but exclude footer/actions.
ANSWER_TEXT_XPATHS = [
    # Rich text blocks within answer; avoids buttons/footers by excluding those with role/button descendants
    ".//div[contains(@class,'q-text') and not(.//button)][not(ancestor::aside)]",
]

ANSWER_LINK_XPATHS = [
    ".//a[contains(@href,'/answer/')][1]",
]

# Profile stats XPaths (Portuguese labels). We normalize numbers later.
PROFILE_STATS_XPATHS = {
    "followers": "//div[contains(text(),'seguidores')]/preceding::div[1]",
    "following": "//div[contains(text(),'seguindo')]/preceding::div[1]",
    "answers": "//div[contains(text(),'respostas')]/preceding::div[1]",
    "questions": "//div[contains(text(),'perguntas')]/preceding::div[1]",
}

# Time to wait for first answer block
INITIAL_ANSWER_WAIT_SECONDS = 15

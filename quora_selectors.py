"""Selector constants for Quora scraping.

We avoid brittle auto-generated class names by:
1. Targeting semantic attributes (href patterns like '/answer/' and '/question/')
2. Using XPath relationships (question link preceding answer content)
3. Providing multiple fallbacks per element (primary then secondary)

The scraper code should iterate through ANSWER_BLOCK_XPATHS until it finds matches.
"""

# XPaths for locating each answer block container
# Strategy: Each answer block typically contains an anchor with '/answer/' in href.
ANSWER_BLOCK_XPATHS = [
    # Newer layout: article element containing answer link
    "//article[.//a[contains(@href,'/answer/')]]",
    # Fallback: div grouping containing answer link
    "//div[.//a[contains(@href,'/answer/')]]",
]

# Within an answer block, find the question text.
# Usually an anchor with a question path (may include the Portuguese localized domain already resolved by Selenium).
QUESTION_TEXT_XPATHS = [
    ".//a[contains(@href,'/question/')][1]",
    # Some layouts place question inside a span preceding answer
    ".//span[contains(@class,'QuestionText') or contains(@class,'q-text')][1]",
]

# Within an answer block, answer text paragraphs/spans aggregate inside a div with role="textbox" or styled q-text
ANSWER_TEXT_XPATHS = [
    ".//div[contains(@class,'Answer') and .//div[contains(@class,'q-text')]]//div[contains(@class,'q-text')]",
    ".//div[contains(@class,'q-text')]",
]

# Direct answer permalink (first /answer/ link inside block)
ANSWER_LINK_XPATHS = [
    ".//a[contains(@href,'/answer/')][1]",
]

# Time to wait for first answer block
INITIAL_ANSWER_WAIT_SECONDS = 15

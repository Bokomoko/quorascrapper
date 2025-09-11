# Quora Profile Scraper

A tool to scrape questions and answers from Quora profiles.

## Setup

1. Install Python 3.8 or higher

2. Install Chrome browser if not already installed

3. Install uv if not already installed:
```bash
pip install uv
```

4. Create and activate virtual environment with uv:
```bash
uv venv
source .venv/bin/activate  # On Unix/MacOS
# or
.venv\Scripts\activate     # On Windows
```

5. Install dependencies with uv:
```bash
uv pip install -r requirements.txt
```

## Running the Scraper

Run using uv:
```bash
uv run quora_scraper.py
```

The script will:
- Start a headless Chrome browser
- Load the profile page
- Scroll through all content
- Save results to `quora_answers.json`

## Output

Results are saved in JSON format containing:
- Question text and link
- Answer text and link

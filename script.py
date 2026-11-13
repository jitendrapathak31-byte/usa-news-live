import os
import re
import json
import datetime
import urllib.parse
import feedparser
from google import genai
from google.genai import types

RSS_FEEDS = {
    "Politics": "https://rss.nytimes.com/services/xml/rss/nyt/Politics.xml",
    "Business": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10001147",
    "Technology": "https://www.theverge.com/rss/index.xml",
    "World": "https://feeds.bbci.co.uk/news/world/us_and_canada/rss.xml",
    "Entertainment": "https://variety.com/feed/"
}

def extract_image_from_entry(entry):
    if "media_content" in entry and len(entry.media_content) > 0:
        url = entry.media_content[0].get("url", "")
        if url.startswith("http"):
            return url
    if "media_thumbnail" in entry and len(entry.media_thumbnail) > 0:
        url = entry.media_thumbnail[0].get("url", "")
        if url.startswith("http"):
            return url
    summary = entry.get("summary", "")
    img_match = re.search(r'<img[^>]+src=["\'](https?://[^"\']+)["\']', summary)
    if img_match:
        return img_match.group(1)
    return ""

def fetch_raw_feeds():
    collected = []
    for category, feed_url in RSS_FEEDS.items():
        try:
            parsed = feedparser.parse(feed_url)
            for idx, entry in enumerate(parsed.entries[:3]):
                clean_summary = re.sub(r'<[^>]+>', '', entry.get("summary", ""))[:500]
                collected.append({
                    "id": f"{category.lower()[:3]}-{idx+1}",
                    "category": category,
                    "raw_title": entry.get("title", "").strip(),
                    "raw_summary": clean_summary.strip(),
                    "url": entry.get("link", "https://apnews.com"),
                    "image_url": extract_image_from_entry(entry),
                    "source": parsed.feed.get("title", f"{category} Wire")[:32]
                })
        except Exception as e:
            print(f"Warning: Failed to fetch {category} feed: {e}")
    return collected

def enrich_with_gemini(raw_items):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY environment variable is missing!")

    client = genai.Client(api_key=api_key)

    prompt = f"""
You are the Executive Editor of a top-tier American national news organization.
Transform the following raw RSS wire items into polished, 100% flawless American English journalism.

Strict Requirements:
1. Return ONLY valid JSON matching the exact schema requested.
2. Provide 5 punchy, all-caps 'breaking_tickers'.
3. Keep each article's exact 'id', 'category', 'url', 'image_url', and 'source'.
4. Write a compelling 'title', a 2-sentence 'summary', and a 3-paragraph 'content' list.
5. Assign a realistic editorial desk 'author' and 'published_at' timestamp (e.g., '12 mins ago').
6. Create a short 'image_prompt' (max 12 words) describing a realistic photojournalism scene for this story (no text in image).

Raw Wire Input:
{json.dumps(raw_items, indent=2)}

Required JSON Output Format:
{{
  "breaking_tickers": ["TICKER 1", "TICKER 2", "TICKER 3", "TICKER 4", "TICKER 5"],
  "articles": [
    {{
      "id": "string",
      "title": "string",
      "summary": "string",
      "content": ["paragraph 1", "paragraph 2", "paragraph 3"],
      "category": "Politics | Business | Technology | World | Entertainment",
      "author": "string",
      "source": "string",
      "published_at": "string",
      "image_prompt": "realistic editorial photojournalism of ...",
      "image_url": "string",
      "url": "string"
    }}
  ]
}}
"""

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.3
        )
    )

    structured_data = json.loads(response.text)

    for idx, article in enumerate(structured_data.get("articles", [])):
        img_url = article.get("image_url", "").strip()
        if not img_url:
            img_prompt = article.get("image_prompt", article.get("title", "USA breaking news"))
            encoded_prompt = urllib.parse.quote(f"{img_prompt}, realistic editorial news photography, 4k, high detail")
            article["image_url"] = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1200&height=675&nologo=true&seed={idx+100}"

    now_utc = datetime.datetime.now(datetime.timezone.utc).strftime("%b %d, %Y %H:%M UTC")
    structured_data["last_updated"] = now_utc
    return structured_data

def update_index_html(news_payload):
    with open("index.html", "r", encoding="utf-8") as f:
        html_content = f.read()

    json_str = json.dumps(news_payload, indent=2, ensure_ascii=False)
    replacement_block = (
        "<!-- NEWS_DATA_START -->\n"
        '    <script id="news-data" type="application/json">\n'
        f"{json_str}\n"
        "    </script>\n"
        "    <!-- NEWS_DATA_END -->"
    )

    pattern = re.compile(r"<!-- NEWS_DATA_START -->.*?<!-- NEWS_DATA_END -->", re.DOTALL)
    updated_html = pattern.sub(replacement_block, html_content)
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(updated_html)
    print("Successfully updated index.html with fresh USA news and AI images.")

if __name__ == "__main__":
    raw_stories = fetch_raw_feeds()
    if raw_stories:
        final_payload = enrich_with_gemini(raw_stories)
        update_index_html(final_payload)

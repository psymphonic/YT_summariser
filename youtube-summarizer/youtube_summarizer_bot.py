# youtube_summarizer_bot.py – Final Version for Render Deployment
# Summarizes new + unsummarized YouTube videos weekly and posts to Notion

import os
import json
import openai
import whisper
import yt_dlp
import requests
from datetime import datetime
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled
from googleapiclient.discovery import build
from notion_client import Client as NotionClient

# === ENVIRONMENT VARIABLES ===
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
NOTION_API_KEY = os.getenv("NOTION_API_KEY")
NOTION_DB_ID = "215605d118f1801baf9ce4b626303824"

openai.api_key = OPENAI_API_KEY
notion = NotionClient(auth=NOTION_API_KEY)
youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)

CHANNEL_IDS = [
    # Sample: Replace or expand with actual channel IDs
    "UCk4jkf8Rpi2XA2lWzSCEieg",  # Physionic
    "UCtqdE1eITw1R9DR_ZltfdzA"   # Nutrition Made Easy!
]

PROCESSED_DB = "processed.json"
VIDEOS_PER_CHANNEL = 10

# === LOAD PROCESSED ===
if os.path.exists(PROCESSED_DB):
    with open(PROCESSED_DB, "r") as f:
        processed = set(json.load(f))
else:
    processed = set()

# === UTILITY FUNCTIONS ===
def fetch_latest_videos(channel_id):
    req = youtube.search().list(
        part="snippet",
        channelId=channel_id,
        maxResults=VIDEOS_PER_CHANNEL,
        order="date",
        type="video"
    )
    res = req.execute()
    return [
        {
            "videoId": item["id"]["videoId"],
            "title": item["snippet"]["title"],
            "publishedAt": item["snippet"]["publishedAt"],
            "channelTitle": item["snippet"]["channelTitle"]
        }
        for item in res.get("items", [])
    ]

def fetch_transcript(video_id):
    try:
        transcript = YouTubeTranscriptApi.get_transcript(video_id)
        return " ".join([x["text"] for x in transcript])
    except:
        return None

def transcribe_with_whisper(video_id):
    url = f"https://www.youtube.com/watch?v={video_id}"
    filename = f"audio_{video_id}.mp3"
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': filename,
        'quiet': True,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
    model = whisper.load_model("base")
    result = model.transcribe(filename)
    os.remove(filename)
    return result['text']

def summarize_with_gpt(transcript, video):
    prompt = f"""
You are summarizing a YouTube video. Provide:
1. Abstract (2–3 sentences)
2. 5–10 bullet points
3. Key quotes (if any, with timestamps if present)

Video Title: {video['title']}
YouTuber: {video['channelTitle']}
Date: {video['publishedAt']}
Link: https://youtube.com/watch?v={video['videoId']}

Transcript:
{transcript[:8000]}
"""
    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.4
    )
    return response.choices[0].message.content

def post_to_notion(summary, video):
    notion.pages.create(
        parent={"database_id": NOTION_DB_ID},
        properties={
            "Title": {"title": [{"text": {"content": video["title"]}}]},
            "YouTuber": {"rich_text": [{"text": {"content": video["channelTitle"]}}]},
            "Date": {"date": {"start": video["publishedAt"]}},
            "Link": {"url": f"https://youtube.com/watch?v={video['videoId']}"},
        },
        children=[
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": summary[:2000]}}]
                }
            }
        ]
    )

# === MAIN LOOP ===
for channel_id in CHANNEL_IDS:
    videos = fetch_latest_videos(channel_id)
    for video in videos:
        if video["videoId"] in processed:
            continue

        transcript = fetch_transcript(video["videoId"])
        if not transcript:
            transcript = transcribe_with_whisper(video["videoId"])
        if not transcript:
            print(f"⚠️ No transcript: {video['title']}")
            continue

        print(f"✅ Summarizing: {video['title']}")
        summary = summarize_with_gpt(transcript, video)
        post_to_notion(summary, video)
        processed.add(video["videoId"])

# === SAVE PROCESSED ===
with open(PROCESSED_DB, "w") as f:
    json.dump(list(processed), f)

print("✅ All summaries posted to Notion.")

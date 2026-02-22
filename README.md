# 🎵 LyreAura

> A lightweight Pomodoro productivity timer + YouTube Music player built with Python & Tkinter.

**No Electron. No browser. Pure Python. Very low RAM.**

---

## 📥 [Download Latest Release](https://github.com/jestkent/LyreAura/releases/latest)

**LyreAura.exe** is now available! No Python installation required. Just download, set your API key, and focus.

---

## 🚀 Features

| Feature | Details |
|---|---|
| 🕐 Pomodoro Timer | Circular countdown, customizable work/break durations, session counter |
| 🧍 Stand-Up Reminders | Stretch tips popup blocks until acknowledged — forces healthy breaks |
| 🎵 YouTube Search | Search via YouTube Data API v3, filtered to Music category |
| 🔊 Audio Playback | yt-dlp + FFmpeg + pygame — reliable MP3 conversion and streaming |
| 🎚️ Volume Control | Slider + mute/unmute button (remembers pre-mute level) |
| ⏮⏯⏭ Playback Controls | Prev / Play-Pause / Next / Shuffle |
| 🎶 Queue System | Add songs to queue, reorder, auto-advance when track ends |
| 📂 Playlist Manager | Create, save, load, and delete named playlists (persisted as JSON) |
| 💾 Session Restore | Your last search results and queue are restored on every launch |
| 🖥️ System Tray | Minimize to tray, live timer countdown in tooltip |
| 🔄 Scrollable UI | Fully resizable window with mouse-wheel scrollable content |
| 🚀 Windows Auto-Start | Optionally starts with Windows for seamless productivity |

---

## 🔐 Security

This project uses a **YouTube Data API v3 key**. Your key is private — follow these rules:

- ✅ Your real key goes in `.env` — **this file is in `.gitignore` and will NEVER be committed**
- ✅ `.env.example` contains only a **placeholder** — safe to commit
- ❌ Never paste your real key into `.env.example`, the README, or any tracked file
- ❌ Never commit `.env`, `playlists.json`, or `session.json` (all gitignored)

If you accidentally commit your key, immediately **delete and regenerate it** in [Google Cloud Console](https://console.cloud.google.com/).

---

## ⚙️ Setup

### 1. Get a YouTube Data API v3 Key

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (or select existing)
3. Enable **YouTube Data API v3** from the API Library
4. Create credentials → **API Key**
5. Copy the key

### 2. Configure your API Key

```bash
# Copy the example env file
copy .env.example .env
```

Then edit `.env` and replace the placeholder with your actual key:

```
YOUTUBE_API_KEY=AIza...your_actual_key...
```

> 💡 Alternatively, just launch the app — it will prompt you to enter the key on first run and save it automatically to `.env`.

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

> Requires **FFmpeg** installed and on PATH (or at `C:\Program Files\ffmpeg\bin\`) for MP3 conversion.
> Download from [ffmpeg.org](https://ffmpeg.org/download.html).

### 4. Run

```bash
python main.py
```

---

## 📖 Usage

### Timer
- Adjust **Work / Short Brk / Long Brk** minute values at the top, press Enter to apply
- Click **▶ Start** to begin the Pomodoro session
- After each work block ends: a stand-up popup appears — dismiss it to start break timer
- Every 4 sessions triggers a 15-min long break

### Music
- Type a song/artist in the search bar and press **Search** or hit Enter
- Click a result to **select** it (no auto-play)
- Click **▶ Play** to start streaming, or **+ Queue** to add to the queue
- Use **⏮ ⏯ ⏭** for playback controls; **🔀** to toggle shuffle
- Adjust volume with the slider; click the speaker icon to mute/unmute

### Queue
- Add songs from search results with **+ Queue**
- Double-click any queue item to play it immediately
- Reorder with **▲Up / ▼Down**, remove with **✕ Remove**, or **Clear** all
- Auto-advances to next track when current one ends

### Playlists
- Click **+ New** to create a named playlist
- Select a search result and click **+ Playlist** to add it
- Select a playlist from the dropdown → **Load** to populate the song list
- **▶ Play All** queues the entire playlist
- **💾 Save** to persist, **🗑 Delete PL** to remove

### System Tray
- Closing the window **minimizes to tray** (does not quit)
- Right-click the tray icon → **Quit** to fully exit

---

## 📦 Requirements

| Package | Purpose |
|---|---|
| `google-api-python-client` | YouTube Data API v3 search |
| `yt-dlp` | Extract audio from YouTube |
| `pygame` | Audio playback + beep sound |
| `python-dotenv` | Load `.env` API key |
| `pystray` | System tray icon |
| `Pillow` | Generate tray icon image |

---

## 📁 Project Structure

```
LyreAura/
├── main.py            # Full application (single file)
├── requirements.txt   # Python dependencies
├── .env.example       # API key template (safe to commit)
├── .env               # Your real API key (GITIGNORED)
├── .gitignore         # Excludes .env, playlists.json, session.json, .venv
├── playlists.json     # Your saved playlists (GITIGNORED — personal data)
├── session.json       # Last session state (GITIGNORED — personal data)
├── README.md          # This file
└── PORTFOLIO.txt      # Project documentation for portfolio/recruiters
```

---

## 📝 Notes

- YouTube API free quota: **10,000 units/day** (each search = 100 units → ~100 free searches/day)
- Tested on **Windows 10/11**, Python 3.10+
- The app stores temp audio in your system temp folder and cleans up automatically

---

## 👤 About

Built by a developer who noticed they were sitting too long while programming.
LyreAura combines healthy work habits with the music they love.

---

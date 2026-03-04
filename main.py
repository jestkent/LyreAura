"""
LyreAura — Pomodoro Timer + YouTube Music Player
Single-file desktop app using Tkinter, pygame, yt-dlp, googleapiclient
Features: Volume control (mute/%), Playlist Manager (save/load), Queue
"""

import os
import sys
import io
import json
import math
import random
import threading
import time
import struct
import traceback
import wave
import tempfile
import tkinter as tk
from tkinter import font as tkfont, messagebox

# ── Path helper: works as plain script AND as a frozen PyInstaller .exe ────────
def _app_dir() -> str:
    """Return the directory containing the app's data files.
    When frozen by PyInstaller (--onefile/--onedir), sys.executable is the .exe.
    When running as a script, __file__ is main.py.
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

APP_DIR   = _app_dir()
_ENV_PATH = os.path.join(APP_DIR, ".env")
try:
    from dotenv import load_dotenv, set_key
    load_dotenv(_ENV_PATH, override=True)
except ImportError:
    def load_dotenv(*a, **k): pass
    def set_key(f, k, v): pass

try:
    import pygame
    pygame.init()
    pygame.mixer.init()
    PYGAME_OK = True
except Exception:
    PYGAME_OK = False

try:
    from googleapiclient.discovery import build as yt_build
    YT_API_OK = True
except ImportError:
    YT_API_OK = False

try:
    import yt_dlp
    YTDLP_OK = True
except ImportError:
    YTDLP_OK = False

try:
    from PIL import Image, ImageDraw
    import pystray
    TRAY_OK = True
except ImportError:
    TRAY_OK = False

# ── Constants ──────────────────────────────────────────────────────────────────
BG        = "#0f0f1a"
CARD      = "#1a1a2e"
CARD2     = "#16213e"
ACCENT    = "#c678dd"
GREEN     = "#00b894"
BLUE      = "#0984e3"
WHITE     = "#ffffff"
MUTED     = "#636e72"
SEP       = "#2d2d44"
RED       = "#e17055"
YELLOW    = "#fdcb6e"

WIN_W, WIN_H = 460, 870

STRETCH_TIPS = [
    "Roll your shoulders back 10 times 🔄",
    "Touch your toes and hold for 15 seconds 🤸",
    "Walk to another room and back 🚶",
    "Look 20 feet away for 20 seconds 👀",
    "Drink a glass of water 💧",
]

ENV_FILE       = os.path.join(APP_DIR, ".env")
PLAYLISTS_FILE = os.path.join(APP_DIR, "playlists.json")
SESSION_FILE   = os.path.join(APP_DIR, "session.json")


def get_font(size, weight="normal"):
    try:
        return tkfont.Font(family="Segoe UI", size=size, weight=weight)
    except Exception:
        return tkfont.Font(family="Helvetica", size=size, weight=weight)


def generate_beep_wav(freq=440, duration=0.4, volume=0.4, rate=44100) -> bytes:
    """Generate a simple sine-wave beep as raw WAV bytes."""
    samples = int(rate * duration)
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        data = bytearray()
        for i in range(samples):
            val = int(volume * 32767 * math.sin(2 * math.pi * freq * i / rate))
            data += struct.pack('<h', val)
        wf.writeframes(bytes(data))
    buf.seek(0)
    return buf.read()


# ── Main Application ───────────────────────────────────────────────────────────
class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("LyreAura")
        self.root.geometry(f"{WIN_W}x{WIN_H}")
        self.root.resizable(True, True)
        self.root.minsize(380, 500)
        self.root.configure(bg=BG)

        # ── State ──────────────────────────────────────────────────────────────
        self.api_key: str = os.getenv("YOUTUBE_API_KEY", "")
        self.yt_client = None

        # Timer state
        self.work_min    = tk.IntVar(value=25)
        self.short_min   = tk.IntVar(value=5)
        self.long_min    = tk.IntVar(value=15)
        self.timer_running   = False
        self.timer_paused    = False
        self.session_num     = 1
        self.total_sessions  = 4
        self.is_break        = False
        self.is_long_break   = False
        self.remaining_secs  = self.work_min.get() * 60
        self._timer_after_id = None
        self._tip_index      = 0

        # Music / search state
        self.search_results: list[dict] = []   # results from last search
        self.current_index: int         = -1
        self.shuffle_on: bool           = False
        self.is_playing: bool           = False
        self._track_loaded: bool        = False   # True once a file is loaded in pygame
        self._np_scroll_pos: int        = 0
        self._np_scroll_id              = None
        self._load_thread               = None
        self._muted: bool               = False
        self._vol_before_mute: int      = 70

        # Seek / progress bar state
        self._track_duration: float     = 0.0    # total duration in seconds
        self._playback_start: float     = 0.0    # time.time() when playback started/resumed
        self._elapsed_before_pause: float = 0.0  # accumulated seconds before last pause
        self._seeking: bool             = False  # True while user is dragging the slider
        self._seek_after_id             = None

        # Playlist manager state  { name: [track_dict, ...] }
        self.playlists: dict            = {}
        self.active_playlist_name: str  = ""
        self._load_playlists()

        # Queue state  [ track_dict, ... ]
        self.queue: list[dict]          = []
        self._playing_from_queue: bool  = False

        # Restore previous session
        self._load_session()

        # Beep sound
        self._beep_raw = generate_beep_wav() if PYGAME_OK else None

        # Build scrollable container, then UI
        self._build_scroll_container()
        self._build_ui()
        self._draw_timer_ring()

        # Tray
        self._tray_icon = None
        if TRAY_OK:
            self._setup_tray()
            self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # API key check
        if not self.api_key:
            self.root.after(200, self._prompt_api_key)
        else:
            self._init_yt_client()

        # Start Now Playing scroller + queue monitor
        self._scroll_now_playing()
        self._monitor_queue()

        # Restore session visuals (must happen after _build_ui)
        self.root.after(100, self._restore_session_ui)

    # ══════════════════════════════════════════════════════════════════════════
    # PERSISTENCE
    # ══════════════════════════════════════════════════════════════════════════
    def _load_playlists(self):
        try:
            if os.path.exists(PLAYLISTS_FILE):
                with open(PLAYLISTS_FILE, "r", encoding="utf-8") as f:
                    self.playlists = json.load(f)
        except Exception:
            self.playlists = {}

    def _save_playlists(self):
        try:
            with open(PLAYLISTS_FILE, "w", encoding="utf-8") as f:
                json.dump(self.playlists, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _load_session(self):
        """Restore last session: search results and queue."""
        try:
            if os.path.exists(SESSION_FILE):
                with open(SESSION_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.search_results = data.get("search_results", [])
                self.queue          = data.get("queue", [])
                self.current_index  = data.get("current_index", -1)
        except Exception:
            pass

    def _save_session(self):
        """Persist search results and queue so they survive restart."""
        try:
            data = {
                "search_results": self.search_results,
                "queue":          self.queue,
                "current_index":  self.current_index,
            }
            with open(SESSION_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _restore_session_ui(self):
        """Repopulate listbox and queue from restored session data."""
        # Repopulate search results listbox
        if self.search_results:
            self.listbox.delete(0, "end")
            for t in self.search_results:
                short = t["title"][:58] + ("…" if len(t["title"]) > 58 else "")
                self.listbox.insert("end", f"  {short}")
            # Highlight previously selected item
            if 0 <= self.current_index < len(self.search_results):
                self.listbox.selection_set(self.current_index)
                self.listbox.see(self.current_index)
            self._set_status(f"Restored {len(self.search_results)} songs — click a song then ▶ Play")
        # Repopulate queue listbox
        if self.queue:
            self._refresh_queue_lb()

    # ══════════════════════════════════════════════════════════════════════════
    # UI BUILD
    # ══════════════════════════════════════════════════════════════════════════
    # ══════════════════════════════════════════════════════════════════════════
    # SCROLLABLE CONTAINER
    # ══════════════════════════════════════════════════════════════════════════
    def _build_scroll_container(self):
        """Wrap everything in a Canvas so the UI is scrollable and resizable."""
        self._scroll_canvas = tk.Canvas(self.root, bg=BG, highlightthickness=0)
        self._vscroll = tk.Scrollbar(self.root, orient="vertical",
                                     command=self._scroll_canvas.yview,
                                     bg=CARD, troughcolor=BG, relief="flat")
        self._scroll_canvas.configure(yscrollcommand=self._vscroll.set)
        self._vscroll.pack(side="right", fill="y")
        self._scroll_canvas.pack(side="left", fill="both", expand=True)

        self.main_frame = tk.Frame(self._scroll_canvas, bg=BG)
        self._canvas_win_id = self._scroll_canvas.create_window(
            (0, 0), window=self.main_frame, anchor="nw"
        )
        self.main_frame.bind("<Configure>", self._on_frame_configure)
        self._scroll_canvas.bind("<Configure>", self._on_canvas_configure)
        # Mouse-wheel scrolling
        self.root.bind_all("<MouseWheel>",
            lambda e: self._scroll_canvas.yview_scroll(-1*(e.delta//120), "units"))

    def _on_frame_configure(self, _event=None):
        self._scroll_canvas.configure(
            scrollregion=self._scroll_canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        # Stretch inner frame to canvas width so it fills horizontally
        self._scroll_canvas.itemconfig(self._canvas_win_id, width=event.width)

    # ══════════════════════════════════════════════════════════════════════════
    # UI BUILD
    # ══════════════════════════════════════════════════════════════════════════
    def _build_ui(self):
        root = self.main_frame

        # ── Header ──────────────────────────────────────────────────────────
        hdr = tk.Frame(root, bg=BG)
        hdr.pack(fill="x", pady=(12, 2))
        tk.Label(hdr, text="🎵 LyreAura", bg=BG, fg=ACCENT,
                 font=get_font(20, "bold")).pack()
        tk.Label(hdr, text="Focus • Music • Health", bg=BG, fg=MUTED,
                 font=get_font(9)).pack()

        # ── Timer customisation row ──────────────────────────────────────────
        cfg = tk.Frame(root, bg=BG)
        cfg.pack(fill="x", padx=18, pady=(6, 0))
        for lbl, var in [("Work", self.work_min),
                          ("Short Brk", self.short_min),
                          ("Long Brk", self.long_min)]:
            cell = tk.Frame(cfg, bg=BG)
            cell.pack(side="left", expand=True)
            tk.Label(cell, text=lbl, bg=BG, fg=MUTED,
                     font=get_font(8)).pack()
            e = tk.Entry(cell, textvariable=var, width=3,
                         bg=CARD, fg=WHITE, insertbackground=WHITE,
                         relief="flat", justify="center",
                         font=get_font(10, "bold"))
            e.pack()
            e.bind("<Return>", lambda _: self._on_duration_change())
            e.bind("<FocusOut>", lambda _: self._on_duration_change())

        # ── Canvas timer ────────────────────────────────────────────────────
        self.canvas = tk.Canvas(root, width=230, height=230,
                                bg=BG, highlightthickness=0)
        self.canvas.pack(pady=(8, 0))

        # ── Session label ────────────────────────────────────────────────────
        self.session_lbl = tk.Label(root, text=self._session_text(),
                                    bg=BG, fg=MUTED, font=get_font(10))
        self.session_lbl.pack(pady=(3, 0))

        # ── Control buttons ──────────────────────────────────────────────────
        ctrl = tk.Frame(root, bg=BG)
        ctrl.pack(pady=(6, 3))
        self.btn_start = self._make_btn(ctrl, "▶  Start",  self._start_timer,  GREEN)
        self.btn_start.pack(side="left", padx=5)
        self.btn_pause = self._make_btn(ctrl, "⏸  Pause",  self._pause_timer,  BLUE)
        self.btn_pause.pack(side="left", padx=5)
        self.btn_reset = self._make_btn(ctrl, "↺  Reset",  self._reset_timer,  MUTED)
        self.btn_reset.pack(side="left", padx=5)

        # ── Separator ────────────────────────────────────────────────────────
        tk.Frame(root, bg=SEP, height=1).pack(fill="x", padx=18, pady=(8, 6))

        # ── Search row ──────────────────────────────────────────────────────
        search_row = tk.Frame(root, bg=BG)
        search_row.pack(fill="x", padx=18, pady=(0, 3))
        self.search_var = tk.StringVar()
        self.search_entry = tk.Entry(search_row, textvariable=self.search_var,
                                     bg=CARD, fg=WHITE, insertbackground=WHITE,
                                     relief="flat", font=get_font(10))
        self.search_entry.pack(side="left", fill="x", expand=True,
                               ipady=6, padx=(0, 6))
        self.search_entry.bind("<Return>", lambda _: self._do_search())
        self._make_btn(search_row, "Search", self._do_search, ACCENT, pad=8).pack(side="left")

        # ── Results Listbox ──────────────────────────────────────────────────
        lb_frame = tk.Frame(root, bg=CARD, bd=0)
        lb_frame.pack(fill="x", padx=18, pady=(0, 2))
        scrollbar = tk.Scrollbar(lb_frame, bg=CARD, troughcolor=BG,
                                 relief="flat", bd=0)
        scrollbar.pack(side="right", fill="y")
        self.listbox = tk.Listbox(lb_frame, height=6, bg=CARD, fg=WHITE,
                                  selectbackground=ACCENT, selectforeground=WHITE,
                                  activestyle="none", relief="flat",
                                  font=get_font(9), borderwidth=0,
                                  highlightthickness=0,
                                  yscrollcommand=scrollbar.set,
                                  cursor="hand2")
        self.listbox.pack(fill="x", expand=True)
        scrollbar.config(command=self.listbox.yview)
        self.listbox.bind("<<ListboxSelect>>", self._on_song_select)

        # ── Search result action buttons ─────────────────────────────────────
        res_btns = tk.Frame(root, bg=BG)
        res_btns.pack(fill="x", padx=18, pady=(0, 2))
        self._make_btn(res_btns, "▶ Play",
                       self._play_selected_result, GREEN, pad=8).pack(side="left", padx=(0, 4))
        self._make_btn(res_btns, "+ Queue",
                       self._add_selected_to_queue, BLUE, pad=8).pack(side="left", padx=(0, 4))
        self._make_btn(res_btns, "+ Playlist",
                       self._add_selected_to_playlist, GREEN, pad=8).pack(side="left")

        # ── Status label ────────────────────────────────────────────────────
        self.status_lbl = tk.Label(root, text="", bg=BG, fg=MUTED,
                                   font=get_font(8))
        self.status_lbl.pack()

        # ── Now Playing bar ──────────────────────────────────────────────────
        self.np_lbl = tk.Label(root, text="♪  Nothing playing",
                               bg=BG, fg=ACCENT, font=get_font(9, "bold"),
                               anchor="w")
        self.np_lbl.pack(fill="x", padx=18, pady=(2, 0))

        # ── Seek / Progress bar ──────────────────────────────────────────────
        seek_row = tk.Frame(root, bg=BG)
        seek_row.pack(fill="x", padx=18, pady=(2, 0))

        self.seek_elapsed_lbl = tk.Label(seek_row, text="0:00", bg=BG, fg=MUTED,
                                         font=get_font(7), width=5, anchor="e")
        self.seek_elapsed_lbl.pack(side="left")

        self.seek_slider = tk.Scale(seek_row, from_=0, to=100,
                                    orient="horizontal", bg=BG, fg=WHITE,
                                    troughcolor=CARD, activebackground=ACCENT,
                                    highlightthickness=0, sliderrelief="flat",
                                    showvalue=False, command=self._on_seek_drag,
                                    sliderlength=14)
        self.seek_slider.set(0)
        self.seek_slider.pack(side="left", fill="x", expand=True, padx=(4, 4))
        self.seek_slider.bind("<ButtonPress-1>", self._on_seek_press)
        self.seek_slider.bind("<ButtonRelease-1>", self._on_seek_release)

        self.seek_total_lbl = tk.Label(seek_row, text="0:00", bg=BG, fg=MUTED,
                                       font=get_font(7), width=5, anchor="w")
        self.seek_total_lbl.pack(side="left")

        # ── Playback controls ────────────────────────────────────────────────
        pb = tk.Frame(root, bg=BG)
        pb.pack(pady=(4, 0))
        self._make_icon_btn(pb, "⏮", self._prev_track).pack(side="left", padx=4)
        self.btn_playpause = self._make_icon_btn(pb, "⏯", self._toggle_play)
        self.btn_playpause.pack(side="left", padx=4)
        self._make_icon_btn(pb, "⏭", self._next_track).pack(side="left", padx=4)
        self.shuf_btn = self._make_icon_btn(pb, "🔀", self._toggle_shuffle,
                                            color=MUTED)
        self.shuf_btn.pack(side="left", padx=4)

        # ── Volume row ────────────────────────────────────────────────────────
        vol_row = tk.Frame(root, bg=BG)
        vol_row.pack(fill="x", padx=18, pady=(4, 2))

        self.mute_btn = tk.Button(vol_row, text="🔊", command=self._toggle_mute,
                                  bg=BG, fg=WHITE, relief="flat",
                                  font=get_font(11), cursor="hand2", bd=0)
        self.mute_btn.pack(side="left")

        self.vol_slider = tk.Scale(vol_row, from_=0, to=100,
                                   orient="horizontal", bg=BG, fg=WHITE,
                                   troughcolor=CARD, activebackground=ACCENT,
                                   highlightthickness=0, sliderrelief="flat",
                                   showvalue=False, command=self._on_volume)
        self.vol_slider.set(70)
        self.vol_slider.pack(side="left", fill="x", expand=True, padx=(4, 6))

        self.vol_pct_lbl = tk.Label(vol_row, text="70%", bg=BG, fg=MUTED,
                                    font=get_font(8), width=4, anchor="e")
        self.vol_pct_lbl.pack(side="left")

        if PYGAME_OK:
            pygame.mixer.music.set_volume(0.7)

        # ── Separator ────────────────────────────────────────────────────────
        tk.Frame(root, bg=SEP, height=1).pack(fill="x", padx=18, pady=(4, 4))

        # ── Queue panel ──────────────────────────────────────────────────────
        q_hdr = tk.Frame(root, bg=BG)
        q_hdr.pack(fill="x", padx=18, pady=(0, 2))
        tk.Label(q_hdr, text="🎶 Queue", bg=BG, fg=WHITE,
                 font=get_font(10, "bold")).pack(side="left")
        self._make_btn(q_hdr, "Clear", self._clear_queue, RED, pad=6).pack(side="right")

        q_frame = tk.Frame(root, bg=CARD2, bd=0)
        q_frame.pack(fill="x", padx=18, pady=(0, 2))
        q_scroll = tk.Scrollbar(q_frame, bg=CARD2, troughcolor=BG,
                                relief="flat", bd=0)
        q_scroll.pack(side="right", fill="y")
        self.queue_lb = tk.Listbox(q_frame, height=4, bg=CARD2, fg=WHITE,
                                   selectbackground=ACCENT, selectforeground=WHITE,
                                   activestyle="none", relief="flat",
                                   font=get_font(8), borderwidth=0,
                                   highlightthickness=0,
                                   yscrollcommand=q_scroll.set,
                                   cursor="hand2")
        self.queue_lb.pack(fill="x", expand=True)
        q_scroll.config(command=self.queue_lb.yview)
        self.queue_lb.bind("<Double-Button-1>", self._play_from_queue)

        q_btns = tk.Frame(root, bg=BG)
        q_btns.pack(fill="x", padx=18, pady=(0, 2))
        self._make_btn(q_btns, "▲ Up",   self._queue_move_up,   MUTED, pad=6).pack(side="left", padx=(0,3))
        self._make_btn(q_btns, "▼ Down", self._queue_move_down, MUTED, pad=6).pack(side="left", padx=(0,3))
        self._make_btn(q_btns, "✕ Remove",self._queue_remove,   RED,   pad=6).pack(side="left")

        # ── Separator ────────────────────────────────────────────────────────
        tk.Frame(root, bg=SEP, height=1).pack(fill="x", padx=18, pady=(4, 4))

        # ── Playlist manager ─────────────────────────────────────────────────
        pl_hdr = tk.Frame(root, bg=BG)
        pl_hdr.pack(fill="x", padx=18, pady=(0, 2))
        tk.Label(pl_hdr, text="📂 Playlists", bg=BG, fg=WHITE,
                 font=get_font(10, "bold")).pack(side="left")
        self._make_btn(pl_hdr, "+ New", self._create_playlist, ACCENT, pad=6).pack(side="right")

        pl_mid = tk.Frame(root, bg=BG)
        pl_mid.pack(fill="x", padx=18, pady=(0, 2))

        # Playlist selector dropdown
        self.pl_var = tk.StringVar(value="— select playlist —")
        self.pl_menu_btn = tk.Menubutton(pl_mid, textvariable=self.pl_var,
                                         bg=CARD, fg=WHITE, relief="flat",
                                         font=get_font(9), cursor="hand2",
                                         indicatoron=True, bd=0,
                                         activebackground=ACCENT,
                                         activeforeground=WHITE)
        self.pl_menu_btn.pack(side="left", fill="x", expand=True, ipady=4, padx=(0,4))
        self.pl_menu = tk.Menu(self.pl_menu_btn, tearoff=0, bg=CARD, fg=WHITE,
                               activebackground=ACCENT, activeforeground=WHITE)
        self.pl_menu_btn.config(menu=self.pl_menu)
        self._refresh_playlist_menu()

        self._make_btn(pl_mid, "Load", self._load_playlist, BLUE, pad=8).pack(side="left")

        # Playlist track listbox
        pl_frame = tk.Frame(root, bg=CARD2, bd=0)
        pl_frame.pack(fill="x", padx=18, pady=(0, 2))
        pl_scroll = tk.Scrollbar(pl_frame, bg=CARD2, troughcolor=BG,
                                 relief="flat", bd=0)
        pl_scroll.pack(side="right", fill="y")
        self.pl_lb = tk.Listbox(pl_frame, height=4, bg=CARD2, fg=WHITE,
                                selectbackground=ACCENT, selectforeground=WHITE,
                                activestyle="none", relief="flat",
                                font=get_font(8), borderwidth=0,
                                highlightthickness=0,
                                yscrollcommand=pl_scroll.set,
                                cursor="hand2")
        self.pl_lb.pack(fill="x", expand=True)
        pl_scroll.config(command=self.pl_lb.yview)
        self.pl_lb.bind("<Double-Button-1>", self._play_from_playlist)

        pl_btns = tk.Frame(root, bg=BG)
        pl_btns.pack(fill="x", padx=18, pady=(0, 4))
        self._make_btn(pl_btns, "▶ Play All",  self._queue_all_playlist, GREEN, pad=6).pack(side="left", padx=(0,3))
        self._make_btn(pl_btns, "✕ Remove",    self._pl_remove_track,   RED,   pad=6).pack(side="left", padx=(0,3))
        self._make_btn(pl_btns, "💾 Save",      self._save_current_pl,   ACCENT,pad=6).pack(side="left", padx=(0,3))
        self._make_btn(pl_btns, "🗑 Delete PL", self._delete_playlist,   MUTED, pad=6).pack(side="left")

    # ══════════════════════════════════════════════════════════════════════════
    # WIDGET HELPERS
    # ══════════════════════════════════════════════════════════════════════════
    def _make_btn(self, parent, text, cmd, color, pad=10):
        btn = tk.Button(parent, text=text, command=cmd,
                        bg=color, fg=WHITE, relief="flat",
                        font=get_font(9, "bold"), cursor="hand2",
                        padx=pad, pady=4, bd=0)
        btn.bind("<Enter>", lambda e, b=btn, c=color: b.config(bg=self._lighten(c)))
        btn.bind("<Leave>", lambda e, b=btn, c=color: b.config(bg=c))
        return btn

    def _make_icon_btn(self, parent, icon, cmd, color=WHITE):
        btn = tk.Button(parent, text=icon, command=cmd,
                        bg=BG, fg=color, relief="flat",
                        font=get_font(14), cursor="hand2",
                        bd=0, padx=6, pady=2)
        btn.bind("<Enter>", lambda e, b=btn: b.config(fg=ACCENT))
        btn.bind("<Leave>", lambda e, b=btn, c=color: b.config(fg=c))
        return btn

    @staticmethod
    def _lighten(hex_color: str) -> str:
        h = hex_color.lstrip("#")
        r, g, b = (int(h[i:i+2], 16) for i in (0, 2, 4))
        return f"#{min(255,r+30):02x}{min(255,g+30):02x}{min(255,b+30):02x}"

    # ══════════════════════════════════════════════════════════════════════════
    # TIMER DRAWING
    # ══════════════════════════════════════════════════════════════════════════
    def _draw_timer_ring(self):
        c = self.canvas
        c.delete("all")
        cx, cy, r = 115, 115, 95
        c.create_oval(cx-r, cy-r, cx+r, cy+r, outline=CARD, width=12)
        total = self._total_secs()
        fraction = (self.remaining_secs / total) if total > 0 else 1.0
        extent = -360 * fraction
        ring_color = BLUE if self.is_break else GREEN
        if fraction > 0.001:
            c.create_arc(cx-r, cy-r, cx+r, cy+r,
                         start=90, extent=extent,
                         outline=ring_color, width=12, style="arc")
        mins, secs = divmod(max(0, self.remaining_secs), 60)
        c.create_text(cx, cy-10, text=f"{mins:02d}:{secs:02d}",
                      fill=WHITE, font=get_font(32, "bold"))
        c.create_text(cx, cy+24, text="Break 🌿" if self.is_break else "Focus 🎯",
                      fill=MUTED, font=get_font(10))

    # ══════════════════════════════════════════════════════════════════════════
    # TIMER LOGIC
    # ══════════════════════════════════════════════════════════════════════════
    def _total_secs(self) -> int:
        if self.is_long_break:  return self.long_min.get() * 60
        if self.is_break:       return self.short_min.get() * 60
        return self.work_min.get() * 60

    def _session_text(self) -> str:
        return f"Session {self.session_num} of {self.total_sessions}"

    def _start_timer(self):
        if self.timer_paused:
            self.timer_paused = False
            self.timer_running = True
            self._tick()
        elif not self.timer_running:
            self.timer_running = True
            self.timer_paused = False
            self._tick()

    def _pause_timer(self):
        if self.timer_running:
            self.timer_running = False
            self.timer_paused = True
            if self._timer_after_id:
                self.root.after_cancel(self._timer_after_id)

    def _reset_timer(self):
        self.timer_running = False
        self.timer_paused = False
        if self._timer_after_id:
            self.root.after_cancel(self._timer_after_id)
        self.is_break = False
        self.is_long_break = False
        self.session_num = 1
        self.remaining_secs = self.work_min.get() * 60
        self.session_lbl.config(text=self._session_text())
        self._draw_timer_ring()
        self._update_tray_tooltip()

    def _tick(self):
        if not self.timer_running:
            return
        if self.remaining_secs <= 0:
            self._on_timer_end()
            return
        self.remaining_secs -= 1
        self._draw_timer_ring()
        self._update_tray_tooltip()
        self._timer_after_id = self.root.after(1000, self._tick)

    def _on_timer_end(self):
        self.timer_running = False
        self._play_beep()
        if not self.is_break:
            if self.session_num % self.total_sessions == 0:
                self.is_long_break = True
            else:
                self.is_long_break = False
            self.is_break = True
            self.remaining_secs = self._total_secs()
            self._show_standup_popup()
        else:
            self.is_break = False
            self.is_long_break = False
            self.session_num = (self.session_num % self.total_sessions) + 1
            self.remaining_secs = self.work_min.get() * 60
        self.session_lbl.config(text=self._session_text())
        self._draw_timer_ring()

    def _on_duration_change(self):
        if not self.timer_running and not self.timer_paused:
            self.remaining_secs = self._total_secs()
            self._draw_timer_ring()

    # ══════════════════════════════════════════════════════════════════════════
    # BEEP
    # ══════════════════════════════════════════════════════════════════════════
    def _play_beep(self):
        if not PYGAME_OK or not self._beep_raw:
            return
        try:
            pygame.mixer.Sound(buffer=self._beep_raw).play()
        except Exception:
            pass

    # ══════════════════════════════════════════════════════════════════════════
    # STAND-UP POPUP
    # ══════════════════════════════════════════════════════════════════════════
    def _show_standup_popup(self):
        tip = STRETCH_TIPS[self._tip_index % len(STRETCH_TIPS)]
        self._tip_index += 1
        popup = tk.Toplevel(self.root)
        popup.title("Stand Up!")
        popup.resizable(False, False)
        popup.configure(bg=CARD)
        popup.attributes("-topmost", True)
        popup.protocol("WM_DELETE_WINDOW", lambda: None)
        pw, ph = 360, 260
        sw, sh = popup.winfo_screenwidth(), popup.winfo_screenheight()
        popup.geometry(f"{pw}x{ph}+{(sw-pw)//2}+{(sh-ph)//2}")
        tk.Label(popup, text="🧍 Time to Stand Up!", bg=CARD, fg=ACCENT,
                 font=get_font(16, "bold")).pack(pady=(30, 10))
        tk.Label(popup, text=tip, bg=CARD, fg=WHITE, font=get_font(11),
                 wraplength=300, justify="center").pack(pady=(0, 20))
        def _close():
            popup.destroy()
            self.timer_running = True
            self._tick()
        self._make_btn(popup, "I'm standing! ✅", _close, GREEN, pad=20).pack(pady=10)

    # ══════════════════════════════════════════════════════════════════════════
    # YOUTUBE / SEARCH
    # ══════════════════════════════════════════════════════════════════════════
    def _init_yt_client(self):
        if not YT_API_OK or not self.api_key:
            return
        try:
            self.yt_client = yt_build('youtube', 'v3', developerKey=self.api_key)
        except Exception as exc:
            self._set_status(f"API Error: {exc}", error=True)

    def _do_search(self):
        query = self.search_var.get().strip()
        if not query:
            return
        if not self.yt_client:
            self._set_status("API Error: check your key", error=True)
            return
        self._set_status("Searching…")
        self.listbox.delete(0, "end")
        self.search_results.clear()
        self.current_index = -1
        try:
            resp = self.yt_client.search().list(
                part="snippet", q=query, type="video",
                videoCategoryId="10", maxResults=10
            ).execute()
            items = resp.get("items", [])
            if not items:
                self._set_status("No results found")
                return
            for item in items:
                vid   = item["id"]["videoId"]
                title = item["snippet"]["title"]
                short = title[:58] + ("…" if len(title) > 58 else "")
                self.listbox.insert("end", f"  {short}")
                self.search_results.append({"id": vid, "title": title})
            self._set_status(f"{len(items)} results found — click a song then ▶ Play")
            self._save_session()
        except Exception as exc:
            self._set_status(f"API Error: {exc}", error=True)

    def _on_song_select(self, _event=None):
        """Highlight the clicked song — do NOT auto-play."""
        sel = self.listbox.curselection()
        if not sel:
            return
        self.current_index = sel[0]
        self._playing_from_queue = False
        track = self.search_results[self.current_index]
        self._set_status(f"Selected: {track['title'][:50]} — click ▶ Play to start")

    def _play_selected_result(self):
        """Play the currently highlighted search result."""
        if self.current_index < 0 or self.current_index >= len(self.search_results):
            self._set_status("Select a song first")
            return
        self._playing_from_queue = False
        self._load_and_play(self.search_results[self.current_index])

    def _load_and_play(self, track: dict):
        self._set_status("Loading…")
        self._update_now_playing("⏳ " + track["title"])
        self._track_loaded = False
        self._load_thread = threading.Thread(
            target=self._extract_and_play,
            args=(track,),
            daemon=True
        )
        self._load_thread.start()

    def _find_cached_audio(self, track_id: str) -> str | None:
        """Check if audio for this track already exists in temp directory."""
        tmp_dir = tempfile.gettempdir()
        base = os.path.join(tmp_dir, f"lyreaura_{track_id}")
        for ext in (".mp3", ".m4a", ".ogg", ".webm", ".opus", ".wav"):
            path = base + ext
            if os.path.exists(path) and os.path.getsize(path) > 1000:
                return path
        return None

    def _extract_and_play(self, track: dict):
        if not YTDLP_OK:
            self.root.after(0, lambda: self._set_status("yt-dlp not installed", error=True))
            return
        url = f"https://www.youtube.com/watch?v={track['id']}"
        tmp_dir = tempfile.gettempdir()
        tmp_tmpl  = os.path.join(tmp_dir, f"lyreaura_{track['id']}.%(ext)s")
        expected_mp3 = os.path.join(tmp_dir, f"lyreaura_{track['id']}.mp3")

        # ── Cache check: skip download if file already exists ──────────────
        cached = self._find_cached_audio(track['id'])
        if cached:
            self.root.after(0, lambda: self._set_status("Playing from cache ⚡"))
            # Probe duration for cached files if not already known
            if not track.get("duration"):
                try:
                    snd = pygame.mixer.Sound(cached)
                    track["duration"] = snd.get_length()
                    del snd
                except Exception:
                    pass
            self.root.after(0, lambda p=cached, t=track: self._play_audio(p, t))
            return

        import shutil
        ffmpeg_bin = shutil.which("ffmpeg") or r"C:\Program Files\ffmpeg\bin\ffmpeg.exe"
        has_ffmpeg = bool(shutil.which("ffmpeg")) or os.path.exists(ffmpeg_bin)

        # ── Progress hook: show download % in status bar ───────────────────
        def _progress_hook(d):
            if d.get("status") == "downloading":
                pct = d.get("_percent_str", "").strip()
                speed = d.get("_speed_str", "").strip()
                eta = d.get("_eta_str", "").strip()
                msg = f"Downloading… {pct}"
                if speed:
                    msg += f"  ↓ {speed}"
                if eta:
                    msg += f"  ETA {eta}"
                self.root.after(0, lambda m=msg: self._set_status(m))
            elif d.get("status") == "finished":
                self.root.after(0, lambda: self._set_status("Converting audio…"))

        # ── Probe duration to adjust quality for long songs ────────────────
        audio_quality = "192"
        try:
            with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True}) as probe:
                info_probe = probe.extract_info(url, download=False)
                duration = info_probe.get("duration", 0) or 0
                track["duration"] = duration  # pass to _play_audio for seek bar
                if duration > 1200:  # > 20 minutes
                    audio_quality = "128"
                    self.root.after(0, lambda d=duration: self._set_status(
                        f"Long track ({d // 60}m) — using optimised download…"))
        except Exception:
            pass

        opts = {
            "format": "bestaudio/best",
            "quiet": True,
            "no_warnings": True,
            "outtmpl": tmp_tmpl,
            "progress_hooks": [_progress_hook],
            "socket_timeout": 30,
            "retries": 3,
            "fragment_retries": 5,
            "http_chunk_size": 10485760,  # 10 MB chunks for reliability
        }
        if has_ffmpeg:
            opts["postprocessors"] = [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": audio_quality,
            }]
            if not shutil.which("ffmpeg"):
                opts["ffmpeg_location"] = os.path.dirname(ffmpeg_bin)

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                out_path = ydl.prepare_filename(info)

            if has_ffmpeg and os.path.exists(expected_mp3):
                out_path = expected_mp3
            elif not os.path.exists(out_path):
                base = os.path.splitext(out_path)[0]
                for ext in (".mp3", ".m4a", ".ogg", ".webm", ".opus"):
                    if os.path.exists(base + ext):
                        out_path = base + ext
                        break

            if not os.path.exists(out_path):
                raise FileNotFoundError("Downloaded audio file not found")

            self.root.after(0, lambda p=out_path, t=track: self._play_audio(p, t))
        except Exception:
            self.root.after(0, lambda: self._set_status("Could not load track, try another", error=True))
            self.root.after(0, lambda: self._update_now_playing("❌ Could not load track"))

    def _play_audio(self, file_path: str, track: dict):
        if not PYGAME_OK:
            self._set_status("pygame not available", error=True)
            return
        try:
            pygame.mixer.music.load(file_path)
            pygame.mixer.music.play()
            self.is_playing = True
            self._track_loaded = True
            self._current_file_path = file_path

            # Reset seek bar state
            self._elapsed_before_pause = 0.0
            self._playback_start = time.time()

            # Get duration from track dict (set by _extract_and_play)
            dur = track.get("duration", 0) or 0
            if dur <= 0:
                # Fallback: try to get duration from the audio file via pygame
                try:
                    snd = pygame.mixer.Sound(file_path)
                    dur = snd.get_length()
                    del snd
                except Exception:
                    dur = 0
            self._track_duration = float(dur)

            # Update seek bar range and labels
            if self._track_duration > 0:
                self.seek_slider.config(to=int(self._track_duration))
                self.seek_slider.set(0)
                self.seek_total_lbl.config(text=self._fmt_time(self._track_duration))
            else:
                self.seek_slider.config(to=100)
                self.seek_slider.set(0)
                self.seek_total_lbl.config(text="--:--")
            self.seek_elapsed_lbl.config(text="0:00")

            # Start the seek bar updater
            self._start_seek_updater()

            self._update_now_playing("♪ " + track["title"])
            self._set_status("")
        except Exception as exc:
            self._set_status(f"Playback error: {exc}", error=True)
            self._update_now_playing("❌ Playback error")

    def _toggle_play(self):
        if not PYGAME_OK:
            return
        if self.is_playing:
            # Pausing — accumulate elapsed time
            self._elapsed_before_pause += time.time() - self._playback_start
            pygame.mixer.music.pause()
            self.is_playing = False
        elif self._track_loaded:
            # Resuming — restart the clock
            self._playback_start = time.time()
            pygame.mixer.music.unpause()
            self.is_playing = True
            self._start_seek_updater()
        else:
            # Nothing loaded yet — play the selected/first track
            self._play_selected_result()

    # ══════════════════════════════════════════════════════════════════════════
    # SEEK / PROGRESS BAR
    # ══════════════════════════════════════════════════════════════════════════
    @staticmethod
    def _fmt_time(secs: float) -> str:
        """Format seconds into m:ss or h:mm:ss."""
        s = max(0, int(secs))
        if s >= 3600:
            h, rem = divmod(s, 3600)
            m, sec = divmod(rem, 60)
            return f"{h}:{m:02d}:{sec:02d}"
        m, sec = divmod(s, 60)
        return f"{m}:{sec:02d}"

    def _start_seek_updater(self):
        """Begin/restart the periodic seek bar updater."""
        if self._seek_after_id:
            self.root.after_cancel(self._seek_after_id)
            self._seek_after_id = None
        self._update_seek_bar()

    def _update_seek_bar(self):
        """Periodically update the seek slider and elapsed time label."""
        if self.is_playing and not self._seeking:
            elapsed = self._elapsed_before_pause + (time.time() - self._playback_start)
            elapsed = min(elapsed, self._track_duration) if self._track_duration > 0 else elapsed
            self.seek_elapsed_lbl.config(text=self._fmt_time(elapsed))
            if self._track_duration > 0:
                self.seek_slider.set(int(elapsed))
        if self.is_playing:
            self._seek_after_id = self.root.after(500, self._update_seek_bar)
        else:
            self._seek_after_id = None

    def _on_seek_press(self, _event=None):
        """User started dragging the seek slider."""
        self._seeking = True

    def _on_seek_release(self, _event=None):
        """User released the seek slider — perform the actual seek."""
        if not PYGAME_OK or not self._track_loaded:
            self._seeking = False
            return
        target_sec = self.seek_slider.get()
        try:
            # For MP3 files, set_pos seeks to absolute seconds
            pygame.mixer.music.play(start=target_sec)
            if not self.is_playing:
                pygame.mixer.music.pause()
        except Exception:
            try:
                pygame.mixer.music.set_pos(target_sec)
            except Exception:
                pass
        self._elapsed_before_pause = float(target_sec)
        self._playback_start = time.time()
        self.seek_elapsed_lbl.config(text=self._fmt_time(target_sec))
        self._seeking = False
        if self.is_playing:
            self._start_seek_updater()

    def _on_seek_drag(self, val):
        """Live update the elapsed label while dragging (no actual seek yet)."""
        if self._seeking:
            self.seek_elapsed_lbl.config(text=self._fmt_time(float(val)))

    def _prev_track(self):
        if self._playing_from_queue:
            return
        if not self.search_results:
            return
        idx = (self.current_index - 1) % len(self.search_results)
        self.current_index = idx
        self._load_and_play(self.search_results[idx])

    def _next_track(self):
        # Queue has priority
        if self.queue:
            track = self.queue.pop(0)
            self._playing_from_queue = True
            self._refresh_queue_lb()
            self._load_and_play(track)
            return
        if not self.search_results:
            return
        self._playing_from_queue = False
        if self.shuffle_on:
            idx = random.randint(0, len(self.search_results) - 1)
        else:
            idx = (self.current_index + 1) % len(self.search_results)
        self.current_index = idx
        self._load_and_play(self.search_results[idx])

    def _toggle_shuffle(self):
        self.shuffle_on = not self.shuffle_on
        self.shuf_btn.config(fg=ACCENT if self.shuffle_on else MUTED)

    # ══════════════════════════════════════════════════════════════════════════
    # VOLUME
    # ══════════════════════════════════════════════════════════════════════════
    def _on_volume(self, val):
        v = int(val)
        self.vol_pct_lbl.config(text=f"{v}%")
        if self._muted and v > 0:
            self._muted = False
            self.mute_btn.config(text="🔊")
        if PYGAME_OK:
            try:
                pygame.mixer.music.set_volume(v / 100)
            except Exception:
                pass

    def _toggle_mute(self):
        if self._muted:
            # Unmute
            self._muted = False
            self.mute_btn.config(text="🔊")
            self.vol_slider.set(self._vol_before_mute)
            if PYGAME_OK:
                pygame.mixer.music.set_volume(self._vol_before_mute / 100)
        else:
            # Mute
            self._muted = True
            self._vol_before_mute = self.vol_slider.get()
            self.mute_btn.config(text="🔇")
            self.vol_slider.set(0)
            if PYGAME_OK:
                pygame.mixer.music.set_volume(0)

    # ══════════════════════════════════════════════════════════════════════════
    # QUEUE
    # ══════════════════════════════════════════════════════════════════════════
    def _add_selected_to_queue(self):
        sel = self.listbox.curselection()
        if not sel:
            self._set_status("Select a track from search results first")
            return
        track = self.search_results[sel[0]]
        self.queue.append(track)
        self._refresh_queue_lb()
        self._save_session()
        self._set_status(f"Added to queue: {track['title'][:40]}")

    def _refresh_queue_lb(self):
        self.queue_lb.delete(0, "end")
        for i, t in enumerate(self.queue):
            self.queue_lb.insert("end", f"  {i+1}. {t['title'][:50]}")

    def _play_from_queue(self, _event=None):
        sel = self.queue_lb.curselection()
        if not sel:
            return
        idx = sel[0]
        track = self.queue.pop(idx)
        self._playing_from_queue = True
        self._refresh_queue_lb()
        self._save_session()
        self._load_and_play(track)

    def _queue_move_up(self):
        sel = self.queue_lb.curselection()
        if not sel or sel[0] == 0:
            return
        idx = sel[0]
        self.queue[idx-1], self.queue[idx] = self.queue[idx], self.queue[idx-1]
        self._refresh_queue_lb()
        self.queue_lb.selection_set(idx-1)
        self._save_session()

    def _queue_move_down(self):
        sel = self.queue_lb.curselection()
        if not sel or sel[0] >= len(self.queue)-1:
            return
        idx = sel[0]
        self.queue[idx+1], self.queue[idx] = self.queue[idx], self.queue[idx+1]
        self._refresh_queue_lb()
        self.queue_lb.selection_set(idx+1)
        self._save_session()

    def _queue_remove(self):
        sel = self.queue_lb.curselection()
        if not sel:
            return
        idx = sel[0]
        self.queue.pop(idx)
        self._refresh_queue_lb()
        self._save_session()

    def _clear_queue(self):
        self.queue.clear()
        self._refresh_queue_lb()
        self._save_session()

    def _monitor_queue(self):
        """Auto-advance: when pygame finishes, play next from queue."""
        if PYGAME_OK:
            try:
                if self.is_playing and not pygame.mixer.music.get_busy():
                    self.is_playing = False
                    if self.queue:
                        self._next_track()
            except Exception:
                pass
        self.root.after(1500, self._monitor_queue)

    # ══════════════════════════════════════════════════════════════════════════
    # PLAYLIST MANAGER
    # ══════════════════════════════════════════════════════════════════════════
    def _refresh_playlist_menu(self):
        self.pl_menu.delete(0, "end")
        for name in self.playlists:
            self.pl_menu.add_command(
                label=name,
                command=lambda n=name: self._select_playlist(n)
            )
        if not self.playlists:
            self.pl_menu.add_command(label="(no playlists yet)", state="disabled")
        # Also update the dropdown label if active playlist was deleted
        if self.active_playlist_name and self.active_playlist_name not in self.playlists:
            self.pl_var.set("— select playlist —")
            self.active_playlist_name = ""

    def _select_playlist(self, name: str):
        self.pl_var.set(name)
        self.active_playlist_name = name
        self._refresh_pl_lb()

    def _refresh_pl_lb(self):
        self.pl_lb.delete(0, "end")
        name = self.active_playlist_name
        if name and name in self.playlists:
            for i, t in enumerate(self.playlists[name]):
                self.pl_lb.insert("end", f"  {i+1}. {t['title'][:50]}")

    def _create_playlist(self):
        """Custom inline dialog — avoids simpledialog visibility issues."""
        dlg = tk.Toplevel(self.root)
        dlg.title("New Playlist")
        dlg.resizable(False, False)
        dlg.configure(bg=CARD)
        dlg.attributes("-topmost", True)
        dlg.grab_set()  # modal
        pw, ph = 300, 140
        sw, sh = dlg.winfo_screenwidth(), dlg.winfo_screenheight()
        dlg.geometry(f"{pw}x{ph}+{(sw-pw)//2}+{(sh-ph)//2}")

        tk.Label(dlg, text="📂 New Playlist Name", bg=CARD, fg=ACCENT,
                 font=get_font(11, "bold")).pack(pady=(16, 8))
        name_var = tk.StringVar()
        entry = tk.Entry(dlg, textvariable=name_var, width=28,
                         bg=BG, fg=WHITE, insertbackground=WHITE,
                         relief="flat", font=get_font(10))
        entry.pack(ipady=5, padx=20)
        entry.focus_set()

        def _confirm(*_):
            name = name_var.get().strip()
            if not name:
                return
            if name in self.playlists:
                tk.Label(dlg, text="Name already exists!",
                         bg=CARD, fg=RED, font=get_font(8)).pack()
                return
            self.playlists[name] = []
            self._save_playlists()
            dlg.destroy()
            self._refresh_playlist_menu()
            self._select_playlist(name)
            self._set_status(f'Playlist "{name}" created ✔')

        entry.bind("<Return>", _confirm)
        self._make_btn(dlg, "Create", _confirm, ACCENT, pad=14).pack(pady=10)
        dlg.wait_window()

    def _load_playlist(self):
        """Load selected playlist tracks into search results list (no auto-play)."""
        name = self.active_playlist_name
        if not name or name not in self.playlists:
            self._set_status("Select a playlist first")
            return
        tracks = self.playlists[name]
        if not tracks:
            self._set_status("Playlist is empty")
            return
        self.search_results = list(tracks)
        self.listbox.delete(0, "end")
        for t in tracks:
            short = t["title"][:58] + ("…" if len(t["title"]) > 58 else "")
            self.listbox.insert("end", f"  {short}")
        self.current_index = 0
        self._playing_from_queue = False
        self._save_session()
        self._set_status(f"Loaded playlist: {name} — click ▶ Play to start")

    def _add_selected_to_playlist(self):
        sel = self.listbox.curselection()
        if not sel:
            self._set_status("Select a track from search results first")
            return
        if not self.playlists:
            self._set_status("Create a playlist first (📂 Playlists → + New)")
            return
        track = self.search_results[sel[0]]
        name = self.active_playlist_name
        # If no active playlist and only one exists, auto-select it
        if not name or name not in self.playlists:
            names = list(self.playlists.keys())
            if len(names) == 1:
                name = names[0]
            else:
                # Show picker dialog
                name = self._pick_playlist_dialog()
                if not name:
                    return
        existing_ids = {t["id"] for t in self.playlists[name]}
        if track["id"] in existing_ids:
            self._set_status("Track already in playlist")
            return
        self.playlists[name].append(track)
        self._save_playlists()
        self._set_status(f'Added to "{name}": {track["title"][:35]}')
        if self.active_playlist_name == name:
            self._refresh_pl_lb()

    def _pick_playlist_dialog(self) -> str:
        """Show a small dialog letting the user pick a playlist by name."""
        result = [""]
        dlg = tk.Toplevel(self.root)
        dlg.title("Choose Playlist")
        dlg.resizable(False, False)
        dlg.configure(bg=CARD)
        dlg.attributes("-topmost", True)
        dlg.grab_set()
        pw, ph = 260, 180
        sw, sh = dlg.winfo_screenwidth(), dlg.winfo_screenheight()
        dlg.geometry(f"{pw}x{ph}+{(sw-pw)//2}+{(sh-ph)//2}")
        tk.Label(dlg, text="Add to which playlist?", bg=CARD, fg=ACCENT,
                 font=get_font(10, "bold")).pack(pady=(12, 6))
        lb = tk.Listbox(dlg, bg=BG, fg=WHITE, selectbackground=ACCENT,
                        selectforeground=WHITE, activestyle="none",
                        relief="flat", font=get_font(9),
                        highlightthickness=0, height=5)
        for n in self.playlists:
            lb.insert("end", f"  {n}")
        lb.pack(fill="x", padx=12)
        def _confirm(*_):
            s = lb.curselection()
            if s:
                result[0] = list(self.playlists.keys())[s[0]]
            dlg.destroy()
        lb.bind("<Double-Button-1>", _confirm)
        self._make_btn(dlg, "Select", _confirm, ACCENT, pad=12).pack(pady=8)
        dlg.wait_window()
        return result[0]

    def _pl_remove_track(self):
        sel = self.pl_lb.curselection()
        if not sel:
            return
        name = self.active_playlist_name
        if not name or name not in self.playlists:
            return
        self.playlists[name].pop(sel[0])
        self._save_playlists()
        self._refresh_pl_lb()

    def _save_current_pl(self):
        name = self.active_playlist_name
        if not name:
            self._set_status("No playlist selected")
            return
        self._save_playlists()
        self._set_status(f"Playlist \"{name}\" saved ✔")

    def _queue_all_playlist(self):
        name = self.active_playlist_name
        if not name or name not in self.playlists:
            self._set_status("Select a playlist first")
            return
        tracks = self.playlists[name]
        if not tracks:
            self._set_status("Playlist is empty")
            return
        self.queue.extend(tracks)
        self._refresh_queue_lb()
        self._save_session()
        self._set_status(f"Queued {len(tracks)} tracks from \"{name}\"")

    def _delete_playlist(self):
        name = self.active_playlist_name
        if not name or name not in self.playlists:
            self._set_status("Select a playlist first")
            return
        if not messagebox.askyesno("Delete Playlist",
                                   f'Delete playlist "{name}"?',
                                   parent=self.root):
            return
        del self.playlists[name]
        self._save_playlists()
        self.active_playlist_name = ""
        self.pl_var.set("— select playlist —")
        self.pl_lb.delete(0, "end")
        self._refresh_playlist_menu()

    def _play_from_playlist(self, _event=None):
        sel = self.pl_lb.curselection()
        if not sel:
            return
        name = self.active_playlist_name
        if not name or name not in self.playlists:
            return
        idx = sel[0]
        track = self.playlists[name][idx]
        self._playing_from_queue = False
        self._load_and_play(track)

    # ══════════════════════════════════════════════════════════════════════════
    # NOW PLAYING SCROLLER
    # ══════════════════════════════════════════════════════════════════════════
    def _update_now_playing(self, text: str):
        self._np_full_text = text
        self._np_scroll_pos = 0

    def _scroll_now_playing(self):
        try:
            full = getattr(self, "_np_full_text", "♪  Nothing playing")
            max_chars = 46
            if len(full) > max_chars:
                padded = full + "   "
                pos = self._np_scroll_pos % len(padded)
                display = (padded + padded)[pos:pos + max_chars]
                self._np_scroll_pos += 1
            else:
                display = full
            self.np_lbl.config(text=display)
        except Exception:
            pass
        self._np_scroll_id = self.root.after(200, self._scroll_now_playing)

    # ══════════════════════════════════════════════════════════════════════════
    # STATUS LABEL
    # ══════════════════════════════════════════════════════════════════════════
    def _set_status(self, msg: str, error: bool = False):
        self.status_lbl.config(text=msg, fg=RED if error else MUTED)

    # ══════════════════════════════════════════════════════════════════════════
    # API KEY PROMPT
    # ══════════════════════════════════════════════════════════════════════════
    def _prompt_api_key(self):
        popup = tk.Toplevel(self.root)
        popup.title("Enter YouTube API Key")
        popup.resizable(False, False)
        popup.configure(bg=CARD)
        popup.attributes("-topmost", True)
        popup.protocol("WM_DELETE_WINDOW", lambda: None)
        pw, ph = 380, 200
        sw, sh = popup.winfo_screenwidth(), popup.winfo_screenheight()
        popup.geometry(f"{pw}x{ph}+{(sw-pw)//2}+{(sh-ph)//2}")
        tk.Label(popup, text="🔑 YouTube API Key Required",
                 bg=CARD, fg=ACCENT, font=get_font(13, "bold")).pack(pady=(20, 6))
        tk.Label(popup, text="Get one free at Google Cloud Console.\nPaste your YOUTUBE_API_KEY below:",
                 bg=CARD, fg=WHITE, font=get_font(9), justify="center").pack()
        key_var = tk.StringVar()
        entry = tk.Entry(popup, textvariable=key_var, width=42,
                         bg=BG, fg=WHITE, insertbackground=WHITE,
                         relief="flat", font=get_font(9), show="")
        entry.pack(pady=8, ipady=5, padx=20)
        def _save():
            key = key_var.get().strip()
            if not key:
                return
            self.api_key = key
            os.environ["YOUTUBE_API_KEY"] = key
            try:
                with open(ENV_FILE, "a") as f:
                    f.write(f"\nYOUTUBE_API_KEY={key}\n")
            except Exception:
                pass
            popup.destroy()
            self._init_yt_client()
        self._make_btn(popup, "Save & Continue", _save, ACCENT, pad=16).pack(pady=6)

    # ══════════════════════════════════════════════════════════════════════════
    # SYSTEM TRAY
    # ══════════════════════════════════════════════════════════════════════════
    def _make_tray_image(self) -> "Image.Image":
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse((4, 4, 60, 60), fill=(198, 120, 221, 255))
        return img

    def _setup_tray(self):
        img = self._make_tray_image()
        menu = pystray.Menu(
            pystray.MenuItem("Open LyreAura", self._tray_open),
            pystray.MenuItem("Quit", self._tray_quit),
        )
        self._tray_icon = pystray.Icon("LyreAura", img, "LyreAura", menu)
        threading.Thread(target=self._tray_icon.run, daemon=True).start()

    def _tray_open(self, *_):
        self.root.after(0, self.root.deiconify)

    def _tray_quit(self, *_):
        if self._tray_icon:
            self._tray_icon.stop()
        self.root.after(0, self.root.destroy)

    def _on_close(self):
        self.root.withdraw()

    def _update_tray_tooltip(self):
        if not TRAY_OK or not self._tray_icon:
            return
        mins, secs = divmod(max(0, self.remaining_secs), 60)
        self._tray_icon.title = f"LyreAura — {mins:02d}:{secs:02d} remaining"


# ── Entry Point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    root.mainloop()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TikTok + Instagram story & Reels downloader -> upload to MEGA -> delete local file
"""

import os
import json
import time
import requests
from mega import Mega  # Vyžaduje: pip install mega.py
from datetime import datetime
import pytz

# ---------- CONFIG ----------
CONFIG_FILE = "config_mega.json"

if not os.path.exists(CONFIG_FILE):
    print("Chybí config.json.")
    exit(1)

with open(CONFIG_FILE, "r", encoding="utf-8") as f:
    cfg = json.load(f)

MEGA_CFG = cfg.get("mega", {})
BARK_URL = cfg.get("bark_url", "")
TIKTOK_CFG = cfg.get("tiktok", {})
IG_CFG = cfg.get("instagram", {})
SCHEDULE_TIMES = cfg.get("prague_schedule_times", ["09:00", "21:00"])
SAVE_FOLDER = cfg.get("save_folder", "downloaded_videos")

os.makedirs(SAVE_FOLDER, exist_ok=True)
TIKTOK_IDS_FILE = "downloaded_tiktok_ids.json"
IG_IDS_FILE = "downloaded_ig_ids.json"
IG_REELS_IDS_FILE = "downloaded_reels_ids.json"

def load_ids(path):
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump([], f)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_ids(path, ids):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(ids, f, indent=2, ensure_ascii=False)

# ---------- MEGA Funkce ----------
def upload_to_mega(local_file):
    """
    Přihlásí se k MEGA a nahraje soubor.
    """
    email = MEGA_CFG.get("email")
    password = MEGA_CFG.get("password")
    target_folder_name = MEGA_CFG.get("target_folder", "stories")

    if not (email and password):
        print("⚠️ MEGA config incomplete (email/password).")
        return False

    try:
        mega = Mega()
        m = mega.login(email, password)
        
        # Najít nebo vytvořit složku
        folder = m.find(target_folder_name)
        
        print(f"⬆️ Nahrávám na MEGA: {os.path.basename(local_file)}")
        if folder:
            m.upload(local_file, folder[0])
        else:
            # Pokud složka neexistuje, nahraje do rootu
            m.upload(local_file)
            
        print(f"✅ Nahráno na MEGA.")
        
        try:
            os.remove(local_file)
            print(f"🗑️ Lokální soubor smazán: {local_file}")
        except Exception as e:
            print("⚠️ Nepodařilo se smazat lokální soubor:", e)
        return True
    except Exception as e:
        print("❌ Chyba při uploadu na MEGA:", e)
    return False

# ---------- Bark notifikace ----------
def send_bark(message):
    if not BARK_URL:
        return
    try:
        requests.get(f"{BARK_URL}&body={requests.utils.quote(message)}", timeout=5)
        print("📱 Bark notifikace odeslána.")
    except Exception as e:
        print("⚠️ Bark notifikace selhala:", e)

# ---------- TikTok story fetch ----------
def fetch_tiktok_stories():
    print("\n=== Kontrola nových TikTok story ===")
    api_key = TIKTOK_CFG.get("api_key")
    api_host = TIKTOK_CFG.get("api_host", "tiktok-scraper7.p.rapidapi.com")
    user_ids = TIKTOK_CFG.get("user_ids", [])

    if not api_key or not user_ids:
        print("⚠️ TikTok config chybí.")
        return

    downloaded_ids = load_ids(TIKTOK_IDS_FILE)
    new_count = 0

    for uid in user_ids:
        url = "https://tiktok-scraper7.p.rapidapi.com/user/story"
        params = {"user_id": uid}
        headers = {"x-rapidapi-key": api_key, "x-rapidapi-host": api_host}
        try:
            r = requests.get(url, headers=headers, params=params, timeout=10)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            print("❌ Chyba TikTok API pro", uid, ":", e)
            continue

        videos = data.get("data", {}).get("videos", [])
        if not videos:
            continue

        for v in videos:
            vid = v.get("video_id")
            if vid in downloaded_ids:
                continue

            play = v.get("play")
            origin_cover = v.get("origin_cover")
            images = v.get("images", [])
            saved = False
            fname = ""

            # --- UPRAVENÁ LOGIKA DETEKCE ---
            # Zjistíme, zda jde o video nebo audio/obrázek na základě mime_type v URL
            is_video_content = False
            if play:
                if "mime_type=video_mp4" in play:
                    is_video_content = True
                elif play.endswith(".mp4"): # Fallback, pokud URL neobsahuje parametry
                    is_video_content = True
                # Pokud je tam mime_type=audio_mpeg, is_video_content zůstane False

            if is_video_content:
                fname = os.path.join(SAVE_FOLDER, f"{vid}.mp4")
                try:
                    rr = requests.get(play, stream=True, timeout=30)
                    with open(fname, "wb") as f:
                        for chunk in rr.iter_content(chunk_size=8192):
                            if chunk: f.write(chunk)
                    saved = True
                except: pass

            # Pokud se neuložilo jako video (buď selhalo, nebo to bylo audio_mpeg), zkusíme cover
            if not saved:
                # Prioritizujeme origin_cover (pro audio story), pak images (pro image slide story)
                image_url = origin_cover if origin_cover else (images[0] if images else None)
                if image_url:
                    fname = os.path.join(SAVE_FOLDER, f"{vid}.jpg")
                    try:
                        rr = requests.get(image_url, stream=True, timeout=30)
                        with open(fname, "wb") as f:
                            for chunk in rr.iter_content(chunk_size=8192):
                                if chunk: f.write(chunk)
                        saved = True
                    except: pass

            if saved:
                if upload_to_mega(fname):
                    downloaded_ids.append(vid)
                    new_count += 1

    save_ids(TIKTOK_IDS_FILE, downloaded_ids)
    if new_count > 0:
        send_bark(f"Bylo staženo {new_count} nových TikTok story 🎬")

# ---------- Instagram story fetch ----------
def fetch_instagram_stories():
    print("\n=== Kontrola nových Instagram story ===")
    api_key = IG_CFG.get("api_key")
    api_host = IG_CFG.get("api_host", "instagram-social-api.p.rapidapi.com")
    usernames = IG_CFG.get("usernames", [])

    if not api_key or not usernames: return

    downloaded_ids = load_ids(IG_IDS_FILE)
    new_count = 0

    for uname in usernames:
        url = "https://instagram-social-api.p.rapidapi.com/v1/stories"
        params = {"username_or_id_or_url": uname}
        headers = {"x-rapidapi-key": api_key, "x-rapidapi-host": api_host}
        try:
            r = requests.get(url, headers=headers, params=params, timeout=12)
            data = r.json()
        except: continue

        items = data.get("data", {}).get("items", [])
        for item in items:
            item_id = item.get("id") or item.get("fbid")
            if not item_id or item_id in downloaded_ids: continue

            saved = False
            if item.get("is_video") or item.get("media_format") == "video":
                video_url = item.get("video_url") or (item.get("video_versions") and item.get("video_versions")[0].get("url"))
                if video_url:
                    fname = os.path.join(SAVE_FOLDER, f"ig_{item_id}.mp4")
                    try:
                        rr = requests.get(video_url, stream=True, timeout=30)
                        with open(fname, "wb") as f:
                            for chunk in rr.iter_content(chunk_size=8192):
                                if chunk: f.write(chunk)
                        saved = True
                    except: pass
            else:
                image_url = item.get("thumbnail_url") or (item.get("image_versions", {}).get("items") and item.get("image_versions")["items"][0].get("url"))
                if image_url:
                    fname = os.path.join(SAVE_FOLDER, f"ig_{item_id}.jpg")
                    try:
                        rr = requests.get(image_url, stream=True, timeout=30)
                        with open(fname, "wb") as f:
                            for chunk in rr.iter_content(chunk_size=8192):
                                if chunk: f.write(chunk)
                        saved = True
                    except: pass

            if saved:
                if upload_to_mega(fname):
                    downloaded_ids.append(item_id)
                    new_count += 1

    save_ids(IG_IDS_FILE, downloaded_ids)
    if new_count > 0:
        send_bark(f"Bylo staženo {new_count} nových Instagram story 🎬")

# ---------- Instagram Reels fetch ----------
def fetch_instagram_reels():
    print("\n=== Kontrola nových Instagram Reels ===")
    api_key = IG_CFG.get("api_key")
    api_host = IG_CFG.get("api_host", "instagram-social-api.p.rapidapi.com")
    reels_usernames = IG_CFG.get("reels_usernames", [])

    if not api_key or not reels_usernames: return

    downloaded_ids = load_ids(IG_REELS_IDS_FILE)
    new_count = 0

    for uname in reels_usernames:
        url = "https://instagram-social-api.p.rapidapi.com/v1/reels"
        headers = {"x-rapidapi-key": api_key, "x-rapidapi-host": api_host}
        try:
            r = requests.get(url, headers=headers, params={"username_or_id_or_url": uname}, timeout=15)
            items = r.json().get("data", {}).get("items", [])
        except: continue

        for item in items:
            item_id = item.get("id")
            if not item_id or item_id in downloaded_ids: continue

            video_versions = item.get("video_versions", [])
            if not video_versions: continue

            best_version = sorted(video_versions, key=lambda x: x.get("height", 0), reverse=True)[0]
            video_url = best_version.get("url")

            if video_url:
                fname = os.path.join(SAVE_FOLDER, f"reel_{item_id}.mp4")
                try:
                    rr = requests.get(video_url, stream=True, timeout=60)
                    with open(fname, "wb") as f:
                        for chunk in rr.iter_content(chunk_size=8192):
                            if chunk: f.write(chunk)
                    
                    if upload_to_mega(fname):
                        downloaded_ids.append(item_id)
                        new_count += 1
                except: pass

    save_ids(IG_REELS_IDS_FILE, downloaded_ids)
    if new_count > 0:
        send_bark(f"Bylo staženo {new_count} nových Instagram Reels 🎥")

# ---------- Scheduler ----------
LAST_RUN_MINUTE = None

def run_checks():
    fetch_tiktok_stories()
    fetch_instagram_stories()
    fetch_instagram_reels()

print("=== START: jednorázová kontrola při spuštění ===")
run_checks()

tz = pytz.timezone("Europe/Prague")
while True:
    now_prague = datetime.now(tz)
    hm = now_prague.strftime("%H:%M")
    current_run_key = now_prague.strftime("%Y-%m-%d %H:%M")
    
    if hm in SCHEDULE_TIMES and LAST_RUN_MINUTE != current_run_key:
        print(f"\n🕒 Spouštím plánovanou kontrolu (Praha čas {hm})...")
        run_checks()
        LAST_RUN_MINUTE = current_run_key
    
    time.sleep(25)

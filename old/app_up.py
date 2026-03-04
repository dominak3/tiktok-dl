#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TikTok + Instagram story & Reels downloader -> upload to Dropbox (with token refresh) -> delete local file
Usage: uprav config.json s tvými klíči a username(s).
Requires: pip install requests dropbox pytz
"""

import os
import json
import time
import requests
import dropbox
from datetime import datetime
import pytz

# ---------- CONFIG (uprav soubor config.json) ----------
CONFIG_FILE = "config.json"

if not os.path.exists(CONFIG_FILE):
    print("Chybí config.json. Vytvoř ho podle příkladu.")
    exit(1)

with open(CONFIG_FILE, "r", encoding="utf-8") as f:
    cfg = json.load(f)

DROPBOX_CFG = cfg.get("dropbox", {})
BARK_URL = cfg.get("bark_url", "")
TIKTOK_CFG = cfg.get("tiktok", {})
IG_CFG = cfg.get("instagram", {})
SCHEDULE_TIMES = cfg.get("prague_schedule_times", ["09:00", "21:00"])
SAVE_FOLDER = cfg.get("save_folder", "downloaded_videos")

# ---------- Příprava složky a souborů s ID ----------
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

# ---------- Dropbox OAuth (refresh) ----------
def refresh_dropbox_access_token():
    app_key = DROPBOX_CFG.get("app_key")
    app_secret = DROPBOX_CFG.get("app_secret")
    refresh_token = DROPBOX_CFG.get("refresh_token")

    if not (app_key and app_secret and refresh_token):
        print("⚠️ Dropbox config incomplete (app_key/app_secret/refresh_token).")
        return None

    token_url = "https://api.dropbox.com/oauth2/token"
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token
    }
    try:
        r = requests.post(token_url, data=data, auth=(app_key, app_secret), timeout=10)
        r.raise_for_status()
        token_data = r.json()
        access_token = token_data.get("access_token")
        if access_token:
            return access_token
        else:
            print("❌ Nezískal jsem access_token z Dropboxu:", token_data)
    except Exception as e:
        print("❌ Chyba při refreshi Dropbox tokenu:", e)
    return None

def upload_to_dropbox(local_file, dropbox_path):
    access_token = refresh_dropbox_access_token()
    if not access_token:
        print("❌ Nelze získat access token pro Dropbox.")
        return False
    try:
        dbx = dropbox.Dropbox(access_token)
        with open(local_file, "rb") as f:
            data = f.read()
        dbx.files_upload(data, dropbox_path, mode=dropbox.files.WriteMode("overwrite"))
        print(f"✅ Nahráno na Dropbox: {dropbox_path}")
        try:
            os.remove(local_file)
            print(f"🗑️ Lokální soubor smazán: {local_file}")
        except Exception as e:
            print("⚠️ Nepodařilo se smazat lokální soubor:", e)
        return True
    except dropbox.exceptions.AuthError as e:
        print("❌ Dropbox AuthError:", e)
    except Exception as e:
        print("❌ Chyba při uploadu na Dropbox:", e)
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
            print("✅ TikTok: žádné story pro uid", uid)
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

            # Video
            if play and not play.endswith(".mp3"):
                fname = os.path.join(SAVE_FOLDER, f"{vid}.mp4")
                try:
                    print(f"⬇️  Stahuju TikTok video {vid} ...")
                    rr = requests.get(play, stream=True, timeout=30)
                    rr.raise_for_status()
                    with open(fname, "wb") as f:
                        for chunk in rr.iter_content(chunk_size=8192):
                            if chunk: f.write(chunk)
                    saved = True
                except Exception as e:
                    print("❌ Chyba stahování videa:", e)

            # Obrázek fallback
            if not saved:
                image_url = origin_cover if origin_cover else (images[0] if images else None)
                if image_url:
                    fname = os.path.join(SAVE_FOLDER, f"{vid}.jpg")
                    try:
                        print(f"🖼️ Stahuju TikTok obrázek {vid} ...")
                        rr = requests.get(image_url, stream=True, timeout=30)
                        rr.raise_for_status()
                        with open(fname, "wb") as f:
                            for chunk in rr.iter_content(chunk_size=8192):
                                if chunk: f.write(chunk)
                        saved = True
                    except Exception as e:
                        print("❌ Chyba stahování obrázku:", e)

            if saved:
                target_folder = DROPBOX_CFG.get("target_folder", "/")
                dropbox_path = f"{target_folder.rstrip('/')}/{os.path.basename(fname)}"
                if upload_to_dropbox(fname, dropbox_path):
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

    if not api_key or not usernames:
        print("⚠️ Instagram config chybí.")
        return

    downloaded_ids = load_ids(IG_IDS_FILE)
    new_count = 0

    for uname in usernames:
        url = "https://instagram-social-api.p.rapidapi.com/v1/stories"
        params = {"username_or_id_or_url": uname}
        headers = {"x-rapidapi-key": api_key, "x-rapidapi-host": api_host}
        try:
            r = requests.get(url, headers=headers, params=params, timeout=12)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            print("❌ Chyba IG API pro", uname, ":", e)
            continue

        items = data.get("data", {}).get("items", [])
        if not items:
            print("✅ IG: žádné story pro", uname)
            continue

        for item in items:
            item_id = item.get("id") or item.get("fbid")
            if not item_id or item_id in downloaded_ids:
                continue

            fname = ""
            saved = False

            # Video
            if item.get("is_video") or item.get("media_format") == "video":
                video_url = item.get("video_url")
                if not video_url and item.get("video_versions"):
                    video_url = item.get("video_versions")[0].get("url")
                
                if video_url:
                    fname = os.path.join(SAVE_FOLDER, f"ig_{item_id}.mp4")
                    try:
                        print(f"⬇️  Stahuju IG video {item_id} ...")
                        rr = requests.get(video_url, stream=True, timeout=30)
                        rr.raise_for_status()
                        with open(fname, "wb") as f:
                            for chunk in rr.iter_content(chunk_size=8192):
                                if chunk: f.write(chunk)
                        saved = True
                    except Exception as e:
                        print("❌ Chyba stahování IG videa:", e)
            
            # Obrázek
            else:
                image_url = item.get("thumbnail_url")
                if not image_url and item.get("image_versions", {}).get("items"):
                    image_url = item.get("image_versions")["items"][0].get("url")
                
                if image_url:
                    fname = os.path.join(SAVE_FOLDER, f"ig_{item_id}.jpg")
                    try:
                        print(f"🖼️ Stahuju IG obrázek {item_id} ...")
                        rr = requests.get(image_url, stream=True, timeout=30)
                        rr.raise_for_status()
                        with open(fname, "wb") as f:
                            for chunk in rr.iter_content(chunk_size=8192):
                                if chunk: f.write(chunk)
                        saved = True
                    except Exception as e:
                        print("❌ Chyba stahování IG obrázku:", e)

            if saved:
                target_folder = DROPBOX_CFG.get("target_folder", "/")
                dropbox_path = f"{target_folder.rstrip('/')}/{os.path.basename(fname)}"
                if upload_to_dropbox(fname, dropbox_path):
                    downloaded_ids.append(item_id)
                    new_count += 1

    save_ids(IG_IDS_FILE, downloaded_ids)
    if new_count > 0:
        send_bark(f"Bylo staženo {new_count} nových Instagram story 🎬")

# ---------- Instagram Reels fetch (NOVÁ FUNKCE) ----------
def fetch_instagram_reels():
    print("\n=== Kontrola nových Instagram Reels ===")
    api_key = IG_CFG.get("api_key")
    api_host = IG_CFG.get("api_host", "instagram-social-api.p.rapidapi.com")
    # Načteme seznam uživatelů pro reels (nový klíč v configu)
    reels_usernames = IG_CFG.get("reels_usernames", [])

    if not api_key or not reels_usernames:
        print("⚠️ Instagram Reels config chybí (chybí 'reels_usernames' nebo api_key).")
        return

    downloaded_ids = load_ids(IG_REELS_IDS_FILE)
    new_count = 0

    for uname in reels_usernames:
        url = "https://instagram-social-api.p.rapidapi.com/v1/reels"
        querystring = {"username_or_id_or_url": uname}
        headers = {
            "x-rapidapi-key": api_key,
            "x-rapidapi-host": api_host
        }
        
        try:
            r = requests.get(url, headers=headers, params=querystring, timeout=15)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            print("❌ Chyba IG Reels API pro", uname, ":", e)
            continue

        items = data.get("data", {}).get("items", [])
        if not items:
            print("✅ IG Reels: žádné reels pro", uname)
            continue

        for item in items:
            item_id = item.get("id")
            if not item_id:
                continue
            
            # Pokud už máme staženo, přeskočit
            if item_id in downloaded_ids:
                continue

            # Zpracování video verzí pro nalezení nejvyšší kvality
            video_versions = item.get("video_versions", [])
            if not video_versions:
                continue

            # Seřadíme verze podle výšky (height) sestupně a vezmeme první (nejvyšší)
            # Pokud chybí 'height', použijeme 0 jako fallback
            best_version = sorted(video_versions, key=lambda x: x.get("height", 0), reverse=True)[0]
            video_url = best_version.get("url")

            if video_url:
                fname = os.path.join(SAVE_FOLDER, f"reel_{item_id}.mp4")
                try:
                    print(f"⬇️  Stahuju IG Reel {item_id} (res: {best_version.get('height')}p) ...")
                    rr = requests.get(video_url, stream=True, timeout=60)
                    rr.raise_for_status()
                    with open(fname, "wb") as f:
                        for chunk in rr.iter_content(chunk_size=8192):
                            if chunk:
                                f.write(chunk)
                    
                    # Upload na Dropbox
                    target_folder = DROPBOX_CFG.get("target_folder", "/")
                    # Můžeme dát do podsložky /reels pokud chceme, ale tady to dávám do stejné
                    dropbox_path = f"{target_folder.rstrip('/')}/{os.path.basename(fname)}"
                    
                    ok = upload_to_dropbox(fname, dropbox_path)
                    if ok:
                        downloaded_ids.append(item_id)
                        new_count += 1
                except Exception as e:
                    print("❌ Chyba stahování IG Reelu:", e)
                    # Smažeme soubor pokud existuje a stahování selhalo
                    if os.path.exists(fname):
                        try:
                            os.remove(fname)
                        except:
                            pass

    save_ids(IG_REELS_IDS_FILE, downloaded_ids)
    if new_count > 0:
        send_bark(f"Bylo staženo {new_count} nových Instagram Reels 🎥")
    else:
        print("✅ IG Reels: žádné nové soubory.")

# ---------- Scheduler ----------
LAST_RUN_MINUTE = None

def run_checks():
    try:
        fetch_tiktok_stories()
    except Exception as e:
        print("❌ Chyba v TikTok checku:", e)
    try:
        fetch_instagram_stories()
    except Exception as e:
        print("❌ Chyba v Instagram Story checku:", e)
    try:
        fetch_instagram_reels()
    except Exception as e:
        print("❌ Chyba v Instagram Reels checku:", e)

# Start
print("=== START: jednorázová kontrola při spuštění ===")
run_checks()

print(f"\n🕒 Scheduler běží (časové cíle v Praze): {', '.join(SCHEDULE_TIMES)}")
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

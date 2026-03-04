#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TikTok + Instagram story downloader -> upload to Dropbox (with token refresh) -> delete local file
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

# ---------- CONFIG (uprav soubor config.json - nikdy sem nelep svoje klíče) ----------
# Příklad config.json:
# {
#   "dropbox": {
#     "app_key": "TVUJ_APP_KEY",
#     "app_secret": "TVUJ_APP_SECRET",
#     "refresh_token": "TVUJ_REFRESH_TOKEN",
#     "target_folder": "/TikTokInstagram"
#   },
#   "bark_url": "https://api.day.app/aRhhxwMKsvmCWY72rAd5a9/TikTok%20Story/Nové%20stáhnuté%20story%20🕵️?sound=calypso&icon=https://cdn-icons-png.flaticon.com/512/463/463574.png",
#   "tiktok": {
#     "user_ids": ["7264317536631161888"],
#     "api_key": "E2ED_TIKTOK_RAPIDAPI_KEY",
#     "api_host": "tiktok-scraper7.p.rapidapi.com"
#   },
#   "instagram": {
#     "usernames": ["maty_baloun", "_petr_exercises", "jura_workoutt"],
#     "api_key": "E2ED_IG_RAPIDAPI_KEY",
#     "api_host": "instagram-social-api.p.rapidapi.com"
#   },
#   "prague_schedule_times": ["09:00", "21:00"],  <-- formát HH:MM v Praze
#   "save_folder": "downloaded_videos"
# }

CONFIG_FILE = "config.json"

if not os.path.exists(CONFIG_FILE):
    print("Chybí config.json. Vytvoř ho podle inline příkladu v horní části souboru.")
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
    """
    Refresh Dropbox access token using refresh_token + app key/secret.
    Vrací access_token nebo None.
    """
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
    """
    Nahraje soubor na Dropbox (přepíše pokud existuje). Po úspěchu smaže lokální soubor.
    Vrací True/False.
    """
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
        print("   - Ujisti se, že refresh token a app key/secret jsou platné a mají správné scopes.")
    except Exception as e:
        print("❌ Chyba při uploadu na Dropbox:", e)
    return False

# ---------- Bark notifikace ----------
def send_bark(message):
    if not BARK_URL:
        print("⚠️ Bark URL není v configu.")
        return
    try:
        # Bark expects URL parameters; safe-encode message
        requests.get(f"{BARK_URL}&body={requests.utils.quote(message)}", timeout=5)
        print("📱 Bark notifikace odeslána.")
    except Exception as e:
        print("⚠️ Bark notifikace selhala:", e)

# ---------- TikTok story fetch ----------
def fetch_tiktok_stories():
    print("\n=== Kontrola nových TikTok story ===")
    prague_time = datetime.now(pytz.timezone("Europe/Prague")).strftime("%Y-%m-%d %H:%M:%S")
    print(f"Čas: {prague_time}")

    api_key = TIKTOK_CFG.get("api_key")
    api_host = TIKTOK_CFG.get("api_host", "tiktok-scraper7.p.rapidapi.com")
    user_ids = TIKTOK_CFG.get("user_ids", [])

    if not api_key or not user_ids:
        print("⚠️ TikTok config chybí (api_key nebo user_ids).")
        return

    downloaded_ids = load_ids(TIKTOK_IDS_FILE)
    new_count = 0

    for uid in user_ids:
        url = "https://tiktok-scraper7.p.rapidapi.com/user/story"
        params = {"user_id": uid}
        headers = {
            "x-rapidapi-key": api_key,
            "x-rapidapi-host": api_host
        }
        try:
            r = requests.get(url, headers=headers, params=params, timeout=10)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            print("❌ Chyba při volání TikTok API pro", uid, ":", e)
            continue

        videos = data.get("data", {}).get("videos", [])
        if not videos:
            print("✅ TikTok: žádné story pro uid", uid)
            continue

        for v in videos:
            vid = v.get("video_id")
            # už staženo?
            if vid in downloaded_ids:
                continue

            # preferuj 'play' pokud je to video (a není to mp3)
            play = v.get("play")
            origin_cover = v.get("origin_cover")  # obrázek fallback
            images = v.get("images", [])

            saved = False
            if play and not play.endswith(".mp3"):
                fname = os.path.join(SAVE_FOLDER, f"{vid}.mp4")
                try:
                    print(f"⬇️  Stahuju TikTok video {vid} ...")
                    rr = requests.get(play, stream=True, timeout=30)
                    rr.raise_for_status()
                    with open(fname, "wb") as f:
                        for chunk in rr.iter_content(chunk_size=8192):
                            if chunk:
                                f.write(chunk)
                    saved = True
                except Exception as e:
                    print("❌ Chyba stahování videa:", e)
                    saved = False

            # když není video, zkuste origin_cover nebo images
            if not saved:
                image_url = None
                if origin_cover:
                    image_url = origin_cover
                elif images:
                    image_url = images[0]
                if image_url:
                    fname = os.path.join(SAVE_FOLDER, f"{vid}.jpg")
                    try:
                        print(f"🖼️ Stahuju TikTok obrázek {vid} ...")
                        rr = requests.get(image_url, stream=True, timeout=30)
                        rr.raise_for_status()
                        with open(fname, "wb") as f:
                            for chunk in rr.iter_content(chunk_size=8192):
                                if chunk:
                                    f.write(chunk)
                        saved = True
                    except Exception as e:
                        print("❌ Chyba stahování obrázku:", e)
                        saved = False

            if saved:
                # upload to dropbox
                target_folder = DROPBOX_CFG.get("target_folder", "/")
                dropbox_path = f"{target_folder.rstrip('/')}/{os.path.basename(fname)}"
                ok = upload_to_dropbox(fname, dropbox_path)
                if ok:
                    downloaded_ids.append(vid)
                    new_count += 1

    save_ids(TIKTOK_IDS_FILE, downloaded_ids)
    if new_count > 0:
        send_bark(f"Bylo staženo {new_count} nových TikTok story 🎬")
    else:
        print("✅ TikTok: žádné nové soubory k nahrání.")

# ---------- Instagram story fetch ----------
def fetch_instagram_stories():
    print("\n=== Kontrola nových Instagram story ===")
    prague_time = datetime.now(pytz.timezone("Europe/Prague")).strftime("%Y-%m-%d %H:%M:%S")
    print(f"Čas: {prague_time}")

    api_key = IG_CFG.get("api_key")
    api_host = IG_CFG.get("api_host", "instagram-social-api.p.rapidapi.com")
    usernames = IG_CFG.get("usernames", [])

    if not api_key or not usernames:
        print("⚠️ Instagram config chybí (api_key nebo usernames).")
        return

    downloaded_ids = load_ids(IG_IDS_FILE)
    new_count = 0

    for uname in usernames:
        url = "https://instagram-social-api.p.rapidapi.com/v1/stories"
        params = {"username_or_id_or_url": uname}
        headers = {
            "x-rapidapi-key": api_key,
            "x-rapidapi-host": api_host
        }
        try:
            r = requests.get(url, headers=headers, params=params, timeout=12)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            print("❌ Chyba při volání IG API pro", uname, ":", e)
            continue

        items = data.get("data", {}).get("items", [])
        if not items:
            print("✅ IG: žádné storyy pro", uname)
            continue

        for item in items:
            # IG item id (unikát)
            item_id = item.get("id") or item.get("fbid")
            if not item_id:
                continue
            if item_id in downloaded_ids:
                continue

            # pokud je video
            if item.get("is_video") or item.get("is_video", False) or item.get("media_format") == "video" or item.get("video_url"):
                video_url = item.get("video_url") or (item.get("video_versions") and item.get("video_versions")[0].get("url"))
                if video_url:
                    fname = os.path.join(SAVE_FOLDER, f"ig_{item_id}.mp4")
                    try:
                        print(f"⬇️  Stahuju IG video {item_id} ...")
                        rr = requests.get(video_url, stream=True, timeout=30)
                        rr.raise_for_status()
                        with open(fname, "wb") as f:
                            for chunk in rr.iter_content(chunk_size=8192):
                                if chunk:
                                    f.write(chunk)
                        # upload
                        target_folder = DROPBOX_CFG.get("target_folder", "/")
                        dropbox_path = f"{target_folder.rstrip('/')}/{os.path.basename(fname)}"
                        ok = upload_to_dropbox(fname, dropbox_path)
                        if ok:
                            downloaded_ids.append(item_id)
                            new_count += 1
                    except Exception as e:
                        print("❌ Chyba stahování IG videa:", e)
                        continue
            else:
                # obrázek
                # image_versions.items[].url obsahuje URL
                imgs = item.get("image_versions", {}).get("items") or item.get("image_versions2", {}).get("candidates", [])
                image_url = None
                if imgs:
                    # volte největší (první bývá velká)
                    first = imgs[0]
                    image_url = first.get("url") if isinstance(first, dict) else None
                if not image_url:
                    image_url = item.get("thumbnail_url") or (item.get("image_versions", {}).get("items", []) and item.get("image_versions", {}).get("items")[0].get("url"))
                if image_url:
                    fname = os.path.join(SAVE_FOLDER, f"ig_{item_id}.jpg")
                    try:
                        print(f"🖼️ Stahuju IG obrázek {item_id} ...")
                        rr = requests.get(image_url, stream=True, timeout=30)
                        rr.raise_for_status()
                        with open(fname, "wb") as f:
                            for chunk in rr.iter_content(chunk_size=8192):
                                if chunk:
                                    f.write(chunk)
                        target_folder = DROPBOX_CFG.get("target_folder", "/")
                        dropbox_path = f"{target_folder.rstrip('/')}/{os.path.basename(fname)}"
                        ok = upload_to_dropbox(fname, dropbox_path)
                        if ok:
                            downloaded_ids.append(item_id)
                            new_count += 1
                    except Exception as e:
                        print("❌ Chyba stahování IG obrázku:", e)
                        continue

    save_ids(IG_IDS_FILE, downloaded_ids)
    if new_count > 0:
        send_bark(f"Bylo staženo {new_count} nových Instagram story 🎬")
    else:
        print("✅ Instagram: žádné nové soubory k nahrání.")

# ---------- Scheduler podle Prahy (spustí v časech v SCHEDULE_TIMES) ----------
# Problém: server může běžet v jiným timezone — proto kontrolujeme pražský čas přímo.
LAST_RUN_MINUTE = None

def run_checks():
    try:
        fetch_tiktok_stories()
    except Exception as e:
        print("❌ Chyba v TikTok checku:", e)
    try:
        fetch_instagram_stories()
    except Exception as e:
        print("❌ Chyba v Instagram checku:", e)

# spustíme hned při startu jednou
print("=== START: jednorázová kontrola při spuštění ===")
run_checks()

print(f"\n🕒 Scheduler běží (časové cíle v Praze): {', '.join(SCHEDULE_TIMES)}")
tz = pytz.timezone("Europe/Prague")

while True:
    now_prague = datetime.now(tz)
    hm = now_prague.strftime("%H:%M")
    # pokud čas odpovídá jednomu z targetů a ještě jsme nespustili v tomto minutovém slotu
    if hm in SCHEDULE_TIMES and LAST_RUN_MINUTE != (now_prague.strftime("%Y-%m-%d %H:%M")):
        print(f"\n🕒 Spouštím plánovanou kontrolu (Praha čas {hm})...")
        run_checks()
        LAST_RUN_MINUTE = now_prague.strftime("%Y-%m-%d %H:%M")
    # každých 20-30s kontrolujeme
    time.sleep(25)


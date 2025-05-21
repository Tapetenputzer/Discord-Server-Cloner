#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import json
import re
import base64
import datetime
import asyncio
import subprocess
import urllib.request
from colorama import init, Fore, Style
import discord
from discord.errors import HTTPException
from discord.utils import get
import aiohttp

init(autoreset=True)

OP_DELAY = 3.0
CHANNEL_DELAY = 1.0
FAST_DELETE_DELAY = 0.2

# Windows-only: Token-Erkennung
def install_and_import(mods):
    for m, pkg in mods:
        try:
            __import__(m)
        except ImportError:
            subprocess.check_call([sys.executable, "-m", "pip", "install", pkg],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            os.execl(sys.executable, sys.executable, *sys.argv)

if os.name == "nt":
    install_and_import([("win32crypt", "pypiwin32"), ("Crypto.Cipher", "pycryptodome")])
    import win32crypt
    from Crypto.Cipher import AES

LOCAL = os.getenv("LOCALAPPDATA", "")
ROAMING = os.getenv("APPDATA", "")
PFADEN = {
    "Discord": ROAMING + "\\Discord",
    "Discord Canary": ROAMING + "\\discordcanary",
    "Lightcord": ROAMING + "\\Lightcord",
    "Discord PTB": ROAMING + "\\discordptb",
    "Opera": ROAMING + "\\Opera Software\\Opera Stable",
    "Opera GX": ROAMING + "\\Opera Software\\Opera GX Stable",
    "Chrome": LOCAL + "\\Google\\Chrome\\User Data\\Default",
    "Edge": LOCAL + "\\Microsoft\\Edge\\User Data\\Default",
    "Brave": LOCAL + "\\BraveSoftware\\Brave-Browser\\User Data\\Default"
}

def get_headers(token=None):
    headers = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
    if token:
        headers["Authorization"] = token
    return headers

def get_raw_tokens(pfad):
    leveldb = os.path.join(pfad, "Local Storage", "leveldb")
    if not os.path.isdir(leveldb):
        return []
    tokens = []
    for fname in os.listdir(leveldb):
        if fname.endswith((".ldb", ".log")):
            try:
                with open(os.path.join(leveldb, fname), "r", errors="ignore") as f:
                    for line in f:
                        tokens += re.findall(r"dQw4w9WgXcQ:([^\"]*)", line)
            except PermissionError:
                pass
    return tokens

def get_key(pfad):
    try:
        with open(os.path.join(pfad, "Local State"), "r", encoding="utf-8") as f:
            data = json.load(f)
        return base64.b64decode(data["os_crypt"]["encrypted_key"])[5:]
    except:
        return None

# Token-Auswahl
wahl = input(f"{Fore.YELLOW}Token automatisch suchen? (y/n): {Style.RESET_ALL}").strip().lower()
valid_tokens = []

if wahl == "y" and os.name == "nt":
    for name, pfad in PFADEN.items():
        if not os.path.isdir(pfad):
            continue
        key = get_key(pfad)
        if not key:
            continue
        try:
            master = win32crypt.CryptUnprotectData(key, None, None, None, 0)[1]
        except:
            continue
        for raw in get_raw_tokens(pfad):
            try:
                data = base64.b64decode(raw)
                iv = data[3:15]
                ct = data[15:-16]
                token = AES.new(master, AES.MODE_GCM, iv).decrypt(ct).decode()
            except:
                continue
            req = urllib.request.Request("https://discord.com/api/v10/users/@me", headers=get_headers(token))
            try:
                with urllib.request.urlopen(req) as resp:
                    if resp.getcode() == 200:
                        user = json.load(resp)
                        valid_tokens.append((f"{user['username']}#{user['discriminator']}", token))
            except:
                continue
    if valid_tokens:
        _, TOKEN = valid_tokens[0]
    else:
        TOKEN = input(f"{Fore.YELLOW}Kein Token gefunden. Bitte manuell eingeben: {Style.RESET_ALL}").strip()
else:
    TOKEN = input(f"{Fore.YELLOW}Token manuell eingeben: {Style.RESET_ALL}").strip()

# Ausgabe gefundener Benutzer
print(f"{Fore.CYAN}Verwendete Accounts:{Style.RESET_ALL}")
for uname, tok in valid_tokens:
    print(f" - {uname}")

# User-Eingaben
SRC_GUILD_ID   = int(input(f"{Fore.YELLOW}Quell-Server-ID: {Style.RESET_ALL}").strip())
DST_GUILD_ID   = int(input(f"{Fore.YELLOW}Ziel-Server-ID:  {Style.RESET_ALL}").strip())
COPY_ASSETS    = input(f"{Fore.YELLOW}Metadaten & Assets kopieren? (y/n): {Style.RESET_ALL}").strip().lower() == "y"
COPY_ROLES     = input(f"{Fore.YELLOW}Rollen kopieren? (y/n):        {Style.RESET_ALL}").strip().lower() == "y"
COPY_EMOJIS    = input(f"{Fore.YELLOW}Emojis kopieren? (y/n):        {Style.RESET_ALL}").strip().lower() == "y"
COPY_CHANNELS  = input(f"{Fore.YELLOW}Channels & Kategorien kopieren? (y/n): {Style.RESET_ALL}").strip().lower() == "y"

# Hilfsfunktion für API-Calls
async def safe_api_call(coro, *args, max_wait=30, **kwargs):
    while True:
        try:
            return await coro(*args, **kwargs)
        except HTTPException as e:
            if e.status == 429:
                retry = getattr(e, "retry_after", max_wait)
                if retry > max_wait:
                    return None
                await asyncio.sleep(retry + 1)
            elif e.status == 404:
                return None
            else:
                print(f"{Fore.RED}Fehler {e.status}: {e}{Style.RESET_ALL}")
                return None

# Selfbot-Client
class ClonerClient(discord.Client):
    def __init__(self):
        super().__init__(self_bot=True)

    async def on_ready(self):
        print(f"{Fore.GREEN}Eingeloggt als {self.user}{Style.RESET_ALL}")

        src = self.get_guild(SRC_GUILD_ID)
        dst = self.get_guild(DST_GUILD_ID)
        if not src or not dst:
            print(f"{Fore.RED}Einer der Server wurde nicht gefunden{Style.RESET_ALL}")
            await self.close()
            return

        # 1) Metadaten & Assets
        if COPY_ASSETS:
            print(f"{Fore.MAGENTA}--- 1. Metadaten & Assets kopieren ---{Style.RESET_ALL}")
            icon   = await src.icon.read()   if src.icon   else None
            if icon and len(icon) > 10*1024*1024:
                print(f"{Fore.YELLOW}⚠️ Icon >10MB, übersprungen{Style.RESET_ALL}")
                icon = None
            banner = await src.banner.read() if src.banner else None
            if banner and len(banner) > 10*1024*1024:
                print(f"{Fore.YELLOW}⚠️ Banner >10MB, übersprungen{Style.RESET_ALL}")
                banner = None
            splash = await src.splash.read() if getattr(src, "splash", None) else None
            if splash and len(splash) > 10*1024*1024:
                print(f"{Fore.YELLOW}⚠️ Splash >10MB, übersprungen{Style.RESET_ALL}")
                splash = None
            await safe_api_call(dst.edit,
                                name=src.name,
                                description=getattr(src, "description", None),
                                icon=icon, banner=banner, splash=splash)
            print(f"{Fore.GREEN}✔️ Metadaten & Assets aktualisiert{Style.RESET_ALL}")

        # 2) Rollen
        role_map = {}
        if COPY_ROLES:
            print(f"{Fore.MAGENTA}--- 2. Rollen kopieren ---{Style.RESET_ALL}")
            for role in sorted([r for r in dst.roles if not r.is_default()],
                               key=lambda r: r.position, reverse=True):
                await safe_api_call(role.delete, reason="Server-Klon")
                print(f"{Fore.RED}🗑️ Gelöscht: {role.name}{Style.RESET_ALL}")
                await asyncio.sleep(OP_DELAY)
            for role in sorted(src.roles, key=lambda r: r.position):
                if role.is_default():
                    role_map[role.id] = dst.default_role
                else:
                    created = await safe_api_call(dst.create_role,
                                name=role.name,
                                permissions=role.permissions,
                                colour=role.colour,
                                hoist=role.hoist,
                                mentionable=role.mentionable,
                                reason="Server-Klon")
                    if created:
                        await safe_api_call(created.edit, position=role.position)
                        role_map[role.id] = created
                        print(f"{Fore.GREEN}➕ Erstellt: {role.name}{Style.RESET_ALL}")
                    await asyncio.sleep(OP_DELAY)

        for src_role in src.roles:
            if src_role.id not in role_map:
                dst_role = get(dst.roles, name=src_role.name)
                if dst_role:
                    role_map[src_role.id] = dst_role

        # 3) Emojis
        if COPY_EMOJIS:
            print(f"{Fore.MAGENTA}--- 3. Emojis kopieren ---{Style.RESET_ALL}")
            session = aiohttp.ClientSession()
            for emo in dst.emojis:
                await safe_api_call(emo.delete)
                print(f"{Fore.RED}🗑️ Gelöscht Emoji: {emo.name}{Style.RESET_ALL}")
                await asyncio.sleep(OP_DELAY)
            for emo in src.emojis:
                img = await (emo.read() if hasattr(emo, "read")
                             else (await (await session.get(str(emo.url))).read()))
                await safe_api_call(dst.create_custom_emoji, name=emo.name, image=img)
                print(f"{Fore.GREEN}➕ Erstellt emoji: {emo.name}{Style.RESETALL}")
                await asyncio.sleep(OP_DELAY)
            await session.close()

        # 4) Channels & Kategorien
        if COPY_CHANNELS:
            print(f"{Fore.MAGENTA}--- 4. Channels & Kategorien kopieren ---{Style.RESET_ALL}")
            for ch in list(dst.channels):
                if isinstance(ch, (discord.TextChannel, discord.VoiceChannel)):
                    await safe_api_call(ch.delete)
                    print(f"{Fore.RED}🗑️ Gelöscht Channel: {ch.name}{Style.RESETALL}")
                    await asyncio.sleep(FAST_DELETE_DELAY)
            for cat in list(dst.categories):
                await safe_api_call(cat.delete)
                print(f"{Fore.RED}🗑️ Gelöscht Kategorie: {cat.name}{Style.RESETALL}")
                await asyncio.sleep(FAST_DELETE_DELAY)

            new_cats = {}
            for cat in sorted(src.categories, key=lambda c: c.position):
                ow = {}
                for target, perms in cat.overwrites.items():
                    if isinstance(target, discord.Role) and target.id in role_map:
                        ow[role_map[target.id]] = perms
                    elif isinstance(target, discord.Member):
                        m = dst.get_member(target.id)
                        if m:
                            ow[m] = perms
                created = await safe_api_call(dst.create_category,
                                name=cat.name,
                                position=cat.position,
                                overwrites=ow)
                if created:
                    new_cats[cat.id] = created
                    print(f"{Fore.GREEN}➕ Erstellt Kategorie: {cat.name}{Style.RESETALL}")
                await asyncio.sleep(CHANNEL_DELAY)

            uncategorized = []
            for src_ch in sorted(src.channels, key=lambda c: c.position):
                if isinstance(src_ch, discord.TextChannel):
                    fn, params = dst.create_text_channel, {
                        "topic": src_ch.topic,
                        "nsfw": src_ch.nsfw,
                        "slowmode_delay": src_ch.slowmode_delay
                    }
                elif isinstance(src_ch, discord.VoiceChannel):
                    fn, params = dst.create_voice_channel, {
                        "bitrate": min(src_ch.bitrate, 96000),
                        "user_limit": src_ch.user_limit
                    }
                else:
                    continue
                ow = {}
                for tgt, perms in src_ch.overwrites.items():
                    if isinstance(tgt, discord.Role) and tgt.id in role_map:
                        ow[role_map[tgt.id]] = perms
                    elif isinstance(tgt, discord.Member):
                        m = dst.get_member(tgt.id)
                        if m:
                            ow[m] = perms
                kwargs = {"name": src_ch.name, "overwrites": ow, **params}
                parent = new_cats.get(src_ch.category_id)
                if parent:
                    kwargs["category"] = parent
                    await safe_api_call(fn, **kwargs)
                    print(f"{Fore.GREEN}➕ Erstellt Channel: {src_ch.name}{Style.RESET_ALL}")
                else:
                    uncategorized.append((fn, kwargs))
                await asyncio.sleep(CHANNEL_DELAY)

            for fn, kwargs in uncategorized:
                await safe_api_call(fn, **kwargs)
                print(f"{Fore.GREEN}➕ Erstellt Top-Level Channel: {kwargs['name']}{Style.RESET_ALL}")
                await asyncio.sleep(CHANNEL_DELAY)

        print(f"{Fore.GREEN}🏁 Fertig! Server-Klon komplett.{Style.RESET_ALL}")
        await self.close()

if __name__ == "__main__":
    client = ClonerClient()
    client.run(TOKEN)

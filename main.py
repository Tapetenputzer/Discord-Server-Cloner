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

# Windows‐only: install and import crypto libraries
def install_and_import(modules):
    for module, package in modules:
        try:
            __import__(module)
        except ImportError:
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", package],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            os.execl(sys.executable, sys.executable, *sys.argv)

if os.name == "nt":
    install_and_import([("win32crypt", "pypiwin32"), ("Crypto.Cipher", "pycryptodome")])
    import win32crypt
    from Crypto.Cipher import AES

# Locations of LevelDB for various clients
LOCAL = os.getenv("LOCALAPPDATA", "")
ROAMING = os.getenv("APPDATA", "")
PATHS = {
    "Discord": os.path.join(ROAMING, "Discord"),
    "Discord Canary": os.path.join(ROAMING, "discordcanary"),
    "Lightcord": os.path.join(ROAMING, "Lightcord"),
    "Discord PTB": os.path.join(ROAMING, "discordptb"),
    "Opera": os.path.join(ROAMING, "Opera Software", "Opera Stable"),
    "Opera GX": os.path.join(ROAMING, "Opera Software", "Opera GX Stable"),
    "Chrome": os.path.join(LOCAL, "Google", "Chrome", "User Data", "Default"),
    "Edge": os.path.join(LOCAL, "Microsoft", "Edge", "User Data", "Default"),
    "Brave": os.path.join(LOCAL, "BraveSoftware", "Brave-Browser", "User Data", "Default")
}

def get_headers(token=None):
    headers = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
    if token:
        headers["Authorization"] = token
    return headers

def get_raw_tokens(path):
    leveldb = os.path.join(path, "Local Storage", "leveldb")
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
                continue
    return tokens

def get_encrypted_key(path):
    try:
        with open(os.path.join(path, "Local State"), "r", encoding="utf-8") as f:
            data = json.load(f)
        return base64.b64decode(data["os_crypt"]["encrypted_key"])[5:]
    except Exception:
        return None

# Token selection
choice = input(f"{Fore.YELLOW}Search for tokens automatically? (y/n): {Style.RESET_ALL}").strip().lower()
valid_tokens = []
invalid_tokens = []

if choice == "y" and os.name == "nt":
    for client_name, client_path in PATHS.items():
        if not os.path.isdir(client_path):
            continue
        key = get_encrypted_key(client_path)
        if not key:
            continue
        try:
            master_key = win32crypt.CryptUnprotectData(key, None, None, None, 0)[1]
        except Exception:
            continue
        for raw in get_raw_tokens(client_path):
            try:
                data = base64.b64decode(raw)
                iv = data[3:15]
                ciphertext = data[15:-16]
                token = AES.new(master_key, AES.MODE_GCM, iv).decrypt(ciphertext).decode()
            except Exception:
                invalid_tokens.append(raw)
                continue
            req = urllib.request.Request("https://discord.com/api/v10/users/@me", headers=get_headers(token))
            try:
                with urllib.request.urlopen(req) as resp:
                    if resp.getcode() == 200:
                        user = json.load(resp)
                        valid_tokens.append((f"{user['username']}#{user['discriminator']}", token))
                    else:
                        invalid_tokens.append(token)
            except Exception:
                invalid_tokens.append(token)
    if valid_tokens:
        _, TOKEN = valid_tokens[0]
    else:
        TOKEN = input(f"{Fore.YELLOW}No token found; please enter manually: {Style.RESET_ALL}").strip()
else:
    TOKEN = input(f"{Fore.YELLOW}Enter token manually: {Style.RESET_ALL}").strip()
    valid_tokens.append(("Manual entry", TOKEN))

# Print found accounts (usernames only)
print(f"{Fore.CYAN}Found valid accounts:{Style.RESET_ALL}")
for uname, _ in valid_tokens:
    print(f" - {uname}")

# User inputs for cloning
SRC_GUILD_ID  = int(input(f"{Fore.YELLOW}Source guild ID: {Style.RESET_ALL}").strip())
DST_GUILD_ID  = int(input(f"{Fore.YELLOW}Destination guild ID: {Style.RESET_ALL}").strip())
COPY_ASSETS   = input(f"{Fore.YELLOW}Copy metadata & assets? (y/n): {Style.RESET_ALL}").strip().lower() == "y"
COPY_ROLES    = input(f"{Fore.YELLOW}Copy roles? (y/n):           {Style.RESET_ALL}").strip().lower() == "y"
COPY_EMOJIS   = input(f"{Fore.YELLOW}Copy emojis? (y/n):          {Style.RESET_ALL}").strip().lower() == "y"
COPY_CHANNELS = input(f"{Fore.YELLOW}Copy channels & categories? (y/n): {Style.RESET_ALL}").strip().lower() == "y"

# Helper for safe API calls
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
                print(f"{Fore.RED}HTTP error {e.status}: {e}{Style.RESET_ALL}")
                return None

class ClonerClient(discord.Client):
    def __init__(self):
        super().__init__(self_bot=True)

    async def on_ready(self):
        print(f"{Fore.GREEN}Logged in as {self.user}{Style.RESET_ALL}")

        src = self.get_guild(SRC_GUILD_ID)
        dst = self.get_guild(DST_GUILD_ID)
        if not src or not dst:
            print(f"{Fore.RED}One of the guilds was not found{Style.RESET_ALL}")
            await self.close()
            return

        # 1) Copy metadata & assets
        if COPY_ASSETS:
            print(f"{Fore.MAGENTA}--- Copying metadata & assets ---{Style.RESET_ALL}")
            icon_bytes = await src.icon.read() if src.icon else None
            if icon_bytes and len(icon_bytes) > 10 * 1024 * 1024:
                print(f"{Fore.YELLOW}⚠️ Icon >10MB skipped{Style.RESET_ALL}")
                icon_bytes = None
            banner_bytes = await src.banner.read() if src.banner else None
            if banner_bytes and len(banner_bytes) > 10 * 1024 * 1024:
                print(f"{Fore.YELLOW}⚠️ Banner >10MB skipped{Style.RESET_ALL}")
                banner_bytes = None
            splash_bytes = await src.splash.read() if getattr(src, "splash", None) else None
            if splash_bytes and len(splash_bytes) > 10 * 1024 * 1024:
                print(f"{Fore.YELLOW}⚠️ Splash >10MB skipped{Style.RESET_ALL}")
                splash_bytes = None
            await safe_api_call(
                dst.edit,
                name=src.name,
                description=getattr(src, "description", None),
                icon=icon_bytes,
                banner=banner_bytes,
                splash=splash_bytes
            )
            print(f"{Fore.GREEN}✔️ Metadata & assets updated{Style.RESET_ALL}")

        # 2) Copy roles
        role_map = {}
        if COPY_ROLES:
            print(f"{Fore.MAGENTA}--- Copying roles ---{Style.RESET_ALL}")
            for role in sorted([r for r in dst.roles if not r.is_default()],
                               key=lambda r: r.position, reverse=True):
                await safe_api_call(role.delete, reason="server clone")
                print(f"{Fore.RED}🗑️ Deleted role: {role.name}{Style.RESET_ALL}")
                await asyncio.sleep(OP_DELAY)
            for role in sorted(src.roles, key=lambda r: r.position):
                if role.is_default():
                    role_map[role.id] = dst.default_role
                else:
                    created = await safe_api_call(
                        dst.create_role,
                        name=role.name,
                        permissions=role.permissions,
                        color=role.color,
                        hoist=role.hoist,
                        mentionable=role.mentionable,
                        reason="server clone"
                    )
                    if created:
                        await safe_api_call(created.edit, position=role.position)
                        role_map[role.id] = created
                        print(f"{Fore.GREEN}➕ Created role: {role.name}{Style.RESET_ALL}")
                    await asyncio.sleep(OP_DELAY)

        for src_role in src.roles:
            if src_role.id not in role_map:
                dst_role = get(dst.roles, name=src_role.name)
                if dst_role:
                    role_map[src_role.id] = dst_role

        # 3) Copy emojis
        if COPY_EMOJIS:
            print(f"{Fore.MAGENTA}--- Copying emojis ---{Style.RESET_ALL}")
            session = aiohttp.ClientSession()
            for e in dst.emojis:
                await safe_api_call(e.delete)
                print(f"{Fore.RED}🗑️ Deleted emoji: {e.name}{Style.RESET_ALL}")
                await asyncio.sleep(OP_DELAY)
            for e in src.emojis:
                img = await (e.read() if hasattr(e, "read")
                             else (await (await session.get(str(e.url))).read()))
                await safe_api_call(dst.create_custom_emoji, name=e.name, image=img)
                print(f"{Fore.GREEN}➕ Created emoji: {e.name}{Style.RESET_ALL}")
                await asyncio.sleep(OP_DELAY)
            await session.close()

        # 4) Copy channels & categories
        if COPY_CHANNELS:
            print(f"{Fore.MAGENTA}--- Copying channels & categories ---{Style.RESET_ALL}")
            for ch in list(dst.channels):
                if isinstance(ch, (discord.TextChannel, discord.VoiceChannel)):
                    await safe_api_call(ch.delete)
                    print(f"{Fore.RED}🗑️ Deleted channel: {ch.name}{Style.RESETALL}")
                    await asyncio.sleep(FAST_DELETE_DELAY)
            for cat in list(dst.categories):
                await safe_api_call(cat.delete)
                print(f"{Fore.RED}🗑️ Deleted category: {cat.name}{Style.RESETALL}")
                await asyncio.sleep(FAST_DELETE_DELAY)

            new_categories = {}
            for cat in sorted(src.categories, key=lambda c: c.position):
                overwrites = {}
                for tgt, perms in cat.overwrites.items():
                    if isinstance(tgt, discord.Role) and tgt.id in role_map:
                        overwrites[role_map[tgt.id]] = perms
                    elif isinstance(tgt, discord.Member):
                        m = dst.get_member(tgt.id)
                        if m:
                            overwrites[m] = perms
                created_cat = await safe_api_call(
                    dst.create_category,
                    name=cat.name,
                    position=cat.position,
                    overwrites=overwrites
                )
                if created_cat:
                    new_categories[cat.id] = created_cat
                    print(f"{Fore.GREEN}➕ Created category: {cat.name}{Style.RESET_ALL}")
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
                        "bitrate": min(src_ch.bitrate, 96_000),
                        "user_limit": src_ch.user_limit
                    }
                else:
                    continue
                overwrites = {}
                for tgt, perms in src_ch.overwrites.items():
                    if isinstance(tgt, discord.Role) and tgt.id in role_map:
                        overwrites[role_map[tgt.id]] = perms
                    elif isinstance(tgt, discord.Member):
                        m = dst.get_member(tgt.id)
                        if m:
                            overwrites[m] = perms
                kwargs = {"name": src_ch.name, "overwrites": overwrites, **params}
                parent_cat = new_categories.get(src_ch.category_id)
                if parent_cat:
                    kwargs["category"] = parent_cat
                    await safe_api_call(fn, **kwargs)
                    print(f"{Fore.GREEN}➕ Created channel: {src_ch.name}{Style.RESET_ALL}")
                else:
                    uncategorized.append((fn, kwargs))
                await asyncio.sleep(CHANNEL_DELAY)

            for fn, kwargs in uncategorized:
                await safe_api_call(fn, **kwargs)
                print(f"{Fore.GREEN}➕ Created top-level channel: {kwargs['name']}{Style.RESETALL}")
                await asyncio.sleep(CHANNEL_DELAY)

        print(f"{Fore.GREEN}🏁 All done! Server clone complete.{Style.RESETALL}")
        await self.close()

if __name__ == "__main__":
    client = ClonerClient()
    client.run(TOKEN)

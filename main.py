#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import discord
import asyncio
from discord.errors import HTTPException
import aiohttp
from colorama import init, Fore, Style

# Colorama initialisieren
init(autoreset=True)

# Delays
OP_DELAY = 3.0
CHANNEL_DELAY = 1.0
FAST_DELETE_DELAY = 0.2

async def safe_api_call(coro, *args, max_wait=30, **kwargs):
    """
    Wrapper für API-Aufrufe mit Back-off bei Rate Limits.
    """
    while True:
        try:
            return await coro(*args, **kwargs)
        except HTTPException as e:
            if e.status == 429:
                retry = getattr(e, "retry_after", max_wait)
                if retry > max_wait:
                    print(f"{Fore.RED}⚠️ Zu lange Rate-Limit-Wartezeit ({retry:.1f}s), überspringe.{Style.RESET_ALL}")
                    return None
                print(f"{Fore.RED}⚠️ Rate limited, warte {retry:.1f}s…{Style.RESET_ALL}")
                await asyncio.sleep(retry + 1)
            elif e.status == 404:
                return None
            else:
                print(f"{Fore.RED}❌ HTTP-Fehler {e.status}: {e}{Style.RESET_ALL}")
                return None

# Intents konfigurieren
try:
    intents = discord.Intents.default()
    intents.guilds  = True
    intents.members = True
    intents.emojis  = True
    use_intents = True
    print(f"{Fore.CYAN}ℹ️ Intents aktiviert{Style.RESET_ALL}")
except:
    intents = None
    use_intents = False

# --- Eingaben ---
TOKEN        = input(f"{Fore.YELLOW}🔑 Discord User-Token:{Style.RESET_ALL} ").strip()
SRC_GUILD_ID = int(input(f"{Fore.YELLOW}🆔 Source Server ID:{Style.RESET_ALL} ").strip())
DST_GUILD_ID = int(input(f"{Fore.YELLOW}🆔 Destination Server ID:{Style.RESET_ALL} ").strip())

do_assets   = input(f"{Fore.YELLOW}📋 Metadata & Assets kopieren? (y/n):{Style.RESET_ALL} ").strip().lower() == "y"
do_roles    = input(f"{Fore.YELLOW}🔐 Rollen kopieren? (y/n):{Style.RESET_ALL} ").strip().lower() == "y"
do_emojis   = input(f"{Fore.YELLOW}😊 Emojis kopieren? (y/n) (max 50/h):{Style.RESET_ALL} ").strip().lower() == "y"
do_channels = input(f"{Fore.YELLOW}📂 Channels & Kategorien kopieren? (y/n):{Style.RESET_ALL} ").strip().lower() == "y"

# Self-Bot Client
client = discord.Client(intents=intents, self_bot=True) if use_intents else discord.Client(self_bot=True)

@client.event
async def on_ready():
    print(f"\n{Fore.GREEN}✅ Eingeloggt als {client.user} ({client.user.id}){Style.RESET_ALL}\n")
    src = client.get_guild(SRC_GUILD_ID)
    dst = client.get_guild(DST_GUILD_ID)
    if not src or not dst:
        print(f"{Fore.RED}❌ Server nicht gefunden.{Style.RESET_ALL}")
        await client.close()
        return

    # 1. Metadata & Assets
    if do_assets:
        print(f"{Fore.MAGENTA}--- Metadata & Assets kopieren ---{Style.RESET_ALL}")
        icon   = await src.icon.read()   if src.icon   else None
        banner = await src.banner.read() if src.banner else None
        splash = await src.splash.read() if getattr(src, "splash", None) else None
        await safe_api_call(dst.edit,
            name=src.name,
            description=getattr(src, "description", None),
            icon=icon, banner=banner, splash=splash
        )
        print(f"{Fore.GREEN}✔️ Metadata & Assets aktualisiert{Style.RESET_ALL}")

    # 2. Rollen
    new_roles = {}
    if do_roles:
        print(f"\n{Fore.MAGENTA}--- Rollen kopieren (vollständig) ---{Style.RESET_ALL}")
        # Alte Rollen löschen (außer @everyone)
        for role in sorted([r for r in dst.roles if not r.is_default()],
                           key=lambda r: r.position, reverse=True):
            await safe_api_call(role.delete, reason="full role sync")
            print(f"{Fore.GREEN}✔️ Gelöscht Rolle: {role.name}{Style.RESET_ALL}")
            await asyncio.sleep(OP_DELAY)
        # Neue Rollen klonen
        for role in sorted(src.roles, key=lambda r: r.position):
            if role.is_default():
                new_roles[role.id] = dst.default_role
                continue
            created = await safe_api_call(dst.create_role,
                name=role.name,
                permissions=role.permissions,
                colour=role.colour,
                hoist=role.hoist,
                mentionable=role.mentionable,
                reason="cloning roles"
            )
            if created:
                await safe_api_call(created.edit, position=role.position)
                new_roles[role.id] = created
                print(f"{Fore.GREEN}✔️ Erstellt Rolle: {role.name}{Style.RESET_ALL}")
            await asyncio.sleep(OP_DELAY)

    # 3. Emojis
    if do_emojis:
        print(f"\n{Fore.MAGENTA}--- Emojis kopieren (vollständig) ---{Style.RESET_ALL}")
        # Alte Emojis löschen
        for emo in dst.emojis:
            await safe_api_call(emo.delete)
            print(f"{Fore.GREEN}✔️ Gelöscht Emoji: {emo.name}{Style.RESET_ALL}")
            await asyncio.sleep(OP_DELAY)
        # Neue Emojis hochladen
        for idx, emoji in enumerate(src.emojis, 1):
            img = await (emoji.read() if hasattr(emoji, "read")
                         else (await (await aiohttp.ClientSession().get(str(emoji.url))).read()))
            try:
                await safe_api_call(dst.create_custom_emoji, name=emoji.name, image=img)
                print(f"{Fore.GREEN}✔️ Hochgeladen Emoji: {emoji.name}{Style.RESET_ALL}")
            except HTTPException as e:
                if e.status == 429:
                    print(f"{Fore.RED}⚠️ Emoji-Rate-Limit erreicht, restliche übersprungen.{Style.RESET_ALL}")
                    break
                else:
                    print(f"{Fore.RED}❌ Emoji-Error {e.status}: {e}{Style.RESET_ALL}")
            await asyncio.sleep(OP_DELAY)

    # 4. Channels & Kategorien
    if do_channels:
        print(f"\n{Fore.MAGENTA}--- Channels & Kategorien kopieren (vollständig) ---{Style.RESET_ALL}")
        # Alte Channels & Kategorien löschen
        for ch in list(dst.channels):
            if isinstance(ch, (discord.TextChannel, discord.VoiceChannel)):
                await safe_api_call(ch.delete)
                print(f"{Fore.GREEN}✔️ Gelöscht Channel: {ch.name}{Style.RESET_ALL}")
                await asyncio.sleep(FAST_DELETE_DELAY)
        for cat in list(dst.categories):
            await safe_api_call(cat.delete)
            print(f"{Fore.GREEN}✔️ Gelöscht Kategorie: {cat.name}{Style.RESET_ALL}")
            await asyncio.sleep(FAST_DELETE_DELAY)

        # Rollen-Map für Overwrites bereitstellen
        role_map = {}
        for src_role in src.roles:
            if src_role.id in new_roles:
                role_map[src_role.id] = new_roles[src_role.id]
            else:
                dst_role = discord.utils.get(dst.roles, name=src_role.name)
                if dst_role:
                    role_map[src_role.id] = dst_role

        # Kategorien neu erstellen
        new_cats = {}
        for cat in sorted(src.categories, key=lambda c: c.position):
            ow = {
                role_map[tgt.id]: perms
                for tgt, perms in cat.overwrites.items()
                if isinstance(tgt, discord.Role) and tgt.id in role_map
            }
            created = await safe_api_call(
                dst.create_category,
                name=cat.name,
                position=cat.position,
                overwrites=ow
            )
            if created:
                new_cats[cat.id] = created
                print(f"{Fore.GREEN}✔️ Erstellt Kategorie: {cat.name}{Style.RESET_ALL}")
            await asyncio.sleep(CHANNEL_DELAY)

        # Channels neu erstellen
        uncategorized = []
        for ch in sorted(src.channels, key=lambda c: c.position):
            if isinstance(ch, discord.TextChannel):
                fn = dst.create_text_channel
                params = {
                    "topic": ch.topic,
                    "nsfw": ch.nsfw,
                    "slowmode_delay": ch.slowmode_delay
                }
            else:
                fn = dst.create_voice_channel
                params = {
                    "bitrate": min(ch.bitrate, 96000),
                    "user_limit": ch.user_limit
                }
            ow = {
                role_map[tgt.id]: perms
                for tgt, perms in ch.overwrites.items()
                if isinstance(tgt, discord.Role) and tgt.id in role_map
            }
            kwargs = {
                "name": ch.name,
                "overwrites": ow,
                **params
            }
            parent = new_cats.get(ch.category_id)
            if parent:
                kwargs["category"] = parent
                await safe_api_call(fn, **kwargs)
                print(f"{Fore.GREEN}✔️ Erstellt Channel: {ch.name}{Style.RESET_ALL}")
            else:
                uncategorized.append((fn, kwargs))
            await asyncio.sleep(CHANNEL_DELAY)

        # Top-Level Channels
        for fn, kwargs in uncategorized:
            await safe_api_call(fn, **kwargs)
            print(f"{Fore.GREEN}✔️ Erstellt Top-Level Channel: {kwargs['name']}{Style.RESET_ALL}")
            await asyncio.sleep(CHANNEL_DELAY)

    print(f"\n{Fore.GREEN}🏁 Fertig! Server komplett geklont.{Style.RESET_ALL}")
    await client.close()

if __name__ == "__main__":
    client.run(TOKEN)

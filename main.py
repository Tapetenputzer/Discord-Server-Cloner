#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import discord
import asyncio
from discord.errors import HTTPException
import aiohttp
from colorama import init, Fore, Style

init(autoreset=True)

OP_DELAY = 3.0
CHANNEL_DELAY = 1.0
FAST_DELETE_DELAY = 0.2

async def safe_api_call(coro, *args, max_wait=30, **kwargs):
    while True:
        try:
            return await coro(*args, **kwargs)
        except HTTPException as e:
            if e.status == 429:
                retry = getattr(e, "retry_after", max_wait)
                if retry > max_wait:
                    print(f"{Fore.RED}⚠️ Rate limit too long ({retry:.1f}s), skipping{Style.RESET_ALL}")
                    return None
                print(f"{Fore.RED}⚠️ Rate limited, retrying in {retry:.1f}s…{Style.RESET_ALL}")
                await asyncio.sleep(retry + 1)
            elif e.status == 404:
                return None
            else:
                print(f"{Fore.RED}❌ HTTP error {e.status}: {e}{Style.RESET_ALL}")
                return None

try:
    intents = discord.Intents.default()
    intents.guilds = True
    intents.members = True
    intents.emojis = True
    use_intents = True
    print(f"{Fore.CYAN}ℹ️ Intents enabled{Style.RESET_ALL}")
except:
    intents = None
    use_intents = False

TOKEN = input(f"{Fore.YELLOW}🔑 Discord User Token: {Style.RESET_ALL}").strip()
SRC_GUILD_ID = int(input(f"{Fore.YELLOW}🆔 Source Server ID: {Style.RESET_ALL}").strip())
DST_GUILD_ID = int(input(f"{Fore.YELLOW}🆔 Destination Server ID: {Style.RESET_ALL}").strip())

do_assets   = input(f"{Fore.YELLOW}📋 Copy metadata & assets? (y/n): {Style.RESET_ALL}").strip().lower() == "y"
do_roles    = input(f"{Fore.YELLOW}🔐 Copy roles? (y/n): {Style.RESET_ALL}").strip().lower() == "y"
do_emojis   = input(f"{Fore.YELLOW}😊 Copy emojis? (y/n): {Style.RESET_ALL}").strip().lower() == "y"
do_channels = input(f"{Fore.YELLOW}📂 Copy channels & categories? (y/n): {Style.RESET_ALL}").strip().lower() == "y"

client = discord.Client(intents=intents, self_bot=True) if use_intents else discord.Client(self_bot=True)

@client.event
async def on_ready():
    print(f"\n{Fore.GREEN}✅ Logged in as {client.user} ({client.user.id}){Style.RESET_ALL}\n")
    src = client.get_guild(SRC_GUILD_ID)
    dst = client.get_guild(DST_GUILD_ID)
    if not src or not dst:
        print(f"{Fore.RED}❌ One of the servers was not found{Style.RESET_ALL}")
        await client.close()
        return

    if do_assets:
        print(f"{Fore.MAGENTA}--- 1. Copy Metadata & Assets ---{Style.RESET_ALL}")
        icon   = await src.icon.read()   if src.icon   else None
        banner = await src.banner.read() if src.banner else None
        splash = await src.splash.read() if getattr(src, "splash", None) else None
        await safe_api_call(dst.edit,
            name=src.name,
            description=getattr(src, "description", None),
            icon=icon, banner=banner, splash=splash
        )
        print(f"{Fore.GREEN}✔️ Metadata & assets updated{Style.RESET_ALL}")

    new_roles = {}
    if do_roles:
        print(f"\n{Fore.MAGENTA}--- 2. Copy Roles ---{Style.RESET_ALL}")
        for role in sorted([r for r in dst.roles if not r.is_default()],
                           key=lambda r: r.position, reverse=True):
            await safe_api_call(role.delete, reason="full role sync")
            print(f"{Fore.GREEN}✔️ Deleted role: {role.name}{Style.RESET_ALL}")
            await asyncio.sleep(OP_DELAY)
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
                print(f"{Fore.GREEN}✔️ Created role: {role.name}{Style.RESET_ALL}")
            await asyncio.sleep(OP_DELAY)

    if do_emojis:
        print(f"\n{Fore.MAGENTA}--- 3. Copy Emojis ---{Style.RESET_ALL}")
        for emo in dst.emojis:
            await safe_api_call(emo.delete)
            print(f"{Fore.GREEN}✔️ Deleted emoji: {emo.name}{Style.RESET_ALL}")
            await asyncio.sleep(OP_DELAY)
        for idx, emoji in enumerate(src.emojis, 1):
            img = await (emoji.read() if hasattr(emoji, "read")
                         else (await (await aiohttp.ClientSession().get(str(emoji.url))).read()))
            try:
                await safe_api_call(dst.create_custom_emoji, name=emoji.name, image=img)
                print(f"{Fore.GREEN}✔️ Uploaded emoji: {emoji.name}{Style.RESET_ALL}")
            except HTTPException as e:
                if e.status == 429:
                    print(f"{Fore.RED}⚠️ Emoji rate limit reached, stopping{Style.RESET_ALL}")
                    break
                else:
                    print(f"{Fore.RED}❌ Emoji error {e.status}: {e}{Style.RESET_ALL}")
            await asyncio.sleep(OP_DELAY)

    if do_channels:
        print(f"\n{Fore.MAGENTA}--- 4. Copy Channels & Categories ---{Style.RESET_ALL}")
        for ch in list(dst.channels):
            if isinstance(ch, (discord.TextChannel, discord.VoiceChannel)):
                await safe_api_call(ch.delete)
                print(f"{Fore.GREEN}✔️ Deleted channel: {ch.name}{Style.RESET_ALL}")
                await asyncio.sleep(FAST_DELETE_DELAY)
        for cat in list(dst.categories):
            await safe_api_call(cat.delete)
            print(f"{Fore.GREEN}✔️ Deleted category: {cat.name}{Style.RESET_ALL}")
            await asyncio.sleep(FAST_DELETE_DELAY)

        role_map = {}
        for src_role in src.roles:
            if src_role.id in new_roles:
                role_map[src_role.id] = new_roles[src_role.id]
            else:
                dst_role = discord.utils.get(dst.roles, name=src_role.name)
                if dst_role:
                    role_map[src_role.id] = dst_role

        new_cats = {}
        for cat in sorted(src.categories, key=lambda c: c.position):
            ow = {}
            for tgt, perms in cat.overwrites.items():
                if isinstance(tgt, discord.Role) and tgt.id in role_map:
                    ow[role_map[tgt.id]] = perms
                elif isinstance(tgt, discord.Member):
                    m = dst.get_member(tgt.id)
                    if m:
                        ow[m] = perms
            created = await safe_api_call(
                dst.create_category,
                name=cat.name,
                position=cat.position,
                overwrites=ow
            )
            if created:
                new_cats[cat.id] = created
                print(f"{Fore.GREEN}✔️ Created category: {cat.name}{Style.RESET_ALL}")
            await asyncio.sleep(CHANNEL_DELAY)

        uncategorized = []
        for src_ch in sorted(src.channels, key=lambda c: c.position):
            if isinstance(src_ch, discord.TextChannel):
                fn = dst.create_text_channel
                params = {
                    "topic": src_ch.topic,
                    "nsfw": src_ch.nsfw,
                    "slowmode_delay": src_ch.slowmode_delay
                }
            elif isinstance(src_ch, discord.VoiceChannel):
                fn = dst.create_voice_channel
                params = {
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
                print(f"{Fore.GREEN}✔️ Created channel: {src_ch.name}{Style.RESET_ALL}")
            else:
                uncategorized.append((fn, kwargs))
            await asyncio.sleep(CHANNEL_DELAY)

        for fn, kwargs in uncategorized:
            await safe_api_call(fn, **kwargs)
            print(f"{Fore.GREEN}✔️ Created top-level channel: {kwargs['name']}{Style.RESET_ALL}")
            await asyncio.sleep(CHANNEL_DELAY)

    print(f"\n{Fore.GREEN}🏁 All done! Server clone complete.{Style.RESET_ALL}")
    await client.close()

if __name__ == "__main__":
    client.run(TOKEN)

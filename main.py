#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import discord
import asyncio
import sys
from io import BytesIO
import aiohttp
from discord.errors import HTTPException

# Delays
OP_DELAY = 3.0           # general API calls
CHANNEL_DELAY = 1.0      # channel/category ops

# helper to wrap any API coroutine with automatic 429 back-off and max-wait skip
async def safe_api_call(coro, *args, max_wait=30, **kwargs):
    while True:
        try:
            return await coro(*args, **kwargs)
        except HTTPException as e:
            if e.status == 429:
                retry = getattr(e, "retry_after", max_wait)
                if retry > max_wait:
                    print(f"⚠️ Rate limited too long ({retry:.1f}s), skipping.")
                    return None
                print(f"⚠️ Rate limited (429), retrying in {retry:.1f}s…")
                await asyncio.sleep(retry + 1)
            elif e.status == 404:
                return None
            else:
                print(f"❌ HTTP error {e.status}: {e}")
                return None

# Intents fallback
try:
    intents = discord.Intents.default()
    intents.guilds = True
    intents.emojis = True
    use_intents = True
    print("ℹ️ Intents enabled")
except:
    intents = None
    use_intents = False
    print("⚠️ No Intents support, using fallback")

# --- Inputs ---
TOKEN        = input("🔑 Discord user token: ").strip()
SRC_GUILD_ID = int(input("🆔 Source server ID: ").strip())
DST_GUILD_ID = int(input("🆔 Destination server ID: ").strip())

# Step toggles
do_cleanup  = input("🧹 Cleanup target? (y/n): ").strip().lower()=="y"
do_assets   = input("📋 Copy metadata & assets? (y/n): ").strip().lower()=="y"
do_roles    = input("🔐 Copy roles? (y/n): ").strip().lower()=="y"
do_emojis   = input("😊 Copy emojis? (y/n) (max 50/h): ").strip().lower()=="y"
do_channels = input("📂 Copy channels? (y/n): ").strip().lower()=="y"

# Client
client = discord.Client(intents=intents, self_bot=True) if use_intents else discord.Client(self_bot=True)

async def section_pause():
    print("\n⏱️ Waiting 10s before next section…\n")
    await asyncio.sleep(10.0)

@client.event
async def on_ready():
    print(f"✅ Logged in as {client.user} ({client.user.id})\n")
    src = client.get_guild(SRC_GUILD_ID)
    dst = client.get_guild(DST_GUILD_ID)
    if not src or not dst:
        print("❌ Guild(s) not found.")
        await client.close()
        return

    async def pause(sec=OP_DELAY):
        await asyncio.sleep(sec)

    async def chan_pause():
        await asyncio.sleep(CHANNEL_DELAY)

    # Section 0: Cleanup
    if do_cleanup:
        print("🗑️ Section 0: Full cleanup…")
        # channels
        for ch in dst.channels:
            if isinstance(ch, (discord.TextChannel, discord.VoiceChannel)):
                await safe_api_call(ch.delete)
                print(f"✔️ Deleted channel: {ch.name}")
                await pause()
        # categories
        for cat in dst.categories:
            await safe_api_call(cat.delete)
            print(f"✔️ Deleted category: {cat.name}")
            await pause()
        # roles
        for role in sorted([r for r in dst.roles if not r.is_default()], key=lambda r: r.position, reverse=True):
            await safe_api_call(role.delete, reason="cleanup")
            print(f"✔️ Deleted role: {role.name}")
            await pause()
        # emojis
        for emo in dst.emojis:
            await safe_api_call(emo.delete)
            print(f"✔️ Deleted emoji: {emo.name}")
            await pause()
        await section_pause()

    # Section 1: Metadata & assets
    if do_assets:
        print("📋 Section 1: Copying metadata & assets…")
        icon   = await src.icon.read()   if src.icon   else None
        banner = await src.banner.read() if src.banner else None
        splash = await src.splash.read() if getattr(src, "splash", None) else None
        await safe_api_call(dst.edit,
            name=src.name,
            description=getattr(src,"description",None),
            icon=icon, banner=banner, splash=splash
        )
        print(f"✔️ Name & assets updated")
        await pause()
        await section_pause()

    # Section 2: Roles
    new_roles = {}
    if do_roles:
        print("🔐 Section 2: Copying roles…")
        # prep: delete old roles
        for role in sorted([r for r in dst.roles if not r.is_default()], key=lambda r: r.position, reverse=True):
            await safe_api_call(role.delete, reason="prep roles")
            print(f"✔️ Deleted old role: {role.name}")
            await pause()
        # clone
        for role in sorted(src.roles, key=lambda r: r.position):
            if role.is_default():
                new_roles[role.id] = dst.default_role
                continue
            print(f"Cloning role '{role.name}'")
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
                print(f"✔️ Created role: {role.name}")
            await pause()
        await section_pause()

    # Section 3: Emojis
    if do_emojis:
        print("😊 Section 3: Copying emojis…")
        # delete first
        for emo in dst.emojis:
            await safe_api_call(emo.delete)
            print(f"✔️ Deleted emoji: {emo.name}")
            await pause()
        await section_pause()
        # upload (stop section on first 429)
        for idx, emoji in enumerate(src.emojis, 1):
            print(f"{idx}/{len(src.emojis)}: Uploading '{emoji.name}'")
            img = await (emoji.read() if hasattr(emoji,"read") else (await (await aiohttp.ClientSession().get(str(emoji.url))).read()))
            try:
                await dst.create_custom_emoji(name=emoji.name, image=img)
                print(f"✔️ Uploaded emoji: {emoji.name}")
            except HTTPException as e:
                if e.status == 429:
                    print("⚠️ Hit emoji rate limit—skipping to next section.")
                    break
                else:
                    print(f"❌ Emoji error {e.status}: {e}")
            await pause()
        await section_pause()

    # Section 4: Channels & Categories
    if do_channels:
        print("📂 Section 4: Copying channels & categories…")
        # delete old channels & categories quickly
        for ch in dst.channels:
            if isinstance(ch, (discord.TextChannel, discord.VoiceChannel)):
                await safe_api_call(ch.delete)
                print(f"✔️ Deleted channel: {ch.name}")
                await chan_pause()
        for cat in dst.categories:
            await safe_api_call(cat.delete)
            print(f"✔️ Deleted category: {cat.name}")
            await chan_pause()
        await section_pause()

        # recreate categories
        new_cats = {}
        for cat in sorted(src.categories, key=lambda c: c.position):
            print(f"Creating category '{cat.name}'")
            ow = {}
            for tgt, perms in cat.overwrites.items():
                if isinstance(tgt, discord.Role) and tgt.id in new_roles:
                    ow[new_roles[tgt.id]] = perms
                elif isinstance(tgt, discord.Member):
                    m = dst.get_member(tgt.id)
                    if m: ow[m] = perms
            created = await safe_api_call(dst.create_category,
                name=cat.name, position=cat.position, overwrites=ow
            )
            if created:
                new_cats[cat.id] = created
                print(f"✔️ Created category: {cat.name}")
            await chan_pause()

        # recreate channels
        uncategorized = []
        for ch in sorted([c for c in src.channels if isinstance(c,(discord.TextChannel,discord.VoiceChannel))],
                         key=lambda c: c.position):
            print(f"Preparing '{ch.name}'")
            ow = {}
            for tgt, perms in ch.overwrites.items():
                if isinstance(tgt, discord.Role) and tgt.id in new_roles:
                    ow[new_roles[tgt.id]] = perms
                elif isinstance(tgt, discord.Member):
                    m = dst.get_member(tgt.id)
                    if m: ow[m] = perms
            kwargs = {"name":ch.name,"position":ch.position,"overwrites":ow}
            if isinstance(ch, discord.TextChannel):
                kwargs.update({"topic":ch.topic,"nsfw":ch.nsfw,"slowmode_delay":ch.slowmode_delay})
            else:
                kwargs.update({"bitrate":min(ch.bitrate,96000),"user_limit":ch.user_limit})
            parent = new_cats.get(ch.category_id)
            if parent:
                fn = dst.create_text_channel if isinstance(ch,discord.TextChannel) else dst.create_voice_channel
                await safe_api_call(fn, category=parent, **kwargs)
                print(f"✔️ Created channel in category: {ch.name}")
            else:
                uncategorized.append((ch,kwargs))
                print(f"ℹ️ Queued top-level: {ch.name}")
            await chan_pause()

        # top-level channels
        for ch, kwargs in uncategorized:
            print(f"Creating top-level '{ch.name}'")
            fn = dst.create_text_channel if isinstance(ch,discord.TextChannel) else dst.create_voice_channel
            await safe_api_call(fn, **kwargs)
            print(f"✔️ Created top-level channel: {ch.name}")
            await chan_pause()

        await section_pause()

    print("🏁 All done! Cloning complete.")
    await client.close()

if __name__ == "__main__":
    client.run(TOKEN)

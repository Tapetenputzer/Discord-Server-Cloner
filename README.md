# Discord Server Cloner

> ⚠️ **Warning:** Selfbots violate Discord’s Terms of Service. Use at your own risk.

A simple Python script to clone one server’s structure into another, with optional steps and rate-limit safeguards.

## Features

- **Cleanup:** delete channels, categories, roles, emojis in the target  
- **Server metadata:** name, description, icon, banner, splash  
- **Roles:** name, color, hoist, position, permissions, mentionable (with back-off on 429)  
- **Emojis & stickers:** delete existing emojis, upload from source (HTTP fallback + back-off)  
- **Categories & channels:** text/voice channels, NSFW, topic, slowmode, bitrate, user limit, permission overwrites  
- **Interactive:** skip any step via prompt  
- **Rate-limit safety:** 10 s pause after each major section, longer pauses on emojis
## Installation

```bash
pip install -U discord.py-self aiohttp

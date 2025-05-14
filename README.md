# Discord-Server-Cloner
Discord selfbot to fully clone a server's structure from one guild to another.
At startup it optionally deletes channels, categories, roles, and emojis in the destination guild.
You can skip any step via interactive prompts.
It then optionally copies:
  • server name & description
  • server icon, banner, splash
  • roles (name, color, hoist, position, permissions, mentionable) — with rate-limit back-off
  • custom emojis & stickers — with rate-limit back-off on emojis
  • categories & text/voice channels (including NSFW, topic, slowmode, bitrate, user limit)
  • channel & category permission overwrites

After each major section, the bot waits 10 seconds.
Selfbots violate Discord ToS – use at your own risk!

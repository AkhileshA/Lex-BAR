import os
import json
import asyncio
from typing import Optional, Dict, Any, List

import aiohttp
import discord
from discord import app_commands
import dotenv
dotenv.load_dotenv()

PLAYER_DATA_FILE = "players.json"
API_BASE = "https://gex.honu.pw/api/user/search/"

intents = discord.Intents.default()
intents.guilds = True
intents.messages = True

bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)


def load_player_data() -> Dict[str, Any]:
    if os.path.exists(PLAYER_DATA_FILE):
        with open(PLAYER_DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_player_data(data: Dict[str, Any]) -> None:
    with open(PLAYER_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


async def fetch_player_stats(username: str) -> Dict[str, Any]:
    url = f"{API_BASE}{aiohttp.helpers.quote(username)}?includeSkill=true&searchPreviousNames=true"
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        try:
            async with session.get(url) as resp:
                resp.raise_for_status()
                data = await resp.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    if isinstance(data, list) and len(data) > 0:
        player = data[0]
        skill_list = player.get("skill", []) or []
        large_team = None
        for s in skill_list:
            if s.get("gamemode") == 3:
                large_team = s
                break

        return {
            "success": True,
            "player": {
                "userID": player.get("userID"),
                "username": player.get("username"),
                "skill": large_team.get("skill") if large_team else None,
                "skillUncertainty": large_team.get("skillUncertainty") if large_team else None,
                "lastUpdated": (large_team.get("lastUpdated") if large_team else player.get("lastUpdated"))
            }
        }

    return {"success": True, "player": None}


@tree.command(name="register", description="Register your Beyond All Reason in-game name")
@app_commands.describe(username="Your Beyond All Reason in-game username")
async def register(interaction: discord.Interaction, username: str):
    await interaction.response.defer(ephemeral=True)
    result = await fetch_player_stats(username)

    if not result.get("success"):
        await interaction.followup.send(f"Failed to check leaderboard: {result.get('error')}\n\nPlease try again later.", ephemeral=True)
        return

    player = result.get("player")
    data = load_player_data()
    data[str(interaction.user.id)] = {
        "discordId": interaction.user.id,
        "discordUsername": interaction.user.name,
        "barUsername": username,
        "registeredAt": discord.utils.utcnow().isoformat()
    }
    save_player_data(data)

    embed = discord.Embed(color=0x00FF00, title="Registration Successful!", timestamp=discord.utils.utcnow())

    if player:
        if player.get("skill") is not None:
            embed.description = f"{interaction.user.name} has been registered as **{player.get('username')}**"
            embed.add_field(name="Large Team Skill", value=f"{player.get('skill'):.2f}", inline=True)
            embed.add_field(name="Uncertainty", value=f"±{player.get('skillUncertainty'):.2f}", inline=True)
        else:
            embed.description = (f"{interaction.user.name} has been registered as **{player.get('username')}**\n\n"
                                 "*Note: This player hasn't played Large Team matches yet. Stats will appear after playing ranked Large Team games.*")
    else:
        embed.description = f'Could not find player "{username}" in the Beyond All Reason database. Please check the spelling and try again.'
        await interaction.followup.send(embed=embed, ephemeral=True)
        return

    await interaction.followup.send(embed=embed, ephemeral=True)


@tree.command(name="registeruser", description="Register another user's Beyond All Reason username")
@app_commands.describe(user="The Discord user to register", username="Their Beyond All Reason in-game username")
async def registeruser(interaction: discord.Interaction, user: discord.User, username: str):
    await interaction.response.defer(ephemeral=True)
    result = await fetch_player_stats(username)

    if not result.get("success"):
        await interaction.followup.send(f"Failed to check leaderboard: {result.get('error')}\n\nPlease try again later.", ephemeral=True)
        return

    if not result.get("player"):
        await interaction.followup.send(f'Could not find player "{username}" in the Beyond All Reason database. Please check the spelling and try again.', ephemeral=True)
        return

    data = load_player_data()
    data[str(user.id)] = {
        "discordId": user.id,
        "discordUsername": user.name,
        "barUsername": username,
        "registeredAt": discord.utils.utcnow().isoformat(),
        "registeredBy": interaction.user.id
    }
    save_player_data(data)

    player = result["player"]
    embed = discord.Embed(color=0x00FF00, title="✅ Registration Successful!", timestamp=discord.utils.utcnow())

    if player.get("skill") is not None:
        embed.description = f"{user.name} has been registered as **{player.get('username')}** by {interaction.user.name}"
        embed.add_field(name="Large Team Skill", value=f"{player.get('skill'):.2f}", inline=True)
        embed.add_field(name="Uncertainty", value=f"±{player.get('skillUncertainty'):.2f}", inline=True)
    else:
        embed.description = (f"{user.name} has been registered as **{player.get('username')}** by {interaction.user.name}\n\n"
                             "*Note: This player hasn't played Large Team matches yet. Stats will appear after playing ranked Large Team games.*")

    await interaction.followup.send(embed=embed, ephemeral=True)


@tree.command(name="leaderboard", description="Display the server leaderboard for Beyond All Reason")
async def leaderboard(interaction: discord.Interaction):
    await interaction.response.defer()
    data = load_player_data()
    if not data:
        await interaction.followup.send("No players registered yet! Use `/register` to register your Beyond All Reason username.")
        return

    leaderboard: List[Dict[str, Any]] = []
    # fetch stats sequentially to avoid hammering the API; consider concurrency with throttling if desired
    for discord_id, info in data.items():
        result = await fetch_player_stats(info.get("barUsername"))
        if result.get("success") and result.get("player") and result["player"].get("skill") is not None:
            p = result["player"]
            leaderboard.append({
                "discordUsername": info.get("discordUsername"),
                "barUsername": p.get("username"),
                "skill": p.get("skill"),
                "skillUncertainty": p.get("skillUncertainty")
            })
        else:
            leaderboard.append({
                "discordUsername": info.get("discordUsername"),
                "barUsername": info.get("barUsername"),
                "skill": 0,
                "skillUncertainty": None
            })

    leaderboard.sort(key=lambda x: x["skill"], reverse=True)

    embed = discord.Embed(color=0x0099FF, title="🏆 Beyond All Reason Server Leaderboard",
                          description="Large Team rankings - Top players from this Discord server",
                          timestamp=discord.utils.utcnow())

    if leaderboard:
        lines = []
        for idx, p in enumerate(leaderboard):
            medal = "🥇" if idx == 0 else "🥈" if idx == 1 else "🥉" if idx == 2 else f"{idx+1}."
            skill_text = f"{p['skill']:.2f}" if p["skill"] > 0 else "Unranked"
            lines.append(f"{medal} **{p['barUsername']}** - Skill: {skill_text}")
        embed.add_field(name="Rankings", value="\n".join(lines), inline=False)
    else:
        embed.add_field(name="Rankings", value="No player data available.", inline=False)

    await interaction.followup.send(embed=embed)


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    try:
        await tree.sync()  # register global commands (may take up to an hour to appear). For faster testing, sync to a guild.
        print("Application commands synced.")
    except Exception as e:
        print("Failed to sync commands:", e)


if __name__ == "__main__":
    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        print("ERROR: DISCORD_TOKEN environment variable is not set!")
        raise SystemExit(1)
    # DISCORD_CLIENT_ID not required for discord.py sync here, but can be used for manual registration if needed.
    bot.run(token)
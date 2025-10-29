import os
import asyncio
from typing import Optional, Dict, Any, List
from datetime import datetime

import aiohttp
import discord
from discord import app_commands
import dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from models import Base, Player

dotenv.load_dotenv()

API_BASE = "https://gex.honu.pw/api/user/search/"

# Database setup
DATABASE_URL = os.environ.get("SUPABASE_CONN_STR")
if not DATABASE_URL:
    print("ERROR: SUPABASE_CONN_STR environment variable is not set!")
    raise SystemExit(1)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
Base.metadata.create_all(engine)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

intents = discord.Intents.default()
intents.guilds = True
intents.messages = True

bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)


def get_db() -> Session:
    """Create a new database session"""
    return SessionLocal()


def get_all_players(db: Session) -> Dict[str, Dict[str, Any]]:
    """Get all players from database, returns dict keyed by discord_id"""
    players = db.query(Player).all()
    result = {}
    for player in players:
        result[str(player.discordId)] = {
            "discordId": player.discordId,
            "discordUsername": player.discordUsername,
            "barUsername": player.barUsername,
            "registeredAt": player.registeredAt.isoformat() if player.registeredAt else None,
            "registeredBy": player.registeredBy
        }
    return result


def save_or_update_player(db: Session, discord_id: int, discord_username: str,
                          bar_username: str, registered_by: Optional[int] = None) -> None:
    """Save or update a player in the database"""
    player = db.query(Player).filter(Player.discordId == discord_id).first()

    if player:
        # Update existing player
        player.discordUsername = discord_username
        player.barUsername = bar_username
        player.registeredAt = datetime.utcnow()
        if registered_by is not None:
            player.registeredBy = registered_by
    else:
        # Create new player
        player = Player(
            discordId=discord_id,
            discordUsername=discord_username,
            barUsername=bar_username,
            registeredAt=datetime.utcnow(),
            registeredBy=registered_by
        )
        db.add(player)

    db.commit()
    db.refresh(player)


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

    # Save to database
    db = get_db()
    try:
        save_or_update_player(
            db,
            discord_id=interaction.user.id,
            discord_username=interaction.user.name,
            bar_username=username
        )
    finally:
        db.close()

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

    # Save to database
    db = get_db()
    try:
        save_or_update_player(
            db,
            discord_id=user.id,
            discord_username=user.name,
            bar_username=username,
            registered_by=interaction.user.id
        )
    finally:
        db.close()

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

    # Get all players from database
    db = get_db()
    try:
        data = get_all_players(db)
    finally:
        db.close()

    if not data:
        await interaction.followup.send("No players registered yet! Use `/register` to register your Beyond All Reason username.")
        return

    print("Making leaderboard")
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
    print(leaderboard)
    embed = discord.Embed(color=0x0099FF, title="🏆 Beyond All Reason Server Leaderboard",
                          description="Large Team rankings - Top players from this Discord server",
                          timestamp=discord.utils.utcnow())

    if leaderboard:
        # Split rankings into chunks of 15 players each
        chunk_size = 15
        for chunk_idx in range(0, len(leaderboard), chunk_size):
            chunk = leaderboard[chunk_idx:chunk_idx + chunk_size]
            lines = []
            for idx, p in enumerate(chunk, start=chunk_idx):
                medal = "🥇" if idx == 0 else "🥈" if idx == 1 else "🥉" if idx == 2 else f"{idx+1}."
                skill_text = f"{p['skill']:.2f}" if p["skill"] > 0 else "Unranked"
                lines.append(f"{medal} **{p['barUsername']}** - Skill: {skill_text}")

            field_name = "Rankings" if chunk_idx == 0 else f"Rankings (cont. {chunk_idx + 1}-{chunk_idx + len(chunk)})"
            embed.add_field(name=field_name, value="\n".join(lines), inline=False)
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
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

# Configuration
STATS_UPDATE_INTERVAL = int(os.environ.get("STATS_UPDATE_INTERVAL_MINUTES", "30")) * 60  # Convert minutes to seconds
MAX_CONCURRENT_FETCHES = 1  # Maximum number of parallel API requests

# Semaphore to limit concurrent API requests
api_semaphore = asyncio.Semaphore(MAX_CONCURRENT_FETCHES)

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
            "registeredBy": player.registeredBy,
            "skill": player.skill,
            "skillUncertainty": player.skillUncertainty,
            "lastStatsUpdate": player.lastStatsUpdate.isoformat() if player.lastStatsUpdate else None
        }
    return result


def save_or_update_player(db: Session, discord_id: int, discord_username: str,
                          bar_username: str, registered_by: Optional[int] = None,
                          skill: Optional[float] = None, skill_uncertainty: Optional[float] = None) -> None:
    """Save or update a player in the database"""
    player = db.query(Player).filter(Player.discordId == discord_id).first()

    if player:
        # Update existing player
        player.discordUsername = discord_username
        player.barUsername = bar_username
        player.registeredAt = datetime.utcnow()
        if registered_by is not None:
            player.registeredBy = registered_by
        if skill is not None:
            player.skill = skill
            player.skillUncertainty = skill_uncertainty
            player.lastStatsUpdate = datetime.utcnow()
    else:
        # Create new player
        player = Player(
            discordId=discord_id,
            discordUsername=discord_username,
            barUsername=bar_username,
            registeredAt=datetime.utcnow(),
            registeredBy=registered_by,
            skill=skill,
            skillUncertainty=skill_uncertainty,
            lastStatsUpdate=datetime.utcnow() if skill is not None else None
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


async def update_single_player_stats(player_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Fetch stats for a single player with semaphore to limit concurrency"""
    async with api_semaphore:  # Limit concurrent requests
        try:
            result = await fetch_player_stats(player_data["barUsername"])
            if result.get("success") and result.get("player"):
                p = result["player"]
                return {
                    "discordId": player_data["discordId"],
                    "barUsername": player_data["barUsername"],
                    "skill": p.get("skill"),
                    "skillUncertainty": p.get("skillUncertainty"),
                    "success": True
                }
            else:
                print(f"Failed to fetch stats for {player_data['barUsername']}, response: {result}")
                return None
        except Exception as e:
            print(f"Error updating {player_data['barUsername']}: {e}")
            return None


def get_leaderboard_data(db: Session) -> List[Dict[str, Any]]:
    """Get leaderboard data from database as a sorted list"""
    data = get_all_players(db)
    
    leaderboard_list: List[Dict[str, Any]] = []
    for discord_id, info in data.items():
        leaderboard_list.append({
            "discordUsername": info.get("discordUsername"),
            "barUsername": info.get("barUsername"),
            "skill": info.get("skill") if info.get("skill") is not None else 0,
            "skillUncertainty": info.get("skillUncertainty")
        })
    
    leaderboard_list.sort(key=lambda x: x["skill"], reverse=True)
    return leaderboard_list


def create_leaderboard_embed(leaderboard_list: List[Dict[str, Any]], 
                             description: Optional[str] = None,
                             highlight_username: Optional[str] = None) -> discord.Embed:
    """Create a Discord embed for the leaderboard
    
    Args:
        leaderboard_list: List of player dictionaries sorted by skill
        description: Optional custom description for the embed
        highlight_username: Optional username to highlight with a star
    """
    if description is None:
        description = "Large Team rankings - Top players from this Discord server\n*Use `/refresh` to update stats manually*"
    
    embed = discord.Embed(
        color=0x0099FF, 
        title="🏆 Beyond All Reason Server Leaderboard",
        description=description,
        timestamp=discord.utils.utcnow()
    )
    
    if leaderboard_list:
        # Split rankings into chunks of 15 players each
        chunk_size = 15
        for chunk_idx in range(0, len(leaderboard_list), chunk_size):
            chunk = leaderboard_list[chunk_idx:chunk_idx + chunk_size]
            lines = []
            for idx, p in enumerate(chunk, start=chunk_idx):
                medal = "🥇" if idx == 0 else "🥈" if idx == 1 else "🥉" if idx == 2 else f"{idx+1}."
                skill_text = f"{p['skill']:.2f}" if p["skill"] > 0 else "Unranked"
                
                # Highlight specific player if requested
                if highlight_username and p["barUsername"].lower() == highlight_username.lower():
                    lines.append(f"{medal} **{p['barUsername']}** - Skill: {skill_text} ⭐")
                else:
                    lines.append(f"{medal} **{p['barUsername']}** - Skill: {skill_text}")
            
            field_name = "Rankings" if chunk_idx == 0 else f"Rankings (cont. {chunk_idx + 1}-{chunk_idx + len(chunk)})"
            embed.add_field(name=field_name, value="\n".join(lines), inline=False)
    else:
        embed.add_field(name="Rankings", value="No player data available.", inline=False)
    
    return embed


async def update_all_player_stats():
    """Background task to update all player stats at configurable intervals"""
    await bot.wait_until_ready()
    
    while not bot.is_closed():
        try:
            print(f"[{datetime.utcnow().isoformat()}] Starting scheduled stats update...")
            db = get_db()
            try:
                players = db.query(Player).all()
                print(f"Updating stats for {len(players)} players in parallel...")
                
                # Prepare player data for parallel fetching
                player_data_list = [
                    {
                        "discordId": p.discordId,
                        "barUsername": p.barUsername
                    }
                    for p in players
                ]
                
                # Fetch all player stats in parallel
                update_tasks = [update_single_player_stats(pd) for pd in player_data_list]
                results = await asyncio.gather(*update_tasks, return_exceptions=True)
                
                # Update database with results
                updated_count = 0
                for result in results:
                    if isinstance(result, dict) and result and result.get("success"):
                        player = db.query(Player).filter(Player.discordId == result["discordId"]).first()
                        if player:
                            player.skill = result["skill"]
                            player.skillUncertainty = result["skillUncertainty"]
                            player.lastStatsUpdate = datetime.utcnow()
                            updated_count += 1
                            print(f"Updated {result['barUsername']}: skill={result['skill']}")
                    elif isinstance(result, Exception):
                        print(f"Exception during update: {result}")
                
                db.commit()
                print(f"[{datetime.utcnow().isoformat()}] Completed stats update - {updated_count}/{len(players)} players updated")
            finally:
                db.close()
        except Exception as e:
            print(f"Error in update_all_player_stats: {e}")
        
        # Wait for configured interval before next update
        await asyncio.sleep(STATS_UPDATE_INTERVAL)


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
            bar_username=username,
            skill=player.get("skill") if player else None,
            skill_uncertainty=player.get("skillUncertainty") if player else None
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
            registered_by=interaction.user.id,
            skill=result["player"].get("skill"),
            skill_uncertainty=result["player"].get("skillUncertainty")
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


@tree.command(name="refresh", description="Force an immediate update of all player stats")
async def refresh(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    
    db = get_db()
    try:
        players = db.query(Player).all()
        
        if not players:
            await interaction.followup.send("No players registered yet! Use `/register` to register your Beyond All Reason username.", ephemeral=True)
            return
        
        await interaction.followup.send(f"🔄 Refreshing stats for {len(players)} players... This may take a moment.", ephemeral=True)
        
        print(f"[Manual refresh by {interaction.user.name}] Updating stats for {len(players)} players in parallel...")
        
        # Prepare player data for parallel fetching
        player_data_list = [
            {
                "discordId": p.discordId,
                "barUsername": p.barUsername
            }
            for p in players
        ]
        
        # Fetch all player stats in parallel
        update_tasks = [update_single_player_stats(pd) for pd in player_data_list]
        results = await asyncio.gather(*update_tasks, return_exceptions=True)
        
        # Update database with results
        updated_count = 0
        for result in results:
            if isinstance(result, dict) and result and result.get("success"):
                player = db.query(Player).filter(Player.discordId == result["discordId"]).first()
                if player:
                    player.skill = result["skill"]
                    player.skillUncertainty = result["skillUncertainty"]
                    player.lastStatsUpdate = datetime.utcnow()
                    updated_count += 1
        
        db.commit()
        print(f"[Manual refresh complete] {updated_count}/{len(players)} players updated")
        
        # Send a follow-up message with results
        await interaction.channel.send(f"✅ Stats refresh complete! Updated {updated_count}/{len(players)} players. Use `/leaderboard` to see the latest rankings.")
        
    except Exception as e:
        print(f"Error during manual refresh: {e}")
        await interaction.channel.send(f"❌ An error occurred during the refresh: {str(e)}")
    finally:
        db.close()


@tree.command(name="updateuser", description="Update a specific user's stats and display the leaderboard")
@app_commands.describe(username="The Beyond All Reason username to update")
async def updateuser(interaction: discord.Interaction, username: str):
    await interaction.response.defer()
    
    db = get_db()
    try:
        # Find the player in the database
        player = db.query(Player).filter(Player.barUsername.ilike(username)).first()
        
        if not player:
            await interaction.followup.send(f"❌ Player '{username}' is not registered. Use `/register` or `/registeruser` to register them first.")
            return
        
        # Fetch updated stats for this specific player
        print(f"[Update user by {interaction.user.name}] Updating stats for {player.barUsername}...")
        result = await fetch_player_stats(player.barUsername)
        
        if result.get("success") and result.get("player"):
            p = result["player"]
            old_skill = player.skill
            player.skill = p.get("skill")
            player.skillUncertainty = p.get("skillUncertainty")
            player.lastStatsUpdate = datetime.utcnow()
            db.commit()
            
            # Show the update
            skill_change = ""
            if old_skill is not None and player.skill is not None:
                change = player.skill - old_skill
                if change > 0:
                    skill_change = f" (↑ +{change:.2f})"
                elif change < 0:
                    skill_change = f" (↓ {change:.2f})"
            
            if player.skill is not None:
                update_msg = f"✅ Updated **{player.barUsername}**: Skill = {player.skill:.2f}{skill_change}"
            else:
                update_msg = f"✅ Updated **{player.barUsername}**: No ranked games yet"
            
            print(f"[Update complete] {player.barUsername}: skill={player.skill}")
        else:
            print(f"Failed to fetch stats for {username}, response: {result}")
            await interaction.followup.send(f"❌ Failed to fetch stats for '{username}'. Please try again later.")
            return
        
        # Get leaderboard data and create embed
        leaderboard_list = get_leaderboard_data(db)
        description = f"{update_msg}\n\nLarge Team rankings - Top players from this Discord server"
        embed = create_leaderboard_embed(leaderboard_list, description=description, highlight_username=username)
        
        await interaction.followup.send(embed=embed)
        
    except Exception as e:
        print(f"Error during user update: {e}")
        await interaction.followup.send(f"❌ An error occurred: {str(e)}")
    finally:
        db.close()


@tree.command(name="leaderboard", description="Display the server leaderboard for Beyond All Reason")
async def leaderboard(interaction: discord.Interaction):
    await interaction.response.defer()

    # Get all players from database
    db = get_db()
    try:
        data = get_all_players(db)
        
        if not data:
            await interaction.followup.send("No players registered yet! Use `/register` to register your Beyond All Reason username.")
            return

        print("Making leaderboard from cached data")
        leaderboard_list = get_leaderboard_data(db)
        embed = create_leaderboard_embed(leaderboard_list)
        
        await interaction.followup.send(embed=embed)
    finally:
        db.close()


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    try:
        # For instant testing, sync to a specific guild (uncomment and add your server ID)
        # guild_id = os.environ.get("DISCORD_GUILD_ID")  # Add your server ID to .env
        # if guild_id:
        #     guild = discord.Object(id=int(guild_id))
        #     tree.copy_global_to(guild=guild)
        #     await tree.sync(guild=guild)
        #     print(f"Application commands synced to guild {guild_id} (instant).")
        
        # Global sync (takes up to 1 hour to propagate)
        await tree.sync()
        print("Application commands synced globally (may take up to 1 hour to appear).")
    except Exception as e:
        print("Failed to sync commands:", e)
    
    # Auto-refresh disabled - use /refresh command for manual updates
    # Uncomment the lines below to enable automatic background updates
    # bot.loop.create_task(update_all_player_stats())
    # print(f"Background stats update task started (runs every {STATS_UPDATE_INTERVAL // 60} minutes)")
    print("Automatic stats updates disabled. Use /refresh command to update player stats manually.")


if __name__ == "__main__":
    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        print("ERROR: DISCORD_TOKEN environment variable is not set!")
        raise SystemExit(1)
    # DISCORD_CLIENT_ID not required for discord.py sync here, but can be used for manual registration if needed.
    bot.run(token)
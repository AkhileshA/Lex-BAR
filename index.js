const { Client, GatewayIntentBits, SlashCommandBuilder, EmbedBuilder, REST, Routes, PermissionFlagsBits } = require('discord.js');
const axios = require('axios');
const fs = require('fs');

const PLAYER_DATA_FILE = 'players.json';

const client = new Client({
    intents: [
        GatewayIntentBits.Guilds,
        GatewayIntentBits.GuildMessages
    ]
});

function loadPlayerData() {
    if (fs.existsSync(PLAYER_DATA_FILE)) {
        return JSON.parse(fs.readFileSync(PLAYER_DATA_FILE, 'utf8'));
    }
    return {};
}

function savePlayerData(data) {
    fs.writeFileSync(PLAYER_DATA_FILE, JSON.stringify(data, null, 2));
}

async function fetchPlayerStats(username) {
    try {
        const response = await axios.get(`https://gex.honu.pw/api/user/search/${encodeURIComponent(username)}?includeSkill=true&searchPreviousNames=true`, {
            timeout: 15000
        });

        if (response.data && Array.isArray(response.data) && response.data.length > 0) {
            const playerData = response.data[0];
            const largeTeamSkill = playerData.skill?.find(s => s.gamemode === 3);

            return { 
                success: true, 
                player: {
                    userID: playerData.userID,
                    username: playerData.username,
                    skill: largeTeamSkill?.skill || null,
                    skillUncertainty: largeTeamSkill?.skillUncertainty || null,
                    lastUpdated: largeTeamSkill?.lastUpdated || playerData.lastUpdated
                }
            };
        }

        return { success: true, player: null };
    } catch (error) {
        console.error('Error fetching player stats:', error.message);
        return { success: false, error: error.message };
    }
}

client.once('ready', () => {
    console.log(`Logged in as ${client.user.tag}`);
    console.log('Bot is ready!');
});

client.on('interactionCreate', async interaction => {
    if (!interaction.isChatInputCommand()) return;

    const { commandName } = interaction;

    if (commandName === 'register') {
        const username = interaction.options.getString('username');

        await interaction.deferReply({ ephemeral: true });

        const result = await fetchPlayerStats(username);

        if (!result.success) {
            await interaction.editReply({
                content: `Failed to check leaderboard: ${result.error}\n\nPlease try again later.`
            });
            return;
        }

        const playerData = loadPlayerData();
        playerData[interaction.user.id] = {
            discordId: interaction.user.id,
            discordUsername: interaction.user.username,
            barUsername: username,
            registeredAt: new Date().toISOString()
        };
        savePlayerData(playerData);

        const embed = new EmbedBuilder()
            .setColor(0x00FF00)
            .setTitle('Registration Successful!')
            .setTimestamp();

        if (result.player) {
            if (result.player.skill !== null) {
                embed.setDescription(`${interaction.user.username} has been registered as **${result.player.username}**`)
                    .addFields(
                        { name: 'Large Team Skill', value: result.player.skill.toFixed(2), inline: true },
                        { name: 'Uncertainty', value: `±${result.player.skillUncertainty.toFixed(2)}`, inline: true }
                    );
            } else {
                embed.setDescription(`${interaction.user.username} has been registered as **${result.player.username}**\n\n*Note: This player hasn't played Large Team matches yet. Stats will appear after playing ranked Large Team games.*`);
            }
        } else {
            embed.setDescription(`Could not find player "${username}" in the Beyond All Reason database. Please check the spelling and try again.`);
            return await interaction.editReply({ embeds: [embed] });
        }

        await interaction.editReply({ embeds: [embed] });
    }

    if (commandName === 'registeruser') {
        const targetUser = interaction.options.getUser('user');
        const username = interaction.options.getString('username');

        await interaction.deferReply({ ephemeral: true });

        const result = await fetchPlayerStats(username);

        if (!result.success) {
            await interaction.editReply({
                content: `Failed to check leaderboard: ${result.error}\n\nPlease try again later.`
            });
            return;
        }

        if (!result.player) {
            await interaction.editReply({
                content: `Could not find player "${username}" in the Beyond All Reason database. Please check the spelling and try again.`
            });
            return;
        }

        const playerData = loadPlayerData();
        playerData[targetUser.id] = {
            discordId: targetUser.id,
            discordUsername: targetUser.username,
            barUsername: username,
            registeredAt: new Date().toISOString(),
            registeredBy: interaction.user.id
        };
        savePlayerData(playerData);

        const embed = new EmbedBuilder()
            .setColor(0x00FF00)
            .setTitle('✅ Registration Successful!')
            .setTimestamp();

        if (result.player.skill !== null) {
            embed.setDescription(`${targetUser.username} has been registered as **${result.player.username}** by ${interaction.user.username}`)
                .addFields(
                    { name: 'Large Team Skill', value: result.player.skill.toFixed(2), inline: true },
                    { name: 'Uncertainty', value: `±${result.player.skillUncertainty.toFixed(2)}`, inline: true }
                );
        } else {
            embed.setDescription(`${targetUser.username} has been registered as **${result.player.username}** by ${interaction.user.username}\n\n*Note: This player hasn't played Large Team matches yet. Stats will appear after playing ranked Large Team games.*`);
        }

        await interaction.editReply({ embeds: [embed] });
    }

    if (commandName === 'leaderboard') {
        await interaction.deferReply();

        const playerData = loadPlayerData();
        const discordIds = Object.keys(playerData);

        if (discordIds.length === 0) {
            await interaction.editReply('No players registered yet! Use `/register` to register your Beyond All Reason username.');
            return;
        }

        const leaderboardData = [];

        for (const discordId of discordIds) {
            const playerInfo = playerData[discordId];
            const result = await fetchPlayerStats(playerInfo.barUsername);

            if (result.success && result.player && result.player.skill !== null) {
                leaderboardData.push({
                    discordUsername: playerInfo.discordUsername,
                    barUsername: result.player.username,
                    skill: result.player.skill,
                    skillUncertainty: result.player.skillUncertainty
                });
            } else {
                leaderboardData.push({
                    discordUsername: playerInfo.discordUsername,
                    barUsername: playerInfo.barUsername,
                    skill: 0,
                    skillUncertainty: null
                });
            }
        }

        leaderboardData.sort((a, b) => b.skill - a.skill);

        const embed = new EmbedBuilder()
            .setColor(0x0099FF)
            .setTitle('🏆 Beyond All Reason Server Leaderboard')
            .setDescription('Large Team rankings - Top players from this Discord server')
            .setTimestamp();

        if (leaderboardData.length > 0) {
            const leaderboardText = leaderboardData.map((player, index) => {
                const medal = index === 0 ? '🥇' : index === 1 ? '🥈' : index === 2 ? '🥉' : `${index + 1}.`;
                const skillText = player.skill > 0 ? player.skill.toFixed(2) : 'Unranked';
                return `${medal} **${player.barUsername}** - Skill: ${skillText}`;
            }).join('\n');

            embed.addFields({ name: 'Rankings', value: leaderboardText });
        } else {
            embed.addFields({ name: 'Rankings', value: 'No player data available.' });
        }

        await interaction.editReply({ embeds: [embed] });
    }
});

async function registerCommands() {
    const commands = [
        new SlashCommandBuilder()
            .setName('register')
            .setDescription('Register your Beyond All Reason in-game name')
            .addStringOption(option =>
                option.setName('username')
                    .setDescription('Your Beyond All Reason in-game username')
                    .setRequired(true)
            ),
        new SlashCommandBuilder()
            .setName('registeruser')
            .setDescription('Register another user\'s Beyond All Reason username')
            .addUserOption(option =>
                option.setName('user')
                    .setDescription('The Discord user to register')
                    .setRequired(true)
            )
            .addStringOption(option =>
                option.setName('username')
                    .setDescription('Their Beyond All Reason in-game username')
                    .setRequired(true)
            ),
        new SlashCommandBuilder()
            .setName('leaderboard')
            .setDescription('Display the server leaderboard for Beyond All Reason')
    ].map(command => command.toJSON());

    const rest = new REST({ version: '10' }).setToken(process.env.DISCORD_TOKEN);

    try {
        console.log('Started refreshing application (/) commands.');

        await rest.put(
            Routes.applicationCommands(process.env.DISCORD_CLIENT_ID),
            { body: commands },
        );

        console.log('Successfully reloaded application (/) commands.');
    } catch (error) {
        console.error(error);
    }
}

async function start() {
    if (!process.env.DISCORD_TOKEN) {
        console.error('ERROR: DISCORD_TOKEN environment variable is not set!');
        process.exit(1);
    }

    if (!process.env.DISCORD_CLIENT_ID) {
        console.error('ERROR: DISCORD_CLIENT_ID environment variable is not set!');
        process.exit(1);
    }

    await registerCommands();
    await client.login(process.env.DISCORD_TOKEN);
}

start();
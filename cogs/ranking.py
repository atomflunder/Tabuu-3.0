import asyncio
import json

import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands

import utils.check
from utils.ids import (
    Emojis,
    GuildIDs,
    GuildNames,
    TGArenaChannelIDs,
    TGMatchmakingRoleIDs,
)


class Ranking(commands.Cog):
    """Contains the ranked portion of our matchmaking system."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def get_ranked_role(
        self, member: discord.Member, guild: discord.Guild
    ) -> discord.Role:
        """Retrieves the ranked role of a member."""
        async with aiosqlite.connect("./db/database.db") as db:
            matching_player = await db.execute_fetchall(
                """SELECT elo FROM ranking WHERE user_id = :user_id""",
                {"user_id": member.id},
            )

        # If the player is not in the database,
        # this gets the default role.
        if len(matching_player) == 0:
            pingrole = discord.utils.get(
                guild.roles, id=TGMatchmakingRoleIDs.ELO_1050_ROLE
            )
        else:
            elo = matching_player[0][0]

            if elo >= 1300:
                pingrole = discord.utils.get(
                    guild.roles, id=TGMatchmakingRoleIDs.ELO_MAX_ROLE
                )
            elif elo >= 1200:
                pingrole = discord.utils.get(
                    guild.roles, id=TGMatchmakingRoleIDs.ELO_1300_ROLE
                )
            elif elo >= 1050:
                pingrole = discord.utils.get(
                    guild.roles, id=TGMatchmakingRoleIDs.ELO_1200_ROLE
                )
            elif elo >= 950:
                pingrole = discord.utils.get(
                    guild.roles, id=TGMatchmakingRoleIDs.ELO_1050_ROLE
                )
            elif elo >= 800:
                pingrole = discord.utils.get(
                    guild.roles, id=TGMatchmakingRoleIDs.ELO_950_ROLE
                )
            else:
                pingrole = discord.utils.get(
                    guild.roles, id=TGMatchmakingRoleIDs.ELO_800_ROLE
                )

        return pingrole

    def get_all_ranked_roles(self, guild: discord.Guild) -> list[discord.Role]:
        """Gets you every ranked role."""
        elo800role = discord.utils.get(
            guild.roles, id=TGMatchmakingRoleIDs.ELO_800_ROLE
        )
        elo950role = discord.utils.get(
            guild.roles, id=TGMatchmakingRoleIDs.ELO_950_ROLE
        )
        elo1050role = discord.utils.get(
            guild.roles, id=TGMatchmakingRoleIDs.ELO_1050_ROLE
        )
        elo1200role = discord.utils.get(
            guild.roles, id=TGMatchmakingRoleIDs.ELO_1200_ROLE
        )
        elo1300role = discord.utils.get(
            guild.roles, id=TGMatchmakingRoleIDs.ELO_1300_ROLE
        )
        elomaxrole = discord.utils.get(
            guild.roles, id=TGMatchmakingRoleIDs.ELO_MAX_ROLE
        )
        return [
            elo800role,
            elo950role,
            elo1050role,
            elo1200role,
            elo1300role,
            elomaxrole,
        ]

    def get_adjacent_roles(
        self, guild: discord.Guild, role: discord.Role
    ) -> list[discord.Role]:
        """Gets you your ranked role, as well as the ones above and below yours."""
        elo_roles = self.get_all_ranked_roles(guild)
        adjacent_roles = []

        index = elo_roles.index(role)

        try:
            adjacent_roles.append(elo_roles[index - 1])
        except IndexError:
            pass

        adjacent_roles.append(elo_roles[index])

        try:
            adjacent_roles.append(elo_roles[index + 1])
        except IndexError:
            pass

        return adjacent_roles

    async def remove_ranked_roles(
        self, member: discord.Member, guild: discord.Guild
    ) -> None:
        """Removes every ranked role a user has."""
        elo_roles = self.get_all_ranked_roles(guild)
        await member.remove_roles(*elo_roles)

    async def update_ranked_role(
        self, member: discord.Member, guild: discord.Guild, threshold: int = 5
    ) -> None:
        """This function updates the ranked roles of a member.
        The role change only triggers if the user does not have their current elo role,
        so its fine to remove ALL others first and then give the new one out.
        Also we only start to give these out at 5 games played automatically,
        or after 1 game if you want it using %rankstats.
        """
        async with aiosqlite.connect("./db/database.db") as db:
            matching_player = await db.execute_fetchall(
                """SELECT wins, losses FROM ranking WHERE user_id = :user_id""",
                {"user_id": member.id},
            )

        if len(matching_player) == 0:
            wins = 0
            losses = 0
        else:
            wins = matching_player[0][0]
            losses = matching_player[0][1]

        if wins + losses >= threshold:
            role = await self.get_ranked_role(member, guild)
            if role not in member.roles:
                await self.remove_ranked_roles(member, guild)
                await member.add_roles(role)

    async def create_ranked_profile(self, member: discord.Member) -> None:
        """Creates an entry in the ranked file for a user,
        if the user is not already in there.
        """
        async with aiosqlite.connect("./db/database.db") as db:
            matching_player = await db.execute_fetchall(
                """SELECT * FROM ranking WHERE user_id = :user_id""",
                {"user_id": member.id},
            )

            if len(matching_player) == 0:
                wins = 0
                losses = 0
                elo = 1000
                matches = ""

                await db.execute(
                    """INSERT INTO ranking VALUES (:user_id, :wins, :losses, :elo, :matches)""",
                    {
                        "user_id": member.id,
                        "wins": wins,
                        "losses": losses,
                        "elo": elo,
                        "matches": matches,
                    },
                )

                await db.commit()

    async def get_elo(self, member: discord.Member) -> int:
        """Gets the elo of a given member."""
        async with aiosqlite.connect("./db/database.db") as db:
            matching_member = await db.execute_fetchall(
                """SELECT elo FROM ranking WHERE user_id = :winner_id""",
                {"winner_id": member.id},
            )

        return matching_member[0][0]

    def calculate_elo(
        self, winner_elo: int, loser_elo: int, k: int = 32
    ) -> tuple[int, int, int]:
        """Calculates the new Elo value of the winner and loser.
        Uses the classic Elo calculations.
        """
        winner_expected = 1 / (1 + 10 ** ((loser_elo - winner_elo) / 400))
        loser_expected = 1 / (1 + 10 ** ((winner_elo - loser_elo) / 400))

        new_winner_elo = round(winner_elo + k * (1 - winner_expected))
        new_loser_elo = round(loser_elo + k * (0 - loser_expected))

        # the winner gains as much elo as the loser loses.
        difference = new_winner_elo - winner_elo

        return new_winner_elo, new_loser_elo, difference

    async def update_ranked_stats(
        self,
        winner: discord.Member,
        winnerelo: int,
        loser: discord.Member,
        loserelo: int,
    ) -> None:
        """Updates the stats of both players after a match."""
        async with aiosqlite.connect("./db/database.db") as db:
            await db.execute(
                """UPDATE ranking SET
                wins = wins + 1,
                matches = matches || "W",
                elo = :winnerelo
                WHERE user_id = :winner_id""",
                {"winnerelo": winnerelo, "winner_id": winner.id},
            )
            await db.execute(
                """UPDATE ranking SET
                losses = losses + 1,
                matches = matches || "L",
                elo = :loserelo
                WHERE user_id = :loser_id""",
                {"loserelo": loserelo, "loser_id": loser.id},
            )

            await db.commit()

    def store_ranked_ping(
        self, ctx: commands.Context, role: discord.Role, timestamp: float
    ) -> None:
        """Stores your ranked ping."""
        with open(r"./json/rankedpings.json", "r", encoding="utf-8") as f:
            rankedusers = json.load(f)

        rankedusers[f"{ctx.author.id}"] = {}
        rankedusers[f"{ctx.author.id}"] = {
            "rank": role.id,
            "channel": ctx.channel.id,
            "time": timestamp,
        }

        with open(r"./json/rankedpings.json", "w", encoding="utf-8") as f:
            json.dump(rankedusers, f, indent=4)

    def delete_ranked_ping(self, ctx: commands.Context) -> None:
        """Deletes your ranked ping."""
        with open(r"./json/rankedpings.json", "r", encoding="utf-8") as f:
            rankedusers = json.load(f)

        try:
            del rankedusers[f"{ctx.message.author.id}"]
        except KeyError:
            logger = self.bot.get_logger("bot.mm")
            logger.warning(
                f"Tried to delete a ranked ping by {str(ctx.message.author)} but the ping was already deleted."
            )

        with open(r"./json/rankedpings.json", "w", encoding="utf-8") as f:
            json.dump(rankedusers, f, indent=4)

    def get_recent_ranked_pings(self, timestamp: float) -> str:
        """Gets a list with all the recent ranked pings.
        We need a different approach than unranked here because we also store the rank role here.
        This is its own function because we need to export it.
        """
        with open(r"./json/rankedpings.json", "r", encoding="utf-8") as f:
            user_pings = json.load(f)

        list_of_searches = []

        for ping in user_pings:
            ping_rank = user_pings[f"{ping}"]["rank"]
            ping_channel = user_pings[f"{ping}"]["channel"]
            ping_timestamp = user_pings[f"{ping}"]["time"]

            difference = timestamp - ping_timestamp

            minutes = round(difference / 60)

            if minutes < 31:
                list_of_searches.append(
                    f"<@&{ping_rank}> | <@!{ping}>, in <#{ping_channel}>, {minutes} minutes ago\n"
                )

        list_of_searches.reverse()

        return "".join(list_of_searches) or "Looks like no one has pinged recently :("

    @commands.hybrid_command(aliases=["rankedmm", "rankedmatchmaking", "rankedsingles"])
    @commands.cooldown(1, 120, commands.BucketType.user)
    @app_commands.guilds(*GuildIDs.ALL_GUILDS)
    async def ranked(self, ctx: commands.Context) -> None:
        """Used for 1v1 competitive ranked matchmaking."""
        if ctx.channel.id not in TGArenaChannelIDs.RANKED_ARENAS:
            await ctx.send(
                "Please only use this command in the ranked matchmaking arenas.",
                ephemeral=True,
            )
            ctx.command.reset_cooldown(ctx)
            return

        timestamp = discord.utils.utcnow().timestamp()

        elo_role = await self.get_ranked_role(ctx.author, ctx.guild)

        self.store_ranked_ping(ctx, elo_role, timestamp)

        # Gets all of the other active pings.
        searches = self.get_recent_ranked_pings(timestamp)

        # Gathers all the roles we are gonna ping.
        pingroles = self.get_adjacent_roles(ctx.guild, elo_role)

        pings = ""

        for pingrole in pingroles:
            pings = f"{pings} {pingrole.mention}"

        embed = discord.Embed(
            title="Ranked pings in the last 30 Minutes:",
            description=searches,
            colour=discord.Colour.blue(),
        )

        if ctx.interaction:
            await ctx.send("Processing request...", ephemeral=True)

        mm_message = await ctx.channel.send(
            f"{ctx.author.mention} is looking for ranked matchmaking games! {pings}",
            embed=embed,
        )
        mm_thread = await mm_message.create_thread(
            name=f"Ranked Arena of {ctx.author.name}", auto_archive_duration=60
        )
        await mm_thread.add_user(ctx.author)
        await mm_thread.send(
            f"Hi there, {ctx.author.mention}! "
            "Please use this thread for communicating with your opponent and for reporting matches."
        )

        # Waits 30 mins and deletes the ping afterwards.
        await asyncio.sleep(1800)

        self.delete_ranked_ping(ctx)

    @commands.hybrid_command(aliases=["reportgame"], cooldown_after_parsing=True)
    @commands.cooldown(1, 41, commands.BucketType.user)
    @commands.guild_only()
    @app_commands.guilds(*GuildIDs.ALL_GUILDS)
    @app_commands.describe(user="The user you beat in the ranked match.")
    async def reportmatch(self, ctx: commands.Context, user: discord.Member) -> None:
        """The winner of the match uses this to report a ranked set.
        Updates the elo values and ranked roles of the players automatically.
        """

        # Since only threads have a parent_id, we need a special case for these to not throw any errors.
        if str(ctx.channel.type) == "public_thread":
            if ctx.channel.parent_id not in TGArenaChannelIDs.RANKED_ARENAS:
                await ctx.send(
                    "Please only use this command in the ranked matchmaking arenas or the threads within."
                )
                ctx.command.reset_cooldown(ctx)
                return
        else:
            if ctx.channel.id not in TGArenaChannelIDs.RANKED_ARENAS:
                await ctx.send(
                    "Please only use this command in the ranked matchmaking arenas or the threads within."
                )
                ctx.command.reset_cooldown(ctx)
                return

        # To prevent any kind of abuse.
        if user is ctx.author:
            await ctx.send("Don't report matches with yourself please.")
            ctx.command.reset_cooldown(ctx)
            return

        if user.bot:
            await ctx.send("Are you trying to play a match with bots?")
            ctx.command.reset_cooldown(ctx)
            return

        def check(message: discord.Message) -> bool:
            return (
                message.content.lower() == "y"
                and message.author == user
                and message.channel == ctx.channel
            )

        await ctx.send(
            f"The winner of the match {ctx.author.mention} vs. {user.mention} is: {ctx.author.mention}! \n"
            f"{user.mention} do you agree with the results? **Type y to verify.**"
        )
        try:
            await self.bot.wait_for("message", timeout=40.0, check=check)
        except asyncio.TimeoutError:
            await ctx.send(
                "You took too long to respond! Please try reporting the match again."
            )
            return

        await self.create_ranked_profile(ctx.author)
        await self.create_ranked_profile(user)

        winner_elo = await self.get_elo(ctx.author)
        loser_elo = await self.get_elo(user)

        winnerupdate, loserupdate, difference = self.calculate_elo(
            winner_elo, loser_elo
        )

        await self.update_ranked_stats(ctx.author, winnerupdate, user, loserupdate)

        await self.update_ranked_role(ctx.author, ctx.guild, 5)
        await self.update_ranked_role(user, ctx.guild, 5)

        await ctx.send(
            f"Game successfully reported!\n{ctx.author.mention} won!\n"
            f"Updated Elo score: {ctx.author.mention} = {winnerupdate} (+{difference}) | "
            f"{user.mention} = {loserupdate} (-{difference})"
        )

    @commands.hybrid_command(aliases=["forcereportgame"], cooldown_after_parsing=True)
    @app_commands.guilds(*GuildIDs.ALL_GUILDS)
    @app_commands.describe(
        winner="The winner of the match.", loser="The loser of the match."
    )
    @app_commands.default_permissions(administrator=True)
    @utils.check.is_moderator()
    @commands.cooldown(1, 41, commands.BucketType.user)
    async def forcereportmatch(
        self, ctx: commands.Context, winner: discord.Member, loser: discord.Member
    ) -> None:
        """Forcefully reports a match, in case someone abandons it or fails to report."""

        if ctx.guild.id != GuildIDs.TRAINING_GROUNDS:
            await ctx.send(
                f"This command is only available on the {GuildNames.TRAINING_GROUNDS} Server."
            )
            return

        def check(message: discord.Message) -> bool:
            return (
                message.content.lower() == "y"
                and message.author == ctx.author
                and message.channel == ctx.channel
            )

        await ctx.send(
            f"The winner of the match {winner.mention} vs. {loser.mention} is: {winner.mention}! \n"
            f"{ctx.author.mention}, is that result correct? **Type y to verify.**"
        )
        try:
            await self.bot.wait_for("message", timeout=40.0, check=check)
        except asyncio.TimeoutError:
            await ctx.send(
                "You took too long to respond! Please try reporting the match again."
            )
            return

        await self.create_ranked_profile(winner)
        await self.create_ranked_profile(loser)

        winner_elo = await self.get_elo(winner)
        loser_elo = await self.get_elo(loser)

        winnerupdate, loserupdate, difference = self.calculate_elo(
            winner_elo, loser_elo
        )

        await self.update_ranked_stats(winner, winnerupdate, loser, loserupdate)

        await self.update_ranked_role(winner, ctx.guild, 5)
        await self.update_ranked_role(loser, ctx.guild, 5)

        await ctx.send(
            f"Game successfully reported!\n{winner.mention} won!\n"
            f"Updated Elo score: {winner.mention} = {winnerupdate} (+{difference}) | "
            f"{loser.mention} = {loserupdate} (-{difference})\n"
            f"Game was forcefully reported by: {ctx.author.mention}"
        )

    @commands.hybrid_command(aliases=["rankedstats"])
    @app_commands.guilds(*GuildIDs.ALL_GUILDS)
    @app_commands.describe(member="The user you want to see the ranked stats of.")
    async def rankstats(
        self, ctx: commands.Context, member: discord.User = None
    ) -> None:
        """Gets you the ranked stats of a member, or your own if you dont specify a member.
        If you get your own, you get a choice of removing/adding your ranked role.
        """
        selfcheck = False
        if member is None or member == ctx.author:
            member = ctx.author
            selfcheck = True

        async with aiosqlite.connect("./db/database.db") as db:
            matching_member = await db.execute_fetchall(
                """SELECT * FROM ranking WHERE user_id = :user_id""",
                {"user_id": member.id},
            )

        _, wins, losses, elo, matches = matching_member[0]

        # Gets the last 5 games played and reverses that string.
        last5games = matches[-5:]
        gamelist = last5games[::-1]

        # Subs in the emojis.
        gamelist = gamelist.replace("W", Emojis.WIN_EMOJI)
        gamelist = gamelist.replace("L", Emojis.LOSE_EMOJI)

        embed = discord.Embed(title=f"Ranked stats of {str(member)}", colour=0x3498DB)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Elo score", value=elo, inline=True)
        embed.add_field(name="Wins", value=wins, inline=True)
        embed.add_field(name="Losses", value=losses, inline=True)
        embed.add_field(name="Last Matches", value=gamelist, inline=True)
        if (
            selfcheck is True
            and ctx.guild is not None
            and ctx.guild.id == GuildIDs.TRAINING_GROUNDS
        ):
            # I have to add the ctx.guild is not None check, otherwise we get an error in DMs.
            embed.set_footer(
                text="React within 120s to turn ranked notifications on or off until the next match"
            )

            embed_message = await ctx.send(embed=embed)

            await embed_message.add_reaction("????")
            await embed_message.add_reaction("????")

            def reaction_check(
                reaction: discord.Reaction, member: discord.Member
            ) -> bool:
                return (
                    member.id == ctx.author.id
                    and reaction.message.id == embed_message.id
                    and str(reaction.emoji) in {"????", "????"}
                )

            try:
                reaction, member = await self.bot.wait_for(
                    "reaction_add", timeout=120.0, check=reaction_check
                )
            except asyncio.TimeoutError:
                return
            else:
                if str(reaction.emoji) == "????":
                    await self.update_ranked_role(ctx.author, ctx.guild, 1)
                elif str(reaction.emoji) == "????":
                    await self.remove_ranked_roles(ctx.author, ctx.guild)

        else:
            await ctx.send(embed=embed)

    @commands.hybrid_command()
    @app_commands.guilds(*GuildIDs.ALL_GUILDS)
    @app_commands.default_permissions(administrator=True)
    @utils.check.is_moderator()
    async def leaderboard(self, ctx: commands.Context) -> None:
        """The Top 10 Players of our Ranked Matchmaking."""
        async with aiosqlite.connect("./db/database.db") as db:
            all_users = await db.execute_fetchall(
                """SELECT * FROM ranking ORDER BY elo DESC"""
            )

        embed_description = []
        # Only gets the top 10.
        for rank, user in enumerate(all_users[:10], start=1):
            user_id, wins, losses, elo, _ = user
            embed_description.append(
                f"{rank} | <@!{user_id}> | {elo} | {wins}/{losses}\n"
            )
        embedstats = "".join(embed_description)

        embed = discord.Embed(
            title=f"Top 10 Players of {GuildNames.TRAINING_GROUNDS} Ranked Matchmaking",
            description=f"**Rank | Username | Elo score | W/L**\n{embedstats}",
            colour=discord.Colour.blue(),
        )
        embed.set_thumbnail(url=ctx.guild.icon.url)
        embed.timestamp = discord.utils.utcnow()
        await ctx.send(embed=embed)

    @reportmatch.error
    async def reportmatch_error(
        self, ctx: commands.Context, error: commands.CommandError
    ) -> None:
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(
                f"You are on cooldown! Try again in {round(error.retry_after)} seconds."
            )
        elif isinstance(error, commands.NoPrivateMessage):
            await ctx.send(
                f"Please only use this command in the {GuildNames.TRAINING_GROUNDS} Discord Server."
            )
        elif isinstance(
            error, (commands.MissingRequiredArgument, commands.MemberNotFound)
        ):
            await ctx.send("Please mention the member that you beat in the match.")
        else:
            raise error

    @forcereportmatch.error
    async def forcereportmatch_error(
        self, ctx: commands.Context, error: commands.CommandError
    ) -> None:
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("Nice try, but you don't have the permissions to do that!")
        elif isinstance(
            error, (commands.MissingRequiredArgument, commands.MemberNotFound)
        ):
            await ctx.send(
                "Please mention the 2 members that have played in this match. "
                "First mention the winner, second mention the loser."
            )
        elif isinstance(error, commands.CommandOnCooldown):
            await ctx.send(
                f"You are on cooldown! Try again in {round(error.retry_after)} seconds."
            )
        else:
            raise error

    @rankstats.error
    async def rankstats_error(
        self, ctx: commands.Context, error: commands.CommandError
    ) -> None:
        if isinstance(
            error, (commands.CommandInvokeError, commands.HybridCommandError)
        ):
            await ctx.send("This user hasn't played a ranked match yet.")
        elif isinstance(error, commands.UserNotFound):
            await ctx.send(
                "I couldn't find this member, make sure you have the right one or just leave it blank."
            )
        else:
            raise error

    @ranked.error
    async def ranked_error(
        self, ctx: commands.Context, error: commands.CommandError
    ) -> None:
        if isinstance(error, commands.CommandOnCooldown):
            if ctx.channel.id not in TGArenaChannelIDs.RANKED_ARENAS:
                await ctx.send(
                    "Please only use this command in the ranked matchmaking arenas.",
                    ephemeral=True,
                )
                return

            timestamp = discord.utils.utcnow().timestamp()

            searches = self.get_recent_ranked_pings(timestamp)

            embed = discord.Embed(
                title="Ranked pings in the last 30 Minutes:",
                description=searches,
                colour=discord.Colour.blue(),
            )

            await ctx.send(
                f"{ctx.author.mention}, you are on cooldown for another {round((error.retry_after)/60)} minutes to use this command. \n"
                "In the meantime, here are the most recent ranked pings:",
                embed=embed,
            )
        else:
            raise error

    @leaderboard.error
    async def leaderboard_error(
        self, ctx: commands.Context, error: commands.CommandError
    ) -> None:
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("Nice try, but you don't have the permissions to do that!")
        else:
            raise error


async def setup(bot) -> None:
    await bot.add_cog(Ranking(bot))
    print("Ranking cog loaded")

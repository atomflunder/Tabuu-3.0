import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands

import utils.check
import utils.search
from utils.ids import GuildIDs


class MacroModal(discord.ui.Modal, title="Create a new macro"):
    def __init__(self):
        super().__init__()

    name = discord.ui.TextInput(
        label="Macro name:",
        style=discord.TextStyle.short,
        placeholder="The name of your macro.",
        max_length=50,
    )

    payload = discord.ui.TextInput(
        label="Macro Payload:",
        style=discord.TextStyle.paragraph,
        placeholder="The payload of your macro (Markdown supported).",
        max_length=1500,
    )

    async def on_submit(self, interaction: discord.Interaction):
        macro_name = self.name.value.lower()

        # list of every command together with the aliases registered.
        # cannot use those for a macro, obviously.
        command_list = [command.name for command in interaction.client.commands]
        for command in interaction.client.commands:
            command_list.extend(iter(command.aliases))

        async with aiosqlite.connect("./db/database.db") as db:
            matching_macro = await db.execute_fetchall(
                """SELECT name FROM macros WHERE name = :name""", {"name": macro_name}
            )

            # basic checks for invalid stuff
            if len(matching_macro) != 0:
                await interaction.response.send_message(
                    "This name was already taken. "
                    "If you want to update this macro please delete it first and then create it again."
                )
                return

            if macro_name in command_list:
                await interaction.response.send_message(
                    "This name is already being used for a command! Please use a different one."
                )
                return

            await db.execute(
                """INSERT INTO macros VALUES (:name, :payload, :uses, :author)""",
                {
                    "name": macro_name,
                    "payload": self.payload.value,
                    "uses": 0,
                    "author": interaction.user.id,
                },
            )

            await db.commit()

        await interaction.response.send_message(
            f"New macro `{macro_name}` was created.\nOutput:\n`{self.payload.value}`"
        )


class MacroButton(discord.ui.View):
    def __init__(self, author: discord.User):
        self.author = author
        super().__init__(timeout=60)

    @discord.ui.button(
        label="Create a new macro!", emoji="🖨️", style=discord.ButtonStyle.gray
    )
    async def macro_button(
        self, interaction: discord.Interaction, button: discord.Button
    ):
        await interaction.response.send_modal(MacroModal())
        self.stop()

    async def interaction_check(self, interaction: discord.Interaction):
        return interaction.user == self.author


class Macros(commands.Cog):
    """
    Contains the logic of adding/removing macros.
    As well as listening for them.
    """

    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # listens for the macros
        async with aiosqlite.connect("./db/database.db") as db:
            macro_names = await db.execute_fetchall("""SELECT name FROM macros""")

            for name in macro_names:
                # it returns tuples, so we need the first (and only) entry
                name = name[0]
                if (
                    len(message.content.split()) == 1
                    and message.content == (f"{self.bot.command_prefix}{name}")
                    or message.content.startswith(f"{self.bot.command_prefix}{name} ")
                ):
                    matching_macro = await db.execute_fetchall(
                        """SELECT payload FROM macros WHERE name = :name""",
                        {"name": name},
                    )
                    payload = matching_macro[0][0]
                    await message.channel.send(payload)

                    self.bot.commands_ran += 1
                    await db.execute(
                        """UPDATE macros SET uses = uses + 1 WHERE name = :name""",
                        {"name": name},
                    )
                    await db.commit()

    @commands.command()
    @utils.check.is_moderator()
    async def createmacro(self, ctx):
        """
        Creates a new macro with the desired name and payload and saves it in the database.
        """
        view = MacroButton(ctx.author)

        await ctx.send(view=view)

    @commands.command()
    @utils.check.is_moderator()
    async def deletemacro(self, ctx, name: str):
        """
        Deletes a macro with the specified name from the database.
        """
        async with aiosqlite.connect("./db/database.db") as db:
            macro_names = await db.execute_fetchall(
                """SELECT * FROM macros WHERE name = :name""", {"name": name}
            )

            # if the macro does not exist we want some kind of error message for the user
            if len(macro_names) == 0:
                await ctx.send(f"The macro `{name}` was not found. Please try again.")
                return

            await db.execute(
                """DELETE FROM macros WHERE name = :name""", {"name": name}
            )

            await db.commit()

        await ctx.send(f"Deleted macro `{name}`")

    @commands.hybrid_command(aliases=["macros", "listmacros", "macrostats"])
    @app_commands.guilds(*GuildIDs.ALL_GUILDS)
    @app_commands.describe(macro="The macro you want to see the stats of.")
    async def macro(self, ctx, *, macro: str = None):
        """
        Gives you detailed information about a macro, or lists every macro saved.
        """
        if macro is None:
            async with aiosqlite.connect("./db/database.db") as db:
                macro_list = await db.execute_fetchall("""SELECT name FROM macros""")

            # it returns a list of tuples,
            # so we need to extract them
            macro_names = [m[0] for m in macro_list]
            await ctx.send(
                "The registered macros are:\n"
                f"`{self.bot.command_prefix}{f', {self.bot.command_prefix}'.join(macro_names)}`"
            )
            return

        async with aiosqlite.connect("./db/database.db") as db:
            matching_macro = await db.execute_fetchall(
                """SELECT * FROM macros WHERE name = :name""", {"name": macro}
            )

        # if the macro does not exist we want some kind of error message for the user
        if len(matching_macro) == 0:
            await ctx.send(
                f"I could not find this macro. List all macros with `{self.bot.command_prefix}macros`."
            )
            return

        name, payload, uses, author_id = matching_macro[0]

        embed = discord.Embed(
            title="Macro info",
            color=0x007377,
            description=f"**Name:** {self.bot.command_prefix}{name}\n**Uses:** {uses}\n"
            f"**Author:**<@{author_id}>\n**Output:**\n{payload}\n",
        )

        await ctx.send(embed=embed)

    @macro.autocomplete("macro")
    async def macro_autocomplete(self, interaction: discord.Interaction, current: str):
        async with aiosqlite.connect("./db/database.db") as db:
            macros = await db.execute_fetchall("""SELECT name FROM macros""")

        return utils.search.autocomplete_choices(current, [m[0] for m in macros])

    # the error handling for the commands above
    # fairly self-explanatory
    @createmacro.error
    async def createmacro_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("Nice try, but you don't have the permissions to do that!")
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(
                "You need to input the macro name and then the desired output."
            )
        elif isinstance(
            error, (commands.ExpectedClosingQuoteError, commands.UnexpectedQuoteError)
        ):
            await ctx.send(
                "Please do not create a macro with the `\"` letter. Use `'` instead."
            )
        else:
            raise error

    @deletemacro.error
    async def deletemacro_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("Nice try, but you don't have the permissions to do that!")
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send("You need to input the macro you want to delete.")
        else:
            raise error


async def setup(bot):
    await bot.add_cog(Macros(bot))
    print("Macros cog loaded")

import discord


class TemplateView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Button",
        custom_id="button_1",
        style=discord.ButtonStyle.primary,
        emoji="👍",
    )
    async def button_1(
        self, button: discord.ui.Button, interaction: discord.Interaction
    ):
        pass

    @discord.ui.button(
        label="Button",
        custom_id="button_2",
        style=discord.ButtonStyle.danger,
        emoji="👎",
    )
    async def button_2(
        self, button: discord.ui.Button, interaction: discord.Interaction
    ):
        pass

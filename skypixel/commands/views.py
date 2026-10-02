from contextlib import suppress

import disnake

from skypixel import discord as utils


class OwnedView(disnake.ui.View):
    def __init__(self, inter: disnake.Interaction, *, timeout: float = 180):
        super().__init__(timeout=timeout)
        self.inter = inter
        self.message: disnake.Message | None = None

    async def interaction_check(self, interaction: disnake.Interaction) -> bool:
        if interaction.user == self.inter.user:
            return True
        await interaction.response.send_message(
            embed=utils.make_error(
                "Not your interaction!",
                "You cannot interact with another user's buttons.",
            ),
            ephemeral=True,
        )
        return False

    async def on_timeout(self) -> None:
        for item in self.children:
            if isinstance(item, disnake.ui.Button):
                item.disabled = True
        with suppress(disnake.HTTPException):
            if self.message is not None:
                await self.message.edit(view=self)
            else:
                await self.inter.edit_original_message(view=self)

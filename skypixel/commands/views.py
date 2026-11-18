from contextlib import suppress

import disnake

from skypixel import embed_utils


class OwnedView(disnake.ui.View):
    def __init__(
        self, inter: disnake.Interaction[disnake.Client], *, timeout: float = 180
    ) -> None:
        super().__init__(timeout=timeout)
        self.inter: disnake.Interaction[disnake.Client] = inter

    async def interaction_check(
        self, interaction: disnake.MessageInteraction[disnake.Client]
    ) -> bool:
        if interaction.user == self.inter.user:
            return True
        await interaction.response.send_message(
            embed=embed_utils.make_error(
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
            await self.inter.edit_original_message(view=self)

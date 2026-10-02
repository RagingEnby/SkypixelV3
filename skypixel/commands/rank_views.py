import asyncio
import logging
from contextlib import suppress
from typing import cast

import disnake

from skypixel import utils
from skypixel.commands.views import OwnedView

logger = logging.getLogger(__name__)


class GotoPageModal(disnake.ui.Modal):
    def __init__(self, view: "RankListView"):
        super().__init__(
            title="Go to page",
            components=[
                disnake.ui.TextInput(
                    label="Page Number",
                    placeholder="Enter page number",
                    style=disnake.TextInputStyle.short,
                    min_length=1,
                    max_length=6,
                    custom_id="goto_page",
                )
            ],
        )
        self.view = view

    async def callback(self, inter: disnake.ModalInteraction):
        page_str = inter.text_values.get("goto_page")
        try:
            page = int(page_str or "")
        except (TypeError, ValueError):
            return await inter.response.send_message(
                embed=utils.make_error("Invalid Page", "Please enter a valid number"),
                ephemeral=True,
            )
        if page < 1 or page > len(self.view.embeds):
            return await inter.response.send_message(
                embed=utils.make_error(
                    "Invalid Page",
                    f"Please choose a page between 1 and {len(self.view.embeds)}",
                ),
                ephemeral=True,
            )
        self.view.page = page - 1
        await asyncio.gather(self.view._update_buttons(), inter.response.defer())
        with suppress(disnake.NotFound, disnake.HTTPException):
            await self.view.inter.edit_original_message(
                embed=self.view.embeds[self.view.page], view=self.view
            )


class RankListView(OwnedView):
    def __init__(self, embeds: list[disnake.Embed], inter: disnake.Interaction):
        logger.debug("initializing RankListView()")
        super().__init__(inter)
        self.embeds = embeds
        self.inter = inter
        self.page = 0
        self.message: disnake.Message | None = None

    async def _update_buttons(self):
        logger.debug("updating buttons")
        prev_btn = cast(disnake.ui.Button, self.children[0])
        next_btn = cast(disnake.ui.Button, self.children[2])
        prev_btn.disabled = self.page == 0
        next_btn.disabled = self.page == len(self.embeds) - 1
        current_embed = self.embeds[self.page]
        current_embed.set_footer(text=f"Page {self.page + 1}/{len(self.embeds)}")

    @disnake.ui.button(style=disnake.ButtonStyle.blurple, emoji="⬅️", row=0)
    async def previous(self, _, interaction: disnake.Interaction):
        logger.debug("previous button clicked")
        self.page = max(self.page - 1, 0)
        await self._update_buttons()
        await interaction.response.edit_message(embed=self.embeds[self.page], view=self)

    @disnake.ui.button(style=disnake.ButtonStyle.gray, emoji="🔢", row=0)
    async def goto_page(self, _, interaction: disnake.Interaction):
        await interaction.response.send_modal(GotoPageModal(self))

    @disnake.ui.button(style=disnake.ButtonStyle.blurple, emoji="➡️", row=0)
    async def next(self, _, interaction: disnake.Interaction):
        logger.debug("next button clicked")
        self.page = min(self.page + 1, len(self.embeds) - 1)
        await self._update_buttons()
        await interaction.response.edit_message(embed=self.embeds[self.page], view=self)

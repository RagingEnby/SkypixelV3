from contextlib import suppress

import disnake

from skypixel import embed_utils
from skypixel.commands.views import OwnedView


class GotoPageModal(disnake.ui.Modal):
    def __init__(self, view: RankListView) -> None:
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
        self.view: RankListView = view

    async def callback(self, inter: disnake.ModalInteraction[disnake.Client]) -> None:
        page_str = inter.text_values.get("goto_page")
        try:
            page = int(page_str or "")
        except (TypeError, ValueError):  # fmt: skip
            return await inter.response.send_message(
                embed=embed_utils.make_error(
                    "Invalid Page", "Please enter a valid number"
                ),
                ephemeral=True,
            )
        if page < 1 or page > len(self.view.embeds):
            return await inter.response.send_message(
                embed=embed_utils.make_error(
                    "Invalid Page",
                    f"Please choose a page between 1 and {len(self.view.embeds)}",
                ),
                ephemeral=True,
            )
        self.view.page = page - 1
        self.view.update_buttons()
        await inter.response.defer()
        with suppress(disnake.NotFound, disnake.HTTPException):
            await self.view.inter.edit_original_message(
                embed=self.view.embeds[self.view.page], view=self.view
            )


class RankListView(OwnedView):
    def __init__(
        self, embeds: list[disnake.Embed], inter: disnake.Interaction[disnake.Client]
    ) -> None:
        if not embeds:
            raise ValueError("The rank list needs at least one page.")
        super().__init__(inter)
        self.embeds: list[disnake.Embed] = embeds
        self.page: int = 0
        self.update_buttons()

    def update_buttons(self) -> None:
        self.previous.disabled = self.page == 0
        self.next.disabled = self.page == len(self.embeds) - 1
        current_embed = self.embeds[self.page]
        current_embed.set_footer(text=f"Page {self.page + 1}/{len(self.embeds)}")

    # disnake types the button callback's interaction as MessageInteraction
    # with no client type, so pyright sees the decorator as partly unknown.
    @disnake.ui.button(style=disnake.ButtonStyle.blurple, emoji="⬅️", row=0)  # pyright: ignore[reportUnknownMemberType]
    async def previous(
        self,
        _: disnake.ui.Button[RankListView],
        interaction: disnake.MessageInteraction[disnake.Client],
    ) -> None:
        self.page = max(self.page - 1, 0)
        self.update_buttons()
        await interaction.response.edit_message(embed=self.embeds[self.page], view=self)

    @disnake.ui.button(style=disnake.ButtonStyle.gray, emoji="🔢", row=0)  # pyright: ignore[reportUnknownMemberType]
    async def goto_page(
        self,
        _: disnake.ui.Button[RankListView],
        interaction: disnake.MessageInteraction[disnake.Client],
    ) -> None:
        await interaction.response.send_modal(GotoPageModal(self))

    @disnake.ui.button(style=disnake.ButtonStyle.blurple, emoji="➡️", row=0)  # pyright: ignore[reportUnknownMemberType]
    async def next(
        self,
        _: disnake.ui.Button[RankListView],
        interaction: disnake.MessageInteraction[disnake.Client],
    ) -> None:
        self.page = min(self.page + 1, len(self.embeds) - 1)
        self.update_buttons()
        await interaction.response.edit_message(embed=self.embeds[self.page], view=self)

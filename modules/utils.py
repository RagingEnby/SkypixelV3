import disnake


def make_error(title: str, *args) -> disnake.Embed:
    return disnake.Embed(
        title=title,
        description='\n'.join([str(arg) for arg in args]),
        color=disnake.Color.red()
    )
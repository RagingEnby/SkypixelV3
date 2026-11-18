"""Format numbers, timestamps, and Minecraft text for Discord."""

import datetime
import re
from zoneinfo import ZoneInfo

import disnake

from skypixel import constants

COLOR_CODE_PATTERN: re.Pattern[str] = re.compile(r"[§&][0-9a-fA-Fklmnor]")
# Minecraft format codes and their ansi escapes: bold, strikethrough, underline,
# italic, and reset. Obfuscated text (k) has no escape and becomes OBFUSCATED.
ANSI_FORMATS: dict[str, int] = {"l": 1, "m": 9, "n": 4, "o": 3, "r": 0}
OBFUSCATED: str = "\u2592"
# Old items carry their creation time as text in Hypixel's server time, which
# is US Eastern.
HYPIXEL_TIMEZONE: ZoneInfo = ZoneInfo("America/New_York")


def remove_color_codes(string: str) -> str:
    return COLOR_CODE_PATTERN.sub("", string)


def to_ansi(string: str) -> str:
    """Turn Minecraft color codes into the escapes of a Discord ansi code block.

    Colors use 24-bit escapes with Minecraft's exact RGB values. Obfuscated
    text shows as a block character in place of each letter.
    """
    if not COLOR_CODE_PATTERN.search(string):
        return string
    parts: list[str] = []
    obfuscated = False
    position = 0
    for match in COLOR_CODE_PATTERN.finditer(string):
        parts.append(_obfuscate(string[position : match.start()], obfuscated))
        position = match.end()
        code = match.group()[1].lower()
        if code in constants.COLOR_CODES:
            # A Minecraft color code also clears every format.
            obfuscated = False
            red, green, blue = constants.COLOR_CODES[code].to_bytes(3)
            parts.append(f"\u001b[0;38;2;{red};{green};{blue}m")
        elif code == "k":
            obfuscated = True
        else:
            obfuscated = obfuscated and code != "r"
            parts.append(f"\u001b[{ANSI_FORMATS[code]}m")
    parts.append(_obfuscate(string[position:], obfuscated))
    return "".join(parts) + "\u001b[0m"


def _obfuscate(text: str, obfuscated: bool) -> str:
    if not obfuscated:
        return text
    return "".join(char if char.isspace() else OBFUSCATED for char in text)


def ansi_block(lines: list[str]) -> str:
    """Return a code block that shows the lines with their Minecraft colors."""
    return "```ansi\n" + "\n".join(to_ansi(line) for line in lines) + "```"


def esc_mrkdwn(string: str) -> str:
    return disnake.utils.escape_markdown(string)


def numerize(num: int | float) -> str:
    if abs(num) < 1000:
        return str(num)
    num = round(num)
    suffixes = ("", "K", "M", "B", "T")
    magnitude = 0
    while abs(num) >= 1000 and magnitude < len(suffixes) - 1:
        num /= 1000
        magnitude += 1
    # 999,999 becomes 999.999, which prints as 1000.00. Move it to the next suffix.
    if abs(round(num, 2)) >= 1000 and magnitude < len(suffixes) - 1:
        num /= 1000
        magnitude += 1
    return f"{num:.2f}".rstrip("0").rstrip(".") + suffixes[magnitude]


def commaize(num: int | float) -> str:
    return f"{num:,}"


def timestamp_to_unix(date_str: str) -> int:
    if "L" in date_str:
        return int(date_str.replace("L", ""))
    try:
        return int(date_str)
    except ValueError:
        pass
    for date_format in ("%m/%d/%y %I:%M %p", "%d/%m/%y %H:%M"):
        try:
            parsed = datetime.datetime.strptime(date_str, date_format)
            return int(parsed.replace(tzinfo=HYPIXEL_TIMEZONE).timestamp())
        except ValueError:
            continue
    raise ValueError(f"Invalid timestamp: {date_str}")


def normalize_timestamp(timestamp: str | int) -> int:
    if isinstance(timestamp, str):
        timestamp = timestamp_to_unix(timestamp)
    return timestamp if abs(timestamp) < 100_000_000_000 else timestamp // 1000

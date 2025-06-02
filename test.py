from javascript import require, On, Once, AsyncTask, once, off
import json
from contextlib import suppress

import constants


mineflayer = require('mineflayer')
bot = mineflayer.createBot({
    'host': 'alpha.hypixel.net',
    'port': 25565,
    'username': constants.MINEFLAYER_EMAIL,
    'auth': 'microsoft',
    'hideErrors': False,
    'version': '1.21.4'
})


def format_kick_reason(reason: dict[str, list[dict[str, str], str]]) -> str:
    formatted = str(reason.get('text', ''))
    for extra in reason.get('extra', []):
        color = extra.get('color', 'white')
        color_code = constants.COLOR_CODE_NAMES.get(color, 'f')
        formatted += f"&{color_code}{extra.get('text', '')}"
    return formatted


@On(bot, 'chat')
def onChat(this, user, message, *rest):
    print(f'{user} said "{message}"')

@On(bot, 'login')
def onLogin(this):
    print('Logged in!')
    bot.quit()


@On(bot, 'kicked')
def onKicked(this, reason, loggedIn):
    with suppress(json.JSONDecodeError):
        reason = json.loads(reason)
    reason = format_kick_reason(reason)
    print(f'Kicked for {reason} (loggedIn: {loggedIn}')
    exit()
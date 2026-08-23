#
# Copyright (C) 2021-2022 by TheAloneteam@Github, < https://github.com/TheAloneTeam >.
#
# This file is part of < https://github.com/TheAloneTeam/AloneMusic > project,
# and is released under the "GNU v3.0 License Agreement".
# Please see < https://github.com/TheAloneTeam/AloneMusic/blob/master/LICENSE >
#
# All rights reserved.

from pyrogram import filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

import random
from AloneMusic import app, YouTube
from AloneMusic.core.call import Alone
from AloneMusic.utils.database import (autoplay_off, autoplay_on,
                                       is_autoplay_on, get_lang)
from AloneMusic.utils.decorators import language, AdminRightsCheck
from config import BANNED_USERS
from strings import get_string


@app.on_message(filters.command(["autoplay"]) & filters.group & ~BANNED_USERS)
@language
async def autoplay_command(client, message: Message, _):
    if len(message.command) < 2:
        playmode = await is_autoplay_on(message.chat.id)
        buttons = [
            [
                InlineKeyboardButton(
                    text="⌯ єɴʌʙʟє ⌯" if not playmode else "⌯ ᴅɪsʌʙʟє ⌯",
                    callback_data=f"AUTOPLAYCHANGE"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="⌯ ᴄʟᴏsє ⌯", callback_data="close"
                ),
            ],
        ]
        return await message.reply_text(
            _["autoplay_1"],
            reply_markup=InlineKeyboardMarkup(buttons),
        )
    state = message.text.split(None, 1)[1].strip().lower()
    if state == "on":
        await autoplay_on(message.chat.id)
        await message.reply_text("» ʌᴜᴛᴏᴘʟʌʏ єɴʌʙʟєᴅ sᴜᴄᴄєssғᴜʟʟʏ.")
    elif state == "off":
        await autoplay_off(message.chat.id)
        await message.reply_text("» ʌᴜᴛᴏᴘʟʌʏ ᴅɪsʌʙʟєᴅ sᴜᴄᴄєssғᴜʟʟʏ.")
    else:
        await message.reply_text("» ɪɴᴠʌʟɪᴅ ʌʀɢᴜϻєɴᴛ. ᴜsє ᴏɴ/ᴏғғ.")

@app.on_message(filters.command(["askip"]) & filters.group & ~BANNED_USERS)
@AdminRightsCheck
async def askip_command(client, message: Message, _, chat_id):
    from AloneMusic.misc import db
    from AloneMusic.utils.stream.stream import stream

    if not await is_autoplay_on(chat_id):
        return await message.reply_text("» ɴᴏᴛ ᴏɴ ʌᴜᴛᴏ ᴘʟʌʏ ᴘʟєʌsє ᴏɴ ʌᴜᴛᴏ ᴘʟʌʏ ʌɴᴅ ᴛʀʏ ʌɢʌɪɴ.")

    check = db.get(chat_id)
    if not check:
        return

    old_mystic = check[0].get("mystic")
    if old_mystic:
        try:
            await old_mystic.delete()
        except:
            pass

    popped = check.pop(0)
    try:
        vidid = popped["vidid"]
        related = await YouTube.get_related_videos(vidid)
        if not related:
            return

        video_id = random.choice(related)
        details, track_id = await YouTube.track(video_id, True)

        await stream(
            _,
            old_mystic,
            popped["user_id"],
            details,
            chat_id,
            popped["by"],
            popped["chat_id"],
            video=True if popped["streamtype"] == "video" else False,
            streamtype="youtube",
            forceplay=True,
        )
    except:
        pass

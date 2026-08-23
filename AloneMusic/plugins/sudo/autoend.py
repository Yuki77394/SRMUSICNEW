#
# Copyright (C) 2021-2022 by TheAloneteam@Github, < https://github.com/TheAloneTeam >.
#
# This file is part of < https://github.com/TheAloneTeam/AloneMusic > project,
# and is released under the "GNU v3.0 License Agreement".
# Please see < https://github.com/TheAloneTeam/AloneMusic/blob/master/LICENSE >
#
# All rights reserved.

from pyrogram import filters
from pyrogram.types import Message

from AloneMusic import app
from AloneMusic.misc import SUDOERS
from AloneMusic.utils.database import (autoend_off, autoend_on, autoleave_off,
                                       autoleave_on, is_autoend, is_autoleave)


@app.on_message(filters.command("autoend") & SUDOERS)
async def auto_end_stream(_, message: Message):
    zerostate = await is_autoend()
    usage = f"<b>ᴇxᴀᴍᴘʟᴇ :</b>\n\n/autoend [ᴇɴᴀʙʟᴇ | ᴅɪsᴀʙʟᴇ]\n\n Current state : {zerostate}"
    if len(message.command) != 2:
        return await message.reply_text(usage)
    state = message.text.split(None, 1)[1].strip().lower()
    if state in ["enable", "on", "yes"]:
        await autoend_on()
        await message.reply_text("» ʌᴜᴛᴏ єɴᴅ sᴛʀєʌϻ єɴʌʙʟєᴅ.\n\nʌssɪsᴛʌɴᴛ ᴡɪʟʟ ʌᴜᴛᴏϻʌᴛɪᴄʌʟʟʏ ʟєʌᴠє ᴛʜє ᴠɪᴅєᴏᴄʜʌᴛ ʌғᴛєʀ ғєᴡ ϻɪɴs ᴡʜєɴ ɴᴏ ᴏɴє ɪs ʟɪsᴛєɴɪɴɢ."
        )
    elif state in ["disable", "off", "no"]:
        await autoend_off()
        await message.reply_text("» ʌᴜᴛᴏ єɴᴅ sᴛʀєʌϻ ᴅɪsʌʙʟєᴅ.")
    else:
        await message.reply_text(usage)


@app.on_message(filters.command("autoleave") & SUDOERS)
async def auto_leave_chat(_, message: Message):
    zerostate = await is_autoleave()
    usage = f"<b>ᴇxᴀᴍᴘʟᴇ :</b>\n\n/autoleave [ᴇɴᴀʙʟᴇ | ᴅɪsᴀʙʟᴇ]\n\n Current state : {zerostate}"
    if len(message.command) != 2:
        return await message.reply_text(usage)
    state = message.text.split(None, 1)[1].strip().lower()
    if state in ["enable", "on", "yes"]:
        await autoleave_on()
        await message.reply_text("» ʌᴜᴛᴏ ʟєʌᴠє ᴄʜʌᴛ єɴʌʙʟєᴅ.\n\nʌssɪsᴛʌɴᴛ ᴡɪʟʟ ʌᴜᴛᴏϻʌᴛɪᴄʌʟʟʏ ʟєʌᴠє ᴛʜє ᴠɪᴅєᴏᴄʜʌᴛ ʌғᴛєʀ ғєᴡ ϻɪɴs ᴡʜєɴ ɴᴏ ᴏɴє ɪs ʟɪsᴛєɴɪɴɢ."
        )
    elif state in ["disable", "off", "no"]:
        await autoleave_off()
        await message.reply_text("» ʌᴜᴛᴏ ʟєʌᴠє ᴄʜʌᴛ ᴅɪsʌʙʟєᴅ.")
    else:
        await message.reply_text(usage)

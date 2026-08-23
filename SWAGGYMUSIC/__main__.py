#
# Copyright (C) 2021-2022 by TheAloneteam@Github, < https://github.com/TheAloneTeam >.
# This file is part of < https://github.com/TheAloneTeam/SWAGGYMUSIC > project,
# and is released under the "GNU v3.0 License Agreement".
# Please see < https://github.com/TheAloneTeam/SWAGGYMUSIC/blob/master/LICENSE >
#
# All rights reserved.

import asyncio
import importlib

import static_ffmpeg
from pyrogram import idle
from pytgcalls.exceptions import NoActiveGroupCall

import config
from SWAGGYMUSIC import LOGGER, app, userbot
from SWAGGYMUSIC.core.call import Alone
from SWAGGYMUSIC.misc import sudo
from SWAGGYMUSIC.plugins import ALL_MODULES
from SWAGGYMUSIC.utils.database import get_banned_users, get_gbanned
from config import BANNED_USERS


async def init():
    static_ffmpeg.add_paths()
    if (
        not config.STRING1
        and not config.STRING2
        and not config.STRING3
        and not config.STRING4
        and not config.STRING5
    ):
        LOGGER(__name__).error("Assistant client variables not defined, exiting...")
        exit()
    await sudo()
    try:
        users = await get_gbanned()
        for user_id in users:
            BANNED_USERS.add(user_id)
        users = await get_banned_users()
        for user_id in users:
            BANNED_USERS.add(user_id)
    except:
        pass
    await app.start()
    for all_module in ALL_MODULES:
        importlib.import_module("SWAGGYMUSIC.plugins" + all_module)
    LOGGER("SWAGGYMUSIC.plugins").info("Successfully Imported Modules...")
    await userbot.start()
    await Alone.start()
    try:
        await Alone.stream_call("https://te.legra.ph/file/29f784eb49d230ab62e9e.mp4")
    except NoActiveGroupCall:
        LOGGER("SWAGGYMUSIC").error(
            "Please turn on the videochat of your log group/channel.\n\nStopping Bot..."
        )
        exit()
    except:
        pass
    await Alone.decorators()
    LOGGER("SWAGGYMUSIC").info(
        "ʙᴏᴛ sᴛᴀʀᴛᴇᴅ sᴜᴄᴄᴇssғᴜʟʟʏ, ɴᴏᴡ ɢɪʙ ʏᴏᴜʀ ɢɪʀʟғʀɪᴇɴᴅ ᴄʜᴜᴛ ɪɴ @TheAloneTeam"
    )
    await idle()
    await app.stop()
    await userbot.stop()
    LOGGER("SWAGGYMUSIC").info("Stopping 𝚻հҽ 𝚨Łꪮⲛ𝛆 🚩𝗧ε᧘‌ᴍ Bot...")


if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(init())

#
# Copyright (C) 2021-2022 by Yuki77394@Github, < https://github.com/Yuki77394 >.
#
# This file is part of < https://github.com/Yuki77394/SWAGGYMUSIC > project,
# and is released under the "GNU v3.0 License Agreement".
# Please see < https://github.com/TheAloneTeam/SWAGGYMUSIC/blob/master/LICENSE >
#
# All rights reserved.

import os

from config import autoclean


async def auto_clean(popped):
    try:
        rem = popped["file"]
        try:
            autoclean.remove(rem)
        except ValueError:
            # The file may already have been removed from the tracking list
            # by another cleanup path. Deletion below remains best-effort.
            pass
        count = autoclean.count(rem)
        if count == 0:
            if "vid_" not in rem and "live_" not in rem and "index_" not in rem:
                try:
                    os.remove(rem)
                except:
                    pass
    except:
        pass
    try:
        mystic = popped.get("mystic")
        if mystic:
            await mystic.delete()
    except:
        pass

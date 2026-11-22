# Copyright (C) 2026 EMCS (Gremlin Ex (GEX) contributions)
#
# Written for Gremlin Ex by Muchimi
# Some portions are derived from the original 2019 Joystick Gremlin by Lionel Ott and other contributors.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

# from __future__ import annotations  # deprecated with python 3.14+
# from gtts import gTTS
# import sys
# import collections
# import os
# import shutil
# import copy
# import logging
# import traceback
# import json
# import time

# syslog = logging.getLogger("system")

# class GTTS:

#     def gttsSpeak(text: str, lang: str = "en", filename: str = "temp_speech.mp3"):
#         """Converts text to speech using Google's free online API and plays it."""
#         try:
#             from gtts import gTTS

#             # 1. Fetch audio from Google's online API
#             tts = gTTS(text=text, lang=lang, slow=False)
#             tts.save(filename)
#         except Exception:
#             syslog.error("Error in gttsSpeak")
#             return
#         return filename


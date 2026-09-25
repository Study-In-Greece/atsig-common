# atsig_common/enums.py
"""
Shared domain enums used across multiple atsig services (programmes-api,
applications-api). These values form part of the event/snapshot contract
between services — keep programmes-api and applications-api in sync when
changing this file.
"""

import enum


class ProgrammeType(enum.StrEnum):
    msc = "Master"
    bsc = "Bachelor"
    short_term = "Short Term"


class Languages(enum.StrEnum):
    greek = "Greek"
    english = "English"
    french = "French"
    german = "German"
    italian = "Italian"
    russian = "Russian"
    turkish = "Turkish"
    spanish = "Spanish"


class RestrictionMode(enum.StrEnum):
    none = "none"
    deny_list = "deny_list"
    allow_list = "allow_list"


class AttendanceMode(enum.StrEnum):
    full_time = "full_time"
    part_time = "part_time"
    undetermined = "undetermined"

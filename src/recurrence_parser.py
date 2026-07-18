"""
Parse Todoist natural-language recurrence strings into the Repeating TODOs
plugin's RecurrenceData format.

Todoist `due.string` examples:
    "every day"
    "every 2 days"
    "every week"
    "every mon, fri"
    "every other week"
    "every month on the 2nd"
    "every second Friday"
    "every year on Jan 1st"
    "every 3 hours"
    "every 30 minutes"
    "every work day"      → weekdays (mon-fri)
    "every weekend"       → sat, sun
    "every! day"          → completion-based (the '!' means reset from completion date)
    "ev day"              → abbreviated forms

Maps to RecurrenceData:
    {
        "enabled": true,
        "interval": "day"|"week"|"month"|"year"|"hour"|"minute",
        "intervalNumber": 1,
        "weekSunday": false, "weekMonday": true, ...,
        "monthOrdinal": ""|"first"|"second"|"third"|"fourth"|"last",
        "monthWeekday": ""|"sunday"|...|"saturday",
        "stopType": "never",
        "stopDate": null,
        "stopNumber": 1
    }
"""

import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RecurrenceData:
    enabled: bool = False
    interval: str = "day"          # minute, hour, day, week, month, year
    intervalNumber: int = 1
    weekSunday: bool = False
    weekMonday: bool = False
    weekTuesday: bool = False
    weekWednesday: bool = False
    weekThursday: bool = False
    weekFriday: bool = False
    weekSaturday: bool = False
    monthOrdinal: str = ""         # "", first, second, third, fourth, last
    monthWeekday: str = ""         # "", sunday, monday, ..., saturday
    stopType: str = "never"        # never, date, number
    stopDate: Optional[str] = None
    stopNumber: int = 1

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "interval": self.interval,
            "intervalNumber": self.intervalNumber,
            "weekSunday": self.weekSunday,
            "weekMonday": self.weekMonday,
            "weekTuesday": self.weekTuesday,
            "weekWednesday": self.weekWednesday,
            "weekThursday": self.weekThursday,
            "weekFriday": self.weekFriday,
            "weekSaturday": self.weekSaturday,
            "monthOrdinal": self.monthOrdinal,
            "monthWeekday": self.monthWeekday,
            "stopType": self.stopType,
            "stopDate": self.stopDate,
            "stopNumber": self.stopNumber,
        }


# Weekday name → field mappings
WEEKDAY_MAP = {
    "sun": "weekSunday", "sunday": "weekSunday",
    "mon": "weekMonday", "monday": "weekMonday",
    "tue": "weekTuesday", "tues": "weekTuesday", "tuesday": "weekTuesday",
    "wed": "weekWednesday", "wednesday": "weekWednesday",
    "thu": "weekThursday", "thur": "weekThursday", "thurs": "weekThursday",
    "thursday": "weekThursday",
    "fri": "weekFriday", "friday": "weekFriday",
    "sat": "weekSaturday", "saturday": "weekSaturday",
}

WEEKDAY_NAMES = ["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"]
ORDINAL_MAP = {
    "first": "first", "1st": "first",
    "second": "second", "2nd": "second",
    "third": "third", "3rd": "third",
    "fourth": "fourth", "4th": "fourth",
    "last": "last", "final": "last",
}

# Numeric multipliers in Todoist strings
MULTIPLIER_WORDS = {
    "other": 2,
    "two": 2, "twice": 2,
    "three": 3, "thrice": 3,
    "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}


def parse_recurrence(due_string: str, is_recurring: bool) -> Optional[RecurrenceData]:
    """
    Parse a Todoist due.string into RecurrenceData.

    Returns None if the string cannot be parsed as a recurrence rule,
    or if the task is not actually recurring.
    """
    if not is_recurring or not due_string:
        return None

    s = due_string.strip().lower()

    # Strip the completion-based marker "!" (e.g., "every! day")
    # We don't handle completion-vs-due based differently in the output,
    # but we note it's a form of recurrence
    completion_based = "!" in s
    s = s.replace("!", " ")

    # Normalize whitespace
    s = re.sub(r'\s+', ' ', s).strip()

    # "ev" is common abbreviation for "every"
    s = re.sub(r'\bev\b', 'every', s)

    rec = RecurrenceData(enabled=True)

    # --- MINUTES ---
    m = re.match(
        r'every (\d+)\s*min(?:ute)?s?', s
    )
    if m:
        rec.interval = "minute"
        rec.intervalNumber = int(m.group(1))
        return rec

    # --- HOURS ---
    m = re.match(
        r'every (\d+)\s*h(?:ou)?r?s?', s
    )
    if m:
        rec.interval = "hour"
        rec.intervalNumber = int(m.group(1))
        return rec

    # --- DAYS ---
    # "every day", "every 2 days", "every work day", "every weekday"
    m = re.match(
        r'every (?:(\d+)\s*)?days?$', s
    )
    if m:
        rec.interval = "day"
        rec.intervalNumber = int(m.group(1)) if m.group(1) else 1
        return rec

    # "every work day" / "every weekday" → mon-fri
    m = re.match(r'every\s*(?:work\s*)?(?:week\s*)?days?$', s)
    if m and 'weekend' not in s:
        # Distinguish "every work day" / "every weekday" from "every X days"
        # If we already matched "every day" above, this won't fire
        # Check if it's "every weekday" / "every work day"
        if 'work' in s or 'weekday' in s:
            rec.interval = "week"
            rec.intervalNumber = 1
            rec.weekMonday = True
            rec.weekTuesday = True
            rec.weekWednesday = True
            rec.weekThursday = True
            rec.weekFriday = True
            return rec

    # "every weekend" → sat, sun
    if 'weekend' in s:
        rec.interval = "week"
        rec.intervalNumber = 1
        rec.weekSaturday = True
        rec.weekSunday = True
        return rec

    # --- MONTHS (check BEFORE weeks) ---
    # "every month", "every 2 months", "every month on the 2nd",
    # "every second Friday", "every 2nd Thursday"
    # These must be checked before "week" patterns because strings like
    # "every second Friday" contain "fri" which would otherwise match
    # the weekly-weekday parser.

    # Check for nth weekday: "every second Friday", "every 2nd Thursday"
    ordinal_match = None
    weekday_match = None
    month_interval_number = 1

    for ord_word, ord_val in ORDINAL_MAP.items():
        pattern = rf'\b{ord_word}\s+(\w+day)\b'
        m = re.search(pattern, s)
        if m:
            ordinal_match = ord_val
            weekday_match = m.group(1).lower()
            break

    # Also check "every month on the second Friday"
    if not ordinal_match:
        for ord_word, ord_val in ORDINAL_MAP.items():
            pattern = rf'on\s+the\s+{ord_word}\s+(\w+day)\b'
            m = re.search(pattern, s)
            if m:
                ordinal_match = ord_val
                weekday_match = m.group(1).lower()
                break

    if ordinal_match and weekday_match:
        rec.interval = "month"
        rec.intervalNumber = 1
        rec.monthOrdinal = ordinal_match
        rec.monthWeekday = weekday_match
        return rec

    # "every month", "every 2 months", "every month on the Xth"
    num_match = re.search(r'every\s+(\d+)\s*months?', s)
    if num_match:
        month_interval_number = int(num_match.group(1))

    if re.search(r'\bmonths?\b', s) and 'week' not in s:
        rec.interval = "month"
        rec.intervalNumber = month_interval_number
        return rec

    # --- WEEKS ---
    # "every week", "every 2 weeks", "every mon, fri",
    # "every other week on mon, fri", "every 2 weeks on mon, wed, fri"

    # Try to extract weekdays from the string
    weekdays_found = _extract_weekdays(s)
    week_interval_number = 1

    # Check for multiplier: "every X weeks", "every other week"
    num_match = re.search(r'every\s+(\d+)\s*weeks?', s)
    if num_match:
        week_interval_number = int(num_match.group(1))
    elif re.search(r'\bother\b', s) and 'week' in s:
        week_interval_number = 2

    if weekdays_found:
        rec.interval = "week"
        rec.intervalNumber = week_interval_number
        for wd in weekdays_found:
            setattr(rec, WEEKDAY_MAP[wd], True)
        return rec

    if re.search(r'every\s+(?:\d+\s*)?weeks?$', s):
        rec.interval = "week"
        rec.intervalNumber = week_interval_number
        return rec

    if re.search(r'\bweeks?\b', s):
        rec.interval = "week"
        rec.intervalNumber = week_interval_number
        return rec

    # --- YEARS ---
    # "every year", "every year on Jan 1st"
    num_match = re.search(r'every\s+(\d+)\s*years?', s)
    if num_match:
        rec.interval = "year"
        rec.intervalNumber = int(num_match.group(1))
        return rec

    if re.search(r'\byears?\b', s) and 'every' in s:
        rec.interval = "year"
        rec.intervalNumber = 1
        return rec

    # --- FALLBACK: try to detect interval from the string ---
    # This handles edge cases we might have missed
    if 'minute' in s or 'min' in s:
        rec.interval = "minute"
    elif 'hour' in s or 'hr' in s:
        rec.interval = "hour"
    elif 'day' in s:
        rec.interval = "day"
    elif 'week' in s:
        rec.interval = "week"
        # Try one more time to find weekdays
        wds = _extract_weekdays(s)
        for wd in wds:
            setattr(rec, WEEKDAY_MAP[wd], True)
    elif 'month' in s:
        rec.interval = "month"
    elif 'year' in s:
        rec.interval = "year"
    else:
        return None

    return rec


def _extract_weekdays(s: str) -> list[str]:
    """Extract weekday names from a string. Returns normalized short names."""
    found = []
    # First, find standalone weekday abbreviations (mon, tue, etc.)
    # Need to be careful not to match parts of other words
    for abbrev, field in [
        ("sun", "sun"), ("mon", "mon"), ("tue", "tue"), ("tues", "tue"),
        ("wed", "wed"), ("thu", "thu"), ("thur", "thu"), ("thurs", "thu"),
        ("fri", "fri"), ("sat", "sat"),
    ]:
        # Match as whole words (preceded by comma, space, or start)
        pattern = rf'(?:^|[,\s])({abbrev})(?:[,\s]|$)'
        if re.search(pattern, s):
            canonical = {"sun": "sun", "mon": "mon", "tue": "tue", "tues": "tue",
                          "wed": "wed", "thu": "thu", "thur": "thu", "thurs": "thu",
                          "fri": "fri", "sat": "sat"}[abbrev]
            if canonical not in found:
                found.append(canonical)

    # Also check full names
    for full_name in ["sunday", "monday", "tuesday", "wednesday",
                       "thursday", "friday", "saturday"]:
        if full_name in s:
            abbr = full_name[:3]
            if abbr not in found:
                found.append(abbr)

    return found

from daily import pace_hours, EVERY_HOURS, SLOW_HOURS


def test_pace_switches_at_70_percent_weekly():
    assert pace_hours({"seven_day": 69.9}, EVERY_HOURS) == EVERY_HOURS
    assert pace_hours({"seven_day": 70}, EVERY_HOURS) == SLOW_HOURS
    assert pace_hours({"seven_day": 12}, SLOW_HOURS) == EVERY_HOURS      # back to normal after the weekly reset
    assert pace_hours(None, SLOW_HOURS) == SLOW_HOURS                     # unknown usage keeps the current pace
    assert pace_hours({"seven_day": None}, EVERY_HOURS) == EVERY_HOURS



def test_locked_vs_transient_errors():
    from daily import LOCKED
    for locked in ["ERROR: [GoogleDrive] x: Unable to download JSON metadata: HTTP Error 404: Not Found",
                   "ERROR: [youtube] x: Join this channel to get access to members-only content like this video",
                   "ERROR: [youtube] x: Private video. Sign in if you've been granted access to this video"]:
        assert LOCKED.search(locked)
    for transient in ["ERROR: [GoogleDrive] x: HTTP Error 429: Too Many Requests",
                      "ERROR: 'cookies.txt' does not look like a Netscape format cookies file",
                      "ERROR: [youtube] x: Sign in to confirm you're not a bot",
                      "ERROR: unable to write data: [Errno 28] No space left on device"]:
        assert not LOCKED.search(transient)


def test_locked_vs_transient_errors():
    from daily import LOCKED
    for locked in ["ERROR: [GoogleDrive] x: Unable to download JSON metadata: HTTP Error 404: Not Found",
                   "ERROR: [youtube] x: Join this channel to get access to members-only content like this video",
                   "ERROR: [youtube] x: Private video. Sign in if you've been granted access to this video"]:
        assert LOCKED.search(locked)
    for transient in ["ERROR: [GoogleDrive] x: HTTP Error 429: Too Many Requests",
                      "ERROR: 'cookies.txt' does not look like a Netscape format cookies file",
                      "ERROR: [youtube] x: Sign in to confirm you're not a bot",
                      "ERROR: unable to write data: [Errno 28] No space left on device"]:
        assert not LOCKED.search(transient)

from yupa import mmss, timeline


def test_timeline_buckets_captions_under_latest_frame():
    cues = [(0.5, "a"), (9.9, "b"), (10, "c"), (25, "d"), (70, "e")]
    assert timeline(cues, [0, 10, 60, 90]) == [(0, "a b"), (10, "c d"), (60, "e"), (90, "")]


def test_mmss():
    assert mmss(65) == "01:05" and mmss(3725) == "1:02:05"


def test_snapshot_times_shoot_end_of_each_segment():
    from yupa import snapshot_times
    assert snapshot_times([0, 10, 10.2], 30) == [9.5, 10, 29.5]  # tiny segment clamps to its own start


def test_parse_vtt_drops_tags_and_rolling_duplicates():
    from yupa import parse_vtt
    vtt = "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nhello <c>world</c>\n\n00:00:02.000 --> 00:00:03.000\nhello world\n\n01:02:03.500 --> 01:02:04.000\nnext"
    assert parse_vtt(vtt) == [(1.0, "hello world"), (3723.5, "next")]

"""The final texts of the messages to a phone, word for word, and in the form every text has to have that leaves
this machine."""

from ringtop_parts.core.alerts import GAP_MARK, MANY, NEUTRAL, PLACEHOLDER, TEXTS, TROUBLES, message

# The texts as they came, title and body by key, and the fixed word of the gap. Held here once more, so that no
# change to the wording goes unseen: whoever changes a text changes it in both places.
FINAL = {
    "away on": (
        "Ringtop: Spark not reporting",
        "No data arrives from <sparks>. Ringtop cannot tell whether power, network, SSH or a hung reader process is the cause.",
    ),
    "away off": ("Ringtop: Sparks reporting again", "Every Spark sends data to ringtop again."),
    "latch on": (
        "Ringtop: GPU clock far below normal",
        "Under load the GPU clock stays far below normal on <sparks>. Looks like the clock latch: the GPU gives no reason, and a reboot does not clear it.",
    ),
    "latch off": (
        "Ringtop: GPU clock normal again",
        "Every GPU that was held low has been seen at normal clock under load again.",
    ),
    "fan on": (
        "Ringtop: fan stopped",
        "A fan reads as stopped on <sparks>. This holds for all fans of a warm Spark, or for a fan beside a spinning fan.",
    ),
    "fan off": ("Ringtop: fans spinning again", "Every fan that was stopped reads as spinning again."),
    "link on": (
        "Ringtop: link inactive or port gone",
        "Ends of each affected link: <sparks>. Ringtop cannot tell cable, port, far side or a Spark that is off apart.",
    ),
    "link off": ("Ringtop: ring links active again", "Every link that was down reports active again."),
    "engine on": (
        "Ringtop: engine not answering",
        "The ring's engine does not answer on its port, although the head Spark does. Ringtop cannot tell whether this is intended.",
    ),
    "engine off": (
        "Ringtop: engine answering again",
        "The ring's engine answers on its port again and says what it is doing.",
    ),
    "quiet": (
        "Ringtop: many changes in a day",
        "Ringtop holds back further messages for a while; the state can change meanwhile and the page shows it. Silence is not an all-clear.",
    ),
}
FINAL_MANY = "at least one Spark"
NAMED_ON = ("away on", "latch on", "fan on", "link on")


def test_the_texts_are_the_final_wording_word_for_word():
    """The table of the texts and the fixed word of the gap are these, sign for sign."""
    assert list(TEXTS) == list(FINAL)
    assert {key: (text["title"], text["body"]) for key, text in TEXTS.items()} == FINAL
    assert MANY == FINAL_MANY


def test_no_text_is_a_placeholder_and_each_has_the_form_of_one_that_leaves():
    """The check of the placeholders, turned round: no text carries the mark any more. Each is plain printable
    ASCII on one line, without a digit and without the name of a machine; every title names Ringtop; no two
    titles and no two bodies are the same. The fixed word of the gap is held to the same."""
    keys = [f"{trouble} {word}" for trouble in TROUBLES for word in ("on", "off")] + ["quiet"]
    assert list(TEXTS) == keys and len(keys) == 11
    for key, text in TEXTS.items():
        assert set(text) == {"title", "body"} and text["title"].startswith("Ringtop") and text["body"], key
        for part in (*text.values(), MANY):
            assert PLACEHOLDER not in part, (key, part)
            assert part.isascii() and part.isprintable() and not any(sign.isdigit() for sign in part), (key, part)
            assert not any(name in part.lower() for name in ("spark-", "dgx", "ntfy")), (key, part)
    assert len({text["title"] for text in TEXTS.values()}) == len({text["body"] for text in TEXTS.values()}) == 11


def test_each_filling_of_the_gap_gives_a_whole_text():
    """The gap stands once in each of the four texts that name Sparks. One name, two, four, five (the fixed word)
    or none that can be placed (the fixed word): each gives a text with no rest of the gap, in plain printable
    ASCII, whose only digits are those of the names."""
    for key in NAMED_ON:
        assert (TEXTS[key]["title"] + TEXTS[key]["body"]).count(GAP_MARK) == 1, key
        for names in (
            ("spark-3",),
            ("spark-1", "spark-3"),
            ("spark-1", "spark-2", "spark-9", "spark-16"),
            NEUTRAL[:5],
            (),
        ):
            for part in message(key, names=names).values():
                assert GAP_MARK not in part and "<" not in part and ">" not in part, (key, names, part)
                assert part.isascii() and part.isprintable(), (key, names, part)
                rest = part
                for name in reversed(NEUTRAL):  # spark-16 before spark-1
                    rest = rest.replace(name, "")
                assert not any(sign.isdigit() for sign in rest), (key, names, part)
        assert message(key, names=("spark-1", "spark-3"))["body"] == TEXTS[key]["body"].replace(
            GAP_MARK, "spark-1, spark-3"
        )
        assert message(key)["body"] == TEXTS[key]["body"].replace(GAP_MARK, MANY), key

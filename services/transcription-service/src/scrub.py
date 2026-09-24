"""
Remove payment and identity numbers from transcripts.

Customers read card numbers, security codes, and bank details aloud on payment calls.
Transcripts are sent to the summarizer and voicemail transcripts go into AgencyZoom notes,
so these numbers are replaced before the transcript is used anywhere.

ponytail: digit-pattern + keyword heuristics; numbers spoken as words ("four four zero zero")
are not caught. Whisper writes digits in practice; revisit if that changes.
"""
import re

# A run of 13-19 digits, optionally grouped with spaces, dashes, dots, or commas
_CARD = re.compile(r"(?<!\d)\d(?:[ \-.,]{0,2}\d){12,18}(?!\d)")
_CARD_CONTEXT = re.compile(r"card|visa|master\s?card|amex|american express|discover", re.I)
# 3-4 digits shortly after a security-code phrase
_CVV = re.compile(r"(security code|cvv|cvc|cid|code on the back)(\W{1,12}(?:is\W{1,3})?)(\d{3,4})(?!\d)", re.I)
# SSN written with separators, or 9 digits shortly after "social"
_SSN = re.compile(r"(?<!\d)\d{3}[ \-.]\d{2}[ \-.]\d{4}(?!\d)")
_SSN_CONTEXT = re.compile(r"(social(?: security)?(?: number)?\W{1,20}(?:is\W{1,3})?)(\d(?:[ \-.]?\d){8})(?!\d)", re.I)
# Bank routing / account numbers shortly after the phrase
_BANK = re.compile(r"((?:routing|account|checking|savings)(?: number)?\W{1,20}(?:is\W{1,3})?)(\d(?:[ \-.]?\d){3,16})(?!\d)", re.I)


def _luhn_ok(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


def _card(match: re.Match, text: str) -> str:
    digits = re.sub(r"\D", "", match.group())
    # Luhn-valid anywhere, or any long digit run near card talk (a misheard digit breaks Luhn)
    nearby = text[max(0, match.start() - 120):match.start()]
    if _luhn_ok(digits) or _CARD_CONTEXT.search(nearby):
        return "[card number removed]"
    return match.group()


def scrub_sensitive(text: str) -> str:
    """Replace card numbers, security codes, SSNs, and bank account numbers in a transcript."""
    if not text:
        return text
    text = _CARD.sub(lambda m: _card(m, text), text)
    text = _CVV.sub(lambda m: f"{m.group(1)}{m.group(2)}[removed]", text)
    text = _SSN_CONTEXT.sub(lambda m: f"{m.group(1)}[SSN removed]", text)
    text = _SSN.sub("[SSN removed]", text)
    text = _BANK.sub(lambda m: f"{m.group(1)}[account number removed]", text)
    return text


if __name__ == "__main__":
    # Real Whisper output from a payment call (card details altered to a Luhn-valid test number)
    call = ("whenever you're ready with the card number. Okay, I'm ready. Go for it. 4111-1111-1111-1111. "
            "Expiration. 1127. And the security code. 561. And the billing zip code. 93442.")
    out = scrub_sensitive(call)
    assert "4111" not in out and "561" not in out, out
    assert "[card number removed]" in out and "security code. [removed]" in out, out
    assert "93442" in out and "1127" in out, out  # zip and expiration are not sensitive on their own

    # Misheard digit (fails Luhn) is still caught because card talk is nearby
    assert "[card number removed]" in scrub_sensitive("my visa is 4111 1111 1111 1112")
    assert scrub_sensitive("The CVV is 1234.") == "The CVV is [removed]."
    assert "[SSN removed]" in scrub_sensitive("my social is 123-45-6789")
    assert "[SSN removed]" in scrub_sensitive("social security number is 123456789")
    assert "[account number removed]" in scrub_sensitive("routing number 121000358 and account number 000123456789")

    # Must NOT change: phones, premiums, dates, zip, policy numbers, VINs, years, mileage
    keep = ("Call me at 805-548-8530 or (805) 279-9381. The premium is $2,279.24 for six months, "
            "effective 9-25, zip 93442, policy number 0189234571, VIN 1HGCM82633A004352, "
            "2017 Ford Fusion with 126,705 miles, rebuild cost $854,000, quote number 5539.")
    assert scrub_sensitive(keep) == keep, scrub_sensitive(keep)
    print("scrub self-check OK")

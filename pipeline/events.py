import unicodedata


def event_group(event):
    """Sort the free-text event names scouts typed into Gotham, Practice, or Other events."""
    name = unicodedata.normalize("NFKD", str(event)).encode("ascii", "ignore").decode().lower()
    if "pract" in name or "test" in name:
        return "Practice"
    if "hali" in name or "hudson" in name:
        return "Other events"
    return "Gotham"

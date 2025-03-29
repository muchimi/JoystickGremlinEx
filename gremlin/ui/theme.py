def theme():
    """queries registry to determine the windows personalization mode:

    :returns "Dark" if dark mode
    :returns "Light" if not dark mode

    """
    from winreg import (
        HKEY_CURRENT_USER as hkey,
        QueryValueEx as getSubkeyValue,
        OpenKey as getKey,
    )

    try:
        key = getKey(
            hkey, "Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize"
        )
        subkey = getSubkeyValue(key, "AppsUseLightTheme")[0]
    except FileNotFoundError:
        subkey = 1
    if subkey == 0:
        return "Dark"
    return "Light"

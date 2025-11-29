import asyncio
import datetime
import hashlib
import re
import base64
from urllib.parse import urlencode
from typing import Dict, List, Optional
import aiohttp
from colorama import init, Fore, Style

# Initialize colorama for colored output
init(autoreset=True)

async def fetch_url(session: aiohttp.ClientSession, url: str) -> str:
    """Fetch content from a URL and return it as text."""
    async with session.get(url) as response:
        response.raise_for_status()
        return await response.text()

def decode_secret(secret_array: List[str]) -> Optional[str]:
    """Decode a base64-encoded secret array, removing trailing 44 characters."""
    combined_secret = "".join(secret_array)[:-44]
    try:
        return base64.b64decode(combined_secret).decode("utf-8")
    except (base64.binascii.Error, UnicodeDecodeError):
        return None

async def validate_secret(
    session: aiohttp.ClientSession, app_id: str, secret: str, track_id: int = 1, format_id: int = 27
) -> bool:
    """Validate a secret by making an API request to Qobuz."""
    timestamp = datetime.datetime.now().timestamp()
    r_sig = f"trackgetFileUrlformat_id{format_id}intentstreamtrack_id{track_id}{timestamp}{secret}"
    r_sig_hashed = hashlib.md5(r_sig.encode()).hexdigest()

    params = {
        "format_id": format_id,
        "intent": "stream",
        "track_id": track_id,
        "request_ts": timestamp,
        "request_sig": r_sig_hashed,
    }
    url = f"https://www.qobuz.com/api.json/0.2/track/getFileUrl?{urlencode(params)}"
    headers = {"X-App-Id": app_id}

    async with session.get(url, headers=headers) as response:
        return response.status != 400

async def get_app_id_and_secrets() -> Optional[Dict[str, str]]:
    """
    Retrieve the Qobuz app ID and valid secret by scraping the login page and bundle.js.
    Returns a dictionary with 'app_id' and 'secret' if successful, None otherwise.
    """
    seed_timezone_regex = re.compile(r'[a-z]\.initialSeed\("(?P<seed>[\w=]+)",window\.utimezone\.(?P<timezone>[a-z]+)\)')
    app_id_regex = re.compile(r'production:{api:{appId:"(?P<app_id>\d{9})",appSecret:"(\w{32})')
    login_url = "https://play.qobuz.com/login"

    try:
        async with aiohttp.ClientSession() as session:
            # Fetch login page
            login_page = await fetch_url(session, login_url)

            # Extract bundle URL
            bundle_url_match = re.search(r'<script src="(/resources/\d+\.\d+\.\d+-[a-z]\d{3}/bundle\.js)"></script>', login_page)
            if not bundle_url_match:
                raise ValueError("Could not find bundle URL")
            bundle_url = f"https://play.qobuz.com{bundle_url_match.group(1)}"

            # Fetch bundle.js
            bundle = await fetch_url(session, bundle_url)

            # Extract app ID
            app_id_match = app_id_regex.search(bundle)
            if not app_id_match:
                raise ValueError("Could not find app ID")
            app_id = app_id_match.group("app_id")

            # Extract seeds and timezones
            secrets: Dict[str, List[str]] = {}
            for seed_match in seed_timezone_regex.finditer(bundle):
                secrets[seed_match.group("timezone")] = [seed_match.group("seed")]

            # Create regex for info/extras
            timezones = "|".join(tz.capitalize() for tz in secrets.keys())
            info_extras_regex = re.compile(
                rf'name:"\w+/(?P<timezone>{timezones})",info:"(?P<info>[\w=]+)",extras:"(?P<extras>[\w=]+)"'
            )

            # Collect info and extras
            for match in info_extras_regex.finditer(bundle):
                timezone = match.group("timezone").lower()
                if timezone in secrets:
                    secrets[timezone].extend([match.group("info"), match.group("extras")])

            # Decode secrets
            decoded_secrets = [secret for secret_array in secrets.values() if (secret := decode_secret(secret_array))]

            # Validate secrets
            for secret in decoded_secrets:
                if await validate_secret(session, app_id, secret):
                    return {
                        "app_id": app_id,
                        "secret": secret,
                    }

            raise ValueError("No valid secret found")

    except Exception as e:
        print(f"{Fore.RED}Error: {e}{Style.RESET_ALL}")
        return None

def print_colored_result(result: Optional[Dict[str, str]]) -> None:
    """Print the result with 'App ID' and 'Secret' in green and their values in white."""
    if result:
        print("Qobuz AppID and Secret")
        print(f"{Fore.GREEN}App ID:{Style.RESET_ALL} {result['app_id']}")
        print(f"{Fore.GREEN}Secret:{Style.RESET_ALL} {result['secret']}")
    else:
        print(f"{Fore.RED}Failed to retrieve app ID and secret.{Style.RESET_ALL}")

if __name__ == "__main__":
    result = asyncio.run(get_app_id_and_secrets())
    print_colored_result(result)

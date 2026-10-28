"""Interactive local setup. Tokens are never echoed, logged or sent elsewhere."""
from getpass import getpass
import json
import os
from pathlib import Path


def main():
    target = Path('.state/settings.json')
    if target.exists():
        print('Local settings already exist. No file was overwritten.')
        return
    print('Token is saved locally in .state/settings.json; keep this file private.')
    token = getpass('Paste BotFather token (hidden): ').strip()
    if ':' not in token or not token.split(':', 1)[0].isdigit():
        raise ValueError('Invalid token format; no file was saved.')
    from bot import Bot, DataError
    client = Bot(token)
    try:
        identity = client.api('getMe', {})
        print('Connected to @' + str(identity.get('username', '')))
        input('Send /start to YOUR bot in Telegram, then press Enter here. ')
        updates = client.api('getUpdates', {'timeout': 0, 'allowed_updates': ['message']})
    except DataError:
        raise ValueError('Telegram connection failed. Check token, connectivity and webhook settings; nothing saved.') from None
    print('Recent private chats (verify your own identity, never choose a stranger):')
    seen = set()
    for update in updates:
        chat = update.get('message', {}).get('chat', {})
        if chat.get('type') == 'private' and chat.get('id') not in seen:
            print(str(chat.get('id')) + ' @' + str(chat.get('username', '(no username)')))
            seen.add(chat.get('id'))
    chat_id = input('Your numeric Telegram chat ID (required for private bot): ').strip()
    if not chat_id.lstrip('-').isdigit():
        raise ValueError('Numeric chat ID required; no file was saved.')
    target.parent.mkdir(exist_ok=True)
    # Exclusive creation protects an existing token against accidental replacement.
    with target.open('x', encoding='utf-8') as file:
        json.dump({'TELEGRAM_BOT_TOKEN': token, 'TELEGRAM_CHAT_ID': chat_id,
                   'REPORT_MODE': 'latest', 'BOT_PUBLIC': 'false'}, file)
    os.chmod(target, 0o600)
    print('Saved locally. Do not upload .state or share its contents.')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError) as exc:
        print(str(exc) if isinstance(exc, ValueError) else 'Could not save settings.')
        raise SystemExit(1) from None

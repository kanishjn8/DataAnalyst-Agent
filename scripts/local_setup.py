"""Create local-only credentials. Never print secrets or overwrite an existing configuration."""
import base64
import hashlib
import hmac
import json
import secrets
import time
from pathlib import Path

root = Path(__file__).resolve().parents[1]
target = root / '.env'
if not target.exists():
    secret = secrets.token_urlsafe(48)
    def token(role):
        encode = lambda value: base64.urlsafe_b64encode(json.dumps(value, separators=(',', ':')).encode()).rstrip(b'=')
        payload = encode({'iss': 'supabase-local', 'role': role, 'iat': int(time.time()), 'exp': int(time.time()) + 315360000})
        unsigned = encode({'alg': 'HS256', 'typ': 'JWT'}) + b'.' + payload
        return (unsigned + b'.' + base64.urlsafe_b64encode(hmac.new(secret.encode(), unsigned, hashlib.sha256).digest()).rstrip(b'=')).decode()
    values = dict(POSTGRES_PASSWORD=secrets.token_hex(24), JWT_SECRET=secret,
                  ANON_KEY=token('anon'), SERVICE_ROLE_KEY=token('service_role'),
                  SUPABASE_PUBLIC_URL='http://127.0.0.1:54321', GEMINI_API_KEY='')
    previous = root / 'backend/.env.local'
    if previous.exists():
        for line in previous.read_text().splitlines():
            if line.startswith('GEMINI_API_KEY='):
                values['GEMINI_API_KEY'] = line.partition('=')[2].strip().strip('\"\'')
    target.write_text('\n'.join(f'{key}={value}' for key, value in values.items()) + '\n')
    target.chmod(0o600)
    print('Created .env with local credentials. Add GEMINI_API_KEY there for live AI questions.')
else:
    print('Keeping existing .env configuration.')

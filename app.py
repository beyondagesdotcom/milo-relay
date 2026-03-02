from flask import Flask, request, jsonify, make_response, redirect
import requests
import hashlib
import base64
import os
import json
import time

app = Flask(__name__)
RELAY_TOKEN = "RELAY_TOKEN_MK2026"

# Frame.io OAuth2 (Adobe)
FRAMEIO_CLIENT_ID = "aa28b05fabb141538b89d8d4dae21168"
FRAMEIO_CLIENT_SECRET = "p8e-qkfniCKr5Af16-sVRj8skhXvDhmXndqC"
FRAMEIO_REDIRECT_URI = "https://milo-relay.onrender.com/frameio/callback"
FRAMEIO_TOKEN_FILE = "/tmp/frameio_tokens.json"

def save_frameio_tokens(tokens):
    with open(FRAMEIO_TOKEN_FILE, "w") as f:
        json.dump(tokens, f)

def load_frameio_tokens():
    if os.path.exists(FRAMEIO_TOKEN_FILE):
        with open(FRAMEIO_TOKEN_FILE) as f:
            return json.load(f)
    return {}

def get_frameio_token():
    tokens = load_frameio_tokens()
    if not tokens:
        return None
    # Refresh if expired
    if tokens.get("expires_at", 0) < time.time() + 60:
        resp = requests.post("https://ims-na1.adobelogin.com/ims/token/v3", data={
            "grant_type": "refresh_token",
            "client_id": FRAMEIO_CLIENT_ID,
            "client_secret": FRAMEIO_CLIENT_SECRET,
            "refresh_token": tokens.get("refresh_token"),
        })
        if resp.status_code == 200:
            new_tokens = resp.json()
            new_tokens["expires_at"] = time.time() + new_tokens.get("expires_in", 3600)
            save_frameio_tokens(new_tokens)
            return new_tokens.get("access_token")
        return None
    return tokens.get("access_token")
WECOM_TOKEN = "XHgrLRTWkt8Dk8Y"
WECOM_AES_KEY = "n8OiirCsEQ8DqQs9NQ1MnrOV2v7Wk5DO6t1dxD2f9ve"

@app.route("/proxy", methods=["POST"])
def proxy():
    auth = request.headers.get("Authorization", "")
    if auth != f"Bearer {RELAY_TOKEN}":
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    url = data.get("url")
    method = data.get("method", "GET").upper()
    headers = data.get("headers", {})
    body = data.get("body", None)
    try:
        resp = requests.request(method, url, headers=headers, json=body, timeout=30)
        try:
            resp_body = resp.json()
        except:
            resp_body = resp.text
        return jsonify({"status": resp.status_code, "body": resp_body})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/wecom", methods=["GET", "POST"])
def wecom():
    if request.method == "GET":
        msg_signature = request.args.get("msg_signature", "")
        timestamp = request.args.get("timestamp", "")
        nonce = request.args.get("nonce", "")
        echostr = request.args.get("echostr", "")
        items = sorted([WECOM_TOKEN, timestamp, nonce, echostr])
        s = hashlib.sha1("".join(items).encode()).hexdigest()
        if s == msg_signature:
            try:
                from Crypto.Cipher import AES
                aes_key = base64.b64decode(WECOM_AES_KEY + "=")
                encrypted = base64.b64decode(echostr)
                cipher = AES.new(aes_key, AES.MODE_CBC, aes_key[:16])
                decrypted = cipher.decrypt(encrypted)
                pad = decrypted[-1]
                decrypted = decrypted[:-pad]
                msg_len = int.from_bytes(decrypted[16:20], "big")
                msg = decrypted[20:20+msg_len].decode("utf-8")
                return make_response(msg, 200)
            except Exception as e:
                return make_response(echostr, 200)
        else:
            return make_response("signature mismatch", 403)
    return make_response("success", 200)

slack_queue = []

@app.route("/slack", methods=["POST"])
def slack_events():
    import json
    data = request.get_json(silent=True) or {}
    if data.get("type") == "url_verification":
        return jsonify({"challenge": data.get("challenge")})
    event = data.get("event", {})
    etype = event.get("type", "")
    user = event.get("user", "")
    text = event.get("text", "")
    channel = event.get("channel", "")
    bot_id = event.get("bot_id", "")
    # Ignore Milo's own messages
    if bot_id or user == "U0AHPH9G3UK":
        return make_response("ok", 200)
    if etype == "message" and text:
        msg = {"user": user, "channel": channel, "text": text}
        slack_queue.append(msg)
        print(f"[Slack] queued: #{channel} {user}: {text[:100]}", flush=True)
    return make_response("ok", 200)

@app.route("/slack/pending", methods=["GET"])
def slack_pending():
    auth = request.headers.get("Authorization", "")
    if auth != f"Bearer {RELAY_TOKEN}":
        return jsonify({"error": "Unauthorized"}), 401
    msgs = slack_queue.copy()
    slack_queue.clear()
    return jsonify({"messages": msgs})

@app.route("/frameio", methods=["POST"])
def frameio_webhook():
    import json, datetime
    payload = request.get_data()
    try:
        data = json.loads(payload)
        event_type = data.get("type", "unknown")
        resource = data.get("resource", {})
        name = resource.get("name", resource.get("id", "?"))
        ts = datetime.datetime.utcnow().isoformat()
        print(f"[Frame.io] {ts} | {event_type} | {name}", flush=True)
    except Exception as e:
        print(f"[Frame.io] parse error: {e}", flush=True)
    return make_response("ok", 200)

@app.route("/frameio/auth")
def frameio_auth():
    """Redirect to Adobe OAuth login"""
    auth = request.headers.get("Authorization", "")
    if auth != f"Bearer {RELAY_TOKEN}" and request.args.get("token") != RELAY_TOKEN:
        return jsonify({"error": "Unauthorized"}), 401
    scope = "openid,email,profile,offline_access"
    url = (
        f"https://ims-na1.adobelogin.com/ims/authorize/v2"
        f"?client_id={FRAMEIO_CLIENT_ID}"
        f"&redirect_uri={FRAMEIO_REDIRECT_URI}"
        f"&scope={scope}"
        f"&response_type=code"
    )
    return redirect(url)

@app.route("/frameio/callback")
def frameio_callback():
    """Handle Adobe OAuth callback, exchange code for tokens"""
    code = request.args.get("code")
    error = request.args.get("error")
    if error:
        return f"OAuth error: {error}", 400
    if not code:
        return "No code received", 400
    resp = requests.post("https://ims-na1.adobelogin.com/ims/token/v3", data={
        "grant_type": "authorization_code",
        "client_id": FRAMEIO_CLIENT_ID,
        "client_secret": FRAMEIO_CLIENT_SECRET,
        "redirect_uri": FRAMEIO_REDIRECT_URI,
        "code": code,
    })
    if resp.status_code != 200:
        return f"Token exchange failed: {resp.text}", 400
    tokens = resp.json()
    tokens["expires_at"] = time.time() + tokens.get("expires_in", 3600)
    save_frameio_tokens(tokens)
    access_token = tokens.get("access_token", "")
    return f"""
    <html><body style='font-family:Arial;padding:40px;text-align:center'>
    <h2 style='color:#28a745'>✅ Frame.io Connected!</h2>
    <p>Milo now has a valid access token.</p>
    <p style='font-size:12px;color:#888'>Token saved. You can close this window.</p>
    </body></html>
    """

@app.route("/frameio/token", methods=["GET"])
def frameio_token_status():
    """Return current token status (for Milo to use)"""
    auth = request.headers.get("Authorization", "")
    if auth != f"Bearer {RELAY_TOKEN}":
        return jsonify({"error": "Unauthorized"}), 401
    token = get_frameio_token()
    tokens = load_frameio_tokens()
    if token:
        return jsonify({"status": "ok", "access_token": token, "expires_at": tokens.get("expires_at")})
    return jsonify({"status": "no_token", "message": "Need to authenticate via /frameio/auth"})

@app.route("/health")
def health():
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)

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

# ── Static image hosting for Airtable attachments ─────────────────────
IMAGES_DIR = "/tmp/mk_images"
os.makedirs(IMAGES_DIR, exist_ok=True)

@app.route("/images/<filename>")
def serve_image(filename):
    """Serve hosted images — no auth required (public for Airtable fetching)"""
    from flask import send_from_directory
    return send_from_directory(IMAGES_DIR, filename)

@app.route("/images/upload", methods=["POST"])
def upload_image():
    """Upload a base64-encoded image for hosting"""
    auth = request.headers.get("Authorization", "")
    if auth != f"Bearer {RELAY_TOKEN}":
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    filename = data.get("filename")
    img_b64 = data.get("image")
    if not filename or not img_b64:
        return jsonify({"error": "Missing filename or image"}), 400
    img_bytes = base64.b64decode(img_b64)
    path = os.path.join(IMAGES_DIR, filename)
    with open(path, "wb") as f:
        f.write(img_bytes)
    url = f"https://milo-relay.onrender.com/images/{filename}"
    return jsonify({"url": url, "filename": filename})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)

# ── Stripe Webhook ──────────────────────────────────────────────────────────
import stripe
import base64 as b64

STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
stripe.api_key = STRIPE_SECRET_KEY
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO = "beyondagesdotcom/squeeze-project-form"

# Map Stripe payment link ID → ambassador file path + display name
AMBASSADOR_MAP = {
    "plink_1TEOagBF4XsXJ5LxT1kRdQYq": {"key": "luke",    "name": "Luke & Aria Kerman"},
    "plink_1TEQ3pBF4XsXJ5Lx6HrLyC9k": {"key": "tessa",   "name": "Tessa Forman"},
    "plink_1TEQFFBF4XsXJ5LxfOjHijF2": {"key": "ben",     "name": "Ben & Jack"},
    "plink_1TEejLBF4XsXJ5LxxtmbC1I6": {"key": "parker",  "name": "Parker Wellen"},
    "plink_1TEfAJBF4XsXJ5Lxev71xJc8": {"key": "jordana", "name": "Jordana Brody"},
}

def update_donations_json(ambassador_key, amount_cents):
    """Update /data/donations.json on GitHub with new donation amount."""
    import urllib.request as ur
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json"
    }
    file_path = "data/donations.json"
    api_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{file_path}"
    req = ur.Request(api_url, headers=headers)
    resp = json.loads(ur.urlopen(req, timeout=10).read().decode())
    current = json.loads(b64.b64decode(resp["content"]).decode())
    sha = resp["sha"]
    current["ambassadors"][ambassador_key]["raised"] += (amount_cents // 100)
    current["grand_total"] = sum(a["raised"] for a in current["ambassadors"].values())
    from datetime import datetime
    current["updated"] = datetime.utcnow().strftime("%Y-%m-%d")
    new_content = json.dumps(current, indent=2)
    payload = json.dumps({
        "message": f"Auto: +${amount_cents//100} to {ambassador_key}",
        "content": b64.b64encode(new_content.encode()).decode(),
        "sha": sha
    }).encode()
    req = ur.Request(api_url, data=payload, headers=headers, method="PUT")
    ur.urlopen(req, timeout=10)
    return current["ambassadors"][ambassador_key]["raised"]

def get_payment_link_id(payment_link_url):
    if not payment_link_url:
        return None
    return payment_link_url.rstrip("/").split("/")[-1]

def update_progress_on_github(file_path, amount_cents):
    import urllib.request as ur
    import urllib.parse

    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json"
    }
    api_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{file_path}"

    # Get current file
    req = ur.Request(api_url, headers=headers)
    resp = json.loads(ur.urlopen(req, timeout=10).read().decode())
    current_content = b64.b64decode(resp["content"]).decode("utf-8")
    sha = resp["sha"]

    # Find current raised amount and add new donation
    import re
    match = re.search(r"const raised = (\d+);", current_content)
    current = int(match.group(1)) if match else 0
    new_amount = current + (amount_cents // 100)
    new_content = re.sub(r"const raised = \d+;", f"const raised = {new_amount};", current_content)

    # Push update
    payload = json.dumps({
        "message": f"Auto-update: +${amount_cents//100} donation",
        "content": b64.b64encode(new_content.encode()).decode(),
        "sha": sha
    }).encode()
    req = ur.Request(api_url, data=payload, headers=headers, method="PUT")
    ur.urlopen(req, timeout=10)
    return new_amount

@app.route("/stripe-webhook", methods=["POST"])
def stripe_webhook():
    payload = request.get_data()
    sig_header = request.headers.get("Stripe-Signature", "")

    try:
        if STRIPE_WEBHOOK_SECRET:
            event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
        else:
            event = json.loads(payload)
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        amount_cents = session.get("amount_total", 0)
        amount = amount_cents / 100
        payment_link = session.get("payment_link", "")
        donor_name = (session.get("customer_details") or {}).get("name", "Unknown")

        if payment_link and payment_link in AMBASSADOR_MAP and GITHUB_TOKEN:
            ambassador = AMBASSADOR_MAP[payment_link]
            key = ambassador["key"]
            name = ambassador["name"]
            try:
                new_total = update_donations_json(key, amount_cents)
                msg = f"💳 New Stripe donation!\n*{donor_name}* gave *${amount:.0f}* to *{name}*\nNew total: *${new_total:,}*"
                send_telegram(msg)
                print(f"Updated {name} +${amount} → ${new_total}")
            except Exception as e:
                print(f"Update failed: {e}")

    return jsonify({"status": "ok"}), 200

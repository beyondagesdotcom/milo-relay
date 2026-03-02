from flask import Flask, request, jsonify, make_response
import requests
import hashlib
import base64

app = Flask(__name__)
RELAY_TOKEN = "RELAY_TOKEN_MK2026"
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

@app.route("/health")
def health():
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)

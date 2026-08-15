import os
import json
import time
import subprocess
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

ITEM_ID = 478
ITEM_TYPE = "collectibles"

SFL_TOKEN = os.environ["SFL_TOKEN"]
TG_BOT_TOKEN = os.environ["TG_BOT_TOKEN"]
TG_CHAT_ID = os.environ["TG_CHAT_ID"]

STATE_PATH = "state.json"

API_URL = f"https://api.sunflower-land.com/collection/{ITEM_TYPE}/{ITEM_ID}?type={ITEM_TYPE}"
TG_API = f"https://api.telegram.org/bot{TG_BOT_TOKEN}"


def load_state():
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"message_id": None, "known_listing_ids": [], "known_offer_ids": []}


def save_state(state):
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    commit_state()


def commit_state():
    subprocess.run(["git", "add", STATE_PATH], check=True)
    diff = subprocess.run(["git", "diff", "--cached", "--quiet"])
    if diff.returncode == 0:
        return  # nothing changed
    subprocess.run(["git", "commit", "-m", "Update state [skip ci]"], check=True)
    subprocess.run(["git", "pull", "--rebase"], check=True)
    subprocess.run(["git", "push"], check=True)


def fetch_market():
    resp = requests.get(
        API_URL,
        headers={
            "accept": "*/*",
            "authorization": f"Bearer {SFL_TOKEN}",
            "content-type": "application/json;charset=UTF-8",
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def format_summary(data):
    listings = sorted(data.get("listings", []), key=lambda x: x["sfl"])
    offers = sorted(data.get("offers", []), key=lambda x: -x["sfl"])

    now = datetime.now(ZoneInfo("Europe/Kyiv")).strftime("%Y-%m-%d %H:%M:%S")

    lines = [f"<b>Item #{ITEM_ID} — листинги и офферы</b>", f"Последний скан: {now}", ""]
    lines.append(f"<b>Листинги ({len(listings)}):</b>")
    if listings:
        for l in listings:
            lines.append(f"  {l['sfl']} SFL — {l['listedBy']['username']}")
    else:
        lines.append("  нет")

    lines.append("")
    lines.append(f"<b>Офферы ({len(offers)}):</b>")
    if offers:
        for o in offers:
            lines.append(f"  {o['sfl']} SFL — {o['offeredBy']['username']}")
    else:
        lines.append("  нет")

    return "\n".join(lines)


def tg_send(text):
    r = requests.post(
        f"{TG_API}/sendMessage",
        json={"chat_id": TG_CHAT_ID, "text": text, "parse_mode": "HTML"},
        timeout=15,
    )
    r.raise_for_status()
    return r.json()["result"]["message_id"]


def tg_edit(message_id, text):
    r = requests.post(
        f"{TG_API}/editMessageText",
        json={
            "chat_id": TG_CHAT_ID,
            "message_id": message_id,
            "text": text,
            "parse_mode": "HTML",
        },
        timeout=15,
    )
    if r.status_code == 400 and "message is not modified" in r.text:
        return
    r.raise_for_status()


def check_once(state):
    data = fetch_market()
    summary = format_summary(data)

    if state["message_id"] is None:
        state["message_id"] = tg_send(summary)
    else:
        tg_edit(state["message_id"], summary)

    listings = data.get("listings", [])
    offers = data.get("offers", [])

    known_listing_ids = set(state["known_listing_ids"])
    known_offer_ids = set(state["known_offer_ids"])

    for l in listings:
        if l["id"] not in known_listing_ids:
            tg_send(f"🆕 Новый листинг: {l['sfl']} SFL от {l['listedBy']['username']}")
            known_listing_ids.add(l["id"])

    for o in offers:
        if o["tradeId"] not in known_offer_ids:
            tg_send(f"🆕 Новый оффер: {o['sfl']} SFL от {o['offeredBy']['username']}")
            known_offer_ids.add(o["tradeId"])

    state["known_listing_ids"] = list(known_listing_ids)
    state["known_offer_ids"] = list(known_offer_ids)
    save_state(state)


def retrigger_next_run():
    repo = os.environ["GITHUB_REPOSITORY"]
    ref = os.environ["GITHUB_REF_NAME"]
    token = os.environ["GH_TOKEN"]
    try:
        r = requests.post(
            f"https://api.github.com/repos/{repo}/actions/workflows/tracker.yml/dispatches",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
            },
            json={"ref": ref},
            timeout=15,
        )
        r.raise_for_status()
    except Exception as e:
        print(f"Failed to retrigger next run (will rely on schedule safety net): {e}")


def main():
    retrigger_next_run()  # start the next run immediately, don't wait 6h

    state = load_state()
    end_time = time.time() + 6 * 60 * 60  # 6 hours

    while time.time() < end_time:
        try:
            check_once(state)
        except Exception as e:
            print(f"Error during check: {e}")
        time.sleep(60)


if __name__ == "__main__":
    main()

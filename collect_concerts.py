import os
import time
from datetime import datetime, date, timezone
import requests
from supabase import create_client

SEARCHAPI_KEY = os.environ.get("SEARCHAPI_KEY", "").strip()
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "").strip()

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

DESTINATIONS = [
    ("MCO", "Orlando, FL"),
    ("DEN", "Denver, CO"),
    ("HNL", "Honolulu, HI"),
    ("CUN", "Cancun, Mexico"),
    ("LAS", "Las Vegas, NV"),
]


def parse_event_row(ev, dest_code, city_name, holiday_meta, run_ts):
    raw_date = ev.get("date")
    if isinstance(raw_date, dict):
        start_date_val = raw_date.get("start_date")
        when_val = raw_date.get("when")
    else:
        start_date_val = str(raw_date) if raw_date else None
        when_val = str(raw_date) if raw_date else None

    raw_venue = ev.get("venue")
    if isinstance(raw_venue, dict):
        venue_name_val = raw_venue.get("name")
        venue_rating_val = raw_venue.get("rating")
        venue_reviews_val = raw_venue.get("reviews")
    else:
        venue_name_val = str(raw_venue) if raw_venue else None
        venue_rating_val = None
        venue_reviews_val = None

    addr_list = ev.get("address")
    if isinstance(addr_list, list):
        addr_str = ", ".join(str(a) for a in addr_list if a)
    else:
        addr_str = str(addr_list) if addr_list else None

    return {
        "run_timestamp": run_ts,
        "provider": "searchapi",
        "holiday_name": holiday_meta["holiday_name"],
        "days_out": holiday_meta["days_out"],
        "destination_code": dest_code,
        "city_name": city_name,
        "depart_date": holiday_meta["depart_date"],
        "return_date": holiday_meta["return_date"],
        "event_title": ev.get("title"),
        "start_date": start_date_val,
        "when_display": when_val,
        "venue_name": venue_name_val,
        "address_lines": addr_str if addr_str else None,
        "description": ev.get("description"),
        "event_link": ev.get("link"),
        "ticket_info_json": ev.get("ticket_info"),
        "venue_rating": venue_rating_val,
        "venue_reviews": venue_reviews_val,
    }


def collect_city_concerts(dest_code, city_name, holiday_meta, run_ts):
    dep_dt = date.fromisoformat(holiday_meta["depart_date"])
    month_year = dep_dt.strftime("%B %Y")
    query_text = f"Concerts in {city_name} {month_year}"

    url = "https://searchapi.io" + "/api/v1/search"
    headers = {"Accept": "application/json"}
    params = {
        "engine": "google_events",
        "q": query_text,
        "gl": "us",
        "hl": "en",
        "api_key": SEARCHAPI_KEY,
    }

    try:
        resp = requests.get(url, params=params, headers=headers, timeout=20)
        resp.raise_for_status()
        payload = resp.json()

        raw_events = payload.get("events_results") or payload.get("events") or []
        rows = [
            parse_event_row(ev, dest_code, city_name, holiday_meta, run_ts)
            for ev in raw_events
            if isinstance(ev, dict) and ev.get("title")
        ]

        if rows:
            supabase.table("holiday_events_weekly").insert(rows).execute()
            print(f"[OK] {holiday_meta['holiday_name']} | {city_name} ({month_year}) -> {len(rows)} headliners")
        else:
            print(f"[EMPTY] {holiday_meta['holiday_name']} | {city_name} ({month_year}) -> 0 events_results")
    except Exception as exc:
        clean_err = next(iter(str(exc).split("api_key=")))
        print(f"[ERR] {holiday_meta['holiday_name']} | {city_name} -> {clean_err}")


if __name__ == "__main__":
    now_utc = datetime.now(timezone.utc)
    today_utc = now_utc.date()
    run_timestamp = now_utc.isoformat()

    windows = supabase.table("holiday_windows").select("*").eq("is_active", True).execute().data

    active_holidays = []
    for win in windows:
        dep_dt = date.fromisoformat(win["depart_date"])
        days_out = (dep_dt - today_utc).days
        if 0 <= days_out <= win["lead_days_start"]:
            win["days_out"] = days_out
            active_holidays.append(win)

    if not active_holidays:
        print(f"[IDLE] No holidays inside T-120 to T-0 window on {today_utc}.")
    else:
        for h_meta in active_holidays:
            for dest_code, city_name in DESTINATIONS:
                collect_city_concerts(dest_code, city_name, h_meta, run_timestamp)
                time.sleep(0.5)

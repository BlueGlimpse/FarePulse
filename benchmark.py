import os
import time
import statistics
from datetime import datetime, timezone
import requests
from supabase import create_client

SEARCHAPI_KEY = os.environ.get("SEARCHAPI_KEY", "").strip()
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "").strip()

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

ROUTES = [
    ("ATL", "MCO"),
    ("PHX", "DEN"),
    ("LAX", "HNL"),
    ("DFW", "CUN"),
    ("LAX", "LAS"),
]

DEPART_DATE = "2027-03-13"
RETURN_DATE = "2027-03-20"


def normalize_time(raw_time_str):
    if not raw_time_str:
        return ""
    raw_time_str = str(raw_time_str).strip()
    for fmt in ("%I:%M:%S %p", "%I:%M %p"):
        try:
            return datetime.strptime(raw_time_str, fmt).strftime("%H:%M")
        except ValueError:
            pass
    if " " in raw_time_str:
        parts = raw_time_str.split(" ")
        return parts[-1][:5]
    return raw_time_str[:5]


def extract_complete_inventory(raw_json, origin, destination, run_ts, slot_hr):
    tagged_items = []
    for item in raw_json.get("best_flights", []):
        tagged_items.append(("best_flights", item))
    for item in raw_json.get("other_flights", []):
        tagged_items.append(("other_flights", item))

    detail_rows = []
    route_code = f"{origin}-{destination}"

    for bucket, item in tagged_items:
        price = item.get("price")
        legs = item.get("flights", [])
        if price is None or not legs:
            continue

        first_leg = next(iter(legs))
        last_leg = legs[-1]

        dep_obj = first_leg.get("departure_airport", {})
        arr_obj = last_leg.get("arrival_airport", {})

        dep_time = normalize_time(dep_obj.get("time", ""))
        arr_time = normalize_time(arr_obj.get("time", ""))
        total_duration = int(item.get("total_duration", 0))
        stops = len(legs) - 1

        airlines = [str(leg.get("airline", "")).strip() for leg in legs if leg.get("airline")]
        flight_nums = [str(leg.get("flight_number", "")).strip() for leg in legs if leg.get("flight_number")]
        airplanes = [str(leg.get("airplane", "")).strip() for leg in legs if leg.get("airplane")]
        cabins = [str(leg.get("travel_class", "")).strip() for leg in legs if leg.get("travel_class")]
        legrooms = [str(leg.get("legroom", "")).strip() for leg in legs if leg.get("legroom")]

        codeshares = []
        for leg in legs:
            also_sold = leg.get("ticket_also_sold_by", [])
            if isinstance(also_sold, list):
                codeshares.extend(str(c) for c in also_sold if c)

        raw_ext = " ".join(str(x) for x in item.get("extensions", [])).lower()
        leg_ext = " ".join(str(ext) for leg in legs for ext in leg.get("extensions", [])).lower()
        bag_notes = str(item.get("baggage_prices", "")).lower()
        combined_notes = f"{raw_ext} {leg_ext} {bag_notes}"

        carryon_excluded = any(
            phrase in combined_notes
            for phrase in ("no carry-on", "carry-on bag for a fee", "carry-on: $", "carry_on: $")
        )
        cleaned_wifi = combined_notes.replace("no wi-fi", "").replace("without wi-fi", "")

        clock_rollover = bool(dep_time and arr_time and arr_time < dep_time)
        has_overnight = bool(
            any(leg.get("overnight") for leg in legs)
            or any(lay.get("overnight") for lay in item.get("layovers", []))
            or "overnight" in combined_notes
            or clock_rollover
        )
        often_delayed = bool(
            any(leg.get("often_delayed_by_over_30_min") or leg.get("often_delayed") for leg in legs)
            or "often delayed" in combined_notes
        )

        carbon_obj = item.get("carbon_emissions", {})
        this_carbon = carbon_obj.get("this_flight")
        typical_carbon = carbon_obj.get("typical_for_this_route")
        diff_carbon = carbon_obj.get("difference_percent")

        detail_rows.append({
            "run_timestamp": run_ts,
            "slot_hour": slot_hr,
            "provider": "searchapi",
            "route": route_code,
            "origin": origin,
            "destination": destination,
            "depart_date": DEPART_DATE,
            "return_date": RETURN_DATE,
            "flight_bucket": bucket,
            "trip_type": item.get("type"),
            "price": round(float(price), 2),
            "total_duration_min": total_duration,
            "stops": stops,
            "primary_airline": next(iter(airlines), None),
            "all_airlines": " | ".join(dict.fromkeys(airlines)) if airlines else None,
            "flight_numbers": " | ".join(flight_nums) if flight_nums else None,
            "operating_carriers": " | ".join(dict.fromkeys(codeshares)) if codeshares else None,
            "airplane_models": " | ".join(dict.fromkeys(airplanes)) if airplanes else None,
            "travel_classes": " | ".join(dict.fromkeys(cabins)) if cabins else None,
            "legroom_info": " | ".join(dict.fromkeys(legrooms)) if legrooms else None,
            "departure_airport_code": dep_obj.get("id"),
            "departure_airport_name": dep_obj.get("name"),
            "departure_date": dep_obj.get("date", DEPART_DATE),
            "departure_time": dep_time,
            "arrival_airport_code": arr_obj.get("id"),
            "arrival_airport_name": arr_obj.get("name"),
            "arrival_date": arr_obj.get("date"),
            "arrival_time": arr_time,
            "has_overnight": has_overnight,
            "often_delayed": often_delayed,
            "carryon_included": not carryon_excluded,
            "wifi_available": "wi-fi" in cleaned_wifi,
            "power_available": any(k in combined_notes for k in ("power", "outlet", "usb")),
            "video_available": any(k in combined_notes for k in ("video", "entertainment", "live tv")),
            "carbon_grams": int(this_carbon) if isinstance(this_carbon, (int, float)) else None,
            "typical_route_carbon_grams": int(typical_carbon) if isinstance(typical_carbon, (int, float)) else None,
            "carbon_diff_percent": round(float(diff_carbon), 2) if isinstance(diff_carbon, (int, float)) else None,
            "layovers_json": item.get("layovers"),
            "baggage_prices_json": item.get("baggage_prices"),
            "itinerary_extensions_json": item.get("extensions"),
            "legs_full_json": legs,
        })
    if not detail_rows:
        return None, []

    prices = sorted(r["price"] for r in detail_rows)
    count = len(detail_rows)
    nonstop_total = sum(1 for r in detail_rows if r["stops"] == 0)

    if count >= 4:
        q_slices = statistics.quantiles(prices, n=4)
        p25_val = next(iter(q_slices))
        p75_val = q_slices[-1]
    else:
        p25_val = min(prices)
        p75_val = max(prices)

    insights = raw_json.get("price_insights", {})
    typ_range = insights.get("typical_price_range")
    typ_low = None
    typ_high = None

    if isinstance(typ_range, dict):
        if isinstance(typ_range.get("low_price"), (int, float)):
            typ_low = float(typ_range["low_price"])
        if isinstance(typ_range.get("high_price"), (int, float)):
            typ_high = float(typ_range["high_price"])
    elif isinstance(typ_range, list) and len(typ_range) >= 2:
        typ_low = float(min(typ_range))
        typ_high = float(max(typ_range))

    summary_row = {
        "run_timestamp": run_ts,
        "slot_hour": slot_hr,
        "provider": "searchapi",
        "route": route_code,
        "origin": origin,
        "destination": destination,
        "depart_date": DEPART_DATE,
        "return_date": RETURN_DATE,
        "total_options_found": count,
        "nonstop_count": nonstop_total,
        "connecting_count": count - nonstop_total,
        "lowest_price": round(min(prices), 2),
        "p25_price": round(p25_val, 2),
        "median_price": round(statistics.median(prices), 2),
        "average_price": round(statistics.mean(prices), 2),
        "p75_price": round(p75_val, 2),
        "highest_price": round(max(prices), 2),
        "google_price_level": insights.get("price_level"),
        "google_typical_low": typ_low,
        "google_typical_high": typ_high,
        "google_price_history": insights.get("price_history"),
        "airports_metadata": raw_json.get("airports"),
        "status": "success",
    }

    return summary_row, detail_rows


def collect_route(origin, destination, run_ts, slot_hr):
    start_time = time.perf_counter()
    url = "https://searchapi.io" + "/api/v1/search"
    headers = {"Accept": "application/json"}
    params = {
        "engine": "google_flights",
        "departure_id": origin,
        "arrival_id": destination,
        "outbound_date": DEPART_DATE,
        "return_date": RETURN_DATE,
        "flight_type": "round_trip",
        "currency": "USD",
        "gl": "us",
        "hl": "en",
        "api_key": SEARCHAPI_KEY,
    }

    try:
        resp = requests.get(url, params=params, headers=headers, timeout=45)
        elapsed_ms = int((time.perf_counter() - start_time) * 1000)
        resp.raise_for_status()

        payload = resp.json()
        summary_row, detail_rows = extract_complete_inventory(
            payload, origin, destination, run_ts, slot_hr
        )

        if not summary_row:
            raise ValueError(f"No flight options returned. Keys: {list(payload.keys())}")

        summary_row["response_time_ms"] = elapsed_ms
        supabase.table("fare_details_hourly").insert(detail_rows).execute()
        supabase.table("fare_summary_hourly").insert(summary_row).execute()

        print(f"[OK] {origin}-{destination} in {elapsed_ms}ms -> {len(detail_rows)} flights | Lowest ${summary_row['lowest_price']}")
    except Exception as exc:
        elapsed_ms = int((time.perf_counter() - start_time) * 1000)
        clean_err = next(iter(str(exc).split("api_key=")))
        err_row = {
            "run_timestamp": run_ts,
            "slot_hour": slot_hr,
            "provider": "searchapi",
            "route": f"{origin}-{destination}",
            "origin": origin,
            "destination": destination,
            "depart_date": DEPART_DATE,
            "return_date": RETURN_DATE,
            "response_time_ms": elapsed_ms,
            "status": "error",
            "error_message": clean_err,
        }
        supabase.table("fare_summary_hourly").insert(err_row).execute()
        print(f"[ERR] {origin}-{destination} in {elapsed_ms}ms -> {clean_err}")


if __name__ == "__main__":
    now_utc = datetime.now(timezone.utc)
    run_timestamp = now_utc.isoformat()
    slot_hour = now_utc.replace(minute=0, second=0, microsecond=0).isoformat()

    for orig, dest in ROUTES:
        collect_route(orig, dest, run_timestamp, slot_hour)
        time.sleep(1)

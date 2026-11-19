# FarePulse — Holiday Airfare Tracking Pipeline

Automated hourly airfare collection and benchmarking pipeline tracking consumer vacation corridors across rolling **T-120 to T-0** advance-purchase windows.

---

## Architecture Overview

* **Data Source:** SearchApi (`google_flights` engine, US point-of-sale, USD)
* **Scheduler:** GitHub Actions (`.github/workflows/collect.yml`) running hourly at `:07` past the hour
* **Collector Script:** Python 3.11 (`collect_fares.py`)
* **Database:** Supabase PostgreSQL (`holiday_windows`, `fare_summary_hourly`, `fare_details_hourly`)

---

## Tracked Routes

| Origin | Destination | Market Profile |
| :--- | :--- | :--- |
| **ATL** | **MCO** | High-frequency family theme-park corridor |
| **PHX** | **DEN** | Winter ski & mountain leisure route |
| **LAX** | **HNL** | Long-haul domestic island vacation route |
| **DFW** | **CUN** | Short-haul international resort corridor |
| **LAX** | **LAS** | High-frequency weekend leisure market |

---

## Automated T-120 Holiday Windows

The collector dynamically checks `holiday_windows` each hour and activates polling when `0 <= (depart_date - today) <= 120`.

| Holiday Window | Outbound Date | Return Date | Lead Window |
| :--- | :--- | :--- | :--- |
| **Christmas 2026** | 2026-12-23 | 2026-12-30 | T-120 to T-0 |
| **New Year's 2027** | 2026-12-30 | 2027-01-03 | T-120 to T-0 |
| **Presidents' Day 2027** | 2027-02-12 | 2027-02-15 | T-120 to T-0 |
| **Spring Break 2027** | 2027-03-13 | 2027-03-20 | T-120 to T-0 |
| **Memorial Day 2027** | 2027-05-28 | 2027-05-31 | T-120 to T-0 |
| **July 4th 2027** | 2027-07-02 | 2027-07-09 | T-120 to T-0 |
| **Labor Day 2027** | 2027-09-03 | 2027-09-06 | T-120 to T-0 |
| **Thanksgiving 2027** | 2027-11-24 | 2027-11-28 | T-120 to T-0 |
| **Christmas 2027** | 2027-12-22 | 2027-12-29 | T-120 to T-0 |

---

## Repository Structure

```text
FarePulse/
├── .github/
│   └── workflows/
│       └── collect.yml      # Hourly GitHub Actions cron schedule (:07)
├── collect_fares.py         # T-120 gate, API fetcher, parser, and Supabase loader
└── README.md                # Pipeline documentation and operational status
```

---

## Required GitHub Secrets

Configured under **Settings → Secrets and variables → Actions**:

1. `SEARCHAPI_KEY` — SearchApi production API key
2. `SUPABASE_URL` — Supabase project API endpoint (`https://<project-id>.supabase.co`)
3. `SUPABASE_SERVICE_KEY` — Supabase `service_role` secret key

---

## Database Schema

* **`holiday_windows`:** Master schedule controlling active departure/return date pairs and `lead_days_start` thresholds.
* **`fare_summary_hourly`:** Route-level hourly aggregations (`lowest_price`, `p25_price`, `median_price`, `average_price`, `p75_price`, `highest_price`), option counts, and Google `price_insights`.
* **`fare_details_hourly`:** Complete itinerary-level records including carrier names, flight numbers, aircraft models, legroom, layovers, baggage rules, and carbon estimates.

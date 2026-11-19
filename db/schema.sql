-- ============================================================================
-- FarePulse Production Database Schema
-- Provider: SearchApi (google_flights engine)
-- Cadence: Hourly T-120 to T-0 dynamic holiday polling
-- ============================================================================

-- 1. Holiday Windows Master Schedule
-- Controls which static vacation date ranges are actively polled.
-- Collector activates when: 0 <= (depart_date - current_date) <= lead_days_start
CREATE TABLE IF NOT EXISTS holiday_windows (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    holiday_name TEXT UNIQUE NOT NULL,
    depart_date DATE NOT NULL,
    return_date DATE NOT NULL,
    lead_days_start INTEGER NOT NULL DEFAULT 120,
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

-- Seed Holiday Windows (2026–2027)
INSERT INTO holiday_windows (holiday_name, depart_date, return_date, lead_days_start) VALUES
    ('Christmas 2026', '2026-12-23', '2026-12-30', 120),
    ('New Years 2027', '2026-12-30', '2027-01-03', 120),
    ('Presidents Day 2027', '2027-02-12', '2027-02-15', 120),
    ('Spring Break 2027', '2027-03-13', '2027-03-20', 120),
    ('Memorial Day 2027', '2027-05-28', '2027-05-31', 120),
    ('July 4th 2027', '2027-07-02', '2027-07-09', 120),
    ('Labor Day 2027', '2027-09-03', '2027-09-06', 120),
    ('Thanksgiving 2027', '2027-11-24', '2027-11-28', 120),
    ('Christmas 2027', '2027-12-22', '2027-12-29', 120)
ON CONFLICT (holiday_name) DO NOTHING;

-- 2. Hourly Route Summary & Price Distribution Table
-- Stores one aggregate snapshot per route + holiday window per UTC hour.
CREATE TABLE IF NOT EXISTS fare_summary_hourly (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_timestamp TIMESTAMPTZ NOT NULL,
    slot_hour TIMESTAMPTZ NOT NULL,
    provider TEXT NOT NULL DEFAULT 'searchapi',
    holiday_name TEXT,
    days_out INTEGER,
    route TEXT NOT NULL,
    origin CHAR(3) NOT NULL,
    destination CHAR(3) NOT NULL,
    depart_date DATE NOT NULL,
    return_date DATE NOT NULL,
    response_time_ms INTEGER,
    total_options_found INTEGER,
    nonstop_count INTEGER,
    connecting_count INTEGER,
    lowest_price NUMERIC(10, 2),
    p25_price NUMERIC(10, 2),
    median_price NUMERIC(10, 2),
    average_price NUMERIC(10, 2),
    p75_price NUMERIC(10, 2),
    highest_price NUMERIC(10, 2),
    google_price_level TEXT,
    google_typical_low NUMERIC(10, 2),
    google_typical_high NUMERIC(10, 2),
    google_price_history JSONB,
    airports_metadata JSONB,
    status TEXT DEFAULT 'success',
    error_message TEXT
);

-- 3. Hourly Flight-Level Detail Table
-- Stores complete itinerary-level data for every flight returned per run.
CREATE TABLE IF NOT EXISTS fare_details_hourly (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_timestamp TIMESTAMPTZ NOT NULL,
    slot_hour TIMESTAMPTZ NOT NULL,
    provider TEXT NOT NULL DEFAULT 'searchapi',
    holiday_name TEXT,
    days_out INTEGER,
    route TEXT NOT NULL,
    origin CHAR(3) NOT NULL,
    destination CHAR(3) NOT NULL,
    depart_date DATE NOT NULL,
    return_date DATE NOT NULL,
    flight_bucket TEXT,
    trip_type TEXT,
    price NUMERIC(10, 2),
    total_duration_min INTEGER,
    stops INTEGER,
    primary_airline TEXT,
    all_airlines TEXT,
    flight_numbers TEXT,
    operating_carriers TEXT,
    airplane_models TEXT,
    travel_classes TEXT,
    legroom_info TEXT,
    departure_airport_code TEXT,
    departure_airport_name TEXT,
    departure_date TEXT,
    departure_time TEXT,
    arrival_airport_code TEXT,
    arrival_airport_name TEXT,
    arrival_date TEXT,
    arrival_time TEXT,
    has_overnight BOOLEAN,
    often_delayed BOOLEAN,
    carryon_included BOOLEAN,
    wifi_available BOOLEAN,
    power_available BOOLEAN,
    video_available BOOLEAN,
    carbon_grams INTEGER,
    typical_route_carbon_grams INTEGER,
    carbon_diff_percent NUMERIC(5, 2),
    layovers_json JSONB,
    baggage_prices_json JSONB,
    itinerary_extensions_json JSONB,
    legs_full_json JSONB
);

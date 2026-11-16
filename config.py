import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'aero-delay-ops-secret-key-2026')
    DEBUG = os.environ.get('FLASK_DEBUG', 'False').lower() in ('true', '1')
    
    # 1. Arrival Delay Model & Data (2023 BTS TranStats)
    ARRIVAL_MODEL_PATH = BASE_DIR / 'model' / 'arrival_models.joblib'
    ARRIVAL_RESULTS_PATH = BASE_DIR / 'model' / 'arrival_results_for_website.json'
    ARRIVAL_PARQUET_PATH = BASE_DIR / 'data' / 'bts_2023_arrival_clean.parquet'
    
    # 2. Departure Delay Model & Data (2024 BTS TranStats)
    DEPARTURE_MODEL_PATH = BASE_DIR / 'model' / 'departure_models.joblib'
    DEPARTURE_RESULTS_PATH = BASE_DIR / 'model' / 'departure_results_for_website.json'
    DEPARTURE_PARQUET_PATH = BASE_DIR / 'data' / 'flights_weather_2024_10airports.parquet'
    
    # Backward compatibility aliases
    MODEL_PATH = ARRIVAL_MODEL_PATH
    RESULTS_JSON_PATH = ARRIVAL_RESULTS_PATH
    PARQUET_PATH = ARRIVAL_PARQUET_PATH
    BACKUP_PARQUET_PATH = BASE_DIR.parent / 'raw_data' / 'flights_weather_2023.parquet'
    
    # Airlines mapping
    AIRLINES = {
        'AA': 'American Airlines',
        'DL': 'Delta Air Lines',
        'UA': 'United Airlines',
        'WN': 'Southwest Airlines',
        'AS': 'Alaska Airlines',
        'B6': 'JetBlue Airways',
        'NK': 'Spirit Airlines',
        'F9': 'Frontier Airlines',
        'OO': 'SkyWest Airlines',
        'YX': 'Republic Airways',
        'MQ': 'Envoy Air',
        '9E': 'Endeavor Air',
        'OH': 'PSA Airlines'
    }
    
    # Airport hubs mapping
    AIRPORTS = {
        'ATL': {'name': 'Hartsfield-Jackson Atlanta International Airport', 'city': 'Atlanta, GA'},
        'CLT': {'name': 'Charlotte Douglas International Airport', 'city': 'Charlotte, NC'},
        'DEN': {'name': 'Denver International Airport', 'city': 'Denver, CO'},
        'DFW': {'name': 'Dallas/Fort Worth International Airport', 'city': 'Dallas, TX'},
        'LAS': {'name': 'Harry Reid International Airport', 'city': 'Las Vegas, NV'},
        'LAX': {'name': 'Los Angeles International Airport', 'city': 'Los Angeles, CA'},
        'MCO': {'name': 'Orlando International Airport', 'city': 'Orlando, FL'},
        'ORD': {'name': "Chicago O'Hare International Airport", 'city': 'Chicago, IL'},
        'PHX': {'name': 'Phoenix Sky Harbor International Airport', 'city': 'Phoenix, AZ'},
        'SEA': {'name': 'Seattle-Tacoma International Airport', 'city': 'Seattle, WA'}
    }
    
    # Arrival model features (38 features)
    ARRIVAL_MODEL_FEATURES = [
        'airline', 'origin', 'dest', 'sched_dep_hour', 'day_of_week', 'wx_sky_cover',
        'distance_mi', 'crs_elapsed_min', 'is_holiday_window', 'wx_temp_f', 'wx_wind_kt',
        'wx_gust_kt', 'wx_vis_mi', 'wx_precip_1h_in', 'wx_ceiling_ft', 'wx_has_gust',
        'wx_rain', 'wx_snow', 'wx_thunder', 'wx_fog', 'wx_mist', 'wx_drizzle',
        'wx_haze', 'wx_freezing', 'wx_ice_hail', 'wx_heavy', 'hist_route_arr_rate',
        'hist_airline_arr_rate', 'hist_origin_arr_rate', 'dep_delay_clip',
        'dep_late_15', 'dep_late_30', 'dep_late_60', 'tail_leg_of_day',
        'prev_arr_delay', 'prev_dep_delay', 'sched_turn_min', 'prev_legs_mean_arr_delay'
    ]
    MODEL_FEATURES = ARRIVAL_MODEL_FEATURES
    
    # Departure model features (40 features)
    DEPARTURE_MODEL_FEATURES = [
        'airline', 'origin', 'dest', 'sched_dep_hour', 'day_of_week', 'wx_sky_cover',
        'distance_mi', 'is_holiday_window', 'wx_temp_f', 'wx_wind_kt', 'wx_gust_kt',
        'wx_vis_mi', 'wx_precip_1h_in', 'wx_ceiling_ft', 'wx_has_gust', 'wx_rain',
        'wx_snow', 'wx_thunder', 'wx_fog', 'wx_mist', 'wx_drizzle', 'wx_haze',
        'wx_freezing', 'wx_ice_hail', 'wx_heavy', 'hist_route_rate',
        'hist_route_hour_rate', 'hist_airline_rate', 'hist_origin_rate',
        'hist_origin_rate_7d', 'hist_route_rate_7d', 'hist_origin_prevday_rate',
        'hist_origin_hour_rate', 'hist_airline_origin_rate', 'airport_late_rate_1h',
        'airport_late_rate_3h', 'airport_late_rate_6h', 'airport_n_3h',
        'airport_mean_delay_3h', 'airport_sched_load_60'
    ]
    
    # Default model and thresholds
    DEFAULT_MODEL = 'Gradient boosting'
    ARRIVAL_THRESHOLDS = {
        'Gradient boosting': 0.6587735313612055,
        'Logistic regression': 0.682254237749569,
        'Random forest': 0.6941011547121909
    }
    DEFAULT_THRESHOLDS = ARRIVAL_THRESHOLDS
    
    DEPARTURE_THRESHOLDS = {
        'Gradient boosting': 0.5260330050762863,
        'Logistic regression': 0.53048845674267,
        'Random forest': 0.49399063484955436,
        'Average ensemble': 0.5164371469330874
    }

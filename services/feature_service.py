import numpy as np
import pandas as pd
from pandas.tseries.holiday import USFederalHolidayCalendar
from config import Config


class FeatureService:
    """
    Handles feature extraction, preparation, validation, and leakage prevention
    for both flight arrival delay and departure delay predictions.
    """
    ARRIVAL_FORBIDDEN_FEATURES = {
        'arr_delay_min', 'arr_del15', 'split', 'wx_obs_utc', 'wx_cutoff_utc',
        'wx_age_min', 'sched_dep_utc', 'sched_dep_local', 'flight_date', 'month'
    }

    DEPARTURE_FORBIDDEN_FEATURES = {
        'dep_delay_min', 'dep_del15', 'arr_delay_min', 'arr_del15', 'cancelled', 'diverted',
        'split', 'wx_obs_utc', 'wx_cutoff_utc', 'wx_age_min', 'sched_dep_utc', 'sched_dep_local'
    }

    def __init__(self):
        self.arrival_features = list(Config.ARRIVAL_MODEL_FEATURES)
        self.departure_features = list(Config.DEPARTURE_MODEL_FEATURES)
        self.expected_features = self.arrival_features
        self.cal = USFederalHolidayCalendar()
        self.holidays = self.cal.holidays(start='2022-01-01', end='2027-12-31')

    def check_holiday_window(self, flight_date):
        """Returns 1 if flight_date is within +/- 3 days of a US federal holiday, else 0."""
        try:
            ts = pd.to_datetime(flight_date)
            for h in self.holidays:
                if abs((ts - h).days) <= 3:
                    return 1
            return 0
        except Exception:
            return 0

    def prepare_features_from_dict(self, raw_data, target_type='arrival'):
        """
        Prepares a single-row DataFrame with the exact features and order
        required for either arrival delay or departure delay prediction.
        """
        if target_type == 'departure':
            return self.prepare_departure_features(raw_data)
        else:
            return self.prepare_arrival_features(raw_data)

    def prepare_arrival_features(self, raw_data):
        """Prepares features for Arrival Delay Prediction (38 features)."""
        row = {}

        # 1. Categorical features
        row['airline'] = str(raw_data.get('airline', 'UNK')).strip().upper()
        row['origin'] = str(raw_data.get('origin', 'UNK')).strip().upper()
        row['dest'] = str(raw_data.get('dest', 'UNK')).strip().upper()
        row['sched_dep_hour'] = str(raw_data.get('sched_dep_hour', '12')).strip()
        row['day_of_week'] = str(raw_data.get('day_of_week', '1')).strip()
        
        sky_cover = raw_data.get('wx_sky_cover')
        row['wx_sky_cover'] = 'UNK' if (pd.isna(sky_cover) or not sky_cover) else str(sky_cover).strip().upper()

        # 2. Numerical flight schedule & route features
        row['distance_mi'] = float(raw_data.get('distance_mi', 500.0) if not pd.isna(raw_data.get('distance_mi')) else 500.0)
        row['crs_elapsed_min'] = float(raw_data.get('crs_elapsed_min', 90.0) if not pd.isna(raw_data.get('crs_elapsed_min')) else 90.0)

        # Holiday window
        if 'is_holiday_window' in raw_data and not pd.isna(raw_data['is_holiday_window']):
            row['is_holiday_window'] = int(raw_data['is_holiday_window'])
        elif 'flight_date' in raw_data:
            row['is_holiday_window'] = self.check_holiday_window(raw_data['flight_date'])
        else:
            row['is_holiday_window'] = 0

        # 3. Origin weather features
        weather_numeric = [
            ('wx_temp_f', 60.0), ('wx_wind_kt', 7.0), ('wx_gust_kt', 0.0),
            ('wx_vis_mi', 10.0), ('wx_precip_1h_in', 0.0), ('wx_ceiling_ft', 25000.0),
            ('wx_has_gust', 0.0), ('wx_rain', 0.0), ('wx_snow', 0.0), ('wx_thunder', 0.0),
            ('wx_fog', 0.0), ('wx_mist', 0.0), ('wx_drizzle', 0.0), ('wx_haze', 0.0),
            ('wx_freezing', 0.0), ('wx_ice_hail', 0.0), ('wx_heavy', 0.0)
        ]
        for w_col, default_val in weather_numeric:
            val = raw_data.get(w_col)
            row[w_col] = float(val) if val is not None and not pd.isna(val) else default_val

        # 4. Historical arrival delay rates (trailing 30-day)
        rate_cols = ['hist_route_arr_rate', 'hist_airline_arr_rate', 'hist_origin_arr_rate']
        for r_col in rate_cols:
            val = raw_data.get(r_col)
            row[r_col] = float(val) if val is not None and not pd.isna(val) else np.nan

        # 5. Departure delay features (known upon departure)
        dep_delay = raw_data.get('dep_delay_min')
        dep_delay_val = 0.0 if (dep_delay is None or pd.isna(dep_delay)) else float(dep_delay)

        row['dep_delay_clip'] = float(np.clip(dep_delay_val, -30.0, 300.0))
        row['dep_late_15'] = int(dep_delay_val >= 15.0)
        row['dep_late_30'] = int(dep_delay_val >= 30.0)
        row['dep_late_60'] = int(dep_delay_val >= 60.0)

        # 6. Aircraft rotation features
        rotation_cols = ['tail_leg_of_day', 'prev_arr_delay', 'prev_dep_delay', 'sched_turn_min', 'prev_legs_mean_arr_delay']
        for rot_col in rotation_cols:
            val = raw_data.get(rot_col)
            row[rot_col] = float(val) if val is not None and not pd.isna(val) else np.nan

        for f in self.ARRIVAL_FORBIDDEN_FEATURES:
            if f in row:
                del row[f]

        df = pd.DataFrame([row])
        return df[self.arrival_features]

    def prepare_departure_features(self, raw_data):
        """Prepares features for Departure Delay Prediction (40 features)."""
        row = {}

        # 1. Categoricals
        row['airline'] = str(raw_data.get('airline', 'UNK')).strip().upper()
        row['origin'] = str(raw_data.get('origin', 'UNK')).strip().upper()
        row['dest'] = str(raw_data.get('dest', 'UNK')).strip().upper()
        row['sched_dep_hour'] = str(raw_data.get('sched_dep_hour', '12')).strip()
        row['day_of_week'] = str(raw_data.get('day_of_week', '1')).strip()
        
        sky_cover = raw_data.get('wx_sky_cover')
        row['wx_sky_cover'] = 'UNK' if (pd.isna(sky_cover) or not sky_cover) else str(sky_cover).strip().upper()

        # 2. Flight distance & holiday
        row['distance_mi'] = float(raw_data.get('distance_mi', 500.0) if not pd.isna(raw_data.get('distance_mi')) else 500.0)
        if 'is_holiday_window' in raw_data and not pd.isna(raw_data['is_holiday_window']):
            row['is_holiday_window'] = int(raw_data['is_holiday_window'])
        elif 'flight_date' in raw_data:
            row['is_holiday_window'] = self.check_holiday_window(raw_data['flight_date'])
        else:
            row['is_holiday_window'] = 0

        # 3. Weather features
        weather_numeric = [
            ('wx_temp_f', 60.0), ('wx_wind_kt', 7.0), ('wx_gust_kt', 0.0),
            ('wx_vis_mi', 10.0), ('wx_precip_1h_in', 0.0), ('wx_ceiling_ft', 25000.0),
            ('wx_has_gust', 0.0), ('wx_rain', 0.0), ('wx_snow', 0.0), ('wx_thunder', 0.0),
            ('wx_fog', 0.0), ('wx_mist', 0.0), ('wx_drizzle', 0.0), ('wx_haze', 0.0),
            ('wx_freezing', 0.0), ('wx_ice_hail', 0.0), ('wx_heavy', 0.0)
        ]
        for w_col, default_val in weather_numeric:
            val = raw_data.get(w_col)
            row[w_col] = float(val) if val is not None and not pd.isna(val) else default_val

        # 4. Trailing historical departure rates
        dep_rate_cols = [
            'hist_route_rate', 'hist_route_hour_rate', 'hist_airline_rate',
            'hist_origin_rate', 'hist_origin_rate_7d', 'hist_route_rate_7d',
            'hist_origin_prevday_rate', 'hist_origin_hour_rate', 'hist_airline_origin_rate'
        ]
        for r_col in dep_rate_cols:
            val = raw_data.get(r_col)
            row[r_col] = float(val) if val is not None and not pd.isna(val) else np.nan

        # 5. Airport operational load & congestion features (pre-departure)
        airport_cols = [
            'airport_late_rate_1h', 'airport_late_rate_3h', 'airport_late_rate_6h',
            'airport_n_3h', 'airport_mean_delay_3h', 'airport_sched_load_60'
        ]
        for a_col in airport_cols:
            val = raw_data.get(a_col)
            row[a_col] = float(val) if val is not None and not pd.isna(val) else np.nan

        for f in self.DEPARTURE_FORBIDDEN_FEATURES:
            if f in row:
                del row[f]

        df = pd.DataFrame([row])
        return df[self.departure_features]


feature_service = FeatureService()

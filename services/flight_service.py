import logging
import datetime
from pathlib import Path
import pandas as pd
import numpy as np
from config import Config

logger = logging.getLogger(__name__)


def format_military_time(val):
    """Converts integer time (e.g. 815 or 1430 or 51) to 'HH:MM AM/PM'."""
    try:
        if pd.isna(val) or val is None:
            return "N/A"
        val = int(val)
        hours = val // 100
        mins = val % 100
        hours = max(0, min(23, hours))
        mins = max(0, min(59, mins))
        t = datetime.time(hours, mins)
        return t.strftime("%I:%M %p")
    except Exception:
        return str(val)


def calculate_actual_dep_time(sched_crs_dep, dep_delay_min):
    """Computes actual departure time based on scheduled CRS time and delay."""
    try:
        if pd.isna(sched_crs_dep) or sched_crs_dep is None:
            return "N/A"
        sched_val = int(sched_crs_dep)
        sched_hours = sched_val // 100
        sched_mins = sched_val % 100
        
        delay = int(dep_delay_min) if (dep_delay_min is not None and not pd.isna(dep_delay_min)) else 0
        total_mins = sched_hours * 60 + sched_mins + delay
        
        total_mins = total_mins % (24 * 60)
        act_hours = total_mins // 60
        act_mins = total_mins % 60
        t = datetime.time(act_hours, act_mins)
        return t.strftime("%I:%M %p")
    except Exception:
        return "N/A"


class FlightService:
    """
    Manages historical flight dataset lookup, indexed queries across both
    2023 (Arrival Delay) and 2024 (Departure Delay) corpuses.
    """
    def __init__(self):
        self.df = None
        self.lookup_index = {}
        self.is_loaded = False
        self.total_2023 = 0
        self.total_2024 = 0
        self.load_dataset()

    def load_dataset(self):
        """Loads both 2023 and 2024 parquet datasets into memory and creates an in-memory index."""
        dfs = []

        # 1. 2023 Arrival Delay Dataset
        if Config.ARRIVAL_PARQUET_PATH.exists():
            try:
                df23 = pd.read_parquet(Config.ARRIVAL_PARQUET_PATH)
                df23['flight_date'] = pd.to_datetime(df23['flight_date'])
                if 'split' not in df23.columns:
                    m = df23['flight_date'].dt.month
                    df23['split'] = 'train'
                    df23.loc[m == 10, 'split'] = 'validation'
                    df23.loc[m.isin([11, 12]), 'split'] = 'test'
                self.total_2023 = len(df23)
                dfs.append(df23)
                logger.info("Loaded 2023 Arrival Dataset (%d flights)", len(df23))
            except Exception as e:
                logger.error("Error loading 2023 arrival parquet: %s", e)

        # 2. 2024 Departure Delay Dataset
        if Config.DEPARTURE_PARQUET_PATH.exists():
            try:
                df24 = pd.read_parquet(Config.DEPARTURE_PARQUET_PATH)
                df24['flight_date'] = pd.to_datetime(df24['flight_date'])
                if 'split' not in df24.columns:
                    m = df24['flight_date'].dt.month
                    df24['split'] = 'train'
                    df24.loc[m == 5, 'split'] = 'validation'
                    df24.loc[m.isin([6, 7]), 'split'] = 'test'
                self.total_2024 = len(df24)
                dfs.append(df24)
                logger.info("Loaded 2024 Departure Dataset (%d flights)", len(df24))
            except Exception as e:
                logger.error("Error loading 2024 departure parquet: %s", e)

        if not dfs and Config.BACKUP_PARQUET_PATH.exists():
            try:
                df_bk = pd.read_parquet(Config.BACKUP_PARQUET_PATH)
                df_bk['flight_date'] = pd.to_datetime(df_bk['flight_date'])
                dfs.append(df_bk)
            except Exception as e:
                logger.error("Error loading backup parquet: %s", e)

        if dfs:
            try:
                self.df = pd.concat(dfs, ignore_index=True)
                self.df['date_str'] = self.df['flight_date'].dt.strftime('%Y-%m-%d')
                self.df['flight_number'] = self.df['flight_number'].astype(int)
                for col in ['airline', 'origin', 'dest']:
                    if col in self.df.columns:
                        self.df[col] = self.df[col].astype(str).str.strip().str.upper()

                logger.info("Building in-memory flight search index...")
                self.lookup_index = self.df.groupby(['date_str', 'flight_number']).indices
                self.is_loaded = True
                logger.info("Flight database ready. Total %d flights indexed across %d unique date/flight keys.",
                            len(self.df), len(self.lookup_index))
                return True
            except Exception as e:
                logger.error("Error building combined flight index: %s", e, exc_info=True)
                self.is_loaded = False
                return False
        else:
            logger.error("No flight datasets could be loaded.")
            self.is_loaded = False
            return False

    def search_flight(self, date_str, flight_number, airline=None, origin=None):
        """
        Searches for flights matching date and flight number across 2023 and 2024.
        """
        if not self.is_loaded or self.df is None:
            return {
                'status': 'error',
                'count': 0,
                'message': 'Flight database is not loaded. Please verify data files.'
            }

        date_str = str(date_str).strip()
        try:
            fl_num = int(str(flight_number).strip().replace('#', '').replace('FL', ''))
        except ValueError:
            return {
                'status': 'invalid_input',
                'count': 0,
                'message': f"Invalid flight number '{flight_number}'. Please enter an integer (e.g., 1562 or 26)."
            }

        matching_indices = self.lookup_index.get((date_str, fl_num))
        if matching_indices is None or len(matching_indices) == 0:
            return {
                'status': 'not_found',
                'count': 0,
                'message': f"No flight records found for Flight #{fl_num} on {date_str}. The database covers historical flights across 2023 and 2024.",
                'date_searched': date_str,
                'flight_number_searched': fl_num
            }

        matched_df = self.df.iloc[matching_indices]

        if airline:
            airline_code = str(airline).strip().upper()
            filtered = matched_df[matched_df['airline'] == airline_code]
            if len(filtered) > 0:
                matched_df = filtered

        if origin:
            origin_code = str(origin).strip().upper()
            filtered = matched_df[matched_df['origin'] == origin_code]
            if len(filtered) > 0:
                matched_df = filtered

        count = len(matched_df)

        if count == 1:
            flight_dict = self._format_flight_record(matched_df.iloc[0])
            return {
                'status': 'exact_match',
                'count': 1,
                'flight': flight_dict,
                'raw_record': self._sanitize_record(matched_df.iloc[0]),
                'message': 'Flight found successfully.'
            }
        else:
            matches_list = []
            for idx, (_, row) in enumerate(matched_df.iterrows()):
                rec = self._format_flight_record(row)
                rec['match_id'] = idx
                matches_list.append(rec)

            return {
                'status': 'multiple_matches',
                'count': count,
                'matches': matches_list,
                'message': f"{count} flights match Flight #{fl_num} on {date_str}. Please select the specific leg/airline below."
            }

    def _sanitize_record(self, row):
        """Converts row to dict and sanitizes NaN/inf values for JSON serialization."""
        clean = {}
        for k, v in row.to_dict().items():
            if pd.isna(v):
                clean[k] = None
            elif isinstance(v, (np.floating, float)):
                clean[k] = None if (np.isnan(v) or np.isinf(v)) else float(v)
            elif isinstance(v, (np.integer, int)):
                clean[k] = int(v)
            elif isinstance(v, pd.Timestamp):
                clean[k] = v.strftime('%Y-%m-%d')
            else:
                clean[k] = v
        return clean

    def _format_flight_record(self, row):
        """Formats raw row into presentation-ready flight information."""
        airline_code = str(row.get('airline', 'UNK'))
        airline_name = Config.AIRLINES.get(airline_code, f"{airline_code} Airlines")
        
        origin_code = str(row.get('origin', 'UNK'))
        origin_info = Config.AIRPORTS.get(origin_code, {'name': f"{origin_code} Airport", 'city': origin_code})
        
        dest_code = str(row.get('dest', 'UNK'))
        dest_info = Config.AIRPORTS.get(dest_code, {'name': f"{dest_code} Airport", 'city': dest_code})

        dep_delay = row.get('dep_delay_min', 0)
        dep_delay_val = int(dep_delay) if not pd.isna(dep_delay) else 0

        sched_dep_fmt = format_military_time(row.get('crs_dep_time'))
        actual_dep_fmt = calculate_actual_dep_time(row.get('crs_dep_time'), dep_delay_val)
        sched_arr_fmt = format_military_time(row.get('crs_arr_time'))

        dep_delay_str = f"+{dep_delay_val} min" if dep_delay_val > 0 else (f"{dep_delay_val} min" if dep_delay_val < 0 else "On Time (0 min)")
        dep_status = "Delayed (≥15m)" if dep_delay_val >= 15 else ("Moderate Delay" if dep_delay_val > 0 else "On Time (<15m)")
        dep_badge_color = "danger" if dep_delay_val >= 15 else ("warning" if dep_delay_val > 0 else "success")

        # Arrival delay info
        arr_delay_raw = row.get('arr_delay_min')
        has_actual_arr = arr_delay_raw is not None and not pd.isna(arr_delay_raw)
        actual_arr_delay = int(arr_delay_raw) if has_actual_arr else None
        actual_arr_status = "Delayed (15+ min)" if (has_actual_arr and actual_arr_delay >= 15) else ("On Time (<15 min)" if has_actual_arr else "N/A")

        # Flight distance and duration
        elapsed_min = int(row.get('crs_elapsed_min', 0)) if not pd.isna(row.get('crs_elapsed_min')) else 0
        duration_str = f"{elapsed_min // 60}h {elapsed_min % 60}m" if elapsed_min > 0 else "N/A"
        dist_mi = int(row.get('distance_mi', 0)) if not pd.isna(row.get('distance_mi')) else 0

        # Weather presentation
        temp_f = row.get('wx_temp_f')
        wind_kt = row.get('wx_wind_kt')
        sky_cover = row.get('wx_sky_cover', 'UNK')
        visibility = row.get('wx_vis_mi')
        has_rain = bool(row.get('wx_rain', 0) == 1)
        has_snow = bool(row.get('wx_snow', 0) == 1)
        has_fog = bool(row.get('wx_fog', 0) == 1)
        has_thunder = bool(row.get('wx_thunder', 0) == 1)

        weather_tags = []
        if has_rain: weather_tags.append("Rain")
        if has_snow: weather_tags.append("Snow")
        if has_fog: weather_tags.append("Fog")
        if has_thunder: weather_tags.append("Thunderstorm")
        if not weather_tags:
            weather_tags.append("Fair / Clear" if sky_cover in ['CLR', 'FEW'] else "Cloudy")

        # Aircraft rotation
        tail_num = str(row.get('tail_num', 'N/A')) if not pd.isna(row.get('tail_num')) else 'N/A'
        leg_of_day = int(row.get('tail_leg_of_day', 1)) if not pd.isna(row.get('tail_leg_of_day')) else 'N/A'
        prev_arr_delay = int(row.get('prev_arr_delay', 0)) if not pd.isna(row.get('prev_arr_delay')) else 'N/A'
        sched_turn = int(row.get('sched_turn_min', 0)) if not pd.isna(row.get('sched_turn_min')) else 'N/A'

        # Dataset Split Analysis
        split_raw = str(row.get('split', 'train')).lower().strip()
        year = pd.to_datetime(row.get('flight_date')).year if row.get('flight_date') else 2023
        
        if year == 2024:
            if split_raw == 'train':
                split_info = {
                    'type': 'train',
                    'title': 'Training Dataset (2023 + Jan–Apr 2024)',
                    'badge_color': 'warning',
                    'badge_text': 'TRAIN 2024',
                    'alert_class': 'border-amber-600 bg-amber-950 text-amber-200',
                    'icon': 'bi-database-fill-check',
                    'period': 'Jan 1 – Apr 30, 2024',
                    'is_training': True,
                    'is_validation': False,
                    'is_test': False,
                    'message': 'This flight is part of the model training dataset (2023 + Jan–Apr 2024). Known ground truth outcomes.',
                    'ground_truth_label': 'Known Ground-Truth (Training Corpus)'
                }
            elif split_raw == 'validation':
                split_info = {
                    'type': 'validation',
                    'title': 'Validation Set (Threshold Tuning)',
                    'badge_color': 'info',
                    'badge_text': 'VALIDATION 2024',
                    'alert_class': 'border-sky-600 bg-sky-950 text-sky-200',
                    'icon': 'bi-sliders',
                    'period': 'May 1 – May 31, 2024',
                    'is_training': False,
                    'is_validation': True,
                    'is_test': False,
                    'message': 'This flight is part of the validation dataset (May 2024) used for decision threshold tuning (Arrival: 0.659, Departure: 0.526).',
                    'ground_truth_label': 'Known Ground-Truth (Threshold Tuning Flight)'
                }
            elif split_raw == 'test':
                split_info = {
                    'type': 'test',
                    'title': 'Held-Out Test Dataset (Dual-Model Inference)',
                    'badge_color': 'primary',
                    'badge_text': 'TEST 2024 (INFERENCE)',
                    'alert_class': 'border-purple-600 bg-purple-950 text-purple-200',
                    'icon': 'bi-crosshair',
                    'period': 'Jun 1 – Jul 31, 2024',
                    'is_training': False,
                    'is_validation': False,
                    'is_test': True,
                    'message': 'This flight belongs to the Held-Out Test dataset (Jun–Jul 2024). Out-of-sample machine learning inference benchmark.',
                    'ground_truth_label': 'Actual Ground-Truth Outcome (Test Benchmark)'
                }
            else:
                split_info = {
                    'type': 'unseen',
                    'title': 'Operational 2024 Traffic',
                    'badge_color': 'success',
                    'badge_text': '2024 OPERATIONS',
                    'alert_class': 'border-emerald-600 bg-emerald-950 text-emerald-200',
                    'icon': 'bi-airplane-engines-fill',
                    'period': 'Aug – Dec 2024',
                    'is_training': False,
                    'is_validation': False,
                    'is_test': True,
                    'message': 'Operational 2024 flight record. Active machine learning prediction evaluated.',
                    'ground_truth_label': 'Recorded Operational Answer'
                }
        else:
            if split_raw == 'train':
                split_info = {
                    'type': 'train',
                    'title': 'Arrival Training Set (In-Sample Flight)',
                    'badge_color': 'warning',
                    'badge_text': 'TRAIN 2023',
                    'alert_class': 'border-amber-600 bg-amber-950 text-amber-200',
                    'icon': 'bi-database-fill-check',
                    'period': 'Jan 1 – Sep 30, 2023',
                    'is_training': True,
                    'is_validation': False,
                    'is_test': False,
                    'message': 'This flight is part of the Arrival Delay model training dataset (Jan–Sep 2023). Known arrival delay outcome.',
                    'ground_truth_label': 'Known Ground-Truth Answer (Used in Model Training)'
                }
            elif split_raw == 'validation':
                split_info = {
                    'type': 'validation',
                    'title': 'Arrival Validation Set (Threshold Tuning)',
                    'badge_color': 'info',
                    'badge_text': 'VALIDATION 2023',
                    'alert_class': 'border-sky-600 bg-sky-950 text-sky-200',
                    'icon': 'bi-sliders',
                    'period': 'Oct 1 – Oct 31, 2023',
                    'is_training': False,
                    'is_validation': True,
                    'is_test': False,
                    'message': 'This flight is part of the Arrival Delay validation dataset (Oct 2023) used for decision threshold tuning (0.672).',
                    'ground_truth_label': 'Known Ground-Truth Answer (Used for Threshold Tuning)'
                }
            else:
                split_info = {
                    'type': 'test',
                    'title': 'Held-Out Test Dataset (Arrival Delay Inference)',
                    'badge_color': 'primary',
                    'badge_text': 'TEST 2023 (INFERENCE)',
                    'alert_class': 'border-purple-600 bg-purple-950 text-purple-200',
                    'icon': 'bi-crosshair',
                    'period': 'Nov 1 – Dec 31, 2023',
                    'is_training': False,
                    'is_validation': False,
                    'is_test': True,
                    'message': 'This flight belongs to the Arrival Delay Held-Out Test dataset (Nov–Dec 2023). Active ML prediction.',
                    'ground_truth_label': 'Actual Ground-Truth Outcome (Held-Out Benchmark)'
                }

        return {
            'airline_code': airline_code,
            'airline_name': airline_name,
            'flight_number': int(row.get('flight_number')),
            'flight_date': str(row.get('date_str')),
            'year': year,
            'split': split_raw,
            'split_info': split_info,
            'origin': origin_code,
            'origin_name': origin_info['name'],
            'origin_city': origin_info['city'],
            'dest': dest_code,
            'dest_name': dest_info['name'],
            'dest_city': dest_info['city'],
            'route': f"{origin_code} → {dest_code}",
            'sched_dep_time': sched_dep_fmt,
            'actual_dep_time': actual_dep_fmt,
            'sched_arr_time': sched_arr_fmt,
            'dep_delay_min': dep_delay_val,
            'dep_delay_str': dep_delay_str,
            'dep_status': dep_status,
            'dep_badge_color': dep_badge_color,
            'distance_mi': dist_mi,
            'distance_km': int(dist_mi * 1.60934) if dist_mi > 0 else 0,
            'duration_str': duration_str,
            'weather': {
                'temp_f': round(float(temp_f), 1) if temp_f is not None and not pd.isna(temp_f) else 'N/A',
                'wind_kt': round(float(wind_kt), 1) if wind_kt is not None and not pd.isna(wind_kt) else 'N/A',
                'sky_cover': str(sky_cover),
                'visibility_mi': round(float(visibility), 1) if visibility is not None and not pd.isna(visibility) else 'N/A',
                'conditions': ", ".join(weather_tags)
            },
            'aircraft_rotation': {
                'tail_num': tail_num,
                'leg_of_day': leg_of_day,
                'prev_arr_delay_min': prev_arr_delay,
                'sched_turn_min': sched_turn
            },
            'historical_ground_truth': {
                'has_data': has_actual_arr,
                'actual_arr_delay_min': actual_arr_delay,
                'actual_arr_status': actual_arr_status,
                'was_delayed_15': bool(actual_arr_delay >= 15) if has_actual_arr else None,
                'dep_delay_min': dep_delay_val,
                'was_dep_delayed_15': bool(dep_delay_val >= 15)
            }
        }

    def get_dashboard_stats(self):
        """Computes summary statistics across both 2023 and 2024 operations datasets."""
        if not self.is_loaded or self.df is None:
            return {
                'total_flights': 0,
                'delayed_flights': 0,
                'on_time_flights': 0,
                'delay_rate': 0.0,
                'on_time_rate': 100.0,
                'airlines_count': 13,
                'airports_count': 10,
                'total_2023': 0,
                'total_2024': 0,
                'date_min': '2023-01-01',
                'date_max': '2024-12-31',
                'hourly_delays': [],
                'hub_stats': []
            }

        total = len(self.df)
        delayed = int((self.df['dep_delay_min'] >= 15).sum()) if 'dep_delay_min' in self.df.columns else int(total * 0.18)
        on_time = total - delayed
        delay_rate = round((delayed / total) * 100, 1) if total > 0 else 0.0

        hour_dist = []
        if 'sched_dep_hour' in self.df.columns and 'dep_delay_min' in self.df.columns:
            h_grp = self.df.groupby('sched_dep_hour').apply(
                lambda g: pd.Series({
                    'count': len(g),
                    'delay_rate': round(((g['dep_delay_min'] >= 15).mean()) * 100, 1)
                }),
                include_groups=False
            ).reset_index()
            for _, r in h_grp.iterrows():
                try:
                    hr = int(r['sched_dep_hour'])
                    hour_dist.append({
                        'hour': f"{hr:02d}:00",
                        'flight_count': int(r['count']),
                        'delay_rate': float(r['delay_rate'])
                    })
                except Exception:
                    continue
            hour_dist.sort(key=lambda x: x['hour'])

        hub_stats = []
        if 'origin' in self.df.columns and 'dep_delay_min' in self.df.columns:
            o_grp = self.df.groupby('origin').apply(
                lambda g: pd.Series({
                    'count': len(g),
                    'delay_rate': round(((g['dep_delay_min'] >= 15).mean()) * 100, 1)
                }),
                include_groups=False
            ).reset_index()
            for _, r in o_grp.iterrows():
                hub_stats.append({
                    'airport': r['origin'],
                    'name': Config.AIRPORTS.get(r['origin'], {}).get('name', r['origin']),
                    'total_departures': int(r['count']),
                    'delay_rate': float(r['delay_rate'])
                })
            hub_stats.sort(key=lambda x: x['delay_rate'], reverse=True)

        return {
            'total_flights': total,
            'delayed_flights': delayed,
            'on_time_flights': on_time,
            'delay_rate': delay_rate,
            'on_time_rate': round(100.0 - delay_rate, 1),
            'total_2023': self.total_2023,
            'total_2024': self.total_2024,
            'airlines_count': self.df['airline'].nunique() if 'airline' in self.df.columns else 13,
            'airports_count': self.df['origin'].nunique() if 'origin' in self.df.columns else 10,
            'date_min': self.df['date_str'].min() if 'date_str' in self.df.columns else '2023-01-01',
            'date_max': self.df['date_str'].max() if 'date_str' in self.df.columns else '2024-12-31',
            'hourly_delays': hour_dist,
            'hub_stats': hub_stats
        }

    def get_sample_flights(self):
        """Returns sample flights across both Arrival Delay and Departure Delay models, covering extremes and borderline ranges."""
        return [
            {
                'split_tag': '2024 TEST (DEP)',
                'split_badge_color': 'primary',
                'target_type': 'departure',
                'date': '2024-06-11',
                'flight_number': 2269,
                'airline': 'UA',
                'origin': 'SEA',
                'description': '2024 Test Set (Departure): Low-risk early pushback (25.6% risk, -10m early pushback from SEA).'
            },
            {
                'split_tag': '2024 VAL (DEP)',
                'split_badge_color': 'info',
                'target_type': 'departure',
                'date': '2024-05-15',
                'flight_number': 1792,
                'airline': 'AA',
                'origin': 'LAS',
                'description': '2024 Validation Set (Departure): Borderline scenario in 0.4–0.7 range (47.6% risk, near 0.526 threshold).'
            },
            {
                'split_tag': '2024 TEST (DEP)',
                'split_badge_color': 'primary',
                'target_type': 'departure',
                'date': '2024-06-26',
                'flight_number': 5029,
                'airline': 'WN',
                'origin': 'MCO',
                'description': '2024 Test Set (Departure): High-risk taxiway queue & terminal congestion (75.5% risk, +146m delay at MCO).'
            },
            {
                'split_tag': '2024 TEST (ARR)',
                'split_badge_color': 'primary',
                'target_type': 'arrival',
                'date': '2024-06-15',
                'flight_number': 883,
                'airline': 'DL',
                'origin': 'DEN',
                'description': '2024 Test Set (Arrival): On-time arrival scenario (3.9% delay risk, arrived -8m early into ATL).'
            },
            {
                'split_tag': '2024 TEST (ARR)',
                'split_badge_color': 'primary',
                'target_type': 'arrival',
                'date': '2024-06-15',
                'flight_number': 2166,
                'airline': 'AA',
                'origin': 'LAS',
                'description': '2024 Test Set (Arrival): Delayed arrival scenario (99.8% risk, +37m arrival delay into DFW).'
            },
            {
                'split_tag': '2023 TRAIN (ARR)',
                'split_badge_color': 'warning',
                'target_type': 'arrival',
                'date': '2023-01-01',
                'flight_number': 26,
                'airline': 'WN',
                'origin': 'LAX',
                'description': '2023 Training Set (Arrival): Known ground-truth on-time flight (8.1% risk, Jan 2023 training corpus).'
            }
        ]


flight_service = FlightService()

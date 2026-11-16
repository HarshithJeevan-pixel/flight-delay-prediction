import unittest
import json
import sys
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app import app
from config import Config
from services.prediction_service import prediction_service
from services.feature_service import feature_service
from services.flight_service import flight_service


class TestFlightDelayApp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config['TESTING'] = True
        cls.client = app.test_client()

    def test_01_models_loaded(self):
        """Verify that ML models and thresholds loaded successfully from joblib for both Arrival and Departure."""
        self.assertTrue(prediction_service.is_loaded, "Prediction service failed to load models")
        arr_models = prediction_service.get_available_models('arrival')
        self.assertIn('Gradient boosting', arr_models)
        self.assertIn('Logistic regression', arr_models)
        self.assertGreater(prediction_service.get_threshold('Gradient boosting', 'arrival'), 0.5)

        dep_models = prediction_service.get_available_models('departure')
        self.assertIn('Gradient boosting', dep_models)
        self.assertIn('Logistic regression', dep_models)
        self.assertGreater(prediction_service.get_threshold('Gradient boosting', 'departure'), 0.5)

    def test_02_dataset_loaded(self):
        """Verify that historical operations dataset and search index are ready."""
        self.assertTrue(flight_service.is_loaded, "Flight dataset failed to load")
        self.assertGreater(len(flight_service.df), 100000)

    def test_03_pages_load_successfully(self):
        """Test GET requests on all website views."""
        # 1. Root page
        r_root = self.client.get('/')
        self.assertIn(r_root.status_code, [200, 302])

        # 2. Dashboard
        r_dash = self.client.get('/dashboard')
        self.assertEqual(r_dash.status_code, 200)
        self.assertIn(b'Operations', r_dash.data)

        # 3. Prediction page
        r_pred = self.client.get('/predict')
        self.assertEqual(r_pred.status_code, 200)
        self.assertIn(b'Flight Delay Prediction', r_pred.data)

        # 4. Performance page
        r_perf = self.client.get('/performance')
        self.assertEqual(r_perf.status_code, 200)
        self.assertIn(b'Model Performance', r_perf.data)

        # 5. About page
        r_about = self.client.get('/about')
        self.assertEqual(r_about.status_code, 200)
        self.assertIn(b'AeroDelay Ops', r_about.data)

    def test_04_flight_search_exact_match(self):
        """Test flight search API returning an exact flight match."""
        # AA 1562 on 2023-01-01 (F9 carrier)
        payload = {
            'date': '2023-01-01',
            'flight_number': 1562,
            'airline': 'F9',
            'origin': 'PHX'
        }
        res = self.client.post('/api/search-flight',
                               data=json.dumps(payload),
                               content_type='application/json')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['status'], 'exact_match')
        self.assertEqual(data['flight']['flight_number'], 1562)
        self.assertEqual(data['flight']['origin'], 'PHX')
        self.assertEqual(data['flight']['dest'], 'ATL')

    def test_05_flight_search_multiple_matches(self):
        """Test flight search API handling multiple flights with same number on same date."""
        # Flight 26 on 2023-01-01 has 3 legs (WN and AS)
        payload = {
            'date': '2023-01-01',
            'flight_number': 26
        }
        res = self.client.post('/api/search-flight',
                               data=json.dumps(payload),
                               content_type='application/json')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['status'], 'multiple_matches')
        self.assertGreaterEqual(data['count'], 2)

    def test_06_flight_search_invalid_inputs(self):
        """Test search error handling for invalid dates and flight numbers."""
        # Invalid date format
        res1 = self.client.post('/api/search-flight',
                                data=json.dumps({'date': 'not-a-date', 'flight_number': 1562}),
                                content_type='application/json')
        self.assertEqual(res1.status_code, 400)

        # Non-numeric flight number
        res2 = self.client.post('/api/search-flight',
                                data=json.dumps({'date': '2023-01-01', 'flight_number': 'not_a_number'}),
                                content_type='application/json')
        self.assertEqual(res2.status_code, 200)
        self.assertEqual(res2.get_json()['status'], 'invalid_input')

        # Flight not in database
        res3 = self.client.post('/api/search-flight',
                                data=json.dumps({'date': '2023-01-01', 'flight_number': 99999}),
                                content_type='application/json')
        self.assertEqual(res3.status_code, 200)
        self.assertEqual(res3.get_json()['status'], 'not_found')

    def test_07_feature_service_leakage_guard(self):
        """Verify that target arrival delay is never leaked into model features."""
        dummy_row = {
            'airline': 'AA',
            'origin': 'ORD',
            'dest': 'DFW',
            'dep_delay_min': 25,
            'arr_delay_min': 35,  # Target!
            'arr_del15': 1         # Target!
        }
        feat_df = feature_service.prepare_features_from_dict(dummy_row)
        self.assertEqual(len(feat_df.columns), len(Config.MODEL_FEATURES))
        self.assertNotIn('arr_delay_min', feat_df.columns)
        self.assertNotIn('arr_del15', feat_df.columns)
        self.assertIn('dep_delay_clip', feat_df.columns)
        self.assertEqual(feat_df['dep_late_15'].iloc[0], 1)

    def test_08_prediction_api(self):
        """Test prediction API with Gradient Boosting for both Arrival and Departure models."""
        # 1. Arrival Delay Prediction
        sample_flight_arr = {
            'airline_code': 'AA',
            'airline': 'AA',
            'origin': 'ORD',
            'dest': 'DFW',
            'sched_dep_hour': '14',
            'day_of_week': '3',
            'wx_sky_cover': 'CLR',
            'distance_mi': 800,
            'crs_elapsed_min': 140,
            'dep_delay_min': 35,
            'flight_number': 100,
            'flight_date': '2023-01-01'
        }
        res_arr = self.client.post('/api/predict',
                                   data=json.dumps({'flight_data': sample_flight_arr, 'model_name': 'Gradient boosting', 'target_type': 'arrival'}),
                                   content_type='application/json')
        self.assertEqual(res_arr.status_code, 200)
        data_arr = res_arr.get_json()
        self.assertEqual(data_arr['status'], 'success')
        pred_arr = data_arr['prediction_result']
        self.assertIn('probability', pred_arr)
        self.assertIn('prediction', pred_arr)
        self.assertIn('threshold', pred_arr)
        self.assertEqual(pred_arr['target_type'], 'arrival')
        self.assertIn(pred_arr['prediction'], ['DELAY LIKELY', 'ON TIME LIKELY'])

        # 2. Departure Delay Prediction
        sample_flight_dep = {
            'airline_code': 'DL',
            'airline': 'DL',
            'origin': 'DEN',
            'dest': 'ATL',
            'sched_dep_hour': '10',
            'day_of_week': '5',
            'distance_mi': 1200,
            'crs_elapsed_min': 180,
            'flight_number': 883,
            'flight_date': '2024-06-15'
        }
        res_dep = self.client.post('/api/predict',
                                   data=json.dumps({'flight_data': sample_flight_dep, 'model_name': 'Gradient boosting', 'target_type': 'departure'}),
                                   content_type='application/json')
        self.assertEqual(res_dep.status_code, 200)
        data_dep = res_dep.get_json()
        self.assertEqual(data_dep['status'], 'success')
        pred_dep = data_dep['prediction_result']
        self.assertIn('probability', pred_dep)
        self.assertIn('prediction', pred_dep)
        self.assertIn('threshold', pred_dep)
        self.assertEqual(pred_dep['target_type'], 'departure')
        self.assertIn(pred_dep['prediction'], ['DELAY LIKELY', 'ON TIME LIKELY'])

    def test_09_model_performance_api(self):
        """Test API returning benchmark metrics from JSON file for arrival, departure, and combined."""
        # 1. Combined
        res_comb = self.client.get('/api/model-performance')
        self.assertEqual(res_comb.status_code, 200)
        data_comb = res_comb.get_json()
        self.assertIn('arrival', data_comb)
        self.assertIn('departure', data_comb)

        # 2. Arrival benchmark query
        res_arr = self.client.get('/api/model-performance?target=arrival')
        self.assertEqual(res_arr.status_code, 200)
        data_arr = res_arr.get_json()
        self.assertIn('models', data_arr)
        self.assertIn('Gradient boosting', data_arr['models'])
        self.assertIn('Logistic regression', data_arr['models'])
        self.assertIn('feature_importance', data_arr)

        # 3. Departure benchmark query
        res_dep = self.client.get('/api/model-performance?target=departure')
        self.assertEqual(res_dep.status_code, 200)
        data_dep = res_dep.get_json()
        self.assertIn('models', data_dep)
        self.assertIn('Gradient boosting', data_dep['models'])
        self.assertIn('Logistic regression', data_dep['models'])
        self.assertIn('feature_importance', data_dep)

    def test_10_dashboard_stats_api(self):
        """Test dashboard statistics API."""
        res = self.client.get('/api/dashboard-stats')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn('total_flights', data)
        self.assertGreater(data['total_flights'], 100000)
        self.assertIn('delayed_flights', data)
        self.assertIn('hourly_delays', data)


if __name__ == '__main__':
    unittest.main()

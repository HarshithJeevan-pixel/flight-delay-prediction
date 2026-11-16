import json
import logging
import datetime
from pathlib import Path
from flask import Flask, render_template, request, jsonify, redirect, url_for, session

from config import Config
from services.flight_service import flight_service
from services.feature_service import feature_service
from services.prediction_service import prediction_service

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config.from_object(Config)
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.jinja_env.auto_reload = True

# In-memory session history for recent predictions in the current application session
SESSION_PREDICTION_HISTORY = []
MAX_HISTORY_ITEMS = 25


def add_to_prediction_history(flight_info, prediction_result):
    """Stores recent prediction in memory for dashboard display."""
    item = {
        'id': len(SESSION_PREDICTION_HISTORY) + 1,
        'timestamp': datetime.datetime.now().strftime('%H:%M:%S'),
        'flight_number': flight_info.get('flight_number'),
        'airline': flight_info.get('airline_code'),
        'airline_name': flight_info.get('airline_name'),
        'route': flight_info.get('route'),
        'dep_delay_min': flight_info.get('dep_delay_min'),
        'target_type': prediction_result.get('target_type', 'arrival'),
        'target_label': prediction_result.get('target_label', 'Arrival Delay'),
        'prediction': prediction_result.get('prediction'),
        'is_delayed': prediction_result.get('is_delayed'),
        'probability_percent': prediction_result.get('probability_percent'),
        'model_name': prediction_result.get('model_name'),
        'risk_level': prediction_result.get('risk_level'),
        'risk_color': prediction_result.get('risk_color')
    }
    SESSION_PREDICTION_HISTORY.insert(0, item)
    if len(SESSION_PREDICTION_HISTORY) > MAX_HISTORY_ITEMS:
        SESSION_PREDICTION_HISTORY.pop()


# --- HTML Page Routes ---

@app.route('/')
def index():
    """Portal landing page."""
    return render_template('index.html')


@app.route('/dashboard')
def dashboard():
    """Main operations dashboard."""
    stats = flight_service.get_dashboard_stats()
    
    # Load both arrival and departure evaluation benchmarks
    arrival_perf = {}
    if Config.ARRIVAL_RESULTS_PATH.exists():
        try:
            with open(Config.ARRIVAL_RESULTS_PATH, 'r') as f:
                arrival_perf = json.load(f)
        except Exception as e:
            logger.warning("Could not load arrival performance json: %s", e)

    departure_perf = {}
    if Config.DEPARTURE_RESULTS_PATH.exists():
        try:
            with open(Config.DEPARTURE_RESULTS_PATH, 'r') as f:
                departure_perf = json.load(f)
        except Exception as e:
            logger.warning("Could not load departure performance json: %s", e)

    return render_template(
        'dashboard.html',
        stats=stats,
        model_perf=arrival_perf,
        arrival_perf=arrival_perf,
        departure_perf=departure_perf,
        recent_history=SESSION_PREDICTION_HISTORY[:8],
        page_title="Operations Dashboard",
        active_page="dashboard"
    )


@app.route('/predict')
def predict_page():
    """Flight search and delay prediction page for both Arrival and Departure delays."""
    sample_flights = flight_service.get_sample_flights()
    available_arrival = prediction_service.get_available_models('arrival')
    available_departure = prediction_service.get_available_models('departure')
    
    return render_template(
        'prediction.html',
        sample_flights=sample_flights,
        available_models=available_arrival,
        available_arrival=available_arrival,
        available_departure=available_departure,
        default_model=Config.DEFAULT_MODEL,
        airlines=Config.AIRLINES,
        airports=Config.AIRPORTS,
        page_title="Flight Delay Prediction",
        active_page="predict"
    )


@app.route('/performance')
def performance():
    """Model Performance & Evaluation page supporting both Arrival Delay and Departure Delay."""
    arrival_perf = {}
    if Config.ARRIVAL_RESULTS_PATH.exists():
        try:
            with open(Config.ARRIVAL_RESULTS_PATH, 'r') as f:
                arrival_perf = json.load(f)
        except Exception as e:
            logger.error("Error reading arrival performance JSON: %s", e)

    departure_perf = {}
    if Config.DEPARTURE_RESULTS_PATH.exists():
        try:
            with open(Config.DEPARTURE_RESULTS_PATH, 'r') as f:
                departure_perf = json.load(f)
        except Exception as e:
            logger.error("Error reading departure performance JSON: %s", e)

    return render_template(
        'performance.html',
        perf=arrival_perf,
        arrival_perf=arrival_perf,
        departure_perf=departure_perf,
        page_title="Model Performance & Evaluation",
        active_page="performance"
    )


@app.route('/about')
def about():
    """About & Documentation page."""
    return render_template(
        'about.html',
        page_title="About AeroDelay Ops",
        active_page="about"
    )


# --- REST API Endpoints ---

@app.route('/api/search-flight', methods=['POST'])
def api_search_flight():
    """
    Searches for a flight in the operational database across 2023 and 2024.
    Expects JSON: { date: 'YYYY-MM-DD', flight_number: 1562, airline?: 'AA', origin?: 'PHX' }
    """
    data = request.get_json() or {}
    date_str = data.get('date')
    fl_num_raw = data.get('flight_number')
    airline = data.get('airline')
    origin = data.get('origin')

    if not date_str:
        return jsonify({'status': 'error', 'message': 'Flight date is required. Please select a date.'}), 400

    if not fl_num_raw:
        return jsonify({'status': 'error', 'message': 'Flight number is required. Please enter an integer.'}), 400

    parsed_date = None
    cleaned_date_str = str(date_str).strip()
    for fmt in ('%Y-%m-%d', '%d-%m-%Y', '%m-%d-%Y', '%Y/%m/%d', '%d/%m/%Y'):
        try:
            parsed_date = datetime.datetime.strptime(cleaned_date_str, fmt)
            break
        except ValueError:
            pass

    if parsed_date is None:
        return jsonify({'status': 'error', 'message': 'Invalid date format. Expected YYYY-MM-DD (e.g. 2023-01-01 or 2024-06-15).'}), 400

    date_str = parsed_date.strftime('%Y-%m-%d')
    result = flight_service.search_flight(date_str, fl_num_raw, airline, origin)
    return jsonify(result)


@app.route('/api/predict', methods=['POST'])
def api_predict():
    """
    Executes delay prediction using either Arrival Delay or Departure Delay ML models.
    Expects JSON: { flight_data: dict, model_name?: str, target_type?: 'arrival' | 'departure' }
    """
    data = request.get_json() or {}
    flight_data = data.get('flight_data')
    model_name = data.get('model_name', Config.DEFAULT_MODEL)
    target_type = str(data.get('target_type', 'arrival')).lower().strip()

    if not flight_data or not isinstance(flight_data, dict):
        return jsonify({'status': 'error', 'message': 'Missing flight data for prediction.'}), 400

    try:
        # Prepare exact features for selected target model without leakage
        features_df = feature_service.prepare_features_from_dict(flight_data, target_type=target_type)

        # Run prediction via trained pipeline
        pred_result = prediction_service.predict(features_df, model_name=model_name, target_type=target_type)

        # Add to session history
        add_to_prediction_history(flight_data, pred_result)

        return jsonify({
            'status': 'success',
            'prediction_result': pred_result,
            'flight_summary': {
                'flight_number': flight_data.get('flight_number'),
                'airline_code': flight_data.get('airline_code'),
                'airline_name': flight_data.get('airline_name'),
                'route': flight_data.get('route'),
                'flight_date': flight_data.get('flight_date'),
                'dep_delay_min': flight_data.get('dep_delay_min'),
                'sched_dep_time': flight_data.get('sched_dep_time'),
                'actual_dep_time': flight_data.get('actual_dep_time')
            }
        })
    except Exception as e:
        logger.error("Prediction error: %s", e, exc_info=True)
        return jsonify({
            'status': 'error',
            'message': f"An error occurred while generating prediction: {str(e)}"
        }), 500


@app.route('/api/predict-custom', methods=['POST'])
def api_predict_custom():
    """
    Simulates custom flight conditions for either Arrival or Departure delay.
    Expects JSON: { ...flight fields..., model_name?: str, target_type?: 'arrival' | 'departure' }
    """
    data = request.get_json() or {}
    target_type = str(data.get('target_type', 'arrival')).lower().strip()
    model_name = data.get('model_name', Config.DEFAULT_MODEL)

    try:
        features_df = feature_service.prepare_features_from_dict(data, target_type=target_type)
        pred_result = prediction_service.predict(features_df, model_name=model_name, target_type=target_type)
        return jsonify({
            'status': 'success',
            'prediction_result': pred_result
        })
    except Exception as e:
        logger.error("Custom prediction error: %s", e, exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/dashboard-stats', methods=['GET'])
def api_dashboard_stats():
    """Returns dataset summary statistics and recent prediction history."""
    stats = flight_service.get_dashboard_stats()
    stats['recent_predictions'] = SESSION_PREDICTION_HISTORY
    return jsonify(stats)


@app.route('/api/model-performance', methods=['GET'])
def api_model_performance():
    """
    Returns model performance metrics for Arrival and/or Departure models.
    Supports query parameter: ?target=arrival | departure | all
    """
    target = request.args.get('target', 'all').lower()

    arrival_perf = {}
    if Config.ARRIVAL_RESULTS_PATH.exists():
        try:
            with open(Config.ARRIVAL_RESULTS_PATH, 'r') as f:
                arrival_perf = json.load(f)
        except Exception as e:
            logger.error("Error reading arrival performance: %s", e)

    departure_perf = {}
    if Config.DEPARTURE_RESULTS_PATH.exists():
        try:
            with open(Config.DEPARTURE_RESULTS_PATH, 'r') as f:
                departure_perf = json.load(f)
        except Exception as e:
            logger.error("Error reading departure performance: %s", e)

    if target == 'arrival':
        return jsonify(arrival_perf)
    elif target == 'departure':
        return jsonify(departure_perf)
    else:
        return jsonify({
            'arrival': arrival_perf,
            'departure': departure_perf
        })


@app.route('/api/sample-flights', methods=['GET'])
def api_sample_flights():
    """Returns preset sample flights across both arrival and departure models."""
    return jsonify(flight_service.get_sample_flights())


@app.route('/api/airlines', methods=['GET'])
def api_airlines():
    """Returns carrier airline details."""
    return jsonify(Config.AIRLINES)


@app.route('/api/airports', methods=['GET'])
def api_airports():
    """Returns airport hub details."""
    return jsonify(Config.AIRPORTS)


@app.after_request
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type,Authorization'
    response.headers['Access-Control-Allow-Methods'] = 'GET,POST,OPTIONS'
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


# Error Handlers
@app.errorhandler(404)
def not_found_error(error):
    return render_template('base.html', page_title="Page Not Found", error_message="404 - Requested page was not found."), 404

@app.errorhandler(500)
def internal_error(error):
    return render_template('base.html', page_title="System Error", error_message="500 - An internal server error occurred."), 500


if __name__ == '__main__':
    logger.info("Starting AeroDelay Ops Flight Prediction Server...")
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=Config.DEBUG)

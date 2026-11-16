import sys
import logging
import datetime
from pathlib import Path
import numpy as np
import pandas as pd

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Compatibility Shims for Scikit-Learn Serialization ---
try:
    import sklearn.compose._column_transformer
    if not hasattr(sklearn.compose._column_transformer, '_RemainderColsList'):
        class _RemainderColsList(list):
            pass
        sklearn.compose._column_transformer._RemainderColsList = _RemainderColsList
except Exception as e:
    logger.warning("Could not patch _RemainderColsList: %s", e)

try:
    import sklearn._loss
    if hasattr(sklearn._loss, '_loss'):
        sys.modules['_loss'] = sklearn._loss._loss
    else:
        sys.modules['_loss'] = sklearn._loss
except Exception as e:
    logger.warning("Could not patch _loss module: %s", e)

try:
    from sklearn.impute import SimpleImputer
    _orig_simple_imputer_transform = SimpleImputer.transform
    def _patched_simple_imputer_transform(self, X, **kwargs):
        if not hasattr(self, '_fill_dtype'):
            self._fill_dtype = getattr(self, '_fit_dtype', np.float64)
        return _orig_simple_imputer_transform(self, X, **kwargs)
    SimpleImputer.transform = _patched_simple_imputer_transform
except Exception as e:
    logger.warning("Could not patch SimpleImputer: %s", e)

import joblib
from config import Config


class PredictionService:
    """
    Service responsible for loading both the Arrival Delay and Departure Delay
    trained ML models and generating predictions using the respective pipelines and thresholds.
    """
    def __init__(self):
        self.arrival_model_path = Config.ARRIVAL_MODEL_PATH
        self.departure_model_path = Config.DEPARTURE_MODEL_PATH
        
        # Arrival models & state
        self.arrival_models = {}
        self.arrival_thresholds = dict(Config.ARRIVAL_THRESHOLDS)
        self.arrival_features = list(Config.ARRIVAL_MODEL_FEATURES)
        self.is_arrival_loaded = False
        
        # Departure models & state
        self.departure_models = {}
        self.departure_thresholds = dict(Config.DEPARTURE_THRESHOLDS)
        self.departure_features = list(Config.DEPARTURE_MODEL_FEATURES)
        self.is_departure_loaded = False
        
        # Legacy aliases
        self.models = self.arrival_models
        self.thresholds = self.arrival_thresholds
        self.features = self.arrival_features
        self.is_loaded = False
        
        self.load_all_models()

    def load_all_models(self):
        """Loads both arrival and departure model packages."""
        self.load_arrival_models()
        self.load_departure_models()
        self.is_loaded = self.is_arrival_loaded or self.is_departure_loaded
        self.models = self.arrival_models
        self.thresholds = self.arrival_thresholds
        self.features = self.arrival_features
        return self.is_loaded

    def load_arrival_models(self):
        """Loads Arrival Delay models from arrival_models.joblib."""
        try:
            if not self.arrival_model_path.exists():
                logger.error("Arrival model file not found at: %s", self.arrival_model_path)
                return False

            data = joblib.load(self.arrival_model_path)
            if isinstance(data, dict):
                if 'features' in data:
                    self.arrival_features = data['features']
                if 'thresholds' in data:
                    self.arrival_thresholds.update(data['thresholds'])

                for m_name in ['Gradient boosting', 'Logistic regression']:
                    if m_name in data:
                        self.arrival_models[m_name] = data[m_name]
                        logger.info("Loaded Arrival Model: %s", m_name)

                self.is_arrival_loaded = len(self.arrival_models) > 0
                return self.is_arrival_loaded
        except Exception as e:
            logger.error("Error loading arrival models: %s", e, exc_info=True)
            self.is_arrival_loaded = False
            return False

    def load_departure_models(self):
        """Loads Departure Delay models from departure_models.joblib."""
        try:
            if not self.departure_model_path.exists():
                logger.error("Departure model file not found at: %s", self.departure_model_path)
                return False

            data = joblib.load(self.departure_model_path)
            if isinstance(data, dict):
                if 'features' in data:
                    self.departure_features = data['features']
                if 'thresholds' in data:
                    self.departure_thresholds.update(data['thresholds'])

                for m_name in ['Gradient boosting', 'Logistic regression']:
                    if m_name in data:
                        self.departure_models[m_name] = data[m_name]
                        logger.info("Loaded Departure Model: %s", m_name)

                self.is_departure_loaded = len(self.departure_models) > 0
                return self.is_departure_loaded
        except Exception as e:
            logger.error("Error loading departure models: %s", e, exc_info=True)
            self.is_departure_loaded = False
            return False

    def get_available_models(self, target_type='arrival'):
        """Returns list of loaded model names for the selected target type."""
        models_dict = self.departure_models if target_type == 'departure' else self.arrival_models
        return list(models_dict.keys())

    def get_threshold(self, model_name, target_type='arrival'):
        """Returns the decision threshold for the selected model and target type."""
        if target_type == 'departure':
            return self.departure_thresholds.get(model_name, self.departure_thresholds.get('Gradient boosting', 0.526))
        else:
            return self.arrival_thresholds.get(model_name, self.arrival_thresholds.get('Gradient boosting', 0.672))

    def predict(self, feature_df, model_name=None, target_type='arrival'):
        """
        Executes prediction for either arrival delay (>=15m) or departure delay (>=15m).
        """
        target_type = target_type.lower() if target_type else 'arrival'
        is_departure = target_type == 'departure'
        
        models_dict = self.departure_models if is_departure else self.arrival_models
        features_list = self.departure_features if is_departure else self.arrival_features
        is_loaded = self.is_departure_loaded if is_departure else self.is_arrival_loaded

        if not is_loaded or not models_dict:
            raise RuntimeError(f"ML Models for {target_type} delay are not loaded.")

        if model_name not in models_dict:
            model_name = 'Gradient boosting' if 'Gradient boosting' in models_dict else list(models_dict.keys())[0]

        model = models_dict[model_name]
        threshold = self.get_threshold(model_name, target_type=target_type)

        # Order DataFrame features exactly as trained
        ordered_df = feature_df[features_list].copy()

        # Class probabilities: [P(on_time <15m), P(delayed >=15m)]
        proba = model.predict_proba(ordered_df)[0]
        prob_on_time = float(proba[0])
        prob_delayed = float(proba[1])

        # Classification decision based on threshold
        is_delayed = prob_delayed >= threshold
        status = "DELAY LIKELY" if is_delayed else "ON TIME LIKELY"

        # Tailor recommendation based on prediction type
        if is_departure:
            target_label = "Departure Delay (≥15m)"
            if prob_delayed >= 0.70:
                risk_level = "High"
                risk_color = "danger"
                recommendation = "High probability of takeoff delay ≥15m. Coordinate with gate agents, pushback tugs, and review taxiway queues."
            elif prob_delayed >= threshold:
                risk_level = "Moderate"
                risk_color = "warning"
                recommendation = "Pre-departure indicators exceed delay threshold. Anticipate possible departure queue or ATC holding."
            elif prob_delayed >= 0.30:
                risk_level = "Low-Moderate"
                risk_color = "info"
                recommendation = "Normal departure flow expected with minor congestion potential."
            else:
                risk_level = "Low"
                risk_color = "success"
                recommendation = "On-time departure likely. Clear origin weather and standard airport operations load."
            timing_notice = "Pre-departure prediction based on airport congestion, METAR weather, schedule, and historical route rates."
        else:
            target_label = "Arrival Delay (≥15m)"
            if prob_delayed >= 0.80:
                risk_level = "High"
                risk_color = "danger"
                recommendation = "High probability of 15+ min delay. Alert ground operations, prepare potential gate buffer, and monitor turnaround."
            elif prob_delayed >= threshold:
                risk_level = "Moderate"
                risk_color = "warning"
                recommendation = "Flight exceeds delay threshold. Potential arrival delay expected. Plan baggage transfer and gate readiness."
            elif prob_delayed >= 0.35:
                risk_level = "Low-Moderate"
                risk_color = "info"
                recommendation = "Flight likely to make up en-route schedule or arrive within standard on-time window (<15m)."
            else:
                risk_level = "Low"
                risk_color = "success"
                recommendation = "Flight on schedule. High confidence of punctual arrival at destination."
            timing_notice = "Prediction evaluated with confirmed departure delay, origin surface weather, and aircraft tail rotation."

        return {
            'prediction': status,
            'is_delayed': is_delayed,
            'target_type': target_type,
            'target_label': target_label,
            'probability': round(prob_delayed, 4),
            'probability_percent': round(prob_delayed * 100, 1),
            'prob_on_time_percent': round(prob_on_time * 100, 1),
            'threshold': round(threshold, 4),
            'threshold_percent': round(threshold * 100, 1),
            'model_name': model_name,
            'risk_level': risk_level,
            'risk_color': risk_color,
            'recommendation': recommendation,
            'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC'),
            'timing_notice': timing_notice
        }


# Global singleton instance
prediction_service = PredictionService()

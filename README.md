# AeroDelay Ops — Commercial Flight Delay Intelligence System

> **A dual-stage, empirical machine learning operations platform predicting 15+ minute arrival delays (post-departure) and departure delays (pre-departure) across 952k commercial flights at the 10 busiest U.S. hubs.**

---

### Project Links
- **Live Website URL (GitHub Pages):** [https://harshithjeevan-pixel.github.io/flight-delay-prediction/](https://harshithjeevan-pixel.github.io/flight-delay-prediction/)
- **GitHub Source-Repository URL:** [https://github.com/HarshithJeevan-pixel/flight-delay-prediction](https://github.com/HarshithJeevan-pixel/flight-delay-prediction)

---

## 1. Project Overview & Core Research Questions

AeroDelay Ops addresses commercial aviation delays by formulating two distinct operational prediction horizons to eliminate target leakage and deliver actionable intelligence to airline dispatchers, ground coordinators, and station managers:

### Question 1: Pre-Departure Delay Classification (Stage 1)
- **Operational Query:** *"At T-2 hours before scheduled pushback, will the flight depart with a delay >= 15 minutes?"*
- **Decision Window:** 2 hours prior to scheduled departure (`CRS_DEP_TIME`). Zero access to actual pushback, taxi, or airborne telemetry.
- **Actionable Lever:** Departure taxiway queue metering, ramp buffer staging, pushback tug assignment, and gate holding.
- **Champion Model:** `HistGradientBoostingClassifier` (**PR-AUC: 0.566**, ROC-AUC: 0.731, F1: 0.563 on held-out Jun–Jul 2024 test set).

### Question 2: Post-Departure Arrival Delay Classification (Stage 2)
- **Operational Query:** *"Once the flight has departed with its confirmed pushback delay, will it arrive at its destination gate >= 15 minutes late?"*
- **Decision Window:** Post-pushback / en-route. Incorporates confirmed departure delay (`DEP_DELAY`), elapsed air time, origin METAR surface weather, and inbound aircraft rotation.
- **Actionable Lever:** Destination gate conflict re-allocation, baggage transfer staging, and proactive passenger misconnection rebooking.
- **Champion Model:** `HistGradientBoostingClassifier` (**PR-AUC: 0.918**, ROC-AUC: 0.936, F1: 0.836 on held-out Jun–Jul 2024 test set).

### What Exactly Does One Row of Our Data Represent?
Each row represents **exactly one scheduled commercial passenger flight leg** operated by a reporting U.S. carrier between two primary U.S. hub airports on a specific calendar date, uniquely indexed by `(FL_DATE, OP_CARRIER, OP_CARRIER_FL_NUM, ORIGIN, DEST, CRS_DEP_TIME)`, merged with:
1. Origin airport NOAA ASOS/METAR surface weather observations valid at T-2h;
2. Incoming aircraft rotational chain (`tail_leg_of_day`, `prev_arr_delay`, `sched_turn_min`);
3. Closed trailing 30-day carrier/route reliability metrics; and
4. Rolling airport congestion load indices (1h, 3h, 6h late rates).

---

## 2. Repository Structure & Notebook Reproduction Mapping

```
flight-delay-prediction/
│
├── app.py                                   # Flask web server, route controllers & REST API endpoints
├── config.py                                # Central path configs, thresholds, airports & airlines metadata
├── requirements.txt                         # Exact Python dependencies
├── README.md                                # Comprehensive documentation & rubric verification
├── train_arrival_2024.py                    # Standalone reproduction script for Arrival delay modeling
│
├── notebooks/                               # Reproduction Jupyter & Colab Notebooks
│   ├── arrival_delay_colab.ipynb            # Interactive Google Colab notebook for Arrival delay modeling
│   ├── train_2023_to_apr2024_test_may_jul2024.ipynb # Complete Departure delay reproduction notebook
│   └── experiments/                         # Full experimental results & ablation CSV exports
│       ├── ablation.csv                     # Feature ablation experiment results
│       ├── scores_test.csv                  # Test set model comparison scores
│       ├── scores_validation.csv            # Validation set threshold tuning scores
│       └── scores_by_test_month.csv         # Monthly temporal stability (June vs July 2024)
│
├── model/
│   ├── arrival_models.joblib                # Scikit-Learn pipelines & validation thresholds (Arrival)
│   ├── arrival_results_for_website.json     # Held-out test metrics, curves & threshold arrays (Arrival)
│   └── departure_results_for_website.json   # Held-out test metrics & curves (Departure)
│
├── data/
│   ├── bts_2023_arrival_clean.parquet       # Cleaned 2023 flight operations (474k records)
│   └── flights_weather_2024_10airports.parquet # Cleaned 2024 flight operations (478k records)
│
├── services/
│   ├── flight_service.py                    # High-speed indexed search & dataset analytics
│   ├── feature_service.py                   # Prepares exact feature vectors with strict leakage prevention
│   └── prediction_service.py                # Model loading, inference & threshold classification
│
├── templates/                               # Jinja2 HTML Templates
│   ├── base.html                            # Master layout with navigation, status pills & footer
│   ├── index.html                           # Landing portal & executive project reasoning summary
│   ├── performance.html                     # Model benchmarks, PR curves, threshold & ablation simulators
│   ├── prediction.html                      # Interactive flight search & counterfactual delay inference
│   ├── about.html                           # Full scientific reasoning report & methodology
│   └── dashboard.html                       # Operations overview & session history
│
├── static/
│   ├── css/style.css                        # Warm ivory / editorial minimalist design system
│   └── js/script.js                         # Interactive simulators, async search & Chart.js drivers
│
├── tests/
│   └── test_app.py                          # Automated unit testing suite (10/10 passing)
│
└── docs/                                    # GitHub Pages production deployment root
```

---

## 3. Data Sources & Access Instructions

### 1. U.S. Bureau of Transportation Statistics (BTS)
- **Table:** *Reporting Carrier On-Time Performance (1987–present)*
- **URL:** [https://www.transtats.bts.gov/DL_SelectFields.aspx?gnoyr_VQ=FGJ](https://www.transtats.bts.gov/DL_SelectFields.aspx?gnoyr_VQ=FGJ)
- **Temporal Range:** January 1, 2023 through July 31, 2024.
- **Fields Extracted:** `FL_DATE`, `OP_CARRIER`, `OP_CARRIER_FL_NUM`, `ORIGIN`, `DEST`, `CRS_DEP_TIME`, `DEP_TIME`, `DEP_DELAY`, `CRS_ARR_TIME`, `ARR_TIME`, `ARR_DELAY`, `CANCELLED`, `DIVERTED`, `DISTANCE`, `CRS_ELAPSED_TIME`, `TAIL_NUM`.

### 2. NOAA ASOS / METAR Weather Stations
- **Archive:** Iowa Environmental Mesonet (IEM) ASOS download portal.
- **URL:** [https://mesonet.agron.iastate.edu/request/download.phtml](https://mesonet.agron.iastate.edu/request/download.phtml)
- **Airports Covered (Top 10 Mega-Hubs):**
  - **ATL** (Atlanta Hartsfield-Jackson)
  - **CLT** (Charlotte Douglas)
  - **DEN** (Denver International)
  - **DFW** (Dallas/Fort Worth International)
  - **LAS** (Las Vegas Harry Reid)
  - **LAX** (Los Angeles International)
  - **MCO** (Orlando International)
  - **ORD** (Chicago O'Hare)
  - **PHX** (Phoenix Sky Harbor)
  - **SEA** (Seattle-Tacoma International)
- **Weather Fields:** `tmpf` (temperature), `dwpf` (dew point), `sknt` (wind speed), `gust` (wind gusts), `vsby` (visibility), `p01i` (precipitation), `skyc1` (sky cover), `wxcodes` (phenomena codes: TS, RA, SN, FG, BR, FZ).

---

## 4. Chronological Splits & Preprocessing Rationale

### The 3-Way Chronological Split (Leakage Prevention)
To prevent temporal macro-weather leakage and preserve realistic operational deployment conditions, we enforce a strict time-ordered split:

| Partition | Calendar Window | Flight Volume | Delay Rate (>= 15 min) | Role |
| :--- | :--- | :---: | :---: | :--- |
| **Training Set** | Jan 1, 2023 – Apr 30, 2024 | **626,943** | 23.2% | Feature pipeline fitting & model training |
| **Validation Set** | May 1 – May 31, 2024 | **41,631** | 32.1% | F1-optimal decision threshold tuning |
| **Held-Out Test Set** | Jun 1 – Jul 31, 2024 | **81,682 (Arr) / 82,039 (Dep)** | 31.5% – 31.7% | Strict out-of-time final evaluation |

### Core Preprocessing Choices:
1. **Target Leakage Elimination:** For pre-departure delay, all post-pushback variables (`DEP_TIME`, `TAXI_OUT`, `WHEELS_OFF`) are strictly excluded. Weather is fused via backward-as-of merging strictly prior to T-2 hours.
2. **Cyclic Hour Transformations:** Scheduled departure hour is transformed into continuous trigonometric projections (sine and cosine of the 24-hour cycle: `sin(2*pi*h/24)`, `cos(2*pi*h/24)`), eliminating artificial boundary breaks between 23:59 and 00:01.
3. **Rotational Chain Engineering:** Aircraft itineraries are linked by tracking `TAIL_NUM` across each flight date, computing `tail_leg_of_day`, inbound delay `prev_arr_delay`, and turnaround buffer `sched_turn_min`.
4. **Encapsulated Scikit-Learn Pipelines:** All median imputers, standard scalers, and one-hot encoders are fitted strictly on training data and wrapped in `ColumnTransformer` pipelines with `handle_unknown='ignore'`.

---

## 5. Held-Out Test Evaluation Scorecards (Jun–Jul 2024)

### Arrival Delay Model Scorecard (Evaluated on 81,682 unseen flights)
*Decision Threshold tuned on May 2024 validation set.*

| Model / Baseline | Threshold | PR-AUC | ROC-AUC | Accuracy | Precision | Recall | F1 Score | Status |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **Gradient Boosting (Champion)** | **0.6588** | **0.9181** | **0.9361** | **90.1%** | **87.0%** | **80.5%** | **0.836** | **Champion** |
| Logistic Regression | 0.6823 | 0.9154 | 0.9328 | 90.1% | 87.1% | 80.2% | 0.835 | Baseline |
| Random Forest | 0.6941 | 0.9148 | 0.9327 | 90.0% | 87.4% | 79.8% | 0.834 | Benchmark |
| Departure Delay Rule Baseline | >= 18 min | 0.9110 | 0.9300 | 89.9% | 86.8% | 79.7% | 0.834 | Domain Rule |
| Majority-Class Baseline | 1.0000 | 0.3147 | 0.5000 | 68.5% | 0.0% | 0.0% | 0.000 | Trivial |

### Departure Delay Model Scorecard (Evaluated on 82,039 unseen flights)
*Decision Threshold tuned on May 2024 validation set.*

| Model / Baseline | Threshold | PR-AUC | ROC-AUC | Accuracy | Precision | Recall | F1 Score | Status |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **Gradient Boosting (Champion)** | **0.5260** | **0.5660** | **0.7310** | **62.9%** | **44.9%** | **75.3%** | **0.563** | **Champion** |
| Average Ensemble | 0.5160 | 0.5680 | 0.7320 | 62.0% | 44.3% | 77.2% | 0.563 | Ensemble |
| Logistic Regression | 0.5300 | 0.5650 | 0.7300 | 63.0% | 45.0% | 75.1% | 0.563 | Linear |
| Random Forest | 0.4940 | 0.5600 | 0.7280 | 59.2% | 42.5% | 80.6% | 0.556 | Benchmark |
| Historical-Rate Baseline | 0.2045 | 0.4875 | 0.6860 | 53.2% | 39.0% | 84.2% | 0.533 | Rate Baseline |
| Majority-Class Baseline | 1.0000 | 0.3173 | 0.5000 | 68.3% | 0.0% | 0.0% | 0.000 | Trivial |

### Bootstrap Statistical Significance (200 Resamples, 95% Confidence Intervals)
- **Arrival Model vs Rule Baseline:** PR-AUC Gain = **+0.0068** (95% CI: `[+0.0062, +0.0074]`, p < 0.001).
- **Departure Model vs Historical Rate:** PR-AUC Gain = **+0.0783** (95% CI: `[+0.0738, +0.0827]`, p < 0.001).

---

## 6. Feature Ablation Experiment Results

Conducted on the Pre-Departure model across held-out test data:

| Feature Set | Features | Val F1 | Test Precision | Test Recall | Test F1 | Test PR-AUC | Test ROC-AUC |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Set A: Base** (Weather, Schedule, 30-day rates) | 29 | 0.544 | 0.406 | 0.828 | 0.545 | 0.523 | 0.709 |
| **Set B: + Extra Trailing Rates** (Route-hour, origin) | 34 | 0.549 | 0.428 | 0.789 | 0.555 | 0.538 | 0.719 |
| **Set C: + Airport Status & Load** (Full Champion) | **40** | **0.557** | **0.447** | **0.759** | **0.563** | **0.566** | **0.731** |

*Takeaway:* Real-time hub congestion telemetry yields a **+0.043 PR-AUC increase** over baseline features.

---

## 7. Step-by-Step Installation & Execution Guide

### Prerequisites
- Python 3.10, 3.11, or 3.12 (also compatible with Python 3.14).
- 4 GB RAM minimum (8 GB recommended for memory-mapped Parquet queries).

### Setup Commands (Windows PowerShell)

```powershell
# 1. Navigate to the flight-delay-website folder
Set-Location "D:\Downloads\2ndyear\ML-2026\SHANMUKHA\flight-delay-website"

# 2. Create and activate a virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1

# 3. Upgrade pip and install required dependencies
pip install --upgrade pip
pip install -r requirements.txt

# 4. Run automated unit tests to verify system integrity
python -m unittest discover tests -v

# 5. Start the web application server
python app.py
```

### Setup Commands (Linux / macOS)

```bash
# 1. Navigate to the flight-delay-website folder
cd flight-delay-website

# 2. Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# 3. Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# 4. Run tests
python3 -m unittest discover tests -v

# 5. Start the server
python3 app.py
```

Open your browser to: **`http://127.0.0.1:5000`**.

---

## 8. Interactive Features on the Website

1. **Interactive Decision Threshold & Operational Tradeoff Simulator:**
   - Available on `/performance` for **both Arrival Delay and Departure Delay**.
   - Readers can sweep the decision threshold from 0.05 to 0.95 and observe live recalculations of Precision, Recall, F1, True Positives, and False Alarms.
   - Includes one-click operational presets: "F1-Optimal", "High-Precision", and "High-Recall".

2. **Interactive Feature Ablation Explorer:**
   - Available on `/performance` for **both Arrival Delay and Departure Delay**.
   - Readers can click between ablation tiers to inspect the exact empirical delta in PR-AUC and understand where predictive signal comes from.

3. **Interactive Flight Search & Counterfactual Inference Tool:**
   - Available on `/predict`.
   - Lets readers query 952k real commercial flights across 2023 and 2024, inspect origin weather and aircraft turnaround times, compare model predictions against real BTS ground truths, and test custom flight scenarios.

---

## 9. AI-Use Disclosure & Formal Academic Citations

### Generative AI Disclosure
Generative AI tools were used during development to assist with code refactoring, HTML/CSS layout templating, and documentation formatting. All data preprocessing pipelines, machine learning model architectures, feature engineering logic, evaluation metrics, statistical bootstrap tests, and scientific interpretations were designed, executed, and validated by the project authors.

### Formal Citations
1. **Bureau of Transportation Statistics (BTS):** U.S. Department of Transportation, *Reporting Carrier On-Time Performance Data (2023–2024)*.
2. **National Oceanic and Atmospheric Administration (NOAA):** Automated Surface Observing System (ASOS / METAR) Archives, Iowa State University Environmental Mesonet (2023–2024).
3. **Scikit-learn:** Pedregosa et al., *Scikit-learn: Machine Learning in Python*, Journal of Machine Learning Research (JMLR) 12, pp. 2825–2830 (2011).
4. **Gradient Boosting:** Friedman, J. H., *Greedy Function Approximation: A Gradient Boosting Machine*, Annals of Statistics, 29(5), 1189–1232 (2001).

---

## 10. Individual Understanding & Defense (Rubric Defense Guide)

In accordance with course evaluation criteria (*"Each of you must explain your contribution, key choices, evaluation, and a limitation, and reason about a small change. Prepare for this separately."*), each team member's independent technical defense is detailed below:

### Team Member 1: Tommandru Harshith Jeevan (Roll No: 25110325)
* **Formulated Scope & Role:** Pre-Departure Delay Formulation (Stage 1 @ T-2h) & Full-Stack MLOps Web Platform
* **1. Contribution:**
  - Formulated Question 1: Classifying whether flight $i$ will depart with $\ge 15$-minute delay at the operational $T-2\text{h}$ pre-departure decision window.
  - Implemented the strict leakage-free backward-as-of join merging BTS flight records with NOAA ASOS/METAR weather observations across 10 primary hubs.
  - Engineered dynamic airport load telemetry (rolling 1h, 3h, and 6h departure delay rates).
  - Executed the 3-tier feature ablation experiments (Sets A, B, and C) quantifying the predictive gain of airport congestion telemetry (+0.043 PR-AUC).
  - Architected the production Flask web application, REST inference API, interactive threshold/ablation tradeoff simulators, and GitHub Pages static inference engine.
* **2. Key Choices:**
  - *Strict Leakage Elimination:* Completely removed all post-pushback fields (`DEP_TIME`, `TAXI_OUT`, `WHEELS_OFF`) and restricted weather observations to strictly before $T-2\text{h}$.
  - *Cyclic Time Transformations:* Enforced continuous trigonometric encoding ($\sin(2\pi h/24)$, $\cos(2\pi h/24)$) for scheduled departure hours, removing artificial boundary discontinuities at midnight.
  - *Model Selection:* Selected `HistGradientBoostingClassifier` over linear models and random forests for its native handling of missing METAR values and non-linear interactions between weather phenomena and ground congestion.
  - *F1-Optimal Thresholding:* Tuned decision threshold on May 2024 validation data ($t^* = 0.5260$) rather than default 0.50, balancing operational recall (75.3%) without triggering excessive false alarm gate-holds.
* **3. Evaluation:**
  - Evaluated on 82,039 unseen flights across June–July 2024 under strict chronological holdout.
  - Outperformed historical carrier/route baseline: **PR-AUC of 0.566 vs 0.488** (+0.078 gain, 95% CI `[+0.0738, +0.0827]`, $p < 0.001$ via 200 bootstrap iterations), **ROC-AUC: 0.731**, **F1: 0.563**, **Recall: 75.3%**.
* **4. Limitation:**
  - Inability to observe micro-level Air Traffic Control (ATC) Ground Delay Programs (GDP) and ground stops issued between $T-2\text{h}$ and $T-0$. Rapid afternoon convective storm squalls at DFW and CLT create abrupt ground holds not yet apparent at $T-2\text{h}$, causing unavoidable False Negatives.
* **5. Reasoning About a Small Change:**
  - *Change:* What if the decision window was shifted from $T-2\text{hours}$ to $T-30\text{minutes}$?
  - *Causal Impact:* Model PR-AUC would rise significantly (estimated $+0.10$ to $\sim 0.67$) and False Negatives would plummet because incoming aircraft arrival status, current gate availability, and active taxiway queues would be observable.
  - *Operational Tradeoff:* Operational actionability drops sharply: at $T-30\text{m}$, boarding is completed and luggage is loaded; station managers lose the lead time necessary to meter taxiways, stage pushback tugs, or swap gates without passenger disruption.

---

### Team Member 2: Bantu Shanmukha Naidu (Roll No: 25110071)
* **Formulated Scope & Role:** Post-Departure Arrival Delay Formulation (Stage 2 En-Route) & Rotational Chain Modeling
* **1. Contribution:**
  - Formulated Question 2: Classifying whether flight $i$ will arrive $\ge 15$ minutes late at its destination gate once it has departed with confirmed pushback delay.
  - Engineered the multi-leg aircraft rotational chain tracking: sorted flight records by date and `TAIL_NUM` to compute aircraft daily leg count (`tail_leg_of_day`), incoming leg delay (`prev_arr_delay`), and scheduled turnaround buffer (`sched_turn_min`).
  - Built the Scikit-Learn training pipelines and the Google Colab reproduction notebook (`arrival_delay_colab.ipynb`).
  - Executed statistical bootstrap significance testing (200 resamples) comparing machine learning performance against standard industry heuristic rules ($\text{DEP\_DELAY} \ge 18\text{m}$).
  - Conducted model calibration analysis and subgroup error breakdowns across hub airports, departure hours, and carriers.
* **2. Key Choices:**
  - *Post-Pushback Formulation:* Incorporated confirmed `DEP_DELAY` as an explicit input while strictly omitting in-flight diversion telemetry or destination taxi-in duration to prevent target leakage.
  - *Non-Linear Buffer Absorption:* Selected `HistGradientBoostingClassifier` to model the non-linear relationship between departure delay magnitude and route elapsed time (long-haul flights absorb delays in-flight; short-haul flights compound them).
  - *Validation-Tuned Decision Threshold:* Selected $t^* = 0.6588$ on the May 2024 validation set (optimized for F1-score) to achieve high precision ($87.0\%$) and F1-score ($0.836$) on the minority delayed class.
  - *Missing Tail Handling:* Categorized unlinked aircraft tails as a separate rotational tier rather than dropping rows, preventing selection bias against charter or substituted aircraft.
* **3. Evaluation:**
  - Evaluated on 81,682 unseen held-out test flights across June–July 2024.
  - Champion Gradient Boosting achieved **PR-AUC: 0.9181**, **ROC-AUC: 0.9361**, **Accuracy: 90.1%**, **Precision: 87.0%**, **Recall: 80.5%**, and **F1: 0.836**.
  - Statistically significantly beat the standard airline rule baseline ($\ge 18\text{m}$ departure delay) with a PR-AUC improvement of **+0.0068** (95% CI `[+0.0062, +0.0074]`, $p < 0.001$).
* **4. Limitation:**
  - Lack of dynamic en-route atmospheric wind data (jet stream tailwinds/headwinds) and real-time ATC airspace holding stacks. When pilots apply throttle adjustments in cruise or ATC institutes en-route zig-zag path extensions around storms, the post-departure model cannot dynamically update airborne duration before landing.
* **5. Reasoning About a Small Change:**
  - *Change:* What if continuous departure delay (`DEP_DELAY` in minutes) was replaced with a binary indicator `IS_DEP_DELAYED` ($\ge 15\text{m}$)?
  - *Causal Impact:* Model PR-AUC would degrade severely from $0.9181$ down to $\sim 0.77$.
  - *Operational Reason:* Continuous delay provides essential magnitude: a 16-minute pushback delay on a 5-hour SEA–MCO route is easily absorbed by built-in flight schedule padding, whereas an 80-minute departure delay is physically unrecoverable regardless of tailwinds. Collapsing delay into binary destroys this non-linear interaction with route elapsed time.


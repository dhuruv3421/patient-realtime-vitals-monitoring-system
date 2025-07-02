# config.py (for Streamlit Cloud)

import streamlit as st

# ================================
# 🔐 MongoDB Configuration
# ================================
MONGODB_URI = st.secrets["MONGODB_URI"]

# Databases
DB_STATIC = st.secrets.get("DB_STATIC", "healthcare")          # Static profiles + historical vitals
DB_LIVE = st.secrets.get("DB_LIVE", "healthcare_db")           # Live vitals, alerts, logs

# Collections
COLL_PATIENTS_STATIC = "patients"   # In healthcare
COLL_PATIENTS_LIVE = "patients"     # In healthcare_db
COLL_ALERTS = "alerts"
COLL_LOGS = "logs"

# ================================
# ☁️ AWS Configuration
# ================================
AWS_REGION = st.secrets["AWS_REGION"]
S3_BUCKET = st.secrets["S3_BUCKET"]
S3_ANALYSIS_PREFIX = "llm-analyses/"  # e.g., llm-analyses/P004/<timestamp>/analysis.json

PARTITION_KEY_FIELD = "patient_id"

# ================================
# 🔄 Kinesis Configuration
# ================================
KINESIS_STREAM_NAME = st.secrets["KINESIS_STREAM_NAME"]
KINESIS_PARTITION_KEY = st.secrets["KINESIS_PARTITION_KEY"]
SEND_TO_KINESIS = True     # Set to False to disable Kinesis publishing

# ================================
# ⚙️ Simulation Settings
# ================================
ENABLE_SIMULATION = True
SIMULATION_INTERVAL_SEC = 10         # seconds between updates
ANOMALY_PROBABILITY = 0.08           # 8% abnormal vitals

# ================================
# 📊 Dashboard Behavior
# ================================
DASHBOARD_REFRESH_SEC = 5
MAX_VITAL_HISTORY = 100
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# ================================
# 📝 Logging Preferences
# ================================
ENABLE_LOGGING = True
LOG_TO_MONGODB = True
LOG_SOURCE = "healthcare_dashboard"

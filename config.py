# config.py

from dotenv import load_dotenv
import os

# Load environment variables from .env file
load_dotenv()

# ================================
# 🔐 MongoDB Configuration
# ================================
MONGODB_URI = os.getenv("MONGODB_URI")

# Databases
DB_STATIC = os.getenv("DB_STATIC", "healthcare")          # Static profiles + historical vitals
DB_LIVE = os.getenv("DB_LIVE", "healthcare_db")           # Live vitals, alerts, logs

# Collections (can stay hardcoded unless you want to make them dynamic too)
COLL_PATIENTS_STATIC = "patients"   # In healthcare
COLL_PATIENTS_LIVE = "patients"     # In healthcare_db
COLL_ALERTS = "alerts"
COLL_LOGS = "logs"

# ================================
# ☁️ AWS Configuration
# ================================
AWS_REGION = os.getenv("AWS_REGION")
S3_BUCKET = os.getenv("S3_BUCKET")
S3_ANALYSIS_PREFIX = "llm-analyses/"  # e.g., llm-analyses/P004/<timestamp>/analysis.json

PARTITION_KEY_FIELD = "patient_id"

# ================================
# 🔄 Kinesis Configuration
# ================================
KINESIS_STREAM_NAME = os.getenv("KINESIS_STREAM_NAME")
KINESIS_PARTITION_KEY = os.getenv("KINESIS_PARTITION_KEY")
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

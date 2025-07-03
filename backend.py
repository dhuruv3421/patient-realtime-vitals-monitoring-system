# backend.py

import random
import threading
import time
from datetime import datetime
import json
import boto3
from pymongo import MongoClient, errors
from config import (
    # Mongo
    MONGODB_URI, DB_STATIC, DB_LIVE,
    COLL_PATIENTS_STATIC, COLL_PATIENTS_LIVE,
    COLL_ALERTS, COLL_LOGS,

    # AWS
    AWS_REGION, S3_BUCKET, S3_ANALYSIS_PREFIX,

    # Simulation
    ENABLE_SIMULATION, SIMULATION_INTERVAL_SEC, ANOMALY_PROBABILITY,

    # Logging
    ENABLE_LOGGING, LOG_TO_MONGODB, LOG_SOURCE,

    # Kinesis
    SEND_TO_KINESIS, KINESIS_STREAM_NAME, KINESIS_PARTITION_KEY
)

# ===============================
# MongoDB Clients
# ===============================
try:
    mongo_client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
    mongo_client.server_info()
    db_static = mongo_client[DB_STATIC]
    db_live = mongo_client[DB_LIVE]
    log_collection = db_live[COLL_LOGS] if LOG_TO_MONGODB else None
    print("[MongoDB] Connected successfully.")
except Exception as e:
    db_static = db_live = log_collection = None
    print(f"[MongoDB Error] Connection failed: {e}")

# ===============================
# AWS Clients
# ===============================
try:
    s3_client = boto3.client("s3", region_name=AWS_REGION)
    s3_client.list_buckets()
    print("[S3] Client ready and authenticated.")
except Exception as e:
    s3_client = None
    print(f"[S3 Error] Initialization failed: {e}")

try:
    kinesis_client = boto3.client("kinesis", region_name=AWS_REGION)
    kinesis_client.list_streams()
    print("[Kinesis] Client ready and authenticated.")
except Exception as e:
    kinesis_client = None
    print(f"[Kinesis Error] Initialization failed: {e}")

# ===============================
# Logging
# ===============================
def log_event(level, function, message, context=None):
    timestamp = datetime.utcnow().isoformat()
    entry = {
        "timestamp": timestamp,
        "level": level.upper(),
        "source": LOG_SOURCE,
        "function": function,
        "message": message,
        "context": context or {}
    }

    if ENABLE_LOGGING:
        print(f"[{level.upper()}] [{function}] {message}")
        if context:
            print(f" └─ Context: {context}")

    if LOG_TO_MONGODB and log_collection is not None:
        try:
            log_collection.insert_one(entry)
        except Exception as e:
            print(f"[Log DB Error] {e}")


def get_latest_vitals_from_s3(patient_id, limit=20):
    """
    Fetch latest vitals for a patient from S3 (based on timestamp order).
    Assumes all objects are under a folder like 'vitals_raw/P001/'.
    """
    if s3_client is None:
        log_event("ERROR", "get_latest_vitals_from_s3", "No S3 client configured.")
        return []

    prefix = f"vitals_raw/{patient_id}/"  # ✅ FIXED

    try:
        paginator = s3_client.get_paginator('list_objects_v2')
        pages = paginator.paginate(Bucket=S3_BUCKET, Prefix=prefix)

        all_files = []
        for page in pages:
            all_files.extend(page.get("Contents", []))

        # Sort by LastModified descending
        latest_files = sorted(all_files, key=lambda x: x["LastModified"], reverse=True)[:limit]

        vitals_list = []
        for obj in latest_files:
            key = obj["Key"]
            response = s3_client.get_object(Bucket=S3_BUCKET, Key=key)
            content = response["Body"].read().decode("utf-8")
            vitals = json.loads(content)
            vitals_list.append(vitals)

        return vitals_list

    except Exception as e:
        log_event("ERROR", "get_latest_vitals_from_s3", str(e), {"patient_id": patient_id})
        return []



# ===============================
# Connection Validation
# ===============================
def validate_connections():
    status = {
        "mongodb": False,
        "s3": False,
        "kinesis": False
    }

    if db_live is not None:
        try:
            db_live.command("ping")
            status["mongodb"] = True
        except Exception as e:
            log_event("ERROR", "validate_connections", f"MongoDB ping failed: {e}")

    if s3_client:
        try:
            s3_client.list_buckets()
            status["s3"] = True
        except Exception as e:
            log_event("ERROR", "validate_connections", f"S3 test failed: {e}")

    if kinesis_client:
        try:
            kinesis_client.list_streams()
            status["kinesis"] = True
        except Exception as e:
            log_event("ERROR", "validate_connections", f"Kinesis test failed: {e}")

    return status

# ===============================
# Patient Data
# ===============================
def fetch_active_patients():
    if db_static is None:
        log_event("ERROR", "fetch_active_patients", "db_static is None, cannot fetch patients.")
        return []
    try:
        patients = db_static[COLL_PATIENTS_STATIC].find(
            {"is_active": True},
            {"_id": 0}
        )
        return list(patients)
    except Exception as e:
        log_event("ERROR", "fetch_active_patients", f"Fetch failed: {e}")
        return []

def get_static_profile(pid):
    try:
        if db_static is None:
            log_event("ERROR", "get_static_profile", "db_static is None.", {"patient_id": pid})
            return None
        return db_static[COLL_PATIENTS_STATIC].find_one({"patient_id": pid}, {"_id": 0})
    except Exception as e:
        log_event("ERROR", "get_static_profile", str(e), {"patient_id": pid})
        return None

def get_live_vitals(pid):
    try:
        if db_live is None:
            log_event("ERROR", "get_live_vitals", "db_live is None.", {"patient_id": pid})
            return {}
        doc = db_live[COLL_PATIENTS_LIVE].find_one({"patient_id": pid}, {"_id": 0})
        return doc.get("vitals", {}) if doc else {}
    except Exception as e:
        log_event("ERROR", "get_live_vitals", str(e), {"patient_id": pid})
        return {}

def get_vitals_history(pid, limit=100):
    try:
        if db_static is None:
            log_event("ERROR", "get_vitals_history", "db_static is None.", {"patient_id": pid})
            return []
        doc = db_static[COLL_PATIENTS_STATIC].find_one(
            {"patient_id": pid},
            {"vitals_history": {"$slice": -limit}, "_id": 0}
        )
        return doc.get("vitals_history", []) if doc else []
    except Exception as e:
        log_event("ERROR", "get_vitals_history", str(e), {"patient_id": pid})
        return []

# ===============================
# Alerts & Analysis
# ===============================
def get_active_alerts():
    try:
        if db_live is None:
            log_event("ERROR", "get_active_alerts", "db_live is None.")
            return []

        alerts = db_live[COLL_ALERTS].find(
            {"status": {"$ne": "resolved"}},
            {"_id": 0}
        )
        return list(alerts)
    except Exception as e:
        log_event("ERROR", "get_active_alerts", str(e))
        return []

def resolve_alert(patient_id, s3_path):
    """
    Resolves the alert for the patient:
    - Deletes the analysis file from S3 if present.
    - Marks the alert as resolved in MongoDB.

    Returns:
        True if either the file was deleted (or already missing) and/or
        the Mongo alert was updated. False on errors.
    """
    if not s3_path:
        log_event(
            "WARNING",
            "resolve_alert",
            "No S3 path provided for alert resolution.",
            {"patient_id": patient_id}
        )
        return False

    deleted = False

    # Delete the file from S3 if exists
    if s3_client:
        try:
            s3_client.head_object(Bucket=S3_BUCKET, Key=s3_path)
            s3_client.delete_object(Bucket=S3_BUCKET, Key=s3_path)
            deleted = True
            log_event(
                "INFO",
                "resolve_alert",
                f"Deleted alert file from S3: {s3_path}",
                {"patient_id": patient_id}
            )
        except s3_client.exceptions.NoSuchKey:
            log_event(
                "WARNING",
                "resolve_alert",
                f"File not found in S3 (already deleted?): {s3_path}",
                {"patient_id": patient_id}
            )
            deleted = True
        except Exception as e:
            log_event(
                "ERROR",
                "resolve_alert",
                f"Error deleting file from S3: {e}",
                {"patient_id": patient_id, "s3_path": s3_path}
            )
            return False
    else:
        log_event(
            "ERROR",
            "resolve_alert",
            "S3 client unavailable, cannot delete file.",
            {"patient_id": patient_id, "s3_path": s3_path}
        )
        return False

    # Now mark the alert resolved in MongoDB
    if db_live is None:
        log_event(
            "ERROR",
            "resolve_alert",
            "MongoDB not connected, cannot update alert.",
            {"patient_id": patient_id, "s3_path": s3_path}
        )
        return False

    try:
        result = db_live[COLL_ALERTS].update_one(
            {
                "patient_id": patient_id,
                "s3_analysis_location": s3_path
            },
            {
                "$set": {
                    "status": "resolved",
                    "resolved_at": datetime.utcnow().isoformat()
                }
            }
        )

        if result.modified_count > 0:
            log_event(
                "INFO",
                "resolve_alert",
                f"Alert resolved in MongoDB for patient {patient_id}.",
                {"s3_path": s3_path}
            )
            return True
        else:
            log_event(
                "WARNING",
                "resolve_alert",
                f"No matching alert found to resolve for patient {patient_id}. Possibly already resolved?",
                {"s3_path": s3_path}
            )
            # still return True if we successfully deleted S3 file
            return deleted

    except Exception as e:
        log_event(
            "ERROR",
            "resolve_alert",
            f"Error updating alert in MongoDB: {e}",
            {"patient_id": patient_id, "s3_path": s3_path}
        )
        return False



def fetch_llm_analysis(s3_analysis_location, quiet=False):
    """
    Loads the analysis JSON from S3 if it exists.
    Returns None if the object is missing or unreadable.

    Args:
        s3_analysis_location (str): the S3 key (e.g. llm-analyses/P001/...)
        quiet (bool): if True, suppress warnings

    Returns:
        dict | None
    """
    if not s3_analysis_location:
        return None

    if s3_client is None:
        log_event(
            "ERROR",
            "fetch_llm_analysis",
            "S3 client is None.",
            {"key": s3_analysis_location}
        )
        return None

    # Only allow analysis objects under the correct prefix
    if not s3_analysis_location.startswith("llm-analyses/"):
        if not quiet:
            log_event(
                "WARNING",
                "fetch_llm_analysis",
                f"Invalid prefix for analysis key: {s3_analysis_location}",
            )
        return None

    try:
        obj = s3_client.get_object(Bucket=S3_BUCKET, Key=s3_analysis_location)
        return json.loads(obj["Body"].read())
    except Exception as e:
        if not quiet:
            log_event(
                "WARNING",
                "fetch_llm_analysis",
                f"Missing: {s3_analysis_location}",
                {"error": str(e)},
            )
        return None


def delete_alert_file_from_s3(s3_key):
    if s3_client is None:
        log_event("ERROR", "delete_alert_file_from_s3", "S3 client is None.", {"s3_key": s3_key})
        return False
    try:
        s3_client.delete_object(Bucket=S3_BUCKET, Key=s3_key)
        log_event("INFO", "delete_alert_file_from_s3", f"Deleted {s3_key}")
        return True
    except Exception as e:
        log_event("ERROR", "delete_alert_file_from_s3", str(e), {"s3_key": s3_key})
        return False

# ===============================
# New Analytics Queries
# ===============================
def get_logs(limit=200):
    """
    Return system logs from the logs collection.
    """
    if db_live is not None:
        try:
            return list(db_live[COLL_LOGS].find({}, {"_id": 0}).sort("timestamp", -1).limit(limit))
        except Exception as e:
            log_event("ERROR", "get_logs", str(e))
            return []
    return []

def get_patient_alerts_from_s3():
    """
    Scan all alerts in S3 alerts_raw and load patient alert data.
    """
    alerts = []
    prefix = "alerts_raw/"

    if s3_client is None:
        log_event("ERROR", "get_patient_alerts_from_s3", "No S3 client configured.")
        return []

    try:
        paginator = s3_client.get_paginator('list_objects_v2')
        pages = paginator.paginate(
            Bucket="patient-vitals-archive-dhuruv",
            Prefix=prefix
        )

        for page in pages:
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if key.endswith(".json"):
                    s3_object = s3_client.get_object(
                        Bucket="patient-vitals-archive-dhuruv",
                        Key=key
                    )
                    data = json.loads(s3_object["Body"].read())
                    alerts.append(data)

        log_event("INFO", "get_patient_alerts_from_s3", f"Loaded {len(alerts)} alert files from S3.")
        return alerts

    except Exception as e:
        log_event("ERROR", "get_patient_alerts_from_s3", str(e))
        return []


def get_alert_patients():
    """
    Return all patients that have current_vitals.flags or llm_analysis_history.
    """
    if db_static is not None:
        try:
            results = list(db_static[COLL_PATIENTS_LIVE].find(
                {
                    "$or": [
                        {"current_vitals.flags": {"$exists": True, "$ne": []}},
                        {"llm_analysis_history": {"$exists": True}}
                    ]
                },
                {
                    "_id": 0,
                    "patient_id": 1,
                    "current_vitals": 1,
                    "vitals": 1,
                    "vitals_history": 1,
                    "llm_analysis_history": 1
                }
            ))
            print(f"[DEBUG] Patients fetched: {len(results)}")
            return results
        except Exception as e:
            log_event("ERROR", "get_alert_patients", str(e))
            return []
    return []






def get_vitals_fluctuations(limit=10):
    """
    Return vitals history for patients from MongoDB.
    """
    if db_static is not None:
        try:
            return list(db_static[COLL_PATIENTS_STATIC].find(
                {"vitals_history": {"$exists": True}},
                {"_id": 0, "patient_id": 1, "vitals_history": {"$slice": -limit}}
            ))
        except Exception as e:
            log_event("ERROR", "get_vitals_fluctuations", str(e))
            return []
    return []

# ===============================
# Simulation
# ===============================
from producer import main as run_producer_simulation

def maybe_start_simulation():
    if not ENABLE_SIMULATION:
        log_event("INFO", "maybe_start_simulation", "Simulation is disabled.")
        return False

    conn_status = validate_connections()
    if not conn_status["mongodb"]:
        log_event("ERROR", "maybe_start_simulation", "MongoDB not connected. Cannot start simulation.")
        return False

    t = threading.Thread(target=run_producer_simulation, daemon=True)
    t.start()
    log_event("INFO", "maybe_start_simulation", "Vitals producer simulation thread started.")
    return True

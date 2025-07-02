# producer.py

import json
import time
import random
from pymongo import MongoClient
import boto3
from datetime import datetime
import os

from config import (
    AWS_REGION,
    KINESIS_STREAM_NAME,
    KINESIS_PARTITION_KEY,
    MONGODB_URI,
    DB_STATIC,
    COLL_PATIENTS_STATIC,
)

# File-based stop flag
SIMULATION_FLAG_FILE = "simulation_running.txt"

# Initialize Kinesis client
kinesis_client = boto3.client("kinesis", region_name=AWS_REGION)

# Initialize MongoDB client (shared global client)
mongo_client = MongoClient(MONGODB_URI)
db_static = mongo_client[DB_STATIC]
patients_collection = db_static[COLL_PATIENTS_STATIC]

def fetch_active_patients():
    """Fetch all active patients from MongoDB"""
    try:
        active_patients = list(
            patients_collection.find({"is_active": True}, {"_id": 0})
        )
        print(f"Found {len(active_patients)} active patients.")
        for patient in active_patients:
            print(f"- {patient['patient_id']}: {patient.get('name')}")
        return active_patients
    except Exception as e:
        print(f"Error fetching patients from MongoDB: {e}")
        return []

def get_patient_baseline_vitals(patient):
    """Compute baseline vitals ranges based on history"""
    baseline = {
        "heart_rate_range": (60, 100),
        "systolic_range": (110, 130),
        "diastolic_range": (70, 85),
        "temp_range": (36.1, 37.2),
        "spo2_range": (95, 99),
    }

    if patient.get("vitals_history"):
        recent = patient["vitals_history"][-3:]
        hr_values = [v["heart_rate"] for v in recent if v.get("heart_rate")]
        if hr_values:
            avg = sum(hr_values) / len(hr_values)
            baseline["heart_rate_range"] = (
                max(50, int(avg - 15)),
                min(120, int(avg + 15)),
            )
        bp_values = [v["blood_pressure"] for v in recent if v.get("blood_pressure")]
        if bp_values:
            systolics, diastolics = [], []
            for bp in bp_values:
                try:
                    s, d = map(int, bp.split("/"))
                    systolics.append(s)
                    diastolics.append(d)
                except:
                    continue
            if systolics and diastolics:
                avg_sys = sum(systolics) / len(systolics)
                avg_dia = sum(diastolics) / len(diastolics)
                baseline["systolic_range"] = (
                    max(90, int(avg_sys - 10)),
                    min(160, int(avg_sys + 10)),
                )
                baseline["diastolic_range"] = (
                    max(60, int(avg_dia - 8)),
                    min(100, int(avg_dia + 8)),
                )
        spo2_values = [v["spo2"] for v in recent if v.get("spo2")]
        if spo2_values:
            avg = sum(spo2_values) / len(spo2_values)
            baseline["spo2_range"] = (max(88, avg - 3), min(100, avg + 2))
    return baseline

def generate_patient_vitals(patient, baseline):
    heart_rate = random.randint(*baseline["heart_rate_range"])
    systolic = random.randint(*baseline["systolic_range"])
    diastolic = random.randint(*baseline["diastolic_range"])
    temp = round(random.uniform(*baseline["temp_range"]), 1)
    spo2 = round(random.uniform(*baseline["spo2_range"]), 1)

    if patient.get("diagnosed_conditions"):
        for condition in patient["diagnosed_conditions"]:
            name = condition.get("condition", "").lower()
            severity = condition.get("severity", "").lower()
            if "hypertension" in name and severity in ["moderate", "severe"]:
                systolic += random.randint(10, 25)
                diastolic += random.randint(5, 15)
            elif "diabetes" in name:
                heart_rate += random.randint(0, 10)
            elif "copd" in name or "asthma" in name:
                spo2 = max(88, spo2 - random.uniform(0, 5))
            elif "fever" in name or "infection" in name:
                temp += random.uniform(0.5, 2.0)
                heart_rate += random.randint(5, 20)

    heart_rate = max(40, min(180, heart_rate))
    systolic = max(80, min(200, systolic))
    diastolic = max(50, min(120, diastolic))
    temp = max(35.0, min(42.0, temp))
    spo2 = max(70.0, min(100.0, spo2))

    return {
        "patient_id": patient["patient_id"],
        "patient_name": patient.get("name", "Unknown"),
        "heart_rate": heart_rate,
        "blood_pressure": f"{systolic}/{diastolic}",
        "temperature_celsius": temp,
        "oxygen_saturation": spo2,
        "timestamp": datetime.utcnow().isoformat(),
    }

def send_vitals_to_kinesis(vitals_data):
    try:
        response = kinesis_client.put_record(
            StreamName=KINESIS_STREAM_NAME,
            Data=json.dumps(vitals_data),
            PartitionKey=vitals_data[KINESIS_PARTITION_KEY],
        )
        print(
            f"✓ Sent data for {vitals_data['patient_id']} ({vitals_data['patient_name']})"
        )
        return response
    except Exception as e:
        print(
            f"✗ Error sending data for {vitals_data['patient_id']}: {e}"
        )
        return None

def is_simulation_running():
    if os.path.exists(SIMULATION_FLAG_FILE):
        with open(SIMULATION_FLAG_FILE, "r") as f:
            return f.read().strip() == "1"
    return False

def set_simulation_running(flag):
    with open(SIMULATION_FLAG_FILE, "w") as f:
        f.write("1" if flag else "0")

def main():
    print("Starting Patient Vitals Simulation (Standalone Producer)")
    print("=" * 60)

    set_simulation_running(True)

    active_patients = fetch_active_patients()
    if not active_patients:
        print("No active patients found. Exiting...")
        return

    patient_baselines = {
        p["patient_id"]: get_patient_baseline_vitals(p) for p in active_patients
    }

    try:
        cycle_count = 0
        while is_simulation_running():
            cycle_count += 1
            print(f"\n--- Simulation Cycle {cycle_count} ---")

            for patient in active_patients:
                if not is_simulation_running():
                    print("Simulation stopped mid-cycle.")
                    break

                pid = patient["patient_id"]
                baseline = patient_baselines[pid]

                vitals_data = generate_patient_vitals(patient, baseline)
                send_vitals_to_kinesis(vitals_data)

                time.sleep(1)

            if not is_simulation_running():
                break

            print(f"Completed cycle {cycle_count} for {len(active_patients)} patients.")
            time.sleep(3)

    except KeyboardInterrupt:
        print("\nSimulation stopped by user.")
    except Exception as e:
        print(f"Error in main loop: {e}")
    finally:
        set_simulation_running(False)
        print("Simulation stopped.")

if __name__ == "__main__":
    main()

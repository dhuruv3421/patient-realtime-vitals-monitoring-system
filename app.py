# app.py

import streamlit as st
import time
import pandas as pd
from datetime import datetime
import plotly.graph_objects as go
from backend import (
    log_event,
    fetch_active_patients,
    get_static_profile,
    get_live_vitals,
    get_vitals_history,
    get_active_alerts,
    resolve_alert,
    fetch_llm_analysis,
    get_logs,
    get_alert_patients,
    get_vitals_fluctuations,
    maybe_start_simulation,
    db_live,
    db_static,  
    s3_client,
    kinesis_client,
    get_patient_alerts_from_s3,
    get_latest_vitals_from_s3,
)
from producer import set_simulation_running, is_simulation_running
from streamlit_autorefresh import st_autorefresh
from config import DASHBOARD_REFRESH_SEC

# @st.cache_data(ttl=2)
# def get_cached_s3_vitals(patient_id, limit=20):
#     from backend import get_latest_vitals_from_s3
#     return get_latest_vitals_from_s3(patient_id, limit)


# ===============================
# Page Config
# ===============================
st.set_page_config(
    page_title="🏥 Patient Realtime Vitals Monitoring System",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ===============================
# Session State Setup
# ===============================
if "sim_started" not in st.session_state:
    st.session_state.sim_started = is_simulation_running()

# ===============================
# System Status
# ===============================
@st.cache_data(ttl=3)
def get_system_status():
    sim_running = is_simulation_running()
    st.session_state.sim_started = sim_running
    return {
        "MongoDB": "🟢 Connected" if db_live is not None and db_static is not None else "🔴 Disconnected",
        "S3": "🟢 Connected" if s3_client else "🔴 Disconnected",
        "Kinesis": "🟢 Connected" if kinesis_client else "🔴 Disconnected",
        "Simulation": "🟢 Running" if sim_running else "🔴 Stopped"
    }

# ===============================
# Simulation Controls
# ===============================
def show_simulation_controls():
    st.markdown("## 🧪 Simulation Control")

    sim_running = st.session_state.sim_started

    if sim_running:
        st.success("✅ Simulation is running.")
        if st.button("⏹️ Stop Simulation", type="primary"):
            set_simulation_running(False)
            st.session_state.sim_started = is_simulation_running()
            st.success("Simulation stopped successfully.")
            st.rerun()
    else:
        if st.button("▶️ Start Simulation", type="primary"):
            success = maybe_start_simulation()
            if success:
                set_simulation_running(True)
                st.session_state.sim_started = is_simulation_running()
                st.success("Simulation started successfully!")
                st.rerun()
            else:
                st.error("Failed to start simulation. Check logs.")

def create_live_scatter_plots(patient_id, limit=20):
    history = get_latest_vitals_from_s3(patient_id, limit)

    if not history:
        st.warning("No vitals history available.")
        return

    df_data = []
    for record in history:
        timestamp = pd.to_datetime(record.get("timestamp", datetime.now().isoformat()))
        df_data.append({
            "timestamp": timestamp,
            "heart_rate": record.get("heart_rate", 0),
            "spo2": record.get("oxygen_saturation", 0),
            "temperature": record.get("temperature_celsius", 0),
            "blood_pressure": record.get("blood_pressure", "0/0"),
        })

    df = pd.DataFrame(df_data)
    if df.empty:
        st.warning("No data for plots.")
        return

    df["systolic"] = df["blood_pressure"].apply(lambda bp: int(bp.split("/")[0]) if "/" in bp else 0)
    df["diastolic"] = df["blood_pressure"].apply(lambda bp: int(bp.split("/")[1]) if "/" in bp else 0)

    # Heart Rate
    st.plotly_chart(
        go.Figure().add_trace(go.Scatter(
            x=df["timestamp"], y=df["heart_rate"],
            mode="markers", name="Heart Rate (bpm)", marker=dict(color="red")
        )).update_layout(title="💓 Heart Rate", xaxis_title="Time", yaxis_title="BPM"),
        use_container_width=True
    )

    # SpO2
    st.plotly_chart(
        go.Figure().add_trace(go.Scatter(
            x=df["timestamp"], y=df["spo2"],
            mode="markers", name="SpO2 (%)", marker=dict(color="blue")
        )).update_layout(title="🫁 SpO2", xaxis_title="Time", yaxis_title="%"),
        use_container_width=True
    )

    # Temperature
    st.plotly_chart(
        go.Figure().add_trace(go.Scatter(
            x=df["timestamp"], y=df["temperature"],
            mode="markers", name="Temperature (°C)", marker=dict(color="green")
        )).update_layout(title="🌡️ Temperature", xaxis_title="Time", yaxis_title="°C"),
        use_container_width=True
    )

    # Blood Pressure
    fig_bp = go.Figure()
    fig_bp.add_trace(go.Scatter(
        x=df["timestamp"], y=df["systolic"],
        mode="markers", name="Systolic", marker=dict(color="purple")
    ))
    fig_bp.add_trace(go.Scatter(
        x=df["timestamp"], y=df["diastolic"],
        mode="markers", name="Diastolic", marker=dict(color="orange")
    ))
    fig_bp.update_layout(title="🩸 Blood Pressure", xaxis_title="Time", yaxis_title="mmHg")
    st.plotly_chart(fig_bp, use_container_width=True)

# ===============================
# Sidebar Navigation
# ===============================
st.sidebar.title("🏥 Navigation")

page = st.sidebar.selectbox(
    "Choose a page:",
    [
        "🏠 Dashboard",
        "🫀 Live Vitals",
        "🚨 Alerts",
        "👤 Patient Details",
        "📊 Analytics",
        "⚙️ System Status",
    ],
)

if st.sidebar.button("🔄 Refresh Now"):
    st.cache_data.clear()
    st.rerun()

if st.sidebar.button("🧹 Clear Cache"):
    st.cache_data.clear()
    st.rerun()

# ===============================
# Display Patient Card
# ===============================
def display_patient_vitals_card(patient_data, vitals):
    with st.container():
        col1, col2 = st.columns([1, 2])

        with col1:
            st.subheader(f"👤 {patient_data.get('name', 'Unknown')}")
            st.write(f"**ID:** {patient_data['patient_id']}")
            st.write(f"**Age:** {patient_data.get('age', 'N/A')}")
            st.write(f"**Condition:** {patient_data.get('condition', 'N/A')}")
            st.write(f"**Gender:** {patient_data.get('gender', 'N/A')}")
            st.write(f"**Email:** {patient_data.get('email', 'N/A')}")

        with col2:
            if vitals:
                col2a, col2b, col2c, col2d = st.columns(4)

                hr = vitals.get("heart_rate", 0)
                spo2 = vitals.get("oxygen_saturation", 0)
                temp = vitals.get("temperature_celsius", 0)
                bp = vitals.get("blood_pressure", "N/A")

                hr_status = "🟢" if 60 <= hr <= 120 else "🔴"
                spo2_status = "🟢" if spo2 >= 95 else "🔴"
                temp_status = "🟢" if 36.0 <= temp <= 37.5 else "🔴"

                with col2a:
                    st.metric("💓 Heart Rate", f"{hr} bpm", hr_status)
                with col2b:
                    st.metric("🫁 SpO2", f"{spo2}%", spo2_status)
                with col2c:
                    st.metric("🌡️ Temperature", f"{temp}°C", temp_status)
                with col2d:
                    st.metric("🩸 Blood Pressure", bp, "🟢")

            else:
                st.warning("⚠️ No vitals data available")

# ===============================
# Vitals Chart
# ===============================
def create_vitals_chart(patient_id, limit=20):
    history = get_vitals_history(patient_id, limit)

    if not history:
        st.warning("No historical data available")
        return

    df_data = []
    for record in history:
        timestamp = record.get("timestamp", datetime.now().isoformat())
        df_data.append({
            "timestamp": pd.to_datetime(timestamp),
            "heart_rate": record.get("heart_rate", 0),
            "spo2": record.get("spo2", 0),
            "temperature": record.get("temperature", 0),
        })

    df = pd.DataFrame(df_data)

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["timestamp"],
        y=df["heart_rate"],
        mode="lines+markers",
        name="Heart Rate (bpm)",
        line=dict(color="red"),
    ))
    fig.add_trace(go.Scatter(
        x=df["timestamp"],
        y=df["spo2"],
        mode="lines+markers",
        name="SpO2 (%)",
        line=dict(color="blue"),
        yaxis="y2",
    ))
    fig.add_trace(go.Scatter(
        x=df["timestamp"],
        y=df["temperature"],
        mode="lines+markers",
        name="Temperature (°C)",
        line=dict(color="green"),
        yaxis="y3",
    ))

    fig.update_layout(
        title=f"Vitals History - Patient {patient_id}",
        xaxis_title="Time",
        yaxis=dict(title="Heart Rate (bpm)", side="left"),
        yaxis2=dict(
            title="SpO2 (%)",
            side="right",
            overlaying="y",
            anchor="x",
        ),
        yaxis3=dict(
            title="Temperature (°C)",
            side="right",
            overlaying="y",
            position=0.85,
        ),
        height=400,
    )

    st.plotly_chart(fig, use_container_width=True)

# ===============================
# Pages
# ===============================
if page == "🏠 Dashboard":
    st.title("🏥 Real-Time Patient Monitoring Dashboard")

    show_simulation_controls()

    st.markdown("---")

    status = get_system_status()

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("MongoDB", status["MongoDB"])
    col2.metric("S3 Storage", status["S3"])
    col3.metric("Kinesis", status["Kinesis"])
    col4.metric("Simulation", status["Simulation"])

    st.markdown("---")

    # Fetch active patients
    patients = fetch_active_patients()

    # Fetch ALL active alerts from MongoDB
    alerts_all = get_active_alerts()

    # Filter to only alerts that:
    # - have an S3 key under llm-analyses/
    # - and the analysis file actually exists in S3
    valid_alerts = []
    for alert in alerts_all:
        s3_key = alert.get("s3_analysis_location", "")
        if s3_key and s3_key.startswith("llm-analyses/"):
            analysis = fetch_llm_analysis(s3_key, quiet=True)
            if analysis:
                valid_alerts.append(alert)

    col1, col2, col3 = st.columns(3)
    col1.metric("👥 Active Patients", len(patients))
    col2.metric("🚨 Active Alerts", len(valid_alerts))

    critical = [a for a in valid_alerts if a.get("severity") == "critical"]
    col3.metric("⚠️ Critical Alerts", len(critical))

    if patients:
        st.success(f"✅ System monitoring {len(patients)} active patients.")
    else:
        st.warning("⚠️ No active patients found. Check MongoDB data.")


elif page == "🫀 Live Vitals":
    st.title("🫀 Live Patient Vitals")
    st_autorefresh(interval=DASHBOARD_REFRESH_SEC * 1000, key="live_vitals_refresh")
    patients = fetch_active_patients()

    if not patients:
        st.warning("⚠️ No active patients found")
    else:
        for patient in patients:
            pid = patient["patient_id"]
            static_profile = get_static_profile(pid)
            vitals_s3 = get_latest_vitals_from_s3(pid, limit=1)


            live_vitals = vitals_s3[0] if vitals_s3 else {}


            with st.expander(f"👤 Patient {pid} - {static_profile.get('name', 'Unknown') if static_profile else 'Unknown'}", expanded=True):
                if static_profile and live_vitals:
                    display_patient_vitals_card(static_profile, live_vitals)

                    if st.button(f"📈 Show History", key=f"chart_{pid}"):
                        create_live_scatter_plots(pid)
                else:
                    st.error("❌ No Live Vitals Data Available for Patient " + pid)

elif page == "🚨 Alerts":
    st.title("🚨 Patient Alerts")

    # Load ALL active alerts from Mongo
    alerts_all = get_active_alerts()

    # Filter to only alerts that:
    # - have an S3 key under llm-analyses/
    # - and the analysis file actually exists
    valid_alerts = []
    for alert in alerts_all:
        s3_key = alert.get("s3_analysis_location", "")
        if s3_key and s3_key.startswith("llm-analyses/"):
            analysis = fetch_llm_analysis(s3_key, quiet=True)
            if analysis:
                alert["llm_analysis"] = analysis
                valid_alerts.append(alert)

    # Show filtered alerts
    if not valid_alerts:
        st.success("✅ No active alerts requiring attention.")
    else:
        st.warning(f"⚠️ {len(valid_alerts)} active alerts require attention")

        for alert in valid_alerts:
            severity = alert.get("severity", "medium")
            severity_color = {
                "low": "🟡",
                "medium": "🟠",
                "high": "🔴",
                "critical": "🚨",
            }

            with st.expander(
                f"{severity_color.get(severity, '⚠️')} Alert - Patient {alert['patient_id']}",
                expanded=severity in ["high", "critical"],
            ):
                col1, col2 = st.columns([2, 1])

                with col1:
                    st.write(f"**Severity:** {severity.upper()}")
                    if alert.get("created_at"):
                        st.write(f"**Generated:** {alert['created_at']}")
                    if alert.get("message"):
                        st.write(f"**Message:** {alert['message']}")

                    # Load analysis already fetched above
                    analysis = alert.get("llm_analysis")
                    vitals_combined = {}

                    if analysis:
                        # Extract vitals from analysis inputs
                        raw_vitals = analysis.get("inputs", {}).get("vitals", {}).get("vitals", [])
                        structured_vitals = {}
                        if isinstance(raw_vitals, list) and len(raw_vitals) >= 8:
                            try:
                                structured_vitals = {
                                    "Blood Pressure": raw_vitals[1],
                                    "Heart Rate (bpm)": raw_vitals[2],
                                    "SpO2 (%)": raw_vitals[3],
                                    "Patient ID": raw_vitals[4],
                                    "Patient Name": raw_vitals[5],
                                    "Temperature (°C)": raw_vitals[6],
                                    "Timestamp": raw_vitals[7]
                                }
                            except Exception:
                                pass

                        analysis_vitals = analysis.get("inputs", {}).get("vitals", {}).get("vitals_snapshot", {})
                        vitals_combined.update(analysis_vitals)
                        vitals_combined.update(structured_vitals)

                    # Merge with alert vitals if available
                    vitals_combined.update(alert.get("vitals", {}))

                    if vitals_combined:
                        st.markdown("### 🫀 Current Vitals Analyzed")
                        df_vitals = pd.DataFrame(
                            [(k, str(v)) for k, v in vitals_combined.items()],
                            columns=["Metric", "Value"]
                        )
                        st.table(df_vitals)

                    # Show analysis outputs
                    if analysis:
                        outputs = analysis.get("outputs", {})
                        if outputs.get("clinical_impression"):
                            st.markdown("### 🧠 Clinical Impression")
                            st.write(outputs["clinical_impression"])

                        if outputs.get("risk_assessment"):
                            st.markdown("### 🚨 Risk Assessment")
                            st.write(outputs["risk_assessment"])

                        if outputs.get("differential_diagnosis"):
                            st.markdown("### 🧾 Differential Diagnosis")
                            for dx in outputs["differential_diagnosis"]:
                                st.markdown(f"- {dx}")

                        if outputs.get("immediate_actions"):
                            st.markdown("### ⚡ Immediate Actions")
                            for act in outputs["immediate_actions"]:
                                st.markdown(f"- {act}")

                        if outputs.get("monitoring_recommendations"):
                            st.markdown("### ⏱️ Monitoring Recommendations")
                            for rec in outputs["monitoring_recommendations"]:
                                st.markdown(f"- {rec}")

                        if outputs.get("follow_up_suggestions"):
                            st.markdown("### 📅 Follow-Up Suggestions")
                            for rec in outputs["follow_up_suggestions"]:
                                st.markdown(f"- {rec}")

                        if outputs.get("medication_considerations"):
                            st.markdown("### 💊 Medication Considerations")
                            for med in outputs["medication_considerations"]:
                                st.markdown(f"- {med}")
                    else:
                        st.info("🤖 LLM analysis not available")

                with col2:
                    unique_alert_id = f"{alert.get('patient_id')}_{alert.get('s3_analysis_location', '')}"
                    if st.button("✅ Resolve", key=f"resolve_{unique_alert_id}"):
                        # Safely resolve alert
                        success = resolve_alert(alert["patient_id"], alert.get("s3_analysis_location", ""))
                        if success:
                            st.success("Alert resolved and analysis deleted from S3.")
                            st.rerun()
                        else:
                            st.error("Failed to resolve alert. Possibly already resolved or missing in DB.")



elif page == "👤 Patient Details":
    st.title("👤 Patient Details")

    patients = fetch_active_patients()

    if not patients:
        st.warning("No active patients found")
    else:
        patient_ids = [p["patient_id"] for p in patients]
        selected_patient = st.selectbox("Select a patient:", patient_ids)

        if selected_patient:
            static_profile = get_static_profile(selected_patient)
            live_vitals = get_live_vitals(selected_patient)

            if static_profile:
                col1, col2 = st.columns([1, 1])

                with col1:
                    st.subheader("📋 Basic Information")
                    basic_info = {
                        "Patient ID": static_profile.get("patient_id"),
                        "Name": static_profile.get("name"),
                        "Gender": static_profile.get("gender"),
                        "DOB": static_profile.get("dob"),
                        "Age": static_profile.get("age")
                    }
                    st.table(pd.DataFrame(
                        [(k, str(v)) for k, v in basic_info.items()],
                        columns=["Field", "Value"]
                    ))

                    st.subheader("📞 Contact Information")
                    address = static_profile.get("address", {})
                    formatted_address = (
                        f"{address.get('street', '')}\n"
                        f"{address.get('city', '')}, {address.get('state', '')}\n"
                        f"{address.get('country', '')} - {address.get('pincode', '')}"
                        if address else "N/A"
                    )
                    contact_info = {
                        "Email": static_profile.get("email"),
                        "Phone": static_profile.get("phone"),
                        "Address": formatted_address
                    }
                    st.table(pd.DataFrame(
                        [(k, str(v)) for k, v in contact_info.items()],
                        columns=["Field", "Value"]
                    ))

                    st.subheader("🚨 Emergency Contact")
                    emergency = static_profile.get("emergency_contact", {})
                    emergency_info = {
                        "Name": emergency.get("name", "N/A"),
                        "Relation": emergency.get("relation", "N/A"),
                        "Phone": emergency.get("phone", "N/A")
                    }
                    st.table(pd.DataFrame(
                        [(k, str(v)) for k, v in emergency_info.items()],
                        columns=["Field", "Value"]
                    ))

                    st.subheader("⚙️ Account Details")
                    login = static_profile.get("login_", {})
                    account_info = {
                        "Active": static_profile.get("is_active"),
                        "Created At": static_profile.get("created_at"),
                        "Last Updated": static_profile.get("last_updated"),
                        "Username": login.get("username", "N/A")
                    }
                    st.table(pd.DataFrame(
                        [(k, str(v)) for k, v in account_info.items()],
                        columns=["Field", "Value"]
                    ))

                with col2:
                    st.subheader("🫀 Current Vitals")

                    if live_vitals:
                        df_vitals = pd.DataFrame(
                            [(k, str(v)) for k, v in live_vitals.items()],
                            columns=["Metric", "Value"]
                        )
                        st.table(df_vitals)
                    else:
                        st.warning("No current vitals available")

                history = static_profile.get("vitals_history", [])
                if history:
                    st.subheader("📈 Vitals History (Last Records)")
                    flat_records = []
                    for rec in history:
                        flat = {}
                        for k, v in rec.items():
                            if isinstance(v, dict):
                                for subk, subv in v.items():
                                    flat[f"{k}.{subk}"] = str(subv)
                            elif isinstance(v, list):
                                flat[k] = "; ".join(str(item) for item in v)
                            else:
                                flat[k] = str(v)
                        flat_records.append(flat)

                    if flat_records:
                        df = pd.DataFrame(flat_records)
                        st.dataframe(df, use_container_width=True)
                    else:
                        st.write("No data available.")
                else:
                    st.info("No vitals history found.")

            else:
                st.error("Patient profile not found")

elif page == "📊 Analytics":
    st.title("📊 System Analytics")

    option = st.selectbox(
        "Choose data to view:",
        ["Logs", "Patient Alerts Summary", "Vitals Fluctuations"]
    )

    if option == "Logs":
        logs = get_logs()
        st.subheader("📚 System Logs")
        if logs:
            for log in logs:
                st.code(
                    f"{log.get('timestamp')} [{log.get('level')}] {log.get('function')} → {log.get('message')}",
                    language="log",
                )
        else:
            st.info("No logs found.")

    elif option == "Patient Alerts Summary":

        # ✅ Load alerts directly from S3
        alerts = get_patient_alerts_from_s3()

        st.subheader("🚨 Alert Types Summary")

        alert_counts = {}

        for alert in alerts:
            flags = alert.get("flags", [])
            for flag in flags:
                alert_counts[flag] = alert_counts.get(flag, 0) + 1

        if not alert_counts:
            st.info("No alert flags found in patient records.")
        else:
            df = pd.DataFrame(
                sorted(alert_counts.items(), key=lambda x: x[1], reverse=True),
                columns=["Alert Type", "Count"]
            )
            st.bar_chart(df.set_index("Alert Type"))

            st.subheader("Detailed Patient Alerts")

            for alert in alerts:
                patient_id = alert.get("patient_id", "Unknown")
                timestamp = alert.get("timestamp", "N/A")
                flags = alert.get("flags", [])
                vitals = alert.get("vitals", {})

                st.markdown(f"### 👤 Patient {patient_id}")
                st.markdown(f"**Timestamp:** {timestamp}")
                st.markdown(f"**Flags:** {', '.join(flags) if flags else 'None'}")

                if vitals:
                    st.markdown("#### 🫀 Vitals")
                    # Strip out internal metadata keys if present
                    vitals_clean = {
                        k: v for k, v in vitals.items()
                        if not k.startswith("_") and k != "_processing_metadata"
                    }
                    if vitals_clean:
                        vitals_df = pd.DataFrame(
                            list(vitals_clean.items()),
                            columns=["Metric", "Value"]
                        )
                        st.table(vitals_df)

                st.markdown("---")

    
    # elif option == "Patient Alerts Summary":
    #     patients = get_alert_patients()
    #     st.subheader("🚨 Alert Types Summary")

    #     alert_counts = {}

    #     for patient in patients:
    #         # Correct: extract flags from current_vitals.flags
    #         flags = []
    #         cv = patient.get("current_vitals", {})
    #         if cv:
    #             flags = cv.get("flags", [])

    #         for flag in flags:
    #             alert_counts[flag] = alert_counts.get(flag, 0) + 1

    #     if not alert_counts:
    #         st.info("No alert flags found in patient records.")
    #     else:
    #         df = pd.DataFrame(
    #             sorted(alert_counts.items(), key=lambda x: x[1], reverse=True),
    #             columns=["Alert Type", "Count"]
    #         )
    #         st.bar_chart(df.set_index("Alert Type"))

    #         st.subheader("Detailed Patient Alerts")
    #         for patient in patients:
    #             st.markdown(f"### 👤 Patient {patient.get('patient_id')}")

    #             # Show extracted flags
    #             flags = []
    #             cv = patient.get("current_vitals", {})
    #             if cv:
    #                 flags = cv.get("flags", [])

    #             st.markdown(f"**Flags:** {', '.join(flags) if flags else 'None'}")

    #             # Show vitals
    #             vitals = patient.get("vitals", {})
    #             if vitals:
    #                 st.markdown("#### 🫀 Vitals")
    #                 vitals_df = pd.DataFrame(
    #                     [(k, str(v)) for k, v in vitals.items()],
    #                     columns=["Metric", "Value"]
    #                 )
    #                 st.table(vitals_df)

    #             vitals_history = patient.get("vitals_history", [])
    #             if vitals_history:
    #                 st.markdown("#### 📈 Vitals History")
    #                 df_history = pd.DataFrame(vitals_history)
    #                 st.dataframe(df_history, use_container_width=True)

    #             analyses = patient.get("llm_analysis_history", [])
    #             if not analyses:
    #                 st.write("No analyses found.")
    #             for entry in analyses:
    #                 timestamp = entry.get("timestamp")
    #                 flags_entry = entry.get("flags", [])
    #                 analysis = entry.get("analysis", {})
    #                 st.markdown(f"**Timestamp:** {timestamp}")
    #                 st.markdown(f"**Flags in this analysis:** {', '.join(flags_entry) if flags_entry else 'None'}")
    #                 if analysis:
    #                     st.markdown("#### 🧠 Clinical Impression")
    #                     st.write(analysis.get("clinical_impression", "N/A"))

    #                     st.markdown("#### 🚨 Risk Assessment")
    #                     st.write(analysis.get("risk_assessment", "N/A"))

    #                     st.markdown("#### 🧾 Differential Diagnosis")
    #                     for dx in analysis.get("differential_diagnosis", []):
    #                         st.markdown(f"- {dx}")

    #                     st.markdown("#### ⚡ Immediate Actions")
    #                     for act in analysis.get("immediate_actions", []):
    #                         st.markdown(f"- {act}")

    #                     st.markdown("#### ⏱️ Monitoring Recommendations")
    #                     for rec in analysis.get("monitoring_recommendations", []):
    #                         st.markdown(f"- {rec}")

    #                     st.markdown("#### 📅 Follow-Up Suggestions")
    #                     for rec in analysis.get("follow_up_suggestions", []):
    #                         st.markdown(f"- {rec}")

    #                     st.markdown("#### 💊 Medication Considerations")
    #                     for med in analysis.get("medication_considerations", []):
    #                         st.markdown(f"- {med}")

    #                     st.markdown("---")




    elif option == "Vitals Fluctuations":
        records = get_vitals_fluctuations()
        st.subheader("📈 Vitals History Sample (Latest)")
        if records:
            for record in records:
                pid = record.get("patient_id")
                vitals = record.get("vitals_history", [])
                st.markdown(f"### 👤 Patient {pid}")
                
                flat_records = []
                for rec in vitals:
                    flat = {}
                    for k, v in rec.items():
                        if isinstance(v, dict):
                            for subk, subv in v.items():
                                flat[f"{k}.{subk}"] = str(subv)
                        elif isinstance(v, list):
                            flat[k] = "; ".join(str(item) for item in v)
                        else:
                            flat[k] = str(v)
                    flat_records.append(flat)

                if flat_records:
                    df = pd.DataFrame(flat_records)
                    st.dataframe(df, use_container_width=True)
                else:
                    st.write("No data available.")
        else:
            st.info("No vitals history found.")

elif page == "⚙️ System Status":
    st.title("⚙️ System Status")

    status = get_system_status()

    st.subheader("🔧 Service Status")
    for service, status_text in status.items():
        if "🟢" in status_text:
            st.success(f"{service}: {status_text}")
        else:
            st.error(f"{service}: {status_text}")

    st.subheader("📊 System Metrics")

    patients = fetch_active_patients()
    alerts = get_active_alerts()

    col1, col2, col3 = st.columns(3)
    col1.metric("Active Patients", len(patients))
    col2.metric("Pending Alerts", len(alerts))
    col3.metric(
        "Simulation Status",
        "Running" if st.session_state.get("sim_started", False) else "Stopped",
    )

    if st.button("🔄 Restart Simulation"):
        success = maybe_start_simulation()
        if success:
            set_simulation_running(True)
            st.session_state.sim_started = is_simulation_running()
            st.success("Simulation restarted successfully!")
        else:
            st.error("Failed to restart simulation")

# Footer
st.markdown("---")
st.markdown(
    """
<div style='text-align: center; color: #666;'>
    Healthcare Monitoring System v1.0 | Built with Streamlit, MongoDB, AWS
</div>
""",
    unsafe_allow_html=True,
)

log_event("INFO", "app.py", f"Page accessed: {page}")
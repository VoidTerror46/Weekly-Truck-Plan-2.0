
import io
import math
from datetime import datetime, timedelta
import numpy as np
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Truck Planning Dashboard", layout="wide")

st.title("🚚 Truck Planning Dashboard (RO32 ➜ RO33)")

with st.sidebar:
    st.header("1) Upload & Settings")
    up = st.file_uploader("Upload the weekly RRP4 Excel (.xlsx)", type=["xlsx"])
    sheet_name = st.text_input("Sheet name", value="RRP 4")
    status_col_input = st.text_input("Status column (name / Excel letter / index)", value="D")
    pallets_col = st.text_input("Pallets column name", value="Pallets")
    lane_col_pref = st.selectbox("Preferred lane/grouping column", ["Deliver To Move 1","Deliver To Move 2","Deliver To","CIG Lane","Destination","Route"], index=0)
    load_day = st.number_input("Load Day offset (production: RO32 ➜ RO33)", min_value=0, max_value=30, value=4)
    snapshot_fallback_date = st.date_input("Stock snapshot date (fallback)", value=datetime.today().date())
    default_ppt = st.number_input("Default pallets per truck (fallback)", min_value=1, max_value=100, value=33)

st.markdown("Stock = same-day. Production = date + LoadDay. Transit = next day. Inspection = excluded. Full-truck logic applies.")

def resolve_col(df, col_ref):
    try:
        idx = int(col_ref)
        return df.columns[idx]
    except:
        pass
    if isinstance(col_ref, str) and col_ref.isalpha():
        letters = col_ref.upper()
        idx = 0
        for ch in letters:
            idx = idx * 26 + (ord(ch) - ord('A') + 1)
        idx -= 1
        if 0 <= idx < len(df.columns):
            return df.columns[idx]
    if col_ref in df.columns:
        return col_ref
    ci = {str(c).lower(): c for c in df.columns}
    return ci.get(str(col_ref).lower())

def choose_lane_column(df, pref):
    cand = [pref] + [c for c in df.columns if str(c).strip().lower() in {"deliver to move 1","deliver to","destination","route","lane"}]
    for c in cand:
        if c in df.columns:
            return c
    txt = [c for c in df.columns if df[c].dtype == object]
    return txt[0] if txt else df.columns[0]

DEFAULT_PPT = {"Ploiesti-BAY (N) DE06": 26, "Ploiesti-BAY (E) DE30": 33, "Ploiesti-Belgrade": 26, "Ploiesti-Boncourt": 33, "Ploiesti-Bornem": 33, "Ploiesti-Bratislava": 26, "Ploiesti-Dabrowa Gornicza": 26, "Ploiesti-Dublin": 26, "Ploiesti-Dunaharaszti": 33, "Ploiesti-Horsens": 33, "Ploiesti-Kanfanar": 26, "Ploiesti-Nupaky": 33, "Ploiesti-Perama": 26, "Ploiesti-GTR - Poznan": 33, "Ploiesti-Poznan": 33, "Ploiesti-Pristina": 28, "Ploiesti-Rotherham": 26, "Ploiesti-RIGA": 33, "Ploiesti-Sarajevo": 26, "Ploiesti-Sofia": 26, "Ploiesti-Southampton": 33, "Ploiesti-Tallinn": 33, "Ploiesti-Teresin": 26, "Ploiesti-Tirana": 26, "Ploiesti-Vestby": 33, "Ploiesti-Vilnius": 33, "Ploiesti-Italy": 26, "Ploiesti-Spain": 26}

@st.cache_data(show_spinner=False)
def compute_trucks(file_bytes, sheet, status_col_ref, pallets_col_name, lane_pref, load_day, snapshot_date, default_ppt_global):
    df = pd.read_excel(io.BytesIO(file_bytes), sheet_name=sheet, engine='openpyxl')
    status_col = resolve_col(df, status_col_ref)
    if pallets_col_name not in df.columns:
        ci = {str(c).lower(): c for c in df.columns}
        pallets_col = ci.get(pallets_col_name.lower())
    else:
        pallets_col = pallets_col_name
    lane_col = choose_lane_column(df, lane_pref)

    # Detect report run date
    report_run_date = pd.NaT
    scan = df.iloc[:20, :10]
    mask = scan.astype(str).applymap(lambda x: x.strip() == "Report Run Date")
    if mask.any().any():
        r, c = np.argwhere(mask.values)[0]
        report_run_date = pd.to_datetime(df.iloc[r, c+1], errors='coerce')
    if pd.isna(report_run_date):
        report_run_date = pd.Timestamp(snapshot_date)

    tmp = df[[lane_col, status_col, pallets_col]].copy()
    tmp.columns = ['lane', 'status', 'pallets']
    tmp['pallets'] = pd.to_numeric(tmp['pallets'], errors='coerce').fillna(0.0)
    tmp['status_str'] = tmp['status'].astype(str).str.lower().str.strip()

    def classify(row):
        s = row['status']
        s_str = row['status_str']
        dt = pd.to_datetime(s, errors='coerce')
        if not pd.isna(dt):
            return 'production', dt.normalize()
        if 'inspection' in s_str:
            return 'inspection', pd.NaT
        if 'transit' in s_str:
            return 'transit', report_run_date
        if s_str == 'stock':
            return 'stock', report_run_date
        return 'other', pd.NaT

    cls = tmp.apply(classify, axis=1, result_type='expand')
    tmp[['kind', 'date']] = cls

    stock_on_hand = tmp[tmp['kind'] == 'stock'].groupby(['lane', 'date'], as_index=False)['pallets'].sum()
    prod = tmp[tmp['kind'] == 'production'].copy()
    prod['avail_date'] = prod['date'] + pd.to_timedelta(load_day, unit='D')
    prod_on_day = prod.groupby(['lane', 'avail_date'], as_index=False)['pallets'].sum().rename(columns={'avail_date': 'date'})

    transit = tmp[tmp['kind'] == 'transit'].copy()
    transit['avail_date'] = transit['date'] + pd.to_timedelta(1, unit='D')
    transit_on_day = transit.groupby(['lane', 'avail_date'], as_index=False)['pallets'].sum().rename(columns={'avail_date': 'date'})

    all_avail = pd.concat([stock_on_hand, prod_on_day, transit_on_day], ignore_index=True)
    if all_avail.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    per_lane = []
    for lane, grp in all_avail.groupby('lane'):
        grp = grp.sort_values('date')
        days = pd.date_range(grp['date'].min(), grp['date'].max(), freq='D')
        s = pd.Series(0.0, index=days)
        for _, r in grp.iterrows():
            s[r['date']] += r['pallets']
        cum = s.cumsum()
        ppt = DEFAULT_PPT.get(lane, default_ppt_global)
        full = (cum // ppt).astype(int)
        trucks = full.diff().fillna(full).clip(lower=0).astype(int)
        out = pd.DataFrame({'Destination': lane, 'Date': days.date, 'AvailablePallets_RO33': s.values, 'CumulativePallets': cum.values, 'PalletsPerTruck': ppt, 'Trucks': trucks.values})
        per_lane.append(out)

    daily = pd.concat(per_lane, ignore_index=True)
    daily['WeekIndex'] = ((pd.to_datetime(daily['Date']) - pd.to_datetime(daily['Date']).min()).dt.days // 7) + 1

    weekly = daily.groupby(['Destination', 'WeekIndex', 'PalletsPerTruck'], as_index=False).agg(AvailablePallets_RO33=('AvailablePallets_RO33', 'sum'), CumulativePallets=('CumulativePallets', 'max'), Trucks=('Trucks', 'sum'))

    master_df = pd.DataFrame({'Destination': sorted(daily['Destination'].unique()), 'PalletsPerTruck': [DEFAULT_PPT.get(d, default_ppt_global) for d in sorted(daily['Destination'].unique())]})

    return daily, weekly, master_df

if up is not None:
    try:
        daily_df, weekly_df, master_df = compute_trucks(up.read(), sheet_name, status_col_input, pallets_col, lane_col_pref, int(load_day), snapshot_fallback_date, int(default_ppt))
        if daily_df.empty:
            st.warning("No valid rows found.")
        else:
            st.success("Processed successfully!")
            st.subheader("Daily Trucks")
            st.dataframe(daily_df, use_container_width=True)
            st.subheader("Weekly Trucks")
            st.dataframe(weekly_df, use_container_width=True)
            st.subheader("MasterData (Pallets Per Truck)")
            edited_master = st.data_editor(master_df, use_container_width=True)

            def export_excel(daily, weekly, master):
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as w:
                    daily.to_excel(w, 'Daily', index=False)
                    weekly.to_excel(w, 'Weekly', index=False)
                    master.to_excel(w, 'MasterData', index=False)
                output.seek(0)
                return output

            dl = export_excel(daily_df, weekly_df, edited_master)
            st.download_button("⬇️ Download Excel", data=dl, file_name="TruckPlan_Daily_Weekly_Master.xlsx")
    except Exception as e:
        st.error(f"Error: {e}")
else:
    st.info("Upload your RRP4 Excel to begin.")

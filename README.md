# Truck Planning Dashboard (RO32 → RO33)

This app calculates trucks per day per lane from a single RRP4 Excel upload.

## Deployment (Streamlit Cloud)
1. Upload these files to GitHub:
   - `app.py`
   - `requirements.txt`
   - `README.md`
   - `.streamlit/runtime.txt`
2. Go to https://share.streamlit.io
3. Deploy → choose repo → select `app.py` entrypoint
4. Done

## Local run
```
pip install -r requirements.txt
streamlit run app.py
```

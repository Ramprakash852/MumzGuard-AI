import streamlit as st
import requests
import json

API_URL = "http://127.0.0.1:8000"
PRODUCTS_TIMEOUT_SECONDS = 10
ANALYZE_TIMEOUT_SECONDS = 180

st.set_page_config(
    page_title="MumzGuard — Return Risk Intelligence",
    page_icon="🛡️",
    layout="wide"
)

st.title("🛡️ MumzGuard")
st.caption("Return Risk Intelligence for Mumzworld")

# --- Sidebar: Product selector ---
st.sidebar.header("Product Configuration")

# Load products from API
@st.cache_data(ttl=60)
def load_products():
    try:
        r = requests.get(f"{API_URL}/products", timeout=PRODUCTS_TIMEOUT_SECONDS)
        return r.json()["products"]
    except Exception:
        return []

products = load_products()
product_options = {f"{p['title_en']} ({p['product_id']})": p for p in products}

selected_label = st.sidebar.selectbox("Select product", list(product_options.keys()))
selected_product = product_options[selected_label]

# --- Sidebar: User context ---
st.sidebar.header("User Context")
child_age = st.sidebar.slider("Child age (months)", 0, 144, 8)
vehicle_model = st.sidebar.text_input("Vehicle model (optional)", placeholder="Toyota Corolla 2021")
has_dairy_allergy = st.sidebar.checkbox("Dairy allergy")
language = st.sidebar.radio("Language", ["en", "ar"])

# --- Main panel ---
col1, col2 = st.columns([1, 1])

with col1:
    st.subheader("Product Details")
    st.markdown(f"**{selected_product['title_en']}**")
    if selected_product.get('title_ar'):
        st.markdown(f"*{selected_product['title_ar']}*")
    
    st.markdown(f"**Category:** {selected_product['category']}")
    st.markdown(f"**Brand:** {selected_product.get('brand', 'Unknown')}")
    st.markdown(f"**Age range:** {selected_product['age_range']['min_months']}–{selected_product['age_range']['max_months']} months")
    st.markdown(f"**Price:** AED {selected_product.get('price_aed', 'N/A')}")
    
    if st.button("Analyze Return Risk", type="primary", use_container_width=True):
        with st.spinner("Analyzing..."):
            payload = {
                "product_id": selected_product["product_id"],
                "product_title_en": selected_product["title_en"],
                "product_title_ar": selected_product.get("title_ar"),
                "category": selected_product["category"],
                "brand": selected_product.get("brand"),
                "child_age_months": child_age,
                "vehicle_model": vehicle_model or None,
                "has_allergies": ["dairy"] if has_dairy_allergy else [],
                "language_preference": language
            }
            
            try:
                response = requests.post(
                    f"{API_URL}/analyze",
                    json=payload,
                    timeout=ANALYZE_TIMEOUT_SECONDS,
                )
                if response.status_code == 200:
                    st.session_state["result"] = response.json()
                    st.session_state["error"] = None
                else:
                    st.session_state["error"] = response.json()
                    st.session_state["result"] = None
            except requests.exceptions.ReadTimeout:
                st.session_state["error"] = (
                    f"Request timed out after {ANALYZE_TIMEOUT_SECONDS}s. "
                    "The backend is still processing the analysis; try again in a moment."
                )
                st.session_state["result"] = None
            except Exception as e:
                st.session_state["error"] = str(e)
                st.session_state["result"] = None

with col2:
    st.subheader("Risk Assessment")
    
    if "result" in st.session_state and st.session_state["result"]:
        result = st.session_state["result"]
        
        # Risk badge
        risk = result["risk_level"]
        score = result["risk_score"]
        confidence = result["confidence"]
        
        color = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢", "INSUFFICIENT_DATA": "⚫"}
        st.markdown(f"## {color.get(risk, '⚫')} {risk}")
        
        col_a, col_b = st.columns(2)
        with col_a:
            st.metric("Risk Score", f"{score:.2f}")
        with col_b:
            st.metric("Confidence", f"{confidence:.2f}")
        
        st.divider()
        
        # Reason
        st.markdown("**Why:**")
        st.info(result["risk_reason_en"])
        
        if result.get("risk_reason_ar"):
            st.markdown("**السبب:**")
            st.info(result["risk_reason_ar"])
        
        # Intervention
        if result.get("intervention_en"):
            st.markdown("**Suggested action:**")
            st.warning(result["intervention_en"])
        
        if result.get("intervention_ar"):
            st.markdown("**الإجراء المقترح:**")
            st.warning(result["intervention_ar"])
        
        # Evidence sources
        if result.get("evidence_sources"):
            with st.expander("Evidence sources"):
                for src in result["evidence_sources"]:
                    st.code(src)
        
        # Raw JSON inspector
        with st.expander("Raw JSON output"):
            st.json(result)
    
    elif "error" in st.session_state and st.session_state["error"]:
        st.error(f"Analysis failed: {st.session_state['error']}")
    else:
        st.info("Select a product and click 'Analyze Return Risk'")
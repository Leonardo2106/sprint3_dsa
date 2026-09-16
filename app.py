from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st


DATA_PATH = Path(__file__).parent / "data" / "processed" / "segmentos_sp348.csv"
COLORS = {"alta": "#d73027", "media": "#fdae61", "baixa": "#1a9850"}

st.set_page_config(page_title="Vegetação na SP-348", page_icon="🌳", layout="wide")
st.title("Monitoramento de vegetação na SP-348")
st.caption("Prova de conceito • trecho Jundiaí–Campinas • dados OpenStreetMap")

if not DATA_PATH.exists():
    st.error("Dataset não encontrado. Execute `python3 src/pipeline.py` primeiro.")
    st.stop()

data = pd.read_csv(DATA_PATH)
selected = st.sidebar.multiselect(
    "Prioridade de inspeção",
    ["alta", "media", "baixa"],
    default=["alta", "media", "baixa"],
)
limit = st.sidebar.slider("Quantidade máxima no mapa", 50, 1200, 500, 50)
filtered = data[data["prioridade_inspecao"].isin(selected)].nlargest(
    limit, "score_prioridade"
)

col1, col2, col3, col4 = st.columns(4)
col1.metric("Segmentos analisados", f"{len(data):,}".replace(",", "."))
col2.metric("Prioridade alta", int((data["prioridade_inspecao"] == "alta").sum()))
col3.metric("Distância mediana", f"{data['distancia_vegetacao_m'].median():.0f} m")
col4.metric("Comprimento observado", f"{data['comprimento_segmento_m'].sum()/1000:.1f} km")

figure = px.scatter_map(
    filtered,
    lat="latitude",
    lon="longitude",
    color="prioridade_inspecao",
    color_discrete_map=COLORS,
    size="score_prioridade",
    size_max=13,
    hover_name="segmento_id",
    hover_data={
        "score_prioridade": ":.1f",
        "distancia_vegetacao_m": ":.1f",
        "tipo_vegetacao": True,
        "latitude": ":.5f",
        "longitude": ":.5f",
    },
    zoom=9,
    height=620,
)
figure.update_layout(map_style="open-street-map", margin=dict(l=0, r=0, t=0, b=0))
st.plotly_chart(figure, width="stretch")

st.subheader("Fila sugerida de inspeção")
st.dataframe(
    filtered[
        [
            "segmento_id",
            "prioridade_inspecao",
            "score_prioridade",
            "distancia_vegetacao_m",
            "tipo_vegetacao",
            "latitude",
            "longitude",
            "osm_via_id",
        ]
    ],
    width="stretch",
    hide_index=True,
)
st.info(
    "A prioridade é um rótulo heurístico de triagem baseado no mapeamento colaborativo do OSM. "
    "Ela deve ser validada em campo antes de qualquer decisão operacional."
)

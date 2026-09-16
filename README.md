# Monitoramento de vegetação na SP-348

Prova de conceito de Ciência de Dados para priorizar inspeções de vegetação no trecho Jundiaí–Campinas da Rodovia dos Bandeirantes (SP-348).

## Pergunta de Ciência de Dados

**Quais segmentos da SP-348 devem ser inspecionados primeiro por apresentarem vegetação mapeada mais próxima da pista?**

A solução cruza a geometria da rodovia com feições de vegetação do OpenStreetMap (OSM), calcula a distância de cada segmento viário à feição mais próxima e produz um rótulo de prioridade (`alta`, `media` ou `baixa`). O rótulo é uma **heurística transparente para triagem**, e não uma constatação de risco operacional.

## Fonte real e recorte

- Fonte: [OpenStreetMap](https://www.openstreetmap.org/), via [Overpass API](https://wiki.openstreetmap.org/wiki/Overpass_API).
- Licença: [Open Database License (ODbL)](https://www.openstreetmap.org/copyright).
- Rodovia: vias com `ref=SP-348`.
- Vegetação: `natural=wood|scrub|grassland` e `landuse=forest|grass|meadow`.
- Área: caixa geográfica entre Jundiaí e Campinas: `(-23.25, -47.25, -22.82, -46.80)`.

Os dados brutos em `data/raw/` preservam a resposta da API usada na entrega. O pipeline pode reutilizar esse cache ou refazer a coleta com `--refresh`.

## Estrutura

```text
.
├── app.py                              # dashboard Streamlit
├── data/
│   ├── processed/segmentos_sp348.csv     # dataset final rotulado
│   └── raw/*.json.gz                    # respostas reais da Overpass
├── notebooks/monitoramento_vegetacao_sp348.ipynb
├── src/pipeline.py                     # coleta, tratamento e rotulagem
├── metadata/dataset_metadata.json      # rastreabilidade da execução
└── requirements.txt
```

## Como reproduzir

Requer Python 3.10 ou superior.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# reproduz o CSV a partir do cache real incluído
python3 src/pipeline.py

# opcional: consulta novamente a API
python3 src/pipeline.py --refresh

# análise narrativa
jupyter lab notebooks/monitoramento_vegetacao_sp348.ipynb

# interface de exploração
streamlit run app.py
```

O pipeline usa apenas a biblioteca padrão do Python; as demais dependências são para o notebook e o dashboard.

## Critério de rotulagem

O escore de 0 a 100 combina:

- proximidade: até 80 pontos, decrescendo linearmente de 0 a 300 metros;
- tipo mapeado: 20 pontos para `scrub`, 15 para `wood/forest`, 10 para `grassland/meadow` e 5 para `grass`.

Rótulos: `alta` para escore ≥ 70; `media` para escore ≥ 40; `baixa` nos demais casos. O arquivo final mantém `score_prioridade`, `distancia_vegetacao_m`, `tipo_vegetacao` e os identificadores OSM, permitindo auditar cada decisão.

## Decisão apoiada

O resultado serve para ordenar uma fila inicial de inspeção. Segmentos de prioridade alta entram primeiro no planejamento, mas a decisão final precisa considerar vistoria, faixa de domínio, inclinação, histórico de quedas/incêndios, clima, tráfego e espécie/altura da vegetação.

## Limitações e vieses

- O OSM é colaborativo: cobertura, atualização e precisão variam espacialmente.
- A ausência de uma feição não prova ausência de vegetação.
- As tags descrevem cobertura/uso do solo, não altura, saúde, inclinação ou possibilidade de queda.
- Segmentos das duas pistas aparecem separadamente e podem representar o mesmo entorno operacional.
- A distância é calculada em aproximação métrica local; é adequada ao recorte, mas não substitui geoprocessamento geodésico de produção.
- Os rótulos são regras do grupo e ainda não foram validados por especialistas ou ocorrências reais.

## Evolução para escala

1. Validar uma amostra em campo com equipe de conservação e medir concordância entre anotadores.
2. Incorporar imagens recentes e índices de vegetação de satélite, relevo, vento/chuva, queimadas e ocorrências históricas.
3. Trocar a heurística por modelo supervisionado quando existirem rótulos confiáveis, comparando-o com este baseline.
4. Agendar coleta periódica, testes de qualidade e detecção de mudanças.
5. Expandir o corredor por lotes para respeitar os limites das instâncias públicas da Overpass.


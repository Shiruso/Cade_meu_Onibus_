import csv
import json
import math
import os
from datetime import datetime, timedelta
from typing import NamedTuple

import requests
from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEnginePage

API_TIMEOUT = 10
INTERVALO_ATUALIZACAO_MS = 20_000
COR_IDA = "#0284c7"
COR_VOLTA = "#f97316"
COR_PARADA = "#22c55e"
GTFS_DIR = os.path.join(os.path.dirname(__file__), "GTFS RJ")
_cache: dict = {}


class Parada(NamedTuple):
    id: str
    nome: str
    lat: float
    lng: float


def _ler_csv(nome: str) -> list[dict[str, str]]:
    caminho = os.path.join(GTFS_DIR, nome)
    if not os.path.exists(caminho):
        return []
    with open(caminho, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        return [{k: v.strip() for k, v in row.items()} for row in reader]


def _carregar():
    if _cache:
        return
    rotas = {r["route_short_name"]: r["route_id"] for r in _ler_csv("routes.txt")}
    _cache["rotas"] = rotas
    paradas = {}
    for s in _ler_csv("stops.txt"):
        sid = s["stop_id"]
        paradas[sid] = Parada(
            id=sid,
            nome=s.get("stop_name", "Parada"),
            lat=float(s["stop_lat"]),
            lng=float(s["stop_lon"]),
        )
    _cache["paradas"] = paradas
    viagens: dict[str, list[dict]] = {}
    for t in _ler_csv("trips.txt"):
        rid = t["route_id"]
        lista = viagens.setdefault(rid, [])
        did = int(t["direction_id"])
        if any(v["direction_id"] == did for v in lista):
            continue
        lista.append({
            "trip_id": t["trip_id"],
            "direction_id": did,
            "shape_id": t["shape_id"],
            "headsign": t["trip_headsign"],
        })
    _cache["viagens"] = viagens
    trip_ids_necessarios = {
        v["trip_id"]
        for lista in viagens.values()
        for v in lista
    }
    stop_times_raw: dict[str, list[tuple[int, str]]] = {}
    for st in _ler_csv("stop_times.txt"):
        tid = st["trip_id"]
        if tid not in trip_ids_necessarios:
            continue
        seq = int(st["stop_sequence"])
        stop_times_raw.setdefault(tid, []).append((seq, st["stop_id"]))
    stop_times: dict[str, list[str]] = {}
    for tid, pontos in stop_times_raw.items():
        pontos.sort(key=lambda x: x[0])
        stop_times[tid] = [sid for _, sid in pontos]
    _cache["stop_times"] = stop_times
    shape_ids_necessarios = {
        v["shape_id"]
        for lista in viagens.values()
        for v in lista
    }
    shapes_raw: dict[str, list[tuple[int, float, float]]] = {}
    for s in _ler_csv("shapes.txt"):
        sid = s["shape_id"]
        if sid not in shape_ids_necessarios:
            continue
        shapes_raw.setdefault(sid, []).append((
            int(s["shape_pt_sequence"]),
            float(s["shape_pt_lat"]),
            float(s["shape_pt_lon"]),
        ))
    shapes: dict[str, list[tuple[float, float]]] = {}
    for sid, pontos in shapes_raw.items():
        pontos.sort(key=lambda x: x[0])
        shapes[sid] = [(lat, lng) for _, lat, lng in pontos]
    _cache["shapes"] = shapes


def dados_linha(numero_linha: str) -> dict | None:
    _carregar()
    route_id = _cache["rotas"].get(numero_linha.strip().upper())
    if not route_id:
        return None
    viagens = _cache["viagens"].get(route_id, [])
    shapes = _cache["shapes"]
    all_paradas = _cache["paradas"]
    stop_times = _cache["stop_times"]
    direcoes: dict[int, dict] = {}
    for v in viagens:
        did = v["direction_id"]
        sid = v["shape_id"]
        tid = v["trip_id"]
        if sid not in shapes:
            continue

        st_ids = stop_times.get(tid, [])
        paradas_lista = [
            {"id": all_paradas[sp].id, "nome": all_paradas[sp].nome,
             "lat": all_paradas[sp].lat, "lng": all_paradas[sp].lng}
            for sp in st_ids if sp in all_paradas
        ]

        direcoes[did] = {
            "headsign": v["headsign"],
            "shape": shapes[sid],
            "paradas": paradas_lista,
        }

    if not direcoes:
        return None
    return {"direcoes": direcoes}


def _dist_sq(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    dlat = lat2 - lat1
    dlng = (lng2 - lng1) * 0.9205
    return dlat * dlat + dlng * dlng


def _dist_haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlng / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def _indice_mais_proximo(shape: list[tuple[float, float]],
                         lat: float, lng: float) -> tuple[int, float]:
    n = len(shape)
    if n == 0:
        return 0, float("inf")
    passo = max(1, n // 200)
    melhor_i = 0
    melhor_d = float("inf")

    for i in range(0, n, passo):
        d = _dist_sq(lat, lng, shape[i][0], shape[i][1])
        if d < melhor_d:
            melhor_d = d
            melhor_i = i
    inicio = max(0, melhor_i - passo)
    fim = min(n, melhor_i + passo + 1)
    for i in range(inicio, fim):
        d = _dist_sq(lat, lng, shape[i][0], shape[i][1])
        if d < melhor_d:
            melhor_d = d
            melhor_i = i
    return melhor_i, melhor_d


def inferir_direcao(dados: dict, lat: float, lng: float,
                    lat_anterior: float | None = None,
                    lng_anterior: float | None = None) -> dict:
    direcoes = dados.get("direcoes", {})
    candidatos = []
    for did, info in direcoes.items():
        shape = info["shape"]
        if not shape:
            continue
        idx, dsq = _indice_mais_proximo(shape, lat, lng)
        candidatos.append({
            "direction_id": did,
            "headsign": info["headsign"],
            "progresso": idx / max(1, len(shape) - 1),
            "dist_sq": dsq,
            "idx": idx,
            "shape": shape,
        })

    if not candidatos:
        return {"direction_id": -1, "headsign": "Desconhecido", "progresso": 0.0}
    usar_heading = False
    dx_veiculo = 0.0
    dy_veiculo = 0.0
    if lat_anterior is not None and lng_anterior is not None:
        dx_veiculo = lng - lng_anterior
        dy_veiculo = lat - lat_anterior
        if (dx_veiculo * dx_veiculo + dy_veiculo * dy_veiculo) > 1.8e-8:
            usar_heading = True
    if usar_heading:
        mag_v = math.sqrt(dx_veiculo * dx_veiculo + dy_veiculo * dy_veiculo)
        melhor = None
        melhor_score = -float("inf")
        for c in candidatos:
            shape = c["shape"]
            idx = c["idx"]
            idx_antes = max(0, idx - 3)
            idx_depois = min(len(shape) - 1, idx + 3)
            dx_shape = shape[idx_depois][1] - shape[idx_antes][1]
            dy_shape = shape[idx_depois][0] - shape[idx_antes][0]
            mag_s = math.sqrt(dx_shape * dx_shape + dy_shape * dy_shape)

            if mag_s > 0:
                cosseno = (dx_veiculo * dx_shape + dy_veiculo * dy_shape) / (mag_v * mag_s)
            else:
                cosseno = 0.0
            score = cosseno - c["dist_sq"] * 5000.0
            if score > melhor_score:
                melhor_score = score
                melhor = c
        if melhor:
            return {
                "direction_id": melhor["direction_id"],
                "headsign": melhor["headsign"],
                "progresso": melhor["progresso"],
            }
    candidatos.sort(key=lambda c: c["dist_sq"])
    melhor = candidatos[0]
    return {
        "direction_id": melhor["direction_id"],
        "headsign": melhor["headsign"],
        "progresso": melhor["progresso"],
    }


def gerar_html():
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  html, body, #map {{ width:100%; height:100%; background:#0f172a; }}
  @keyframes pulse {{
    0% {{ transform: scale(1); opacity: 1; }}
    50% {{ transform: scale(1.8); opacity: 0.4; }}
    100% {{ transform: scale(1); opacity: 1; }}
  }}
  .user-marker-pulse {{
    width: 18px; height: 18px;
    background: #3b82f6;
    border: 3px solid #ffffff;
    border-radius: 50%;
    box-shadow: 0 0 10px rgba(59,130,246,0.7);
    position: relative;
  }}
  .user-marker-pulse::after {{
    content: '';
    position: absolute;
    top: -5px; left: -5px;
    width: 24px; height: 24px;
    border-radius: 50%;
    background: rgba(59,130,246,0.3);
    animation: pulse 2s infinite;
  }}
</style>
</head>
<body>
<div id="map"></div>
<script>
  var map = L.map("map").setView([-22.9068, -43.1729], 12);

  var osm = L.tileLayer("https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png", {{
    maxZoom: 19, attribution: "© OpenStreetMap"
  }});
  var sat = L.tileLayer(
    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}",
    {{ maxZoom: 19, attribution: "Tiles © Esri" }}
  );
  sat.addTo(map);
  L.control.layers({{"Claro": osm, "Satélite": sat}}, {{}}, {{position: "topright"}}).addTo(map);

  window._layerRotas = L.layerGroup().addTo(map);
  window._veiculos = {{}};
  window._userMarker = null;
  window._userLat = null;
  window._userLng = null;
  window._geoWatchId = null;
  window._locPermissao = "desconhecido";

  // --- Geolocalização ---
  window.iniciarGeolocalizacao = function() {{
      if (!navigator.geolocation) {{
          document.title = "GEO_ERROR:Geolocalização não suportada neste dispositivo.";
          return;
      }}
      navigator.geolocation.getCurrentPosition(
          function(pos) {{
              window._locPermissao = "ativa";
              window._atualizarPosicaoUsuario(pos);
              // Iniciar monitoramento contínuo
              window._geoWatchId = navigator.geolocation.watchPosition(
                  window._atualizarPosicaoUsuario,
                  function(err) {{}},
                  {{ enableHighAccuracy: true, maximumAge: 10000, timeout: 15000 }}
              );
              document.title = "GEO_OK:" + pos.coords.latitude + "," + pos.coords.longitude;
          }},
          function(err) {{
              window._locPermissao = "negada";
              if (err.code === 1) {{
                  document.title = "GEO_ERROR:Permissão de localização negada. Ative a localização nas configurações do dispositivo.";
              }} else if (err.code === 2) {{
                  document.title = "GEO_ERROR:Localização indisponível. Verifique se o GPS está ativado.";
              }} else {{
                  document.title = "GEO_ERROR:Não foi possível obter a localização. Verifique se o GPS está ativado.";
              }}
          }},
          {{ enableHighAccuracy: true, maximumAge: 10000, timeout: 15000 }}
      );
  }};

  window._atualizarPosicaoUsuario = function(pos) {{
      var lat = pos.coords.latitude;
      var lng = pos.coords.longitude;
      window._userLat = lat;
      window._userLng = lng;

      if (window._userMarker) {{
          window._userMarker.setLatLng([lat, lng]);
      }} else {{
          var icon = L.divIcon({{
              className: "",
              html: '<div class="user-marker-pulse"></div>',
              iconSize: [18, 18],
              iconAnchor: [9, 9]
          }});
          window._userMarker = L.marker([lat, lng], {{icon: icon, zIndexOffset: 1000}})
              .addTo(map)
              .bindPopup("<b>Você está aqui</b>");
      }}
      // Notificar Python da posição atualizada
      document.title = "GEO_UPDATE:" + lat + "," + lng;
  }};

  // Função para calcular distância haversine em JS (km)
  window.calcularDistancia = function(lat1, lng1, lat2, lng2) {{
      var R = 6371.0;
      var dLat = (lat2 - lat1) * Math.PI / 180;
      var dLng = (lng2 - lng1) * Math.PI / 180;
      var a = Math.sin(dLat/2) * Math.sin(dLat/2) +
              Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
              Math.sin(dLng/2) * Math.sin(dLng/2);
      return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
  }};

  window.limparMapa = function() {{
      window._layerRotas.clearLayers();
      for (var id in window._veiculos) {{
          map.removeLayer(window._veiculos[id]);
      }}
      window._veiculos = {{}};
  }};

  window._dadosVeiculos = {{}};

  window.atualizarOnibus = function(veiculos, ajustarZoom) {{
      var idsAtuais = {{}};
      var pontosBounds = [];

      veiculos.forEach(function(v) {{
          var id = v.ordem;
          idsAtuais[id] = true;
          window._dadosVeiculos[id] = v;
          pontosBounds.push([v.lat, v.lng]);

          if (window._veiculos[id]) {{
              window._veiculos[id].setLatLng([v.lat, v.lng]);
              window._veiculos[id].getPopup().setContent(v.popup);
          }} else {{
              var icon = L.divIcon({{
                  className: "",
                  html: `<div style="background:${{v.cor}};color:#ffffff;padding:5px 10px;
                                      border-radius:12px;font-weight:bold;border:2px solid #bae6fd;
                                      white-space:nowrap;font-size:12px;cursor:pointer;
                                      box-shadow:0 3px 8px rgba(0,0,0,0.4);">
                              ${{v.label}}
                         </div>`,
                  iconSize: [100, 30], iconAnchor: [50, 15]
              }});
              
              var marker = L.marker([v.lat, v.lng], {{icon: icon}}).addTo(map).bindPopup(v.popup);
              marker._busId = id;
              marker.on("click", function() {{
                  var busData = window._dadosVeiculos[this._busId];
                  var dist = -1;
                  if (window._userLat !== null && busData) {{
                      dist = window.calcularDistancia(window._userLat, window._userLng, busData.lat, busData.lng);
                  }}
                  document.title = "BUS_CLICK:" + this._busId + "|" + dist.toFixed(3);
              }});
              window._veiculos[id] = marker;
          }}
      }});

      for (var id in window._veiculos) {{
          if (!idsAtuais[id]) {{
              map.removeLayer(window._veiculos[id]);
              delete window._veiculos[id];
              delete window._dadosVeiculos[id];
          }}
      }}

      if (ajustarZoom && pontosBounds.length > 0) {{
          if (window._userLat !== null) {{
              pontosBounds.push([window._userLat, window._userLng]);
          }}
          map.fitBounds(pontosBounds, {{padding: [50, 50]}});
      }}
  }};

  // Iniciar geolocalização automaticamente ao carregar
  window.iniciarGeolocalizacao();
</script>
</body>
</html>"""


def gerar_js_rotas(gtfs_dados):
    if not gtfs_dados or "direcoes" not in gtfs_dados:
        return ""
    js_parts = ["window.limparMapa();"]
    for did, info in gtfs_dados["direcoes"].items():
        shape = info.get("shape", [])
        headsign = info.get("headsign", "Destino")
        hs_esc = headsign.replace("'", "\\'").replace('"', '\\"')
        cor_rota = COR_IDA if did == 0 else COR_VOLTA

        if shape:
            passo = max(1, len(shape) // 600)
            pontos_js = ",".join(f"[{lat},{lng}]" for lat, lng in shape[::passo])
            js_parts.append(
                f"window._layerRotas.addLayer("
                f"L.polyline([{pontos_js}], {{"
                f"color: '{cor_rota}', weight: 5, opacity: 0.85, smoothFactor: 1"
                f"}}).bindTooltip('Sentido {hs_esc}', {{sticky: true}})"
                f");"
            )

        for parada in info.get("paradas", []):
            nome_p = parada.get('nome', 'Parada').replace("'", "\\'").replace('"', '\\"')
            js_parts.append(
                f"window._layerRotas.addLayer("
                f"L.circleMarker([{parada['lat']}, {parada['lng']}], {{"
                f"radius: 5, color: '#ffffff', fillColor: '{COR_PARADA}',"
                f"fillOpacity: 0.9, weight: 1.5"
                f"}}).bindPopup(\"🏣 <b>Parada:</b> {nome_p}<br><b>Sentido:</b> {hs_esc}\")"
                f");"
            )

    return "\n".join(js_parts)


class CarregarGTFSWorker(QThread):
    sucesso = pyqtSignal(object, str)

    def __init__(self, linha):
        super().__init__()
        self.linha = linha

    def run(self):
        try:
            dados = dados_linha(self.linha)
            self.sucesso.emit(dados, self.linha)
        except Exception:
            self.sucesso.emit(None, self.linha)


class BuscaWorker(QThread):
    sucesso = pyqtSignal(list, str)
    erro = pyqtSignal(str)

    _posicoes_anteriores: dict = {}

    def __init__(self, linha, gtfs_dados):
        super().__init__()
        self.linha = linha
        self.gtfs_dados = gtfs_dados

    def run(self):
        try:
            self._buscar()
        except Exception as e:
            self.erro.emit(f"Erro interno: {e}")

    def _buscar(self):
        agora = datetime.now()
        inicio = agora - timedelta(minutes=3)
        fmt = "%Y-%m-%d %H:%M:%S"
        url = (
            "https://dados.mobilidade.rio/gps/sppo"
            f"?dataInicial={inicio.strftime(fmt)}"
            f"&dataFinal={agora.strftime(fmt)}"
        )
        try:
            resp = requests.get(url, timeout=API_TIMEOUT)
            resp.raise_for_status()
            dados = resp.json()
            brutos = dados.get("veiculos", dados) if isinstance(dados, dict) else dados
        except Exception as e:
            self.erro.emit(f"Falha na conexão: {e}")
            return

        def extrair_datahora(v):
            dh = v.get("datahora") or v.get("dataHora") or ""
            try:
                return datetime.strptime(str(dh), "%Y-%m-%d %H:%M:%S")
            except ValueError:
                return datetime.min

        brutos_ordenados = sorted(brutos, key=extrair_datahora, reverse=True)
        veiculos_filtrados = []
        unicos = set()
        for v in brutos_ordenados:
            if str(v.get("linha", "")).strip().upper() != self.linha.strip().upper():
                continue

            ordem = str(v.get("ordem", "")).strip()
            if not ordem or ordem in unicos:
                continue
            try:
                lat = float(str(v["latitude"]).replace(",", "."))
                lng = float(str(v["longitude"]).replace(",", "."))
                vel = float(str(v.get("velocidade", 0)).replace(",", "."))
            except (ValueError, KeyError):
                continue
            pos_ant = BuscaWorker._posicoes_anteriores.get(ordem)
            lat_ant = pos_ant[0] if pos_ant else None
            lng_ant = pos_ant[1] if pos_ant else None

            if self.gtfs_dados and "direcoes" in self.gtfs_dados:
                direcao = inferir_direcao(self.gtfs_dados, lat, lng, lat_ant, lng_ant)
            else:
                direcao = {"direction_id": 0, "headsign": "Desconhecido", "progresso": 0.0}
            BuscaWorker._posicoes_anteriores[ordem] = (lat, lng)
            unicos.add(ordem)
            veiculos_filtrados.append({
                "ordem": ordem,
                "lat": lat,
                "lng": lng,
                "velocidade": vel,
                "direcao": direcao,
            })

        self.sucesso.emit(veiculos_filtrados, self.linha)


class GeoPage(QWebEnginePage):
    """Página que concede automaticamente permissão de geolocalização."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.featurePermissionRequested.connect(self._on_permission)

    def _on_permission(self, url, feature):
        if feature == QWebEnginePage.Feature.Geolocation:
            self.setFeaturePermission(
                url, feature,
                QWebEnginePage.PermissionPolicy.PermissionGrantedByUser
            )


class CadeMeuOnibusApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Cadê meu Ônibus? — RJ")
        self.resize(800, 700)
        self.setMinimumSize(600, 500)
        self.setStyleSheet("background-color: #1e293b;")

        self._linha_ativa = None
        self._gtfs_dados = None
        self._veiculos_atuais = {}
        self._user_pos = None  # (lat, lng) do usuário
        self._worker_busca = None
        self._worker_gtfs = None
        self._timer = QTimer(self)
        self._timer.setInterval(INTERVALO_ATUALIZACAO_MS)
        self._timer.timeout.connect(self._atualizar_automatico)
        self._build_ui()

    def _build_ui(self):
        layout_principal = QVBoxLayout(self)
        layout_principal.setContentsMargins(0, 0, 0, 0)
        layout_principal.setSpacing(0)

        # --- Barra superior: campo de busca + botão ---
        barra_topo = QFrame()
        barra_topo.setStyleSheet("background-color: #1e293b;")
        barra_topo.setFixedHeight(70)
        layout_topo = QHBoxLayout(barra_topo)
        layout_topo.setContentsMargins(20, 15, 20, 15)
        layout_topo.setSpacing(15)

        self.campo_busca = QLineEdit()
        self.campo_busca.setPlaceholderText("Digite a linha (ex: 864)")
        self.campo_busca.setStyleSheet("""
            QLineEdit {
                background-color: #0f172a; color: #f8fafc; font-size: 14px;
                padding: 12px 16px; border: 2px solid #334155; border-radius: 8px;
            }
            QLineEdit:focus { border: 2px solid #0284c7; }
        """)
        self.campo_busca.returnPressed.connect(self._executar_busca_botao)

        self.btn_buscar = QPushButton("BUSCAR LINHA")
        self.btn_buscar.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_buscar.setFixedWidth(200)
        self.btn_buscar.setStyleSheet("""
            QPushButton {
                background-color: #22c55e; color: #ffffff; font-size: 13px; font-weight: bold;
                padding: 12px; border: none; border-radius: 8px;
            }
            QPushButton:hover { background-color: #16a34a; }
            QPushButton:disabled { background-color: #334155; color: #64748b; }
        """)
        self.btn_buscar.clicked.connect(self._executar_busca_botao)

        layout_topo.addWidget(self.campo_busca, stretch=1)
        layout_topo.addWidget(self.btn_buscar)

        # --- Mapa central ---
        self.web_mapa = QWebEngineView()
        geo_page = GeoPage(self.web_mapa)
        self.web_mapa.setPage(geo_page)
        self.web_mapa.setHtml(gerar_html())
        self.web_mapa.page().titleChanged.connect(self._on_titulo_mudou)

        # --- Barra separadora azul ---
        separador = QFrame()
        separador.setFixedHeight(4)
        separador.setStyleSheet("background-color: #0284c7;")

        # --- Painel inferior: informações do ônibus ---
        painel_info = QFrame()
        painel_info.setStyleSheet("background-color: #1e293b;")
        layout_info = QVBoxLayout(painel_info)
        layout_info.setContentsMargins(20, 15, 20, 15)
        layout_info.setSpacing(4)

        self.lbl_onibus = QLabel("")
        self.lbl_onibus.setStyleSheet("color: #22c55e; font-size: 13px; font-weight: bold;")
        self.lbl_codigo = QLabel("")
        self.lbl_codigo.setStyleSheet("color: #f8fafc; font-size: 13px; font-weight: bold;")
        self.lbl_distancia = QLabel("")
        self.lbl_distancia.setStyleSheet("color: #f8fafc; font-size: 13px; font-weight: bold;")
        self.lbl_tempo = QLabel("")
        self.lbl_tempo.setStyleSheet("color: #f8fafc; font-size: 13px; font-weight: bold;")
        self.lbl_trajeto = QLabel("")
        self.lbl_trajeto.setStyleSheet("color: #f8fafc; font-size: 13px; font-weight: bold;")
        self.lbl_sentido = QLabel("")
        self.lbl_sentido.setStyleSheet("color: #f8fafc; font-size: 13px; font-weight: bold;")

        self.lbl_status = QLabel("Digite o número da linha e clique em Buscar.")
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setStyleSheet("color: #94a3b8; font-size: 12px;")

        layout_info.addWidget(self.lbl_onibus)
        layout_info.addWidget(self.lbl_codigo)
        layout_info.addWidget(self.lbl_distancia)
        layout_info.addWidget(self.lbl_tempo)
        layout_info.addWidget(self.lbl_trajeto)
        layout_info.addWidget(self.lbl_sentido)
        layout_info.addWidget(self.lbl_status)

        # --- Montar layout principal ---
        layout_principal.addWidget(barra_topo)
        layout_principal.addWidget(self.web_mapa, stretch=1)
        layout_principal.addWidget(separador)
        layout_principal.addWidget(painel_info)

    def _on_titulo_mudou(self, titulo):
        # --- Geolocalização: posição obtida com sucesso ---
        if titulo.startswith("GEO_OK:"):
            partes = titulo.replace("GEO_OK:", "").split(",")
            try:
                self._user_pos = (float(partes[0]), float(partes[1]))
            except (ValueError, IndexError):
                pass
            return

        # --- Geolocalização: atualização contínua de posição ---
        if titulo.startswith("GEO_UPDATE:"):
            partes = titulo.replace("GEO_UPDATE:", "").split(",")
            try:
                self._user_pos = (float(partes[0]), float(partes[1]))
            except (ValueError, IndexError):
                pass
            return

        # --- Geolocalização: erro (permissão negada ou GPS desativado) ---
        if titulo.startswith("GEO_ERROR:"):
            msg = titulo.replace("GEO_ERROR:", "")
            self.lbl_status.setText(f"📍 {msg}")
            self.lbl_status.setStyleSheet("color: #fbbf24;")
            return

        # --- Clique no ônibus ---
        if titulo.startswith("BUS_CLICK:"):
            dados = titulo.replace("BUS_CLICK:", "")
            # Formato: ordem|distancia_km
            if "|" in dados:
                ordem, dist_str = dados.split("|", 1)
            else:
                ordem = dados
                dist_str = "-1"

            veiculo = self._veiculos_atuais.get(ordem)
            if not veiculo or not self._linha_ativa:
                return

            linha = self._linha_ativa
            progresso = veiculo["direcao"].get("progresso", 0.0)
            headsign = veiculo["direcao"].get("headsign", "Desconhecido")

            # Calcular distância real entre usuário e ônibus
            try:
                dist_km = float(dist_str)
            except ValueError:
                dist_km = -1

            if dist_km < 0 and self._user_pos:
                dist_km = _dist_haversine(
                    self._user_pos[0], self._user_pos[1],
                    veiculo["lat"], veiculo["lng"]
                )

            if dist_km >= 0:
                tempo_min = max(1, int(dist_km / 0.4))
                self.lbl_distancia.setText(f"Distância: <b>{dist_km:.1f} km</b>")
                self.lbl_tempo.setText(f"Tempo estimado: <b>{tempo_min} min</b>")
            else:
                self.lbl_distancia.setText("Distância: <b>--</b> (ative a localização)")
                self.lbl_tempo.setText("Tempo estimado: <b>--</b>")

            self.lbl_onibus.setText(f"Onibus selecionado: <b>{linha}</b>")
            self.lbl_codigo.setText(f"Código ID: <b>{ordem}</b>")
            self.lbl_trajeto.setText(f"Trajeto: <b>{progresso * 100:.0f}% concluído</b>")
            self.lbl_sentido.setText(f"Sentido: <b>{headsign}</b>")
            return

    def _executar_busca_botao(self):
        texto = self.campo_busca.text().strip().upper()
        if not texto:
            self.lbl_status.setText("⚠️ Digite o número de uma linha.")
            self.lbl_status.setStyleSheet("color: #fbbf24;")
            return
        self._linha_ativa = texto
        self.lbl_status.setText("📡 Carregando dados da linha...")
        self.lbl_status.setStyleSheet("color: #38bdf8;")
        if self._worker_gtfs and self._worker_gtfs.isRunning():
            return
        self._worker_gtfs = CarregarGTFSWorker(texto)
        self._worker_gtfs.sucesso.connect(self._on_gtfs_carregado)
        self._worker_gtfs.start()

    def _on_gtfs_carregado(self, dados, linha):
        if linha != self._linha_ativa:
            return
        try:
            self._worker_gtfs.sucesso.disconnect(self._on_gtfs_carregado)
        except Exception:
            pass
        self._gtfs_dados = dados
        if not dados or "direcoes" not in dados:
            self.lbl_status.setText(
                f"⚠️ Linha <b>{linha}</b> não encontrada no GTFS.<br>"
                "A busca continuará sem dados de rota."
            )
            self.lbl_status.setStyleSheet("color: #fbbf24;")
        self._iniciar_busca(silencioso=False, reescrever_mapa=True)

    def _atualizar_automatico(self):
        if self._linha_ativa and (self._worker_busca is None or not self._worker_busca.isRunning()):
            self._iniciar_busca(silencioso=True, reescrever_mapa=False)

    def _iniciar_busca(self, silencioso=False, reescrever_mapa=False):
        if not silencioso:
            self.lbl_status.setText("📡 Localizando ônibus...")
            self.lbl_status.setStyleSheet("color: #38bdf8;")
        self._worker_busca = BuscaWorker(self._linha_ativa, self._gtfs_dados)
        self._worker_busca.sucesso.connect(
            lambda v, l: self._on_busca_sucesso(v, l, reescrever_mapa, silencioso)
        )
        self._worker_busca.erro.connect(lambda msg: self._on_busca_erro(msg, silencioso))
        self._worker_busca.start()

    def _on_busca_sucesso(self, veiculos, linha, reescrever_mapa, silencioso):
        if not self._timer.isActive():
            self._timer.start()
        agora_str = datetime.now().strftime("%H:%M:%S")
        self.lbl_status.setText(
            f"<span style='color:#64748b;font-size:11px'>🔄 Atualizado às {agora_str} — "
            f"{len(veiculos)} ônibus</span>"
        )
        self.lbl_status.setStyleSheet("color: #64748b;")

        # Armazenar veículos para uso ao clicar
        self._veiculos_atuais = {v["ordem"]: v for v in veiculos}

        # Se nenhum ônibus selecionado ainda, mostrar mensagem
        if not self.lbl_onibus.text() and veiculos:
            self.lbl_onibus.setText(f"Onibus selecionado: <b>{linha}</b>")
            self.lbl_status.setText(
                f"<span style='color:#94a3b8;font-size:11px'>"
                f"Clique em um ônibus no mapa para ver detalhes — "
                f"{len(veiculos)} encontrados (🔄 {agora_str})</span>"
            )

        payload = []
        for v in veiculos:
            direction_id = v["direcao"].get("direction_id")
            cor = COR_IDA if direction_id == 0 else COR_VOLTA
            sentido_txt = "Ida" if direction_id == 0 else "Volta"
            progresso = v["direcao"].get("progresso", 0.0)
            popup = (
                f"<b>Linha {linha}</b><br>"
                f"Veículo: <b>{v['ordem']}</b><br>"
                f"Sentido: <b>{sentido_txt}</b><br>"
                f"Velocidade: {v['velocidade']:.0f} km/h<br>"
                f"Progresso na rota: {progresso * 100:.0f}%"
            )
            payload.append({
                "ordem": v["ordem"],
                "lat": v["lat"],
                "lng": v["lng"],
                "cor": cor,
                "label": f"🚌 {v['ordem']}",
                "popup": popup,
            })
        if reescrever_mapa:
            js_rotas = gerar_js_rotas(self._gtfs_dados)
            js_onibus = f"window.atualizarOnibus({json.dumps(payload, ensure_ascii=False)}, true);"
            js_total = js_rotas + "\n" + js_onibus
            self.web_mapa.page().runJavaScript(js_total)
        else:
            js = f"window.atualizarOnibus({json.dumps(payload, ensure_ascii=False)}, false);"
            self.web_mapa.page().runJavaScript(js)

    def _on_busca_erro(self, msg, silencioso):
        self._timer.stop()
        self.lbl_status.setText(f"❌ {msg}")
        self.lbl_status.setStyleSheet("color: #f87171;")


if __name__ == "__main__":
    import sys
    app = QApplication(sys.argv)
    janela = CadeMeuOnibusApp()
    janela.show()
    sys.exit(app.exec())

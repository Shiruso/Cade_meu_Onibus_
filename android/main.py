"""
Cade meu Onibus - Versao Android
Compativel com Android 9 (API 28) ou superior.
Usa Kivy + Android WebView nativo para o mapa.
"""
import csv
import json
import math
import os
from datetime import datetime, timedelta
from threading import Thread

from kivy.app import App
from kivy.clock import Clock
from kivy.lang import Builder
from kivy.utils import platform
from kivy.uix.boxlayout import BoxLayout

# Constantes
API_TIMEOUT = 10
INTERVALO_ATUALIZACAO_S = 20
COR_IDA = "#0284c7"
COR_VOLTA = "#f97316"
COR_PARADA = "#22c55e"

# URL base para download dos dados GTFS
GTFS_DOWNLOAD_URL = "https://raw.githubusercontent.com/Shiruso/Cade_meu_Onibus_/main/GTFS%20RJ/"
GTFS_ARQUIVOS = [
    "routes.txt",
    "trips.txt",
    "stops.txt",
    "stop_times.zip",
    "shapes.txt",
    "frequencies.txt",
]

# Diretorio GTFS - definido em runtime
GTFS_DIR = ""

_cache = {}
_posicoes_anteriores = {}


def _definir_gtfs_dir():
    """Define o diretorio GTFS com base na plataforma."""
    global GTFS_DIR
    if platform == "android":
        # No Android, salva no armazenamento privado do app
        app = App.get_running_app()
        if app:
            GTFS_DIR = os.path.join(app.user_data_dir, "gtfs")
        else:
            GTFS_DIR = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "gtfs")
    else:
        GTFS_DIR = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "gtfs")
    os.makedirs(GTFS_DIR, exist_ok=True)


def gtfs_disponivel():
    """Verifica se os dados GTFS ja foram baixados."""
    if not GTFS_DIR or not os.path.isdir(GTFS_DIR):
        return False
    # Verifica se pelo menos routes.txt e trips.txt existem
    obrigatorios = ["routes.txt", "trips.txt", "stops.txt"]
    for arq in obrigatorios:
        if not os.path.exists(os.path.join(GTFS_DIR, arq)):
            return False
    return True


def baixar_gtfs(callback_progresso=None):
    """Baixa os arquivos GTFS do servidor. Retorna True se sucesso."""
    import requests
    import zipfile
    os.makedirs(GTFS_DIR, exist_ok=True)
    total = len(GTFS_ARQUIVOS)
    for i, nome in enumerate(GTFS_ARQUIVOS):
        url = GTFS_DOWNLOAD_URL + nome
        destino = os.path.join(GTFS_DIR, nome)
        try:
            if callback_progresso:
                callback_progresso(i, total, nome)
            resp = requests.get(url, timeout=120, stream=True)
            resp.raise_for_status()
            with open(destino, "wb") as f:
                for chunk in resp.iter_content(chunk_size=65536):
                    if chunk:
                        f.write(chunk)
            # Se for zip, descompactar e remover o zip
            if nome.endswith(".zip"):
                with zipfile.ZipFile(destino, "r") as zf:
                    zf.extractall(GTFS_DIR)
                os.remove(destino)
        except Exception as e:
            if os.path.exists(destino):
                os.remove(destino)
            raise Exception("Erro ao baixar {}: {}".format(nome, e))
    if callback_progresso:
        callback_progresso(total, total, "Concluido")
    return True


# ==============================================================
# Leitura GTFS
# ==============================================================

def _ler_csv(nome):
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
        paradas[sid] = {
            "id": sid,
            "nome": s.get("stop_name", "Parada"),
            "lat": float(s["stop_lat"]),
            "lng": float(s["stop_lon"]),
        }
    _cache["paradas"] = paradas

    viagens = {}
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

    trip_ids_necessarios = set()
    for lista in viagens.values():
        for v in lista:
            trip_ids_necessarios.add(v["trip_id"])

    stop_times_raw = {}
    for st in _ler_csv("stop_times.txt"):
        tid = st["trip_id"]
        if tid not in trip_ids_necessarios:
            continue
        seq = int(st["stop_sequence"])
        stop_times_raw.setdefault(tid, []).append((seq, st["stop_id"]))
    stop_times = {}
    for tid, pontos in stop_times_raw.items():
        pontos.sort(key=lambda x: x[0])
        stop_times[tid] = [sid for _, sid in pontos]
    _cache["stop_times"] = stop_times

    shape_ids_necessarios = set()
    for lista in viagens.values():
        for v in lista:
            shape_ids_necessarios.add(v["shape_id"])

    shapes_raw = {}
    for s in _ler_csv("shapes.txt"):
        sid = s["shape_id"]
        if sid not in shape_ids_necessarios:
            continue
        shapes_raw.setdefault(sid, []).append((
            int(s["shape_pt_sequence"]),
            float(s["shape_pt_lat"]),
            float(s["shape_pt_lon"]),
        ))
    shapes = {}
    for sid, pontos in shapes_raw.items():
        pontos.sort(key=lambda x: x[0])
        shapes[sid] = [(lat, lng) for _, lat, lng in pontos]
    _cache["shapes"] = shapes


def dados_linha(numero_linha):
    _carregar()
    route_id = _cache["rotas"].get(numero_linha.strip().upper())
    if not route_id:
        return None
    viagens = _cache["viagens"].get(route_id, [])
    shapes = _cache["shapes"]
    all_paradas = _cache["paradas"]
    stop_times = _cache["stop_times"]
    direcoes = {}
    for v in viagens:
        did = v["direction_id"]
        sid = v["shape_id"]
        tid = v["trip_id"]
        if sid not in shapes:
            continue
        st_ids = stop_times.get(tid, [])
        paradas_lista = [
            {"id": all_paradas[sp]["id"], "nome": all_paradas[sp]["nome"],
             "lat": all_paradas[sp]["lat"], "lng": all_paradas[sp]["lng"]}
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


# ==============================================================
# Funcoes de geometria
# ==============================================================

def _dist_sq(lat1, lng1, lat2, lng2):
    dlat = lat2 - lat1
    dlng = (lng2 - lng1) * 0.9205
    return dlat * dlat + dlng * dlng


def _dist_haversine(lat1, lng1, lat2, lng2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlng / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def _indice_mais_proximo(shape, lat, lng):
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


def inferir_direcao(dados, lat, lng, lat_anterior=None, lng_anterior=None):
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
        mag_v = math.sqrt(dx_veiculo ** 2 + dy_veiculo ** 2)
        melhor = None
        melhor_score = -float("inf")
        for c in candidatos:
            shape = c["shape"]
            idx = c["idx"]
            idx_antes = max(0, idx - 3)
            idx_depois = min(len(shape) - 1, idx + 3)
            dx_shape = shape[idx_depois][1] - shape[idx_antes][1]
            dy_shape = shape[idx_depois][0] - shape[idx_antes][0]
            mag_s = math.sqrt(dx_shape ** 2 + dy_shape ** 2)
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


# ==============================================================
# Gerar JS para rotas no mapa
# ==============================================================

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
            pontos_js = ",".join(
                "[{},{}]".format(lat, lng) for lat, lng in shape[::passo]
            )
            js_parts.append(
                "window._layerRotas.addLayer("
                "L.polyline([{}], {{".format(pontos_js)
                + "color: '{}', weight: 5, opacity: 0.85, smoothFactor: 1".format(cor_rota)
                + "}}).bindTooltip('Sentido {}', {{sticky: true}})".format(hs_esc)
                + ");"
            )
        for parada in info.get("paradas", []):
            nome_p = parada.get("nome", "Parada").replace("'", "\\'").replace('"', '\\"')
            js_parts.append(
                "window._layerRotas.addLayer("
                "L.circleMarker([{}, {}], {{".format(parada["lat"], parada["lng"])
                + "radius: 5, color: '#ffffff', fillColor: '{}',".format(COR_PARADA)
                + "fillOpacity: 0.9, weight: 1.5"
                + "}}).bindPopup(\"<b>Parada:</b> {}<br><b>Sentido:</b> {}\")".format(nome_p, hs_esc)
                + ");"
            )
    return "\n".join(js_parts)


# ==============================================================
# Busca na API
# ==============================================================

def buscar_veiculos(linha, gtfs_dados):
    """Busca veiculos da linha na API. Retorna lista de dicts."""
    import requests  # importado aqui para nao travar o startup
    agora = datetime.now()
    inicio = agora - timedelta(minutes=3)
    fmt = "%Y-%m-%d %H:%M:%S"
    url = (
        "https://dados.mobilidade.rio/gps/sppo"
        "?dataInicial={}&dataFinal={}".format(
            inicio.strftime(fmt), agora.strftime(fmt))
    )
    resp = requests.get(url, timeout=API_TIMEOUT)
    resp.raise_for_status()
    dados = resp.json()
    brutos = dados.get("veiculos", dados) if isinstance(dados, dict) else dados

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
        if str(v.get("linha", "")).strip().upper() != linha.strip().upper():
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
        pos_ant = _posicoes_anteriores.get(ordem)
        lat_ant = pos_ant[0] if pos_ant else None
        lng_ant = pos_ant[1] if pos_ant else None
        if gtfs_dados and "direcoes" in gtfs_dados:
            direcao = inferir_direcao(gtfs_dados, lat, lng, lat_ant, lng_ant)
        else:
            direcao = {"direction_id": 0, "headsign": "Desconhecido", "progresso": 0.0}
        _posicoes_anteriores[ordem] = (lat, lng)
        unicos.add(ordem)
        veiculos_filtrados.append({
            "ordem": ordem,
            "lat": lat,
            "lng": lng,
            "velocidade": vel,
            "direcao": direcao,
        })
    return veiculos_filtrados


# ==============================================================
# Interface Kivy (KV language)
# ==============================================================

KV = """
<CadeMeuOnibusRoot>:
    orientation: 'vertical'

    BoxLayout:
        size_hint_y: None
        height: dp(56)
        padding: dp(8)
        spacing: dp(8)
        canvas.before:
            Color:
                rgba: 0.118, 0.161, 0.231, 1
            Rectangle:
                pos: self.pos
                size: self.size

        TextInput:
            id: campo_busca
            hint_text: 'Digite a linha (ex: 864)'
            multiline: False
            size_hint_x: 0.65
            font_size: sp(15)
            background_color: 0.059, 0.090, 0.165, 1
            foreground_color: 1, 1, 1, 1
            hint_text_color: 0.58, 0.64, 0.72, 1
            padding: [dp(12), dp(10)]
            on_text_validate: root.executar_busca()

        Button:
            text: 'BUSCAR'
            size_hint_x: 0.35
            font_size: sp(14)
            bold: True
            background_color: 0.133, 0.773, 0.369, 1
            background_normal: ''
            color: 1, 1, 1, 1
            on_release: root.executar_busca()

    # Area do mapa (placeholder - WebView fica por cima)
    Widget:
        id: mapa_area
        size_hint_y: 1

    # Separador
    Widget:
        size_hint_y: None
        height: dp(3)
        canvas:
            Color:
                rgba: 0.008, 0.518, 0.78, 1
            Rectangle:
                pos: self.pos
                size: self.size

    # Painel inferior
    BoxLayout:
        orientation: 'vertical'
        size_hint_y: None
        height: dp(150)
        padding: dp(12), dp(8)
        spacing: dp(1)
        canvas.before:
            Color:
                rgba: 0.118, 0.161, 0.231, 1
            Rectangle:
                pos: self.pos
                size: self.size

        Label:
            id: lbl_onibus
            markup: True
            text: ''
            color: 0.133, 0.773, 0.369, 1
            font_size: sp(13)
            size_hint_y: None
            height: self.texture_size[1]
            text_size: self.width, None
            halign: 'left'
        Label:
            id: lbl_codigo
            markup: True
            text: ''
            color: 1, 1, 1, 1
            font_size: sp(13)
            size_hint_y: None
            height: self.texture_size[1]
            text_size: self.width, None
            halign: 'left'
        Label:
            id: lbl_distancia
            markup: True
            text: ''
            color: 1, 1, 1, 1
            font_size: sp(13)
            size_hint_y: None
            height: self.texture_size[1]
            text_size: self.width, None
            halign: 'left'
        Label:
            id: lbl_tempo
            markup: True
            text: ''
            color: 1, 1, 1, 1
            font_size: sp(13)
            size_hint_y: None
            height: self.texture_size[1]
            text_size: self.width, None
            halign: 'left'
        Label:
            id: lbl_trajeto
            markup: True
            text: ''
            color: 1, 1, 1, 1
            font_size: sp(13)
            size_hint_y: None
            height: self.texture_size[1]
            text_size: self.width, None
            halign: 'left'
        Label:
            id: lbl_sentido
            markup: True
            text: ''
            color: 1, 1, 1, 1
            font_size: sp(13)
            size_hint_y: None
            height: self.texture_size[1]
            text_size: self.width, None
            halign: 'left'
        Label:
            id: lbl_status
            markup: True
            text: 'Digite a linha e toque em BUSCAR.'
            color: 0.58, 0.64, 0.72, 1
            font_size: sp(12)
            size_hint_y: None
            height: self.texture_size[1]
            text_size: self.width, None
            halign: 'left'
"""


# ==============================================================
# WebView para Android
# ==============================================================

class CadeMeuOnibusRoot(BoxLayout):
    """Widget raiz do app."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._linha_ativa = None
        self._gtfs_dados = None
        self._veiculos_atuais = {}
        self._user_pos = None
        self._timer_event = None
        self._webview = None

    def on_kv_post(self, base_widget):
        # Definir diretorio GTFS
        _definir_gtfs_dir()
        if platform == "android":
            self._pedir_permissoes()
            Clock.schedule_once(self._criar_webview, 1.0)
        # Verificar se GTFS precisa ser baixado
        if not gtfs_disponivel():
            self.ids.lbl_status.text = (
                "[color=#38bdf8]Baixando dados de rotas (primeira vez)...[/color]"
            )
            Thread(target=self._thread_baixar_gtfs, daemon=True).start()

    def _thread_baixar_gtfs(self):
        """Baixa GTFS em background e atualiza UI."""
        def progresso(atual, total, nome):
            msg = "[color=#38bdf8]Baixando {}/{}: {}...[/color]".format(
                atual + 1, total, nome)
            Clock.schedule_once(lambda dt: self._set_status(msg), 0)
        try:
            baixar_gtfs(callback_progresso=progresso)
            Clock.schedule_once(
                lambda dt: self._set_status(
                    "[color=#22c55e]Dados baixados com sucesso![/color]"), 0)
        except Exception as e:
            Clock.schedule_once(
                lambda dt: self._set_status(
                    "[color=#f87171]Erro no download: {}[/color]".format(e)), 0)

    def _set_status(self, texto):
        self.ids.lbl_status.text = texto

    def _pedir_permissoes(self):
        from android.permissions import request_permissions, Permission
        request_permissions([
            Permission.ACCESS_FINE_LOCATION,
            Permission.ACCESS_COARSE_LOCATION,
            Permission.INTERNET,
            Permission.ACCESS_NETWORK_STATE,
        ])

    def _criar_webview(self, dt):
        """Cria o WebView nativo do Android sobre a area do mapa."""
        from jnius import PythonJavaClass, java_method, autoclass
        from android.runnable import run_on_ui_thread

        # Criar JSBridge na thread Python (obrigatorio para PythonJavaClass)
        app_ref = self

        class JSBridge(PythonJavaClass):
            __javainterfaces__ = ["android/webkit/JavascriptInterface"]
            __javacontext__ = "app"

            @java_method("(Ljava/lang/String;)V")
            def onBusClick(self, data):
                Clock.schedule_once(lambda dt: app_ref._on_bus_click(data), 0)

            @java_method("(Ljava/lang/String;)V")
            def onGeoUpdate(self, data):
                Clock.schedule_once(lambda dt: app_ref._on_geo_update(data), 0)

            @java_method("(Ljava/lang/String;)V")
            def onGeoError(self, msg):
                Clock.schedule_once(lambda dt: app_ref._on_geo_error(msg), 0)

        # Manter referencia para nao ser coletado pelo GC
        self._js_bridge = JSBridge()

        # Determinar caminho do HTML
        html_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "mapa.html")

        @run_on_ui_thread
        def _create():
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            WebView = autoclass("android.webkit.WebView")
            WebChromeClient = autoclass("android.webkit.WebChromeClient")
            FrameLayoutParams = autoclass(
                "android.widget.FrameLayout$LayoutParams")

            activity = PythonActivity.mActivity
            wv = WebView(activity)

            # Configuracoes do WebView
            settings = wv.getSettings()
            settings.setJavaScriptEnabled(True)
            settings.setDomStorageEnabled(True)
            settings.setGeolocationEnabled(True)
            settings.setAllowFileAccess(True)
            settings.setAllowContentAccess(True)
            settings.setBuiltInZoomControls(True)
            settings.setDisplayZoomControls(False)
            settings.setMixedContentMode(0)

            wv.setWebChromeClient(WebChromeClient())

            # Adicionar interface JS -> Python
            wv.addJavascriptInterface(self._js_bridge, "Android")

            # Carregar mapa
            wv.loadUrl("file://" + html_path)

            # Posicionar o WebView na area do mapa
            mapa_widget = self.ids.mapa_area
            from kivy.core.window import Window
            density = Window.dpi / 160.0

            x = int(mapa_widget.x * density)
            y = int((Window.height - mapa_widget.top) * density)
            w = int(mapa_widget.width * density)
            h = int(mapa_widget.height * density)

            params = FrameLayoutParams(w, h)
            params.leftMargin = x
            params.topMargin = y

            activity.addContentView(wv, params)
            self._webview = wv

        _create()

    def _executar_js(self, js_code):
        """Executa JavaScript no WebView de forma segura."""
        if not self._webview:
            return
        from android.runnable import run_on_ui_thread

        @run_on_ui_thread
        def _run():
            if self._webview:
                self._webview.evaluateJavascript(js_code, None)
        _run()

    # ==============================================================
    # Busca e atualizacao
    # ==============================================================

    def executar_busca(self):
        texto = self.ids.campo_busca.text.strip().upper()
        if not texto:
            self.ids.lbl_status.text = "[color=#fbbf24]Digite o numero de uma linha.[/color]"
            return
        self._linha_ativa = texto
        self.ids.lbl_status.text = "[color=#38bdf8]Carregando dados da linha...[/color]"
        Thread(target=self._thread_busca, args=(texto,), daemon=True).start()

    def _thread_busca(self, linha):
        try:
            gtfs = dados_linha(linha)
            self._gtfs_dados = gtfs
        except Exception:
            self._gtfs_dados = None
        try:
            veiculos = buscar_veiculos(linha, self._gtfs_dados)
        except Exception as e:
            Clock.schedule_once(
                lambda dt: self._on_erro("Falha na conexao: {}".format(e)), 0)
            return
        Clock.schedule_once(
            lambda dt: self._on_busca_sucesso(veiculos, linha, True), 0)

    def _on_busca_sucesso(self, veiculos, linha, reescrever_mapa):
        if linha != self._linha_ativa:
            return
        agora_str = datetime.now().strftime("%H:%M:%S")
        self.ids.lbl_status.text = (
            "[color=#64748b]Atualizado as {} - {} onibus[/color]".format(
                agora_str, len(veiculos))
        )
        self._veiculos_atuais = {v["ordem"]: v for v in veiculos}

        if not self.ids.lbl_onibus.text and veiculos:
            self.ids.lbl_onibus.text = "[color=#22c55e]Toque em um onibus no mapa[/color]"

        # Payload para o mapa
        payload = []
        for v in veiculos:
            direction_id = v["direcao"].get("direction_id")
            cor = COR_IDA if direction_id == 0 else COR_VOLTA
            progresso = v["direcao"].get("progresso", 0.0)
            popup = (
                "<b>Linha {}</b><br>"
                "Veiculo: <b>{}</b><br>"
                "Velocidade: {:.0f} km/h<br>"
                "Progresso: {:.0f}%"
            ).format(linha, v["ordem"], v["velocidade"], progresso * 100)
            payload.append({
                "ordem": v["ordem"],
                "lat": v["lat"],
                "lng": v["lng"],
                "cor": cor,
                "label": v["ordem"],
                "popup": popup,
            })

        js_payload = json.dumps(payload, ensure_ascii=False)
        if reescrever_mapa:
            js_rotas = gerar_js_rotas(self._gtfs_dados)
            js = js_rotas + "\nwindow.atualizarOnibus({}, true);".format(js_payload)
        else:
            js = "window.atualizarOnibus({}, false);".format(js_payload)

        if platform == "android":
            self._executar_js(js)

        # Timer de atualizacao
        if self._timer_event:
            self._timer_event.cancel()
        self._timer_event = Clock.schedule_interval(
            self._atualizar_automatico, INTERVALO_ATUALIZACAO_S)

    def _atualizar_automatico(self, dt):
        if not self._linha_ativa:
            return
        Thread(target=self._thread_atualizar, daemon=True).start()

    def _thread_atualizar(self):
        linha = self._linha_ativa
        try:
            veiculos = buscar_veiculos(linha, self._gtfs_dados)
        except Exception:
            return
        Clock.schedule_once(
            lambda dt: self._on_busca_sucesso(veiculos, linha, False), 0)

    def _on_erro(self, msg):
        self.ids.lbl_status.text = "[color=#f87171]{}[/color]".format(msg)
        if self._timer_event:
            self._timer_event.cancel()
            self._timer_event = None

    # ==============================================================
    # Callbacks do JavaScript
    # ==============================================================

    def _on_bus_click(self, data):
        if "|" in data:
            ordem, dist_str = data.split("|", 1)
        else:
            ordem = data
            dist_str = "-1"

        veiculo = self._veiculos_atuais.get(ordem)
        if not veiculo or not self._linha_ativa:
            return

        linha = self._linha_ativa
        progresso = veiculo["direcao"].get("progresso", 0.0)
        headsign = veiculo["direcao"].get("headsign", "Desconhecido")

        try:
            dist_km = float(dist_str)
        except ValueError:
            dist_km = -1.0

        if dist_km < 0 and self._user_pos:
            dist_km = _dist_haversine(
                self._user_pos[0], self._user_pos[1],
                veiculo["lat"], veiculo["lng"])

        self.ids.lbl_onibus.text = "[b]Onibus selecionado: {}[/b]".format(linha)
        self.ids.lbl_codigo.text = "[b]Codigo ID: {}[/b]".format(ordem)
        if dist_km >= 0:
            tempo_min = max(1, int(dist_km / 0.4))
            self.ids.lbl_distancia.text = "[b]Distancia: {:.1f} km[/b]".format(dist_km)
            self.ids.lbl_tempo.text = "[b]Tempo estimado: {} min[/b]".format(tempo_min)
        else:
            self.ids.lbl_distancia.text = "[b]Distancia: -- (ative a localizacao)[/b]"
            self.ids.lbl_tempo.text = "[b]Tempo estimado: --[/b]"
        self.ids.lbl_trajeto.text = "[b]Trajeto: {:.0f}% concluido[/b]".format(progresso * 100)
        self.ids.lbl_sentido.text = "[b]Sentido: {}[/b]".format(headsign)

    def _on_geo_update(self, data):
        try:
            partes = data.split(",")
            self._user_pos = (float(partes[0]), float(partes[1]))
        except (ValueError, IndexError):
            pass

    def _on_geo_error(self, msg):
        self.ids.lbl_status.text = "[color=#fbbf24]{}[/color]".format(msg)


# ==============================================================
# App principal
# ==============================================================

class CadeMeuOnibusApp(App):
    def build(self):
        Builder.load_string(KV)
        return CadeMeuOnibusRoot()


if __name__ == "__main__":
    CadeMeuOnibusApp().run()

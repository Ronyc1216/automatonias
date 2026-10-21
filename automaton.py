"""
Automaton de cripto — colonia de bots con supervivencia, muerte y replicación.
Paper trading (dinero falso) con precios reales de Coinbase.
Corre cada 15 min con GitHub Actions y guarda todo en state.json.
"""
import json
import os
import random
import sys
import time
import urllib.request
from datetime import datetime, timezone

STATE_FILE = "state.json"
ALERT_FILE = "alerts.txt"
CAPITAL_INICIAL = 200.0
COMISION = 0.006          # 0.6% por operación (taker de Coinbase)
MONEDAS = ["BTC", "ETH", "SOL", "DOGE"]
HISTORIAL_MAX = 300
EVENTOS_MAX = 150
SIMULAR = "--simular" in sys.argv

FUNDADORES = [
    # nombre, moneda, capital, apalancamiento
    ("Satoshi", "BTC", 120.0, 1),
    ("Halcón",  "BTC",  60.0, 3),
    ("Éter",    "ETH",   7.0, 1),
    ("Solar",   "SOL",   7.0, 2),
    ("Dogo",    "DOGE",  6.0, 1),
]

NOMBRES_HIJOS = ["Nova", "Rayo", "Brasa", "Cobre", "Eco", "Lince", "Puma", "Quetzal",
                 "Volcán", "Jade", "Maya", "Tikal", "Ceiba", "Kukul", "Balam", "Ixchel"]


def ahora():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


# ---------------------------------------------------------------- precios
def precio_coinbase(moneda):
    url = f"https://api.coinbase.com/v2/prices/{moneda}-USD/spot"
    req = urllib.request.Request(url, headers={"User-Agent": "automatonias"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return float(json.load(r)["data"]["amount"])


def obtener_precios(state):
    precios = {}
    for m in MONEDAS:
        if SIMULAR:
            hist = state["historial"].get(m) or [{"BTC": 67000, "ETH": 2600, "SOL": 150, "DOGE": 0.12}[m]]
            precios[m] = hist[-1] * (1 + random.gauss(0, 0.01))
        else:
            for intento in range(3):
                try:
                    precios[m] = precio_coinbase(m)
                    break
                except Exception as e:
                    if intento == 2:
                        print(f"No pude leer {m}: {e}")
                    time.sleep(2)
    return precios


# ---------------------------------------------------------------- utilidades
def ema(valores, n):
    if len(valores) < n:
        return None
    k = 2 / (n + 1)
    e = sum(valores[:n]) / n
    for v in valores[n:]:
        e = v * k + e * (1 - k)
    return e


def equity(bot, precio):
    eq = bot["efectivo"]
    pos = bot.get("posicion")
    if pos and precio:
        eq += pos["margen"] + pos["cantidad"] * (precio - pos["entrada"])
    return eq


def evento(state, texto):
    state["eventos"].insert(0, f"{ahora()} · {texto}")
    del state["eventos"][EVENTOS_MAX:]
    print(texto)


def genes_base(apalancamiento):
    return {
        "ema_rapida": random.randint(5, 12),
        "ema_lenta": random.randint(20, 40),
        "stop_loss": round(random.uniform(0.02, 0.06), 3),
        "take_profit": round(random.uniform(0.04, 0.12), 3),
        "apalancamiento": apalancamiento,
        "uso_capital": round(random.uniform(0.5, 0.9), 2),
    }


def nuevo_bot(state, nombre, moneda, capital, genes, padre=None, gen=1):
    state["contador"] += 1
    return {
        "id": state["contador"],
        "nombre": nombre,
        "moneda": moneda,
        "capital_inicial": round(capital, 2),
        "efectivo": round(capital, 2),
        "posicion": None,
        "genes": genes,
        "padre": padre,
        "generacion": gen,
        "vivo": True,
        "nacio": ahora(),
        "murio": None,
        "operaciones": 0,
        "ganadas": 0,
        "hijos": 0,
        "alerta_50": False,
        "equity": round(capital, 2),
    }


def estado_inicial():
    state = {"creado": ahora(), "contador": 0, "ciclos": 0, "bots": [],
             "historial": {m: [] for m in MONEDAS}, "eventos": [],
             "equity_colonia": [], "alerta_colonia": False}
    for nombre, moneda, capital, apal in FUNDADORES:
        state["bots"].append(nuevo_bot(state, nombre, moneda, capital, genes_base(apal)))
    evento(state, f"Nace la colonia con ${CAPITAL_INICIAL:.0f} y {len(FUNDADORES)} bots fundadores")
    return state


# ---------------------------------------------------------------- vida de un bot
def cerrar(state, bot, precio, motivo):
    pos = bot["posicion"]
    pnl = pos["cantidad"] * (precio - pos["entrada"])
    comision = pos["cantidad"] * precio * COMISION
    bot["efectivo"] += pos["margen"] + pnl - comision
    bot["posicion"] = None
    bot["operaciones"] += 1
    if pnl - comision > 0:
        bot["ganadas"] += 1
    evento(state, f"{bot['nombre']} cierra {bot['moneda']} ({motivo}): {pnl - comision:+.2f} USD")


def abrir(state, bot, precio):
    g = bot["genes"]
    margen = bot["efectivo"] * g["uso_capital"]
    nocional = margen * g["apalancamiento"]
    comision = nocional * COMISION
    if margen < 1:
        return
    bot["efectivo"] -= margen + comision
    bot["posicion"] = {"entrada": precio, "margen": margen, "cantidad": nocional / precio,
                       "abierta": ahora()}
    evento(state, f"{bot['nombre']} compra {bot['moneda']} a {precio:,.4f} "
                  f"(margen ${margen:.2f}, x{g['apalancamiento']})")


def morir(state, bot, motivo):
    bot["vivo"] = False
    bot["murio"] = ahora()
    bot["posicion"] = None
    bot["efectivo"] = max(bot["efectivo"], 0)
    evento(state, f"☠ {bot['nombre']} muere: {motivo}. Solo pierde su propio capital.")


def mutar(genes):
    g = dict(genes)
    g["ema_rapida"] = max(3, g["ema_rapida"] + random.randint(-2, 2))
    g["ema_lenta"] = max(g["ema_rapida"] + 5, g["ema_lenta"] + random.randint(-4, 4))
    g["stop_loss"] = round(min(0.15, max(0.01, g["stop_loss"] * random.uniform(0.8, 1.2))), 3)
    g["take_profit"] = round(min(0.3, max(0.02, g["take_profit"] * random.uniform(0.8, 1.2))), 3)
    g["uso_capital"] = round(min(0.95, max(0.3, g["uso_capital"] + random.uniform(-0.1, 0.1))), 2)
    if random.random() < 0.3:
        g["apalancamiento"] = random.choice([1, 1, 2, 3, 5])
    return g


def replicar(state, padre):
    ganancia = padre["efectivo"] - padre["capital_inicial"]
    dote = ganancia / 2
    padre["efectivo"] -= dote
    padre["capital_inicial"] = round(padre["efectivo"], 2)
    padre["hijos"] += 1
    moneda = padre["moneda"]
    if random.random() < 0.3:
        moneda = random.choice([m for m in MONEDAS if m != padre["moneda"]])
    usados = {b["nombre"] for b in state["bots"]}
    libres = [n for n in NOMBRES_HIJOS if n not in usados] or [f"Bot{state['contador'] + 1}"]
    hijo = nuevo_bot(state, random.choice(libres), moneda, dote, mutar(padre["genes"]),
                     padre=padre["nombre"], gen=padre["generacion"] + 1)
    state["bots"].append(hijo)
    mut = " y MUTA a " + moneda if moneda != padre["moneda"] else ""
    evento(state, f"🧬 {padre['nombre']} se replica: nace {hijo['nombre']} con ${dote:.2f}{mut} "
                  f"(x{hijo['genes']['apalancamiento']})")


def vivir(state, bot, precios):
    precio = precios.get(bot["moneda"])
    if not precio:
        return
    g = bot["genes"]
    pos = bot["posicion"]

    # liquidación: si la posición apalancada se come su margen, el bot muere
    if pos:
        perdida = pos["cantidad"] * (precio - pos["entrada"])
        if pos["margen"] + perdida <= 0:
            bot["efectivo"] += 0
            morir(state, bot, f"liquidado en {bot['moneda']} a {precio:,.4f}")
            return
        cambio = (precio - pos["entrada"]) / pos["entrada"]
        if cambio <= -g["stop_loss"]:
            cerrar(state, bot, precio, "stop loss")
        elif cambio >= g["take_profit"]:
            cerrar(state, bot, precio, "take profit")

    hist = state["historial"][bot["moneda"]]
    rapida, lenta = ema(hist, g["ema_rapida"]), ema(hist, g["ema_lenta"])
    if rapida and lenta:
        if bot["posicion"] and rapida < lenta:
            cerrar(state, bot, precio, "tendencia a la baja")
        elif not bot["posicion"] and rapida > lenta * 1.001:
            abrir(state, bot, precio)

    eq = equity(bot, precio)
    bot["equity"] = round(eq, 2)

    if eq < 1:
        morir(state, bot, "se quedó sin capital")
        return
    if not bot["alerta_50"] and eq <= bot["capital_inicial"] * 0.5:
        bot["alerta_50"] = True
        evento(state, f"⚠ {bot['nombre']} perdió 50% de su capital — revisar a mano")
        with open(ALERT_FILE, "a") as f:
            f.write(f"{bot['nombre']} ({bot['moneda']}) bajó a ${eq:.2f} de ${bot['capital_inicial']:.2f}\n")
    if not bot["posicion"] and eq >= bot["capital_inicial"] * 1.5:
        replicar(state, bot)


# ---------------------------------------------------------------- ciclo
def main():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            state = json.load(f)
    else:
        state = estado_inicial()

    precios = obtener_precios(state)
    if not precios:
        print("Sin precios, salto este ciclo")
        return
    for m, p in precios.items():
        state["historial"][m].append(p)
        del state["historial"][m][:-HISTORIAL_MAX]

    for bot in list(state["bots"]):
        if bot["vivo"]:
            vivir(state, bot, precios)

    total = sum(b["equity"] for b in state["bots"] if b["vivo"])
    state["equity_colonia"].append([ahora(), round(total, 2)])
    del state["equity_colonia"][:-500]
    state["ciclos"] += 1
    state["actualizado"] = ahora()
    state["precios"] = {m: round(p, 6) for m, p in precios.items()}
    state["vivos"] = sum(b["vivo"] for b in state["bots"])

    if not state["alerta_colonia"] and total <= CAPITAL_INICIAL * 0.5:
        state["alerta_colonia"] = True
        evento(state, "🚨 La colonia perdió 50% del capital total — intervención manual")
        with open(ALERT_FILE, "a") as f:
            f.write(f"COLONIA: bajó a ${total:.2f} de ${CAPITAL_INICIAL:.2f}\n")

    with open(STATE_FILE, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)
    print(f"Ciclo {state['ciclos']}: colonia ${total:.2f}, {state['vivos']} bots vivos")


if __name__ == "__main__":
    main()

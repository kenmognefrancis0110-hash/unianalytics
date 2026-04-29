"""
╔══════════════════════════════════════════════════════════════╗
║  app.py — UniAnalytics / PARAEU                             ║
║  Lancement : python3 app.py                                 ║
║  Accès     : http://127.0.0.1:8000                          ║
╚══════════════════════════════════════════════════════════════╝
"""

import sqlite3, os, webbrowser, threading, time
import pandas as pd
import uvicorn

from datetime import datetime
from typing import Optional, List

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

# ═══════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(BASE_DIR, "unianalytics.db")
HOST     = "127.0.0.1"
PORT     = 8000


# ═══════════════════════════════════════════════════════════════
# BASE DE DONNÉES
# ═══════════════════════════════════════════════════════════════

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS etudiants (
            id_etudiant       INTEGER PRIMARY KEY AUTOINCREMENT,
            matricule         TEXT UNIQUE,
            nom               TEXT NOT NULL,
            prenom            TEXT NOT NULL,
            sexe              TEXT DEFAULT 'M',
            filiere           TEXT NOT NULL,
            niveau            TEXT NOT NULL,
            age               INTEGER NOT NULL,
            annee_inscription INTEGER
        );
        CREATE TABLE IF NOT EXISTS sessions_etude (
            id_session     INTEGER PRIMARY KEY AUTOINCREMENT,
            id_etudiant    INTEGER NOT NULL
                               REFERENCES etudiants(id_etudiant) ON DELETE CASCADE,
            date           TEXT NOT NULL,
            heures_etude   REAL NOT NULL,
            heures_sommeil REAL NOT NULL,
            humeur_index   INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS resultats (
            id_resultat   INTEGER PRIMARY KEY AUTOINCREMENT,
            id_etudiant   INTEGER NOT NULL
                              REFERENCES etudiants(id_etudiant) ON DELETE CASCADE,
            code_matiere  TEXT NOT NULL,
            nom_matiere   TEXT NOT NULL,
            note_examen   REAL NOT NULL,
            taux_presence REAL NOT NULL,
            session       TEXT DEFAULT 'S1'
        );
        CREATE TABLE IF NOT EXISTS anciens_etudiants (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            id_etudiant  INTEGER NOT NULL
                             REFERENCES etudiants(id_etudiant) ON DELETE CASCADE,
            cause        TEXT NOT NULL,
            annee_depart INTEGER,
            commentaire  TEXT
        );
    """)
    # Migration douce : ajoute sexe si absente
    try:
        conn.execute("ALTER TABLE etudiants ADD COLUMN sexe TEXT DEFAULT 'M'")
        conn.commit()
    except Exception:
        pass
    conn.commit()
    conn.close()
    print(f"✅  Base SQLite prête : {DB_PATH}")


# ═══════════════════════════════════════════════════════════════
# HELPERS DATAFRAMES
# ═══════════════════════════════════════════════════════════════

def df_resultats() -> pd.DataFrame:
    conn = get_db()
    df = pd.read_sql_query("""
        SELECT r.*, e.nom, e.prenom, e.filiere, e.niveau, e.matricule
        FROM resultats r
        JOIN etudiants e ON e.id_etudiant = r.id_etudiant
    """, conn)
    conn.close()
    return df


def df_sessions() -> pd.DataFrame:
    conn = get_db()
    df = pd.read_sql_query("""
        SELECT s.*, e.nom, e.prenom, e.filiere
        FROM sessions_etude s
        JOIN etudiants e ON e.id_etudiant = s.id_etudiant
    """, conn)
    conn.close()
    return df


def df_anciens() -> pd.DataFrame:
    conn = get_db()
    df = pd.read_sql_query("""
        SELECT ae.*, e.nom, e.prenom, e.filiere, e.matricule,
               AVG(r.note_examen) AS moy_notes
        FROM anciens_etudiants ae
        JOIN etudiants e ON e.id_etudiant = ae.id_etudiant
        LEFT JOIN resultats r ON r.id_etudiant = ae.id_etudiant
        GROUP BY ae.id
    """, conn)
    conn.close()
    return df


# ═══════════════════════════════════════════════════════════════
# ANALYTICS
# ═══════════════════════════════════════════════════════════════

def stats_resume() -> dict:
    conn = get_db()
    nb   = conn.execute("SELECT COUNT(*) FROM etudiants").fetchone()[0]
    conn.close()
    df   = df_resultats()
    if df.empty:
        return {"nb_etudiants": nb, "nb_resultats": 0, "moyenne_generale": 0,
                "note_min": 0, "note_max": 0, "ecart_type": 0,
                "taux_reussite": 0, "taux_risque_abandon": 0}
    n = df["note_examen"]
    p = df["taux_presence"]
    return {
        "nb_etudiants":        nb,
        "nb_resultats":        len(df),
        "moyenne_generale":    round(float(n.mean()), 2),
        "note_min":            round(float(n.min()),  2),
        "note_max":            round(float(n.max()),  2),
        "ecart_type":          round(float(n.std()),  2) if pd.notna(n.std()) else 0.0,
        "taux_reussite":       round(float((n >= 10).mean() * 100), 1),
        "taux_risque_abandon": round(float((p < 25).mean()  * 100), 1),
    }


def stats_distribution(filiere: Optional[str] = None) -> dict:
    df = df_resultats()
    if filiere:
        df = df[df["filiere"] == filiere]
    if df.empty:
        return {"labels": [], "values": [], "filiere": filiere or "Toutes"}
    bins   = [0, 5, 10, 12, 14, 16, 18, 20.01]
    labels = ["0-5","5-10","10-12","12-14","14-16","16-18","18-20"]
    cuts   = pd.cut(df["note_examen"], bins=bins, labels=labels, right=False)
    values = cuts.value_counts().reindex(labels, fill_value=0).tolist()
    return {"labels": labels, "values": [int(v) for v in values],
            "filiere": filiere or "Toutes"}


def stats_filieres() -> dict:
    df = df_resultats()
    if df.empty:
        return {"filieres": []}
    grp  = df.groupby("filiere").agg(
        moyenne=("note_examen","mean"), note_min=("note_examen","min"),
        note_max=("note_examen","max"), ecart_type=("note_examen","std"),
        nb_notes=("note_examen","count"),
    ).reset_index()
    nb_e = df.groupby("filiere")["id_etudiant"].nunique().rename("nb_etudiants")
    taux = df.groupby("filiere").apply(
        lambda g: round(float((g["note_examen"] >= 10).mean() * 100), 1)
    ).rename("taux_reussite")
    grp = grp.join(nb_e, on="filiere").join(taux, on="filiere")
    result = []
    for _, r in grp.iterrows():
        result.append({
            "filiere":       r["filiere"],
            "moyenne":       round(float(r["moyenne"]),  2),
            "note_min":      round(float(r["note_min"]), 2),
            "note_max":      round(float(r["note_max"]), 2),
            "ecart_type":    round(float(r["ecart_type"]), 2) if pd.notna(r["ecart_type"]) else 0.0,
            "nb_notes":      int(r["nb_notes"]),
            "nb_etudiants":  int(r["nb_etudiants"]),
            "taux_reussite": float(r["taux_reussite"]),
        })
    result.sort(key=lambda x: x["moyenne"], reverse=True)
    return {"filieres": result}


def stats_risque(seuil: float = 25.0) -> dict:
    df = df_resultats()
    if df.empty:
        return {"a_risque": [], "nb_a_risque": 0, "nb_total": 0,
                "taux_risque": 0, "seuil_presence": seuil}
    pres    = df.groupby("id_etudiant")["taux_presence"].mean().rename("moy_presence")
    note    = df.groupby("id_etudiant")["note_examen"].mean().rename("moy_note")
    infos   = df.groupby("id_etudiant").first()[["nom","prenom","filiere","matricule"]]
    merged  = pd.concat([pres, note, infos], axis=1).reset_index()
    risques = merged[merged["moy_presence"] < seuil]
    details = []
    for _, r in risques.iterrows():
        details.append({
            "id_etudiant":  int(r["id_etudiant"]),
            "nom":          f"{r['prenom']} {r['nom']}",
            "matricule":    r.get("matricule",""),
            "filiere":      r["filiere"],
            "moy_presence": round(float(r["moy_presence"]), 1),
            "moy_note":     round(float(r["moy_note"]),     2),
        })
    return {
        "a_risque":       details,
        "nb_a_risque":    len(details),
        "nb_total":       len(merged),
        "taux_risque":    round(len(details)/len(merged)*100, 1) if len(merged) else 0,
        "seuil_presence": seuil,
    }


def stats_anciens() -> dict:
    df = df_anciens()
    if df.empty:
        return {"anciens":[],"total":0,"fin_parcours":0,"abandon":0,"echec_scolaire":0}
    result = []
    for _, r in df.iterrows():
        result.append({
            "id":          int(r["id"]),
            "id_etudiant": int(r["id_etudiant"]),
            "nom":         f"{r['prenom']} {r['nom']}",
            "matricule":   r.get("matricule",""),
            "filiere":     r.get("filiere",""),
            "cause":       r["cause"],
            "promo":       str(int(r["annee_depart"])) if pd.notna(r.get("annee_depart")) else "—",
            "note":        r.get("commentaire",""),
            "moy":         round(float(r["moy_notes"]),2) if pd.notna(r.get("moy_notes")) else 0.0,
        })
    counts = df["cause"].value_counts()
    return {
        "anciens":        result,
        "total":          len(result),
        "fin_parcours":   int(counts.get("fin_parcours",  0)),
        "abandon":        int(counts.get("abandon",       0)),
        "echec_scolaire": int(counts.get("echec_scolaire",0)),
    }


def stats_correlation() -> dict:
    df_r = df_resultats()
    df_s = df_sessions()
    if df_r.empty or df_s.empty:
        return {"points": [], "nb_etudiants": 0}
    moy_n  = df_r.groupby("id_etudiant")["note_examen"].mean().rename("note")
    moy_h  = df_s.groupby("id_etudiant")["heures_etude"].mean().rename("heures_etude")
    infos  = df_r.groupby("id_etudiant").first()[["nom","prenom","filiere"]]
    merged = pd.concat([moy_n, moy_h, infos], axis=1).dropna()
    points = []
    for eid, r in merged.iterrows():
        points.append({
            "id_etudiant":  int(eid),
            "nom":          f"{r['prenom']} {r['nom']}",
            "filiere":      r["filiere"],
            "heures_etude": round(float(r["heures_etude"]), 2),
            "note":         round(float(r["note"]),         2),
        })
    return {"points": points, "nb_etudiants": len(points)}


def stats_prediction(id_etudiant: int) -> dict:
    conn = get_db()
    df_s = pd.read_sql_query(
        "SELECT heures_etude FROM sessions_etude WHERE id_etudiant=?",
        conn, params=(id_etudiant,))
    df_r = pd.read_sql_query(
        "SELECT note_examen FROM resultats WHERE id_etudiant=?",
        conn, params=(id_etudiant,))
    conn.close()
    if df_s.empty or df_r.empty:
        raise HTTPException(404, "Données insuffisantes")
    moy_note  = float(df_r["note_examen"].mean())
    moy_etude = float(df_s["heures_etude"].mean())
    return {
        "id_etudiant":   id_etudiant,
        "note_actuelle": round(moy_note,  2),
        "note_predite":  round(moy_note,  2),
        "conseils":      ["Maintenez ce rythme !"] if moy_note >= 10
                         else ["Augmentez vos heures d'étude."]
    }


# ═══════════════════════════════════════════════════════════════
# MODÈLES PYDANTIC
# ═══════════════════════════════════════════════════════════════

class EtudiantCreate(BaseModel):
    nom:               str = Field(..., min_length=1)
    prenom:            str = Field(..., min_length=1)
    sexe:              Optional[str] = "M"
    filiere:           str
    niveau:            str
    age:               int = Field(..., ge=17, le=60)
    annee_inscription: Optional[int] = None


class EtudiantUpdate(BaseModel):
    nom:     Optional[str] = None
    prenom:  Optional[str] = None
    sexe:    Optional[str] = None
    filiere: Optional[str] = None
    niveau:  Optional[str] = None
    age:     Optional[int] = Field(None, ge=17, le=60)


class SessionCreate(BaseModel):
    id_etudiant:    int
    date:           str
    heures_etude:   float = Field(..., ge=0, le=24)
    heures_sommeil: float = Field(7.0,  ge=0, le=24)
    humeur_index:   int   = Field(...,  ge=1, le=5)


class ResultatItem(BaseModel):
    code_matiere:  str
    nom_matiere:   str
    note_examen:   float = Field(..., ge=0, le=20)
    taux_presence: float = Field(100.0, ge=0, le=100)


class ResultatBatch(BaseModel):
    id_etudiant: int
    session:     Optional[str] = "S1"
    matieres:    List[ResultatItem] = Field(..., min_length=1)


class AncienCreate(BaseModel):
    id_etudiant:  int
    cause:        str
    annee_depart: Optional[int] = None
    commentaire:  Optional[str] = ""


# ═══════════════════════════════════════════════════════════════
# APPLICATION
# ═══════════════════════════════════════════════════════════════

app = FastAPI(title="UniAnalytics", version="4.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)


@app.on_event("startup")
def startup():
    init_db()
    _ecrire_fichiers_frontend()


# ─── UTILITAIRES ──────────────────────────────────────────────

@app.get("/ping")
def ping():
    return {"status": "ok", "db": DB_PATH}


@app.get("/info")
def info():
    return {"status": "ok",
            "date":  datetime.now().strftime("%d/%m/%Y"),
            "heure": datetime.now().strftime("%H:%M:%S")}


# ─── ÉTUDIANTS ────────────────────────────────────────────────

@app.get("/etudiants")
def lister_etudiants(filiere: Optional[str] = None):
    conn = get_db()
    q    = "SELECT * FROM etudiants WHERE filiere=? ORDER BY id_etudiant" if filiere \
           else "SELECT * FROM etudiants ORDER BY id_etudiant"
    rows = conn.execute(q, (filiere,) if filiere else ()).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/etudiants/{id_etudiant}")
def get_etudiant(id_etudiant: int):
    conn = get_db()
    row  = conn.execute(
        "SELECT * FROM etudiants WHERE id_etudiant=?", (id_etudiant,)
    ).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Étudiant non trouvé")
    return dict(row)


@app.post("/etudiants", status_code=201)
def creer_etudiant(data: EtudiantCreate):
    conn = get_db()
    try:
        nid       = conn.execute(
            "SELECT COALESCE(MAX(id_etudiant),0)+1 FROM etudiants"
        ).fetchone()[0]
        matricule = f"CM{nid:04d}"
        cur = conn.execute(
            """INSERT INTO etudiants
               (nom,prenom,sexe,filiere,niveau,age,annee_inscription,matricule)
               VALUES (?,?,?,?,?,?,?,?)""",
            (data.nom, data.prenom, data.sexe or "M",
             data.filiere, data.niveau, data.age,
             data.annee_inscription, matricule)
        )
        conn.commit()
        return {"message":"Succès","id_etudiant":cur.lastrowid,
                "matricule":matricule,"status":"success"}
    except Exception as e:
        conn.rollback()
        raise HTTPException(400, f"Erreur : {e}")
    finally:
        conn.close()


@app.put("/etudiants/{id_etudiant}")
def modifier_etudiant(id_etudiant: int, data: EtudiantUpdate):
    conn    = get_db()
    updates = {k: v for k, v in data.dict().items() if v is not None}
    if not updates:
        conn.close()
        raise HTTPException(400, "Aucun champ à modifier")
    fields = [f"{k} = ?" for k in updates]
    vals   = list(updates.values()) + [id_etudiant]
    conn.execute(f"UPDATE etudiants SET {', '.join(fields)} WHERE id_etudiant=?", vals)
    conn.commit()
    conn.close()
    return {"message": "Modifié avec succès"}


@app.delete("/etudiants/{id_etudiant}")
def supprimer_etudiant(id_etudiant: int):
    conn = get_db()
    conn.execute("DELETE FROM etudiants WHERE id_etudiant=?", (id_etudiant,))
    conn.commit()
    conn.close()
    return {"message": "Étudiant supprimé"}


@app.post("/etudiants/archiver-m2")
def archiver_m2():
    conn  = get_db()
    annee = datetime.now().year
    ids   = conn.execute(
        "SELECT id_etudiant FROM etudiants WHERE niveau='M2'"
    ).fetchall()
    ok, ko = 0, 0
    for (eid,) in ids:
        res = conn.execute(
            "SELECT AVG(note_examen) FROM resultats WHERE id_etudiant=?", (eid,)
        ).fetchone()[0] or 0
        cause = "fin_parcours" if res >= 10 else "echec_scolaire"
        conn.execute(
            "INSERT INTO anciens_etudiants(id_etudiant,cause,annee_depart,commentaire)"
            " VALUES(?,?,?,?)",
            (eid, cause, annee, f"Clôture M2 {annee} — {round(res,2)}/20")
        )
        conn.execute("DELETE FROM etudiants WHERE id_etudiant=?", (eid,))
        if cause == "fin_parcours": ok += 1
        else: ko += 1
    conn.commit()
    conn.close()
    return {"message": f"{ok} diplômé(s), {ko} en échec archivé(s)."}


# ─── SESSIONS ─────────────────────────────────────────────────

@app.post("/sessions", status_code=201)
def creer_session(data: SessionCreate):
    conn = get_db()
    conn.execute(
        "INSERT INTO sessions_etude(id_etudiant,date,heures_etude,heures_sommeil,humeur_index)"
        " VALUES(?,?,?,?,?)",
        (data.id_etudiant, data.date, data.heures_etude,
         data.heures_sommeil, data.humeur_index)
    )
    conn.commit()
    conn.close()
    return {"message": "Session enregistrée"}


@app.get("/sessions/{id_etudiant}")
def get_sessions(id_etudiant: int):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM sessions_etude WHERE id_etudiant=? ORDER BY date DESC",
        (id_etudiant,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ─── RÉSULTATS ────────────────────────────────────────────────

@app.post("/resultats/batch", status_code=201)
def resultats_batch(data: ResultatBatch):
    if len(data.matieres) < 5:
        raise HTTPException(400, "Minimum 5 matières requises")
    conn = get_db()
    if not conn.execute(
        "SELECT 1 FROM etudiants WHERE id_etudiant=?", (data.id_etudiant,)
    ).fetchone():
        conn.close()
        raise HTTPException(404, f"Étudiant #{data.id_etudiant} introuvable")
    try:
        for m in data.matieres:
            conn.execute(
                "INSERT INTO resultats"
                "(id_etudiant,code_matiere,nom_matiere,note_examen,taux_presence,session)"
                " VALUES(?,?,?,?,?,?)",
                (data.id_etudiant, m.code_matiere, m.nom_matiere,
                 m.note_examen, m.taux_presence, data.session)
            )
        conn.commit()
        return {"message": f"{len(data.matieres)} résultats enregistrés",
                "nb_matieres": len(data.matieres)}
    except Exception as e:
        conn.rollback()
        raise HTTPException(400, str(e))
    finally:
        conn.close()


@app.get("/resultats/{id_etudiant}")
def get_resultats(id_etudiant: int):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM resultats WHERE id_etudiant=?", (id_etudiant,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ─── ANCIENS ──────────────────────────────────────────────────

@app.post("/anciens", status_code=201)
def creer_ancien(data: AncienCreate):
    conn = get_db()
    conn.execute(
        "INSERT INTO anciens_etudiants(id_etudiant,cause,annee_depart,commentaire)"
        " VALUES(?,?,?,?)",
        (data.id_etudiant, data.cause, data.annee_depart, data.commentaire)
    )
    conn.commit()
    conn.close()
    return {"message": "Départ enregistré"}


@app.get("/anciens")
def lister_anciens():
    return stats_anciens()


# ─── ANALYTICS ────────────────────────────────────────────────

@app.get("/analytics/resume")
def api_resume():
    return stats_resume()


@app.get("/analytics/distribution-notes")
def api_distribution(filiere: Optional[str] = None):
    return stats_distribution(filiere)


@app.get("/analytics/performance-par-filiere")
def api_filieres():
    return stats_filieres()


@app.get("/analytics/risque-abandon")
def api_risque(seuil_presence: float = 25.0):
    return stats_risque(seuil_presence)


@app.get("/analytics/correlation-etude-note")
def api_correlation():
    return stats_correlation()


@app.get("/analytics/prediction/{id_etudiant}")
def api_prediction(id_etudiant: int):
    return stats_prediction(id_etudiant)


# ═══════════════════════════════════════════════════════════════
# FRONTEND — fichiers HTML/JS générés automatiquement
# ═══════════════════════════════════════════════════════════════

def _ecrire_fichiers_frontend():
    """Écrit api.js (corrigé) et vérifie les HTML dans le dossier courant."""

    api_js = r"""/**
 * api.js — UniAnalytics PARAEU — VERSION CORRIGÉE
 */
const API_BASE = localStorage.getItem('api_url') || 'http://127.0.0.1:8000';

(function(){
  const t = localStorage.getItem('theme') || 'dark';
  document.documentElement.setAttribute('data-theme', t);
})();

async function apiGet(path) {
  const r = await fetch(API_BASE + path, { signal: AbortSignal.timeout(5000) });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

async function apiPost(path, body) {
  const r = await fetch(API_BASE + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(5000)
  });
  const data = await r.json();
  if (!r.ok) {
    let msg = data.detail;
    if (Array.isArray(msg)) msg = msg.map(e => `${e.loc[e.loc.length-1]} invalide`).join(' | ');
    throw new Error(msg || 'Erreur serveur');
  }
  return data;
}

async function apiPut(path, body) {
  const r = await fetch(API_BASE + path, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(5000)
  });
  const data = await r.json();
  if (!r.ok) throw new Error(data.detail || 'Erreur serveur');
  return data;
}

async function apiDelete(path) {
  const r = await fetch(API_BASE + path, { method: 'DELETE' });
  return r.json();
}

let API_OK = false;

async function checkAPI() {
  try {
    const r = await fetch(API_BASE + '/ping', { signal: AbortSignal.timeout(2000) });
    API_OK = r.ok;
  } catch { API_OK = false; }

  ['api-dot','api-dot2'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.className = 'api-dot' + (API_OK ? '' : ' off');
  });
  const lbl = document.getElementById('api-label');
  if (lbl) lbl.textContent = API_OK ? 'API EN LIGNE' : 'MODE DÉMO';
  return API_OK;
}

function toast(msg, err = false) {
  const t = document.getElementById('toast');
  if (!t) return;
  t.textContent = msg;
  t.className = 'show' + (err ? ' err' : '');
  setTimeout(() => { t.className = ''; }, 3500);
}

function getChartColors() {
  const cs = getComputedStyle(document.documentElement);
  return {
    accent:  cs.getPropertyValue('--accent').trim()  || '#38bdf8',
    accent2: cs.getPropertyValue('--accent2').trim() || '#818cf8',
    green:   cs.getPropertyValue('--green').trim()   || '#34d399',
    red:     cs.getPropertyValue('--red').trim()     || '#f87171',
    yellow:  cs.getPropertyValue('--yellow').trim()  || '#fbbf24',
    text2:   cs.getPropertyValue('--text2').trim()   || '#94a3b8',
    border:  cs.getPropertyValue('--border').trim()  || '#1f2d4a',
  };
}

const CHARTS = {};
function destroyChart(id) {
  if (CHARTS[id]) { CHARTS[id].destroy(); delete CHARTS[id]; }
}

const _bc = (typeof BroadcastChannel !== 'undefined')
  ? new BroadcastChannel('unianalytics') : null;

function broadcastRefresh(type) {
  if (_bc) _bc.postMessage({ type: type || 'refresh', ts: Date.now() });
}

if (_bc) {
  _bc.onmessage = (ev) => {
    if (ev.data.type === 'refresh') {
      if (typeof loadDashboard   === 'function') loadDashboard();
      if (typeof loadPerformance === 'function') loadPerformance();
      if (typeof loadAnciens     === 'function') loadAnciens();
      if (typeof loadEtudiants   === 'function') loadEtudiants();
    }
  };
}
"""

    api_path = os.path.join(BASE_DIR, "api.js")
    with open(api_path, "w", encoding="utf-8") as f:
        f.write(api_js)
    print("✅  api.js corrigé écrit")

    # Vérifier que les HTML existent
    pages = ["index.html","collecte.html","recherche.html",
             "performance.html","anciens.html","parametres.html"]
    manquants = [p for p in pages if not os.path.exists(os.path.join(BASE_DIR, p))]
    if manquants:
        print(f"⚠️   Fichiers HTML manquants : {', '.join(manquants)}")
        print("     Place tes fichiers HTML dans le même dossier que app.py")
    else:
        print(f"✅  {len(pages)} pages HTML trouvées")


# ─── Servir les fichiers statiques (HTML, JS, CSS, images) ────
# IMPORTANT : ce mount doit être en DERNIER pour ne pas écraser les routes API
app.mount("/", StaticFiles(directory=BASE_DIR, html=True), name="static")


# ═══════════════════════════════════════════════════════════════
# LANCEMENT
# ═══════════════════════════════════════════════════════════════

def _ouvrir_navigateur():
    """Ouvre le navigateur 1,5 s après le démarrage du serveur."""
    time.sleep(1.5)
    webbrowser.open(f"http://{HOST}:{PORT}/index.html")


if __name__ == "__main__":
    print("╔══════════════════════════════════════════╗")
    print("║      UniAnalytics / PARAEU  v4.0         ║")
    print("╠══════════════════════════════════════════╣")
    print(f"║  API  →  http://{HOST}:{PORT}            ║")
    print(f"║  App  →  http://{HOST}:{PORT}/index.html ║")
    print("║  Stop →  Ctrl + C                        ║")
    print("╚══════════════════════════════════════════╝")

    # Ouvre le navigateur dans un thread séparé
    threading.Thread(target=_ouvrir_navigateur, daemon=True).start()

    uvicorn.run(
        "app:app",
        host=HOST,
        port=PORT,
        reload=False,      # False car on génère api.js au startup
        log_level="info"
    )

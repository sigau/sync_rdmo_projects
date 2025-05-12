#!/usr/bin/env python3
# -*- coding: utf-8 -*
import os
import json
import shutil
import subprocess
import traceback
import requests
from pathlib import Path
from datetime import datetime
from git import Repo


##########################################################################################################################################################################################################################################################################################
####   Récupère les variables d'environnement
##########################################################################################################################################################################################################################################################################################

TOKEN = os.environ["TOKENRDMO"]
MYRDMO = os.environ["MYRDMO"]

HEADERS = {"Authorization": f"Token {TOKEN}"}
LISTE_PROJET_URL = f"{MYRDMO}/api/v1/projects/projects/"
LISTE_FILE = "liste_projet.json"
OLD_LISTE_FILE = "old_liste_projet.json"



##########################################################################################################################################################################################################################################################################################
####   definition des fonctions
##########################################################################################################################################################################################################################################################################################

def run_curl(url, output_file):
    cmd = [
        "curl", "-s", "-w", "%{http_code}", "-LH", f"Authorization: Token {TOKEN}", url
    ]
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        http_code = result.stdout[-3:]
        body = result.stdout[:-3]

        if http_code != "200":
            print(f"[ERREUR] Code HTTP {http_code} pour {url}")
            print(f"[DEBUG] Réponse : {body[:500]}...")  # Tronque pour pas spammer
            raise Exception(f"Échec HTTP {http_code}")

        with open(output_file, "w", encoding="utf-8") as f:
            f.write(body)

    except subprocess.CalledProcessError as e:
        print(f"[ERREUR] curl a échoué pour {url}")
        raise


def safe_title(title):
    return title.replace(" ", "_").replace("/", "-")

def fetch_all_projects():
    headers = {"Authorization": f"Token {TOKEN}"}
    url = LISTE_PROJET_URL
    all_results = []

    while url:
        print(f"[INFO] Téléchargement de {url}")
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            print(f"[ERREUR] Code HTTP {response.status_code} pour {url}")
            print(f"[DEBUG] Réponse : {response.text[:500]}...")
            raise Exception(f"Échec HTTP {response.status_code}")

        data = response.json()
        all_results.extend(data.get("results", []))
        url = data.get("next")

    with open(LISTE_FILE, "w", encoding="utf-8") as f:
        json.dump({"results": all_results}, f, ensure_ascii=False, indent=2)


def parse_projects(filename):
    with open(filename, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {
        proj["id"]: {
            "title": proj["title"],
            "last_changed": proj["last_changed"]
        }
        for proj in data["results"]
    }

def download_and_commit_project(project_id, title):
    from time import sleep

    folder = Path(f"{project_id}_{safe_title(title)}")
    folder.mkdir(exist_ok=True)
    output_file = folder / f"{safe_title(title)}.json"

    url = f"{MYRDMO}/api/v1/projects/projects/{project_id}/values"
    run_curl(url, str(output_file))

    sleep(0.5)  # Pour éviter les problèmes de détection de fichier
    if not output_file.exists():
        print(f"[ERREUR] Le fichier {output_file} n’a pas été créé.")
        return

    if not (folder / ".git").exists():
        repo = Repo.init(folder)
    else:
        repo = Repo(folder)

    original_dir = os.getcwd()
    try:
        os.chdir(folder)
        repo.index.add([output_file.name])
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        repo.index.commit(f"Update on {now}")
    except Exception as e:
        print(f"[ERREUR] Git add/commit a échoué pour {output_file} : {e}")
        print(f"[DEBUG] Répertoire courant : {os.getcwd()}")
        import traceback
        traceback.print_exc()
    finally:
        os.chdir(original_dir)

##########################################################################################################################################################################################################################################################################################
####   Début du script
##########################################################################################################################################################################################################################################################################################


# Étape 1 : Télécharger tous les projets paginés
fetch_all_projects()

# Étape 2 : Extraire les projets
projects = parse_projects(LISTE_FILE)

# Étape 3 : Vérifier si old_liste_projet.json existe
if not Path(OLD_LISTE_FILE).exists():
    shutil.move(LISTE_FILE, OLD_LISTE_FILE)
    for pid, info in projects.items():
        print(f"[INIT] Téléchargement du projet {info['title']}")
        download_and_commit_project(pid, info["title"])
else:
    old_projects = parse_projects(OLD_LISTE_FILE)
    for pid, info in projects.items():
        title = info["title"]
        new_date = info["last_changed"]
        old_date = old_projects.get(pid, {}).get("last_changed")

        if old_date != new_date:
            print(f"[UPDATE] {title} a changé ({old_date} -> {new_date})")
            download_and_commit_project(pid, title)
        else:
            print(f"[SKIP] {title} pas modifié")

    # Mise à jour du fichier de référence
    shutil.copyfile(LISTE_FILE, OLD_LISTE_FILE)
'''
Put in `/path/to/rdmo-app/scripts/export_projects.py`.
Call with `./manage.py runscript export_projects --script-args ~/rdmo_exports`.
'''

from pathlib import Path

from django.contrib.auth.models import User
from django.test import RequestFactory

from rdmo.core.exports import XMLResponse
from rdmo.projects.models import Project
from rdmo.projects.views import ProjectExportView
from rdmo.questions.models import Catalog
from rdmo.questions.renderers import CatalogRenderer
from rdmo.questions.serializers.export import CatalogExportSerializer

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

TOKEN = os.environ["tokenrdmo"]
MYRDMO = os.environ["myrdmo"]

HEADERS = {"Authorization": f"Token {TOKEN}"}
LISTE_PROJET_URL = f"{MYRDMO}/api/v1/projects/projects/"
LISTE_FILE = "/var/www/rdmo/rdmo-app/static_root/rdmo_project_export/liste_projet.json"
OLD_LISTE_FILE = "/var/www/rdmo/rdmo-app/static_root/rdmo_project_export/old_liste_projet.json"


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
        #print(f"[INFO] Téléchargement de {url}")
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


def commit_project(project_folder,project_xml_path):
    ##init the git 
    if not (project_folder / ".git").exists():
        repo = Repo.init(project_folder)
    else:
        repo = Repo(project_folder)

    original_dir = os.getcwd()
    try:
        os.chdir(project_folder)
        repo.index.add([project_xml_path.name])
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        repo.index.commit(f"Update on {now}")
    except Exception as e:
        print(f"[ERREUR] Git add/commit a échoué pour {project_xml_path} : {e}")
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
projects_json = parse_projects(LISTE_FILE)

# dict to cache the rendered catalogs
catalogs = {}

def run(path):


    base_path = Path.cwd() / 'projects' if path is None else Path(path)
    projects = Project.objects.all()

    if not Path(OLD_LISTE_FILE).exists():
        shutil.move(LISTE_FILE, OLD_LISTE_FILE)
        for project in projects:
            project_path = base_path / str(project.id)
            project_path.mkdir(exist_ok=True, parents=True)

            project_xml_path = project_path / 'project.xml'
            if not project_xml_path.exists():
                project_xml = export_project(project.id)
                with project_xml_path.open('w') as fp:
                    fp.write(project_xml)

            catalog_xml_path = project_path / 'catalog.xml'
            if not catalog_xml_path.exists():
                catalog_xml = export_catalog(project.catalog.id)
                with catalog_xml_path.open('w') as fp:
                    fp.write(catalog_xml)
            commit_project(project_path,project_xml_path)
    else:
        old_projects = parse_projects(OLD_LISTE_FILE)
        for pid, info in projects_json.items():
            title = info["title"]
            new_date = info["last_changed"]
            old_date = old_projects.get(pid, {}).get("last_changed")

            if old_date != new_date:
                print(f"[UPDATE] {title} a changé ({old_date} -> {new_date})")
                project_path = base_path / str(pid)
                project_path.mkdir(exist_ok=True, parents=True)

                project_xml_path = project_path / 'project.xml'
                project_xml = export_project(pid)
                with project_xml_path.open('w') as fp:
                    fp.write(project_xml)
                commit_project(project_path,project_xml_path)
            #else:
            #    print(f"[SKIP] {title} pas modifié")
        
    # Mise à jour du fichier de référence
    shutil.copyfile(LISTE_FILE, OLD_LISTE_FILE)

def export_project(project_id):
    factory = RequestFactory()
    request = factory.get('/dummy-url/')
    request.user = User.objects.filter(is_superuser=True).first()
    view = ProjectExportView.as_view()
    response = view(request, pk=project_id, format='xml')
    return response.content.decode()


def export_catalog(catalog_id):
    if catalog_id not in catalogs:
        catalog = Catalog.objects.get(id=catalog_id)
        catalog.prefetch_elements()
        serializer = CatalogExportSerializer(catalog)
        xml = CatalogRenderer().render([serializer.data], context={
            'sections': True,
            'pages': True,
            'questionsets': True,
            'questions': True,
            'attributes': True,
            'optionsets': True,
            'options': True,
            'conditions': True
        })
        catalogs[catalog_id] = XMLResponse(xml, name='catalogs').content.decode()

    return catalogs[catalog_id]

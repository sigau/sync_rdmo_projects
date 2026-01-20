from pathlib import Path
from datetime import datetime
from git import Repo, Actor
import hashlib
import os

from django.contrib.auth.models import User
from django.test import RequestFactory

from rdmo.core.exports import XMLResponse
from rdmo.projects.models import Project
from rdmo.projects.views import ProjectExportView
from rdmo.questions.models import Catalog
from rdmo.questions.renderers import CatalogRenderer
from rdmo.questions.serializers.export import CatalogExportSerializer

# dict to cache the rendered catalogs
catalogs = {}


def run(path):
    base_path = Path.cwd() / 'projects' if path is None else Path(path)
    projects = Project.objects.all()

    print(f"[INFO] Export de {projects.count()} projets vers {base_path}")

    for project in projects:
        print(f"\n[INFO] Traitement du projet {project.id} : {project.title}")
        project_path = base_path / str(project.id)
        project_path.mkdir(exist_ok=True, parents=True)

        files_to_commit = []

        # --- Project XML ---
        project_xml_path = project_path / 'project.xml'
        project_xml = export_project(project.id)
        if write_if_changed(project_xml_path, project_xml):
            print(f"[INFO] project.xml modifié pour {project.title}")
            files_to_commit.append(project_xml_path)
        else:
            print(f"[SKIP] project.xml inchangé pour {project.title}")

        # --- Catalog XML ---
        catalog_xml_path = project_path / 'catalog.xml'
        catalog_xml = export_catalog(project.catalog.id)
        if write_if_changed(catalog_xml_path, catalog_xml):
            print(f"[INFO] catalog.xml modifié pour {project.title}")
            files_to_commit.append(catalog_xml_path)
        else:
            print(f"[SKIP] catalog.xml inchangé pour {project.title}")

        # --- Commit si des fichiers ont changé ---
        if files_to_commit:
            git_commit_project(project_path, files_to_commit, project)
        else:
            print(f"[INFO] Aucun changement détecté pour {project.title}, pas de commit.")


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


def write_if_changed(path: Path, new_content: str) -> bool:
    """Écrit le fichier seulement si le contenu a changé. Retourne True si modifié."""
    new_hash = hashlib.md5(new_content.encode("utf-8")).hexdigest()
    if path.exists():
        old_hash = hashlib.md5(path.read_bytes()).hexdigest()
        if old_hash == new_hash:
            return False  # Pas de changement

    with path.open('w', encoding='utf-8') as f:
        f.write(new_content)
    return True


def git_commit_project(project_path: Path, files, project):
    """Initialise un repo git dans le dossier du projet et commit tous les fichiers modifiés en un seul commit"""
    if not (project_path / ".git").exists():
        repo = Repo.init(project_path)
        print(f"[GIT] Nouveau dépôt initialisé dans {project_path}")
    else:
        repo = Repo(project_path)

    original_dir = Path.cwd()
    try:
        os.chdir(project_path)

        repo.index.add([f.name for f in files])

        # Récupération de la date de dernière modification RDMO
        last_mod = getattr(project, "last_modified", None) or datetime.now()

        # Conversion si c’est une chaîne ISO
        if isinstance(last_mod, str):
            try:
                last_mod = datetime.fromisoformat(last_mod)
            except ValueError:
                try:
                    from dateutil import parser
                    last_mod = parser.parse(last_mod)
                except Exception:
                    last_mod = datetime.now()

        print(f"[GIT] Commit en préparation pour {project.title} ({project.id})")
        print(f"       - Fichiers : {[f.name for f in files]}")
        print(f"       - Date utilisée : {last_mod} (type={type(last_mod)})")
        print(f"       - Repo : {project_path}")

        commit_msg = f"Update project {project.id} ({project.title}) on {last_mod.strftime('%Y-%m-%d %H:%M:%S')}"

        # Utiliser la date RDMO comme date du commit git
        author = Actor("RDMO Export", "rdmo@example.com")
        repo.index.commit(
            commit_msg,
            author=author,
            committer=author,
            author_date=last_mod,
            commit_date=last_mod,
        )

        print(f"[GIT] ✅ Commit effectué pour {project.title} ({project.id}) à {last_mod}")
    except Exception as e:
        print(f"[ERREUR] Git add/commit a échoué pour {project.title} : {e}")
    finally:
        os.chdir(original_dir)

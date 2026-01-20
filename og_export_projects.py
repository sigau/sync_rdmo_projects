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

# dict to cache the rendered catalogs
catalogs = {}

def run(path):
    base_path = Path.cwd() / 'projects' if path is None else Path(path)
    projects = Project.objects.all()

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

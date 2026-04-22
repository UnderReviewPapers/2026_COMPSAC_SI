import os, traceback
from tempfile import NamedTemporaryFile
from rest_framework.decorators import api_view
from rest_framework.response import Response
from django.shortcuts import render
from rest_framework import status
from utilities.bpmn_importer import BPMNImporterXmlBased

def importer_home(request):
    return render(request, 'importer/home.html')


@api_view(['POST'])
def upload_imported_diagram(request):
    name = request.data.get('name')
    xml  = request.data.get('xml_content')
    if not name or not xml:
        return Response({'error': 'Missing name or xml_content'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        with NamedTemporaryFile(mode='w+', suffix=".bpmn", delete=False, encoding='utf-8') as tmp:
            tmp.write(xml)
            tmp.flush()
            tmp_path = tmp.name

        servers = [{"url": request.build_absolute_uri("/").rstrip("/")}]
        importer = BPMNImporterXmlBased(bpmn_path=tmp_path, name=name, servers=servers)
        result = importer.import_all()

        os.remove(tmp_path)
        return Response(result, status=status.HTTP_200_OK)

    except Exception as e:
        traceback.print_exc()  # stampa traceback completo
        return Response(
            {'error': f'{type(e).__name__}: {e}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

def import_summary(request):
    return render(request, 'importer/summary.html', {
        'diagram_id': request.GET.get('diagram_id'),
        'atomic': request.GET.get('atomic', 0),
        'cpps': request.GET.get('cpps', 0),
        'cppn': request.GET.get('cppn', 0)
    })


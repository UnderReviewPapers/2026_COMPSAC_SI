from django.shortcuts import render
from rest_framework.decorators import api_view
from rest_framework.response import Response
from utilities.mongodb_handler import bpmn_collection

def homepage_view(request):
    return render(request, 'homepage.html')
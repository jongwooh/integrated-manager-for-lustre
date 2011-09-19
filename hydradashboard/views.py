
# ==============================
# Copyright 2011 Whamcloud, Inc.
# ==============================

# Create your views here.
from django.core.management import setup_environ
from django.shortcuts import render_to_response
from django.template import RequestContext

import settings
setup_environ(settings)

def dashboard(request):
    return render_to_response("index.html",
            RequestContext(request, {}))


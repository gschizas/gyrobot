"""The Jinja environment shared by the web UI routers."""
import json
import pathlib

from fastapi.templating import Jinja2Templates

from webapp.capabilities import can

templates = Jinja2Templates(directory=str(pathlib.Path(__file__).parent / 'templates'))
templates.env.filters['tojson'] = json.dumps
templates.env.globals['can'] = can

"""Inicia no Windows com o ambiente do arquivo .env do projeto."""
from pathlib import Path
import runpy

from dotenv import load_dotenv

project = Path(__file__).resolve().parent
load_dotenv(project / '.env', override=True)
runpy.run_path(str(project / 'run.py'), run_name='__main__')

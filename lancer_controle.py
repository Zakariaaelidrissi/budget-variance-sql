import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
ETAPES = ["generer_donnees.py", "analyse_ecarts.py", "rentabilite.py", "rolling_forecast.py", "reporting.py"]

for i, script in enumerate(ETAPES, start=1):
    print(f"\n{'=' * 78}\nÉtape {i}/{len(ETAPES)} : {script}\n{'=' * 78}")
    if subprocess.run([sys.executable, str(BASE / script)], cwd=BASE).returncode:
        sys.exit(f"\nArrêt : {script} a échoué.")
print("\nAnalyse terminée. Base dans « data », reporting et graphiques dans « resultats ».")

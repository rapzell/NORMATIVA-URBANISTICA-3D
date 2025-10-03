import os
from src.rules_engine import ZoneInput, analizar_zonificacion

def main():
    os.environ['PLAN_PROVIDER'] = 'mock'
    os.environ.pop('PLAN_CSV_PATH', None)
    print('PLAN_PROVIDER=', os.getenv('PLAN_PROVIDER'))
    cases = [
        ZoneInput(zona='urbano', uso_previsto='residencial', municipio='Vigo'),
        ZoneInput(zona='urbano', uso_previsto='residencial', municipio='Vigo', subzona='RZ-2'),
        ZoneInput(zona='urbano', uso_previsto='residencial', municipio='A Coruña'),
    ]
    for c in cases:
        print(analizar_zonificacion(c))

if __name__ == '__main__':
    main()

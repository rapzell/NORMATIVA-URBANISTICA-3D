from scripts.extract_residencial_from_text import extract_from_text

FRAGMENT = (
    "Ordenanza U9.2. Actividades de Industria productiva, almacenaje y comercial mediana y actividades terciarias. "
    "1. Parámetros y condiciones de ordenación. La industria productiva, almacenaje y terciaria, ordenada dentro de esta "
    "ordenanza comprende áreas especializadas que se desarrollan en polígonos o en ámbitos resultado de procesos de "
    "concentración informal. También se incluyen las actividades industriales y terciarias ubicadas de manera aislada en el suelo urbano. "
    "Las edificaciones podrán estar agrupadas o ser pareadas, adosadas o aisladas. Para nuevas edificaciones o ampliación de las existentes, "
    "se establece una edificabilidad máxima sobre parcela edificable de 1,50 m2/m2, altura máxima de 15 metros, medidos en el arranque de la cubierta, "
    "y ocupación máxima del 70% de la parcela edificable, para nuevas edificaciones o ampliación de las existentes. Cuando la edificación se realice "
    "retranqueada a alguno de los colindantes se exigirá que la distancia de retranqueo sea como mínimo la mitad de la altura máxima de la edificación. "
    "Se exigirá que cuando menos el 20% de la superficie de la parcela neta esté destinada a viales y aparcamiento. Para los efectos de nueva parcelación, "
    "se establece una parcela mínima de 1.000 m2 y un frente mínimo de parcela de 10 metros. Cuando por las condiciones del proceso productivo deriven "
    "mayores condiciones de altura o superficie, podrán excepcionalmente autorizarse puntualmente alturas mayores, debiendo ser debidamente justificada dicha necesidad. "
    "Se autorizan plantas sótano y semisótano. Los usos de la planta sótano y semisótano serán los de garaje- aparcamiento, almacén o instalaciones técnicas de la edificación, "
    "y se pueden destinar a los usos permitidos en las plantas superiores, a las que tendrán que estar vinculados, siempre que cumplan las normas sectoriales correspondientes. "
    "En el área de Puxeiros afectada por la zona de vulnerabilidad de servidumbres aeronáuticas del Aeropuerto de Vigo, los parámetros de edificación serán una edificabilidad de 0,80 m2/m2 "
    "y una altura de 14 metros, medidos en el arranque de la cubierta, manteniéndose la ocupación del 70% de la parcela edificable. En las parcelas catastrales 8938702NG2783N0001JR y 9741301NG2794S0000BO "
    "no podrá incrementarse el volumen actualmente edificado conforme a licencia."
)

def test_extract_from_fragment_industria_ordenanza():
    out = extract_from_text(FRAGMENT)
    # Debe detectar ordenanza como subzona
    assert out.get('subzona'), f"subzona no detectada: {out}"
    # Debe detectar edificabilidad 1.50 m2/m2
    assert abs(float(out.get('edificabilidad_max_m2_m2', 0.0)) - 1.5) < 1e-6
    # Debe detectar altura 15 m
    assert abs(float(out.get('altura_maxima_m', 0.0)) - 15.0) < 1e-6
    # Debe detectar ocupación 70% -> 0.7
    assert abs(float(out.get('ocupacion_max', 0.0)) - 0.7) < 1e-6

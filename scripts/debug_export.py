from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def run():
    payload = {
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [[0,0],[10,0],[10,10],[0,10],[0,0]],
                [[3,3],[7,3],[7,7],[3,7],[3,3]]
            ]
        },
        "altura_maxima_m": 10.0,
        "retranqueo_min_m": 0.0,
        "format": "cityjson"
    }
    r = client.post('/zoning/volume-export', json=payload)
    print(r.status_code)
    print(r.text)

if __name__ == '__main__':
    run()

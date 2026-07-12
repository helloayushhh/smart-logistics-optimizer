import requests
import pandas as pd
import mysql.connector
from math import radians, sin, cos, sqrt, atan2

# Configuración inicial
API_KEY = "TU_API_KEY_AQUI"
API_URL_OPTIMIZATION = "https://graphhopper.com/api/1/vrp"
API_URL_ROUTE = "https://graphhopper.com/api/1/route"

warehouse_location = {"lat": 27.96683841473653, "lng": -15.392203774815524}

# Configuración de la base de datos
DB_CONFIG = {
    "host": "TU_HOST_AQUI",
    "user": "TU_USUARIO_AQUI",
    "password": "TU_CONTRASEÑA_AQUI",
    "database": "TU_BASE_DE_DATOS_AQUI",
}

# Función para calcular la distancia entre dos puntos
def calculate_distance(point1, point2):
    R = 6371e3
    lat1, lon1 = radians(point1[0]), radians(point1[1])
    lat2, lon2 = radians(point2[0]), radians(point2[1])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return R * c

# Ordenar los puntos en base al recorrido codicioso
def greedy_route(start_point, locations):
    remaining = locations[:]
    route = []
    current_point = start_point
    while remaining:
        next_point = min(remaining, key=lambda loc: calculate_distance(
            (current_point["lat"], current_point["lng"]),
            (loc["lat"], loc["lng"])
        ))
        route.append(next_point)
        remaining.remove(next_point)
        current_point = next_point
    return route

#**************************************************************************
# Obtener todas las rutas disponibles de la tabla "route"
with mysql.connector.connect(**DB_CONFIG) as conn:
    with conn.cursor(dictionary=True) as cursor:
        cursor.execute("SELECT id FROM `route`")
        routes = cursor.fetchall()

    if not routes:
        print("No hay rutas disponibles en la base de datos.")
        exit()

    # Procesar cada ruta
    for route in routes:
        ROUTE_ID = route['id']  # Asignar el id de la ruta actual
        print(f"Procesando pedidos para la ruta con route_id = {ROUTE_ID}...")

        # Obtener los pedidos asociados a la ruta actual
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute("""
                SELECT id, latitude AS lat, longitude AS lng
                FROM `order`
                WHERE route_id = %s
            """, (ROUTE_ID,))
            order_locations = cursor.fetchall()

        if not order_locations:
            print(f"No hay pedidos asignados a la ruta con route_id = {ROUTE_ID}.")
            continue  # Pasar a la siguiente ruta

        # Convertir Decimal a float
        for loc in order_locations:
            loc["lat"] = float(loc["lat"])
            loc["lng"] = float(loc["lng"])

        # Crear la ruta optimizada
        sorted_locations = greedy_route(warehouse_location, order_locations)

        # Preparar datos para GraphHopper
        vehicle = {
            "vehicle_id": f"vehicle_{ROUTE_ID}",
            "start_address": {
                "location_id": "warehouse",
                "lon": warehouse_location["lng"],
                "lat": warehouse_location["lat"]
            }
        }

        services = []
        for loc in sorted_locations:
            services.append({
                "id": str(loc["id"]),
                "address": {
                    "location_id": str(loc["id"]),
                    "lon": loc["lng"],
                    "lat": loc["lat"]
                }
            })

        payload = {"vehicles": [vehicle], "services": services}
        headers = {"Content-Type": "application/json"}

        response = requests.post(f"{API_URL_OPTIMIZATION}?key={API_KEY}", json=payload, headers=headers)

        if response.status_code == 200:
            data = response.json()
            route_order = []
            for route in data["solution"]["routes"]:
                for activity in route["activities"]:
                    if activity["type"] == "service":
                        route_order.append(activity["id"])

            # Crear un DataFrame con los resultados
            df_data = []
            for loc in sorted_locations:
                df_data.append({
                    "id": route_order.index(str(loc["id"])) + 1 if str(loc["id"]) in route_order else None,
                    "id_order": loc["id"],
                    "latitude": loc["lat"],
                    "longitude": loc["lng"]
                })

            df = pd.DataFrame(df_data)

            # Ordenar el DataFrame por la columna 'id'
            df = df.sort_values(by="id").reset_index(drop=True)

            print(df)

            # Actualizar los resultados en la columna "sequence" de la tabla "order"
            for _, row in df.iterrows():
                with conn.cursor() as cursor:
                    cursor.execute("""
                        UPDATE `order`
                        SET sequence = %s
                        WHERE id = %s
                    """, (row["id"], row["id_order"]))
                    conn.commit()

            print(f"Columna 'sequence' actualizada para los pedidos de la ruta {ROUTE_ID}.")
        else:
            print(f"Error en la API de GraphHopper para route_id {ROUTE_ID}: {response.status_code} - {response.text}")

#*************************************************************************

# Convertir Decimal a float
for loc in order_locations:
    loc["lat"] = float(loc["lat"])
    loc["lng"] = float(loc["lng"])

# Crear la ruta optimizada
sorted_locations = greedy_route(warehouse_location, order_locations)

# Preparar datos para GraphHopper
vehicle = {
    "vehicle_id": "van_1",
    "start_address": {
        "location_id": "warehouse",
        "lon": warehouse_location["lng"],
        "lat": warehouse_location["lat"]
    }
}

services = []
for loc in sorted_locations:
    services.append({
        "id": str(loc["id"]),  # Convertir 'id' a STRING
        "address": {
            "location_id": str(loc["id"]),  # Convertir 'location_id' a STRING
            "lon": loc["lng"],
            "lat": loc["lat"]
        }
    })

payload = {"vehicles": [vehicle], "services": services}
headers = {"Content-Type": "application/json"}

response = requests.post(f"{API_URL_OPTIMIZATION}?key={API_KEY}", json=payload, headers=headers)

if response.status_code == 200:
    data = response.json()
    route_order = []
    for route in data["solution"]["routes"]:
        for activity in route["activities"]:
            if activity["type"] == "service":
                route_order.append(activity["id"])

    # Crear un DataFrame con los resultados
    df_data = []
    for loc in sorted_locations:
        df_data.append({
            "id": route_order.index(str(loc["id"])) + 1 if str(loc["id"]) in route_order else None,
            "id_order": loc["id"],
            "latitude": loc["lat"],
            "longitude": loc["lng"]
        })

    df = pd.DataFrame(df_data)

    # Ordenar el DataFrame por la columna 'id'
    df = df.sort_values(by="id").reset_index(drop=True)

    print(df)

    # Actualizar los resultados en la columna "sequence" de la tabla "order"
    for _, row in df.iterrows():
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE `order`
            SET sequence = %s
            WHERE id = %s
        """, (row["id"], row["id_order"]))
        conn.commit()
        cursor.close()

    conn.close()
    print(f"Columna 'sequence' actualizada para los pedidos de la ruta {ROUTE_ID}.")
else:
    print(f"Error en la API de GraphHopper: {response.status_code} - {response.text}")
message.txt
8 KB

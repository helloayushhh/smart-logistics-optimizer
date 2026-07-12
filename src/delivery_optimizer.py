import pymysql
import pandas as pd
import pygad
from sklearn.cluster import KMeans
import folium
import numpy as np

# Conexión a la base de datos MySQL
conn = pymysql.connect(
    host="TU_HOST_AQUI",
    user="TU_USUARIO_AQUI", 
    password="TU_CONTRASEÑA_AQUI",
    database="TU_BASE_DE_DATOS_AQUI" 
)

cursor = conn.cursor()

# Consultas a la base de datos
query_truck = "SELECT id, license_plate, max_mass, max_volume FROM truck"
cursor.execute(query_truck)
df_truck = pd.DataFrame(cursor.fetchall(), columns=["id", "license_plate", "max_mass", "max_volume"])

query_order = "SELECT id, maximum_permissible_mass, maximum_permissible_volume, longitude, latitude FROM `order`"
cursor.execute(query_order)
df_order = pd.DataFrame(cursor.fetchall(),
                        columns=["id", "maximum_permissible_mass", "maximum_permissible_volume", "longitude",
                                 "latitude"])

# Función para obtener el route_id basado en el truck_id
def get_route_id(truck_id):
    query = "SELECT id FROM route WHERE truck_id = %s"
    cursor.execute(query, (truck_id,))
    result = cursor.fetchone()
    return result[0] if result else None

# Función para actualizar el route_id en la tabla order
def update_order_route(order_id, route_id):
    query = "UPDATE `order` SET route_id = %s WHERE id = %s"
    cursor.execute(query, (route_id, order_id))
    conn.commit()

# Preparación de datos
df_order["maximum_permissible_mass"] = pd.to_numeric(df_order["maximum_permissible_mass"], errors="coerce")
df_order["maximum_permissible_volume"] = pd.to_numeric(df_order["maximum_permissible_volume"], errors="coerce")
df_order.dropna(subset=["maximum_permissible_mass", "maximum_permissible_volume"], inplace=True)
df_order['uploaded'] = False

# Parámetros del clustering con centroides específicos
n_clusters = 8
cluster_centers = np.array([
    (28.135035564504964, -15.43209759947092),
    (28.11873238338806, -15.52326563195904),
    (28.14414695029059, -15.655172960469848),
    (28.100333635665432, -15.705940715919775),
    (28.009191893709804, -15.532718469403878),
    (27.99648257146135, -15.417906498231394),
    (27.91787907070111, -15.432363893330333),
    (27.770627079086285, -15.605982396663174)
])

# Aplicar K-Means con centroides iniciales específicos
kmeans = KMeans(n_clusters=n_clusters, init=cluster_centers, n_init=1, random_state=666)
df_order['cluster'] = kmeans.fit_predict(df_order[["latitude", "longitude"]])

# Crear diccionarios para resultados
clusters = {f'cluster_{i}': df_order[df_order['cluster'] == i].copy() for i in range(n_clusters)}
orders_in_trucks = {}
volume_truck_used = {}

# Diccionario para seguimiento del uso de cada camión
truck_usage = {truck['license_plate']: {'mass': 0, 'volume': 0} for _, truck in df_truck.iterrows()}

def can_fit_in_truck(cluster_df, truck_data, truck_id):
    """
    Verifica si un cluster completo cabe en el camión considerando el uso actual
    """
    total_mass = cluster_df['maximum_permissible_mass'].sum()
    total_volume = cluster_df['maximum_permissible_volume'].sum()

    current_usage = truck_usage[truck_id]
    remaining_mass_capacity = truck_data['max_mass'] - current_usage['mass']
    remaining_volume_capacity = truck_data['max_volume'] - current_usage['volume']

    return (total_mass <= remaining_mass_capacity * 0.99 and
            total_volume <= remaining_volume_capacity * 0.99)

def fitness_function(ga_instance, solution, solution_idx, remaining_clusters, truck_data, truck_id):
    """
    Función de fitness con verificación más estricta
    """
    total_mass = truck_usage[truck_id]['mass']
    total_volume = truck_usage[truck_id]['volume']

    for i, use_cluster in enumerate(solution):
        if use_cluster == 1:
            cluster_df = remaining_clusters[i]
            cluster_mass = cluster_df['maximum_permissible_mass'].sum()
            cluster_volume = cluster_df['maximum_permissible_volume'].sum()

            if (total_mass + cluster_mass > truck_data['max_mass'] * 0.99 or
                    total_volume + cluster_volume > truck_data['max_volume'] * 0.99):
                return 0

            total_mass += cluster_mass
            total_volume += cluster_volume

    volume_utilization = total_volume / truck_data['max_volume']
    mass_utilization = total_mass / truck_data['max_mass']

    return (volume_utilization + mass_utilization) / 2

def verify_assignment(cluster_df, truck_id, truck_data):
    """
    Verificación final antes de asignar un cluster
    """
    total_mass = cluster_df['maximum_permissible_mass'].sum()
    total_volume = cluster_df['maximum_permissible_volume'].sum()

    current_usage = truck_usage[truck_id]
    final_mass = current_usage['mass'] + total_mass
    final_volume = current_usage['volume'] + total_volume

    if final_mass > truck_data['max_mass'] or final_volume > truck_data['max_volume']:
        print(f"¡Advertencia! Asignación rechazada para camión {truck_id}:")
        print(f"Masa final: {final_mass}/{truck_data['max_mass']}")
        print(f"Volumen final: {final_volume}/{truck_data['max_volume']}")
        return False
    return True

def verify_total_truck_usage(truck_id, df_truck):
    """
    Verifica que el uso total del camión no exceda sus límites
    """
    usage = truck_usage[truck_id]
    truck_data = df_truck[df_truck['license_plate'] == truck_id].iloc[0]

    mass_percentage = (usage['mass'] / truck_data['max_mass']) * 100
    volume_percentage = (usage['volume'] / truck_data['max_volume']) * 100

    return mass_percentage <= 100 and volume_percentage <= 100

def update_truck_usage(truck_id, mass, volume):
    """
    Actualiza el uso del camión
    """
    truck_usage[truck_id]['mass'] += mass
    truck_usage[truck_id]['volume'] += volume

def assign_cluster_to_truck(cluster_df, truck_id, truck_data, cluster_id):
    """
    Asigna un cluster completo a un camión
    """
    total_mass = cluster_df['maximum_permissible_mass'].sum()
    total_volume = cluster_df['maximum_permissible_volume'].sum()

    current_usage = truck_usage[truck_id]
    if (current_usage['mass'] + total_mass > truck_data['max_mass'] or
            current_usage['volume'] + total_volume > truck_data['max_volume']):
        print(f"¡Error! El cluster {cluster_id} excede la capacidad del camión {truck_id}.")
        return False

    update_truck_usage(truck_id, total_mass, total_volume)

    truck_key = f"Truck_{truck_id}_cluster_{cluster_id}"
    orders_in_trucks[truck_key] = cluster_df['id'].tolist()
    volume_truck_used[truck_key] = {
        'volume_used': total_volume,
        'volume_capacity': truck_data['max_volume'],
        'mass_used': total_mass,
        'mass_capacity': truck_data['max_mass']
    }

    df_order.loc[df_order['cluster'] == cluster_id, 'uploaded'] = True
    return True

# Proceso principal de asignación
available_clusters = list(range(n_clusters))
trucks_list = df_truck['license_plate'].tolist()
current_truck_index = 0

while available_clusters and current_truck_index < len(trucks_list):
    current_truck_id = trucks_list[current_truck_index]
    current_truck = df_truck[df_truck['license_plate'] == current_truck_id].iloc[0]

    first_cluster = available_clusters[0]
    first_cluster_df = clusters[f'cluster_{first_cluster}']

    if can_fit_in_truck(first_cluster_df, current_truck, current_truck_id):
        assign_cluster_to_truck(first_cluster_df, current_truck_id, current_truck, first_cluster)
        available_clusters.remove(first_cluster)

        remaining_clusters_data = [clusters[f'cluster_{i}'] for i in available_clusters]

        if remaining_clusters_data:
            ga_instance = pygad.GA(
                num_generations=100,
                num_parents_mating=5,
                fitness_func=lambda ga, sol, idx: fitness_function(
                    ga, sol, idx, remaining_clusters_data, current_truck, current_truck_id
                ),
                sol_per_pop=20,
                num_genes=len(remaining_clusters_data),
                gene_space=[0, 1],
                crossover_type="single_point",
                mutation_type="random",
                mutation_probability=0.1
            )

            ga_instance.run()
            solution, solution_fitness, _ = ga_instance.best_solution()

            if solution_fitness > 0:
                selected_indices = [i for i, val in enumerate(solution) if val == 1]
                selected_indices = [idx for idx in selected_indices if idx < len(available_clusters)]

                for idx in selected_indices:
                    if idx >= len(available_clusters):
                        print(f"Índice {idx} fuera de rango. Longitud actual de available_clusters: {len(available_clusters)}")
                        continue

                    cluster_id = available_clusters[idx]
                    cluster_df = clusters[f'cluster_{cluster_id}']
                    if assign_cluster_to_truck(cluster_df, current_truck_id, current_truck, cluster_id):
                        available_clusters.remove(cluster_id)

    current_truck_index += 1

# Crear visualización
map_center = [df_order['latitude'].mean(), df_order['longitude'].mean()]
map_clusters = folium.Map(location=map_center, zoom_start=12)

colors = ['red', 'blue', 'green', 'purple', 'orange', 'darkred', 'lightblue', 'pink']

# Agregar marcadores de pedidos
for cluster_id in range(n_clusters):
    cluster_color = colors[cluster_id]
    cluster_data = df_order[df_order['cluster'] == cluster_id]

    for _, row in cluster_data.iterrows():
        status = "Asignado" if row['uploaded'] else "No asignado"
        folium.CircleMarker(
            location=(row['latitude'], row['longitude']),
            radius=5,
            color=cluster_color,
            fill=True,
            fill_opacity=0.7,
            popup=f"ID: {row['id']}<br>Volume: {row['maximum_permissible_volume']:.2f}<br>Mass: {row['maximum_permissible_mass']:.2f}<br>Status: {status}"
        ).add_to(map_clusters)

# Agregar centroides
for i, center in enumerate(cluster_centers):
    folium.CircleMarker(
        location=(center[0], center[1]),
        radius=8,
        color='black',
        fill=True,
        popup=f'Centroide {i}',
        weight=2
    ).add_to(map_clusters)

map_clusters.save("clusters_map.html")

# Imprimir resultados y actualizar route_id
print("\nResumen de asignaciones por camión y cluster:")
for truck_key, orders in orders_in_trucks.items():
    # Extraer la matrícula del camión del truck_key
    truck_license = truck_key.split('_')[1]
    
    # Obtener el truck_id
    truck_id = df_truck[df_truck['license_plate'] == truck_license]['id'].iloc[0]
    
    # Obtener el route_id correspondiente
    route_id = get_route_id(truck_id)
    
    if route_id:
        # Actualizar los pedidos con el route_id
        for order_id in orders:
            update_order_route(order_id, route_id)
        
        print(f"\n{truck_key}:")
        print(f"Truck ID: {truck_id}")
        print(f"Route ID: {route_id}")
        print(f"Pedidos asignados: {orders}")
        
        usage = volume_truck_used[truck_key]
        print(f"Volumen utilizado: {usage['volume_used']:.2f}/{usage['volume_capacity']:.2f} "
              f"({(usage['volume_used'] / usage['volume_capacity'] * 100):.1f}%)")
        print(f"Masa utilizada: {usage['mass_used']:.2f}/{usage['mass_capacity']:.2f} "
              f"({(usage['mass_used'] / usage['mass_capacity'] * 100):.1f}%)")
    else:
        print(f"\nAdvertencia: No se encontró ruta para el camión {truck_license}")

print("\nUso total por camión:")
for truck_id, usage in truck_usage.items():
    truck_data = df_truck[df_truck['license_plate'] == truck_id].iloc[0]
    max_volume = truck_data['max_volume']
    max_mass = truck_data['max_mass']

    volume_percentage = (usage['volume'] / max_volume) * 100
    mass_percentage = (usage['mass'] / max_mass) * 100

    print(f"\nCamión {truck_id}:")
    print(f"Volumen total utilizado: {volume_percentage:.1f}%")
    print(f"Masa total utilizada: {mass_percentage:.1f}%")

# Verificar pedidos no asignados
unassigned_orders = df_order[~df_order['uploaded']]['id'].tolist()
if unassigned_orders:
    print("\nPedidos no asignados:", unassigned_orders)
else:
    print("\nTodos los pedidos fueron asignados exitosamente")

# Cerrar conexión
conn.close()
message.txt
13 KB

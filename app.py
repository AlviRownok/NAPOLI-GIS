import streamlit as st
import pandas as pd
import os
import json
import requests
import folium
from streamlit_folium import st_folium
from shapely.geometry import Polygon
import geopandas as gpd

# Function to load existing polygons
def load_existing_polygons(csv_file):
    if os.path.exists(csv_file):
        df = pd.read_csv(csv_file)
        df['Coordinates'] = df['Coordinates'].apply(json.loads)
        return df
    else:
        return pd.DataFrame(columns=['Nome', 'Cognome', 'Nome Impresa', 'Area Name', 'Area Size', 'Streets', 'Places', 'Color', 'Coordinates'])

# Function to save polygon data
def save_polygon_data(csv_file, data):
    df = load_existing_polygons(csv_file)
    df = df.append(data, ignore_index=True)
    df.to_csv(csv_file, index=False)

# Function to get the next available color
def get_next_color(used_colors):
    COLOR_LIST = [
        '#FF0000', '#0000FF', '#008000', '#FFFF00',
        '#FFA500', '#800080', '#00FFFF', '#FFC0CB',
        '#A52A2A', '#000000', '#808080', '#00FF00',
        '#800000', '#808000', '#008080', '#000080'
    ]
    for color in COLOR_LIST:
        if color not in used_colors:
            return color
    # If all colors are used, generate a random color
    import random
    return "#{:06x}".format(random.randint(0, 0xFFFFFF))

# CSV file path
csv_file = 'napoli_polygon_data.csv'

# Streamlit app
st.title('Napoli Map Platform')

# Input boxes for user information
st.sidebar.header('User Information')
nome = st.sidebar.text_input('Nome')
cognome = st.sidebar.text_input('Cognome')
nome_impresa = st.sidebar.text_input('Nome Impresa')

if not nome or not cognome or not nome_impresa:
    st.warning('Please fill in all the user information.')
    st.stop()

client_info = {
    'Nome': nome,
    'Cognome': cognome,
    'Nome_impresa': nome_impresa
}

# Load existing polygons
df_polygons = load_existing_polygons(csv_file)

# Maintain client color mapping
client_key = f"{nome}_{cognome}_{nome_impresa}"
client_colors = df_polygons.groupby(['Nome', 'Cognome', 'Nome Impresa'])['Color'].first().to_dict()
used_colors = set(client_colors.values())
color = client_colors.get((nome, cognome, nome_impresa), get_next_color(used_colors))

# Create a map centered on Napoli
m = folium.Map(location=[40.8518, 14.2681], zoom_start=13)

# Add existing polygons to the map
for idx, row in df_polygons.iterrows():
    coords = row['Coordinates']
    folium.vector_layers.Polygon(
        locations=[(lat, lon) for lon, lat in coords],
        color=row['Color'],
        fill=True,
        fill_color=row['Color'],
        fill_opacity=0.5,
        popup=f"{row['Nome']} {row['Cognome']} - {row['Nome Impresa']}"
    ).add_to(m)

# Allow user to draw a new polygon
st.write('Draw a polygon on the map to select an area.')
output = st_folium(m, width=700, height=500, drawing_mode='edit', key='map')

# Check if a new polygon was drawn
if output['last_active_drawing']:
    # Get the geometry of the drawn polygon
    geometry = output['last_active_drawing']['geometry']
    coords = geometry['coordinates'][0]

    # Prepare data
    transformed_coords = [(lon, lat) for lon, lat in coords]
    polygon = Polygon(transformed_coords)
    area = polygon.area * (111139 ** 2)  # Approximate area in square meters
    area_size = f"{area:.2f} sqm"

    # Use Overpass API to get street names and place names within the polygon
    overpass_url = 'https://overpass-api.de/api/interpreter'
    poly_coords_string = ' '.join(f"{lat} {lon}" for lon, lat in transformed_coords)
    overpass_query = f"""
        [out:json];
        (
            way["highway"](poly:"{poly_coords_string}");
            node["amenity"](poly:"{poly_coords_string}");
            node["shop"](poly:"{poly_coords_string}");
            node["tourism"](poly:"{poly_coords_string}");
            node["leisure"](poly:"{poly_coords_string}");
            node["building"](poly:"{poly_coords_string}");
            way["building"](poly:"{poly_coords_string}");
        );
        out tags;
    """

    response = requests.post(overpass_url, data=overpass_query)
    data = response.json()

    elements = data.get('elements', [])

    # Extract street names
    street_names = [el['tags']['name'] for el in elements if 'highway' in el['tags'] and 'name' in el['tags']]

    # Extract place names
    place_names = [el['tags']['name'] for el in elements if any(tag in el['tags'] for tag in ['amenity', 'shop', 'tourism', 'leisure', 'building']) and 'name' in el['tags']]

    streets = ', '.join(set(street_names))
    places = ', '.join(set(place_names))

    # Use Nominatim to get the area name
    nominatim_url = f"https://nominatim.openstreetmap.org/reverse?format=json&lat={transformed_coords[0][1]}&lon={transformed_coords[0][0]}"
    nominatim_response = requests.get(nominatim_url)
    nominatim_data = nominatim_response.json()
    area_name = nominatim_data.get('address', {}).get('suburb') or \
                nominatim_data.get('address', {}).get('city_district') or \
                nominatim_data.get('address', {}).get('city') or 'Unknown'

    # Prepare data to save
    polygon_data = {
        'Nome': nome,
        'Cognome': cognome,
        'Nome Impresa': nome_impresa,
        'Area Name': area_name,
        'Area Size': area_size,
        'Streets': streets,
        'Places': places,
        'Color': color,
        'Coordinates': json.dumps([(lon, lat) for lon, lat in coords])
    }

    # Save data to CSV
    save_polygon_data(csv_file, polygon_data)

    st.success('Polygon data saved successfully.')

    # Refresh the map to show the new polygon
    st.experimental_rerun()

# Download CSV
if st.button('Download CSV'):
    if os.path.exists(csv_file):
        with open(csv_file, 'rb') as f:
            st.download_button('Click here to download', f, file_name='napoli_polygon_data.csv')
    else:
        st.warning('No data available to download.')
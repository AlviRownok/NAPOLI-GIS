import streamlit as st
import pandas as pd
import json
import requests
import folium
from streamlit_folium import st_folium
from shapely.geometry import Polygon
from folium.plugins import Draw
import boto3
from botocore.exceptions import NoCredentialsError

# Functions to interact with AWS S3
def load_existing_polygons():
    s3 = boto3.client(
        's3',
        aws_access_key_id=st.secrets["aws"]["aws_access_key_id"],
        aws_secret_access_key=st.secrets["aws"]["aws_secret_access_key"],
        region_name=st.secrets["aws"]["region_name"]
    )
    try:
        obj = s3.get_object(Bucket='napoligis', Key='napoli_polygon_data.csv')
        df = pd.read_csv(obj['Body'])
        if not df.empty:
            df['Coordinates'] = df['Coordinates'].apply(json.loads)
            return df
        else:
            return pd.DataFrame(columns=[
                'Nome', 'Cognome', 'Nome Impresa', 'Area Name', 'Area Size',
                'Streets', 'Places', 'Color', 'Coordinates'
            ])
    except s3.exceptions.NoSuchKey:
        # The file does not exist in S3
        return pd.DataFrame(columns=[
            'Nome', 'Cognome', 'Nome Impresa', 'Area Name', 'Area Size',
            'Streets', 'Places', 'Color', 'Coordinates'
        ])
    except NoCredentialsError:
        st.error("AWS credentials not available.")
        return pd.DataFrame()
    except Exception as e:
        st.error(f"Error loading data from S3: {e}")
        return pd.DataFrame()

def save_polygon_data(polygon_data):
    # Load existing data
    df = load_existing_polygons()
    
    # Append new data
    df = df.append(polygon_data, ignore_index=True)
    
    # Convert DataFrame to CSV
    csv_buffer = df.to_csv(index=False)
    
    # Upload CSV to S3
    s3 = boto3.resource(
        's3',
        aws_access_key_id=st.secrets["aws"]["aws_access_key_id"],
        aws_secret_access_key=st.secrets["aws"]["aws_secret_access_key"],
        region_name=st.secrets["aws"]["region_name"]
    )
    try:
        s3.Object('napoligis', 'napoli_polygon_data.csv').put(Body=csv_buffer)
    except NoCredentialsError:
        st.error("AWS credentials not available.")
    except Exception as e:
        st.error(f"Error saving data to S3: {e}")

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
df_polygons = load_existing_polygons()

# Maintain client color mapping
client_key = f"{nome}_{cognome}_{nome_impresa}"
if not df_polygons.empty:
    df_polygons['Client Key'] = df_polygons['Nome'] + '_' + df_polygons['Cognome'] + '_' + df_polygons['Nome Impresa']
    client_colors = df_polygons.set_index('Client Key')['Color'].to_dict()
    used_colors = set(client_colors.values())
else:
    client_colors = {}
    used_colors = set()

color = client_colors.get(client_key, get_next_color(used_colors))

# Create a map centered on Napoli
m = folium.Map(location=[40.8518, 14.2681], zoom_start=13)

# Add existing polygons to the map
if not df_polygons.empty:
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

# Add drawing tools to the map
draw = Draw(
    draw_options={
        'polyline': False,
        'polygon': True,
        'circle': False,
        'rectangle': False,
        'marker': False,
        'circlemarker': False
    }
)
draw.add_to(m)

# Display the map
st.write('Draw a polygon on the map to select an area.')
output = st_folium(m, width=700, height=500, key='map')

# Check if a new polygon was drawn
if 'all_drawings' in output and output['all_drawings']:
    # Get the last drawn feature
    last_drawing = output['all_drawings'][-1]
    geometry = last_drawing['geometry']
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

    # Save data to AWS S3
    save_polygon_data(polygon_data)

    st.success('Polygon data saved successfully.')

    # Refresh the app to show the new polygon
    st.experimental_rerun()

# Download Data
if st.button('Download Data'):
    df_polygons = load_existing_polygons()
    if not df_polygons.empty:
        csv_data = df_polygons.to_csv(index=False)
        st.download_button('Click here to download', data=csv_data, file_name='napoli_polygon_data.csv', mime='text/csv')
    else:
        st.warning('No data available to download.')

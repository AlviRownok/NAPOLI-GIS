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

# ---------------------
# Initialize Session State
# ---------------------
if 'client_info' not in st.session_state:
    st.session_state.client_info = {}
if 'client_colors' not in st.session_state:
    st.session_state.client_colors = {}
if 'used_colors' not in st.session_state:
    st.session_state.used_colors = set()
if 'map_displayed' not in st.session_state:
    st.session_state.map_displayed = False
if 'polygon_saved' not in st.session_state:
    st.session_state.polygon_saved = False
if 'user_counter' not in st.session_state:
    st.session_state.user_counter = 0

# ---------------------
# AWS S3 Interaction Functions
# ---------------------
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
        # The file does not exist in S3, create it
        df = pd.DataFrame(columns=[
            'Nome', 'Cognome', 'Nome Impresa', 'Area Name', 'Area Size',
            'Streets', 'Places', 'Color', 'Coordinates'
        ])
        csv_buffer = df.to_csv(index=False)
        s3.put_object(Bucket='napoligis', Key='napoli_polygon_data.csv', Body=csv_buffer)
        return df
    except NoCredentialsError:
        st.error("AWS credentials not available.")
        return pd.DataFrame()
    except Exception as e:
        st.error(f"Error loading data from S3: {e}")
        return pd.DataFrame()

def save_polygon_data(polygon_data):
    # Load existing data
    df = load_existing_polygons()

    # Append new data using pd.concat (since append is deprecated)
    df = pd.concat([df, pd.DataFrame([polygon_data])], ignore_index=True)

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
        st.session_state.polygon_saved = True
    except NoCredentialsError:
        st.error("AWS credentials not available.")
    except Exception as e:
        st.error(f"Error saving data to S3: {e}")

def reset_polygon_data():
    # Create an empty DataFrame
    df = pd.DataFrame(columns=[
        'Nome', 'Cognome', 'Nome Impresa', 'Area Name', 'Area Size',
        'Streets', 'Places', 'Color', 'Coordinates'
    ])

    # Convert DataFrame to CSV
    csv_buffer = df.to_csv(index=False)

    # Upload empty CSV to S3
    s3 = boto3.resource(
        's3',
        aws_access_key_id=st.secrets["aws"]["aws_access_key_id"],
        aws_secret_access_key=st.secrets["aws"]["aws_secret_access_key"],
        region_name=st.secrets["aws"]["region_name"]
    )
    try:
        s3.Object('napoligis', 'napoli_polygon_data.csv').put(Body=csv_buffer)
        st.success("All entries have been reset.")
    except NoCredentialsError:
        st.error("AWS credentials not available.")
    except Exception as e:
        st.error(f"Error resetting data in S3: {e}")

# ---------------------
# Utility Functions
# ---------------------
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

# ---------------------
# Streamlit App Layout
# ---------------------
st.title('Napoli Map Platform')

# ---------------------
# Sidebar: Developer Options and Done Button
# ---------------------
with st.sidebar:
    st.header('Controls')
    
    # Developer Options
    st.subheader('Developer Options')
    if st.checkbox('Developer Mode'):
        st.session_state.developer_mode = True
    else:
        st.session_state.developer_mode = False

    if st.session_state.developer_mode:
        if st.button('Reset'):
            reset_polygon_data()
            st.session_state.clear()
            st.success("Application state has been reset.")

    # Download Data
    if st.button('Download Data'):
        df_polygons = load_existing_polygons()
        if not df_polygons.empty:
            csv_data = df_polygons.to_csv(index=False)
            st.download_button('Click here to download', data=csv_data, file_name='napoli_polygon_data.csv', mime='text/csv')
        else:
            st.warning('No data available to download.')

    # Done Button inside a form
    st.subheader('User Actions')
    with st.form(key='done_form'):
        done_button = st.form_submit_button(label='Done')

# ---------------------
# Main Panel: User Information and Map
# ---------------------
if not st.session_state.map_displayed:
    st.header('User Information')
    # Use unique keys for each user to avoid conflicts
    user_key_suffix = f"user_{st.session_state.user_counter}"
    nome = st.text_input('Nome', key=f'nome_{user_key_suffix}')
    cognome = st.text_input('Cognome', key=f'cognome_{user_key_suffix}')
    nome_impresa = st.text_input('Nome Impresa', key=f'nome_impresa_{user_key_suffix}')
    
    if st.button('OK'):
        if nome and cognome and nome_impresa:
            st.session_state.client_info = {
                'Nome': nome,
                'Cognome': cognome,
                'Nome_impresa': nome_impresa
            }
            # Assign a new color to the client
            client_key = f"{nome}_{cognome}_{nome_impresa}"
            color = get_next_color(st.session_state.used_colors)
            st.session_state.client_colors[client_key] = color
            st.session_state.used_colors.add(color)
            st.session_state.map_displayed = True
            st.session_state.polygon_saved = False
            # Increment user_counter for unique keys
            st.session_state.user_counter += 1
        else:
            st.warning('Please fill in all the user information.')
else:
    # Load existing polygons
    df_polygons = load_existing_polygons()

    # Update client color mapping with existing data
    if not df_polygons.empty:
        df_polygons['Client Key'] = df_polygons['Nome'] + '_' + df_polygons['Cognome'] + '_' + df_polygons['Nome Impresa']
        existing_client_colors = df_polygons.set_index('Client Key')['Color'].to_dict()
        st.session_state.client_colors.update(existing_client_colors)
        st.session_state.used_colors.update(existing_client_colors.values())

    client_info = st.session_state.client_info
    client_key = f"{client_info['Nome']}_{client_info['Cognome']}_{client_info['Nome_impresa']}"
    color = st.session_state.client_colors.get(client_key, get_next_color(st.session_state.used_colors))

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
                tooltip=f"{row['Nome']} {row['Cognome']} - {row['Nome Impresa']}"
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

    # Display the map with increased size
    st.write('Draw a polygon on the map to select an area.')
    output = st_folium(m, width=800, height=600, key='map')

    # Handle the "Done" button click from the sidebar form
    if done_button:
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
            try:
                response = requests.post(overpass_url, data=overpass_query)
                if response.status_code == 200 and response.content:
                    data = response.json()

                    elements = data.get('elements', [])

                    # Extract street names
                    street_names = [el['tags']['name'] for el in elements if 'highway' in el['tags'] and 'name' in el['tags']]

                    # Extract place names
                    place_names = [el['tags']['name'] for el in elements if any(tag in el['tags'] for tag in ['amenity', 'shop', 'tourism', 'leisure', 'building']) and 'name' in el['tags']]

                    streets = ', '.join(set(street_names))
                    places = ', '.join(set(place_names))
                else:
                    st.error("Failed to fetch data from Overpass API.")
                    streets = ''
                    places = ''
            except Exception as e:
                st.error(f"Error fetching data from Overpass API: {e}")
                streets = ''
                places = ''

            # Use Nominatim to get the area name
            try:
                nominatim_url = f"https://nominatim.openstreetmap.org/reverse?format=json&lat={transformed_coords[0][1]}&lon={transformed_coords[0][0]}"
                headers = {'User-Agent': 'Napoli-GIS-App/1.0'}
                nominatim_response = requests.get(nominatim_url, headers=headers)
                if nominatim_response.status_code == 200 and nominatim_response.content:
                    nominatim_data = nominatim_response.json()
                    area_name = nominatim_data.get('address', {}).get('suburb') or \
                                nominatim_data.get('address', {}).get('city_district') or \
                                nominatim_data.get('address', {}).get('city') or 'Unknown'
                else:
                    st.error("Failed to fetch data from Nominatim.")
                    area_name = 'Unknown'
            except Exception as e:
                st.error(f"Error fetching data from Nominatim: {e}")
                area_name = 'Unknown'

            # Prepare data to save
            polygon_data = {
                'Nome': client_info['Nome'],
                'Cognome': client_info['Cognome'],
                'Nome Impresa': client_info['Nome_impresa'],
                'Area Name': area_name,
                'Area Size': area_size,
                'Streets': streets,
                'Places': places,
                'Color': color,
                'Coordinates': json.dumps([(lon, lat) for lon, lat in coords])
            }

            # Save data to AWS S3
            save_polygon_data(polygon_data)

            if st.session_state.polygon_saved:
                st.success('Polygon data saved successfully.')

                # Reset for the next user
                st.session_state.map_displayed = False
                st.session_state.polygon_saved = False
                st.session_state.client_info = {}
        else:
            st.warning("Please draw a polygon before clicking Done.")

    if st.session_state.polygon_saved:
        st.info("Thank you! You can enter a new user.")
        st.session_state.polygon_saved = False

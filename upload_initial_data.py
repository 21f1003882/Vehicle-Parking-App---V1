import csv
import requests
import json
import sys
import getpass
from datetime import datetime, timedelta

# --- Configuration ---
# Make sure your Flask app is running and accessible at this address.
BASE_API_URL = "http://127.0.0.1:5001/api" 

# Define paths to your data files.
# It's recommended to place them in a 'data' subdirectory.
SECRET_QUESTIONS_CSV = 'data/secret_questions.csv'
PARKING_AREAS_CSV = 'data/parking_areas.csv'
USERS_CSV = 'data/users.csv'
CARS_CSV = 'data/cars.csv'
BOOKINGS_CSV = 'data/bookings.csv'

# Global headers dictionary to be populated with the auth token.
HEADERS = {'Content-Type': 'application/json'}

# --- Helper Functions ---

def get_auth_token(username, password):
    """Logs in the admin user to get a JWT for subsequent requests."""
    login_url = f"{BASE_API_URL}/auth/login"
    print(f"\nAttempting login as '{username}'...")
    try:
        # NOTE: The login endpoint is under /api/auth, not /api/admin
        response = requests.post(login_url, json={"username": username, "password": password})
        response.raise_for_status()
        token = response.json().get('access_token')
        if token:
            print("Login successful. Admin token obtained.")
            HEADERS['Authorization'] = f"Bearer {token}"
            return token
        else:
            print("ERROR: Login successful, but no token was returned.")
            return None
    except requests.exceptions.HTTPError as e:
        print(f"ERROR: Login failed - Status {e.response.status_code}")
        try: print(f"       Response: {e.response.json()}")
        except json.JSONDecodeError: print(f"       Response: {e.response.text}")
        return None
    except Exception as e:
        print(f"ERROR: An unexpected error occurred during login: {e}")
        return None

def send_request(method, url, payload=None):
    """A generic function to send API requests and handle responses."""
    try:
        if payload:
            response = requests.request(method, url, headers=HEADERS, data=json.dumps(payload))
        else:
            response = requests.request(method, url, headers=HEADERS)
        
        response.raise_for_status()
        print(f"SUCCESS: {method.upper()} {url}")
        # Return JSON response if it exists, otherwise None
        return response.json() if response.content else None
    except requests.exceptions.HTTPError as e:
        print(f"ERROR: {method.upper()} {url} - Status {e.response.status_code}")
        try: print(f"       Response: {e.response.json()}")
        except json.JSONDecodeError: print(f"       Response: {e.response.text}")
        return None
    except Exception as e:
        print(f"ERROR: An unexpected error occurred for {method.upper()} {url} - {e}")
        return None

# --- Data Upload Functions ---

def upload_secret_questions(csv_path):
    """Uploads new secret questions from a CSV file."""
    print("\n--- Processing Secret Questions ---")
    
    # Get existing questions to avoid duplicates
    existing_questions_res = send_request("GET", f"{BASE_API_URL}/auth/secret-questions")
    if not existing_questions_res:
        print("ERROR: Could not fetch existing secret questions. Aborting questions upload.")
        return
    existing_texts = {q['text'] for q in existing_questions_res}

    try:
        with open(csv_path, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row['text'] in existing_texts:
                    print(f"Skipping existing question: \"{row['text']}\"")
                    continue
                
                print(f"Creating question: \"{row['text']}\"")
                # Assumes an admin endpoint for creating questions
                send_request("POST", f"{BASE_API_URL}/admin/secret-questions", {"text": row['text']})
    except FileNotFoundError:
        print(f"WARNING: {csv_path} not found. Skipping secret questions upload.")

def upload_parking_areas(csv_path):
    """Uploads new parking areas and their spots from a CSV file."""
    print("\n--- Processing Parking Areas ---")
    
    existing_areas_res = send_request("GET", f"{BASE_API_URL}/admin/parking-areas")
    if not existing_areas_res:
        print("ERROR: Could not fetch existing parking areas. Aborting areas upload.")
        return
    existing_names = {a['name'] for a in existing_areas_res.get('areas', [])}

    try:
        with open(csv_path, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row['name'] in existing_names:
                    print(f"Skipping existing parking area: {row['name']}")
                    continue
                
                print(f"Creating parking area: {row['name']} with code {row['area_code']}")
                payload = {
                    "name": row['name'],
                    "area_code": row['area_code'], # <-- ADD THIS LINE
                    "location_description": row['location_description'],
                    "price_per_hour": float(row['price_per_hour']),
                    "num_spots": int(row['num_spots'])
                }
                send_request("POST", f"{BASE_API_URL}/admin/parking-areas", payload)
    except FileNotFoundError:
        print(f"WARNING: {csv_path} not found. Skipping parking areas upload.")

        
def upload_users(csv_path):
    """Uploads new regular users from a CSV file."""
    print("\n--- Processing Users ---")

    # Get mappings needed for user creation
    questions_res = send_request("GET", f"{BASE_API_URL}/auth/secret-questions")
    users_res = send_request("GET", f"{BASE_API_URL}/admin/users")

    if not questions_res or not users_res:
        print("ERROR: Could not fetch prerequisite data (questions/users). Aborting user upload.")
        return
    
    question_map = {q['text']: q['id'] for q in questions_res}
    existing_usernames = {u['username'] for u in users_res.get('users', [])}

    try:
        with open(csv_path, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row['username'] in existing_usernames:
                    print(f"Skipping existing user: {row['username']}")
                    continue
                
                question_id = question_map.get(row['secret_question_text'])
                if not question_id:
                    print(f"WARNING: Secret question '{row['secret_question_text']}' not found for user '{row['username']}'. Skipping.")
                    continue

                print(f"Creating user: {row['username']}")
                payload = {
                    "username": row['username'], "email": row['email'],
                    "password": row['password'],
                    "secret_question_id": question_id,
                    "secret_answer": row['secret_answer']
                }
                send_request("POST", f"{BASE_API_URL}/admin/users", payload)
    except FileNotFoundError:
        print(f"WARNING: {csv_path} not found. Skipping users upload.")

def upload_cars(csv_path):
    """Uploads new cars and links them to users."""
    print("\n--- Processing Cars ---")
    
    users_res = send_request("GET", f"{BASE_API_URL}/admin/users")
    cars_res = send_request("GET", f"{BASE_API_URL}/admin/cars")

    if not users_res or not cars_res:
        print("ERROR: Could not fetch prerequisite data (users/cars). Aborting car upload.")
        return

    user_map = {u['username']: u['id'] for u in users_res.get('users', [])}
    existing_plates = {c['license_plate'] for c in cars_res.get('cars', [])}

    try:
        with open(csv_path, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row['license_plate'] in existing_plates:
                    print(f"Skipping existing car: {row['license_plate']}")
                    continue

                owner_id = user_map.get(row['owner_username'])
                if not owner_id:
                    print(f"WARNING: Owner '{row['owner_username']}' not found for car '{row['license_plate']}'. Skipping.")
                    continue
                
                print(f"Creating car: {row['license_plate']} for user {row['owner_username']}")
                payload = {
                    "license_plate": row['license_plate'], "make": row['make'],
                    "model": row['model'], "color": row['color'],
                    "user_id": owner_id
                }
                send_request("POST", f"{BASE_API_URL}/admin/cars", payload)
    except FileNotFoundError:
        print(f"WARNING: {csv_path} not found. Skipping cars upload.")


def upload_bookings(csv_path):
    """Uploads historical and active bookings."""
    print("\n--- Processing Bookings ---")
    
    # This function requires fetching and mapping a lot of data.
    users_res = send_request("GET", f"{BASE_API_URL}/admin/users")
    cars_res = send_request("GET", f"{BASE_API_URL}/admin/cars")
    areas_res = send_request("GET", f"{BASE_API_URL}/admin/parking-areas")

    if not all([users_res, cars_res, areas_res]):
        print("ERROR: Could not fetch prerequisite data. Aborting booking upload.")
        return

    user_map = {u['username']: u['id'] for u in users_res.get('users', [])}
    car_map = {c['license_plate']: c['id'] for c in cars_res.get('cars', [])}
    area_map = {a['name']: a['id'] for a in areas_res.get('areas', [])}
    
    # Create a detailed spot map: (area_name, spot_identifier) -> spot_id
    spot_map = {}
    for area_name, area_id in area_map.items():
        spots_res = send_request("GET", f"{BASE_API_URL}/admin/parking-areas/{area_id}/spots")
        if spots_res and 'spots' in spots_res:
            for spot in spots_res['spots']:
                spot_map[(area_name, spot['spot_identifier'])] = spot['id']

    try:
        with open(csv_path, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                user_id = user_map.get(row['owner_username'])
                car_id = car_map.get(row['license_plate'])
                spot_id = spot_map.get((row['parking_area_name'], row['spot_identifier']))
                
                if not all([user_id, car_id, spot_id]):
                    print(f"WARNING: Could not find user, car, or spot for booking row: {row}. Skipping.")
                    continue

                # To prevent re-creating the exact same booking, we'd need a way to uniquely identify it.
                # For this script, we'll assume we're starting with a clean slate for bookings.
                print(f"Creating booking for {row['owner_username']} in {row['parking_area_name']}")
                
                payload = {
                    "user_id": user_id, "car_id": car_id, "spot_id": spot_id,
                    "start_time": row['start_time'], "status": row['status'],
                    "end_time": row.get('end_time') or None, # Handle optional end_time
                    "total_cost": float(row['total_cost']) if row.get('total_cost') else None
                }
                # Filter out None values from payload before sending
                payload = {k: v for k, v in payload.items() if v is not None}

                send_request("POST", f"{BASE_API_URL}/admin/bookings", payload)
    except FileNotFoundError:
        print(f"WARNING: {csv_path} not found. Skipping bookings upload.")


# --- Main Execution ---

if __name__ == '__main__':
    print("--- Starting Initial Data Upload Script for Parking App ---")
    admin_user = input("Enter Admin Username [default: admin]: ") or "admin"
    try:
        admin_pass = getpass.getpass(f"Enter Password for '{admin_user}': ")
    except Exception as e:
        print(f"Could not read password: {e}")
        sys.exit(1)

    if not get_auth_token(admin_user, admin_pass):
        print("\nCould not obtain authorization token. Exiting.")
        sys.exit(1)
    
    # Run all the upload functions in the correct order of dependency
    upload_secret_questions(SECRET_QUESTIONS_CSV)
    upload_parking_areas(PARKING_AREAS_CSV)
    upload_users(USERS_CSV)
    upload_cars(CARS_CSV)
    upload_bookings(BOOKINGS_CSV)
    
    print("-" * 50)
    print("Initial data upload process complete.")
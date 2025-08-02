# Vehicle-Parking-App---V1
It is a multi-user app (one requires an administrator and other users) that manages different parking lots, parking spots and parked vehicles.

## 1. Project Overview

**Problem Statement**  
Design and implement a web application to manage vehicle parking across multiple areas. The system must support two primary roles: Admin and User. Admins are responsible for managing parking areas and their spots, monitoring real-time occupancy, approving user parking requests, and handling on-premise “walk-in” bookings. Users can register, manage their vehicles, request parking spots, view their active sessions, release spots upon departure, and review their usage history and spending statistics.

**Approach**  
The project is implemented as a monolithic web application using the Flask framework. The architecture is built on the following principles:  
- **Role-Based Access Control:** Secure authentication is handled by Flask-Login, with distinct permissions for Admin and User roles defined in a dedicated Role model.  
- **Relational Data Model:** Core entities such as ParkingArea, ParkingSpot, Car, and Booking are modeled using SQLAlchemy and backed by a relational database (SQLite).  
- **Server-Rendered UI:** The user interface is built with Jinja2 templates, styled with the Bootstrap 5 framework for a responsive and modern user experience.  
- **Dynamic Components:** Asynchronous JavaScript (Fetch API) is used to power interactive UI components, such as dashboard charts and live data modals, which consume purpose-built JSON API endpoints.  
- **System Bootstrap:** A bootstrap module ensures that essential data like user roles and a default admin account are created on the application's first run.

## 2. Frameworks & Libraries

| Category  | Technology/Library     | Purpose                                                                 |
|-----------|------------------------|-------------------------------------------------------------------------|
| Backend   | Python 3, Flask        | Core web framework and language.                                        |
| Backend   | Flask-Login            | Manages user sessions and authentication.                               |
| Backend   | Flask-WTF              | Handles form creation, validation, and CSRF protection.                |
| Backend   | Flask-SQLAlchemy       | Provides the Object-Relational Mapper (ORM) for database interactions. |
| Backend   | Flask-JWT-Extended     | Used for stateless API authentication (for data upload scripts).       |
| Backend   | Werkzeug               | Provides security utilities for password hashing.                      |
| Database  | SQLite                 | Default lightweight, file-based database.                              |
| Frontend  | Jinja2                 | Server-side template engine for rendering HTML.                        |
| Frontend  | Bootstrap 5            | CSS framework for styling and responsive design.                       |
| Frontend  | Bootstrap Icons        | Vector icons used throughout the UI.                                    |
| Frontend  | Chart.js               | JavaScript library for creating interactive charts.                    |

Export to Sheets

## 3. Core Functionalities

### Admin Capabilities
- **Parking Area Management:** Admins can create, edit, and delete parking areas.  
  - **Creation:** When creating an area, the admin specifies a name, price, and a 3-letter `area_code`. The system then dynamically generates the specified number of spots with unique identifiers (e.g., `PMC-1`, `PMC-2`, etc.).  
  - **Editing:** The area's name, description, and price can be updated. The spot count and area code are immutable after creation to maintain data integrity.  
  - **Deletion:** An area can only be deleted if all its spots are currently available, preventing accidental data loss for active sessions.  
- **Occupancy Monitoring:** The dashboard provides a real-time overview of total vs. occupied spots for each area. The “Search Spot” page allows detailed lookup of any spot's status and occupant details.  
- **Request Management:** Admins can view and Approve or Reject pending parking requests from registered users.  
- **Offline / Walk-in Bookings:** A dedicated form on the admin dashboard allows for immediate booking for walk-in customers. If the vehicle's license plate is not in the system, it is automatically created and assigned to a special `offline_user` account. These bookings become active instantly without needing approval.  
- **User Management:** A comprehensive list of all registered users is available. Admins can click a “View Stats” button for any user, which opens a modal showing their complete booking history, total spending, and other details, loaded dynamically via a secure API endpoint.

### User Capabilities
- **Authentication:** Users can register for a new account, log in, log out, and reset their password using a secret question and a partial secret key for security.  
- **Vehicle Management:** Users can add, view, and delete their own vehicles. A car cannot be deleted if it has an active parking session.  
- **Parking Flow:**  
  1. **Request:** The user selects one of their registered cars and a desired parking area. The system allocates the first available spot in that area.  
  2. **Pending:** The request is submitted and enters a pending state, awaiting admin approval. The spot is marked as reserved.  
  3. **Active:** Once approved by an admin, the booking becomes active, and the parking timer starts.  
  4. **Release:** Upon returning, the user clicks “Release Spot,” which transitions the booking to completed, calculates the final cost, and makes the spot available again.  
- **Dashboard & Summary:** The user dashboard displays any active or pending bookings. A dedicated summary page shows key statistics like total sessions, total amount spent, and a Chart.js bar chart visualizing recent spending by location and date.

## 4. Data Model & ER Diagram

The application's data is organized into eight interconnected tables:

| Entity         | Description                                                                        |
|----------------|------------------------------------------------------------------------------------|
| User           | Stores user credentials, roles, and secret question info.                          |
| Role           | Defines user types (e.g., 'admin', 'user').                                        |
| user_roles     | A join table to manage the Many-to-Many relationship between Users and Roles.      |
| SecretQuestion | A list of predefined questions for password recovery.                              |
| Car            | Represents a vehicle, uniquely identified by its license plate and owned by a User.|
| ParkingArea    | A physical parking lot with a name, location, and hourly price.                    |
| ParkingSpot    | An individual spot within a ParkingArea, with a unique identifier and status.      |
| Booking        | The central transactional table, linking a User, Car, and ParkingSpot for a session.|

## 5. ER Diagram

![ER Diagram](er_diagram.png)

## 5. Key Implementation Details
- **Time Handling:** All datetime operations are timezone-aware, using `datetime.now(timezone.utc)` to ensure consistency and prevent timezone-related bugs during calculations.  
- **Cost Calculation:** The total cost for a booking is calculated upon release. The duration is rounded up to the nearest hour (`ceil`) with a minimum charge of one hour.  
- **Access Control:** All sensitive routes and API endpoints are protected by decorators (`@login_required`, `@admin_required`) that verify the user's session and role.  
- **Database Seeding:** A bootstrap script (`bootstrap_auth.py`) runs on application startup to create the database schema and seed essential data, including the admin and user roles, a default admin account, and the special `offline_user` for walk-in bookings.

## 6. API Endpoints (JSON)
- `GET /api/admin/occupancy`  
  Returns real-time occupancy data for all areas.  
- `GET /api/admin/revenue`  
  Returns total revenue calculated from completed bookings for all areas.  
- `GET /api/admin/users/<id>/stats`  
  Returns a detailed statistical profile for a specific user, including their entire booking history.  
- `GET /api/admin/areas/<id>/spot-status`  
  Returns the area code and lists of available/occupied spots for a specific area.  
- `POST /admin/offline-book`  
  An endpoint for the admin dashboard to create an immediate, active booking for a walk-in customer.  
- `GET /api/user/spend`  
  Returns the data for the current user's “Recent Spend” chart.

## 7. Validation & Security
- **Backend:** The application enforces security through CSRF tokens on all web forms, role-based access control, ownership checks (e.g., a user can only release their own booking), and robust validation (e.g., license plate uniqueness, preventing a car from being booked twice).  
- **Passwords:** All user passwords are securely hashed using `werkzeug.security` before being stored in the database.  
- **Frontend:** Key forms use HTML5 `required` attributes, and JavaScript provides confirmation prompts for destructive actions like deleting a car or area.

## 8. How to Run
**Setup:** Create a Python virtual environment and install dependencies:  

- `pip install -r requirements.txt`
- `python app.py`
The application will be available at http://127.0.0.1:5001. The first run will create parking.db and seed it with roles and a default admin (admin/admin123).

Populate Data (Optional): After starting the server, run the upload script in a separate terminal to populate the database with sample data:
- `python upload_initial_data.py`

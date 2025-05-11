# backend/main.py
import json
import os
import random
import string
import time
from typing import List, Dict, Any, Optional

from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import websockets.exceptions
import traceback

# --- Configuration and Initialization ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(BASE_DIR, "../frontend")

# Define paths for data files
DATABASE_DIR = os.path.join(BASE_DIR, "database")
CHAT_HISTORY_FILE = os.path.join(DATABASE_DIR, "chat_history.json")
USERS_FILE = os.path.join(DATABASE_DIR, "users.json")
SESSIONS_FILE = os.path.join(DATABASE_DIR, "active_sessions.json")

# --- Data Storage (in-memory) ---
chat_history: List[Dict[str, Any]] = []
users_data: Dict[str, Dict[str, str]] = {}
active_sessions: Dict[str, str] = {}


# --- Persistence Functions ---
def load_data(filepath: str, default_data: Any):
    """Generic function to load JSON data from a file."""
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # Basic check: if file is empty or invalid structure for default
                if not data and default_data is not None:
                    print(f"File {filepath} is empty or contains only whitespace. Using default data.")
                    return default_data
                print(f"Loaded {len(data) if isinstance(data, (list, dict)) else 'some'} records from {filepath}")
                return data
        except json.JSONDecodeError:
            print(f"Error decoding JSON from {filepath}. Starting with default data.")
            return default_data
        except Exception as e:
            print(f"An error occurred while loading {filepath}: {e}")
            traceback.print_exc() # Log loading error details
            return default_data
    else:
        print(f"File not found at {filepath}. Starting with default data.")
        return default_data


def save_data(filepath: str, data: Any):
    """Generic function to save data to a JSON file."""
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            # Use ensure_ascii=False to correctly save non-ASCII characters (like Ukrainian names)
            # Use indent=4 for pretty printing the JSON file (easier to read)
            json.dump(data, f, indent=4, ensure_ascii=False)
            # print(f"Saved {len(data) if isinstance(data, (list, dict)) else 'some'} records to {filepath}") # Optional: verbose logging
    except Exception as e:
        print(f"An error occurred while saving {filepath}: {e}")
        traceback.print_exc() # Log saving error details


# Load data when the application starts
@asynccontextmanager
async def lifespan(app: FastAPI): # Renamed and added app argument type hint
    """
    Handles application startup and shutdown events.
    Loads data on startup.
    """
    print("Loading data on startup...")
    global chat_history, users_data, active_sessions
    chat_history = load_data(CHAT_HISTORY_FILE, [])
    users_data = load_data(USERS_FILE, {})
    active_sessions = load_data(SESSIONS_FILE, {})
    print(f"Loaded {len(active_sessions)} active sessions from {SESSIONS_FILE}")

    yield

    print("Application shutting down.")

    print("Clearing active sessions...")
    active_sessions = {}

    try:
        os.remove(SESSIONS_FILE)
        print(f"Successfully removed {SESSIONS_FILE}")
    except FileNotFoundError:
        print(f"{SESSIONS_FILE} not found, nothing to remove.")
    except Exception as e:
        print(f"Error removing {SESSIONS_FILE}: {e}")

    save_chat_history()

app = FastAPI(lifespan=lifespan)

app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
templates = Jinja2Templates(directory=FRONTEND_DIR)

# Save chat history function now just calls generic save
def save_chat_history():
    save_data(CHAT_HISTORY_FILE, chat_history)

# Save users data function
def save_users_data():
    save_data(USERS_FILE, users_data)

# --- NEW: Save active sessions data function ---
def save_active_sessions():
    save_data(SESSIONS_FILE, active_sessions)


# --- User Authentication/Session Logic ---

# Pydantic model for login request body
class LoginRequest(BaseModel):
    username: str
    password: str

# Function to generate a unique session ID
def generate_session_id() -> str:
    # Use a slightly longer ID for session
    characters = string.ascii_letters + string.digits
    while True:
        session_id = ''.join(random.choice(characters) for i in range(32)) # Use a longer ID for better uniqueness
        # Check uniqueness against currently active sessions (in memory)
        if session_id not in active_sessions:
            # Also check if it coincidentally exists in the file history if needed,
            # but for temporary sessions, checking in-memory active ones is usually enough.
            return session_id


# Function to validate user credentials (simplified)
def validate_user_credentials(username: str, password: str) -> Optional[str]:
    """
    Checks if user exists and password matches (simplified check).
    Returns permanent_id if valid, otherwise None.
    """
    user_info = users_data.get(username)
    if user_info:
        # TODO: In a real app, HASH the password and compare hashes securely!
        # For this example, we just check if user_info exists and password matches plaintext.
        if user_info.get("password") == password: # Basic plaintext password check
            print(f"User '{username}' found and password matches. Logging in.")
            return user_info.get("permanent_id") # Return their permanent ID
        else:
            print(f"User '{username}' found, but password does not match.")
            return None # Password incorrect
    print(f"User '{username}' not found.")
    return None # User not found


# Function to create a new user and return permanent ID
def create_user(username: str, password: str) -> str:
    """
    Creates a new user entry and returns a permanent user ID.
    Assumes username does not already exist.
    """
    # Generate a permanent user ID for this user
    # Use uuid4() for better uniqueness in real app, but random string is fine for test
    # permanent_id = str(uuid4())
    permanent_id = 'user_' + ''.join(random.choice(string.ascii_lowercase + string.digits) for i in range(10))

    users_data[username] = {
        "password": password, # WARNING: Storing passwords in plain text is INSECURE!
        "permanent_id": permanent_id
    }
    save_users_data() # Save the updated users data immediately
    print(f"New user '{username}' created with permanent ID {permanent_id}. Saved users data.")
    return permanent_id

# Function to get permanent_user_id from a valid session_id
def get_user_id_from_session_id(session_id: str) -> Optional[str]:
    """Looks up the permanent_user_id for a given active session_id."""
    # Check if the session_id exists in our in-memory active sessions dictionary
    return active_sessions.get(session_id)


# --- Player Representation (Server Side) ---
class Player:
    # Player object is created when a WebSocket connects for an active session
    def __init__(self, session_id: str, permanent_user_id: str, websocket: WebSocket):
        self.session_id: str = session_id # The temporary session ID for this connection
        self.permanent_user_id: str = permanent_user_id # The permanent ID of the user
        self.websocket: WebSocket = websocket
        # Find the user's name from users_data using their permanent ID
        self.name: str = "Unknown User" # Default name
        for uname, udata in users_data.items():
            if udata.get("permanent_id") == permanent_user_id:
                self.name = uname # Use username as the display name
                break

        self.is_authenticated: bool = True # Player is "authenticated" if they have a valid session

    def to_dict(self) -> Dict[str, str]:
        """Returns a dictionary representation suitable for JSON response (/players)."""
        return {"permanent_user_id": self.permanent_user_id, "name": self.name}


    # Equality and hash based on session ID, as it's unique per active connection
    def __eq__(self, other):
        if not isinstance(other, Player):
            return NotImplemented
        return self.session_id == other.session_id

    def __hash__(self):
        return hash(self.session_id)


# --- Active WebSocket Connection Manager ---
class ConnectionManager:
    def __init__(self):
        # Dictionary to hold active players: {session_id: Player_object}
        # This represents the *currently connected* websockets, not active sessions in general.
        self.active_players: Dict[str, Player] = {}
        print("ConnectionManager initialized.")

    # Connect method accepts session_id and permanent_user_id
    async def connect(self, session_id: str, permanent_user_id: str, websocket: WebSocket) -> Player:
        """
        Accepts a new WebSocket connection for a validated session,
        creates a Player object, and adds it to the manager of *connected* players.
        """
        await websocket.accept()

        # Check if a player with this session ID is already actively connected via WS
        if session_id in self.active_players:
            print(f"Warning: Session ID {session_id} is already connected. Replacing old connection.")
            # Optional: Close the old connection cleanly
            try:
                old_websocket = self.active_players[session_id].websocket
                if old_websocket.client_state != websockets.enums.ClientState.CLOSED:
                    # Use a close code indicating replacement or policy violation
                    await old_websocket.close(code=1008, reason="New connection for same session ID") # 1008 Policy Violation
            except Exception as e:
                print(f"Error closing old websocket for session {session_id}: {e}")


        # Create a Player object using the session ID and permanent user ID
        player = Player(session_id, permanent_user_id, websocket)
        # Add the player to our dictionary of *currently connected* players using the session ID as key
        self.active_players[session_id] = player

        print(f"New WebSocket connection established for Session ID: {session_id} (User ID: {permanent_user_id}, Name: {player.name}). Total active WebSocket connections: {len(self.active_players)}")

        # --- Send chat history to the newly connected player ---
        # Use send_json directly on the specific player's websocket
        await player.websocket.send_json({"type": "chat_history", "messages": chat_history})
        print(f"Sent chat history ({len(chat_history)} messages) to Session {session_id}")

        # --- Inform others that this user has joined the chat (using permanent ID and name) ---
        # Note: This means "joined the chat", not "logged in". A user logs in, gets a session,
        # and then joins the chat via WebSocket with that session.
        # We broadcast this after the new player has received the history.
        await self.broadcast_json({"type": "player_joined", "permanent_user_id": permanent_user_id, "name": player.name, "total_players": len(self.active_players)})


        return player # Return the new player object


    # Disconnect method uses session_id of the WebSocket connection
    async def disconnect(self, session_id: str):
        """Removes a player's *WebSocket connection* from the manager using their session_id."""
        if session_id in self.active_players:
            player_name = self.active_players[session_id].name # Get name before removing
            permanent_user_id = self.active_players[session_id].permanent_user_id

            # Try to close the websocket cleanly
            try:
                websocket = self.active_players[session_id].websocket
                if websocket.client_state != websockets.enums.ClientState.CLOSED:
                    await websocket.close(code=1000, reason="Disconnected by server")  # Explicitly close
            except Exception as e:
                print(f"Error closing websocket for session {session_id} during disconnect: {e}")

            del self.active_players[session_id]
            print(f"WebSocket connection for Session {session_id} closed (User ID: {permanent_user_id}, Name: {player_name}). Remaining active WebSocket connections: {len(self.active_players)}")

            # --- IMPORTANT: We do NOT remove the session_id from active_sessions file here! ---
            # A session is active until it expires (which we haven't implemented yet)
            # or the user explicitly logs out. Disconnecting the websocket only means
            # the user closed the chat tab, not that their login session is invalid.
            # The session should persist so they can reconnect.
            # If you *did* want disconnecting the WS to invalidate the session, you would add:
            # if session_id in active_sessions: del active_sessions[session_id]; save_active_sessions()


            # Inform ALL remaining connected clients that this player disconnected from chat.
            await self.broadcast_json({"type": "player_left", "permanent_user_id": permanent_user_id, "name": player_name, "remaining_players": len(self.active_players)})
        else:
            print(f"Attempted to disconnect session {session_id} from ConnectionManager but ID not found in active_players (was already removed?).")


    async def broadcast_json(self, message_data: Dict[str, Any]):
        """Sends a JSON message (as dict) to all connected clients."""
        players_to_send = list(self.active_players.values())

        for player in players_to_send:
            try:
                await player.websocket.send_json(message_data)
            except (WebSocketDisconnect, websockets.exceptions.ConnectionClosedOK, websockets.exceptions.ConnectionClosedError):
                print(f"WebSocketDisconnect detected during broadcast to session {player.session_id}. Removing connection.")
                await self.disconnect(player.session_id)
            except Exception as e:
                print(f"Error during broadcast JSON message to session {player.session_id}: {e}")
                traceback.print_exc()
                await self.disconnect(player.session_id)


    # This method now gets *currently connected* players' data
    def get_active_players_data(self) -> List[Dict[str, str]]:
        """Returns a list of dictionary representations of *currently connected* players (permanent ID and name)."""
        return [player.to_dict() for player in self.active_players.values()]


    # We no longer need get_player_by_session_id in Manager itself,
    # validation happens in the endpoint using the global active_sessions.
    # The Player object obtained after successful connection check has the session_id.


manager = ConnectionManager()


# --- HTTP Endpoint for Root Page ---
@app.get("/", response_class=HTMLResponse)
async def root():
    return RedirectResponse(url="/login")


@app.get("/login", response_class=HTMLResponse)
async def get_login_page(request: Request):
    # Ideally, here you'd check for a valid session cookie. If found,
    # redirect directly to /chat. For simplicity, always serve login page for now.
    return templates.TemplateResponse("login.html", {"request": request})


# --- HTTP Endpoint for Login (POST) ---
@app.post("/login")
async def login_or_register(login_request: LoginRequest):
    username = login_request.username
    password = login_request.password

    if not username or not password:
        return JSONResponse(status_code=400, content={"detail": "Username and password cannot be empty."})

    # --- Authentication/Registration Logic ---
    permanent_user_id = validate_user_credentials(username, password) # Try to validate existing user

    if permanent_user_id is None:
        # User does NOT exist or password was incorrect (with simplified check)
        # Assuming correct password if username exists for now, so this branch is only for new users
        if username in users_data: # If username exists but validate_user_credentials failed (means password incorrect in this simplified logic)
            print(f"Login failed for user '{username}': Incorrect password.")
            return JSONResponse(status_code=401, content={"detail": "Incorrect username or password."})
        else:
            # User does NOT exist, create a new user
            return JSONResponse(status_code=401, content={"detail": "User does not exist."})

    # User exists and credentials are valid (or new user just created). Establish a session.
    # Generate a temporary session ID for this login session.
    session_id = generate_session_id()

    # --- NEW: Handle existing active sessions ---
    # Check if this user already has an active session
    existing_session_id = None
    for s_id, u_id in active_sessions.items():
        if u_id == permanent_user_id:
            existing_session_id = s_id
            break # Found the existing session

    if existing_session_id:
        print(f"User {username} (Permanent ID: {permanent_user_id}) already has an active session {existing_session_id}.  Terminating old session.")
        # --- NEW: Terminate the old session ---
        # 1. Remove the session from active_sessions

        # 2. (IMPORTANT) Disconnect the WebSocket for the old session
        # If they are *currently connected* via WebSocket
        if existing_session_id in manager.active_players:
            print(f"User {username} had active WebSocket connection, disconnecting it.")

            # --- Send a message to the old client BEFORE disconnecting ---
            try:
                old_websocket = manager.active_players[existing_session_id].websocket
                await old_websocket.send_json({"type": "session_terminated", "message": "Your session has been terminated due to a new login."})
            except Exception as e:
                print(f"Error sending session terminated message to old client: {e}")

            await manager.disconnect(existing_session_id) # Disconnect their active websocket

        del active_sessions[existing_session_id]

        # --- Save active sessions to file immediately after terminating old session. ---
        save_active_sessions()

    # Map the new session ID to the user's permanent ID in our in-memory dictionary
    active_sessions[session_id] = permanent_user_id

    # Save the updated active sessions to the file
    save_active_sessions()
    print(f"Session {session_id} created for user {username} (Permanent ID: {permanent_user_id}). Saved active sessions.")


    # Return the session ID to the client. Frontend JS will use this for WebSocket connection.
    return JSONResponse(content={"session_id": session_id})


@app.get("/registration", response_class=HTMLResponse)
async def get_register_page(request: Request):
    # Ideally, here you'd check for a valid session cookie. If found,
    # redirect directly to /chat. For simplicity, always serve login page for now.
    return templates.TemplateResponse("registration.html", {"request": request})


# --- HTTP Endpoint for Registration (POST) ---
@app.post("/registration")
async def register_user(login_request: LoginRequest):
    username = login_request.username
    password = login_request.password

    if not username or not password:
        return JSONResponse(status_code=400, content={"detail": "Username and password cannot be empty."})

    if username in users_data:
        print(f"Registration failed: User '{username}' already exists.")
        return JSONResponse(status_code=409, content={"detail": "Username already exists."})  # 409 Conflict

    # User does NOT exist, create a new user
    print(f"Registering new user '{username}'...")
    permanent_user_id = create_user(username, password)  # Create and save user
    
    session_id = generate_session_id()
    
    # Map the new session ID to the user's permanent ID in our in-memory dictionary
    active_sessions[session_id] = permanent_user_id

    # Save the updated active sessions to the file
    save_active_sessions()
    print(f"Session {session_id} created for user {username} (Permanent ID: {permanent_user_id}). Saved active sessions.")
    
    print(f"Registration successful for user '{username}' with permanent ID {permanent_user_id}.")

    # Return the session ID to the client. Frontend JS will use this for WebSocket connection.
    return JSONResponse(content={"session_id": session_id})


# --- HTTP Endpoint for Chat Page ---
# Accessing "/chat" serves the chat.html page, but REQUIRES a valid session_id.
@app.get("/chat", response_class=HTMLResponse)
async def get_chat_page(request: Request):
    # Get session_id from query parameter (as sent by login.html redirect)
    session_id = request.query_params.get("session_id")

    permanent_user_id = get_user_id_from_session_id(session_id)

    if not session_id or not permanent_user_id:
        # If session_id is missing, invalid, or not in our active_sessions
        print(f"Access to /chat denied: Invalid or missing session_id: {session_id}. Redirecting to login.")
        return RedirectResponse(url="/login", status_code=302) # 302 Found (Temporary Redirect)


    # If session ID is valid and found in active_sessions, render the chat page.
    # Pass the session_id to the template so the frontend JS knows how to connect to WebSocket.
    print(f"Access to /chat granted for session_id {session_id} (User ID: {permanent_user_id}). Rendering chat page.")
    # We can also pass user's permanent ID and name to the template if helpful for frontend
    user_name = ""
    for uname, udata in users_data.items():
        if udata.get("permanent_id") == permanent_user_id:
            user_name = uname
            break

    return templates.TemplateResponse("chat.html", {"request": request, "session_id": session_id, "permanent_user_id": permanent_user_id, "user_name": user_name})

# --- HTTP Endpoint for Connected users list (GET) ---
@app.get("/users", response_class=JSONResponse)
async def get_active_users_list():

    """Returns a list of currently connected users with their permanent IDs and names."""
    active_connected_users_data = manager.get_active_players_data()
    print(f"Received request for active users list. Currently {len(active_connected_users_data)} active WebSocket connections.")

    return active_connected_users_data # This will return a list: [{"permanent_user_id": "...", "name": "..."}, ...]


# --- WebSocket Endpoint ---
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, session_id: str = None): # Expect session_id as query param
    print(f"Attempting WebSocket connection for session_id: {session_id}...")

    # --- Validate the session_id using our active_sessions data ---
    permanent_user_id = get_user_id_from_session_id(session_id)

    if not session_id or not permanent_user_id:
        # If session_id is missing or invalid (not found in active_sessions), reject connection
        print(f"WebSocket connection denied: Invalid or missing session_id: {session_id}.")
        # Accept the connection briefly to send an error message before closing
        await websocket.accept()
        try:
            await websocket.send_json({"type": "error", "message": "Invalid or expired session ID. Please log in again."})
            # Use a specific close code for policy violation or invalid credentials
            await websocket.close(code=1008) # 1008 Policy Violation is common for auth issues
        except Exception as e:
            print(f"Error sending WebSocket close message: {e}")

        print(f"WebSocket connection closed for invalid session_id: {session_id}.")
        return # Stop processing this connection


    # Session ID is valid, proceed with connection
    print(f"WebSocket connection authorized for session_id {session_id} (User ID: {permanent_user_id}).")

    # Connect the player using the validated session ID and permanent user ID
    # manager.connect adds to active_players, sends history, and broadcasts player_joined
    player = await manager.connect(session_id, permanent_user_id, websocket)

    try:
        # --- Main loop: Handle subsequent messages (e.g., chat messages, game actions) ---
        # The initial name setting is done via login. The client doesn't send name here.
        while True:
            # Wait for the next message from this client. Expecting JSON for actions in a real game.
            # For now, still accepting text for chat messages.
            data = await websocket.receive_text()

            message_text = data.strip()
            if message_text:
                chat_message = {
                    "type": "chat_message",
                    "permanent_user_id": player.permanent_user_id,
                    "sender": player.name,
                    "text": message_text,
                    "timestamp": time.time()
                }

                chat_history.append(chat_message)
                save_chat_history() # Save history after adding message

                await manager.broadcast_json(chat_message) # Broadcast to all connected players
            else:
                print(f"Received empty message from session {player.session_id} ('{player.name}'). Ignoring.")


    except (WebSocketDisconnect, websockets.exceptions.ConnectionClosedOK, websockets.exceptions.ConnectionClosedError) as e:
        # Handle player disconnection from WebSocket.
        disconnected_session_id = player.session_id if 'player' in locals() else session_id

        if disconnected_session_id in manager.active_players:
            print(f"Session {disconnected_session_id} ('{manager.active_players[disconnected_session_id].name}') disconnected from WebSocket: {e}")
            await manager.disconnect(disconnected_session_id)
        else:
            print(f"A WebSocket disconnected (session {disconnected_session_id}) but was already removed from ConnectionManager. {e}")


    except Exception as e:
        session_id_info = player.session_id if 'player' in locals() and player else session_id
        player_name_info = player.name if 'player' in locals() and player else "N/A"
        print(f"Unexpected error in WebSocket connection for session {session_id_info} ('{player_name_info}'): {e}")
        traceback.print_exc()

        if 'player' in locals() and player and player.websocket:
            try:
                error_msg = {"type": "server_error", "message": "An unexpected server error occurred with your connection."}
                await player.websocket.send_json(error_msg)
            except Exception:
                pass

        if 'player' in locals() and player and player.session_id in manager.active_players:
            await manager.disconnect(player.session_id)
        else:
            if 'websocket' in locals():
                try:
                    await websocket.close(code=1011)
                except Exception:
                    pass

        permanent_id_info = player.permanent_user_id if 'player' in locals() and player else "N/A"
        await manager.broadcast_json({"type": "player_error", "permanent_user_id": permanent_id_info, "name": player_name_info, "message": f"An error occurred with {player_name_info}'s connection."})


# To run this server:
# 1. Make sure you are in the 'backend/' directory in your terminal.
# 2. Ensure your virtual environment is activated ('source venv/bin/activate').
# 3. Run the command:
#    uvicorn main:app --reload
# 4. Open http://localhost:8000/ to see the login page.
# 5. Enter username/password and click submit. You should be redirected to /chat?session_id=....
# 6. Open / in other tabs, use same or different credentials to test login/registration flow.
# 7. Open http://localhost:8000/players to see the list of players currently CONNECTED to chat.
# 8. Crucially, stop and restart the server. Then try opening /chat with a session_id from a previous login
#    (copy the URL from before restart). It should now allow connection because active sessions are saved/loaded.
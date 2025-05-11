import json
import os
import random
import string
import time
import uuid
import traceback
from typing import List, Dict, Any, Optional

from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, Query
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

# --- Configuration and Initialization ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(BASE_DIR, "../frontend")

DATABASE_DIR = os.path.join(BASE_DIR, "database")
CHAT_HISTORY_FILE = os.path.join(DATABASE_DIR, "chat_history.json")
USERS_FILE = os.path.join(DATABASE_DIR, "users.json")
SESSIONS_FILE = os.path.join(DATABASE_DIR, "active_sessions.json") # Stores active session_id -> permanent_user_id mapping

# --- Data Storage (in-memory cache) ---
# Note: This is simple in-memory storage with file persistence.
# For high-traffic or critical applications, a proper database (like PostgreSQL, SQLite, Redis) is recommended.
chat_history: List[Dict[str, Any]] = []
users_data: Dict[str, Dict[str, str]] = {} # Stores username -> {password, permanent_id}
active_sessions: Dict[str, str] = {} # Stores session_id -> permanent_user_id for currently logged-in sessions


# --- Persistence Functions ---
def load_data(filepath: str, default_data: Any):
    """Loads data from a JSON file."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        # Return default data if file not found or corrupted
        return default_data
    except Exception as e:
        print(f"Error loading data from {filepath}: {e}")
        return default_data


def save_data(filepath: str, data: Any):
    """Saves data to a JSON file."""
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving data to {filepath}: {e}")


# Lifespan context manager for application startup and shutdown
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Application startup: Loading data...")
    global chat_history, users_data, active_sessions
    chat_history = load_data(CHAT_HISTORY_FILE, [])
    users_data = load_data(USERS_FILE, {})
    # active_sessions are typically volatile and might not need persistent loading,
    # but loading allows potential recovery after a crash (though managing stale sessions is complex)
    # Let's load them for now as per original logic
    active_sessions = load_data(SESSIONS_FILE, {})

    print(f"Loaded {len(chat_history)} chat messages from {CHAT_HISTORY_FILE}")
    print(f"Loaded {len(users_data)} users from {USERS_FILE}")
    print(f"Loaded {len(active_sessions)} active sessions from {SESSIONS_FILE}")

    yield # Application is running

    # Application shutdown
    print("Application shutting down: Saving data and cleaning up...")
    # Active sessions are cleared on shutdown to prevent stale sessions on restart
    # (This is a design choice - might need adjustment based on requirements)
    active_sessions = {}
    try:
        # Optionally remove the sessions file on clean shutdown
        if os.path.exists(SESSIONS_FILE):
            os.remove(SESSIONS_FILE)
            print(f"Successfully removed {SESSIONS_FILE} on shutdown.")
        else:
            print(f"{SESSIONS_FILE} not found on shutdown, nothing to remove.")

    except Exception as e:
        print(f"Error removing {SESSIONS_FILE} on shutdown: {e}")

    # Save chat history on shutdown
    save_chat_history()
    save_users_data() # Ensure users are saved if any new ones were created during runtime
    save_active_sessions() # Save empty sessions just in case file wasn't removed


app = FastAPI(lifespan=lifespan)

# Mount static files (HTML, CSS, JS from frontend)
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
templates = Jinja2Templates(directory=FRONTEND_DIR)

# Helper functions to save specific data files
# These just wrap the generic save_data for clarity
def save_chat_history():
    save_data(CHAT_HISTORY_FILE, chat_history)

def save_users_data():
    save_data(USERS_FILE, users_data)

def save_active_sessions():
    save_data(SESSIONS_FILE, active_sessions)


# --- User Authentication and Session Management ---

class LoginRequest(BaseModel):
    """Pydantic model for login/registration request body."""
    username: str
    password: str

def generate_session_id() -> str:
    """Generates a unique random session ID."""
    characters = string.ascii_letters + string.digits
    return ''.join(random.choice(characters) for _ in range(32)) # Use _ for unused loop variable


def validate_user_credentials(username: str, password: str) -> Optional[str]:
    """Validates username and password. Returns permanent_user_id if valid, None otherwise."""
    user_info = users_data.get(username)
    if user_info and user_info.get("password") == password:
        return user_info.get("permanent_id")
    return None


def create_user(username: str, password: str) -> str:
    """Creates a new user and returns their permanent ID."""
    # Check if user already exists before creating (should be handled by caller)
    if username in users_data:
        raise ValueError(f"User '{username}' already exists.")

    permanent_id = 'user_' + ''.join(random.choice(string.ascii_lowercase + string.digits) for _ in range(10))

    users_data[username] = {
        "password": password, # In a real app, store hashed passwords!
        "permanent_id": permanent_id
    }
    save_users_data()
    print(f"New user '{username}' created with permanent ID {permanent_id}.")
    return permanent_id

def get_user_id_from_session_id(session_id: str) -> Optional[str]:
    """Gets permanent_user_id from a valid active session ID."""
    return active_sessions.get(session_id)

def get_username_from_permanent_id(permanent_user_id: str) -> str:
    """Gets username from permanent user ID."""
    for username, user_info in users_data.items():
        if user_info.get("permanent_id") == permanent_user_id:
            return username
    return "Unknown User" # Default if ID not found (shouldn't happen with valid IDs)


# --- Player Representation (Server Side) ---
class Player:
    """Represents a single active WebSocket connection for a user session."""
    def __init__(self, session_id: str, permanent_user_id: str, websocket: WebSocket):
        self.session_id: str = session_id
        self.permanent_user_id: str = permanent_user_id
        self.websocket: WebSocket = websocket
        self.connection_id: str = str(uuid.uuid4()) # Unique ID for THIS connection instance
        self.name: str = get_username_from_permanent_id(permanent_user_id)
        self.is_authenticated: bool = True # Implicitly True if Player object is created after validation

    def to_dict(self) -> Dict[str, str]:
        """Returns a dictionary representation for broadcasting/listing players."""
        return {"permanent_user_id": self.permanent_user_id, "name": self.name}

    # Implement __eq__ and __hash__ based on connection_id for potential set/dict usage
    def __eq__(self, other):
        return isinstance(other, Player) and self.connection_id == other.connection_id

    def __hash__(self):
        return hash(self.connection_id)


# --- Active WebSocket Connection Manager ---
class ConnectionManager:
    """Manages active WebSocket connections (Players) by session ID."""
    def __init__(self):
        # Stores the *currently active* Player object for each session_id
        self.active_players: Dict[str, Player] = {}
        print("ConnectionManager initialized.")

    async def connect(self, session_id: str, permanent_user_id: str, websocket: WebSocket) -> Player:
        """Handles a new WebSocket connection request."""
        await websocket.accept()

        player = Player(session_id, permanent_user_id, websocket)

        # --- Session Takeover Logic ---
        # If a connection for this session ID already exists, terminate the old one.
        if session_id in self.active_players:
            old_player = self.active_players[session_id]
            print(f"Session ID {session_id} ({player.name}, Conn ID: {player.connection_id}) is already connected. Terminating old connection (Conn ID: {old_player.connection_id}).")
            try:
                # Send termination message to the old connection
                await old_player.websocket.send_json({"type": "session_terminated", "message": "Your session has been taken over by a new connection."})
                # Close the old connection with code 1008 (Policy Violation)
                await old_player.websocket.close(code=1008, reason="New connection for same session ID")
            except Exception as e:
                # Log any errors during old connection termination
                print(f"Error closing old websocket for session {session_id} (Conn ID: {old_player.connection_id}): {e}")

            # Optional: Announce the old player leaving before adding the new one.
            # This helps other clients see the old connection dropped.
            # await self.broadcast_json({"type": "player_left", "permanent_user_id": old_player.permanent_user_id, "name": old_player.name, "remaining_players": len(self.active_players)}) # Note: active_players count will be wrong here

        # Add the new player to the active connections dictionary
        self.active_players[session_id] = player

        print(f"New WebSocket connection established for Session ID: {session_id} (User ID: {player.permanent_user_id}, Name: {player.name}, Connection ID: {player.connection_id}). Total active WebSocket connections: {len(self.active_players)}")

        # Send chat history to the newly connected player
        await player.websocket.send_json({"type": "chat_history", "messages": chat_history})

        # Announce the player joining (the new connection)
        await self.broadcast_json({"type": "player_joined", "permanent_user_id": player.permanent_user_id, "name": player.name, "totalPlayers": len(self.active_players)})

        return player

    async def disconnect(self, player: Player):
        """Handles a WebSocket disconnection."""
        print(f"Attempting to disconnect player {player.name} ({player.permanent_user_id}, Conn ID: {player.connection_id}) with Session {player.session_id}.")
        # Check if the player object being disconnected is still the active one for this session ID.
        # This is crucial because a new connection for the same session might have taken over already.
        if player.session_id in self.active_players and self.active_players[player.session_id].connection_id == player.connection_id:
            # If it is the active player for this session, remove them
            print(f"Removing active player {player.name} ({player.permanent_user_id}, Conn ID: {player.connection_id}) from active players.")
            del self.active_players[player.session_id]
            remaining_players_count = len(self.active_players)
            print(f"Remaining active WebSocket connections after removing {player.name}: {remaining_players_count}")

            # Broadcast player leaving message to remaining players
            await self.broadcast_json({"type": "player_left", "permanent_user_id": player.permanent_user_id, "name": player.name, "remaining_players": remaining_players_count})
        else:
            # If the player being disconnected was already replaced by a new connection for the same session ID,
            # we don't remove anything from active_players, as it holds the new connection.
            print(f"Player {player.name} ({player.permanent_user_id}, Conn ID: {player.connection_id}) disconnected, but was already replaced in active_players. No removal needed from manager.")


    async def broadcast_json(self, message_data: Dict[str, Any]):
        """Broadcasts a JSON message to all active connections."""
        # Iterate over a list copy in case disconnect modifies the dict during iteration
        for session_id, player in list(self.active_players.items()):
            try:
                await player.websocket.send_json(message_data)
            except WebSocketDisconnect:
                # If sending fails due to disconnect, remove the player.
                print(f"WebSocketDisconnect detected during broadcast to session {player.session_id} ({player.name}, Conn ID: {player.connection_id}). Removing connection.")
                # Call disconnect with the specific player object that failed
                await self.disconnect(player)
            except Exception as e:
                # Handle other potential errors during send (e.g., connection closed unexpectedly)
                print(f"Error during broadcast JSON message to session {player.session_id} ({player.name}, Conn ID: {player.connection_id}): {e}")
                traceback.print_exc()
                # Attempt to disconnect the player on error
                await self.disconnect(player)


    def get_active_players_data(self) -> List[Dict[str, str]]:
        """Returns a list of dicts representing active players."""
        return [player.to_dict() for player in self.active_players.values()]


manager = ConnectionManager()


# --- HTTP Endpoints ---

@app.get("/", response_class=HTMLResponse)
async def root():
    """Redirects root URL to login page."""
    return RedirectResponse(url="/login", status_code=302)


@app.get("/login", response_class=HTMLResponse)
async def get_login_page(request: Request):
    """Serves the login page."""
    # In a real app, check for session cookie and redirect to chat if valid
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/login")
async def login_user(login_request: LoginRequest):
    """Handles login requests."""
    username = login_request.username
    password = login_request.password

    if not username or not password:
        return JSONResponse(status_code=400, content={"detail": "Username and password cannot be empty."})

    permanent_user_id = validate_user_credentials(username, password)

    if permanent_user_id is None:
        print(f"Login failed for user '{username}': Incorrect username or password.")
        return JSONResponse(status_code=401, content={"detail": "Incorrect username or password."})

    # User exists and credentials are valid.
    print(f"Login successful for user '{username}' (Permanent ID: {permanent_user_id}).")

    # --- Session Management: Find and invalidate old active session ---
    existing_session_id = None
    for s_id, u_id in list(active_sessions.items()): # Use list() to iterate over a copy if modifying
        if u_id == permanent_user_id:
            existing_session_id = s_id
            break

    if existing_session_id:
        print(f"User '{username}' already had active session {existing_session_id}. Terminating old session and its WebSocket.")

        # --- Find the old player's WebSocket connection in the manager ---
        # Check if the player with this old session ID is currently active in the ConnectionManager
        if existing_session_id in manager.active_players:
            old_player = manager.active_players[existing_session_id]
            print(f"Found active WebSocket for old session {existing_session_id} (Conn ID: {old_player.connection_id}). Sending termination signal and closing.")
            try:
                # Send termination message to the old connection
                await old_player.websocket.send_json({"type": "session_terminated", "message": "Your session has been terminated due to a new login."})
                # Close the old connection. This will trigger its disconnect handler in websocket_endpoint.
                await old_player.websocket.close(code=1008, reason="New login for same user")
                print(f"Termination signal and close sent to old connection {old_player.connection_id}.")
            except Exception as e:
                # Log any errors during old connection termination
                print(f"Error closing old websocket for session {existing_session_id} (Conn ID: {old_player.connection_id}): {e}")
                # Even if closing fails, the old session ID is removed from active_sessions below,
                # and the new connection will take precedence in active_players eventually.

        # Remove the old session ID from the active_sessions mapping (this is already in your code, just clarifying)
        if existing_session_id in active_sessions: # Double check in case it was removed elsewhere
            del active_sessions[existing_session_id]
            save_active_sessions() # Save after removal

    # --- Create and activate the new session ---
    session_id = generate_session_id()
    active_sessions[session_id] = permanent_user_id
    save_active_sessions() # Save after adding the new session

    print(f"New session {session_id} created for user '{username}'.")

    # Return the new session ID to the client for redirect and WebSocket connection
    return JSONResponse(content={"session_id": session_id})


@app.get("/registration", response_class=HTMLResponse)
async def get_register_page(request: Request):
    """Serves the registration page."""
    # In a real app, check for session cookie and redirect to chat if valid
    return templates.TemplateResponse("registration.html", {"request": request})


@app.post("/registration")
async def register_user(login_request: LoginRequest):
    """Handles registration requests."""
    username = login_request.username
    password = login_request.password

    if not username or not password:
        return JSONResponse(status_code=400, content={"detail": "Username and password cannot be empty."})

    if username in users_data:
        print(f"Registration failed: User '{username}' already exists.")
        return JSONResponse(status_code=409, content={"detail": "Username already exists."})

    # Create new user and get permanent ID
    permanent_user_id = create_user(username, password)

    # Create a new session for the newly registered user
    session_id = generate_session_id()
    active_sessions[session_id] = permanent_user_id
    save_active_sessions()

    print(f"Registration successful for user '{username}' (Permanent ID: {permanent_user_id}). Created session {session_id}.")
    # Return the new session ID so the client can proceed to chat
    return JSONResponse(content={"session_id": session_id})


@app.get("/chat", response_class=HTMLResponse)
async def get_chat_page(request: Request):
    """Serves the chat page, requires a valid session_id query parameter."""
    # Get session_id from query parameter (passed from login/registration redirect)
    session_id = request.query_params.get("session_id")

    # Validate session ID
    permanent_user_id = get_user_id_from_session_id(session_id)

    if not session_id or not permanent_user_id:
        print(f"Access to /chat denied: Invalid or missing session_id: {session_id}. Redirecting to login.")
        return RedirectResponse(url="/login", status_code=302)

    # If session ID is valid, get user info and render chat page
    user_name = get_username_from_permanent_id(permanent_user_id)
    print(f"Access to /chat granted for session_id {session_id} (User ID: {permanent_user_id}, Name: {user_name}). Rendering chat page.")

    # Pass session_id, user_id, and user_name to the template for frontend JS
    return templates.TemplateResponse("chat.html", {
        "request": request,
        "session_id": session_id,
        "permanent_user_id": permanent_user_id,
        "user_name": user_name
    })

@app.get("/users", response_class=JSONResponse)
async def get_active_users_list():
    """Returns a list of currently active players (based on WebSocket connections)."""
    active_connected_users_data = manager.get_active_players_data()
    print(f"Received request for active users list. Currently {len(active_connected_users_data)} active WebSocket connections.")
    return active_connected_users_data


# --- WebSocket Endpoint ---
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, session_id: str = Query(None)):
    """Handles WebSocket connections for chat."""
    print(f"Attempting WebSocket connection for session_id: {session_id}...")

    # Validate session ID immediately upon connection request
    permanent_user_id = get_user_id_from_session_id(session_id)

    if not session_id or not permanent_user_id:
        print(f"WebSocket connection denied: Invalid or missing session_id: {session_id}.")
        await websocket.accept() # Accept to send rejection message
        await websocket.send_json({"type": "error", "message": "Invalid or expired session ID. Please log in again."})
        await websocket.close(code=1008) # Policy Violation code
        return

    print(f"WebSocket connection authorized for session_id {session_id} (User ID: {permanent_user_id}).")

    player = None # Initialize player variable before the try block
    try:
        # Connect the player using the ConnectionManager
        player = await manager.connect(session_id, permanent_user_id, websocket)

        # Main loop for receiving messages
        while True:
            # Receive text data from the WebSocket
            data = await websocket.receive_text()
            message_text = data.strip()

            # Ignore empty messages
            if not message_text:
                continue

            # Prepare chat message data
            chat_message = {
                "type": "chat_message",
                "permanent_user_id": player.permanent_user_id,
                "sender": player.name,
                "text": message_text,
                "timestamp": time.time()
            }

            # Add message to history and save
            chat_history.append(chat_message)
            save_chat_history() # Consider batching saves for performance in busy chats

            # Broadcast the message to all active connections
            await manager.broadcast_json(chat_message)

    except WebSocketDisconnect as e:
        # Handle expected WebSocket disconnections (client closed, server closed with code)
        session_id_info = player.session_id if player else session_id
        player_name_info = player.name if player else "N/A"
        print(f"WebSocket disconnected for Session {session_id_info} ('{player_name_info}'): {e.code}, {e.reason}")
        # Call disconnect manager - pass the player object if it exists
        if player:
            await manager.disconnect(player)
        else:
            print(f"WebSocketDisconnect occurred before player object was fully created for session {session_id_info}.")


    except Exception as e:
        # Handle any other unexpected errors during WebSocket processing
        # Determine player info for logging, handling case where player object wasn't created
        session_id_info = session_id
        player_name_info = "N/A"
        permanent_id_info = "N/A"

        if player: # If player object was successfully created
            session_id_info = player.session_id
            player_name_info = player.name
            permanent_id_info = player.permanent_user_id
            print(f"Unexpected error in WebSocket connection for session {session_id_info} ('{player_name_info}', Conn ID: {player.connection_id if player else 'N/A'}): {e}")
            traceback.print_exc()

            # Attempt to send an error message back to the client if the socket is still open
            if player.websocket and player.websocket.readyState == WebSocket.OPEN:
                try:
                    error_msg = {"type": "server_error", "message": "An unexpected server error occurred with your connection."}
                    await player.websocket.send_json(error_msg)
                except Exception:
                    # Ignore errors if we can't even send the error message
                    pass

            # Attempt to disconnect the player gracefully through the manager
            await manager.disconnect(player)

        else: # If the error happened before player object was created (e.g., during accept)
            print(f"Unexpected error in WebSocket connection for session {session_id_info} before player object created: {e}")
            traceback.print_exc()
            # Attempt to close the raw websocket connection if it exists
            # Check if the 'websocket' variable is defined in the local scope
            if 'websocket' in locals() and websocket:
                try:
                    # Use code 1011 for internal server error
                    await websocket.close(code=1011, reason="Internal Server Error")
                except Exception:
                    # Ignore errors if we can't close the socket
                    pass

        # Optionally broadcast a message indicating a player connection had an error
        # Use the player info determined above
        if 'manager' in globals() and hasattr(manager, 'broadcast_json'):
            # Note: This message will be broadcast even if player object wasn't fully created,
            # providing info about a failed connection attempt related to a session ID.
            error_broadcast_info = {
                "type": "player_error",
                "permanent_user_id": permanent_id_info,
                "name": player_name_info,
                "message": f"An error occurred with {player_name_info}'s connection."
            }
            # Avoid broadcasting if it's just an error during the initial invalid session check
            # This check might be too complex, simplified version:
            # Only broadcast player_error if player object was successfully created before the error
            if player:
                await manager.broadcast_json(error_broadcast_info)
            else:
                print("Skipping player_error broadcast as player object was not created.")


# --- Main execution block (for running with uvicorn) ---
# This part is usually not needed if you run with `uvicorn main:app --reload`
# but can be included if you want to run the file directly
# if __name__ == "__main__":
#    import uvicorn
#    uvicorn.run(app, host="127.0.0.1", port=8000)
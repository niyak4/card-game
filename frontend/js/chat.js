// frontend/js/chat.js

document.addEventListener('DOMContentLoaded', () => {
    console.log("Script execution started after DOMContentLoaded!");

    const statusDiv = document.getElementById('status');
    const playerIdDisplay = document.getElementById('playerIdDisplay');
    const playerNameDisplay = document.getElementById('playerNameDisplay');
    const messagesDiv = document.getElementById('messages');
    const messageInput = document.getElementById('messageInput');
    const sendButton = document.getElementById('sendButton');

    let websocket;

    // --- Get session_id ---
    const urlParams = new URLSearchParams(window.location.search);
    const sessionId = urlParams.get('session_id'); // Get session_id from ?session_id=...

    // --- LOGGING BLOCK ---
    console.log("Current URL:", window.location.href);
    console.log("URL search params:", window.location.search);
    console.log("Attempting to retrieve 'session_id' from URL params...");
    console.log("Retrieved session_id:", sessionId); // ADDED: This log should definitely appear if script runs this far

    // --- NO SESSION ID FOUND ---
    if (!sessionId) {
        console.error("No session ID found in URL. Redirecting to login page in 2 seconds."); // ADDED: Log before redirect
        setTimeout(() => {
            window.location.href = '/login';
        }, 2000);
        return;
    }

    // --- WebSocket Connection ---
    let wsProtocol = window.location.protocol === 'https:' ? 'wss://' : 'ws://';
    let wsHost = window.location.host; // This will be 'localhost:8000' or '19b3-...ngrok.app'
    let wsPath = '/ws';
    let wsQuery = window.location.search;

    const websocketUrl = `${wsProtocol}${wsHost}${wsPath}${wsQuery}`; // Combine parts

    console.log(`Attempting to connect via WebSocket using URL: ${websocketUrl}`);


    // Function to connect to the WebSocket server
    function connectWebSocket() {
        websocket = new WebSocket(websocketUrl);

        // --- WebSocket Event Handlers ---

        websocket.onopen = function (event) {
            console.log("WebSocket connection opened", event);
            // The player is considered 'joined' after validation and initial setup on the server.
            // Server will send chat_history and player_joined messages.
            // Input is enabled only after receiving initial data/history.
        };

        websocket.onmessage = function (event) {
            try {
                const message = JSON.parse(event.data);
                console.log("Parsed message:", message);

                // --- Message Type Handling ---
                switch (message.type) {
                    case 'chat_history':
                        // Server sends the entire chat history upon connection
                        appendMessage(`<em>--- Chat History ---</em>`, 'system-message');
                        messagesDiv.innerHTML = ''; // Clear initial messages

                        if (message.messages && Array.isArray(message.messages)) {
                            message.messages.sort((a, b) => a.timestamp - b.timestamp);

                            message.messages.forEach(msg => {
                                if (msg.type === 'chat_message') {
                                    appendMessage(`<strong>${msg.sender}:</strong> ${msg.text}`);
                                }
                            });
                        }
                        appendMessage(`<em>--- End History (${message.messages ? message.messages.length : 0} messages) ---</em>`, 'system-message');

                        // History received, enable input
                        messageInput.disabled = false;
                        sendButton.disabled = false;
                        messageInput.focus();

                        break;

                    case 'player_joined':
                        const permanentUserId = message.permanent_user_id;
                        const playerName = message.name;
                        const totalPlayers = message.total_players;

                        // Update display for THIS player's ID and Name based on the joined message
                        if (permanentUserId && message.permanent_user_id === getPermanentUserIdFromSession(sessionId)) {
                            appendMessage(`<em>${playerName} joined the chat. Total players: ${totalPlayers}</em>`, 'system-message');
                        } else if (permanentUserId && message.permanent_user_id !== getPermanentUserIdFromSession(sessionId)) {
                            appendMessage(`<em>${playerName} joined the chat. Total players: ${totalPlayers}</em>`, 'system-message');
                        } else {
                            appendMessage(`<em>A player joined the chat. Total players: ${totalPlayers}</em>`, 'system-message');
                        }

                        // Update player list display if you have one

                        break;

                    case 'session_terminated':
                        alert(message.message || "Your session has been terminated.");
                        window.location.href = "/login";
                        break;

                    case 'player_left':
                        appendMessage(`<em>${message.name || message.permanent_user_id || message.player_id} left the chat. Remaining players: ${message.remaining_players}</em>`, 'system-message');
                        break;

                    case 'chat_message':
                        if (message.sender && message.text) {
                            appendMessage(`<strong>${message.sender}:</strong> ${message.text}`);
                        }
                        break;

                    case 'server_error':
                        // A specific error message from the server
                        appendMessage(`<strong>Error:</strong> ${message.message}`, 'system-message');
                        // Optional: Redirect to login if the error indicates session invalidity
                        // if (message.message.includes("session ID")) { setTimeout(() => window.location.href = '/', 3000); }
                        break;

                    case 'player_error':
                        // An error related to another player
                        appendMessage(`<strong>Warning:</strong> An error occurred with ${message.name || message.permanent_user_id || message.player_id}'s connection.`, 'system-message');
                        break;

                    case 'error': // Custom error type sent upon invalid session connection attempt (from backend WS endpoint)
                        appendMessage(`<strong>Connection Rejected:</strong> ${message.message}`, 'system-message'); // Changed message slightly
                        console.error("WebSocket Connection Error:", message.message);
                        // Redirect to login page after a short delay
                        setTimeout(() => { window.location.href = '/login'; }, 3000); // Redirect after 3 seconds
                        break;


                    default:
                        // Handle unknown message types
                        console.warn("Received message with unknown type:", message.type, message);
                        // Optional: Display unknown raw message
                        // appendMessage(`<em>Unknown message type received:</em> ${event.data}`, 'system-message');
                        break;
                }

            } catch (e) {
                console.error("Failed to parse message as JSON or process message:", e);
                appendMessage(`<em>Failed to process message:</em> ${event.data}`, 'system-message');
            }
        };

        websocket.onerror = function (event) {
            console.error("WebSocket error observed:", event);
            appendMessage("<em>WebSocket Error! Connection failed or interrupted.</em>", 'system-message');
            // Disable input on error
            messageInput.disabled = true;
            sendButton.disabled = true;
            playerNameDisplay.textContent = "Error";
            playerIdDisplay.textContent = "Error";
            // Basic auto-reconnect logic could go here
        };

        websocket.onclose = function (event) {
            console.log("WebSocket connection closed:", event.code, event.reason);
            let reason = event.reason || "Unknown reason";
            let closeMessage = `<em>WebSocket connection closed (${event.code}): ${reason}</em>`;

            // Check for specific close codes related to policy violation (like invalid session ID)
            if (event.code === 1008 || event.code === 4001) { // 1008 Policy Violation, 4001 Custom (if used by backend)
                closeMessage = `<em>Connection rejected: ${reason}. Please log in again.</em>`;
                // Redirect to login page immediately or after delay?
                // If we got code 1008 or 4001, it's likely an auth failure, so redirect is appropriate.
                // Let's rely on the 'error' message type for explicit backend errors/redirects.
                // For general close codes, maybe don't auto-redirect unless it's specifically for auth.
            } else if (event.code === 1000) { // Normal closure
                closeMessage = `<em>WebSocket connection closed: ${reason}</em>`;
            } 

            appendMessage(closeMessage, 'system-message');

            messageInput.disabled = true;
            sendButton.disabled = true;

        };
    }

    // --- Helper Function to update Player Info Display ---
    // We'll update the Player ID and Name display based on values passed from the backend template
    function updatePlayerInfoDisplay() {

        const templatePlayerId = document.getElementById('playerIdDisplay').textContent;
        const templatePlayerName = document.getElementById('playerNameDisplay').textContent;

        if (templatePlayerId && templatePlayerId !== 'Connecting...') {
            playerIdDisplay.textContent = templatePlayerId;
            playerNameDisplay.textContent = templatePlayerName;
        }

    }


    function getPermanentUserIdFromSession(sId) {
        return playerIdDisplay.textContent;
    }


    // --- UI Event Handlers ---
    sendButton.onclick = function () {
        sendMessage();
    };

    messageInput.addEventListener("keypress", function (event) {
        if (event.key === "Enter") {
            event.preventDefault();
            sendMessage();
        }
    });

    // --- Helper Function to Send Message ---
    function sendMessage() {
        const message = messageInput.value;
        if (message && websocket && websocket.readyState === WebSocket.OPEN && !messageInput.disabled) {
            // Send the plain text message. Server will process it as chat.
            websocket.send(message);
            messageInput.value = "";
        } else if (!message) {
            console.warn("Cannot send empty message.");
        }
        else {
            console.warn("WebSocket not connected, ready, or input disabled.");
            // appendMessage("<em>Cannot send message: WebSocket not connected or ready.</em>", 'system-message');
        }
    }

    // --- Helper Function to Append Message to UI ---
    function appendMessage(messageHtml, className = '') {
        const messageElement = document.createElement('p');
        messageElement.innerHTML = messageHtml;
        if (className) {
            messageElement.classList.add(className);
        }
        messagesDiv.appendChild(messageElement);
        // Scroll to bottom
        messagesDiv.scrollTop = messagesDiv.scrollHeight;
    }

    // --- Initialization ---

    // Update display with initial template values
    updatePlayerInfoDisplay(); // ADDED: Call this on startup

    // Connect to the WebSocket server using the obtained session ID
    // IMPORTANT: Connection only happens IF sessionId was successfully retrieved.
    if (sessionId) { // ADDED: Only attempt connection if sessionId is valid
        connectWebSocket();
    } else {
        // If sessionId was NOT found in URL, the code should have redirected already due to the check above.
        // This else block should theoretically not be reached if the redirect logic is correct.
        console.error("Fatal: Session ID not found, but redirect did not occur. Check logic.");
    }


    // --- Handle page closing ---
    window.onbeforeunload = function () {
        if (websocket && websocket.readyState === WebSocket.OPEN) {
            websocket.close(1000, "Client leaving page");
        }
    };
});